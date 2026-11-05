# Pocket — your own AI agent, on your laptop

A desktop AI agent that lives on your Windows machine. You type or paste things into
one small window and it **actually does them**: sets reminders that pop up at the
right minute, drafts replies you can send as-is, remembers facts about you, searches
the web, and (if you allow it) opens apps, reads files and types into other windows.

It runs on Google's **free** Gemini API — no subscription, no credit card.

---

## Install (10 minutes, once)

1. **Install Python** — https://www.python.org/downloads/
   On the first screen of the installer, tick **“Add python.exe to PATH”**. This is the
   step people miss; without it nothing else works.

2. **Copy this `pocket-agent` folder** onto your laptop — for example to
   `C:\Users\YourName\pocket-agent`.

3. **Double-click `setup.bat`.** It creates a private `.venv` folder and installs four
   packages. Takes about a minute and needs internet.

4. **Get your free key** — open https://aistudio.google.com/apikey, sign in with a
   Google account, click **Create API key**, and copy it (it starts with `AIza…`).

5. **Double-click `start.bat`.** The window opens. Go to **Settings**, paste the key,
   add your name, press **Test connection** (you should see a green "Connection OK"),
   then **Save settings**.

### The "Create new key / choose a project" screen

When you click **Create API key**, Google asks which Google Cloud project the key should
belong to. Three options appear:

| Option | What it means | Choose it? |
|---|---|---|
| **Default Gemini project** | The project AI Studio auto-created for you when you accepted the terms. It is the one currently showing the restriction. | Not if that project is blocked |
| **Import project** | Pulls in an existing Google Cloud project (e.g. a project you made in console). Only useful if you already have one with billing set up. | No |
| **Create project** | Makes a brand-new Google Cloud project just for this. | **Yes — this is the one that clears a project-level block** |

Order that works:

1. Finish **age verification**, **phone verification** and turn **2-Step Verification ON**
   on the Google account first. A new project created before this tends to get flagged too.
2. Come back and choose **Create project**, name it something like `pocket-agent`.
3. Create the key in that new project and paste it into Pocket.
4. Press **Settings → Diagnose key** to confirm before you start using it.

You did not break anything by picking the wrong one — the choice isn't permanent. Delete
the key, make a new one in a different project, done.

### “Model not found / that model has been retired”

Google retires Gemini model IDs every few months — `gemini-2.5-flash` and
`gemini-2.5-flash-lite` were both shut down on **20 October 2026**. Any app that
hard-codes a model ID breaks on those dates. Pocket doesn't:

- **Discover** — it asks Google which text models your key can actually use. Press
  **Settings → Find models** to see the list and pick one.
- **Self-heal** — if a model disappears mid-conversation, Pocket notices, looks up the
  live catalogue, switches to the best available model, saves it and carries on without
  bothering you. You'll see a one-line note in the status bar.
- **Prefer sensibly** — newest GA Flash models first, previews and experimental IDs
  demoted, and non-chat models (image, TTS, embedding, Live, Gemma) filtered out.

As of now the best free choice is **`gemini-3.8-flash`** (GA 2 Sept 2026, supported into
late 2027). It's the default. Leave **“Always use the best available model”** ticked and
you won't have to think about this again.

### My key starts with `AQ.`, not `AIza`

That's correct and expected. Google replaced the old `AIza…` **Standard keys** with
`AQ.Ab…` **Auth keys** during 2026; AI Studio now issues the new format to everyone.
Older guides — and older versions of this app — wrongly expected `AIza`.

Pocket accepts **both** formats. It checks the key by asking Google, never by looking at
the first few characters. If your key is `AQ.` and something still says "invalid key",
the app is out of date, so grab the current `Pocket-Agent.zip`.

Two things worth knowing:

- **Native endpoint works.** `AQ.` keys authenticate via the `x-goog-api-key` header on
  `generativelanguage.googleapis.com`. That's what Pocket uses, and it's why the app
  talks to the native API rather than any OpenAI-style compatibility layer.
- **A few brand-new keys hit a Google-side bug** — `401 UNAUTHENTICATED` /
  `ACCESS_TOKEN_TYPE_UNSUPPORTED` — where the key is fine but Google's backend rejects
  its token type. Pocket handles this two ways: it retries the same turn over plain
  REST, and **Diagnose key** includes a `RAW REST CHECK` that proves whether the fault is
  the SDK path or Google itself. If the raw check also fails, wait a few hours, or create
  a key in **Google Cloud Console → APIs & Services → Credentials → Create credentials →
  API key**, which still issues the older `AIza` format that isn't affected.

### Which credential do I need? Only the API key.

| From the Google Cloud console | Do you need it? |
|---|---|
| **API key** — starts with `AIza…`, from https://aistudio.google.com/apikey | **Yes.** This is the only thing the app needs. |
| **Project ID** — e.g. `charismatic-age-513716-e7` | **No.** The app never uses it. It's just the Google Cloud container that key belongs to, and it's not something you need to remember or type. |
| Project number, OAuth client ID, service-account JSON | No. Not used. |

If "Test connection" says *Connection OK*, you're done — regardless of which project
the key came from.

That's it. Use `start.bat` from now on. If it ever fails to open, use
`start-debug.bat` instead — it keeps the console open and shows the error.

---

## What to say to it

| You type | What happens |
|---|---|
| `remind me to call Mum at 6pm tomorrow` | Reminder at the exact time, with a popup, a tray notification and a chat notice |
| `remind me to take my meds every morning at 8` | Repeating daily reminder that re-arms itself |
| `draft a reply to this message` (with something on your clipboard) | Ready-to-send text in your voice |
| `what's on my plate today?` | Reads your reminders + memory and tells you |
| `summarise this and list the action items` (clipboard) | Condensed summary |
| `who won the Nigeria vs Ghana match?` | Web search and a short answer |
| `I moved to Nairobi last month` | Silently saved to memory, used later without being asked |
| `open youtube.com` | Opens it in Chrome, because Chrome is your default browser |
| `open my browser` / `play some music` | Uses your default apps (Chrome, Spotify) |
| *(spoken)* "Hey Zinger, open Chrome" | Wake word wakes him; he ignores everything else |
| `remember this as a skill: open Chrome, open Spotify` | Saves a reusable skill |
| `teach yourself about me` / `what do you know about me?` | Reads your profile back |
| `open youtube.com` | Opens in your browser |
| `write my shopping list to a file` | Saved in `C:\Users\You\PocketAgent\files` |

---

## The face

A golden energy core drawn live in Qt — rotating tick rings, broken arcs, a sweeping
scanner, plasma filaments and drifting sparks. It reacts to what's happening:

| Look | Meaning |
|---|---|
| Slow amber breathing, few sparks | idle, waiting |
| Bright white core, dense sparks, waveform bars | **listening** (bars move with your voice) |
| Fast spin, orbiting node | thinking |
| Pulsing ripples | speaking |
| Dim, brown, "running low" | tired |

Press **Full screen** (or `F11`) for the JARVIS view: just the core, live captions and an
energy readout, on black. `Esc` returns.

## Talking to it (voice, hotkey, background)

- **Press `Ctrl+Alt+Space`** — anywhere, even with Pocket minimised. It starts
  listening, the orb turns green and pulses with your voice, your words appear, and it
  answers **out loud**.
- **`Ctrl+Alt+Q`** — brings the window up for typing instead.
- **Closing the window keeps it alive** in the tray (right-click the tray icon to talk or
  quit). Turn this off in Settings → *Keep running in the tray*.
- **Settings → Test voice** tells you straight away whether the mic and speech engine
  work on your machine.

### Always-on ears

Turn on **Settings → Always listening**. Once it's on, you don't press anything: it
listens, hears a sentence, answers out loud, then goes back to listening. A click on the
core (or `Ctrl+Alt+Space`) starts and stops it. If the room stays quiet for about a
minute it says so and goes idle rather than listening to nothing forever. It also mutes
its own ears while speaking, so it never answers itself.

### Wake word — "Hey Zinger"

In **Settings → Wake word, your voice, and what he's learned**, tick *Only answer when I
say the wake word*. From then on it ignores the room and only acts when it hears:

> **"Hey Zinger, open Chrome."** · "Zinger, remind me to call Mum at six."
> "Hey Zinga, play some music."

It forgives the way speech recognition mangles the name — *Zinger, Zinga, Singer,
Zingger, Senga* — and strips the greeting, so the agent only ever sees "open Chrome".
Ordinary conversation in the room is ignored. Leave the box unticked and it goes back to
answering anything it hears.

You only say it **once per conversation**. After he answers, he stays awake for about 25
seconds, so you can follow up naturally — *"open Chrome … now play some music … and
remind me at six"* — without repeating the wake word. Say it again to start a new
conversation.

### If it doesn't talk

He speaks through Windows' own offline voice (SAPI5). If you hear nothing:

1. **Settings → Test voice.** It now reports exactly what happened: which engine
   spoke, which voices Windows has, and the last error. No guessing.
2. If it says *pyttsx3 is not installed*: open a terminal in the Pocket folder and run
   `.venv\Scripts\pip install pyttsx3`.
3. If pyttsx3 is installed but silent, he **automatically falls back** to
   PowerShell's own speech engine, so you still get audio.
4. Check Windows **Settings → System → Sound** that the output device is the one you're
   listening on, and that Pocket isn't muted in **Volume mixer**.

He also re-opens his ears the moment a sentence finishes — a callback from the speech
engine, not a guess — so he never goes deaf after talking.

### Multiple API keys (so a daily limit never stops him)

Free tiers run out mid-day. Settings → **Extra keys**, one per line. He uses the first
working key, and when a key hits its quota, is rate-limited or is rejected, he switches
to the next one and carries on mid-conversation. The gateway provider has the same
*Extra gateway keys* box.

He remembers which key last worked, so a burnt key isn't retried first every time.

### It knows your voice

Tick **Only recognise my voice**, press **Learn my voice**, and read three short passages
aloud. Those samples are reduced to a 14-number fingerprint of your voice (pitch, band
energy, rhythm — never a recording of you) and saved as `PocketAgent/voiceprint.json`.
After that a stranger's voice is ignored: *"That doesn't sound like you."*

This is a lightweight speaker check, not bank-grade biometrics — siblings with similar
voices or a bad microphone can still slip through. It's there to stop the TV and other
people triggering him, which is the annoyance that actually matters.

### Teaching him who you are

Two ways:

- **By voice:** "Remember my name is Brian." · "I study at Kenyatta University." ·
  "My sister Wanjiku's birthday is 12 March." He stores each one as a fact.
- **By typing:** Settings → the box under *What he should know about you*, one fact per
  line, then **Save these facts**. Ask *"what do you know about me?"* and he'll recite it.

Those facts are injected into every prompt, so he uses them without being reminded — no
retraining, no new key.

### He gets sharper the more you use him

- **Skills.** "Learn this as a skill: open Chrome, open Spotify, read the news." Later
  just say *"run my morning routine"*. He replays the steps, remembers which ones worked,
  and counts how often each skill is used. **Settings → Manage skills** lists them.
- **App routes.** The first time you say *"open the browser"* he tries Chrome; when one
  works, he remembers it and prefers it next time.
- **Your defaults.** Settings → *Default apps*: browser = **chrome**, music = **spotify**
  by default. Change them to whatever you actually use; he follows the setting rather
  than guessing.

All of this lives in the same local database — nothing is uploaded.

### Watermark mode

**The face is the app.** Pocket starts as just the small floating orb — the dashboard
stays hidden in the background and never opens itself, not when you talk to him, not when
he answers. The dashboard only appears when *you* ask for it: click the orb, or press
`Ctrl+Alt+Q`.

That means anything he needs to tell you shows up on the **desktop itself** (a short
note next to the face) and is **spoken**, never printed into a window you can't see.

When you minimise or close the window, the face collapses back to that small see-through
orb in the corner of the desktop. It isn't a window you have to manage:

- **drag** it anywhere, it remembers where you left it
- **click** it to open the dashboard · **double-click** for the full-screen face
- **right-click** for Open / Start–stop listening / Full screen / Hide
- it shows the same live state as the big face (idle, listening, thinking, speaking)

Its clicks pass through to nothing else and it never takes focus from what you're doing.
Turn it off with *Show the floating face when minimised* in Settings.

### It gets tired

Every turn costs energy, and energy is saved to `PocketAgent/mood.json`. As it drops:

- the face dims toward brown and the rings slow down
- the voice gets **slower, softer and a little lower**
- replies get shorter, and it starts admitting it — *"I'm running on fumes"* before a
  long answer, *"long shift, but I'm fine"* earlier on
- a **night's rest** (time not being used) restores about 10% per hour

It never refuses work over being tired — it just sounds like it. Energy shows in the
full-screen view and under the core.

Voice needs two small packages — `pip install SpeechRecognition pyttsx3` — plus a
microphone. **No compiler, no PyAudio.** Audio capture uses PyQt6's built-in
QtMultimedia, which is why setup no longer needs Microsoft's C++ build tools.

Speech-to-text uses Google's free web recogniser, so *listening* needs internet;
*speaking* (pyttsx3 → Windows SAPI) works fully offline.

> The orb is the "listening" cue: **idle** = slow blue breathing, **green + bars** = it's
> hearing you, **purple dots** = thinking, **blue ripple** = talking back.

## Opening apps

"Open Chrome." "Launch Spotify." "Open the calculator." He looks for the app in this
order: **your default apps → what he learned last time → the alias list → PATH → the
usual install folders → the Start Menu**. That last step is what makes Store apps and
oddly-named shortcuts work.

Two things had to be true for this to work at all:

- **Settings → Allow opening apps** must be ticked (it is by default).
- If a name is ambiguous, give him the exact Start Menu name once: *"open Visual Studio
  Code"*. He remembers it as the route for that intent from then on.

Short commands like "open chrome" are handled **directly**, without asking the model —
so a launch can't fail because the model felt like chatting instead. And if a launch
does fail, he says so out loud and on the desktop, naming what he tried.

## Full access — what actually works

You asked for the agent to run your computer. Here's the honest scoreboard, because some
of this is limited by Windows, not by Pocket:

| Capability | Status | Notes |
|---|---|---|
| Open apps, run commands, type into windows | ✅ Real | Settings → Allow shell commands + keyboard control |
| Read everything on screen | ✅ Real | OCR via Tesseract; needs `pytesseract` + the free Tesseract engine |
| Screenshots | ✅ Real | Saved to your files folder |
| Browse websites for you | ✅ Real | Opens pages and searches the web |
| Email you a reminder | ✅ Real | Needs your Gmail + a 16-character **App Password** |
| Send WhatsApp messages | ⚠️ Drafts + opens the chat | WhatsApp has no official silent-send; with keyboard control it can press Enter for you |
| Read incoming messages | ⚠️ Via Phone Link | It opens Phone Link, screenshots it and reads the text on screen |
| Send SMS | ⚠️ Hands off to Phone Link | Windows exposes no SMS API to desktop apps |
| Make phone calls | ⚠️ Opens the dialler | Real auto-calls need a Twilio account (fields are in the config for that) |

**Why the ⚠️ row matters:** WhatsApp, SMS and calls all sit behind accounts that
deliberately forbid silent automation — that's an anti-spam decision by those companies,
not something an app can code around. Pocket does the honest version: it writes the
message, opens the right screen, and either you tap send or it presses Enter for you.

### About "full access"

Full access is a real trade, so it's all **off by default** and switchable:

- Screen reading means it can see whatever is on your display — including passwords and
  bank screens.
- Email/SMS/calls mean it can contact people **in your name**.
- My advice: turn on shell + screen first. Add email/SMS only once you trust the
  drafts it writes. Keep `send` off for WhatsApp until you've watched it a few times.

Nothing is hidden: every blocked action returns an explicit "Blocked" message naming the
switch to flip, and every tool call is echoed in the status line as it runs.

## Using a different brain (optional)

Settings → **Provider** lets you swap the AI backend without touching anything else:

| Provider | What to fill in |
|---|---|
| **Google Gemini** | AI Studio key (`AQ.` or `AIza`) — the default |
| **OpenAI-compatible gateway** | Base URL (ending `/v1`), gateway key, model slug |

For a gateway: paste the base URL (e.g. `https://api.experientiallabs.ai/v1`), the key,
then press **List models** — Pocket reads the catalogue from `GET /models` and you pick a
slug instead of guessing. **Test provider** confirms it before you save. Keys starting
`xpl_` (Experiential Labs), `gsk_` (Groq), `sk-or-` (OpenRouter) and plain localhost
(Ollama/LM Studio, no key) all just work, because the gateway path never inspects prefixes
— it only sends `Authorization: Bearer <your key>` to the base URL you typed.

Any OpenAI-compatible endpoint works — Groq, OpenRouter, LM Studio, Ollama (`/v1`), or a
routing gateway. Your key is only ever sent to the base URL you type, and **Test provider**
verifies it before you save. All of Pocket's tools (reminders, memory, files, drafting)
work identically on either provider.

### ⚠️ Before you paste a key from a random site

Keys are credentials, and free-key sites are a classic way to collect them:

- Type check the domain in the address bar. `experimentallab.ai` **does not exist** —
  DNS fails. The real company is `experientiallabs.ai`.
- A gateway sees every prompt you send through it. Never route private work, client data
  or passwords through one you don't trust.
- **Never paste an API key into a chat window**, including with me. If you already did,
  revoke it on the issuing site and make a new one.
- Simpler and safer: you don't need one. Gemini's free tier needs no card, and Ollama
  runs locally with no key at all.

## Permissions — off until you say otherwise

In **Settings**:

- **Allow reading and writing files** — on by default, but only inside the agent's own
  `PocketAgent\files` folder. It cannot wander your drive.
- **Allow shell commands and launching apps** — off. When on, the agent can run
  commands and open programs.
- **Allow typing into the focused window** — off. When on, it can type into whatever
  window you have focused (handy for pasting a draft into WhatsApp Web or Outlook).

Anything blocked is refused by the code itself, not just hidden from the model — the
tool returns `Blocked` and the agent tells you which switch to turn on.

**Treat the key like a password.** Don't post it in chats, screenshots or GitHub.
If it ever leaks, delete it at aistudio.google.com/apikey and make a new one — it takes
ten seconds, and the old one dies immediately.

**Privacy:** your API key and everything else live only on your laptop, in
`C:\Users\You\PocketAgent\`. The only thing that leaves the machine is the text of each
message (with relevant memories) sent to Google's Gemini API for a reply. No accounts,
no server, no analytics.

---

## Keeping it always available

- Minimise it — it keeps running and keeps firing reminders from the **system tray**
  (bottom-right, near the clock). Right-click the tray icon to reopen or quit.
- To start it with Windows: press `Win+R`, type `shell:startup`, press Enter, and put a
  shortcut to `start.bat` in that folder.
- Reminders only fire while the app is open. That's the one real limitation of a
  laptop-side agent.

---

## When something goes wrong

### “The key works but isn’t allowed to use this model”

This is almost never a model problem. Google returns **403 / “denied access”** when the
whole **project** is restricted, and creating a key from that project inherits the block.
Changing to `flash-lite` won’t help, because every model fails the same way.

Press **Settings → Diagnose key**. It talks to Google and prints the truth: whether your
key can even list models, and if it can, which models actually generate text. A working
model is offered to you as one click.

Then work through this, in order (straight from Google’s support replies):

1. **Age verification** — Google Account → Personal info → verify your date of birth.
2. **Phone verification** and **2-Step Verification** switched ON for that Google account.
3. **Create a brand-new project + key** in https://aistudio.google.com/apikey. Google’s
   own advice is that existing projects often stay locked even after you verify —
   a fresh project is what usually clears it.
4. If it *still* fails, **attach billing / add prepaid credits** in AI Studio. This moves
   the project to the paid tier and clears the flag. Note: you lose the free-tier quota
   on that project, though prepaid credit on Flash models goes very far for personal use
   — think cents, not dollars, for a month of light use.
5. **Don’t** use a VPN to work around it — Google flags that and can revoke the key.

Check the project’s status in AI Studio while you’re there. If it says **Restricted** or
**Project quota tier unavailable**, no amount of model-switching will fix it.

> FYI: Kenya *is* on Google’s list of supported regions for the Gemini API, so the
> country isn’t the problem — it’s an account/project flag.

---

| Symptom | Fix |
|---|---|
| Window never appears | Run `start-debug.bat` and read the error; details also go to `error.log` |
| Hotkey does nothing | `pip install pynput`. If another app owns Ctrl+Alt+Space, change it in Settings |
| Mic not detected | `pip install SpeechRecognition`, and check Windows → Privacy → Microphone → allow desktop apps |
| `error: Microsoft Visual C++ 14.0 is required` | You're on an old copy of the zip — PyAudio was removed. Re-download, or run `pip install SpeechRecognition pyttsx3` and skip PyAudio entirely |
| `Building wheel for pyaudio failed` | Same: PyAudio is no longer used. If you installed it yourself and don't need it, `pip uninstall pyaudio pyaudio-fix` |
| "Some optional packages failed" during setup | Harmless — Pocket runs without voice. Add them later with `.venv\Scripts\pip install SpeechRecognition pyttsx3 pynput` |
| No sound | `pip install pyttsx3`; press Settings → Test voice |
| "Tesseract isn't installed" | Install it from github.com/UB-Mannheim/tesseract/wiki, then restart |
| Gmail "authentication failed" | You used your normal password. Make an App Password (myaccount.google.com/apppasswords) |
| “No API key yet” | Settings → paste the key → **Test connection** → Save |
| “Google rejected the key” | Re-copy from aistudio.google.com/apikey — no spaces or line breaks, copied in full. `AQ.` and `AIza` are both valid |
| “TOKEN-TYPE BUG” / `UNAUTHENTICATED` | Known issue with some new `AQ.` keys. Pocket auto-retries over REST; otherwise wait, or make an `AIza` key in Google Cloud Console |
| “Model not found” / retired model | Self-healing; or press **Find models** and pick the newest one |
| “Key is valid but you've hit the free-tier rate limit” | Wait a minute, or switch the model to `gemini-2.5-flash-lite` |
| “PROJECT BLOCKED” / “denied access” | See the section above — verify age/phone/2SV, make a new project, or attach billing |
| “Use a working model” greyed out | Nothing generated text — read the report, it says why |
| “model unavailable, trying another model…” | Normal — it falls back to another free Gemini model |
| 429 / quota errors | You hit the free-tier limit for the day. Wait, or switch the model in Settings to `gemini-2.5-flash-lite` |
| Shell/app tool says *Blocked* | Settings → turn on “Allow shell commands” |
| Reminders don't pop | Check the app is running (tray icon present) and the reminder time isn't in the past |
| Emoji show as boxes | Windows 10/11 usually fine; on older builds they may not render |

Run `python tests.py` any time to check the storage, reminder and tool layers.

**Settings → Diagnose key** is the place to start for any connection problem. It prints
a copyable report showing which models your key can really reach, and the plain-English
cause of any failure.

---

## How it works (if you want to tinker)

```
pocket-agent/
├── app.py            entry point
├── ui.py             the desktop window (PyQt6): chat, reminders, memory, settings
├── agent.py          the brain: Gemini + the tool-calling loop
├── tools.py          what the agent can do, and the JSON schemas that describe it
├── store.py          SQLite: chat history, memories, reminders  (~/PocketAgent)
├── config.py         settings in config.json
├── tests.py          self-check
├── setup.bat / start.bat / start-debug.bat
├── install/          the same three scripts, with the real logic
└── screenshots/
```

The loop is simple: your message + recent history + saved memories + open reminders go
to Gemini along with a list of tools. If Gemini asks to call one, `agent.py` runs the
Python function, hands the result back, and repeats until Gemini has a real answer.

**Easy upgrades you could ask for later:**
- Wake-word listening (“Hey Pocket…”) with `speech_recognition` + text-to-speech
- Telegram bot mode, so you can message your laptop agent from your phone
- Gmail / Google Calendar tools so it can read mail and book events
- Auto-start on boot + minimise-to-tray only
- A packaged `.exe` with PyInstaller so Python isn't needed

---

Free-tier note: Gemini's free tier limits requests per minute and per day, which is
plenty for personal use — you'd need to be chatting constantly to hit it.
