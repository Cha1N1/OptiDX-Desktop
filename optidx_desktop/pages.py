"""Pages own their controls and raw draft serialization."""

from PySide6.QtWidgets import QWidget, QCheckBox, QComboBox, QPlainTextEdit


def bind(widget, key):
    widget.setProperty("draftKey", key)
    return widget


class ProfilePage(QWidget):
    def controls(self):
        return [widget for widget in self.findChildren(QWidget) if widget.property("draftKey")]

    def collect(self):
        values = {}
        for widget in self.controls():
            if isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QComboBox):
                value = widget.currentText()
            elif isinstance(widget, QPlainTextEdit):
                value = widget.toPlainText()
            else:
                value = widget.text()
            values[widget.property("draftKey")] = value
        return values

    def load(self, profile):
        for widget in self.controls():
            key = widget.property("draftKey")
            if key not in profile:
                continue
            if isinstance(widget, QCheckBox):
                widget.setChecked(profile[key])
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(profile[key])
            elif isinstance(widget, QPlainTextEdit):
                widget.setPlainText(profile[key])
            else:
                widget.setText(profile[key])


class InstallationPage(ProfilePage):
    def add_maintenance_widget(self, widget):
        self.maintenance.addWidget(widget)

    def add_maintenance_layout(self, layout):
        self.maintenance.addLayout(layout)

    def add_section(self, title):
        from .feature_ui import section

        return section(self.content, title, expanded=False)
