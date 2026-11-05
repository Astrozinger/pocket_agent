"""
orb.py — the face.

A golden energy core: concentric rotating rings, radial sparks, HUD brackets and a
breathing plasma centre. States change rotation, glow and spark density so you can
read what the agent is doing from across the room.

States: idle | listening | thinking | speaking | tired
"""

import math
import random

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import (QColor, QPainter, QRadialGradient, QBrush, QPen,
                         QConicalGradient, QFont, QLinearGradient)
from PyQt6.QtWidgets import QWidget

def _a(value) -> int:
    """Clamp an alpha to a legal 0-255 range."""
    return max(0, min(255, int(value)))


AMBER = QColor("#ffb347")
GOLD = QColor("#ffd27a")
DEEP = QColor("#ff7a18")
WHITE = QColor("#fff6e0")
COOL = QColor("#6fd6ff")
DIM = QColor("#7a5a2a")


class Spark:
    __slots__ = ("angle", "dist", "speed", "life", "size", "hue")

    def __init__(self, angle, dist, speed, life, size, hue):
        self.angle = angle
        self.dist = dist
        self.speed = speed
        self.life = life
        self.size = size
        self.hue = hue


class Orb(QWidget):
    def __init__(self, parent=None, size: int = 320):
        super().__init__(parent)
        self.setMinimumSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.state = "idle"
        self.mood = 1.0            # 1.0 = fresh, 0.0 = exhausted
        self._t = 0.0
        self._level = 0.0
        self._target = 0.0
        self._sparks = []
        self._spin = 0.0
        self._spin2 = 0.0
        self._spin3 = 0.0
        self._flicker = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)          # ~30 fps
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------------------------ api
    def set_state(self, state: str):
        if state == self.state:
            return
        self.state = state
        if state == "listening":
            self._burst(26)
        elif state == "thinking":
            self._burst(14)
        elif state == "speaking":
            self._burst(10)

    def set_level(self, level: float):
        self._target = max(0.0, min(1.0, level))

    def set_mood(self, mood: float):
        self.mood = max(0.0, min(1.0, mood))

    def ripple(self, count: int = 18):
        self._burst(count)

    # ----------------------------------------------------------------- tick
    def _burst(self, n: int):
        for _ in range(n):
            self._sparks.append(Sparks.emit(self))

    def _tick(self):
        self._t += 0.033
        self._level += (self._target - self._level) * 0.30
        if self.state != "listening":
            self._target *= 0.90

        # rotation speeds per state
        speed = {
            "idle": 0.10,
            "listening": 0.26,
            "thinking": 0.85,
            "speaking": 0.40,
            "tired": 0.045,
        }.get(self.state, 0.10)
        speed *= 0.45 + 0.55 * self.mood      # exhaustion slows everything

        self._spin += speed
        self._spin2 -= speed * 1.55
        self._spin3 += speed * 0.42

        # spark emission
        rate = {"idle": 0.25, "listening": 1.4, "thinking": 2.2,
                "speaking": 1.6, "tired": 0.08}.get(self.state, 0.25)
        rate *= 0.3 + 0.7 * self.mood
        if self._level > 0.25:
            rate += self._level * 2.0
        if random.random() < rate * 0.35:
            self._sparks.append(Sparks.emit(self))

        for s in self._sparks:
            s.dist += s.speed * (0.4 + 0.6 * self.mood)
            s.angle += 0.004 * s.speed
            s.life -= 0.014
        self._sparks = [s for s in self._sparks if s.life > 0][-190:]

        # a tired core occasionally falters
        if self.state == "tired" or self.mood < 0.3:
            if random.random() < 0.02:
                self._flicker = 1.0
        self._flicker *= 0.90
        self.update()

    # ---------------------------------------------------------------- paint
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        R = min(w, h) * 0.5

        mood = self.mood
        energy = 0.55 + 0.45 * mood
        if self.state == "listening":
            energy *= 1.12 + self._level * 0.35
        if self.state == "thinking":
            energy *= 1.05
        flick = 1.0 - 0.45 * self._flicker
        energy *= flick

        base_hue = WHITE if self.state == "listening" else GOLD
        accent = DEEP if energy > 0.8 else DIM

        # ---------------------------------------------------------- HUD frame
        p.setPen(QPen(QColor(255, 179, 71, int(70 * energy)), 1.2))
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            x0 = cx + sx * R * 0.86
            y0 = cy + sy * R * 0.86
            p.drawLine(QPointF(x0, y0), QPointF(x0 - sx * R * 0.18, y0))
            p.drawLine(QPointF(x0, y0), QPointF(x0, y0 - sy * R * 0.18))
        p.setPen(QPen(QColor(255, 179, 71, int(38 * energy)), 1))
        p.drawLine(QPointF(cx - R * 0.62, cy - R * 0.9),
                   QPointF(cx + R * 0.62, cy - R * 0.9))

        # ------------------------------------------------------- outer glow
        glow = QRadialGradient(QPointF(cx, cy), R * 1.02)
        c = QColor(accent)
        c.setAlpha(_a(90 * energy))
        glow.setColorAt(0.0, c)
        mid = QColor(DEEP)
        mid.setAlpha(_a(52 * energy))
        glow.setColorAt(0.45, mid)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), R * 1.02, R * 1.02)

        # --------------------------------------------------------- sparks
        for s in self._sparks:
            a = (s.angle + self._spin3 * 0.2) % (2 * math.pi)
            rr = s.dist * R
            x = cx + math.cos(a) * rr
            y = cy + math.sin(a) * rr
            alpha = int(230 * max(0.0, s.life) * energy)
            col = QColor(s.hue)
            col.setAlpha(_a(alpha))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col))
            p.drawEllipse(QPointF(x, y), s.size, s.size)

        # ------------------------------------------------- rotating rings
        # ring 3 (outer, segmented ticks)
        self._ticks(p, cx, cy, R * 0.80, self._spin, 78, 0.55, energy)
        # ring 2 (dashed arcs, reverse)
        self._arcs(p, cx, cy, R * 0.66, self._spin2, energy, cool=False)
        # ring 1 (inner, bright sweeping arc)
        self._sweep(p, cx, cy, R * 0.50, self._spin3, energy)
        # thin containment circle
        pen = QPen(QColor(255, 200, 120, int(120 * energy)), 1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), R * 0.44, R * 0.44)

        # ------------------------------------------------------------ core
        pulse = 1.0 + 0.05 * math.sin(self._t * 2.2)
        if self.state == "listening":
            pulse += self._level * 0.22
        elif self.state == "speaking":
            pulse += 0.07 * abs(math.sin(self._t * 8.0))
        core_r = R * 0.30 * pulse

        cg = QRadialGradient(QPointF(cx, cy), core_r * 1.5)
        cg.setColorAt(0.0, QColor(255, 255, 245,
                                  max(0, min(255, int(255 * min(1.0, energy + 0.2))))))
        cg.setColorAt(0.35, QColor(base_hue.red(), base_hue.green(), base_hue.blue(),
                                   int(235 * energy)))
        cg.setColorAt(0.75, QColor(DEEP.red(), DEEP.green(), DEEP.blue(),
                                   int(150 * energy)))
        cg.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(cg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), core_r * 1.5, core_r * 1.5)

        # plasma filaments inside the core
        p.setPen(QPen(QColor(255, 240, 200, int(150 * energy)), 1.4))
        for i in range(3):
            phase = self._t * (1.1 + i * 0.35) + i * 2.1
            radius = core_r * (0.62 - i * 0.13)
            rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
            p.drawArc(rect, int(math.degrees(phase) * 16) % 5760, 120 * 16)

        # listening waveform bars through the middle
        if self.state in ("listening", "speaking"):
            p.setPen(Qt.PenStyle.NoPen)
            n = 9
            for i in range(n):
                phase = self._t * 9.0 + i * 0.7
                amp = 0.25 + 0.75 * abs(math.sin(phase))
                if self.state == "listening":
                    amp *= max(0.18, self._level + 0.12)
                bh = core_r * 1.15 * amp
                bw = max(2.0, core_r * 0.075)
                x = cx + (i - (n - 1) / 2.0) * core_r * 0.20
                col = QColor(255, 255, 235, int(210 * energy))
                p.setBrush(QBrush(col))
                p.drawRoundedRect(QRectF(x - bw / 2, cy - bh / 2, bw, bh),
                                  bw / 2, bw / 2)

        # thinking: orbiting node
        if self.state == "thinking":
            a = self._t * 5.0
            rr = R * 0.50
            x, y = cx + math.cos(a) * rr, cy + math.sin(a) * rr
            ng = QRadialGradient(QPointF(x, y), R * 0.09)
            ng.setColorAt(0.0, QColor(255, 255, 255, 240))
            ng.setColorAt(1.0, QColor(255, 160, 60, 0))
            p.setBrush(QBrush(ng))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x, y), R * 0.09, R * 0.09)

        # tired: a small dim label where the light should be
        if mood < 0.25 or self.state == "tired":
            p.setPen(QColor(255, 190, 120, 120))
            f = QFont("Segoe UI", max(7, int(R * 0.055)))
            p.setFont(f)
            p.drawText(QRectF(cx - R, cy + R * 0.34, R * 2, R * 0.2),
                       Qt.AlignmentFlag.AlignCenter, "running low")

    # ------------------------------------------------------------- helpers
    def _ticks(self, p, cx, cy, radius, spin, count, alpha_mul, energy):
        """Segmented ring of small radial ticks."""
        p.setPen(QPen(QColor(255, 190, 110, int(150 * energy * alpha_mul)), 1.6))
        step = 360.0 / count
        for i in range(count):
            ang = math.radians(spin + i * step)
            long = (i % 6 == 0)
            r1 = radius * (0.93 if long else 0.965)
            r2 = radius
            p.drawLine(QPointF(cx + math.cos(ang) * r1, cy + math.sin(ang) * r1),
                       QPointF(cx + math.cos(ang) * r2, cy + math.sin(ang) * r2))

    def _arcs(self, p, cx, cy, radius, spin, energy, cool=False):
        """Broken arcs, slowly counter-rotating."""
        col = COOL if cool else QColor(255, 150, 60)
        col.setAlpha(_a(200 * energy))
        p.setPen(QPen(col, 2.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        for k in range(4):
            start = spin + k * 90.0
            p.drawArc(rect, int(start * 16), int(46 * 16))

    def _sweep(self, p, cx, cy, radius, spin, energy):
        """Bright tapering sweep - the 'scanning' arc."""
        grad = QConicalGradient(QPointF(cx, cy), -spin)
        c1 = QColor(255, 230, 170)
        c1.setAlpha(_a(255 * energy))
        c2 = QColor(255, 120, 20)
        c2.setAlpha(_a(60 * energy))
        grad.setColorAt(0.0, c1)
        grad.setColorAt(0.14, c2)
        grad.setColorAt(0.30, QColor(0, 0, 0, 0))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(QPen(QBrush(grad), 3.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), radius, radius)


class Sparks:
    """Factory for emitted particles."""

    @staticmethod
    def emit(orb: "Orb") -> Spark:
        r = min(orb.width(), orb.height()) * 0.5
        return Spark(
            angle=random.uniform(0, 2 * math.pi),
            dist=random.uniform(0.12, 0.42),
            speed=random.uniform(0.0016, 0.0075),
            life=random.uniform(0.55, 1.0),
            size=random.uniform(0.7, 2.3),
            hue=random.choice([QColor("#ffd27a"), QColor("#ffb347"),
                               QColor("#ff8a2b"), QColor("#fff2cc")]),
        )
