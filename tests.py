"""
tests.py — quick self-check after installing. Run:  python tests.py
It exercises storage, reminders and the tool layer without needing an API key.
"""

import datetime
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import store
import tools

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  -> {detail}" if detail and not cond else ""))


def main():
    print("\nPocket Agent self-check\n" + "-" * 40)
    store.init_db()

    # storage
    store.clear_chat()
    store.add_chat("user", "hello")
    store.add_chat("assistant", "hi")
    rows = store.recent_chat(10)
    check("chat history saves and loads", len(rows) == 2 and rows[0]["content"] == "hello")

    # reminders
    due = (datetime.datetime.now() + datetime.timedelta(hours=2)).replace(microsecond=0)
    out = tools.set_reminder("self-check reminder", due.isoformat(), "none")
    check("set_reminder accepts ISO time", out.startswith("Reminder #"), out)
    check("bad time is rejected", tools.set_reminder("x", "tomorrow", "none").startswith("ERROR"))
    listing = tools.list_reminders()
    check("reminder appears in list", "self-check reminder" in listing)
    check("complete_reminder matches by text",
          "done" in tools.complete_reminder("self-check").lower())

    # repeating maths
    nxt = store.next_occurrence("2026-11-06T09:00", "weekdays")
    check("weekdays skip the weekend", nxt.startswith("2026-11-09"), nxt)
    check("daily adds a day",
          store.next_occurrence("2026-11-06T09:00", "daily").startswith("2026-11-07"))

    # memory
    tools.remember("self-check fact: user likes tea")
    check("memory saves", "tea" in tools.recall("tea"))

    # files
    cfg = config.load()
    out = tools.write_file("selfcheck.txt", "round trip works")
    check("write_file works", "Saved" in out, out)
    check("read_file round-trips", "round trip works" in tools.read_file(
        os.path.join(cfg["files_dir"], "selfcheck.txt")))

    # permissions
    cfg["allow_commands"] = False
    config.save(cfg)
    check("shell is blocked by default", "Blocked" in tools.run_command("echo hi"))
    check("keyboard is blocked by default", "Blocked" in tools.type_text("hi"))

    # model discovery / ranking - IDs get retired, so this must not be hard-coded
    from agent import score_model
    check("newest flash outranks older ones",
          score_model("gemini-3.8-flash") > score_model("gemini-3.6-flash")
          > score_model("gemini-2.5-flash"))
    check("previews are demoted", score_model("gemini-3.8-flash") >
          score_model("gemini-3.8-flash-preview"))
    check("default model is a current one",
          config.DEFAULTS["model"] == "gemini-3.8-flash", config.DEFAULTS["model"])

    # key formats - Google now issues AQ. auth keys, older ones are AIza
    from agent import looks_like_key, key_kind, Agent
    aq = "AQ.Ab8RN6JywhTw4HqaKzEXAMPLEKEY1234567890abcdef"
    aiza = "AIzaSyBxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    check("accepts new AQ. auth keys", looks_like_key(aq), key_kind(aq))
    check("accepts legacy AIza keys", looks_like_key(aiza), key_kind(aiza))
    check("rejects a truncated key", not looks_like_key("AQ.Ab8"))
    check("rejects a key with spaces", not looks_like_key("AQ.abc def ghi jkl mno pqr stu"))

    # error translation
    v = Agent.classify_error
    check("project block is recognised",
          v("403 PERMISSION_DENIED: Your project has been denied access").startswith("PROJECT BLOCKED"))
    check("free-tier block is recognised",
          v("400 FAILED_PRECONDITION: The Gemini API free tier is not available").startswith("PROJECT BLOCKED"))
    check("zero-quota is read as not-on-free-tier",
          v("429 RESOURCE_EXHAUSTED limit: 0").startswith("MODEL NOT ON FREE TIER"))
    check("token-type bug is named",
          v("401 ACCESS_TOKEN_TYPE_UNSUPPORTED").startswith("TOKEN-TYPE BUG"))
    check("retired model is recognised",
          v("404 NOT_FOUND: models/x is not found").startswith("MODEL NOT FOUND"))

    # tool schemas
    decls = tools.declarations({**cfg, "allow_commands": True, "allow_keyboard": True,
                                "allow_screen": True, "allow_email": True,
                                "allow_sms": True, "allow_calls": True})
    names = [d["name"] for d in decls]
    check("tools are declared with schemas", len(decls) >= 20 and all(
        d.get("description") and d.get("parameters") for d in decls), names)
    check("dangerous tools gated behind switches",
          "run_command" not in [d["name"] for d in tools.declarations(cfg)])

    # new full-access tools must respect their switches
    cfg2 = {**cfg, "allow_screen": False, "allow_email": False, "allow_sms": False,
            "allow_calls": False, "allow_commands": False}
    names = tools.enabled_names(cfg2)
    check("screen tools hidden by default", "read_screen" not in names)
    check("email tools hidden by default", "email_me" not in names)
    check("call tools hidden by default", "phone_call" not in names)

    cfg3 = {**cfg, "allow_screen": True, "allow_email": True, "allow_sms": True,
            "allow_calls": True, "allow_commands": True}
    names3 = tools.enabled_names(cfg3)
    check("screen tools appear when allowed", "read_screen" in names3)
    check("email appears when allowed", "email_me" in names3)
    check("calling appears when allowed", "phone_call" in names3)
    check("every enabled tool has a schema",
          all(n in tools.SPECS for n in names3), [n for n in names3 if n not in tools.SPECS])

    # tools that are off must refuse, not crash
    off = {**cfg, "allow_screen": False, "allow_email": False, "allow_calls": False}
    config.save(off)
    check("read_screen refuses politely", "Blocked" in tools.read_screen())
    check("email_me refuses politely", "Blocked" in tools.email_me("s", "b"))
    check("phone_call refuses politely", "Blocked" in tools.phone_call("+254700000000"))
    config.save(cfg)


    # ---------------------------------------------------- wake word + learning
    import memory_learn
    import voice
    import voiceprint

    for phrase, want in [
        ("hey zinger, open chrome", "open chrome"),
        ("Hey Zinger what's the time", "what's the time"),
        ("hey zinga play music", "play music"),
        ("hi singer, remind me", "remind me"),
    ]:
        check("wake word: %r" % phrase, voice.contains_wake(phrase)
              and voice.strip_wake(phrase) == want, voice.strip_wake(phrase))
    for phrase in ("hello there", "what time is it", "open chrome"):
        check("no false wake: %r" % phrase, not voice.contains_wake(phrase))

    memory_learn.set_profile("selfcheck_name", "Tester")
    check("teach_me stores a fact", memory_learn.get_profile().get("selfcheck_name") == "Tester")
    check("who_am_i reads it back", "Tester" in tools.who_am_i())
    memory_learn.delete_profile("selfcheck_name")
    check("profile fact can be deleted",
          "selfcheck_name" not in memory_learn.get_profile())

    memory_learn.remember("my favourite drink is chai")
    check("plain sentence becomes a fact",
          memory_learn.get_profile().get("favourite_drink") == "chai",
          str(memory_learn.get_profile()))
    memory_learn.delete_profile("favourite_drink")

    memory_learn.save_skill("selfcheck skill", ["open chrome", "open spotify"])
    check("skill is saved", any(s["name"] == "selfcheck skill" for s in memory_learn.list_skills()))
    check("skill is found by trigger",
          memory_learn.find_skill("selfcheck skill") is not None)
    memory_learn.use_skill("selfcheck skill")
    check("skill use is counted",
          [s for s in memory_learn.list_skills() if s["name"] == "selfcheck skill"][0]["uses"] >= 1)
    memory_learn.delete_skill("selfcheck skill")
    check("skill can be deleted",
          not any(s["name"] == "selfcheck skill" for s in memory_learn.list_skills()))

    memory_learn.learn_route("music", "spotify.exe")
    check("app route is remembered",
          memory_learn.best_route("music") == "spotify.exe")
    check("learned context reaches the prompt",
          "LEARNED CONTEXT" in memory_learn.summary_for_prompt())

    # voiceprint maths
    check("voiceprint similarity is 1.0 for identical",
          abs(voiceprint.similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) - 1.0) < 0.001)
    check("voiceprint separates different speakers",
          voiceprint.similarity([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]) < 0.55)
    check("centroid averages samples",
          voiceprint.centroid([[1.0, 1.0], [3.0, 3.0]]) == [2.0, 2.0],
          voiceprint.centroid([[1.0, 1.0], [3.0, 3.0]]))
    check("empty sample is rejected", not voiceprint.features("/nope/missing.wav"))

    # app defaults + skills reach the tool list
    check("opening apps works without shell access",
          {"open_preferred", "open_website", "play_music"} <= set(names))
    off_cfg = {**cfg2, "allow_apps": False}
    check("app launching can be switched off",
          "open_preferred" not in tools.enabled_names(off_cfg))
    cfg2 = config.load()
    check("app defaults are in config",
          cfg2.get("app_defaults", {}).get("browser") == "chrome")
    names = tools.enabled_names(cfg2)
    for t in ("learn_skill", "use_skill", "teach_me", "who_am_i"):
        check("tool %s is exposed" % t, t in names)


    # ------------------------------------------------- voice out + app launch
    import voice as _v

    sp = _v.Speaker()
    check("speaker reports its own health", isinstance(sp.diagnose(), str))
    check("speaker says nothing on empty text", sp.say("") is False)
    check("speaker done-callback can be set",
          (sp.set_on_done(lambda: None) is None))

    check("launcher rejects an empty name", tools._launch("") is False)
    check("launcher rejects junk instead of claiming success",
          tools._launch("definitely-not-a-real-app-xyz") is False)
    out = tools.open_app("definitely-not-a-real-app-xyz")
    check("open_app is honest about failure",
          "Couldn't launch" in out, out)
    check("open_app respects the allow_apps switch",
          "Blocked" in tools.open_app("chrome")
          if not config.load().get("allow_apps", True) else True)

    # Windows resolution logic (safe on any OS - just must not raise)
    for name in ("chrome", "spotify", "notepad", "calculator", "edge"):
        res = tools._find_on_windows(name)
        check("app lookup for %r is safe" % name, res is None or isinstance(res, str))
    check("intent_of maps chrome to browser",
          tools.intent_of("chrome.exe") == "browser")
    check("intent_of maps spotify to music",
          tools.intent_of("Spotify.exe") == "music")

    # ----------------------------------------------------------- multiple keys
    import agent as _agent

    cfgk = config.load()
    saved = {k: cfgk.get(k) for k in ("api_key", "api_keys", "key_index")}
    cfgk.update(api_key="AQ.first", api_keys=["AQ.second", "AQ.third"],
                key_index=0)
    config.save(cfgk)
    ag = _agent.Agent()
    check("all keys are known", len(ag.keys()) == 3)
    check("primary key comes first", ag.keys()[0] == "AQ.first")
    ag.mark_key_good("AQ.third")
    check("rotation remembers the working key",
          _agent.Agent().keys()[0] == "AQ.third")
    check("quota errors trigger failover",
          ag.key_is_dead_error("429 RESOURCE_EXHAUSTED"))
    check("invalid key triggers failover",
          ag.key_is_dead_error("API key not valid. Please pass a valid API key."))
    check("a network error does not burn a key",
          not ag.key_is_dead_error("connection reset by peer"))
    cfgk = config.load()
    cfgk.update(**saved)
    config.save(cfgk)

    # ----------------------------------------------------------- face only
    cfgo = config.load()
    check("watermark-first is the default",
          cfgo.get("start_as_watermark", True) is True)
    check("conversation window exists",
          hasattr(__import__("ui"), "ConversationLoop"))

    # cleanup
    try:
        os.remove(os.path.join(cfg["files_dir"], "selfcheck.txt"))
    except OSError:
        pass
    store.clear_chat()

    print("-" * 40)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("Failed:", ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
