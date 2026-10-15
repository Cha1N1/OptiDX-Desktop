import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QToolButton, QTabWidget
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from optidx_desktop.motion import SectionMotion, PageMotion


class MotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QWidget()
        self.window.service_settings = {}
        self.layout = QVBoxLayout(self.window)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_section_rapid_reversal_finishes_open_and_can_resize(self):
        toggle = QToolButton()
        toggle.setCheckable(True)
        body = QWidget()
        content = QVBoxLayout(body)
        content.addWidget(QLabel('Advanced settings'))
        self.layout.addWidget(toggle); self.layout.addWidget(body)
        motion = SectionMotion(body, toggle)
        toggle.toggled.connect(motion.change)
        motion.change(False)
        self.window.show(); self.app.processEvents()
        toggle.setChecked(True)
        QTest.qWait(30)
        toggle.setChecked(False)
        QTest.qWait(20)
        toggle.setChecked(True)
        QTest.qWait(200)
        self.assertTrue(body.isVisible())
        self.assertEqual(body.maximumHeight(), 16777215)
        self.assertEqual(toggle.arrowType(), Qt.ArrowType.DownArrow)
        toggle.setChecked(False)
        QTest.qWait(200)
        self.assertFalse(body.isVisible())

    def test_page_switches_leave_no_effect_or_blocked_interaction(self):
        tabs = QTabWidget()
        for title in ['One', 'Two', 'Three']: tabs.addTab(QWidget(), title)
        self.layout.addWidget(tabs)
        motion = PageMotion(tabs)
        self.window.show(); self.app.processEvents()
        tabs.setCurrentIndex(1)
        QTest.qWait(20)
        tabs.setCurrentIndex(2)
        QTest.qWait(160)
        self.assertEqual(tabs.currentIndex(), 2)
        self.assertTrue(tabs.currentWidget().isEnabled())
        for i in range(tabs.count()): self.assertIsNone(tabs.widget(i).graphicsEffect())
        self.assertIsNone(motion.animation)

    def test_reduced_motion_is_immediate(self):
        self.window.service_settings = {'reduce_motion': True}
        tabs = QTabWidget()
        tabs.addTab(QWidget(), 'One'); tabs.addTab(QWidget(), 'Two')
        self.layout.addWidget(tabs)
        motion = PageMotion(tabs)
        self.window.show(); self.app.processEvents()
        tabs.setCurrentIndex(1)
        self.assertIsNone(motion.animation)
        self.assertIsNone(tabs.currentWidget().graphicsEffect())
