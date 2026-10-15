"""Accelerated mouse-wheel motion scoped to this window's scroll areas."""
import time

from PySide6.QtCore import QEvent, QEasingCurve, QObject, QPropertyAnimation, Qt
from PySide6.QtGui import QInputDevice
from PySide6.QtWidgets import QApplication, QAbstractItemView, QAbstractScrollArea, QWidget

from .motion import reduced_motion


class WheelMotion(QObject):
    """Accumulate a bounded target; reverse immediately and reset after a pause."""
    def __init__(self, area, bar):
        super().__init__(area)
        self.area = area
        self.bar = bar
        self.animation = QPropertyAnimation(bar, b'value', self)
        self.animation.setDuration(140)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.last_tick = 0
        self.direction = 0
        self.burst = 0
        self.fraction = 0.0
        self.target = bar.value()
        bar.sliderPressed.connect(self.cancel)
        bar.actionTriggered.connect(self.cancel)
        bar.rangeChanged.connect(self.cancel)

    def cancel(self, *args):
        self.animation.stop()
        self.last_tick = 0
        self.direction = 0
        self.burst = 0
        self.fraction = 0.0
        self.target = self.bar.value()

    def scroll(self, delta, now=None):
        now = time.monotonic() if now is None else now
        direction = 1 if delta < 0 else -1
        continuing = self.direction == direction and 0 <= now - self.last_tick < 0.22
        running = self.animation.state() == QPropertyAnimation.State.Running
        base = self.target if continuing and running else self.bar.value()
        self.burst = min(6, self.burst + abs(delta) / 120) if continuing else 0
        if not continuing:
            self.fraction = 0.0
        gain = 1 + self.burst * 0.35
        distance = -delta / 120 * self.bar.singleStep() * QApplication.wheelScrollLines() * gain + self.fraction
        # Bound pending travel, so stopping the wheel never leaves a long coast.
        span = self.area.viewport().height() if self.bar.orientation() == Qt.Orientation.Vertical else self.area.viewport().width()
        limit = max(self.bar.singleStep() * 3, span * 1.5)
        target = min(self.bar.maximum(), max(self.bar.minimum(),
                     min(self.bar.value() + limit, max(self.bar.value() - limit, base + distance))))
        self.animation.stop()
        self.last_tick, self.direction, self.target = now, direction, int(round(target))
        self.fraction = target - self.target
        if self.target == self.bar.value():
            if self.fraction:
                return True  # Retain sub-pixel high-resolution wheel movement.
            self.cancel()
            return False  # Let Qt propagate a wheel at an exhausted boundary.
        self.animation.setStartValue(self.bar.value())
        self.animation.setEndValue(self.target)
        self.animation.start()
        return True


class SmoothScrolling(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in {QEvent.Type.Wheel, QEvent.Type.Show, QEvent.Type.Hide,
                        QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress}:
            return False
        if not isinstance(watched, QWidget) or not self.window.isAncestorOf(watched):
            return False
        area = watched if isinstance(watched, QAbstractScrollArea) else watched.parentWidget()
        if not isinstance(area, QAbstractScrollArea) or area.window().windowType() == Qt.WindowType.Popup:
            return False
        if kind == QEvent.Type.Show:
            if isinstance(area, QAbstractItemView):
                area.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
                area.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            return False
        motions = getattr(area, '_wheel_motions', {})
        if kind != QEvent.Type.Wheel:
            for motion in motions.values(): motion.cancel()
            return False
        if watched is not area.viewport():
            return False
        if (reduced_motion(self.window) or not event.pixelDelta().isNull() or
                event.device().type() == QInputDevice.DeviceType.TouchPad or
                event.phase() != Qt.ScrollPhase.NoScrollPhase or
                event.modifiers() != Qt.KeyboardModifier.NoModifier or event.buttons() != Qt.MouseButton.NoButton):
            for motion in motions.values(): motion.cancel()
            return False  # Native precision gestures, modifiers and selection.
        vertical = bool(event.angleDelta().y())
        delta = event.angleDelta().y() if vertical else event.angleDelta().x()
        if not delta:
            return False
        bar = area.verticalScrollBar() if vertical else area.horizontalScrollBar()
        if bar.maximum() <= bar.minimum() or bar.isSliderDown():
            return False
        if vertical not in motions:
            motions[vertical] = WheelMotion(area, bar)
            area._wheel_motions = motions
        if motions[vertical].scroll(delta):
            event.accept()
            return True
        return False
