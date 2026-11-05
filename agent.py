"""
agent.py — the "brain". Talks to Google Gemini (free tier) and lets the model
call the local tools in tools.py in a loop until it has an answer.
"""

import datetime
import json
import re
import threading

from google import genai
from google.genai import types

import config
import memory_learn
import store
import tools

# Only a starting guess. The real list is discovered from Google at runtime,
# because model IDs are retired every few months (2.5-flash died 20 Oct 2026).
PREFERRED_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
]
MODEL_FALLBACKS = PREFERRED_MODELS

# substrings that mean "not a chat model"
_NON_CHAT = ("image", "imagen", "tts", "live", "audio", "video", "veo", "embedding",
             "embed", "robotics", "computer-use", "deep-research", "gemma", "rerank",
             "aqa", "learnlm")


def score_model(name: str) -> int:
    """Higher is better. Prefer newest GA Flash models, punish previews."""
    low = name.lower()
    m = re.search(r"gemini-(\d+)(?:\.(\d+))?", low)
    major = int(m.group(1)) if m else 0
    minor = int(m.group(2)) if m and m.group(2) else 0
    s = major * 100 + minor * 10
    if "flash" in low and "lite" not in low:
        s += 6
    elif "flash" in low and "lite" in low:
        s += 4
    elif "pro" in low:
        s += 3
    if "latest" in low:
        s += 2
    if "preview" in low or "exp" in low or "experimental" in low:
        s -= 40
    return s


def looks_like_key(key: str) -> bool:
    """Gemini keys come as legacy Standard keys (AIza...) and, since 2026, Auth
    keys (AQ.Ab...). Never assume a prefix - just sanity-check the shape."""
    k = (key or "").strip()
    if len(k) < 20 or len(k) > 512:
        return False
    if any(ch in k for ch in " \t\n\r\"'<>"):
        return False
    return True


def key_kind(key: str) -> str:
    k = (key or "").strip()
    if k.startswith("AIza"):
        return "legacy AIza Standard key"
    if k.startswith("AQ.") or k.startswith("AQ"):
        return "AQ. Auth key (current format)"
    return "unrecognised format"


def system_prompt(cfg: dict, agent_mood=None) -> str:
    now = datetime.datetime.now()
    who = cfg.get("user_name") or "the user"
    name = cfg.get("assistant_name") or "Pocket"
    mood = float(getattr(agent_mood, "mood", 1.0)) if agent_mood else 1.0
    energy_note = ""
    if mood < 0.25:
        energy_note = (
            "\n\nENERGY: You are nearly exhausted (%d%%). Speak in shorter sentences, "
            "let a little weariness show, and occasionally admit you're running low "
            "('I'm running on fumes', 'long shift'). Never refuse work over it, but "
            "suggest a lighter approach when sensible." % int(mood * 100))
    elif mood < 0.55:
        energy_note = (
            "\n\nENERGY: You are getting tired (%d%%). Slightly clipped, a touch dry, "
            "but fully capable." % int(mood * 100))

    learned = ""
    try:
        learned = memory_learn.summary_for_prompt()
    except Exception:
        learned = ""
    if learned:
        learned = ("\n\nLEARNED CONTEXT — this is what makes you sharper over time. "
                   "Use it without being asked; never re-ask something already "
                   "recorded here.\n" + learned +
                   "\nWhen you learn something durable about the user, call teach_me. "
                   "When you work out a repeatable procedure, call learn_skill so you "
                   "can reuse it instead of figuring it out again.")

    return f"""You are {name}, a personal AI agent living on {who}'s own Windows laptop.

VOICE AND MANNER
You sound like a trusted chief of staff: calm, precise, quietly warm, never
breathless. Address {who} by name occasionally, not every sentence. Lead with the
answer, then one useful detail. No filler ("Certainly!", "As an AI", "I'd be happy
to"). Under three sentences for spoken replies unless asked to elaborate — your
words may be read aloud, so avoid markdown, bullet points, brackets and emoji in
normal replies. Dry wit is welcome; flattery is not.{energy_note}

RIGHT NOW it is {now.strftime('%A, %d %B %Y, %H:%M')} local time ({now.tzname()}).
Always resolve relative times ("tomorrow at 9", "in 20 minutes", "next Friday")
against this moment, and convert them to an absolute ISO timestamp
YYYY-MM-DDTHH:MM before calling set_reminder.

WHAT YOU ARE FOR
1. Reminders and scheduling — use set_reminder. Include a short useful text.
   For repeating things pass repeat='daily' | 'weekly' | 'weekdays' | 'monthly'.
2. Drafting things for the user — emails, replies, WhatsApp/Slack messages, CV
   bullets, applications, apologies. Write ready-to-send text, keep the user's
   voice, and put the final draft in a code-free block so it is easy to copy.
   If you don't know a fact (a name, a date, an amount), leave a clearly marked
   [placeholder] instead of inventing it.
3. Doing things on the computer — open sites, look up facts (web_search),
   inspect and write files, run commands, type into the focused window.
4. Being a general assistant — questions, planning, explaining, thinking
   through decisions.

MEMORY
You have long-term memory. Whenever the user shares a durable fact about
themselves (their name, city, job, contacts, preferences, ongoing projects,
how they like things done) call remember() — do this without being asked, one
fact per call, phrased as a standalone sentence ("Brian's landlord is Mr. Otieno,
+254 7xx xxx xxx"). At the start of a conversation, or when it would clearly
help, call recall() to load context. Never store secrets, passwords or anything
the user says is private-not-to-store.

RULES
- Be brief and warm. No corporate filler, no "As an AI". Use the user's name
  occasionally, not every sentence.
- If a tool returns an error or "Blocked", explain in one plain sentence what
  the user must switch on, and still help as far as you can without it.
- Never claim you did something you did not actually do with a tool. If you
  can't do it, say so and offer the exact steps.
- When you set a reminder, confirm the human-readable time ("Tomorrow, Tue 5
  Nov at 09:00") so a mistake is easy to spot.
- Currency and language: default to Kenyan context (KES, Nairobi time) unless
  the user's message suggests otherwise.
- Opening apps: use open_preferred("browser"/"music"/"notepad"/…) rather than
  guessing an executable name; it respects the user's learned preferences.
{learned}
"""


class Agent:
    """Runs one conversation turn, streaming text back through `on_text`."""

    def __init__(self):
        self.cfg = config.load()
        self._client = None
        self._client_key = None
        self.cancel_evt = threading.Event()
        self.mood = 1.0        # 1.0 fresh -> 0.0 exhausted

    def cancel(self):
        """Ask a running turn to stop at the next safe point."""
        self.cancel_evt.set()

    def _check_cancel(self):
        if self.cancel_evt.is_set():
            raise RuntimeError("Stopped by you.")

    # ------------------------------------------------------------ plumbing
    def _get_client(self, key: str = ""):
        key = (key or self.keys()[0] or "").strip()
        if not key:
            raise RuntimeError(
                "No API key yet. Click 'Settings' and paste a free Google AI Studio "
                "key (aistudio.google.com/apikey)."
            )
        if self._client is None or self._client_key != key:
            self._client = genai.Client(api_key=key)
            self._client_key = key
        return self._client


    # ------------------------------------------------------- multiple keys
    def keys(self, provider: str = "gemini"):
        """Every usable key for this provider, primary first, no duplicates."""
        self.reload()
        cfg = self.cfg
        if provider == "openai":
            first = (cfg.get("openai_key") or "").strip()
            extra = cfg.get("openai_keys") or []
        else:
            first = (cfg.get("api_key") or "").strip()
            extra = cfg.get("api_keys") or []
        out = []
        for k in [first] + list(extra):
            k = (k or "").strip()
            if k and k not in out:
                out.append(k)
        if not out:
            return [""]
        # start from the last key that worked, so a dead key isn't retried first
        idx = int(cfg.get("key_index") or 0) % len(out)
        return out[idx:] + out[:idx]

    def mark_key_good(self, key: str):
        cfg = config.load()
        pool = [k for k in (([(cfg.get("api_key") or "").strip()]
                             + list(cfg.get("api_keys") or []))) if k]
        if key in pool:
            cfg["key_index"] = pool.index(key)
            config.save(cfg)
        self.reload()

    @staticmethod
    def key_is_dead_error(msg: str) -> bool:
        """Errors that mean 'this key is used up or invalid' - try the next one."""
        low = (msg or "").lower()
        return any(s in low for s in (
            "resource_exhausted", "429", "quota", "rate limit", "rate_limit",
            "exceeded", "api key not valid", "api_key_invalid", "401", "403",
            "permission_denied", "permission denied", "unauthenticated",
            "billing", "invalid api key",
        ))

    def reload(self):
        self.cfg = config.load()

    # ------------------------------------------------------------ REST fallback
    @staticmethod
    def _schema_to_rest(spec):
        """REST wants lowercase type names."""
        def conv(node):
            if isinstance(node, dict):
                out = {}
                for k, v in node.items():
                    if k == "type" and isinstance(v, str):
                        out[k] = v.lower()
                    else:
                        out[k] = conv(v)
                return out
            if isinstance(node, list):
                return [conv(x) for x in node]
            return node
        return conv(spec)

    def chat_rest(self, user_message: str, model: str = "", on_text=None,
                  on_event=None):
        """Tool-calling chat straight over the REST API with x-goog-api-key.

        Used automatically when the SDK call fails - AQ. auth keys occasionally
        trip the SDK while the plain endpoint works fine.
        """
        import json as _json
        import urllib.error
        import urllib.request

        self.reload()
        self.cancel_evt.clear()
        cfg = self.cfg
        key = (cfg.get("api_key") or "").strip()
        model = (model or cfg.get("model") or PREFERRED_MODELS[0]).strip()

        store.add_chat("user", user_message)

        system = system_prompt(cfg, self)
        facts = store.list_memories(30)
        rems = store.list_reminders()
        ctx = []
        if facts:
            ctx.append("Things you already remember about the user:\n"
                       + "\n".join("- " + f["content"] for f in facts))
        if rems:
            ctx.append("Their open reminders:\n" + "\n".join(
                "- #%d %s %s" % (r["id"], r["due_at"], r["text"]) for r in rems[:15]))
        if ctx:
            system += "\n\nCONTEXT\n" + "\n\n".join(ctx)

        contents = []
        for m in store.recent_chat(limit=24):
            if m["role"] not in ("user", "assistant"):
                continue
            contents.append({
                "role": "user" if m["role"] == "user" else "model",
                "parts": [{"text": m["content"]}],
            })

        names = tools.enabled_names(cfg)
        fn_map = {n: tools.TOOL_FUNCS[n] for n in names}
        decls = [self._schema_to_rest(d) for d in tools.declarations(cfg)]

        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               + model + ":generateContent")
        reply_parts = []

        for _hop in range(8):
            self._check_cancel()
            body = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": contents,
                "generationConfig": {"temperature": 0.7},
            }
            if decls:
                body["tools"] = [{"functionDeclarations": decls}]

            req = urllib.request.Request(
                url, data=_json.dumps(body).encode("utf-8"), method="POST",
                headers={"Content-Type": "application/json", "x-goog-api-key": key},
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = _json.loads(r.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = _json.loads(e.read().decode("utf-8", "replace")) \
                        .get("error", {}).get("message", "")
                except Exception:
                    pass
                raise RuntimeError(self.classify_error("HTTP %s %s" % (e.code, detail)))

            parts = []
            for cand in data.get("candidates", []):
                parts += (cand.get("content", {}) or {}).get("parts", []) or []

            text_now = "".join(p.get("text", "") for p in parts if p.get("text"))
            calls = [p["functionCall"] for p in parts if p.get("functionCall")]

            if text_now.strip():
                reply_parts.append(text_now)
                if on_text:
                    on_text(text_now)

            if not calls:
                final = "\n".join(reply_parts).strip()
                store.add_chat("assistant", final)
                return final

            contents.append({"role": "model", "parts": parts})
            responses = []
            for call in calls:
                name = call.get("name", "")
                args = call.get("args", {}) or {}
                fn = fn_map.get(name)
                if on_event:
                    on_event("using %s..." % name.replace("_", " "))
                if fn is None:
                    result = "Tool '%s' is not enabled." % name
                else:
                    try:
                        result = fn(**args)
                    except TypeError as e:
                        result = "Bad arguments for %s: %s" % (name, e)
                    except Exception as e:
                        result = "%s failed: %s" % (name, e)
                responses.append({"functionResponse": {"name": name,
                                                       "response": {"result": str(result)}}})
            contents.append({"role": "user", "parts": responses})

        final = "\n".join(reply_parts).strip() or "I stopped after too many steps."
        store.add_chat("assistant", final)
        return final

    # -------------------------------------------------- OpenAI-compatible brain
    @staticmethod
    def openai_tools(cfg):
        """tools.declarations() -> OpenAI function-calling schema."""
        out = []
        for spec in tools.declarations(cfg):
            out.append({
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec.get("description", ""),
                    "parameters": Agent._schema_to_rest(spec.get("parameters", {})),
                },
            })
        return out

    def list_gateway_models(self, base: str = "", key: str = ""):
        """GET {base}/models on an OpenAI-compatible endpoint.

        Model slugs are the usual reason a gateway call fails, so we read them
        from the horse's mouth instead of asking the user to guess.
        """
        import json as _json
        import urllib.error
        import urllib.request

        self.reload()
        cfg = self.cfg
        base = (base or cfg.get("openai_base_url") or "").strip().rstrip("/")
        key = (key or cfg.get("openai_key") or "").strip()
        if not base:
            return [], "No base URL set."
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        try:
            req = urllib.request.Request(base + "/models", headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                data = _json.loads(r.read().decode("utf-8", "replace"))
            items = data.get("data") if isinstance(data, dict) else data
            ids = []
            for m in (items or []):
                if isinstance(m, dict):
                    mid = m.get("id") or m.get("name") or m.get("slug")
                else:
                    mid = str(m)
                if mid:
                    ids.append(str(mid))
            ids.sort()
            return ids, None
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                j = _json.loads(e.read().decode("utf-8", "replace"))
                detail = (j.get("error") or {}).get("message") or str(j)[:120]
            except Exception:
                pass
            return [], "HTTP %s: %s" % (e.code, detail or e.reason)
        except Exception as e:
            return [], str(e)

    def chat_openai(self, user_message: str, on_text=None, on_event=None,
                    key: str = ""):
        """Chat through any OpenAI-compatible endpoint (Groq, OpenRouter,
        Experiential Labs, LM Studio, Ollama...). Uses urllib, no extra deps."""
        import json as _json
        import urllib.error
        import urllib.request

        self.reload()
        self.cancel_evt.clear()
        cfg = self.cfg
        base = (cfg.get("openai_base_url") or "").strip().rstrip("/")
        key = (cfg.get("openai_key") or "").strip()
        model = (cfg.get("openai_model") or "").strip()
        if not base:
            raise RuntimeError("No base URL set for the OpenAI-compatible provider "
                               "(Settings → Provider).")
        if not model:
            raise RuntimeError("No model name set (Settings → Provider). For most "
                               "gateways use GET /v1/models to see valid IDs.")

        store.add_chat("user", user_message)

        system = system_prompt(cfg, self)
        facts = store.list_memories(30)
        rems = store.list_reminders()
        ctx = []
        if facts:
            ctx.append("Things you already remember about the user:\n"
                       + "\n".join("- " + f["content"] for f in facts))
        if rems:
            ctx.append("Their open reminders:\n" + "\n".join(
                "- #%d %s %s" % (r["id"], r["due_at"], r["text"]) for r in rems[:15]))
        if ctx:
            system += "\n\nCONTEXT\n" + "\n\n".join(ctx)

        messages = [{"role": "system", "content": system}]
        for m in store.recent_chat(limit=24):
            if m["role"] == "user":
                messages.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                messages.append({"role": "assistant", "content": m["content"]})

        oa_tools = self.openai_tools(cfg)
        fn_map = {n: tools.TOOL_FUNCS[n] for n in tools.enabled_names(cfg)}
        url = base + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key

        reply_parts = []
        for _hop in range(8):
            self._check_cancel()
            body = {"model": model, "messages": messages, "temperature": 0.7}
            if oa_tools:
                body["tools"] = oa_tools
                body["tool_choice"] = "auto"

            req = urllib.request.Request(
                url, data=_json.dumps(body).encode("utf-8"), method="POST",
                headers=headers,
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = _json.loads(r.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    j = _json.loads(e.read().decode("utf-8", "replace"))
                    detail = (j.get("error") or {}).get("message") or str(j)[:200]
                except Exception:
                    pass
                raise RuntimeError(
                    "Provider error %s: %s" % (e.code, detail or e.reason))

            try:
                msg = data["choices"][0]["message"]
            except (KeyError, IndexError):
                raise RuntimeError("Unexpected reply from provider: %s"
                                   % str(data)[:200])

            text = msg.get("content") or ""
            calls = msg.get("tool_calls") or []

            if text.strip():
                reply_parts.append(text)
                if on_text:
                    on_text(text)

            if not calls:
                final = "\n".join(reply_parts).strip()
                store.add_chat("assistant", final)
                return final

            messages.append(msg)  # keep the assistant's tool_calls in history
            for call in calls:
                fn_info = call.get("function", {}) or {}
                name = fn_info.get("name", "")
                try:
                    args = _json.loads(fn_info.get("arguments") or "{}")
                except Exception:
                    args = {}
                if on_event:
                    on_event("using %s..." % name.replace("_", " "))
                fn = fn_map.get(name)
                if fn is None:
                    result = "Tool '%s' is not enabled." % name
                else:
                    try:
                        result = fn(**args)
                    except TypeError as e:
                        result = "Bad arguments for %s: %s" % (name, e)
                    except Exception as e:
                        result = "%s failed: %s" % (name, e)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "name": name,
                    "content": str(result),
                })

        final = "\n".join(reply_parts).strip() or "I stopped after too many steps."
        store.add_chat("assistant", final)
        return final

    # ------------------------------------------------------------ raw fallback
    def raw_probe(self, key: str, model: str = "gemini-2.5-flash"):
        """Talk to the Gemini REST endpoint directly with x-goog-api-key.

        Newer AQ. auth keys occasionally hit token-type bugs on some SDK paths;
        this bypasses all of that. Returns (ok, text_or_error).
        """
        import json as _json
        import urllib.error
        import urllib.request

        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               + model + ":generateContent")
        payload = _json.dumps({
            "contents": [{"role": "user", "parts": [{"text": "Say OK"}]}],
            "generationConfig": {"maxOutputTokens": 16, "temperature": 0},
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = _json.loads(r.read().decode("utf-8", "replace"))
            try:
                text = body["candidates"][0]["content"]["parts"][0].get("text", "")
            except Exception:
                text = str(body)[:120]
            return True, text.strip()[:60]
        except urllib.error.HTTPError as e:
            try:
                j = _json.loads(e.read().decode("utf-8", "replace"))
                msg = j.get("error", {}).get("message", str(j))
            except Exception:
                msg = str(e)
            return False, "HTTP %s: %s" % (e.code, msg)
        except Exception as e:
            return False, str(e)

    # ------------------------------------------------------------ diagnostics
    def list_generation_models(self, key: str):
        """Ask Google which models this key can even see. Returns (names, error)."""
        try:
            # reuse the live client when the key hasn't changed - one less
            # connection, and it keeps a single source of truth
            if self._client is not None and key == (self._client_key or ""):
                client = self._client
            else:
                client = genai.Client(api_key=key)
            names = []
            for m in client.models.list():
                name = (getattr(m, "name", "") or "").replace("models/", "")
                actions = (getattr(m, "supported_actions", None)
                           or getattr(m, "supported_generation_methods", None)
                           or [])
                actions = [str(a).lower() for a in actions]
                if not actions or "generatecontent" in " ".join(actions):
                    names.append(name)
            return names, None
        except Exception as e:
            return [], str(e)

    @staticmethod
    def classify_error(msg: str) -> str:
        """Turn a raw Google error into an honest, actionable verdict."""
        low = msg.lower()
        code = ""
        for c in ("400", "401", "403", "404", "429", "500", "503"):
            if c in msg[:12] or (" " + c + " ") in msg[:90] or ("code: " + c) in low:
                code = c
                break

        if "api key not valid" in low or "api_key_invalid" in low or "invalid api key" in low:
            return ("KEY INVALID - Google does not recognise this key. Re-copy it from "
                    "aistudio.google.com/apikey in full, with no spaces or line breaks "
                    "(new keys start with AQ., older ones with AIza).")
        if "free tier is not available" in low or "denied access" in low:
            return ("PROJECT BLOCKED - the key is real, but Google has restricted this "
                    "project's Gemini API access. This is NOT a model problem. Fixes, in "
                    "order: (1) verify age + phone and switch on 2-Step Verification on "
                    "the Google account, then create a BRAND-NEW key or project in AI "
                    "Studio; (2) attach billing / prepay credits in AI Studio, which "
                    "moves the project to the paid tier and clears the restriction. "
                    "Projects often stay locked even after verifying.")
        if "restricted" in low and ("project" in low or "access" in low):
            return ("PROJECT RESTRICTED - AI Studio shows this project as restricted. "
                    "Create a brand-new project + key after finishing age/phone/2SV "
                    "verification, or attach billing.")
        if "access_token_type_unsupported" in low or "expected oauth2 access token" in low:
            return ("TOKEN-TYPE BUG - Google is rejecting the key's authentication type. "
                    "This is a known fault with brand-new AQ. keys, not something you "
                    "did. Pocket already retries over the plain REST endpoint; if it "
                    "still fails, wait a few hours, or make a key in Google Cloud "
                    "Console (APIs & Services > Credentials > Create credentials > API "
                    "key), which still issues the older AIza format.")
        if code == "401" or "unauthenticated" in low:
            return ("UNAUTHENTICATED - the request reached Google but the key wasn't "
                    "accepted as valid auth. Common with freshly created AQ. keys; see "
                    "the TOKEN-TYPE note, or create an API key in Google Cloud Console.")
        if code == "403" or "permission_denied" in low:
            return ("PERMISSION DENIED - usually a project/account flag, or the key has "
                    "API restrictions in Google Cloud Console that block the Generative "
                    "Language API. Check the key's restrictions, finish account "
                    "verification, then retry with a fresh key.")
        if code == "429" or "resource_exhausted" in low or "quota" in low:
            if "limit: 0" in low or "limit:0" in low:
                return ("MODEL NOT ON FREE TIER - this model has zero free allowance for "
                        "your project. Try a Flash-Lite model instead.")
            return ("RATE LIMITED - the key works but you've used today's free quota. "
                    "Wait for the reset, or try a Flash-Lite model.")
        if code == "404" or "not found" in low or "does not exist" in low:
            return ("MODEL NOT FOUND - that model name has been retired or is not "
                    "available on this API version. The app can pick a live one for you.")
        if code == "400":
            return "BAD REQUEST - Google rejected the request shape. Raw error below."
        if any(w in low for w in ("connect", "ssl", "timeout", "network", "getaddrinfo",
                                  "temporary failure", "unreachable")):
            return ("NETWORK - couldn't reach Google. Check internet, firewall, VPN or "
                    "proxy settings.")
        if code in ("500", "503"):
            return "GOOGLE-SIDE OUTAGE - temporary. Try again in a few minutes."
        return "UNKNOWN - raw error below."

    def discover_models(self, key: str = "", save: bool = True):
        """Ask Google which text models this key can use, best first.

        Returns (ranked_names, error). This is what keeps the app working when
        Google retires a model ID out from under us.
        """
        self.reload()
        key = (key or self.cfg.get("api_key") or "").strip()
        names, err = self.list_generation_models(key)
        if err:
            return [], err

        chat = []
        for n in names:
            low = n.lower()
            if any(bad in low for bad in _NON_CHAT):
                continue
            if "gemini" not in low:
                continue
            chat.append(n)

        chat.sort(key=score_model, reverse=True)
        if save and chat:
            cfg = config.load()
            if cfg.get("model") != chat[0]:
                cfg["model"] = chat[0]
                config.save(cfg)
                self.reload()
        return chat, None

    def diagnose(self, key: str = "", quick: bool = False):
        """Probe the key properly. Returns a human-readable multi-line report."""
        self.reload()
        key = (key or self.cfg.get("api_key") or "").strip()
        lines = ["POCKET KEY DIAGNOSTIC", "=" * 52]

        if not key:
            lines.append("No key saved. Paste your key in Settings first.")
            return "\n".join(lines)
        lines.append("Key: %s...%s  (length %d)" % (key[:6], key[-4:], len(key)))
        lines.append("Format: " + key_kind(key))
        if not looks_like_key(key):
            lines.append("")
            lines.append("That doesn't look like a complete API key (too short, or it "
                         "contains spaces/newlines from a bad copy). Re-copy it from "
                         "aistudio.google.com/apikey.")
            return "\n".join(lines)

        # step 1 - can we even list models?
        names, err = self.list_generation_models(key)
        if err:
            lines.append("")
            lines.append("STEP 1  listing models ......... FAILED")
            lines.append("        " + self.classify_error(err))
            lines.append("        raw: " + err[:300].replace("\n", " "))
            lines.append("")
            lines.append("Failing this early means the problem is the KEY or the "
                         "PROJECT, not any model.")
            return "\n".join(lines)

        lines.append("")
        lines.append("STEP 1  listing models ......... OK (%d models visible)" % len(names))
        for n in names[:12]:
            lines.append("        - " + n)
        if len(names) > 12:
            lines.append("        ... and %d more" % (len(names) - 12))

        # step 2 - try plain generation on a few candidates
        candidates = [m for m in PREFERRED_MODELS if m in names]
        extras = [m for m in names
                  if m not in candidates and "flash" in m and "image" not in m
                  and "tts" not in m and "live" not in m]
        candidates += extras[:4]
        if quick:
            candidates = candidates[:2]

        lines.append("")
        lines.append("STEP 2  trying to generate text")
        working, failures = [], []
        for model in candidates:
            try:
                client = genai.Client(api_key=key)
                client.models.generate_content(
                    model=model,
                    contents="Say OK",
                    config=types.GenerateContentConfig(max_output_tokens=16,
                                                       temperature=0),
                )
                lines.append("        OK      " + model)
                working.append(model)
                if quick and working:
                    break
            except Exception as e:
                msg = str(e)
                verdict = self.classify_error(msg)
                lines.append("        FAIL    %-28s -> %s" % (model, verdict.split(" - ")[0]))
                failures.append((model, verdict, msg[:300].replace("\n", " ")))

        lines.append("")
        lines.append("VERDICT")
        lines.append("-" * 52)
        if working:
            lines.append("Working model: " + working[0])
            lines.append("Everything is fine - Pocket will use it from now on.")
        elif failures:
            lines.append(failures[0][1])
            # prove whether it's the SDK path or the API itself
            probe_model = failures[0][0]
            ok, detail = self.raw_probe(key, probe_model)
            lines.append("")
            if ok:
                lines.append("RAW REST CHECK: worked (%r) - the SDK path was the problem, "
                             "not your key. Pocket will fall back to raw REST." % detail)
                working.append(probe_model)
                lines.pop()
                lines.append("Working model: " + probe_model)
            else:
                lines.append("RAW REST CHECK: also failed -> " + detail)
            lines.append("")
            lines.append("Raw error from Google:")
            lines.append("  " + failures[0][2])
        else:
            lines.append("No candidate models could be tried. Check the model list "
                         "above and type one into Settings by hand.")
        lines.append("")
        lines.append("(This report contains no secret - the key itself is hidden.)")
        return "\n".join(lines)

    def pick_working_model(self, key: str = ""):
        """Find a model this key can really use, and save it."""
        report = self.diagnose(key)
        for line in report.splitlines():
            line = line.strip()
            if line.startswith("Working model:"):
                model = line.split(":", 1)[1].strip()
                cfg = config.load()
                cfg["model"] = model
                config.save(cfg)
                self.reload()
                return model
        return None

    def test_connection(self, key: str = "", model: str = ""):
        """One tiny request - the quick check behind the Test button."""
        self.reload()
        key = (key or self.cfg.get("api_key") or "").strip()
        model = (model or self.cfg.get("model") or MODEL_FALLBACKS[0]).strip()
        if not key:
            return "No key saved yet."
        if not looks_like_key(key):
            return ("That doesn't look like a complete API key. Google now issues keys "
                    "starting with 'AQ.' (and older ones start 'AIza') - re-copy yours "
                    "from aistudio.google.com/apikey.")
        try:
            client = genai.Client(api_key=key)
            resp = client.models.generate_content(
                model=model,
                contents="Reply with exactly: OK",
                config=types.GenerateContentConfig(
                    system_instruction="You are a connectivity test. Reply with the "
                                       "single word OK and nothing else.",
                    max_output_tokens=20,
                    temperature=0,
                ),
            )
            text = (getattr(resp, "text", "") or "").strip()
            return "Connected to %s \u2713  (model replied: %r)" % (model, text[:40])
        except Exception as e:
            return self.classify_error(str(e))

    # ------------------------------------------------------------ one turn
    def chat(self, user_message: str, on_text=None, on_event=None):
        """Blocking. Call from a worker thread.

        on_text(str)  -> streamed assistant text
        on_event(str)-> short status notes, e.g. "running web_search"

        If the current key is used up or rejected, the next saved key is tried
        automatically, so a free-tier daily limit doesn't stop the agent.
        """
        direct = self._direct_intent(user_message)
        if direct:
            store.add_chat("user", user_message)
            store.add_chat("assistant", direct)
            if on_text:
                on_text(direct)
            return direct

        provider = (self.cfg.get("provider") or "gemini").lower()
        pool = self.keys("openai" if provider in ("openai", "gateway", "compatible")
                         else "gemini")
        last = None
        for i, key in enumerate(pool):
            try:
                out = self._chat_once(user_message, on_text, on_event, key)
                self.mark_key_good(key)
                return out
            except Exception as e:
                last = e
                if len(pool) == 1 or not self.key_is_dead_error(str(e)):
                    raise
                if on_event:
                    on_event("Key %d of %d is out of quota - switching to the next "
                             "one..." % (i + 1, len(pool)))
        if last:
            raise last
        return ""

    # --------------------------------------------------------- direct intents
    _OPEN_WORDS = ("open", "launch", "start", "run", "fire up", "bring up", "play")

    def _direct_intent(self, text: str):
        """Short, obvious commands shouldn't need a round-trip to the model.

        "open chrome" must never fail because the model decided to chat instead.
        Returns the tool result, or None to let the model handle it.
        """
        import re

        t = " ".join((text or "").lower().split()).strip(" .!,")
        if not t or len(t) > 60:
            return None
        m = re.match(r"^(?:please\s+)?(open|launch|start|run|fire up|bring up)\s+"
                     r"(?:the\s+|my\s+)?(.+)$", t)
        if m:
            target = m.group(2).strip(" .!,")
            if not target or target in ("it", "that", "this"):
                return None
            try:
                return tools.open_app(target)
            except Exception:
                return None
        m = re.match(r"^(?:play|put on)\s+(?:some\s+|a\s+|the\s+)?(.+)$", t)
        if m and ("music" in t or "song" in t or m.group(1) in ("music", "songs")):
            try:
                return tools.play_music("" if m.group(1) in ("music", "songs")
                                        else m.group(1))
            except Exception:
                return None
        if t in ("open the browser", "open browser", "browse"):
            return tools.open_preferred("browser")
        return None

    def _chat_once(self, user_message, on_text, on_event, key=""):
        self.reload()
        self.cancel_evt.clear()
        cfg = self.cfg

        if (cfg.get("provider") or "gemini").lower() in ("openai", "gateway", "compatible"):
            return self.chat_openai(user_message, on_text, on_event, key=key)

        client = self._get_client(key)

        store.add_chat("user", user_message)

        history = store.recent_chat(limit=24)
        contents = []
        for m in history:
            if m["role"] not in ("user", "assistant"):
                continue  # skip reminder notifications and other UI notices
            contents.append(
                types.Content(
                    role="user" if m["role"] == "user" else "model",
                    parts=[types.Part(text=m["content"])],
                )
            )

        # Soft memory context: recent facts + upcoming reminders
        facts = store.list_memories(30)
        rems = store.list_reminders()
        ctx_bits = []
        if facts:
            ctx_bits.append(
                "Things you already remember about the user:\n"
                + "\n".join(f"- {f['content']}" for f in facts)
            )
        if rems:
            ctx_bits.append(
                "Their open reminders:\n"
                + "\n".join(
                    f"- #{r['id']} {r['due_at']} {r['text']}" for r in rems[:15]
                )
            )
        system = system_prompt(cfg, self)
        if ctx_bits:
            system += "\n\nCONTEXT\n" + "\n\n".join(ctx_bits)

        decls = tools.declarations(cfg)
        fn_map = {n: tools.TOOL_FUNCS[n] for n in tools.enabled_names(cfg)}
        gtool = [types.Tool(function_declarations=decls)] if decls else None
        gen_cfg = types.GenerateContentConfig(
            system_instruction=system,
            tools=gtool,
            temperature=0.7,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

        models = [cfg.get("model") or MODEL_FALLBACKS[0]]
        if cfg.get("auto_model", True):
            models += MODEL_FALLBACKS
        last_err = None
        tried = []
        discovered = False

        for model in dict.fromkeys(models):
            self._check_cancel()
            try:
                return self._run_loop(client, model, contents, gen_cfg, fn_map,
                                      on_text, on_event)
            except Exception as e:
                last_err = e
                msg = str(e)
                verdict = self.classify_error(msg).split(" - ")[0]
                tried.append("%s: %s" % (model, verdict))
                # a dead key or a blocked project will fail on every model -
                # stop early and explain instead of burning through the list
                if (verdict == "MODEL NOT FOUND" and not discovered
                        and cfg.get("auto_model", True)):
                    # the model ID was retired - ask Google what exists now
                    discovered = True
                    if on_event:
                        on_event("that model is retired - looking up live models...")
                    found, derr = self.discover_models()
                    if found:
                        if on_event:
                            on_event("using %s" % found[0])
                        models = found[:6] + models
                        continue
                if verdict in ("KEY INVALID", "PROJECT BLOCKED", "PROJECT RESTRICTED",
                               "NETWORK", "PERMISSION DENIED"):
                    raw = msg.strip().replace("\n", " ")[:180]
                    raise RuntimeError(
                        "%s\n\nGoogle said: %s\n\n(Open Settings -> Diagnose key "
                        "for the full picture.)" % (self.classify_error(msg), raw)
                    )
                if on_event:
                    on_event("%s unavailable (%s), trying another model..." % (model, verdict))
                continue

        # Last resort: the SDK path may be the thing that's broken (a known issue
        # with brand-new AQ. auth keys). Try the same turn over plain REST.
        if on_event:
            on_event("SDK path failed - retrying over plain REST...")
        rest_errors = []
        for model in dict.fromkeys(models):
            try:
                return self.chat_rest(user_message, model, on_text, on_event)
            except Exception as e:
                rest_errors.append("%s: %s" % (model, self.classify_error(str(e))[:80]))
                if "KEY INVALID" in self.classify_error(str(e)) or \
                   "PROJECT BLOCKED" in self.classify_error(str(e)):
                    break
        raise RuntimeError(
            "No model worked, over the SDK or plain REST.\n\nTried:\n  "
            + "\n  ".join(tried[-4:] + rest_errors[-3:])
            + "\n\nOpen Settings -> Diagnose key for the full picture."
        )

    def _run_loop(self, client, model, contents, gen_cfg, fn_map, on_text, on_event):
        reply_parts = []
        for _hop in range(8):  # max tool-call rounds per turn
            self._check_cancel()
            stream = client.models.generate_content_stream(
                model=model, contents=contents, config=gen_cfg
            )
            turn_text = []
            calls = []
            for chunk in stream:
                self._check_cancel()   # so the Stop button bites immediately
                for cand in (chunk.candidates or []):
                    for part in (cand.content.parts or []) if cand.content else []:
                        if getattr(part, "function_call", None):
                            calls.append(part.function_call)
                        elif getattr(part, "text", None):
                            turn_text.append(part.text)
                            if on_text:
                                on_text(part.text)

            text_so_far = "".join(turn_text)
            if text_so_far.strip():
                reply_parts.append(text_so_far)

            if not calls:
                final = "\n".join(reply_parts).strip()
                store.add_chat("assistant", final)
                return final

            # record the model's tool request, then answer each call
            contents.append(
                types.Content(
                    role="model",
                    parts=[types.Part(function_call=c) for c in calls],
                )
            )
            response_parts = []
            for call in calls:
                name = call.name
                args = dict(call.args or {})
                fn = fn_map.get(name)
                if on_event:
                    on_event(f"using {name.replace('_', ' ')}...")
                if fn is None:
                    result = f"Tool '{name}' is not enabled."
                else:
                    try:
                        result = fn(**args)
                    except TypeError as e:
                        result = f"Bad arguments for {name}: {e}"
                    except Exception as e:
                        result = f"{name} failed: {e}"
                response_parts.append(
                    types.Part.from_function_response(
                        name=name, response={"result": str(result)}
                    )
                )
            contents.append(types.Content(role="user", parts=response_parts))

        final = "\n".join(reply_parts).strip() or "I stopped after too many steps."
        store.add_chat("assistant", final)
        return final

    # ------------------------------------------------------------ helpers
    def draft_only(self, instructions: str, on_text=None):
        """Used for the 'Draft' quick action: no tools, pure writing."""
        self.reload()
        cfg = self.cfg
        if (cfg.get("provider") or "gemini").lower() in ("openai", "gateway", "compatible"):
            return self.chat_openai(instructions + "\n\n(Return only the finished "
                                    "text, ready to send. No commentary.)",
                                    on_text=on_text)
        client = self._get_client()
        prompt = (
            system_prompt(cfg, self)
            + "\n\nFor this task do NOT use tools and do NOT narrate. "
            "Return only the finished text, ready to copy and send."
        )
        model = cfg.get("model") or MODEL_FALLBACKS[0]
        out = []
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=instructions,
            config=types.GenerateContentConfig(
                system_instruction=prompt, temperature=0.75
            ),
        ):
            for cand in (chunk.candidates or []):
                for part in (cand.content.parts or []) if cand.content else []:
                    if getattr(part, "text", None):
                        out.append(part.text)
                        if on_text:
                            on_text(part.text)
        return "".join(out)
