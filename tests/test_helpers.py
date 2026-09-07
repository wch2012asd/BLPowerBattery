"""Tests for deterministic display helper functions."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blpower.display import _hex_to_rgb, _pct_to_alpha, battery_color
from blpower.version import __version__


class DisplayHelpersTest(unittest.TestCase):
    def test_release_version(self):
        self.assertEqual(__version__, "1.0.0")

    def test_battery_color_thresholds(self):
        self.assertEqual(battery_color(100), "#3ee07a")
        self.assertEqual(battery_color(50), "#3ee07a")
        self.assertEqual(battery_color(49), "#ffce4d")
        self.assertEqual(battery_color(20), "#ffce4d")
        self.assertEqual(battery_color(19), "#ff5b5b")

    def test_hex_to_rgb(self):
        self.assertEqual(_hex_to_rgb("#3ee07a"), (62, 224, 122))
        self.assertEqual(_hex_to_rgb("#fff"), (255, 255, 255))

    def test_opacity_is_clamped(self):
        self.assertEqual(_pct_to_alpha(-1), 0)
        self.assertEqual(_pct_to_alpha(100), 255)
        self.assertEqual(_pct_to_alpha(101), 255)


if __name__ == "__main__":
    unittest.main()
