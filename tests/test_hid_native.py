import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if sys.platform == "win32":
    from blpower import hid_native as native


@unittest.skipUnless(sys.platform == "win32", "Windows HID ABI")
class NativeHidTests(unittest.TestCase):
    def test_abi_layouts(self):
        self.assertEqual(native.c.sizeof(native.Caps), 64)
        self.assertEqual(native.c.sizeof(native.ValueCaps), 72)
        self.assertEqual(native.ValueCaps.logical_min.offset, 40)
        self.assertEqual(native.ValueCaps.ranges.offset, 56)

    def test_report_id_validation(self):
        device = native.Device("test")
        device.caps = native.Caps()
        device.caps.feature_length = 8
        def unexpected(handle, buffer, length):
            buffer[0] = 7
            return True
        with patch.object(native.hid, "HidD_GetFeature", side_effect=unexpected):
            with self.assertRaises(ValueError):
                device.report(2, 3)

    def test_parse_error_does_not_become_zero(self):
        device = native.Device("test")
        with patch.object(native.hid, "HidP_GetUsageValue", return_value=-1):
            self.assertIsNone(device.value(dict(kind=2, link=0), b"\x01\x00"))
