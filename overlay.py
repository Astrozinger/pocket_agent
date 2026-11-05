"""
overlay.py — the watermark.

A small, always-on-top, translucent version of the face that floats over your
desktop when the main window is put away. Click it to reopen Pocket, drag it
somewhere out of the way, or hide it from its menu.
"""

from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QAction, QCursor
from PyQt6.QtWidgets import QApplication, QMenu, QVBoxLayout, QWidget

from orb import Orb


class FloatingFace(QWidget):
    """Frameless watermark orb. Stays above other windows; never steals focus."""

    def __init__(self, win, size: int = 96):
        super().__init__(None)
        self.win = win
        self._drag = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("Zinger")
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.orb = Orb(size=size)
        self.orb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.orb)

        self.setWindowOpacity(0.55)          # watermark-ish
        self._sync = QTimer(self)
        self._sync.setInterval(80)
        self._sync.timeout.connect(self._follow_state)
        self._sync.start()

    # ------------------------------------------------------------------ state
    def _follow_state(self):
        src = self.win.chat_page.orb
        self.orb.set_state(src.state)
        self.orb.set_mood(src.mood)
        self.orb.set_level(src._level)

    def flash(self, ms: int = 900):
        """Briefly brighten so the user knows something happened."""
        try:
            self.show()
            self.raise_()
            self.setWindowOpacity(0.95)
            QTimer.singleShot(ms, lambda: self.setWindowOpacity(0.55))
        except Exception:
            pass

    def place(self, pos=None):
        if pos is None:
            screen = QApplication.primaryScreen().availableGeometry()
            pos = QPoint(screen.right() - self.width() - 28,
                         screen.bottom() - self.height() - 28)
        self.move(pos)

    # ------------------------------------------------------------------ input
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif ev.button() == Qt.MouseButton.RightButton:
            self._menu()

    def mouseMoveEvent(self, ev):
        if self._drag is not None:
            self.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, ev):
        moved = (ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
                 - self._drag) if self._drag else None
        self._drag = None
        if moved is not None and moved.manhattanLength() > 6:
            self.win.save_overlay_pos(self.pos())
            return
        if ev.button() == Qt.MouseButton.LeftButton:
            self._single = QTimer.singleShot(220, self.win.raise_and_focus)

    def mouseDoubleClickEvent(self, ev):
        """Double-click goes straight to the big face."""
        self.win.toggle_fullscreen_face()

    def _menu(self):
        m = QMenu(self)
        m.setStyleSheet(
            "QMenu { background:#161d2e; color:#e7ecf5; border:1px solid #26314b; }"
            "QMenu::item:selected { background:#1d2740; }"
        )
        open_act = QAction("Open Zinger", self)
        open_act.triggered.connect(self.win.raise_and_focus)
        m.addAction(open_act)
        talk = QAction("Start / stop listening", self)
        talk.triggered.connect(self.win.toggle_conversation)
        m.addAction(talk)
        face = QAction("Full screen face", self)
        face.triggered.connect(self.win.toggle_fullscreen_face)
        m.addAction(face)
        m.addSeparator()
        hide = QAction("Hide watermark", self)
        hide.triggered.connect(self.win.hide_overlay)
        m.addAction(hide)
        m.exec(QCursor.pos())
