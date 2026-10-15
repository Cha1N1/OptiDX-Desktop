"""Short, interruptible UI transitions that never delay an action."""
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QObject
from PySide6.QtWidgets import QGraphicsOpacityEffect


def reduced_motion(widget):
    window = widget.window()
    settings = getattr(window, 'service_settings', {})
    return settings.get('reduce_motion', False)


class SectionMotion(QObject):
    def __init__(self, body, toggle):
        super().__init__(body)
        self.body = body
        self.toggle = toggle
        self.animation = QPropertyAnimation(body, b'maximumHeight', self)
        self.animation.setDuration(140)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self.finish)

    def change(self, opened):
        from PySide6.QtCore import Qt
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
        start = self.body.height() if self.body.isVisible() else 0
        self.animation.stop()
        if not self.toggle.isVisible() or reduced_motion(self.body):
            self.finish()
            return
        self.body.setVisible(True)
        self.body.setMaximumHeight(16777215)
        self.body.layout().activate()
        end = self.body.sizeHint().height() if opened else 0
        self.body.setMaximumHeight(start)
        self.animation.setStartValue(start)
        self.animation.setEndValue(end)
        self.animation.start()

    def finish(self):
        opened = self.toggle.isChecked()
        self.body.setMaximumHeight(16777215 if opened else 0)
        self.body.setVisible(opened)


class PageMotion(QObject):
    def __init__(self, tabs):
        super().__init__(tabs)
        self.tabs = tabs
        self.page = None
        self.effect = None
        self.animation = None
        tabs.currentChanged.connect(self.change)

    def clear(self):
        if self.animation:
            self.animation.stop()
            self.animation.deleteLater()
            self.animation = None
        if self.page:
            self.page.setGraphicsEffect(None)
        self.page = self.effect = None

    def change(self, index):
        self.clear()
        page = self.tabs.widget(index)
        if not page or not self.tabs.isVisible() or reduced_motion(self.tabs):
            return
        self.page = page
        self.effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(self.effect)
        self.animation = QPropertyAnimation(self.effect, b'opacity', self)
        self.animation.setDuration(110)
        self.animation.setStartValue(0.78)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self.clear)
        self.animation.start()
