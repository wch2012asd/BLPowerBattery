import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from blpower.battery import is_candidate, merge_readings, query_providers


class BatteryTests(unittest.TestCase):
    def test_supported_transports(self):
        for identity in ("BTHENUM\\one", "BTHLEDEVICE\\one", "usb\\one", "HID\\one"):
            self.assertTrue(is_candidate(identity))
        self.assertFalse(is_candidate("ROOT\\USB"))

    def test_same_name_different_devices_survive(self):
        rows = [dict(name="Mouse", battery=50, instance_id=i) for i in ("HID\\A", "HID\\B")]
        self.assertEqual(len(merge_readings(rows)), 2)

    def test_invalid_battery_is_not_zero(self):
        rows = [dict(instance_id=str(i), battery=v) for i, v in enumerate(
            [None, -1, 101, True, "50", 0, 100])]
        self.assertEqual([r["battery"] for r in merge_readings(rows)], [0, 100])

    def test_source_priority_and_failure_isolation(self):
        def broken():
            raise OSError("Disconnected")
        a = dict(instance_id="HID\\A", battery=40)
        b = dict(instance_id="hid\\a", battery=60)
        self.assertEqual(query_providers([
            ("failed", broken), ("first", lambda: [a]), ("second", lambda: [b])]), [a])

    def test_missing_identity_and_empty_sources(self):
        self.assertEqual(merge_readings([dict(battery=50)]), [])
        self.assertEqual(query_providers([]), [])
