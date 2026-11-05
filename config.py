"""config.py — tiny JSON settings file stored in ~/PocketAgent/config.json"""

import json
import os

APP_DIR = os.path.join(os.path.expanduser("~"), "PocketAgent")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

DEFAULTS = {
    "api_key": "",
    "api_keys": [],          # extra Gemini keys, used in turn when one hits its quota
    "openai_keys": [],       # extra gateway keys
    "key_index": 0,
    "provider": "gemini",          # gemini | openai (any OpenAI-compatible gateway)
    "openai_base_url": "",
    "openai_key": "",
    "openai_model": "",
    "model": "gemini-3.8-flash",
    "assistant_name": "Pocket",
    "user_name": "",
    "auto_model": True,          # re-check with Google when a model ID dies
    "allow_commands": False,   # run shell commands on the laptop
    "allow_files": True,       # read/write files
    "allow_keyboard": False,   # type text / press keys via pyautogui
    "allow_apps": True,
    "allow_learning": True,      # learn skills, profile, app prefs
    "allow_screen": False,     # read what's on screen (OCR) / screenshots
    "allow_email": False,      # send email via the user's Gmail + App Password
    "allow_sms": False,        # text messages via Phone Link
    "allow_calls": False,      # place calls (Twilio if configured, else dialler)
    "email_address": "",
    "email_app_password": "",
    "twilio_sid": "",
    "twilio_token": "",
    "twilio_from": "",
    # voice
    "speak_replies": True,
    "always_listening": False,   # ears stay on; no hotkey needed
    "hotkey_talk": "ctrl+alt+space",
    "voice_autosend": True,
    "wake_word": "hey zinger",
    "wake_enabled": False,
    "voice_id_enabled": False,
    "voice_threshold": 0.45,
    "overlay_enabled": True,
    "start_as_watermark": True,
    "app_defaults": {"browser": "chrome", "music": "spotify"},
    "files_dir": os.path.join(APP_DIR, "files"),
}


def load() -> dict:
    os.makedirs(APP_DIR, exist_ok=True)
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f) or {})
        except Exception:
            pass
    return cfg


def save(cfg: dict):
    os.makedirs(APP_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    try:  # keep the key private on posix
        os.chmod(CONFIG_PATH, 0o600)
    except Exception:
        pass
