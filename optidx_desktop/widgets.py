"""Small shared widget helpers for feature pages."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget


def push(label, fn):
    button = QPushButton(label)
    button.clicked.connect(fn)
    return button


def help_label(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setObjectName("muted")
    return label


def section(parent, title, expanded=True):
    """Give advanced actions their own explicitly expanded scope."""
    box = QWidget()
    outer = QVBoxLayout(box)
    outer.setContentsMargins(0, 4, 0, 4)
    toggle = QToolButton()
    toggle.setText(title)
    toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    toggle.setCheckable(True)
    toggle.setChecked(expanded)
    body = QWidget()
    inner = QVBoxLayout(body)
    inner.setContentsMargins(12, 6, 0, 6)
    from .motion import SectionMotion

    body.motion = SectionMotion(body, toggle)
    toggle.toggled.connect(body.motion.change)
    body.motion.change(expanded)
    outer.addWidget(toggle)
    outer.addWidget(body)
    parent.addWidget(box)
    return inner
