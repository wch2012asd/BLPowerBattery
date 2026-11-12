import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if sys.platform == "win32":
    from blpower import windows_battery as provider


@unittest.skipUnless(sys.platform == "win32", "Windows API tests")
class WindowsBatteryTests(unittest.TestCase):
    def test_empty_scan_does_not_run_powershell(self):
        with patch.object(provider, "_query_via_setupapi", return_value=[]), \
                patch.object(provider, "_query_via_powershell") as fallback:
            self.assertEqual(provider.query_windows_devices(), [])
            fallback.assert_not_called()

    def test_failure_uses_fallback(self):
        rows = [dict(instance_id="USB\\A", name="Mouse", battery=42)]
        with patch.object(provider, "_query_via_setupapi", side_effect=OSError("API failed")), \
                patch.object(provider, "_query_via_powershell", return_value=rows) as fallback:
            self.assertEqual(provider.query_windows_devices(), rows)
            fallback.assert_called_once()

    def test_invalid_handle_is_rejected(self):
        with patch.object(provider._setupapi, "SetupDiGetClassDevsW",
                          return_value=provider.ctypes.c_void_p(-1).value):
            with self.assertRaises(OSError):
                provider._query_via_setupapi()

    def test_enumeration_failure_releases_handle(self):
        with patch.object(provider._setupapi, "SetupDiGetClassDevsW", return_value=123), \
                patch.object(provider._setupapi, "SetupDiEnumDeviceInfo", return_value=False), \
                patch.object(provider.ctypes, "get_last_error", return_value=5), \
                patch.object(provider._setupapi, "SetupDiDestroyDeviceInfoList") as close:
            with self.assertRaises(OSError):
                provider._query_via_setupapi()
            close.assert_called_once_with(123)
