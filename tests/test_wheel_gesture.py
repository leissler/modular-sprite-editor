import unittest

from ui.base_canvas import (
    ZOOM_LEVELS,
    WheelGestureFilter,
    nearest_zoom_level,
    snap_zoom_level,
    wheel_zoom_factor,
)

FRAME = 1.0 / 60.0  # trackpads report at display rate


def _run(filter_, events, start=0.0):
    """events: list of (horizontal, rotation); returns the accepted ones."""
    accepted = []
    for i, (horizontal, rotation) in enumerate(events):
        if filter_.accept(horizontal, rotation, now=start + i * FRAME):
            accepted.append((horizontal, rotation))
    return accepted


class TestWheelGestureFilter(unittest.TestCase):
    def test_vertical_trackpad_gesture_ignores_sideways_noise(self):
        events = []
        for _ in range(20):
            events += [(False, 9), (True, 2), (False, 11), (True, -3)]
        accepted = _run(WheelGestureFilter(), events)
        self.assertTrue(accepted)
        self.assertTrue(all(not horizontal for horizontal, _ in accepted))

    def test_sideways_swipe_ignores_vertical_noise(self):
        events = []
        for _ in range(20):
            events += [(True, 10), (False, 2), (True, 8), (False, -1)]
        accepted = _run(WheelGestureFilter(), events)
        self.assertTrue(accepted)
        self.assertTrue(all(horizontal for horizontal, _ in accepted))

    def test_mouse_notch_is_accepted_immediately(self):
        filter_ = WheelGestureFilter()
        self.assertTrue(filter_.accept(False, 120, now=0.0))
        self.assertTrue(filter_.gesture_started)
        self.assertTrue(filter_.accept(False, -120, now=0.05))
        self.assertFalse(filter_.gesture_started)

    def test_pause_starts_a_new_gesture_on_another_axis(self):
        filter_ = WheelGestureFilter()
        self.assertTrue(_run(filter_, [(False, 20)] * 5, start=0.0))
        later = 5 * FRAME + WheelGestureFilter.GESTURE_GAP_SECONDS + 0.05
        accepted = _run(filter_, [(True, 20)] * 5, start=later)
        self.assertEqual(len(accepted), 5)

    def test_gesture_started_marks_first_accepted_event(self):
        filter_ = WheelGestureFilter()
        # Small first event is undecided (dropped); the start flag moves to the first accepted one.
        self.assertFalse(filter_.accept(False, 5, now=0.0))
        self.assertTrue(filter_.accept(False, 9, now=FRAME))
        self.assertTrue(filter_.gesture_started)
        self.assertTrue(filter_.accept(False, 9, now=2 * FRAME))
        self.assertFalse(filter_.gesture_started)

    def test_single_macos_mouse_notch_is_accepted(self):
        # wxOSX reports a notch as rotation 10 with wheel delta 10.
        filter_ = WheelGestureFilter()
        self.assertTrue(filter_.accept(False, 10, now=0.0, wheel_delta=10))
        self.assertTrue(WheelGestureFilter().accept(False, -120, now=0.0, wheel_delta=120))

    def test_axis_is_held_during_momentum(self):
        filter_ = WheelGestureFilter()
        # Strong vertical start, then decaying momentum with occasional sideways jitter.
        events = [(False, 30)] * 3 + [(False, 4), (True, 3)] * 30
        accepted = _run(filter_, events)
        self.assertTrue(all(not horizontal for horizontal, _ in accepted))


class TestZoomSnapping(unittest.TestCase):
    def test_notch_factor_is_platform_independent(self):
        self.assertAlmostEqual(wheel_zoom_factor(10, 10), wheel_zoom_factor(120, 120))
        self.assertAlmostEqual(wheel_zoom_factor(10, 10), 1.1)
        self.assertLessEqual(wheel_zoom_factor(10_000, 10), 1.6 + 1e-9)

    def test_nearest_level_is_logarithmic(self):
        self.assertEqual(nearest_zoom_level(3.4, ZOOM_LEVELS), 3.0)
        self.assertEqual(nearest_zoom_level(3.6, ZOOM_LEVELS), 4.0)
        self.assertEqual(nearest_zoom_level(13.5, ZOOM_LEVELS), 12.0)

    def test_single_notch_moves_exactly_one_level(self):
        levels = sorted(ZOOM_LEVELS)
        for i, level in enumerate(levels):
            up = snap_zoom_level(level * 1.1, level, ZOOM_LEVELS)
            down = snap_zoom_level(level / 1.1, level, ZOOM_LEVELS)
            self.assertEqual(up, levels[min(i + 1, len(levels) - 1)])
            self.assertEqual(down, levels[max(i - 1, 0)])

    def test_overshoot_snaps_to_nearest_and_wiggle_stays(self):
        self.assertEqual(snap_zoom_level(4.3, 3.0, ZOOM_LEVELS), 4.0)
        self.assertEqual(snap_zoom_level(4.01, 4.0, ZOOM_LEVELS), 4.0)


if __name__ == "__main__":
    unittest.main()
