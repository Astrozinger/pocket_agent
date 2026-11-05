"""
voice.py — speaking and listening for Pocket.

Both directions degrade gracefully: if a microphone or speech engine is missing,
the app still works by typing. Nothing here ever blocks the UI thread.
"""

import os
import queue
import threading


# --------------------------------------------------------------------- speech out
_PS_SPEAK = r"""
Add-Type -AssemblyName System.Speech;
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;
$s.Rate = {rate};
$s.Volume = {volume};
{voice}
$s.Speak([Console]::In.ReadToEnd());
"""


class Speaker:
    """Text to speech.

    pyttsx3 (SAPI5) is the primary engine. On Windows it is backed up by
    PowerShell's System.Speech, because pyttsx3's driver silently produces no
    audio on some machines (no default voice, a USB headset, a 64/32-bit
    mismatch). Whichever engine actually works is remembered and reused.
    """

    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()
        self._queue = queue.Queue()
        self._worker = None
        self._ok = None
        self._backend = None          # "pyttsx3" | "powershell" | None
        self._rate = 178
        self._pitch = 50
        self._volume = 1.0
        self._on_done = None          # set by the UI: fired when speech ends
        self._speaking = False
        self.last_error = ""

    # ---------------------------------------------------------------- config
    def set_voice_character(self, rate: int = 178, pitch: int = 50,
                            volume: float = 1.0):
        """Let the UI make the voice sound fresh or worn out."""
        self._rate = int(rate)
        self._pitch = int(pitch)
        self._volume = float(volume)
        if self._engine:
            try:
                self._engine.setProperty("rate", self._rate)
                self._engine.setProperty("volume", self._volume)
                try:
                    self._engine.setProperty("pitch", self._pitch)
                except Exception:
                    pass
            except Exception:
                pass

    def set_on_done(self, fn):
        """fn() is called whenever an utterance finishes, so the ears can re-open."""
        self._on_done = fn

    def is_speaking(self) -> bool:
        return self._speaking

    # ------------------------------------------------------------- backends
    def _pyttsx3_ok(self) -> bool:
        try:
            import pyttsx3

            if self._engine is None:
                self._engine = pyttsx3.init()
                self._engine.setProperty("rate", self._rate)
                self._engine.setProperty("volume", self._volume)
                try:
                    self._engine.setProperty("pitch", self._pitch)
                except Exception:
                    pass
                self._pick_voice()
            return True
        except Exception as e:
            self.last_error = "pyttsx3: %s" % e
            self._engine = None
            return False

    def _pick_voice(self):
        """Prefer a lively local voice over the default robotic one."""
        try:
            import platform

            if platform.system() != "Windows":
                return
            nice = ("zira", "aria", "jenny", "sonia", "female", "guy", "david",
                    "hazel", "george", "eva")
            voices = self._engine.getProperty("voices") or []
            for want in nice:
                for v in voices:
                    name = (getattr(v, "name", "") or "").lower()
                    if want in name:
                        self._engine.setProperty("voice", v.id)
                        return
        except Exception:
            pass

    def _powershell_say(self, text: str) -> bool:
        """Windows-only last resort: System.Speech through PowerShell."""
        import platform
        import subprocess

        if platform.system() != "Windows":
            return False
        try:
            voice = ""
            ps = _PS_SPEAK.format(
                rate=max(-10, min(10, int((self._rate - 180) / 25))),
                volume=max(0, min(100, int(self._volume * 100))),
                voice=voice,
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                input=text.encode("utf-8", "ignore"),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=max(20, len(text) // 8),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except Exception as e:
            self.last_error = "powershell: %s" % e
            return False

    def available(self) -> bool:
        """Can we make sound at all? Cheap check, no engine start."""
        if self._ok is not None:
            return self._ok
        try:
            import pyttsx3  # noqa: F401

            self._ok = True
            return True
        except Exception:
            pass
        import platform

        if platform.system() == "Windows":
            self._ok = True          # PowerShell fallback is always there
            return True
        self._ok = False
        self.last_error = self.last_error or "no speech engine installed"
        return False

    def diagnose(self) -> str:
        """Human-readable reason speech does or doesn't work."""
        import platform

        bits = ["platform: %s" % platform.system()]
        try:
            import pyttsx3

            bits.append("pyttsx3: installed")
            try:
                eng = pyttsx3.init()
                voices = eng.getProperty("voices") or []
                bits.append("voices: %d (%s)" % (
                    len(voices),
                    ", ".join((getattr(v, "name", "?") or "?")[:18] for v in voices[:4])))
                try:
                    eng.stop()
                except Exception:
                    pass
            except Exception as e:
                bits.append("voice list failed: %s" % e)
        except Exception as e:
            bits.append("pyttsx3: NOT installed (%s)" % e)
        bits.append("last error: %s" % (self.last_error or "none"))
        return " | ".join(bits)

    # ---------------------------------------------------------------- worker
    def _ensure_worker(self):
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _run(self):
        while True:
            text = self._queue.get()
            if text is None:
                break
            self._speaking = True
            spoke = False
            try:
                if self._backend in (None, "pyttsx3") and self._pyttsx3_ok():
                    try:
                        self._engine.say(text)
                        self._engine.runAndWait()
                        spoke = True
                        self._backend = "pyttsx3"
                    except Exception as e:
                        self.last_error = "pyttsx3 speak: %s" % e
                        try:
                            self._engine.stop()
                        except Exception:
                            pass
                if not spoke and self._powershell_say(text):
                    spoke = True
                    self._backend = "powershell"
            finally:
                self._speaking = False
                cb = self._on_done
                if cb:
                    try:
                        cb()
                    except Exception:
                        pass
                if self._queue.empty():
                    self._queue.task_done() if False else None

    def say(self, text: str, clean: bool = True):
        """Queue speech. Returns immediately."""
        if not text:
            return False
        if clean:
            text = _speakable(text)
        if not text:
            return False
        if not self.available():
            return False
        self._ensure_worker()
        self._speaking = True
        self._queue.put(text)
        return True

    def say_blocking(self, text: str, clean: bool = True, timeout: float = 60):
        """Speak now and wait — used by the 'Test voice' button."""
        if clean:
            text = _speakable(text)
        if not text:
            return False
        if self._pyttsx3_ok():
            try:
                self._engine.say(text)
                self._engine.runAndWait()
                self._backend = "pyttsx3"
                return True
            except Exception as e:
                self.last_error = "pyttsx3 speak: %s" % e
        return self._powershell_say(text)

    def stop(self):
        try:
            if self._engine:
                self._engine.stop()
        except Exception:
            pass
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Exception:
                break


def _speakable(text: str) -> str:
    """Strip markdown/code so the voice doesn't read asterisks and backticks."""
    import re

    t = re.sub(r"```.*?```", " (code block) ", text, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", t)
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.M)
    t = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", t)
    t = re.sub(r"[#_>]+", " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t[:600]


# --------------------------------------------------------------------- speech in
class Listener:
    """Microphone -> text, using Qt's own audio stack (no pyaudio, no compiler).

    Records with QAudioSource into an in-memory WAV, then hands it to
    SpeechRecognition for transcription. SpeechRecognition is pure Python, so it
    installs everywhere; only the *device* part needed pyaudio, and Qt replaces it.
    """

    def __init__(self):
        self._sr = None
        self._import_error = None
        self._busy = threading.Event()
        self._available = None

    # ---------------------------------------------------------------- checks
    def available(self) -> bool:
        if self._available is not None:
            return self._available
        ok = True
        if not _qt_audio_ok():
            ok = False
            self._import_error = ("Qt audio isn't available. Reinstall PyQt6: "
                                  "pip install --force-reinstall PyQt6")
        try:
            import speech_recognition as sr

            self._sr = sr
        except Exception as e:
            ok = False
            self._import_error = ("SpeechRecognition is missing. Run: "
                                  "pip install SpeechRecognition  (%s)" % e)
        self._available = ok
        return ok

    @property
    def problem(self) -> str:
        return self._import_error or ""

    @property
    def busy(self) -> bool:
        return self._busy.is_set()

    # ---------------------------------------------------------------- record
    def _record_wav(self, seconds: float = 5.0, stop_evt=None,
                    on_level=None) -> str:
        """Record the default mic to a temp WAV. Returns the path."""
        from PyQt6.QtCore import QTimer, QEventLoop, QIODevice
        from PyQt6.QtMultimedia import (QAudioFormat, QAudioSource, QMediaDevices)

        device = QMediaDevices.defaultAudioInput()
        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()

        audio_in = QAudioSource(device, fmt)
        io = audio_in.start()          # pull mode: we read from the device
        if io is None:
            raise RuntimeError("The microphone could not be opened (is it in use, "
                               "or blocked in Windows privacy settings?).")

        frames = bytearray()
        loop = QEventLoop()
        elapsed = {"t": 0.0}
        speech_seen = {"t": None}
        silence = {"t": 0.0}
        chunk_ms = 100

        def tick():
            nonlocal frames
            data = io.readAll()
            if data and data.size():
                raw = bytes(data)
                frames.extend(raw)
                if on_level:
                    on_level(_rms(raw))
                level = _rms(raw)
                if level > 0.06:
                    speech_seen["t"] = elapsed["t"]
                    silence["t"] = 0.0
                else:
                    silence["t"] += chunk_ms / 1000.0
            elapsed["t"] += chunk_ms / 1000.0
            done = (elapsed["t"] >= seconds
                    or (stop_evt is not None and stop_evt.is_set())
                    or (speech_seen["t"] is not None and silence["t"] >= 1.1))
            if done:
                loop.quit()

        timer = QTimer()
        timer.timeout.connect(tick)
        timer.start(chunk_ms)
        loop.exec()
        timer.stop()
        try:
            audio_in.stop()
        except Exception:
            pass

        import tempfile
        import wave

        path = os.path.join(tempfile.gettempdir(), "pocket_voice.wav")
        with wave.open(path, "wb") as wf:
            wf.setnchannels(max(1, fmt.channelCount()))
            wf.setsampwidth(2)
            wf.setframerate(fmt.sampleRate())
            wf.writeframes(bytes(frames))
        if not frames:
            raise RuntimeError("I recorded nothing — check the microphone.")
        self._last_clip = path
        return path

    # ----------------------------------------------------------------- listen
    def record_clip(self, seconds: float = 6.0, stop_evt=None, on_level=None,
                    on_state=None):
        """Record one clip and return its path (or None). Keeps the file."""
        if not self.available() or self._busy.is_set():
            return None
        self._busy.set()
        try:
            if on_state:
                on_state("listening")
            return self._record_wav(seconds=seconds, stop_evt=stop_evt,
                                    on_level=on_level)
        except Exception:
            return None
        finally:
            self._busy.clear()

    def transcribe(self, path: str, on_state=None):
        """WAV -> text. Returns (text, error). Never deletes the clip."""
        if on_state:
            on_state("thinking")
        if not self.available():
            return None, self.problem
        if not path or not os.path.exists(path):
            return None, "Nothing was recorded."
        sr = self._sr
        try:
            with sr.AudioFile(path) as source:
                audio = sr.Recognizer().record(source)
            try:
                return sr.Recognizer().recognize_google(audio), None
            except sr.UnknownValueError:
                return None, "I couldn't make that out — try again."
            except sr.RequestError as e:
                return None, ("Transcribing needs internet (Google's free "
                              "service). Error: %s" % e)
        except Exception as e:
            return None, "Audio problem: %s" % e

    def transcribe_last(self, on_state=None):
        """Convenience for the loop: transcribe whatever clip was just recorded."""
        if on_state:
            on_state("thinking")
        return self.transcribe(getattr(self, "_last_clip", None))

    def listen_once(self, timeout: float = 6.0, phrase_limit: float = 12.0,
                    on_state=None, stop_evt=None, on_level=None):
        """Record one phrase and transcribe it. Returns (text, error)."""
        path = self.record_clip(seconds=phrase_limit, stop_evt=stop_evt,
                                on_level=on_level, on_state=on_state)
        self._last_clip = path
        if on_state:
            on_state("thinking")
        try:
            return self.transcribe(path)
        finally:
            self._cleanup(path)


    @staticmethod
    def _cleanup(path: str):
        if not path:
            return
        try:
            os.remove(path)
        except OSError:
            pass


def _rms(raw: bytes) -> float:
    """Root-mean-square of 16-bit PCM, normalised to 0..1 (no audioop needed)."""
    if not raw:
        return 0.0
    n = len(raw) // 2
    if n == 0:
        return 0.0
    total = 0
    for i in range(0, n * 2, 2):
        v = int.from_bytes(raw[i:i + 2], "little", signed=True)
        total += v * v
    rms = (total / n) ** 0.5
    return min(1.0, rms / 6000.0)


def _qt_audio_ok() -> bool:
    try:
        from PyQt6.QtMultimedia import QAudioSource  # noqa: F401

        return True
    except Exception:
        return False




# --------------------------------------------------------------------- wake word
def contains_wake(text: str, phrase: str = "hey zinger") -> bool:
    """Tolerant match for 'hey zinger' — handles Zinger/singer/zinga slips."""
    if not text:
        return False
    t = " ".join(text.lower().replace(",", " ").replace(".", " ").split())
    p = " ".join((phrase or "hey zinger").lower().split())
    if p and p in t:
        return True
    # common mis-hearings of "zinger"
    for variant in WAKE_VARIANTS:
        if variant in t:
            return True
    # "hey" + something short that starts with z/s and ends in -er
    words = t.split()
    for i, w in enumerate(words):
        if w in ("hey", "hi", "hay", "ey") and i + 1 < len(words):
            nxt = words[i + 1]
            if nxt[:1] in ("z", "s") and nxt[-2:] in ("er", "a", "ah"):
                return True
    # last resort: one mangled token that looks like a mis-heard "zinger"
    return any(_fuzzy_zinger(w) for w in words)


WAKE_VARIANTS = ("zinger", "zinga", "singer", "zinjer", "zingger", "zing er",
                 "senga", "zingah", "zinga's", "zinger's")


def _fuzzy_zinger(word: str) -> bool:
    """True if a single word is probably a mangled 'zinger' (e.g. 'singa')."""
    import difflib

    return len(word) >= 4 and difflib.SequenceMatcher(
        None, word, "zinger").ratio() >= 0.72


def _clean(word: str) -> str:
    return word.lower().strip(" ,.-!?;:")


GREETINGS = ("hey", "hi", "hay", "ey", "ok", "okay")


def strip_wake(text: str, phrase: str = "hey zinger") -> str:
    """Remove the wake phrase so 'hey zinger, open chrome' becomes 'open chrome'."""
    if not text:
        return ""
    words = text.split()
    low = [_clean(w) for w in words]

    # 1. the exact phrase, as consecutive words
    ptokens = (phrase or "hey zinger").lower().split()
    n = len(ptokens)
    for i in range(max(0, len(low) - n + 1)):
        if low[i:i + n] == ptokens:
            del words[i:i + n]
            return " ".join(words).strip(" ,.-!?;:")

    # 2. a single mis-heard token, plus any greeting in front of it
    for i, w in enumerate(low):
        if w in WAKE_VARIANTS or _fuzzy_zinger(w):
            start = i
            if i > 0 and low[i - 1] in GREETINGS:
                start = i - 1
            del words[start:i + 1]
            return " ".join(words).strip(" ,.-!?;:")

    return text.strip(" ,.-!?;:")


class WakeListener:
    """Cheap always-on loop: listens in ~4s windows and only reacts on the phrase.

    Full transcription of every window would burn quota, so it looks for the wake
    word in each short clip and only then takes the real request.
    """

    def __init__(self, listener: Listener, phrase: str = "hey zinger"):
        self.listener = listener
        self.phrase = phrase

    def wait_for_wake(self, stop_evt=None, on_level=None, on_state=None,
                      max_windows: int = 45):
        """Block until the phrase is heard. Returns (ok, leftover_text)."""
        for _ in range(max_windows):
            if stop_evt is not None and stop_evt.is_set():
                return False, ""
            text, err = self.listener.listen_once(
                timeout=4.0, phrase_limit=4.5, on_state=on_state,
                stop_evt=stop_evt, on_level=on_level,
            )
            if text and contains_wake(text, self.phrase):
                return True, strip_wake(text, self.phrase)
        return False, ""

# --------------------------------------------------------------------- hotkey
class Hotkey:
    """Global hotkey (works even when Pocket is in the background).

    Default: Ctrl+Alt+Space  — press to talk.
             Ctrl+Alt+Q      — ask/answer without speaking.
    Uses pynput, which needs no admin rights on Windows.
    """

    def __init__(self, on_talk, on_ask=None):
        self._listener = None
        self._ok = None
        self._on_talk = on_talk
        self._on_ask = on_ask

    def available(self) -> bool:
        if self._ok is not None:
            return self._ok
        try:
            from pynput import keyboard  # noqa: F401

            self._ok = True
        except Exception:
            self._ok = False
        return self._ok

    def start(self) -> bool:
        if not self.available() or self._listener is not None:
            return False
        try:
            from pynput import keyboard
        except Exception:
            return False

        combo_talk = {keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.Key.space}
        combo_ask = {keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.KeyCode.from_char("q")}
        state = {"down": set()}

        def on_press(key):
            state["down"].add(key)
            if combo_talk.issubset(state["down"]):
                state["down"].clear()
                _spawn(self._on_talk)
            elif combo_ask.issubset(state["down"]) and self._on_ask:
                state["down"].clear()
                _spawn(self._on_ask)

        def on_release(key):
            state["down"].discard(key)

        try:
            self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._listener.daemon = True
            self._listener.start()
            return True
        except Exception:
            self._ok = False
            return False

    def stop(self):
        try:
            if self._listener:
                self._listener.stop()
        except Exception:
            pass
        self._listener = None


def _spawn(fn):
    if fn:
        threading.Thread(target=fn, daemon=True).start()
