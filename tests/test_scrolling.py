import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import unittest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QScrollArea, QListWidget, QDialog
from PySide6.QtTest import QTest
from optidx_desktop.scrolling import SmoothScrolling, WheelMotion


class ScrollingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QWidget()
        self.window.service_settings = {}
        layout = QVBoxLayout(self.window)
        self.area = QScrollArea()
        content = QWidget(); content.resize(600, 8000)
        self.area.setWidget(content)
        layout.addWidget(self.area)
        self.scrolling = SmoothScrolling(self.window)
        self.window.resize(500, 600); self.window.show(); self.app.processEvents()
        self.bar = self.area.verticalScrollBar()

    def tearDown(self):
        self.window.close(); self.window.deleteLater(); self.app.processEvents()

    def event(self, angle=-120, pixels=0, modifiers=Qt.KeyboardModifier.NoModifier,
              phase=Qt.ScrollPhase.NoScrollPhase):
        return QWheelEvent(QPointF(20,20), QPointF(20,20), QPoint(0,pixels), QPoint(0,angle),
                           Qt.MouseButton.NoButton, modifiers, phase, False)

    def test_wheel_animates_to_target_and_repeated_ticks_accelerate(self):
        motion = WheelMotion(self.area, self.bar)
        self.assertTrue(motion.scroll(-120, now=10))
        first = motion.target
        self.assertEqual(self.bar.value(), 0)
        motion.scroll(-120, now=10.05)
        self.assertGreater(motion.target - first, first)
        target = motion.target
        QTest.qWait(200)
        self.assertEqual(self.bar.value(), target)

    def test_fractional_wheel_deltas_accumulate_without_jumping_to_native_steps(self):
        self.bar.setSingleStep(1)
        motion = WheelMotion(self.area, self.bar)
        for tick in range(40):
            self.assertTrue(motion.scroll(-1, now=10+tick*0.001))
        QTest.qWait(200)
        self.assertGreater(self.bar.value(), 0)
        self.assertLess(self.bar.value(), 10)

    def test_pause_resets_speed_and_reversal_drops_forward_target(self):
        motion = WheelMotion(self.area, self.bar)
        motion.scroll(-120, now=10)
        first = motion.target
        motion.scroll(-120, now=10.05)
        QTest.qWait(200)
        position = self.bar.value()
        motion.scroll(-120, now=11)
        self.assertEqual(motion.target - position, first)
        QTest.qWait(40)
        position = self.bar.value()
        motion.scroll(120, now=11.05)
        self.assertLess(motion.target, position)
        self.assertEqual(motion.burst, 0)

    def test_bursts_are_bounded_and_manual_drag_cancels_motion(self):
        motion = WheelMotion(self.area, self.bar)
        for tick in range(100): motion.scroll(-120, now=10+tick*0.01)
        self.assertLessEqual(motion.burst, 6)
        self.assertLessEqual(motion.target, self.area.viewport().height()*1.5)
        self.bar.sliderPressed.emit()
        self.bar.setValue(300)
        QTest.qWait(180)
        self.assertEqual(self.bar.value(), 300)
        self.assertEqual(motion.burst, 0)

    def test_real_event_delivery_and_boundary_propagation(self):
        QApplication.sendEvent(self.area.viewport(), self.event())
        self.assertIn(True, self.area._wheel_motions)
        QTest.qWait(200)
        self.assertGreater(self.bar.value(), 0)
        self.bar.setValue(self.bar.maximum())
        motion = self.area._wheel_motions[True]
        motion.cancel()
        self.assertFalse(self.scrolling.eventFilter(self.area.viewport(), self.event()))
        self.assertEqual(self.bar.value(), self.bar.maximum())

    def test_precision_modifiers_and_reduced_motion_use_native_handling(self):
        for event in [self.event(pixels=-25), self.event(modifiers=Qt.KeyboardModifier.ControlModifier),
                      self.event(phase=Qt.ScrollPhase.ScrollMomentum)]:
            self.assertFalse(self.scrolling.eventFilter(self.area.viewport(), event))
        self.window.service_settings['reduce_motion'] = True
        self.assertFalse(self.scrolling.eventFilter(self.area.viewport(), self.event()))
        self.assertFalse(hasattr(self.area, '_wheel_motions'))
        dialog = QDialog(self.window)
        listing = QListWidget(dialog)
        listing.addItems(['Row '+str(i) for i in range(100)])
        QVBoxLayout(dialog).addWidget(listing)
        dialog.show(); self.app.processEvents()
        self.assertFalse(self.scrolling.eventFilter(listing.viewport(), self.event()))
        self.assertFalse(hasattr(listing, '_wheel_motions'))
        dialog.close()

    def test_lists_use_pixel_scroll_and_hide_stops_pending_travel(self):
        listing = QListWidget(self.window)
        listing.addItems(['Row '+str(i) for i in range(100)])
        self.window.layout().addWidget(listing); listing.show(); self.app.processEvents()
        self.assertEqual(listing.verticalScrollMode(), QListWidget.ScrollMode.ScrollPerPixel)
        QApplication.sendEvent(listing.viewport(), self.event())
        motion = listing._wheel_motions[True]
        listing.hide(); self.app.processEvents()
        self.assertEqual(motion.animation.state(), motion.animation.State.Stopped)
