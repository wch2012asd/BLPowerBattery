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

    def test_extract_bt_mac(self):
        mac = "0013d68bc6eb"
        # 蓝牙根设备节点
        self.assertEqual(
            provider._extract_bt_mac(
                "BTHLE\\DEV_0013D68BC6EB\\7&2FEC0A54&0&0013D68BC6EB"), mac)
        # 蓝牙服务节点（MAC 在实例 ID 尾段）
        self.assertEqual(
            provider._extract_bt_mac(
                "BTHENUM\\{0000111E-0000-1000-8000-00805F9B34FB}_VID&000102B0_"
                "PID&0000\\7&33F8E0FF&0&0013D68BC6EB_C00000000"), mac)
        # 非蓝牙设备不产生 MAC
        self.assertIsNone(
            provider._extract_bt_mac("USB\\VID_046D&PID_C52B\\6&1234ABCD&0&2"))
        self.assertIsNone(provider._extract_bt_mac(""))

    def test_filter_hides_disconnected_device(self):
        rows = [
            dict(instance_id="BTHENUM\\{0000111E-0000-1000-8000-00805F9B34FB}"
                 "_VID&000102B0_PID&0000\\7&33F8E0FF&0&0013D68BC6EB_C00000000",
                 name="Xiaomi 耳夹式耳机 Hands-Free AG", battery=32),
            dict(instance_id="BTHLE\\DEV_F4EE251AC3A9\\7&2FEC0A54&0&F4EE251AC3A9",
                 name="AJ159 APEX", battery=94),
        ]
        flags = {"0013d68bc6eb": True, "f4ee251ac3a9": False}
        with patch.object(provider, "_scan_bth_root_flags", return_value=flags):
            kept = provider._filter_disconnected(rows)
        self.assertEqual([r["name"] for r in kept], ["AJ159 APEX"])

    def test_filter_skips_scan_without_bluetooth_readings(self):
        rows = [dict(instance_id="USB\\A", name="Mouse", battery=42)]
        with patch.object(provider, "_scan_bth_root_flags") as scan:
            self.assertEqual(provider._filter_disconnected(rows), rows)
        scan.assert_not_called()

    def test_filter_fails_open_when_scan_fails(self):
        rows = [dict(instance_id="BTHLE\\DEV_F4EE251AC3A9\\7&1&0&F4EE251AC3A9",
                     name="AJ159 APEX", battery=94)]
        with patch.object(provider, "_scan_bth_root_flags",
                          side_effect=OSError("API failed")):
            self.assertEqual(provider._filter_disconnected(rows), rows)
