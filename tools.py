"""
tools.py — everything the agent can actually DO on your laptop.
Each function is exposed to Gemini as a tool. Responses are plain strings so the
model can read the result and continue its reasoning.
"""

import datetime
import os
import platform
import subprocess
import urllib.parse
import webbrowser

import config
import memory_learn
import store

MAX_OUTPUT = 4000


def _clip(s: str, n: int = MAX_OUTPUT) -> str:
    s = str(s)
    return s if len(s) <= n else s[:n] + f"\n...[truncated, {len(s)} chars total]"


# ------------------------------------------------------------------ reminders

def set_reminder(text: str, when: str, repeat: str = "none") -> str:
    """Create a reminder.

    Args:
        text: what to remind the user about.
        when: absolute local time in ISO format 'YYYY-MM-DDTHH:MM' (24h, no seconds).
        repeat: one of 'none', 'daily', 'weekly', 'weekdays', 'monthly'.
    """
    try:
        dt = datetime.datetime.fromisoformat(when.strip().replace(" ", "T"))
    except ValueError:
        return f"ERROR: '{when}' is not a valid ISO time. Use YYYY-MM-DDTHH:MM."
    if dt.year < 2000:
        return "ERROR: year looks wrong, use YYYY-MM-DDTHH:MM."
    rid = store.add_reminder(text, dt.replace(microsecond=0).isoformat(), repeat)
    nice = dt.strftime("%a %d %b %Y at %H:%M")
    extra = "" if repeat in ("none", "", None) else f" (repeats {repeat})"
    return f"Reminder #{rid} set for {nice}{extra}: {text}"


def list_reminders(include_completed: bool = False) -> str:
    """List reminders, soonest first."""
    rows = store.list_reminders(include_done=include_completed)
    if not rows:
        return "No reminders."
    out = []
    for r in rows:
        dt = datetime.datetime.fromisoformat(r["due_at"])
        stamp = dt.strftime("%a %d %b, %H:%M")
        flag = " [done]" if r["done"] else ""
        rep = "" if r["repeat"] == "none" else f" (repeats {r['repeat']})"
        out.append(f"#{r['id']} - {stamp}{rep}{flag} - {r['text']}")
    return "\n".join(out)


def complete_reminder(text: str) -> str:
    """Mark a reminder done, matching on any part of its text."""
    r = store.find_reminder(text)
    if not r:
        return f"No open reminder matching '{text}'."
    store.complete_reminder(r["id"])
    return f"Marked reminder #{r['id']} done: {r['text']}"


def cancel_reminder(text: str) -> str:
    """Delete a reminder, matching on any part of its text."""
    r = store.find_reminder(text)
    if not r:
        return f"No open reminder matching '{text}'."
    store.delete_reminder(r["id"])
    return f"Deleted reminder #{r['id']}: {r['text']}"


# ------------------------------------------------------------------ memory

def remember(fact: str) -> str:
    """Save a long-term fact about the user (names, preferences, contacts, projects)."""
    store.add_memory(fact)
    return f"Remembered: {fact}"


def recall(query: str = "") -> str:
    """Search saved memories. Empty query returns the most recent ones."""
    rows = store.search_memories(query) if query.strip() else store.list_memories(40)
    if not rows:
        return "Nothing stored about that."
    return "\n".join(f"#{r['id']} - {r['content']}" for r in rows)


# ------------------------------------------------------------------ web

def web_search(query: str) -> str:
    """Search the web. Returns a short list of results (title, link, snippet)."""
    import json as _json

    try:
        url = (
            "https://html.duckduckgo.com/html/?q="
            + urllib.parse.quote(query)
            + "&kl=ke-en"
        )
        html = subprocess.run(
            ["curl", "-sL", "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", url],
            capture_output=True,
            text=True,
            timeout=25,
        ).stdout
        import re

        results = re.findall(
            r'result__a"[^>]*href="(.*?)".*?>(.*?)</a>.*?result__snippet"[^>]*>(.*?)</a>',
            html,
            re.S,
        )
        items = []
        for href, title, snippet in results[:6]:
            clean = lambda s: re.sub(r"<[^>]+>", "", s).replace("&amp;", "&").strip()
            if "duckduckgo.com/l/?uddg=" in href:
                href = urllib.parse.unquote(href.split("uddg=")[-1].split("&")[0])
            items.append(f"- {clean(title)}\n  {href}\n  {clean(snippet)[:220]}")
        if not items:
            return "No results parsed (the search page layout may have changed)."
        return _clip("\n".join(items))
    except Exception as e:
        return f"Search failed: {e}"


def open_url(url: str) -> str:
    """Open a web page or search in the user's default browser."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url} in the browser."


# ------------------------------------------------------------------ system

def system_info() -> str:
    """Basic info about this machine, plus the current local time."""
    now = datetime.datetime.now()
    return (
        f"Local time: {now.strftime('%A %d %B %Y, %H:%M')} ({now.tzname()})\n"
        f"OS: {platform.system()} {platform.release()} ({platform.version()})\n"
        f"Machine: {platform.machine()} | Host: {platform.node()}\n"
        f"Python: {platform.python_version()} | User home: {os.path.expanduser('~')}"
    )


def list_files(folder: str = "") -> str:
    """List files in a folder (default: the agent's own files folder)."""
    cfg = config.load()
    if not cfg.get("allow_files", True):
        return "File access is switched off in Settings."
    path = folder.strip() or cfg["files_dir"]
    path = os.path.expanduser(path)
    if not os.path.isdir(path):
        return f"Not a folder: {path}"
    try:
        names = sorted(os.listdir(path))[:120]
        rows = []
        for n in names:
            p = os.path.join(path, n)
            size = os.path.getsize(p) if os.path.isfile(p) else 0
            rows.append(f"{'DIR ' if os.path.isdir(p) else '    '}{n}  ({size} B)")
        return f"Contents of {path}:\n" + ("\n".join(rows) or "(empty)")
    except Exception as e:
        return f"Could not list {path}: {e}"


def read_file(path: str) -> str:
    """Read a text file from disk (first 4000 characters)."""
    cfg = config.load()
    if not cfg.get("allow_files", True):
        return "File access is switched off in Settings."
    path = os.path.expanduser(path.strip())
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return _clip(f.read())
    except Exception as e:
        return f"Could not read {path}: {e}"


def write_file(filename: str, content: str) -> str:
    """Create or append to a text file inside the agent's files folder."""
    cfg = config.load()
    if not cfg.get("allow_files", True):
        return "File access is switched off in Settings."
    folder = cfg["files_dir"]
    os.makedirs(folder, exist_ok=True)
    safe = os.path.basename(filename.strip()) or "note.txt"
    path = os.path.join(folder, safe)
    try:
        mode = "a" if os.path.exists(path) else "w"
        with open(path, mode, encoding="utf-8") as f:
            if mode == "a":
                f.write("\n")
            f.write(content)
        return f"Saved to {path} ({os.path.getsize(path)} bytes)."
    except Exception as e:
        return f"Could not write {path}: {e}"


def run_command(command: str) -> str:
    """Run a shell command on the laptop and return its output. Requires the
    'Allow shell commands' switch to be ON in Settings."""
    cfg = config.load()
    if not cfg.get("allow_commands"):
        return (
            "Blocked: shell commands are disabled. Ask the user to switch on "
            "'Allow shell commands' in Settings if they want this."
        )
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.path.expanduser("~"),
        )
        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        return _clip(f"exit code {proc.returncode}\n{out.strip() or '(no output)'}")
    except subprocess.TimeoutExpired:
        return "Command timed out after 60s."
    except Exception as e:
        return f"Command failed: {e}"


def type_text(text: str) -> str:
    """Type text into whatever window is focused (and can optionally press Enter).
    Requires the 'Allow keyboard control' switch to be ON."""
    cfg = config.load()
    if not cfg.get("allow_keyboard"):
        return (
            "Blocked: keyboard control is disabled. Ask the user to switch on "
            "'Allow keyboard control' in Settings."
        )
    try:
        import pyautogui
        import time

        time.sleep(0.6)  # give the user a moment to focus the target window
        pyautogui.typewrite(text, interval=0.01)
        return "Typed the text into the focused window."
    except Exception as e:
        return f"Typing failed ({e}). Is pyautogui installed?"



# ------------------------------------------------------------------ apps

# Sensible starting points; whatever the user teaches overrides these.
DEFAULT_APPS = {
    "browser": ["chrome", "msedge", "firefox", "brave"],
    "music": ["spotify", "ms-windows-store://music", "wmplayer"],
    "notepad": ["notepad"],
    "terminal": ["wt", "powershell", "cmd"],
    "calculator": ["calc"],
    "explorer": ["explorer"],
    "camera": ["microsoft.windows.camera:"],
    "settings": ["ms-settings:"],
    "mail": ["outlook", "ms-outlook:"],
    "word": ["winword"],
    "excel": ["excel"],
    "powerpoint": ["powerpnt"],
}

_ALIAS = {
    "chrome": ["chrome", "google chrome", "msedge"],
    "edge": ["msedge"], "firefox": ["firefox"], "brave": ["brave"],
    "spotify": ["spotify"],
    "notepad": ["notepad"], "calculator": ["calc"], "calc": ["calc"],
    "explorer": ["explorer"], "files": ["explorer"],
    "word": ["winword"], "excel": ["excel"], "powerpoint": ["powerpnt"],
    "vscode": ["code"], "code": ["code"], "terminal": ["wt", "powershell"],
    "cmd": ["cmd"], "powershell": ["powershell"],
    "settings": ["ms-settings:"], "camera": ["microsoft.windows.camera:"],
    "whatsapp": ["whatsapp:"], "telegram": ["tg:"], "phone": ["ms-phone:"],
    "mail": ["ms-outlook:"], "outlook": ["ms-outlook:"],
    "vlc": ["vlc"], "youtube": ["https://youtube.com"],
}


_APP_PATHS = [
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
    r"%LocalAppData%\Programs\Microsoft VS Code\Code.exe",
    r"%AppData%\Spotify\Spotify.exe",
    r"%LocalAppData%\Microsoft\Teams\current\Teams.exe",
    r"%ProgramFiles%\Microsoft Office\root\Office16\WINWORD.EXE",
    r"%ProgramFiles%\Microsoft Office\root\Office16\EXCEL.EXE",
]

_WIN_ALIASES = {
    "chrome": ["chrome", "chrome.exe", "google chrome", "google-chrome"],
    "msedge": ["msedge", "edge", "microsoft edge", "msedge.exe"],
    "firefox": ["firefox", "mozilla firefox"],
    "brave": ["brave", "brave browser"],
    "spotify": ["spotify", "spotify.exe"],
    "notepad": ["notepad", "notepad.exe"],
    "calculator": ["calc", "calc.exe", "calculator"],
    "explorer": ["explorer", "explorer.exe", "file explorer"],
    "vscode": ["code", "vscode", "visual studio code"],
    "word": ["winword", "word", "microsoft word"],
    "excel": ["excel", "microsoft excel"],
    "whatsapp": ["whatsapp"],
    "telegram": ["telegram"],
    "settings": ["ms-settings:", "settings", "windows settings"],
    "task manager": ["taskmgr", "taskmanager", "task manager"],
    "paint": ["mspaint", "paint"],
    "photos": ["ms-photos:", "photos"],
    "camera": ["microsoft.windows.camera:", "camera"],
    "store": ["ms-windows-store:", "store", "microsoft store"],
}


def _expand(path: str) -> str:
    import os

    return os.path.expandvars(path)


def _find_on_windows(name: str):
    """Return a real path for a Windows app, or None. Silent and fast."""
    import os
    import shutil

    low = (name or "").strip().lower()
    if not low:
        return None

    # 1. anything on PATH (chrome.exe, notepad.exe, code.cmd…)
    for cand in dict.fromkeys([name] + _WIN_ALIASES.get(low, [])):
        if cand.lower().endswith((".exe", ".cmd", ".bat")):
            hit = shutil.which(cand)
            if hit:
                return hit
    hits = shutil.which(low)
    if hits:
        return hits

    # 2. the usual install locations
    wanted = _WIN_ALIASES.get(low, [low])
    for path in _APP_PATHS:
        expanded = _expand(path)
        base = os.path.basename(expanded).lower()
        if base.replace(".exe", "") in [w.replace(".exe", "") for w in wanted] \
                or low in expanded.lower():
            if os.path.exists(expanded):
                return expanded

    # 3. Start Menu shortcuts (.lnk) — this is how Store apps get found
    roots = []
    for var in ("ProgramData", "AppData"):
        val = os.environ.get(var)
        if val:
            roots.append(os.path.join(val, "Microsoft", "Windows", "Start Menu",
                                      "Programs"))
    for root in roots:
        try:
            for dirpath, _dirs, files in os.walk(root):
                for f in files:
                    if not f.lower().endswith(".lnk"):
                        continue
                    stem = f[:-4].lower()
                    if low == stem or low in stem or stem in low:
                        return os.path.join(dirpath, f)
        except Exception:
            continue
    return None


def _launch(cmd: str) -> bool:
    """Launch one thing. Returns True only if the OS actually accepted it."""
    import platform
    import subprocess

    if not cmd or not str(cmd).strip():
        return False
    cmd = str(cmd).strip()

    try:
        if platform.system() == "Windows":
            # a URL always goes through the default browser
            if cmd.lower().startswith(("http://", "https://")):
                import webbrowser

                return bool(webbrowser.open(cmd))

            # protocol handlers (ms-settings:, microsoft.windows.camera: …)
            if cmd.endswith(":") or (":" in cmd and not cmd[1:3] == ":\\"
                                     and not os.path.exists(cmd)):
                try:
                    os.startfile(cmd)  # type: ignore[attr-defined]
                    return True
                except Exception:
                    pass

            resolved = _find_on_windows(cmd) if not os.path.exists(cmd) else cmd

            # a shell built-in (calc, notepad, start-menu lnk, store app alias)
            for target in dict.fromkeys([resolved, cmd]):
                if not target:
                    continue
                try:
                    os.startfile(target)  # type: ignore[attr-defined]
                    return True
                except OSError:
                    pass
                except Exception:
                    pass

            # absolute fallback: cmd's own `start`, which knows App Paths
            try:
                proc = subprocess.Popen(
                    ['cmd', '/c', 'start', '', cmd],
                    shell=False,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                # `start` returns immediately; a 0/None code means it was accepted
                return proc.returncode in (0, None)
            except Exception:
                return False

        if platform.system() == "Darwin":
            subprocess.Popen(["open", "-a", cmd])
            return True

        # Linux: only claim success when there is something real to open
        import shutil

        if shutil.which(cmd.split()[0]):
            subprocess.Popen(cmd.split())
            return True
        if os.path.exists(cmd):
            subprocess.Popen(["xdg-open", cmd])
            return True
        return False
    except Exception:
        return False


def intent_of(app: str, defaults: dict = None) -> str:
    """What purpose does this app serve? Used so routes are remembered by intent."""
    low = (app or "").lower()
    for intent, target in (defaults or {}).items():
        if (target or "").lower() == low:
            return intent
    if any(k in low for k in ("chrome", "edge", "firefox", "brave", "browser")):
        return "browser"
    if any(k in low for k in ("spotify", "music", "itunes", "groove")):
        return "music"
    return low.split(".")[0].split("\\")[-1][:32] or "app"


def open_preferred(what: str) -> str:
    """Open the app or site the user means by 'browser', 'music', 'chrome'…"""
    cfg = config.load()
    if not (cfg.get("allow_apps", True) or cfg.get("allow_commands")):
        return "Blocked: launching apps is switched off in Settings."
    key = (what or "").strip().lower()

    # 1. what has the user taught us?
    learned = memory_learn.best_route(key)
    candidates = []
    if learned:
        candidates.append(learned)

    # 2. their configured default for this purpose
    defaults = cfg.get("app_defaults") or {}
    if defaults.get(key):
        candidates.append(defaults[key])

    # 3. a known alias, then the name as given
    candidates += _ALIAS.get(key, [])
    candidates.append(what)

    tried = []
    for cand in dict.fromkeys([c for c in candidates if c]):
        tried.append(cand)
        if _launch(cand):
            memory_learn.learn_route(key, cand)
            return "Opened %s (via %s)." % (key, cand)
    return ("Couldn't launch %s. Tried: %s. Tell me the exact app name, or set it in "
            "Settings → App defaults." % (key, ", ".join(tried)))


def open_website(url: str, purpose: str = "browser") -> str:
    """Always use the user's preferred browser when one is known."""
    cfg = config.load()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    learned = memory_learn.best_route(purpose)
    if learned and cfg.get("allow_commands"):
        # chrome/edge/firefox accept a URL argument
        import platform
        import subprocess

        exe = {"chrome": "chrome", "edge": "msedge", "msedge": "msedge",
               "firefox": "firefox", "brave": "brave"}.get(learned.lower())
        if exe and platform.system() == "Windows":
            try:
                subprocess.Popen('start "" %s "%s"' % (exe, url), shell=True)
                return "Opened %s in %s." % (url, learned)
            except Exception:
                pass
    import webbrowser

    webbrowser.open(url)
    return "Opened %s in the default browser." % url


def play_music(query: str = "") -> str:
    """Open the user's music app, or search a song on it."""
    cfg = config.load()
    app = memory_learn.best_route("music") or (cfg.get("app_defaults") or {}).get("music")
    if query:
        import urllib.parse

        # Spotify/YouTube both accept search URLs; safest universal route:
        url = "https://open.spotify.com/search/" + urllib.parse.quote(query)
        if app and "spotify" not in (app or "").lower():
            url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
        import webbrowser

        webbrowser.open(url)
        return "Searching for %r in your music app." % query
    return open_preferred("music")


# ------------------------------------------------------------------ learning

def learn_skill(name: str, steps: str, trigger: str = "") -> str:
    """Save a repeatable procedure so it can be reused later."""
    if not (config.load().get("allow_learning", True)):
        return "Blocked: learning is switched off in Settings."
    saved = memory_learn.save_skill(name, steps, trigger)
    if not saved:
        return "I need a name for that skill."
    return "Learned skill '%s' (%s). I'll reuse it next time." % (saved, steps[:80])


def list_skills() -> str:
    rows = memory_learn.list_skills()
    if not rows:
        return "No skills learned yet."
    return "\n".join("#%d %s — used %dx — %s" % (r["id"], r["name"], r["uses"],
                                                 r["steps"][:90]) for r in rows)


def use_skill(name: str) -> str:
    skill = memory_learn.find_skill(name)
    if not skill:
        return "No skill matches '%s'." % name
    memory_learn.use_skill(skill["name"])
    return "Skill '%s': %s" % (skill["name"], skill["steps"])


def teach_me(key: str, value: str) -> str:
    """Record a fact about the user in their profile."""
    memory_learn.set_profile(key, value)
    return "Noted — %s: %s" % (key, value)


def who_am_i() -> str:
    prof = memory_learn.get_profile()
    if not prof:
        return ("I don't know much yet. Say things like 'remember my name is ...' "
                "or use Settings → Teach about me.")
    return "\n".join("%s: %s" % (k.replace("_", " "), v) for k, v in prof.items())

# ------------------------------------------------------------------ screen

def read_screen(max_chars: int = 2500) -> str:
    """Read the text currently visible on the user's screen (OCR)."""
    cfg = config.load()
    if not cfg.get("allow_screen"):
        return ("Blocked: screen reading is switched off. Ask the user to enable "
                "'Let the agent read my screen' in Settings.")
    try:
        import screen
        text = screen.ocr_text(max_chars)
    except Exception as e:
        return str(e)
    if not text:
        return "I captured the screen but found no readable text on it."
    return "Text visible on screen:\n" + text


def take_screenshot() -> str:
    """Save a screenshot to the agent's files folder and report where it is."""
    cfg = config.load()
    if not cfg.get("allow_screen"):
        return "Blocked: screen capture is switched off in Settings."
    try:
        import shutil
        import screen

        src = screen.screenshot()
        folder = cfg["files_dir"]
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(folder, "screen-%s.png" % stamp)
        shutil.copyfile(src, dest)
        return "Screenshot saved to %s" % dest
    except Exception as e:
        return str(e)


# ------------------------------------------------------------------ messages

def send_email(to: str, subject: str, body: str) -> str:
    """Email the user (or anyone) through their own Gmail account.

    Needs a Gmail App Password in Settings - a normal password will not work.
    """
    import smtplib
    from email.message import EmailMessage

    cfg = config.load()
    if not cfg.get("allow_email"):
        return "Blocked: email is switched off in Settings."
    addr = (cfg.get("email_address") or "").strip()
    pwd = (cfg.get("email_app_password") or "").strip()
    if not addr or not pwd:
        return ("Email isn't configured. The user must add their Gmail address and a "
                "Google App Password in Settings (myaccount.google.com/apppasswords).")
    to = (to or addr).strip()
    try:
        msg = EmailMessage()
        msg["From"] = addr
        msg["To"] = to
        msg["Subject"] = subject or "A note from Pocket"
        msg.set_content(body or "")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=25) as s:
            s.login(addr, pwd)
            s.send_message(msg)
        return "Email sent to %s (subject: %s)." % (to, subject)
    except Exception as e:
        return ("Email failed: %s. If it mentions authentication, the App Password "
                "is wrong - create a new one at myaccount.google.com/apppasswords."
                % e)


def email_me(subject: str, body: str) -> str:
    """Email the user themselves - good for a reminder they might miss on screen."""
    return send_email("", subject, body)


def send_sms(number: str, message: str) -> str:
    """Send an SMS through the user's phone via an Android phone paired to this PC
    (Phone Link / KDE Connect style relay), or report what's missing."""
    cfg = config.load()
    if not cfg.get("allow_sms"):
        return "Blocked: SMS is switched off in Settings."
    import platform
    import subprocess
    import urllib.parse

    number = (number or "").strip()
    if not number:
        return "I need a phone number to text."
    if platform.system() == "Windows":
        # Windows has no public SMS API; hand off to the Phone Link dialog.
        try:
            subprocess.Popen('start "" "ms-phone:"', shell=True)
            return ("Opened Phone Link. Windows doesn't allow apps to send SMS "
                    "silently, so I opened the app - the message text is ready to "
                    "paste: %r" % message[:120])
        except Exception as e:
            return "Couldn't open Phone Link: %s" % e
    return "SMS sending isn't supported on this platform."


def whatsapp_message(number: str, message: str, send: bool = False) -> str:
    """Open a WhatsApp chat with the message pre-filled.

    WhatsApp has no official way to send silently; with send=True Pocket types
    the final Enter via keyboard control, otherwise the user just presses send.
    """
    import urllib.parse
    import webbrowser

    cfg = config.load()
    digits = "".join(ch for ch in (number or "") if ch.isdigit() or ch == "+")
    if not digits:
        return "I need a phone number with country code, e.g. +254712345678."
    url = "https://wa.me/%s?text=%s" % (digits.lstrip("+"),
                                        urllib.parse.quote(message or ""))
    webbrowser.open(url)
    if send and cfg.get("allow_keyboard") and cfg.get("allow_commands"):
        try:
            import time

            import pyautogui

            time.sleep(5)          # let the chat load
            pyautogui.press("enter")
            return "Opened WhatsApp and pressed send."
        except Exception as e:
            return "Opened WhatsApp with the message ready; couldn't auto-send (%s)." % e
    return "Opened WhatsApp with the message pre-filled - press Enter to send."


def phone_call(number: str) -> str:
    """Start a phone call. Real calling needs a service (Twilio); otherwise this
    opens the dialler/Phone Link ready for the user to tap call."""
    cfg = config.load()
    if not cfg.get("allow_calls"):
        return "Blocked: calling is switched off in Settings."
    digits = "".join(ch for ch in (number or "") if ch.isdigit() or ch == "+")
    if not digits:
        return "I need a phone number to call."
    tw_sid = (cfg.get("twilio_sid") or "").strip()
    tw_tok = (cfg.get("twilio_token") or "").strip()
    tw_from = (cfg.get("twilio_from") or "").strip()
    if tw_sid and tw_tok and tw_from:
        try:
            import base64
            import urllib.parse
            import urllib.request

            data = urllib.parse.urlencode({"To": digits, "From": tw_from,
                                           "Url": "http://demo.twilio.com/docs/voice.xml"})
            req = urllib.request.Request(
                "https://api.twilio.com/2010-04-01/Accounts/%s/Calls.json" % tw_sid,
                data=data.encode(),
                headers={"Authorization": "Basic " + base64.b64encode(
                    ("%s:%s" % (tw_sid, tw_tok)).encode()).decode()},
            )
            with urllib.request.urlopen(req, timeout=25) as r:
                if r.status in (200, 201):
                    return "Calling %s now." % digits
            return "Twilio refused the call."
        except Exception as e:
            return "Twilio call failed: %s" % e
    for target in ("ms-phone:", "tel:%s" % digits):
        try:
            os.startfile(target)  # type: ignore[attr-defined]
            return ("Opened the phone dialler for %s - tap call to connect. (For real "
                    "one-click calls, add Twilio details in Settings.)" % digits)
        except Exception:
            continue
    return "Couldn't open a dialler on this machine."


def check_messages() -> str:
    """Report anything waiting: opens Phone Link and reads visible message text."""
    cfg = config.load()
    if not cfg.get("allow_screen"):
        return "Blocked: reading messages needs screen access switched on."
    try:
        os.startfile("ms-phone:")  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        import time

        import screen

        time.sleep(3)
        text = screen.ocr_text(1500)
        return ("Opened Phone Link and read the screen. Visible text:\n" + text
                if text else "Opened Phone Link, but I couldn't read any message text.")
    except Exception as e:
        return "Opened Phone Link, but reading it failed: %s" % e


# ------------------------------------------------------------------ deep links

def open_app(name: str) -> str:
    """Launch an application, file or folder using the OS default."""
    cfg = config.load()
    if not (cfg.get("allow_apps", True) or cfg.get("allow_commands")):
        return "Blocked: launching apps is switched off in Settings."
    key = (name or "").strip()
    if not key:
        return "Which app should I open?"
    low = key.lower()

    # "the browser" / "my music" should follow the configured default
    defaults = cfg.get("app_defaults") or {}
    for intent, app in defaults.items():
        if intent in low and app:
            key = app
            break

    if _launch(key):
        memory_learn.learn_route(intent_of(key, defaults), key)
        return "Opened %s." % key
    tried = key
    return ("Couldn't launch %s. I tried PATH, Program Files and the Start Menu. "
            "Tell me the exact name shown in the Start Menu, or set it in "
            "Settings → Default apps. (Tried: %s)" % (key, tried))


# ------------------------------------------------------------------ schemas
# Explicit JSON schemas (newer google-genai versions require these rather than
# raw Python callables). Descriptions are what the model reads, so they matter.
SPECS = {
    "set_reminder": {
        "description": "Create a reminder that pops up on the user's screen at a "
                       "specific local time. Convert relative times to an absolute "
                       "timestamp first.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "text": {"type": "STRING",
                         "description": "What to remind them about, short and clear."},
                "when": {"type": "STRING",
                         "description": "Local time in ISO 24h format YYYY-MM-DDTHH:MM"},
                "repeat": {"type": "STRING",
                           "description": "Repeat pattern; use 'none' for one-off.",
                           "enum": ["none", "daily", "weekdays", "weekly", "monthly"]},
            },
            "required": ["text", "when"],
        },
    },
    "list_reminders": {
        "description": "List the user's reminders, soonest first.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "include_completed": {"type": "BOOLEAN",
                                      "description": "Include reminders already done."},
            },
        },
    },
    "complete_reminder": {
        "description": "Mark a reminder as done. Matches on any part of its text.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"text": {"type": "STRING",
                                    "description": "Words from the reminder to match."}},
            "required": ["text"],
        },
    },
    "cancel_reminder": {
        "description": "Delete a reminder entirely. Matches on any part of its text.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"text": {"type": "STRING",
                                    "description": "Words from the reminder to match."}},
            "required": ["text"],
        },
    },
    "remember": {
        "description": "Save one durable fact about the user to long-term memory. "
                       "Call this whenever they mention something worth keeping: "
                       "names, contacts, cities, jobs, preferences, projects.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"fact": {"type": "STRING",
                                    "description": "A standalone sentence, e.g. "
                                                   "'The user's sister is Achieng.'"}},
            "required": ["fact"],
        },
    },
    "recall": {
        "description": "Search long-term memory for facts about the user.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"query": {"type": "STRING",
                                     "description": "Keyword to search; empty returns "
                                                    "the most recent facts."}},
        },
    },
    "web_search": {
        "description": "Search the web and get back result titles, links and snippets. "
                       "Use for current facts, prices, news, how-to lookups.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"query": {"type": "STRING", "description": "Search terms."}},
            "required": ["query"],
        },
    },
    "open_url": {
        "description": "Open a website in the user's default browser.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"url": {"type": "STRING",
                                   "description": "Full URL or bare domain."}},
            "required": ["url"],
        },
    },
    "system_info": {
        "description": "Get the current local date/time and basic info about this "
                       "computer. Use it to check the time before setting reminders.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    "list_files": {
        "description": "List files in a folder. Defaults to the agent's files folder.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"folder": {"type": "STRING",
                                      "description": "Folder path; empty for the default."}},
        },
    },
    "read_file": {
        "description": "Read a text file from disk.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"path": {"type": "STRING", "description": "File path."}},
            "required": ["path"],
        },
    },
    "write_file": {
        "description": "Create or append to a text file inside the agent's files folder. "
                       "Use for notes, drafts, lists.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "filename": {"type": "STRING", "description": "File name, e.g. notes.txt"},
                "content": {"type": "STRING", "description": "Text to write."},
            },
            "required": ["filename", "content"],
        },
    },
    "open_preferred": {
        "description": "Open an app or site the way the user likes it. Use for "
                       "'open chrome', 'open my browser', 'play music', 'open word', "
                       "'open whatsapp'. Pocket remembers which app worked last time.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "what": {"type": "STRING",
                         "description": "Purpose or app name: browser, music, chrome, "
                                        "notepad, terminal, mail, whatsapp…"},
            },
            "required": ["what"],
        },
    },
    "play_music": {
        "description": "Open the user's music app, optionally searching for a song.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"query": {"type": "STRING",
                                     "description": "Song or artist, or empty to just "
                                                    "open the app."}},
        },
    },
    "open_website": {
        "description": "Open a website in the user's preferred browser.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING"},
                "purpose": {"type": "STRING",
                            "description": "Usually 'browser'."},
            },
            "required": ["url"],
        },
    },
    "learn_skill": {
        "description": "Save a repeatable procedure after doing something non-trivial, "
                       "so it can be reused and improved next time. Name it clearly "
                       "(e.g. 'send weekly report').",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING", "description": "Short skill name."},
                "steps": {"type": "STRING",
                          "description": "The ordered steps that worked."},
                "trigger": {"type": "STRING",
                            "description": "Words the user would say to invoke it."},
            },
            "required": ["name", "steps"],
        },
    },
    "list_skills": {
        "description": "List skills learned so far.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    "use_skill": {
        "description": "Fetch the steps of a learned skill by name before doing it.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING"}},
            "required": ["name"],
        },
    },
    "teach_me": {
        "description": "Store a fact about the user in their profile: name, city, job, "
                       "preferred browser, contacts, how they like things done.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "key": {"type": "STRING",
                        "description": "Short label, e.g. 'name', 'city', "
                                       "'preferred_browser'."},
                "value": {"type": "STRING"},
            },
            "required": ["key", "value"],
        },
    },
    "who_am_i": {
        "description": "Read back everything known about the user.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    "read_screen": {
        "description": "Read the text currently visible on the user's screen (OCR). "
                       "Use when they ask what's on screen, or to read a message, "
                       "email or page they are looking at.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"max_chars": {"type": "INTEGER",
                                         "description": "How much text to return."}},
        },
    },
    "take_screenshot": {
        "description": "Save a screenshot of the current screen to the files folder.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    "email_me": {
        "description": "Send the user an email. Use this to remind them of something "
                       "they might miss, e.g. a summary or a deadline.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "subject": {"type": "STRING", "description": "Email subject."},
                "body": {"type": "STRING", "description": "Email body."},
            },
            "required": ["subject", "body"],
        },
    },
    "send_email": {
        "description": "Send an email to a specific address through the user's Gmail.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "to": {"type": "STRING", "description": "Recipient address."},
                "subject": {"type": "STRING"},
                "body": {"type": "STRING"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    "whatsapp_message": {
        "description": "Open WhatsApp with a message ready for a number. Drafts the "
                       "text first; never invent facts.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "number": {"type": "STRING",
                           "description": "Phone number with country code."},
                "message": {"type": "STRING", "description": "Message text."},
                "send": {"type": "BOOLEAN",
                         "description": "Press send automatically if allowed."},
            },
            "required": ["number", "message"],
        },
    },
    "send_sms": {
        "description": "Send a text message via the user's phone (Windows Phone Link).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "number": {"type": "STRING"},
                "message": {"type": "STRING"},
            },
            "required": ["number", "message"],
        },
    },
    "phone_call": {
        "description": "Place a phone call to a number.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"number": {"type": "STRING"}},
            "required": ["number"],
        },
    },
    "check_messages": {
        "description": "Open the user's phone messages on this PC and read what's "
                       "visible, so you can summarise or reply to them.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    "open_app": {
        "description": "Launch an app or protocol: 'notepad', 'ms-phone:', "
                       "'whatsapp:', 'spotify:', 'mailto:a@b.com'.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING",
                                    "description": "App, path or protocol."}},
            "required": ["name"],
        },
    },
    "run_command": {
        "description": "Run a shell command on the user's laptop and return its output. "
                       "Only available if the user switched shell access on.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"command": {"type": "STRING",
                                       "description": "The command line to run."}},
            "required": ["command"],
        },
    },
    "type_text": {
        "description": "Type text into whatever window currently has focus. Only "
                       "available if the user switched keyboard control on.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"text": {"type": "STRING", "description": "Text to type."}},
            "required": ["text"],
        },
    },
    "open_app": {
        "description": "Launch an application, file or folder using the OS default.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"name": {"type": "STRING",
                                    "description": "App or path to launch."}},
            "required": ["name"],
        },
    },
}

TOOL_FUNCS = {
    "set_reminder": set_reminder,
    "list_reminders": list_reminders,
    "complete_reminder": complete_reminder,
    "cancel_reminder": cancel_reminder,
    "remember": remember,
    "recall": recall,
    "web_search": web_search,
    "open_url": open_url,
    "system_info": system_info,
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "run_command": run_command,
    "type_text": type_text,
    "open_app": open_app,
    "open_preferred": open_preferred,
    "open_website": open_website,
    "play_music": play_music,
    "learn_skill": learn_skill,
    "list_skills": list_skills,
    "use_skill": use_skill,
    "teach_me": teach_me,
    "who_am_i": who_am_i,
    "read_screen": read_screen,
    "take_screenshot": take_screenshot,
    "email_me": email_me,
    "send_email": send_email,
    "whatsapp_message": whatsapp_message,
    "send_sms": send_sms,
    "phone_call": phone_call,
    "check_messages": check_messages,
}


def enabled_names(cfg: dict):
    """Only expose tools the user has allowed. Some tools are honestly gated by
    what an OS permits, so they always report what they can and cannot do."""
    names = [
        "set_reminder", "list_reminders", "complete_reminder", "cancel_reminder",
        "remember", "recall", "web_search", "open_url", "system_info",
    ]
    if cfg.get("allow_files", True):
        names += ["list_files", "read_file", "write_file"]
    if cfg.get("allow_learning", True):
        names += ["learn_skill", "list_skills", "use_skill", "teach_me", "who_am_i"]
    if cfg.get("allow_commands"):
        names += ["run_command", "open_app", "whatsapp_message"]
    if cfg.get("allow_apps", True):
        names += ["open_preferred", "open_website", "play_music"]
    if cfg.get("allow_keyboard") and cfg.get("allow_commands"):
        names.append("type_text")
    if cfg.get("allow_screen"):
        names += ["read_screen", "take_screenshot", "check_messages"]
    if cfg.get("allow_email"):
        names += ["email_me", "send_email"]
    if cfg.get("allow_sms"):
        names.append("send_sms")
    if cfg.get("allow_calls"):
        names.append("phone_call")
    return names


def declarations(cfg: dict):
    """FunctionDeclaration dicts for the Gemini request."""
    out = []
    for n in enabled_names(cfg):
        spec = dict(SPECS[n])
        spec["name"] = n
        out.append(spec)
    return out
