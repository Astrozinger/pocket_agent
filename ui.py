"""
ui.py — Pocket Agent desktop window (PyQt6).

Run:  python app.py
"""

import datetime
import html
import os
import re
import sys
import threading
import time

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QDateTime
from PyQt6.QtGui import (QAction, QFont, QIcon, QPixmap, QColor, QPainter,
                         QTextCursor, QTextDocument)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateTimeEdit, QDialog, QFileDialog,
    QFrame, QMenu,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy,
    QScrollArea, QStackedWidget, QSystemTrayIcon, QTextBrowser,
    QVBoxLayout, QWidget,
)

import config
import store
import voice
from agent import Agent
from orb import Orb
from overlay import FloatingFace
from PyQt6.QtGui import QGuiApplication

C = {
    "bg": "#0f1420",
    "surface": "#161d2e",
    "surface2": "#1d2740",
    "line": "#26314b",
    "text": "#e7ecf5",
    "muted": "#8b97ad",
    "accent": "#4f8cff",
    "accent2": "#7c5cff",
    "green": "#38d39f",
    "warn": "#ffb545",
    "red": "#ff6b6b",
}

APP_QSS = f"""
* {{ font-family: 'Segoe UI', 'Inter', 'Helvetica Neue', Arial, 'Segoe UI Emoji', 'Noto Color Emoji'; }}
QMainWindow, QDialog, QWidget#Root {{ background: {C['bg']}; }}
QWidget {{ color: {C['text']}; font-size: 14px; }}
QLabel#H1 {{ font-size: 19px; font-weight: 700; }}
QLabel#Muted {{ color: {C['muted']}; }}
QFrame#Card {{ background: {C['surface']}; border: 1px solid {C['line']}; border-radius: 12px; }}
QFrame#Side {{ background: {C['surface']}; border-right: 1px solid {C['line']}; }}
QPushButton {{
    background: {C['surface2']}; border: 1px solid {C['line']}; border-radius: 9px;
    padding: 8px 14px; color: {C['text']};
}}
QPushButton:hover {{ background: #25314f; }}
QPushButton:pressed {{ background: #1a2338; }}
QPushButton:disabled {{ color: {C['muted']}; background: #171f31; }}
QPushButton#Primary {{
    background: {C['accent']}; border: none; font-weight: 700; padding: 9px 20px;
}}
QPushButton#Primary:hover {{ background: #6a9dff; }}
QPushButton#Primary:disabled {{ background: #2b3550; color: #8b97ad; }}
QPushButton#Nav {{
    text-align: left; padding: 10px 14px; border: none; border-radius: 9px;
    background: transparent; color: {C['muted']}; font-size: 14px;
}}
QPushButton#Nav:hover {{ background: {C['surface2']}; color: {C['text']}; }}
QPushButton#Nav:checked {{
    background: {C['surface2']}; color: {C['text']}; font-weight: 700;
    border-left: 3px solid {C['accent']};
}}
QPushButton#Chip {{
    background: transparent; border: 1px solid {C['line']}; border-radius: 14px;
    padding: 5px 12px; color: {C['muted']}; font-size: 12px;
}}
QPushButton#Chip:hover {{ border-color: {C['accent']}; color: {C['text']}; }}
QPlainTextEdit, QLineEdit, QComboBox, QDateTimeEdit {{
    background: {C['surface2']}; border: 1px solid {C['line']}; border-radius: 10px;
    padding: 8px 10px; min-height: 22px; selection-background-color: {C['accent']};
}}
QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus, QDateTimeEdit:focus {{ border-color: {C['accent']}; }}
QListWidget {{ background: {C['surface']}; border: 1px solid {C['line']}; border-radius: 12px; padding: 6px; }}
QListWidget::item {{ padding: 9px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {C['surface2']}; color: {C['text']}; }}
QCheckBox {{ spacing: 9px; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border-radius: 5px;
    border: 1px solid #3a4763; background: #131a29;
}}
QCheckBox::indicator:hover {{ border-color: {C['accent']}; }}
QCheckBox::indicator:checked {{
    background: {C['accent']}; border-color: {C['accent']};
    image: none;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{
    image: none; border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {C['muted']}; margin-right: 8px;
}}
QDateTimeEdit::drop-down {{ border: none; width: 20px; }}
QDateTimeEdit::down-arrow {{
    image: none; border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 5px solid {C['muted']}; margin-right: 6px;
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: #33405f; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QComboBox QAbstractItemView {{ background: {C['surface2']}; border: 1px solid {C['line']}; selection-background-color: {C['accent']}; }}
"""


# --------------------------------------------------------------------- workers
class ListenWorker(QThread):
    WINDOW = 25.0            # seconds of follow-up allowed after "hey zinger"

    heard = pyqtSignal(str)
    failed = pyqtSignal(str)
    state = pyqtSignal(str)
    level = pyqtSignal(float)

    def __init__(self, listener: voice.Listener, on_level=None):
        super().__init__()
        self.listener = listener
        self._on_level = on_level
        self._stop = threading.Event()

    def run(self):
        text, err = self.listener.listen_once(
            on_state=self.state.emit,
            stop_evt=self._stop,
            on_level=self._emit_level,
        )
        if text:
            self.heard.emit(text)
        else:
            self.failed.emit(err or "I didn't catch that.")

    def _emit_level(self, value: float):
        if self._on_level:
            self.level.emit(value)   # Qt marshals this to the UI thread

    def finish(self):
        """Stop early (the user pressed Stop while speaking)."""
        self._stop.set()


class ConversationLoop(QThread):
    """Always-on ears.

    Two modes:
      * wake mode  - whispers nothing until it hears "Hey Zinger", then takes the
                     request. Cheaper and far less creepy than transcribing a room.
      * open mode  - transcribes everything and answers.

    In both modes it can ignore voices that aren't the user's (voice ID) and it
    mutes itself while speaking.
    """

    WINDOW = 25.0            # seconds of follow-up allowed after "hey zinger"

    heard = pyqtSignal(str)
    noted = pyqtSignal(str)
    state = pyqtSignal(str)
    level = pyqtSignal(float)
    held = pyqtSignal()          # went quiet - back to idle
    stranger = pyqtSignal(float)  # heard a voice that isn't the user

    def __init__(self, listener, is_busy, is_speaking, wake_phrase="",
                 voiceprint=None, threshold=0.55):
        super().__init__()
        self.listener = listener
        self._is_busy = is_busy
        self._is_speaking = is_speaking
        self.wake_phrase = wake_phrase or ""
        self.voiceprint = voiceprint or []
        self.threshold = threshold
        self._stop = threading.Event()
        self._muted = threading.Event()
        self._awake_until = 0.0

    def _sample_path(self):
        """Record a short clip, keep the file so voice ID can inspect it."""
        return self.listener.record_clip(seconds=6.0, stop_evt=self._stop,
                                         on_level=self.level.emit,
                                         on_state=self.state.emit)

    def _is_mine(self, wav_path: str):
        if not self.voiceprint or not wav_path:
            return True
        try:
            import voiceprint as vp

            vec = vp.features(wav_path)
            mine, score = vp.match(self.voiceprint, vec, self.threshold)
            if not mine:
                self.stranger.emit(score)
            return mine
        except Exception:
            return True     # never block the user because analysis failed

    def run(self):
        import voice as _v

        quiet_rounds = 0
        fails = 0
        announced = False
        while not self._stop.is_set():
            if self._muted.is_set() or self._is_busy() or self._is_speaking():
                self.msleep(250)
                continue

            # record the clip once; it is used for voice ID *and* transcribing
            wav = self._sample_path()
            if self._stop.is_set():
                break
            if not wav:
                fails += 1
                if fails in (3, 20):
                    self.noted.emit("I can't reach the microphone. Check Windows "
                                    "Settings \u2192 Privacy \u2192 Microphone.")
                self.msleep(600)
                continue
            fails = 0

            try:
                text, err = self.listener.transcribe(wav, on_state=self.state.emit)
            finally:
                self.listener._cleanup(wav)
            if self._stop.is_set():
                break

            if not text:
                quiet_rounds += 1
                low = (err or "").lower()
                if err and "couldn't make" not in low and "didn't hear" not in low:
                    # a real problem (no internet, no mic) - surface it at once
                    if quiet_rounds in (2, 20):
                        self.noted.emit(err)
                self.msleep(150)
                continue

            # a different voice is speaking - ignore it, but never let the check
            # swallow the user's own command
            if not self._is_mine(wav):
                quiet_rounds += 1
                if quiet_rounds in (1, 10):
                    self.noted.emit("That doesn't sound like you - ignoring it.")
                self.msleep(200)          # never spin if the mic returns instantly
                continue

            if self.wake_phrase:
                awake = time.time() < self._awake_until
                if _v.contains_wake(text, self.wake_phrase):
                    text = _v.strip_wake(text, self.wake_phrase)
                    announced = False
                    self._awake_until = time.time() + self.WINDOW
                    if not text:
                        # just the wake word - acknowledge and take the command next
                        self.noted.emit("Yes sir?")
                        continue
                elif not awake:
                    quiet_rounds += 1
                    if not announced:
                        announced = True
                        self.noted.emit('Listening for "%s"\u2026' % self.wake_phrase)
                    self.msleep(120)
                    continue
                else:
                    # inside the conversation window - no wake word needed
                    self._awake_until = time.time() + self.WINDOW

                quiet_rounds = 0
                self.state.emit("heard")
                self.heard.emit(text)
            else:
                quiet_rounds = 0
                self.state.emit("heard")
                self.heard.emit(text)

            # wait for the reply to finish before listening again
            waited = 0.0
            while (self._is_busy() or self._is_speaking()) and \
                    not self._stop.is_set():
                self.msleep(200)
                waited += 0.2
                if waited > 180:          # never hang the loop forever
                    break
        self.state.emit("idle")

    def mute(self, on: bool):
        if on:
            self._muted.set()
        else:
            self._muted.clear()

    def stop_loop(self):
        self._stop.set()


class AskWorker(QThread):
    chunk = pyqtSignal(str)
    event = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, agent: Agent, text: str, draft_mode: bool = False):
        super().__init__()
        self.agent, self.text, self.draft_mode = agent, text, draft_mode
        self.setTerminationEnabled(False)   # stop politely, never kill mid-write

    def run(self):
        try:
            if self.draft_mode:
                out = self.agent.draft_only(self.text, on_text=self.chunk.emit)
            else:
                out = self.agent.chat(self.text, on_text=self.chunk.emit,
                                      on_event=self.event.emit)
            self.finished_ok.emit(out or "")
        except Exception as e:
            self.failed.emit(str(e))


class TestKeyWorker(QThread):
    done = pyqtSignal(str)

    def __init__(self, agent: "Agent", key: str, model: str):
        super().__init__()
        self.agent, self.key, self.model = agent, key, model

    def run(self):
        self.done.emit(self.agent.test_connection(self.key, self.model))


class ReminderWatcher(QThread):
    fired = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._stop = False

    def run(self):
        while not self._stop:
            try:
                for r in store.due_reminders():
                    store.mark_notified(r["id"])
                    nxt = store.next_occurrence(r["due_at"], r["repeat"])
                    if nxt != r["due_at"]:
                        store.reschedule(r["id"], nxt)
                    else:
                        store.complete_reminder(r["id"])
                    self.fired.emit(r)
            except Exception:
                pass
            for _ in range(40):  # ~20s, responsive to stop
                if self._stop:
                    return
                self.msleep(500)

    def stop(self):
        self._stop = True


# --------------------------------------------------------------------- helpers
def md_to_html(text: str, color: str = C["text"]) -> str:
    """Small markdown subset -> HTML for a chat bubble."""
    parts = re.split(r"```(?:\w+)?\n?(.*?)```", text, flags=re.S)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:  # fenced code block
            out.append(
                "<table width='100%' cellspacing='0' cellpadding='9' style='margin:6px 0'>"
                "<tr><td bgcolor='#0c1220'>"
                "<span style='font-family:Consolas,monospace;font-size:13px;color:#c8d6f0;"
                "white-space:pre-wrap'>" + html.escape(part.strip()) + "</span>"
                "</td></tr></table>"
            )
            continue
        safe = html.escape(part)
        safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
        safe = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", safe)
        safe = re.sub(
            r"`([^`]+)`",
            r"<span style='font-family:Consolas,monospace;background-color:#0c1220'>"
            r"&nbsp;\1&nbsp;</span>",
            safe,
        )
        safe = safe.replace("\n", "<br>")
        out.append("<span style='color:%s'>%s</span>" % (color, safe))
    return "".join(out)


class Bubble(QFrame):
    """One chat message: rounded, auto-sized, with selectable text."""

    def __init__(self, role: str, text: str, max_width: int = 620, parent=None):
        super().__init__(parent)
        self.role = role
        self._text = text

        inner = QTextBrowser(self)
        inner.setOpenExternalLinks(True)
        inner.setFrameShape(QFrame.Shape.NoFrame)
        inner.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; padding: 0px; }"
        )
        inner.document().setDocumentMargin(0)
        inner.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        inner.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.inner = inner

        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 9, 13, 9)
        lay.setSpacing(0)
        lay.addWidget(inner)

        if role == "user":
            bg, self._fg = C["accent"], "#ffffff"
        elif role == "system":
            bg, self._fg = "#2a2213", C["warn"]
        else:
            bg, self._fg = C["surface2"], C["text"]
        self.setStyleSheet("QFrame { background: %s; border-radius: 14px; }" % bg)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set_text(text, max_width)

    def set_text(self, text: str, max_width: int = 620):
        self._text = text
        html_text = md_to_html(text, self._fg)

        # measure with a throwaway document so the live widget can't skew it
        meas = QTextDocument()
        meas.setDocumentMargin(0)
        meas.setDefaultFont(self.inner.font())
        meas.setHtml(html_text)
        meas.setTextWidth(-1)
        natural = meas.idealWidth() or 200
        w = int(min(max_width, max(56, natural + 4)))
        meas.setTextWidth(w)
        h = int(meas.size().height())

        self.inner.setHtml(html_text)
        self.inner.document().setTextWidth(w)
        self.inner.setFixedSize(w, max(18, h))
        self.setFixedSize(w + 26, max(18, h) + 18)
        self.updateGeometry()


def logo_pixmap(size: int = 64) -> QPixmap:
    """The app icon: a rounded blue tile with a little agent glyph."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(C["accent"]))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, size * 0.28, size * 0.28)
    p.setBrush(QColor("#ffffff"))
    r = size * 0.17
    p.drawEllipse(int(size * 0.5 - r), int(size * 0.30), int(r * 2), int(r * 2))
    p.drawRoundedRect(int(size * 0.25), int(size * 0.60), int(size * 0.50),
                      int(size * 0.15), int(size * 0.075), int(size * 0.075))
    p.end()
    return pm


# --------------------------------------------------------------------- widgets
class Toast(QLabel):
    """Small floating notification inside the window."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet(
            f"background:{C['accent2']};color:white;border-radius:10px;"
            "padding:12px 16px;font-weight:600;"
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, ms: int = 8000):
        self.setText(text)
        self.adjustSize()
        pw = self.parent().width()
        self.setFixedWidth(min(420, pw - 60))
        self.move(pw - self.width() - 24, 20)
        self.raise_()
        self.show()
        self._timer.start(ms)


class ChatPage(QWidget):
    """Scrollable column of message bubbles."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.live = None
        self.bubbles = []
        self._live_text = ""
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(80)   # ~12 redraws/sec, not one per token
        self._flush_timer.timeout.connect(self._flush_live)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)

        head = QHBoxLayout()
        self.title = QLabel("Chat")
        self.title.setObjectName("H1")
        head.addWidget(self.title)
        head.addStretch(1)
        self.mic_hint = QLabel("Ctrl+Alt+Space to talk")
        self.mic_hint.setObjectName("Muted")
        self.mic_hint.setStyleSheet("font-size:11px")
        head.addWidget(self.mic_hint)
        btn = QPushButton("New chat")
        btn.clicked.connect(self.new_chat)
        head.addWidget(btn)
        outer.addLayout(head)

        # ---- the face
        self.orb = Orb(size=300)
        self.orb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.orb.mousePressEvent = lambda _e: self.win.toggle_conversation()
        presence = QHBoxLayout()
        presence.addStretch(1)
        presence.addWidget(self.orb)
        presence.addStretch(1)
        outer.addLayout(presence, 1)

        self.mood_label = QLabel("")
        self.mood_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mood_label.setStyleSheet("font-size:11px; color:%s" % C["muted"])
        outer.addWidget(self.mood_label)

        vb = QHBoxLayout()
        vb.addStretch(1)
        self.talk_btn = QPushButton("Start listening")
        self.talk_btn.setObjectName("Chip")
        self.talk_btn.setMinimumWidth(260)
        self.talk_btn.clicked.connect(self.win.toggle_conversation)
        vb.addWidget(self.talk_btn)
        self.full_btn = QPushButton("Full screen")
        self.full_btn.setObjectName("Chip")
        self.full_btn.clicked.connect(self.win.toggle_fullscreen_face)
        vb.addWidget(self.full_btn)
        vb.addStretch(1)
        outer.addLayout(vb)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.canvas = QWidget()
        self.canvas.setStyleSheet("background: transparent;")
        self.col = QVBoxLayout(self.canvas)
        self.col.setContentsMargins(4, 4, 10, 4)
        self.col.setSpacing(8)
        self.col.addStretch(1)
        self.scroll.setWidget(self.canvas)
        outer.addWidget(self.scroll, 1)

        chips = QHBoxLayout()
        chips.setSpacing(8)
        for label, text in [
            ("Remind me…", "Remind me to "),
            ("Draft a reply…", "Draft a reply to this: "),
            ("What's on my plate?", "What's on my plate today?"),
            ("Summarise clipboard", "__CLIP_SUMMARY__"),
        ]:
            b = QPushButton(label)
            b.setObjectName("Chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, t=text: self.quick(t))
            chips.addWidget(b)
        chips.addStretch(1)
        outer.addLayout(chips)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText(
            "Tell me what to do…  (Enter sends, Shift+Enter for a new line)"
        )
        self.input.setFixedHeight(74)
        self.input.installEventFilter(self)
        row.addWidget(self.input, 1)
        col = QVBoxLayout()
        col.setSpacing(6)
        self.send = QPushButton("Send")
        self.send.setObjectName("Primary")
        self.send.setFixedHeight(36)
        self.send.clicked.connect(self.submit)
        col.addWidget(self.send)
        stop = QPushButton("Stop")
        stop.setFixedHeight(30)
        stop.clicked.connect(self.win.stop_current)
        col.addWidget(stop)
        row.addLayout(col)
        outer.addLayout(row)

        self.status = QLabel("Ready")
        self.status.setObjectName("Muted")
        outer.addWidget(self.status)

    # ------------------------------------------------------------------
    def _max_width(self) -> int:
        w = self.scroll.viewport().width() if self.scroll.viewport() else 700
        return max(200, int(w * 0.74))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if not self.bubbles:
            return
        mw = self._max_width()
        for b in self.bubbles:          # deferred: resizing mid-stream caused stalls
            b.set_text(b._text, mw)

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent

        if obj is self.input and ev.type() == QEvent.Type.KeyPress:
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                ev.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                self.submit()
                return True
        return super().eventFilter(obj, ev)

    def quick(self, text: str):
        if text == "__CLIP_SUMMARY__":
            clip = QApplication.clipboard().text().strip()
            if not clip:
                self.win.toast.show_message("Clipboard is empty.")
                return
            self.input.setPlainText(
                "Summarise this and pull out any action items:\n\n" + clip[:4000]
            )
        elif text.startswith("Draft a reply"):
            clip = QApplication.clipboard().text().strip()
            self.input.setPlainText(
                ("Draft a reply to this message, ready to send:\n\n" + clip)
                if clip else "Draft a reply to this: "
            )
        else:
            self.input.setPlainText(text)
        self.input.setFocus()
        cur = self.input.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self.input.setTextCursor(cur)

    # ------------------------------------------------------------------
    def add_bubble(self, role: str, text: str) -> Bubble:
        b = Bubble(role, text, self._max_width())
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        if role == "user":
            row.addStretch(1)
            row.addWidget(b)
        else:
            row.addWidget(b)
            row.addStretch(1)
        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        wrapper.setLayout(row)
        wrapper.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        wrapper.setFixedHeight(b.height())
        self.col.insertWidget(self.col.count() - 1, wrapper)
        self.bubbles.append(b)
        self._scroll_bottom()
        return b

    def begin_live(self):
        self._live_text = ""
        self.live = self.add_bubble("assistant", "▍")
        self._flush_timer.start()

    def update_live(self, text: str):
        """Called for every streamed chunk - only stores the text.

        Redrawing is done by the timer, so a fast stream can't drown the UI
        thread and freeze the window.
        """
        self._live_text = text
        if self.live is None:
            self.begin_live()

    def _flush_live(self):
        if self.live is None:
            self._flush_timer.stop()
            return
        old_h = self.live.height()
        self.live.set_text(self._live_text or "▍", self._max_width())
        if self.live.parentWidget() and self.live.height() != old_h:
            self.live.parentWidget().setFixedHeight(self.live.height())
        self._scroll_bottom()

    def end_live(self):
        self._flush_timer.stop()
        if self.live is not None:
            self.live.set_text(self._live_text or "(no reply)", self._max_width())
            if self.live.parentWidget():
                self.live.parentWidget().setFixedHeight(self.live.height())
        self.live = None

    def _scroll_bottom(self):
        sb = self.scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: sb.setValue(sb.maximum()))

    def clear_bubbles(self):
        self.bubbles = []
        self.live = None
        while self.col.count() > 1:
            item = self.col.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def render_history(self):
        self.clear_bubbles()
        rows = store.recent_chat(limit=80)
        if not rows:
            self.add_bubble(
                "system",
                "Hi 👋 I'm your laptop agent. Try *“remind me to call Mum at 6pm "
                "tomorrow”*, *“draft a reply to this message”*, or *“what's on my "
                "plate today?”*",
            )
            return
        recent = [r for r in rows if r["role"] != "system"]
        if len(recent) > 40:                       # keep the window responsive
            hidden = len(recent) - 40
            recent = recent[-40:]
            self.add_bubble("system", "… %d older messages hidden. Press New chat "
                                      "to start clean." % hidden)
        for r in recent:
            self.add_bubble(r["role"], r["content"])
        self._scroll_bottom()

    def new_chat(self):
        if QMessageBox.question(
            self, "New chat",
            "Start fresh? This clears the chat on screen (reminders and memories "
            "are kept).",
        ) == QMessageBox.StandardButton.Yes:
            store.clear_chat()
            self.render_history()

    def submit(self, spoken: bool = False):
        text = self.input.toPlainText().strip()
        if not text or self.win.busy:
            return
        self.win.busy = True
        self.win._last_activity = time.time()
        self.send.setEnabled(False)
        self.input.clear()
        self.add_bubble("user", text)
        self.status.setText("Thinking…")
        self.win.start_worker(AskWorker(self.win.agent, text))


class RemindersPage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)

        t = QLabel("Reminders")
        t.setObjectName("H1")
        lay.addWidget(t)

        card = QFrame()
        card.setObjectName("Card")
        g = QGridLayout(card)
        g.setContentsMargins(14, 14, 14, 14)
        g.setSpacing(10)
        self.text = QLineEdit()
        self.text.setPlaceholderText("What should I remind you about?")
        g.addWidget(self.text, 0, 0, 1, 2)
        self.when = QDateTimeEdit()
        self.when.setCalendarPopup(True)
        self.when.setDisplayFormat("ddd dd MMM yyyy  HH:mm")
        self.when.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        g.addWidget(self.when, 1, 0)
        self.repeat = QComboBox()
        self.repeat.addItems(["none", "daily", "weekdays", "weekly", "monthly"])
        g.addWidget(self.repeat, 1, 1)
        add = QPushButton("Add reminder")
        add.setObjectName("Primary")
        add.clicked.connect(self.add)
        g.addWidget(add, 2, 0, 1, 2)
        lay.addWidget(card)

        self.listw = QListWidget()
        lay.addWidget(self.listw, 1)

        btns = QHBoxLayout()
        done = QPushButton("Mark done")
        done.clicked.connect(self.complete)
        dele = QPushButton("Delete")
        dele.clicked.connect(self.delete)
        btns.addWidget(done)
        btns.addWidget(dele)
        btns.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        btns.addWidget(refresh)
        lay.addLayout(btns)
        self.refresh()

    def refresh(self):
        self.listw.clear()
        rows = store.list_reminders(include_done=True)
        if not rows:
            it = QListWidgetItem("Nothing scheduled yet.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.listw.addItem(it)
            return
        for r in rows:
            dt = datetime.datetime.fromisoformat(r["due_at"])
            stamp = dt.strftime("%a %d %b · %H:%M")
            rep = "" if r["repeat"] == "none" else f"  ↻ {r['repeat']}"
            prefix = "✓  " if r["done"] else "⏰  "
            it = QListWidgetItem(f"{prefix}{stamp}{rep}   —   {r['text']}")
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            if r["done"]:
                it.setForeground(QColor(C["muted"]))
            self.listw.addItem(it)

    def add(self):
        text = self.text.text().strip()
        if not text:
            return
        due = self.when.dateTime().toPyDateTime().replace(microsecond=0).isoformat()
        store.add_reminder(text, due, self.repeat.currentText())
        self.text.clear()
        self.refresh()
        self.win.toast.show_message("Reminder added ⏰")

    def _sel(self):
        it = self.listw.currentItem()
        if not it:
            return None
        return it.data(Qt.ItemDataRole.UserRole)

    def complete(self):
        rid = self._sel()
        if rid:
            store.complete_reminder(rid)
            self.refresh()

    def delete(self):
        rid = self._sel()
        if rid:
            store.delete_reminder(rid)
            self.refresh()


class MemoryPage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)
        t = QLabel("Memory")
        t.setObjectName("H1")
        lay.addWidget(t)
        sub = QLabel("Facts the agent keeps about you. It adds these itself as you talk.")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        row = QHBoxLayout()
        self.new = QLineEdit()
        self.new.setPlaceholderText("Something to remember… e.g. My landlord is Mr. Otieno")
        self.new.returnPressed.connect(self.add)
        row.addWidget(self.new, 1)
        b = QPushButton("Remember")
        b.setObjectName("Primary")
        b.clicked.connect(self.add)
        row.addWidget(b)
        lay.addLayout(row)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search memory…")
        self.search.textChanged.connect(self.refresh)
        lay.addWidget(self.search)

        self.listw = QListWidget()
        lay.addWidget(self.listw, 1)
        dele = QPushButton("Forget selected")
        dele.clicked.connect(self.delete)
        lay.addWidget(dele)
        self.refresh()

    def refresh(self):
        self.listw.clear()
        q = self.search.text().strip()
        rows = store.search_memories(q) if q else store.list_memories(200)
        if not rows:
            it = QListWidgetItem("Nothing stored yet.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.listw.addItem(it)
            return
        for r in rows:
            it = QListWidgetItem(r["content"])
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.listw.addItem(it)

    def add(self):
        t = self.new.text().strip()
        if t:
            store.add_memory(t)
            self.new.clear()
            self.refresh()
            self.win.toast.show_message("Saved to memory 🧠")

    def delete(self):
        it = self.listw.currentItem()
        if it and it.data(Qt.ItemDataRole.UserRole):
            store.delete_memory(it.data(Qt.ItemDataRole.UserRole))
            self.refresh()


class ModelFinder(QThread):
    done = pyqtSignal(list, str)

    def __init__(self, agent: "Agent"):
        super().__init__()
        self.agent = agent

    def run(self):
        try:
            names, err = self.agent.discover_models()
            self.done.emit(names or [], err or "")
        except Exception as e:
            self.done.emit([], str(e))


class DiagnoseWorker(QThread):
    done = pyqtSignal(str)

    def __init__(self, agent: "Agent", key: str):
        super().__init__()
        self.agent, self.key = agent, key

    def run(self):
        try:
            self.done.emit(self.agent.diagnose(self.key))
        except Exception as e:
            self.done.emit("Diagnostic crashed: %s" % e)


class DiagnoseDialog(QDialog):
    """Shows the full key diagnostic in a scrollable, copyable window."""

    def __init__(self, win, key: str):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Key diagnostic")
        self.resize(780, 580)
        self.setObjectName("DiagDialog")
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            "QDialog#DiagDialog, QWidget#DiagDialog { background: %s; }"
            "QLabel { color: %s; }" % (C["bg"], C["text"])
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        head = QLabel("Checking your key against Google…")
        head.setObjectName("H1")
        lay.addWidget(head)

        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setStyleSheet(
            "font-family:Consolas,'Cascadia Mono',monospace; font-size:12.5px;"
        )
        lay.addWidget(self.out, 1)

        row = QHBoxLayout()
        self.copy_btn = QPushButton("Copy report")
        self.copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(self.out.toPlainText())
        )
        row.addWidget(self.copy_btn)
        row.addStretch(1)
        self.fix_btn = QPushButton("Use a working model")
        self.fix_btn.setObjectName("Primary")
        self.fix_btn.setEnabled(False)
        self.fix_btn.clicked.connect(self.use_working)
        row.addWidget(self.fix_btn)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        lay.addLayout(row)

        self.report = ""
        self.worker = DiagnoseWorker(win.agent, key)
        self.worker.done.connect(self.show_report)
        self.worker.start()

    def show_report(self, text: str):
        self.report = text
        self.out.setPlainText(text)
        self.findChild(QLabel).setText("Key diagnostic")
        if "Working model:" in text:
            self.fix_btn.setEnabled(True)
            self.fix_btn.setText("Use " + text.split("Working model:")[1].split("\n")[0].strip())

    def use_working(self):
        self.fix_btn.setEnabled(False)
        self.fix_btn.setText("Finding a live model…")

        def done(ok):
            if ok:
                model = config.load().get("model", "")
                self.win.set_page.model.setCurrentText(model)
                self.win.toast.show_message("Using %s — try a message in Chat." % model)
                self.accept()
            else:
                self.fix_btn.setEnabled(True)
                self.fix_btn.setText("Use a working model")
                self.win.toast.show_message("No working model found — see the report.")

        self._fixer = ModelFinder(self.win.agent)
        self._fixer.done.connect(lambda names, err: done(bool(names)))
        self._fixer.start()


class SettingsPage(QWidget):
    """All configuration in one place. Two provider panels share a stack, so no
    fragile row-number juggling and nothing can overlap."""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        cfg = config.load()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        scroll.setWidget(body)
        outer.addWidget(scroll)

        lay = QVBoxLayout(body)
        lay.setContentsMargins(18, 14, 18, 18)
        lay.setSpacing(10)

        title = QLabel("Settings")
        title.setObjectName("H1")
        lay.addWidget(title)

        # ---------------------------------------------------------- brain card
        card = QFrame()
        card.setObjectName("Card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(8)

        prow = QHBoxLayout()
        prow.addWidget(QLabel("Provider"))
        self.provider = QComboBox()
        self.provider.addItems([
            "Google Gemini (AI Studio key)",
            "OpenAI-compatible gateway (custom base URL)",
        ])
        self.provider.setCurrentIndex(
            0 if (cfg.get("provider") or "gemini") == "gemini" else 1
        )
        prow.addWidget(self.provider, 1)
        v.addLayout(prow)

        self.stack = QStackedWidget()
        v.addWidget(self.stack)

        # --- panel 0: Gemini
        gem = QWidget()
        gv = QVBoxLayout(gem)
        gv.setContentsMargins(0, 4, 0, 0)
        gv.setSpacing(6)
        gv.addWidget(QLabel("Google AI Studio API key"))
        keyrow = QHBoxLayout()
        self.key = QLineEdit(cfg.get("api_key", ""))
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("AQ.… or AIza…  (free at aistudio.google.com/apikey)")
        keyrow.addWidget(self.key, 1)
        self.show_key = QCheckBox("show")
        self.show_key.toggled.connect(
            lambda on: self.key.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        keyrow.addWidget(self.show_key)
        gv.addLayout(keyrow)

        gv.addWidget(QLabel("Extra keys (one per line - used automatically when the "
                            "first runs out of quota)"))
        self.keys_extra = QPlainTextEdit()
        self.keys_extra.setPlainText("\n".join(cfg.get("api_keys") or []))
        self.keys_extra.setFixedHeight(64)
        self.keys_extra.setPlaceholderText("AQ.…\nAQ.…")
        gv.addWidget(self.keys_extra)

        gv.addWidget(QLabel("Model"))
        mrow = QHBoxLayout()
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems([cfg.get("model") or "gemini-3.8-flash"])
        self.model.setCurrentText(cfg.get("model", "gemini-3.8-flash"))
        mrow.addWidget(self.model, 1)
        self.find_btn = QPushButton("Find models")
        self.find_btn.clicked.connect(self.find_models)
        mrow.addWidget(self.find_btn)
        gv.addLayout(mrow)

        self.auto = QCheckBox("Always use the best available model (recommended)")
        self.auto.setChecked(cfg.get("auto_model", True))
        gv.addWidget(self.auto)
        self.stack.addWidget(gem)

        # --- panel 1: OpenAI-compatible gateway
        gw = QWidget()
        wv = QVBoxLayout(gw)
        wv.setContentsMargins(0, 4, 0, 0)
        wv.setSpacing(6)
        wv.addWidget(QLabel("Base URL (must end in /v1 for most gateways)"))
        self.oa_base = QLineEdit(cfg.get("openai_base_url", ""))
        self.oa_base.setPlaceholderText("https://api.example-gateway.ai/v1")
        wv.addWidget(self.oa_base)
        wv.addWidget(QLabel("Gateway API key"))
        self.oa_key = QLineEdit(cfg.get("openai_key", ""))
        self.oa_key.setEchoMode(QLineEdit.EchoMode.Password)
        wv.addWidget(self.oa_key)
        wv.addWidget(QLabel("Extra gateway keys (one per line)"))
        self.oa_keys_extra = QPlainTextEdit()
        self.oa_keys_extra.setPlainText("\n".join(cfg.get("openai_keys") or []))
        self.oa_keys_extra.setFixedHeight(56)
        wv.addWidget(self.oa_keys_extra)
        wv.addWidget(QLabel("Model slug"))
        mrow2 = QHBoxLayout()
        self.oa_model = QComboBox()
        self.oa_model.setEditable(True)
        if cfg.get("openai_model"):
            self.oa_model.addItems([cfg["openai_model"]])
            self.oa_model.setCurrentText(cfg["openai_model"])
        self.oa_model.setPlaceholderText("press List models to load the catalogue")
        mrow2.addWidget(self.oa_model, 1)
        self.oa_list_btn = QPushButton("List models")
        self.oa_list_btn.clicked.connect(self.list_gateway_models)
        mrow2.addWidget(self.oa_list_btn)
        wv.addLayout(mrow2)
        note = QLabel("Works with Groq, OpenRouter, LM Studio, Ollama (/v1) and most "
                      "gateways. This key is only ever sent to the base URL above.")
        note.setWordWrap(True)
        note.setObjectName("Muted")
        note.setStyleSheet("font-size:12px")
        wv.addWidget(note)
        wv.addStretch(1)
        self.stack.addWidget(gw)

        v.addWidget(QLabel(""))
        nrow = QHBoxLayout()
        nrow.addWidget(QLabel("Your name"))
        self.uname = QLineEdit(cfg.get("user_name", ""))
        self.uname.setPlaceholderText("e.g. Brian")
        nrow.addWidget(self.uname, 1)
        nrow.addWidget(QLabel("Agent name"))
        self.aname = QLineEdit(cfg.get("assistant_name", "Pocket"))
        nrow.addWidget(self.aname, 1)
        v.addLayout(nrow)
        lay.addWidget(card)

        # ---------------------------------------------------- permissions card
        card2 = QFrame()
        card2.setObjectName("Card")
        pv = QVBoxLayout(card2)
        pv.setContentsMargins(16, 14, 16, 14)
        pv.setSpacing(7)
        pv.addWidget(QLabel("Permissions"))
        sub = QLabel("Off by default — nothing happens on your laptop unless you allow it.")
        sub.setObjectName("Muted")
        pv.addWidget(sub)
        self.apps_cb = QCheckBox("Allow opening apps on my computer (Chrome, Spotify…)")
        self.apps_cb.setChecked(cfg.get("allow_apps", True))
        pv.addWidget(self.apps_cb)
        self.cmd = QCheckBox("Allow shell commands")
        self.cmd.setChecked(cfg.get("allow_commands", False))
        pv.addWidget(self.cmd)
        self.files = QCheckBox("Allow reading and writing files")
        self.files.setChecked(cfg.get("allow_files", True))
        pv.addWidget(self.files)
        self.kbd = QCheckBox("Allow typing into the focused window (keyboard control)")
        self.kbd.setChecked(cfg.get("allow_keyboard", False))
        pv.addWidget(self.kbd)
        self.scr = QCheckBox("Let the agent read my screen (and read messages on it)")
        self.scr.setChecked(cfg.get("allow_screen", False))
        pv.addWidget(self.scr)
        self.eml = QCheckBox("Let the agent send email from my Gmail")
        self.eml.setChecked(cfg.get("allow_email", False))
        pv.addWidget(self.eml)
        self.sms = QCheckBox("Let the agent send texts / place calls")
        self.sms.setChecked(cfg.get("allow_sms", False) or cfg.get("allow_calls", False))
        pv.addWidget(self.sms)
        warn = QLabel("Full access means full access: with these on, the agent can read "
                      "your screen and message people in your name. Turn on only what "
                      "you actually want, and check what it drafted before it sends.")
        warn.setWordWrap(True)
        warn.setStyleSheet("font-size:12px; color:%s" % C["warn"])
        pv.addWidget(warn)
        frow = QHBoxLayout()
        self.fdir = QLineEdit(cfg.get("files_dir", config.DEFAULTS["files_dir"]))
        frow.addWidget(self.fdir, 1)
        pick = QPushButton("Choose…")
        pick.clicked.connect(self.pick_dir)
        frow.addWidget(pick)
        pv.addLayout(frow)
        lay.addWidget(card2)

        # -------------------------------------------------------- voice card
        card3 = QFrame()
        card3.setObjectName("Card")
        vv = QVBoxLayout(card3)
        vv.setContentsMargins(16, 14, 16, 14)
        vv.setSpacing(7)
        vv.addWidget(QLabel("Voice and background"))
        self.speak_cb = QCheckBox("Speak replies out loud")
        self.speak_cb.setChecked(cfg.get("speak_replies", True))
        vv.addWidget(self.speak_cb)
        self.always_cb = QCheckBox("Always listening — talk without pressing anything")
        self.always_cb.setChecked(cfg.get("always_listening", False))
        vv.addWidget(self.always_cb)
        self.autosend_cb = QCheckBox("Send as soon as I finish speaking")
        self.autosend_cb.setChecked(cfg.get("voice_autosend", True))
        vv.addWidget(self.autosend_cb)
        self.close_tray_cb = QCheckBox("Keep running in the tray when I close the window")
        self.close_tray_cb.setChecked(cfg.get("close_to_tray", True))
        vv.addWidget(self.close_tray_cb)
        vrow = QHBoxLayout()
        vrow.addWidget(QLabel("Push-to-talk hotkey"))
        self.hk = QLineEdit(cfg.get("hotkey_talk", "ctrl+alt+space"))
        self.hk.setReadOnly(True)
        vrow.addWidget(self.hk, 1)
        test_voice = QPushButton("Test voice")
        test_voice.clicked.connect(self.test_voice)
        vrow.addWidget(test_voice)
        vv.addLayout(vrow)
        self.voice_result = QLabel("")
        self.voice_result.setWordWrap(True)
        self.voice_result.setObjectName("Muted")
        self.voice_result.setStyleSheet("font-size:12px")
        vv.addWidget(self.voice_result)
        lay.addWidget(card3)

        # -------------------------------------------------------- email card
        card4 = QFrame()
        card4.setObjectName("Card")
        ev = QVBoxLayout(card4)
        ev.setContentsMargins(16, 14, 16, 14)
        ev.setSpacing(6)
        ev.addWidget(QLabel("Email (so the agent can remind you off-screen)"))
        erow = QHBoxLayout()
        erow.addWidget(QLabel("Gmail address"))
        self.eml_addr = QLineEdit(cfg.get("email_address", ""))
        self.eml_addr.setPlaceholderText("you@gmail.com")
        erow.addWidget(self.eml_addr, 1)
        ev.addLayout(erow)
        prow2 = QHBoxLayout()
        prow2.addWidget(QLabel("App Password"))
        self.eml_pw = QLineEdit(cfg.get("email_app_password", ""))
        self.eml_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.eml_pw.setPlaceholderText("16 characters — NOT your normal password")
        prow2.addWidget(self.eml_pw, 1)
        ev.addLayout(prow2)
        ehelp = QLabel("Gmail blocks normal passwords. Create a free App Password at "
                       "myaccount.google.com/apppasswords (needs 2-Step Verification on) "
                       "and paste it above.")
        ehelp.setWordWrap(True)
        ehelp.setStyleSheet("font-size:12px; color:%s" % C["muted"])
        ev.addWidget(ehelp)
        lay.addWidget(card4)


        # ------------------------------------------------------- zinger card
        zc = QFrame()
        zc.setObjectName("Card")
        z = QVBoxLayout(zc)
        z.setContentsMargins(16, 14, 16, 14)
        z.setSpacing(8)

        zt = QLabel("Wake word, your voice, and what he's learned")
        zt.setObjectName("H2")
        z.addWidget(zt)

        self.wake_cb = QCheckBox('Only answer when I say the wake word')
        self.wake_cb.setChecked(bool(cfg.get("wake_enabled", False)))
        z.addWidget(self.wake_cb)

        wrow = QHBoxLayout()
        wrow.addWidget(QLabel("Wake word"))
        self.wake_edit = QLineEdit(cfg.get("wake_word") or "hey zinger")
        wrow.addWidget(self.wake_edit, 1)
        z.addLayout(wrow)

        self.overlay_cb = QCheckBox("Show the floating face when minimised")
        self.overlay_cb.setChecked(bool(cfg.get("overlay_enabled", True)))
        z.addWidget(self.overlay_cb)

        self.watermark_start_cb = QCheckBox(
            "Start as the floating face only (no dashboard window)")
        self.watermark_start_cb.setChecked(bool(cfg.get("start_as_watermark", True)))
        z.addWidget(self.watermark_start_cb)

        self.vid_cb = QCheckBox("Only recognise my voice")
        self.vid_cb.setChecked(bool(cfg.get("voice_id_enabled", False)))
        z.addWidget(self.vid_cb)

        idrow = QHBoxLayout()
        self.vid_enrol = QPushButton("Learn my voice (3 samples)")
        self.vid_enrol.clicked.connect(self.enrol_voice)
        self.vid_clear = QPushButton("Forget my voice")
        self.vid_clear.clicked.connect(self.clear_voice)
        idrow.addWidget(self.vid_enrol)
        idrow.addWidget(self.vid_clear)
        idrow.addStretch(1)
        z.addLayout(idrow)
        self.vid_state = QLabel("")
        self.vid_state.setWordWrap(True)
        z.addWidget(self.vid_state)

        z.addWidget(QLabel("What he should know about you (one fact per line)"))
        self.about_edit = QPlainTextEdit()
        self.about_edit.setPlaceholderText(
            "my name is Brian\nI study at Kenyatta University\n"
            "I prefer Swahili greetings\nmy sister's birthday is 12 March")
        self.about_edit.setFixedHeight(96)
        z.addWidget(self.about_edit)
        arow = QHBoxLayout()
        teach = QPushButton("Save these facts")
        teach.clicked.connect(self.save_about_me)
        arow.addWidget(teach)
        arow.addStretch(1)
        z.addLayout(arow)
        self.about_state = QLabel("")
        self.about_state.setWordWrap(True)
        z.addWidget(self.about_state)

        z.addWidget(QLabel("Default apps"))
        brow = QHBoxLayout()
        brow.addWidget(QLabel("Browser"))
        self.app_browser = QLineEdit((cfg.get("app_defaults") or {}).get("browser", "chrome"))
        brow.addWidget(self.app_browser, 1)
        brow.addWidget(QLabel("Music"))
        self.app_music = QLineEdit((cfg.get("app_defaults") or {}).get("music", "spotify"))
        brow.addWidget(self.app_music, 1)
        z.addLayout(brow)

        self.skills_state = QLabel("")
        self.skills_state.setWordWrap(True)
        z.addWidget(self.skills_state)
        srow = QHBoxLayout()
        manage = QPushButton("Manage skills")
        manage.clicked.connect(self.open_skills)
        srow.addWidget(manage)
        srow.addStretch(1)
        z.addLayout(srow)

        lay.addWidget(zc)

        # ------------------------------------------------------------- actions
        row = QHBoxLayout()
        row.setSpacing(8)
        save = QPushButton("Save settings")
        save.setObjectName("Primary")
        save.clicked.connect(self.save)
        row.addWidget(save, 1)
        self.test_btn = QPushButton("Test connection")
        self.test_btn.clicked.connect(self.test_any)
        row.addWidget(self.test_btn)
        self.diag_btn = QPushButton("Diagnose key")
        self.diag_btn.clicked.connect(self.diagnose)
        row.addWidget(self.diag_btn)
        lay.addLayout(row)

        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        self.test_result.setStyleSheet("font-size:13px; padding:2px 2px")
        lay.addWidget(self.test_result)

        hint = QLabel("Free Gemini key: aistudio.google.com/apikey → Create API key → "
                      "paste above. If a model is retired, press Find models.")
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        lay.addWidget(hint)
        self._refresh_zinger_labels()
        lay.addStretch(1)

        self.provider.currentIndexChanged.connect(self._sync_provider)
        self._sync_provider()

    # ------------------------------------------------------------------ helpers
    def gateway_mode(self) -> bool:
        return self.provider.currentIndex() == 1

    def _sync_provider(self):
        self.stack.setCurrentIndex(1 if self.gateway_mode() else 0)
        self.test_btn.setText("Test provider" if self.gateway_mode() else "Test connection")
        self.diag_btn.setEnabled(not self.gateway_mode())

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Folder the agent may use")
        if d:
            self.fdir.setText(d)

    def _set_result(self, text: str, kind: str = "muted"):
        colour = {"ok": C["green"], "warn": C["warn"], "muted": C["muted"]}[kind]
        self.test_result.setText(text)
        self.test_result.setStyleSheet("color:%s;font-size:13px" % colour)

    # ------------------------------------------------------------------ models
    def find_models(self):
        key = self.key.text().strip() or config.load().get("api_key", "")
        if not key:
            self._set_result("Paste your key first, then press Find models.", "warn")
            return
        self._set_result("Asking Google which models your key can use…")

        def done(names, err):
            if names:
                current = self.model.currentText()
                self.model.clear()
                self.model.addItems(names)
                self.model.setCurrentText(current if current in names else names[0])
                self._set_result("Found %d usable models. Best: %s"
                                 % (len(names), names[0]), "ok")
            else:
                self._set_result("Couldn't list models: %s"
                                 % (err or "no text models returned"), "warn")

        self._finder = ModelFinder(self.win.agent)
        self._finder.done.connect(done)
        self._finder.start()

    def list_gateway_models(self):
        base = self.oa_base.text().strip().rstrip("/")
        key = self.oa_key.text().strip()
        if not base:
            self._set_result("Fill in the base URL first.", "warn")
            return
        self._set_result("Reading the model catalogue from %s …" % base)

        class W(QThread):
            done = pyqtSignal(list, str)

            def run(inner):
                ids, err = self.win.agent.list_gateway_models(base, key)
                inner.done.emit(ids or [], err or "")

        def finished(ids, err):
            if ids:
                current = self.oa_model.currentText()
                self.oa_model.clear()
                self.oa_model.addItems(ids)
                if current in ids:
                    self.oa_model.setCurrentText(current)
                self._set_result("%d models available — pick one, then Test provider."
                                 % len(ids), "ok")
            else:
                self._set_result("Couldn't list models: %s" % (err or "empty list"),
                                 "warn")

        self._lister = W()
        self._lister.done.connect(finished)
        self._lister.start()

    # ------------------------------------------------------------------- tests
    def test_any(self):
        if self.gateway_mode():
            self._test_gateway()
        else:
            self._test_gemini()

    def _test_gemini(self):
        key = self.key.text().strip()
        model = self.model.currentText().strip() or "gemini-3.8-flash"
        if not key:
            self._set_result("Paste your key first, then press Test.", "warn")
            return
        self._set_result("Talking to Google…")

        def work():
            return self.win.agent.test_connection(key, model)

        class W(QThread):
            done = pyqtSignal(str)

            def run(inner):
                try:
                    inner.done.emit(work())
                except Exception as e:
                    inner.done.emit("Failed: %s" % e)

        def finished(msg):
            ok = "\\u2713" in msg or msg.startswith("Connected")
            self._set_result(("Connection OK — " if ok else "") + msg,
                             "ok" if ok else "warn")
            if ok:
                cfg = config.load()
                cfg.update(api_key=key, model=model, provider="gemini")
                config.save(cfg)
                self.win.agent.reload()

        self._tester = W()
        self._tester.done.connect(finished)
        self._tester.start()

    def _test_gateway(self):
        base = self.oa_base.text().strip().rstrip("/")
        key = self.oa_key.text().strip()
        model = self.oa_model.currentText().strip()
        if not base or not model:
            self._set_result("Fill in the base URL and the model slug first.", "warn")
            return
        self._set_result("Calling %s …" % base)

        def work():
            import json as _j
            import urllib.error
            import urllib.request
            body = _j.dumps({"model": model,
                             "messages": [{"role": "user",
                                           "content": "Reply with exactly: OK"}],
                             "max_tokens": 16, "temperature": 0}).encode()
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = "Bearer " + key
            req = urllib.request.Request(base + "/chat/completions", data=body,
                                         method="POST", headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = _j.loads(r.read().decode("utf-8", "replace"))
                txt = (data["choices"][0]["message"].get("content") or "")[:40]
                return True, "Connection OK \\u2713 (reply: %r)" % txt
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    j = _j.loads(e.read().decode("utf-8", "replace"))
                    detail = (j.get("error") or {}).get("message") or str(j)[:120]
                except Exception:
                    pass
                return False, "Provider said %s: %s" % (e.code, detail or e.reason)
            except Exception as e:
                return False, "Couldn't reach %s — %s" % (base, e)

        class W(QThread):
            done = pyqtSignal(bool, str)

            def run(inner):
                ok, msg = work()
                inner.done.emit(ok, msg)

        def finished(ok, msg):
            self._set_result(msg, "ok" if ok else "warn")

        self._gw = W()
        self._gw.done.connect(finished)
        self._gw.start()

    def test_voice(self):
        """Speak a line out loud and report exactly what happened."""
        sp = self.win.speaker
        notes = []
        if not sp.available():
            self.voice_result.setText(
                "No speech engine. In a terminal run:\n"
                ".venv\\Scripts\\pip install pyttsx3")
            self.voice_result.setStyleSheet("font-size:12px; color:%s" % C["warn"]
                                            if "warn" in C else "font-size:12px")
            return
        ok = sp.say_blocking("Voice check. This is how I sound, sir.")
        if ok:
            notes.append("Spoke through %s." % (sp._backend or "the speech engine"))
        else:
            notes.append("Speech engine could not speak: %s"
                         % (sp.last_error or "unknown error"))
        if self.win.listener.available():
            notes.append("Microphone found.")
        else:
            notes.append(self.win.listener.problem
                         or "No microphone - check Windows Privacy -> Microphone")
        notes.append(sp.diagnose())
        self.voice_result.setText("\n".join(notes))
        self.voice_result.setStyleSheet("font-size:12px; color:%s" % C["muted"])

    def diagnose(self):
        key = self.key.text().strip() or config.load().get("api_key", "")
        if not key:
            self._set_result("Paste your key first, then press Diagnose.", "warn")
            return
        DiagnoseDialog(self.win, key).exec()

    # -------------------------------------------------------------------- save
    # ------------------------------------------------------- zinger helpers
    def _refresh_zinger_labels(self):
        try:
            import memory_learn as ml

            prof = ml.get_profile()
            self.about_state.setText(
                "He knows %d thing(s) about you." % len(prof) if prof
                else "He doesn't know anything about you yet.")
            sk = ml.list_skills()
            self.skills_state.setText(
                "Skills learned: %d (%s)" % (len(sk), ", ".join(x["name"] for x in sk[:4]))
                if sk else "No skills learned yet.")
        except Exception as e:
            self.skills_state.setText("Skills unavailable: %s" % e)
        try:
            if self.win.load_voiceprint():
                self.vid_state.setText("Voice learned \u2713 (%d samples)"
                                       % self._vp_samples())
            else:
                self.vid_state.setText("Your voice isn't learned yet.")
        except Exception:
            self.vid_state.setText("")

    def _vp_samples(self):
        import json

        try:
            with open(self.win._print_path(), "r", encoding="utf-8") as f:
                return json.load(f).get("samples", 0)
        except Exception:
            return 0

    def save_about_me(self):
        import memory_learn as ml

        lines = [ln.strip() for ln in self.about_edit.toPlainText().splitlines()]
        n = 0
        for ln in lines:
            if ln and ml.remember(ln):
                n += 1
        self.about_state.setText("He knows %d thing(s) about you."
                                 % len(ml.get_profile()))
        self.win.toast.show_message("Learned %d fact(s) about you." % n)

    def open_skills(self):
        import memory_learn as ml

        sk = ml.list_skills()
        if not sk:
            self.win.toast.show_message(
                "No skills yet - teach him one by voice.", 6000)
            return
        body = "\n\n".join("%s - %s (used %dx)" % (x["name"], x["steps"], x["uses"])
                            for x in sk[:12])
        QMessageBox.information(self, "Skills he has learned", body)

    def enrol_voice(self):
        """Three short samples averaged into one voiceprint."""
        if self.win.conversation and self.win.conversation.isRunning():
            self.win.stop_conversation()
        paths = []
        for i in range(3):
            self.vid_state.setText("Sample %d of 3 - talk now (4 seconds)..." % (i + 1))
            QApplication.processEvents()
            try:
                p = self.win.listener.record_clip(seconds=4.0)
            except Exception:
                p = None
            if p:
                paths.append(p)
        if not paths:
            self.vid_state.setText("I couldn't hear the microphone.")
            return
        try:
            import voiceprint as vp

            vecs = [v for v in (vp.features(p) for p in paths) if v]
            if not vecs:
                self.vid_state.setText("The samples sounded too quiet - try again.")
                return
            self.win.save_voiceprint(vecs)
            self.vid_cb.setChecked(True)
            self.save()
            self.vid_state.setText("Voice learned \u2713 (%d samples)" % len(vecs))
            self.win.toast.show_message("I'll know it's you from now on.")
        except Exception as e:
            self.vid_state.setText("Couldn't build the voiceprint: %s" % e)
        finally:
            import os

            for p in paths:
                try:
                    os.remove(p)
                except OSError:
                    pass

    def clear_voice(self):
        import os

        try:
            os.remove(self.win._print_path())
        except OSError:
            pass
        self.vid_cb.setChecked(False)
        self.vid_state.setText("Voice forgotten.")

    def save(self):
        cfg = config.load()
        cfg.update(
            api_key=self.key.text().strip(),
            api_keys=[k.strip() for k in
                      self.keys_extra.toPlainText().splitlines() if k.strip()],
            openai_keys=[k.strip() for k in
                         self.oa_keys_extra.toPlainText().splitlines() if k.strip()],
            model=self.model.currentText().strip() or "gemini-3.8-flash",
            user_name=self.uname.text().strip(),
            assistant_name=self.aname.text().strip() or "Pocket",
            allow_commands=self.cmd.isChecked(),
            allow_apps=self.apps_cb.isChecked(),
            allow_files=self.files.isChecked(),
            allow_keyboard=self.kbd.isChecked(),
            files_dir=self.fdir.text().strip() or config.DEFAULTS["files_dir"],
            auto_model=self.auto.isChecked(),
            allow_screen=self.scr.isChecked(),
            allow_email=self.eml.isChecked(),
            allow_sms=self.sms.isChecked(),
            allow_calls=self.sms.isChecked(),
            email_address=self.eml_addr.text().strip(),
            email_app_password=self.eml_pw.text().strip(),
            speak_replies=self.speak_cb.isChecked(),
            always_listening=self.always_cb.isChecked(),
            voice_autosend=self.autosend_cb.isChecked(),
            close_to_tray=self.close_tray_cb.isChecked(),
            hotkey_talk=self.hk.text().strip() or "ctrl+alt+space",
            provider=("openai" if self.gateway_mode() else "gemini"),
            openai_base_url=self.oa_base.text().strip(),
            openai_key=self.oa_key.text().strip(),
            openai_model=self.oa_model.currentText().strip(),
            wake_enabled=self.wake_cb.isChecked(),
            wake_word=self.wake_edit.text().strip() or "hey zinger",
            voice_id_enabled=self.vid_cb.isChecked(),
            overlay_enabled=self.overlay_cb.isChecked(),
            start_as_watermark=self.watermark_start_cb.isChecked(),
            app_defaults={
                "browser": self.app_browser.text().strip() or "chrome",
                "music": self.app_music.text().strip() or "spotify",
            },
        )
        config.save(cfg)
        self.win.agent.reload()
        self.win.toast.show_message("Settings saved ✓")


class FaceWindow(QWidget):
    """Full-screen presence: just the core, the energy line and live captions."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setWindowTitle("Pocket")
        self.setStyleSheet("background: #05050a;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 20, 0, 20)
        lay.setSpacing(8)

        self.orb = Orb(size=520)
        self.orb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.orb.mousePressEvent = lambda _e: win.toggle_conversation()
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.orb)
        row.addStretch(1)
        lay.addLayout(row, 1)

        self.caption = QLabel("Say anything. I'm listening.")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet("color:#ffd9a0; font-size:19px; padding:0 60px;")
        lay.addWidget(self.caption)

        self.energy = QLabel("")
        self.energy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.energy.setStyleSheet("color:#7a5a2a; font-size:12px; letter-spacing:2px;")
        lay.addWidget(self.energy)

        hint = QLabel("Esc to leave  ·  click the core to start or stop listening")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color:#3a3a48; font-size:11px;")
        lay.addWidget(hint)

        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._sync)
        self._timer.start()

    def _sync(self):
        src = self.win.chat_page.orb
        self.orb.set_state(src.state)
        self.orb.set_mood(src.mood)
        self.orb.set_level(src._level)
        self.caption.setText(self.win.chat_page.status.text() or " ")
        self.energy.setText("ENERGY %d%%" % int(getattr(self.win.agent, "mood", 1.0) * 100))

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.win._escape()
        else:
            super().keyPressEvent(ev)

    def closeEvent(self, ev):
        self._timer.stop()
        self.win.face_window = None
        ev.accept()


class DesktopNote(QLabel):
    """A message that appears on the desktop itself, not inside the dashboard.

    Needed because the dashboard is usually hidden: if opening an app fails the
    user has to *see* that, not have it printed into a window that isn't there.
    """

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setStyleSheet(
            "background:%s;color:white;border-radius:14px;padding:16px 20px;"
            "font-size:14px;font-weight:600;" % "#1c2436")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def show_text(self, text: str, ms: int = 9000):
        from PyQt6.QtWidgets import QApplication as _QApp

        self.setText(text)
        self.setFixedWidth(min(460, max(260, len(text) * 8)))
        self.adjustSize()
        screen = _QApp.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 32,
                  screen.top() + 48)
        self.show()
        self.raise_()
        self._timer.start(ms)


class MainWindow(QMainWindow):
    speech_finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.agent = Agent()
        self.busy = False
        self.worker = None
        self.speaker = voice.Speaker()
        self._speak_n = 0
        self._speak_ended = None
        self.speech_finished.connect(self._speech_done)
        try:
            self.speaker.set_on_done(self._on_speech_finished)
        except Exception:
            pass
        self.listener = voice.Listener()
        self.hotkey = None
        self._listen_worker = None
        self._level_worker = None
        self._quitting = False
        self.conversation = None
        self._speaking = False
        self.face_window = None
        self.overlay = None
        self._overlay_pos = None
        self.setWindowTitle("Pocket — your laptop agent")
        self.setWindowIcon(QIcon(logo_pixmap(128)))
        self.resize(1040, 720)
        self.setMinimumSize(820, 560)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # sidebar
        side = QFrame()
        side.setObjectName("Side")
        side.setFixedWidth(196)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(12, 16, 12, 14)
        sv.setSpacing(6)

        brand = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(logo_pixmap(30))
        brand.addWidget(icon)
        name = QLabel("Pocket")
        name.setObjectName("H1")
        brand.addWidget(name)
        brand.addStretch(1)
        sv.addLayout(brand)
        sv.addSpacing(14)

        self.pages = QStackedWidget()
        self.chat_page = ChatPage(self)
        self.rem_page = RemindersPage(self)
        self.mem_page = MemoryPage(self)
        self.set_page = SettingsPage(self)
        for p in (self.chat_page, self.rem_page, self.mem_page, self.set_page):
            self.pages.addWidget(p)

        self.nav = []
        for i, (label, key) in enumerate([
            ("💬   Chat", 0), ("⏰   Reminders", 1), ("🧠   Memory", 2), ("⚙️   Settings", 3)
        ]):
            b = QPushButton(label)
            b.setObjectName("Nav")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, idx=i: self.go(idx))
            sv.addWidget(b)
            self.nav.append(b)

        sv.addStretch(1)
        self.hint = QLabel("Enter to send\nShift+Enter new line")
        self.hint.setObjectName("Muted")
        self.hint.setStyleSheet("font-size:11px")
        sv.addWidget(self.hint)
        h.addWidget(side)
        h.addWidget(self.pages, 1)

        QAction("", self, shortcut="F11", triggered=self.toggle_fullscreen_face)
        QAction("", self, shortcut="Esc", triggered=self._escape)
        self.toast = Toast(root)
        self.desk_note = DesktopNote()

        # tray
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(QIcon(logo_pixmap(64)), self)
            self.tray.setToolTip("Pocket — your laptop agent")
            menu = self.tray.contextMenu() or QMenu(self)
            open_act = QAction("Open Pocket", self)
            open_act.triggered.connect(self.raise_and_focus)
            menu.addAction(open_act)
            talk_act = QAction("Talk to Pocket  (Ctrl+Alt+Space)", self)
            talk_act.triggered.connect(self.push_to_talk)
            menu.addAction(talk_act)
            quit_act = QAction("Quit", self)
            quit_act.triggered.connect(self._quit)
            menu.addAction(quit_act)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self._tray_clicked)
            self.tray.show()

        # stall watchdog: if a turn goes quiet, say so instead of looking frozen
        self._last_activity = 0.0
        self._watch = QTimer(self)
        self._watch.setInterval(5000)
        self._watch.timeout.connect(self._check_stall)
        self._watch.start()

        self.watcher = ReminderWatcher()
        self.watcher.fired.connect(self.on_reminder)
        self.watcher.start()
        # make sure the background thread dies cleanly even if Quit comes from the tray
        QApplication.instance().aboutToQuit.connect(self._shutdown)

        self.go(0)
        self.chat_page.render_history()
        self.start_hotkey()
        self.load_mood()
        if config.load().get("overlay_enabled", True):
            QTimer.singleShot(600, self.show_overlay)
        if config.load().get("always_listening", False):
            QTimer.singleShot(1200, self.start_conversation)

        if not config.load().get("api_key"):
            QTimer.singleShot(400, lambda: self.toast.show_message(
                "Add your free Gemini key in Settings to start →", 12000
            ))

    # ------------------------------------------------------------------ voice
    def start_hotkey(self):
        """Ctrl+Alt+Space talks to me, even when the window is in the background."""
        self.hotkey = voice.Hotkey(on_talk=self._hotkey_talk,
                                   on_ask=self._hotkey_ask)
        if not self.hotkey.available():
            self.chat_page.mic_hint.setText("push-to-talk needs: pip install pynput")
            return
        if not self.hotkey.start():
            self.chat_page.mic_hint.setText("push-to-talk hotkey could not start")
            return
        key = (config.load().get("hotkey_talk") or "ctrl+alt+space").upper()
        self.chat_page.mic_hint.setText("%s to talk · Ctrl+Alt+Q to type" % key)

    def _hotkey_talk(self):
        # always hop to the UI thread
        QTimer.singleShot(0, self.push_to_talk)

    def _hotkey_ask(self):
        """Ctrl+Alt+Q is the *only* shortcut that brings the dashboard up."""
        QTimer.singleShot(0, self.raise_and_focus)

    def raise_and_focus(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        try:
            self.chat_page.input.setFocus()
        except Exception:
            pass

    # ------------------------------------------------------ always-on ears
    def start_conversation(self):
        """Switch the ears on and leave them on - no key presses."""
        if self.conversation and self.conversation.isRunning():
            return
        if not self.listener.available():
            self._note_on_face(self.listener.problem or
                               "No microphone found — check Windows privacy "
                               "settings for microphone access.")
            return
        cfg = config.load()
        wake = (cfg.get("wake_word") or "").strip() if cfg.get("wake_enabled") else ""
        print_vec = self.load_voiceprint() if cfg.get("voice_id_enabled") else []
        self.conversation = ConversationLoop(
            self.listener,
            is_busy=lambda: self.busy,
            is_speaking=lambda: self._speaking,
            wake_phrase=wake,
            voiceprint=print_vec,
            threshold=float(cfg.get("voice_threshold", 0.45)),
        )
        self.conversation.heard.connect(self._on_conversation_heard)
        self.conversation.noted.connect(self._on_conversation_note)
        self.conversation.state.connect(self._on_conversation_state)
        self.conversation.level.connect(self.chat_page.orb.set_level)
        self.conversation.held.connect(self._on_conversation_held)
        self.conversation.stranger.connect(
            lambda sc: self._on_conversation_note(
                "That voice isn't you (match %.0f%%) — ignoring it." % (sc * 100))
        )
        self.conversation.start()
        self.chat_page.orb.set_state("listening")
        self.chat_page.status.setText(
            'Listening for "%s"…' % wake if wake else "Listening — just talk to me.")
        self.chat_page.talk_btn.setText("Stop listening")
        # the dashboard never jumps in front on its own - the face speaks for it
        if wake:
            self.speak("At your service, sir.")
        else:
            self.speak("Listening, sir.")

    def _note_on_face(self, msg: str, speak_it: bool = True):
        """Tell the user something without ever pulling the dashboard up."""
        try:
            self.chat_page.status.setText(msg)
        except Exception:
            pass
        try:
            self.desk_note.show_text(msg)
        except Exception:
            pass
        if self.overlay:
            try:
                self.overlay.flash()
            except Exception:
                pass
        if speak_it:
            self.speak(msg)

    def stop_conversation(self):
        if self.conversation:
            self.conversation.stop_loop()
            self.conversation.wait(1500)
            self.conversation = None
        self.chat_page.orb.set_state("idle")
        self.chat_page.talk_btn.setText("Start listening")
        self.chat_page.status.setText("Not listening")

    # -------------------------------------------------------------- overlay
    def show_overlay(self):
        if self.overlay is None:
            self.overlay = FloatingFace(self, size=96)
            self.overlay.place(self._overlay_pos)
        self.overlay.show()
        self.overlay.raise_()

    def hide_overlay(self):
        if self.overlay:
            self.overlay.hide()

    def save_overlay_pos(self, pos):
        if pos is not None:
            self._overlay_pos = pos

    def changeEvent(self, ev):
        """Minimising turns the window into the watermark."""
        super().changeEvent(ev)
        try:
            if ev.type() == ev.Type.WindowStateChange and self.isMinimized():
                QTimer.singleShot(150, self.show_overlay)
        except Exception:
            pass

    def toggle_fullscreen_face(self):
        if self.face_window:
            self.face_window.close()
            self.face_window = None
            return
        self.face_window = FaceWindow(self)
        self.face_window.showFullScreen()

    def toggle_conversation(self):
        if self.conversation and self.conversation.isRunning():
            self.stop_conversation()
        else:
            self.start_conversation()

    def _on_conversation_heard(self, text: str):
        self.chat_page.orb.set_state("thinking")
        self.chat_page.status.setText("Heard: %s" % text[:60])
        self.chat_page.input.setPlainText(text)
        self.chat_page.submit(spoken=True)

    def _on_conversation_note(self, msg: str):
        """Listening-loop messages: status line + a desktop note when it matters."""
        self.chat_page.status.setText(msg)
        low = (msg or "").lower()
        important = any(k in low for k in ("microphone", "internet", "transcrib",
                                           "couldn't", "can't reach", "ignoring",
                                           "yes sir"))
        if important:
            try:
                self.desk_note.show_text(msg, 6000)
            except Exception:
                pass

    def _on_conversation_state(self, st: str):
        if st == "listening" and not self.busy:
            self.chat_page.orb.set_state("listening")

    def _on_conversation_held(self):
        self.chat_page.orb.set_state("idle")
        self.chat_page.talk_btn.setText("Start listening")

    # ---------------------------------------------------------- voiceprint
    def _print_path(self):
        return os.path.join(config.APP_DIR, "voiceprint.json")

    def load_voiceprint(self):
        import json

        try:
            with open(self._print_path(), "r", encoding="utf-8") as f:
                return json.load(f).get("vector", [])
        except Exception:
            return []

    def save_voiceprint(self, vectors):
        import json

        import voiceprint as vp

        os.makedirs(config.APP_DIR, exist_ok=True)
        vec = vp.centroid(vectors)
        with open(self._print_path(), "w", encoding="utf-8") as f:
            json.dump({"vector": vec, "samples": len(vectors)}, f)
        return vec

    def has_voiceprint(self):
        return bool(self.load_voiceprint())

    # ------------------------------------------------------------ fatigue
    def _mood_file(self) -> str:
        return os.path.join(config.APP_DIR, "mood.json")

    def load_mood(self):
        """How tired it is persists between launches."""
        import json

        mood, last = 1.0, time.time()
        try:
            with open(self._mood_file(), "r", encoding="utf-8") as f:
                data = json.load(f)
            mood = float(data.get("mood", 1.0))
            last = float(data.get("last", time.time()))
        except Exception:
            pass
        # a night's rest restores it: ~10% per hour of not being used
        hours_off = max(0.0, (time.time() - last) / 3600.0)
        mood = min(1.0, mood + hours_off * 0.10)
        self.agent.mood = mood
        self.apply_mood()

    def save_mood(self):
        import json

        try:
            os.makedirs(config.APP_DIR, exist_ok=True)
            with open(self._mood_file(), "w", encoding="utf-8") as f:
                json.dump({"mood": round(getattr(self.agent, "mood", 1.0), 4),
                           "last": time.time()}, f)
        except Exception:
            pass

    def apply_mood(self):
        mood = getattr(self.agent, "mood", 1.0)
        if mood < 0.25:
            state = "tired"
        else:
            state = "idle"
        if not self.busy and not self._speaking:
            self.chat_page.orb.set_mood(mood)
            if self.chat_page.orb.state in ("idle", "tired"):
                self.chat_page.orb.set_state(state)
        # a worn voice speaks slower, softer, lower
        rate = int(86 + 92 * mood)
        pitch = int(50 + 22 * (mood - 0.5))
        volume = 0.62 + 0.38 * mood
        self.speaker.set_voice_character(rate=rate, pitch=pitch, volume=volume)
        self.chat_page.mood_label.setText(
            "energy %d%%" % int(mood * 100) if mood < 0.98 else "")

    def spend_energy(self):
        """Every turn wears it down a little; low energy sounds tired."""
        self.agent.mood = max(0.06, getattr(self.agent, "mood", 1.0) - 0.012)
        self.apply_mood()
        self.save_mood()

    def push_to_talk(self):
        # first press starts the always-on ears; pressing again stops them
        if self.conversation and self.conversation.isRunning():
            self.stop_conversation()
            return
        if config.load().get("always_listening", False):
            self.start_conversation()
            return
        if self.busy or self.listener.busy:
            self.toast.show_message("Still working on the last one…")
            return
        if not self.listener.available():
            self.toast.show_message(
                self.listener.problem or
                "No microphone found. Check Windows → Privacy → Microphone → "
                "allow desktop apps.", 12000)
            return
        self.raise_and_focus()
        self.chat_page.orb.set_state("listening")
        self.chat_page.status.setText("Listening…")
        self.chat_page.talk_btn.setText("Listening…")
        self.speaker.stop()

        self._listen_worker = ListenWorker(self.listener,
                                           on_level=self.chat_page.orb.set_level)
        self._listen_worker.state.connect(
            lambda st: self.chat_page.orb.set_state(
                "thinking" if st == "thinking" else "listening")
        )
        self._listen_worker.level.connect(self.chat_page.orb.set_level)
        self._listen_worker.heard.connect(self._on_heard)
        self._listen_worker.failed.connect(self._on_hear_failed)
        self._listen_worker.start()

    def _stop_levels(self):
        """Nothing to tear down now - the recorder owns its own audio stream."""
        return

    def _on_heard(self, text: str):
        self._stop_levels()
        self.chat_page.orb.set_state("thinking")
        self.chat_page.talk_btn.setText("Hold a thought — press to talk")
        self.chat_page.status.setText("Heard: %s" % text[:60])
        self.chat_page.input.setPlainText(text)
        if config.load().get("voice_autosend", True):
            self.chat_page.submit()

    def _on_hear_failed(self, msg: str):
        self._stop_levels()
        self.chat_page.orb.set_state("idle")
        self.chat_page.talk_btn.setText("Hold a thought — press to talk")
        self.chat_page.status.setText(msg)
        self.toast.show_message(msg, 6000)

    def speak(self, text: str, mood: float = None):
        """Say the reply out loud. Falls back to typing when nothing can speak."""
        self._speak_n = getattr(self, "_speak_n", 0) + 1
        n = self._speak_n
        if not config.load().get("speak_replies", True):
            return
        if not text or not self.speaker.available():
            if text and not getattr(self, "_warned_no_voice", False):
                self._warned_no_voice = True
                self.chat_page.status.setText(
                    "Silent — no speech engine. Install pyttsx3 or use the "
                    "Test voice button in Settings.")
            return
        mood = getattr(self.agent, "mood", 1.0) if mood is None else mood
        spoken = text
        try:
            line = voice.weariness_line(mood)
            if line:
                spoken = line + ". " + text
        except Exception:
            pass

        self._speaking = True
        if self.conversation:
            self.conversation.mute(True)          # never listen to itself
        self.chat_page.orb.set_state("speaking")
        try:
            self.chat_page.orb.ripple()
        except Exception:
            pass

        if not self.speaker.say(spoken):
            # engine refused the utterance entirely - don't leave the ears shut
            self._speech_done()

        # safety net: the engine may never call back (or may hang). Reopen the
        # ears on a timer in case, but never before the speech really ended.
        ms = max(2500, int(len(spoken) / 12.0 * 1000 * (1.6 - 0.6 * mood)))
        QTimer.singleShot(ms, lambda: self._speech_done(n, forced=True))

    def _on_speech_finished(self):
        """Called from the speech worker thread — bounce to the UI thread."""
        try:
            self.speech_finished.emit()
        except Exception:
            pass

    def _speech_done(self, n: int = None, forced: bool = False):
        """Called when speech ends. Ignores stale timers from earlier replies."""
        if n is not None:
            if n != getattr(self, "_speak_n", 0):
                return
            if forced:
                if getattr(self, "_speak_ended", None) == n:
                    return
                try:
                    if self.speaker.is_speaking():
                        return          # still talking - the callback will fire
                except Exception:
                    pass
        self._speaking = False
        self._speak_ended = n if n is not None else getattr(self, "_speak_n", 0)
        if self.conversation:
            self.conversation.mute(False)
        if not self.busy:
            self.chat_page.orb.set_state(
                "tired" if getattr(self.agent, "mood", 1) < 0.25 else "idle")
            self.chat_page.status.setText("Ready — listening")

    # ------------------------------------------------------------------
    def go(self, idx: int):
        self.pages.setCurrentIndex(idx)
        for i, b in enumerate(self.nav):
            b.setChecked(i == idx)
        if idx == 1:
            self.rem_page.refresh()
        elif idx == 2:
            self.mem_page.refresh()

    def _tray_clicked(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.showNormal()
            self.raise_()

    def start_worker(self, worker: AskWorker):
        self.worker = worker
        live = {"text": ""}

        def on_chunk(t):
            self._last_activity = time.time()
            live["text"] += t
            self.chat_page.update_live(live["text"])

        def on_event(msg):
            self._last_activity = time.time()
            self.chat_page.status.setText(msg)

        def done(_):
            if not live["text"].strip():
                self.chat_page.add_bubble("assistant", "(no reply)")
            self.chat_page.end_live()
            self.speak(live["text"])
            self.finish()
            # if nothing spoke, make sure the ears come straight back
            if not self.speaker.available() or not config.load().get(
                    "speak_replies", True):
                self._speech_done()

        def fail(msg):
            self.chat_page.end_live()
            self.chat_page.add_bubble("system", f"⚠️ {msg}")
            self.finish()

        worker.chunk.connect(on_chunk)
        worker.event.connect(on_event)
        worker.finished_ok.connect(done)
        worker.failed.connect(fail)
        worker.start()

    def _check_stall(self):
        if not self.busy or not self._last_activity:
            return
        quiet = time.time() - self._last_activity
        if quiet > 45:
            self.chat_page.status.setText(
                "Google is not responding (%d s). Press Stop and try again." % int(quiet)
            )
            # the network call may never return: give the user the UI back anyway
            if quiet > 75:
                self.chat_page.end_live()
                self.chat_page.add_bubble(
                    "system", "That request seems stuck. I've re-enabled the box — "
                              "press Stop if you still see the spinner, then try again "
                              "or use Settings → Diagnose key."
                )
                self.finish()
        elif quiet > 15:
            self.chat_page.status.setText(
                "Still waiting on Google… (%ds)" % int(quiet)
            )

    def finish(self):
        self.busy = False
        self.spend_energy()
        if self.chat_page.orb.state not in ("speaking",):
            self.chat_page.orb.set_state("idle")
        self.chat_page.send.setEnabled(True)
        self.chat_page.status.setText("Ready")
        self.rem_page.refresh()

    def stop_current(self):
        if self._listen_worker and self._listen_worker.isRunning():
            self._listen_worker.finish()
        self.agent.cancel()              # cooperative: no terminate(), no deadlocks
        self.chat_page.status.setText("Stopped")
        self.chat_page.end_live()
        self.finish()

    def on_reminder(self, r: dict):
        due = datetime.datetime.fromisoformat(r["due_at"])
        late = datetime.datetime.now() - due
        when = ""
        if late.total_seconds() > 120:
            when = f"  (was due {due.strftime('%a %d %b, %H:%M')})"
        msg = f"Reminder: {r['text']}{when}"
        self.speak(msg.replace("Reminder: ", "Reminder, sir. "))
        self.chat_page.add_bubble("system", msg)
        store.add_chat("system", msg)
        self.toast.show_message(msg, 12000)
        if self.tray:
            self.tray.showMessage("Pocket", msg,
                                  QSystemTrayIcon.MessageIcon.Information, 10000)
        self.rem_page.refresh()

    def _escape(self):
        if self.face_window:
            self.face_window.close()
            self.face_window = None
            return
        if self.isFullScreen():
            self.showNormal()

    def _quit(self):
        self._quitting = True
        QApplication.quit()

    def _shutdown(self):
        try:
            self.watcher.stop()
            self.watcher.wait(2000)
        except Exception:
            pass

    def closeEvent(self, ev):
        # closing the window keeps the agent alive in the tray unless told not to
        if (self.tray and config.load().get("close_to_tray", True)
                and not self._quitting):
            ev.ignore()
            self.hide()
            # the face stays on the desktop so he's never really gone
            if config.load().get("overlay_enabled", True):
                self._overlay_pos = self.overlay.pos() if self.overlay else None
                self.show_overlay()
            if self.tray:
                self.tray.showMessage(
                    "Pocket is still running",
                    "He's the small face on your desktop. Double-click it to open, "
                    "or press Ctrl+Alt+Space to talk.",
                    QSystemTrayIcon.MessageIcon.Information, 5000)
            return
        self._shutdown()
        ev.accept()
        if self.tray:
            self.tray.hide()
        ev.accept()


def _log_crash(exc_type, exc, tb):
    """Never leave the user staring at a dead window with no explanation."""
    import traceback
    from config import APP_DIR
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(os.path.join(APP_DIR, "error.log"), "a", encoding="utf-8") as f:
            f.write("\n--- %s ---\n" % datetime.datetime.now().isoformat())
            traceback.print_exception(exc_type, exc, tb, file=f)
    except Exception:
        pass
    try:
        QMessageBox.critical(None, "Pocket hit a problem",
                             "Something failed:\n\n%s\n\nDetails are in "
                             "PocketAgent\\error.log — the app will try to keep going."
                             % exc)
    except Exception:
        pass


def main():
    sys.excepthook = _log_crash
    store.init_db()
    app = QApplication(sys.argv)
    app.setApplicationName("Pocket")
    app.setStyleSheet(APP_QSS)
    win = MainWindow()
    if config.load().get("start_as_watermark", True):
        # the face is the app; the dashboard is summoned, not imposed
        win.showMinimized()
        QTimer.singleShot(0, win.show_overlay)
        QTimer.singleShot(250, win.hide)
    else:
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
