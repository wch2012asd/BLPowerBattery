import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from blpower.vendor_battery import (match_adapter, read_vendor, hidpp_request,
                                    parse_arctis, parse_hidpp_status, parse_hidpp_unified)
from blpower.battery import merge_readings


class VendorTests(unittest.TestCase):
    def test_unknown_vendor_and_wrong_interface_never_receive_commands(self):
        class Fake:
            info = dict(vid=0x1038, pid=0x1260, interface=0, usage_page=0xFF00, usage=1)
            def exchange(self, *args, **kwargs):
                raise AssertionError("Must not send")
        self.assertEqual(read_vendor(Fake(), "test"), [])
        self.assertIsNone(match_adapter(dict(vid=0x1234, pid=0x5678)))

    def test_arctis_fixtures(self):
        self.assertEqual(parse_arctis(bytes.fromhex("06 18 4b 00 00 00 00 00"))["battery"], 75)
        self.assertEqual(parse_arctis(bytes.fromhex("06 18 00 00 00 00 00 00"))["battery"], 0)
        for value in (b"", b"\x06\x18\x32", bytes.fromhex("06 24 32 00 00 00 00 00"),
                      bytes.fromhex("06 18 ff 00 00 00 00 00")):
            self.assertIsNone(parse_arctis(value))

    def test_arctis_command_and_match(self):
        class Fake:
            info = dict(vid=0x1038, pid=0x12AD, interface=5, usage_page=0xFF00, usage=1, name="Arctis")
            def exchange(self, request, matches, timeout):
                self_request = bytes.fromhex("06 18 64 00 00 00 00 00")
                assert request == b"\x06\x18"
                assert matches(self_request)
                return self_request
        self.assertEqual(read_vendor(Fake(), "headset")[0]["battery"], 100)

    def test_hidpp_invalid_and_unknown_battery(self):
        for data in (None, b"", b"\x00\x00\x00", b"\xff\x00\x00", b"\x50\x00\x07"):
            self.assertIsNone(parse_hidpp_status(data))
        self.assertTrue(parse_hidpp_status(b"\x50\x00\x01")["charging"])
        self.assertIsNone(parse_hidpp_unified(b"\x00\x08\x00\x00"))
        self.assertEqual(parse_hidpp_unified(b"\x64\x08\x03\x00")["battery"], 100)

    def test_hidpp_response_correlation_and_errors(self):
        class Fake:
            def exchange(self, request, matches, timeout):
                assert request[:4] == bytes((0x11, 2, 5, 0x1A))
                assert not matches(bytes((0x11, 1, 5, 0x1A, 40, 0, 0)))
                assert not matches(bytes((0x11, 2, 5, 0x10, 40, 0, 0)))
                error = bytes((0x11, 2, 0xFF, 5, 0x1A, 2, 0))
                assert matches(error)
                return error
        self.assertIsNone(hidpp_request(Fake(), 2, 5, 1))

    def test_hidpp_multiple_slots_and_dynamic_indices(self):
        class Fake:
            info = dict(vid=0x046D, pid=0xC52B, usage_page=0xFF00, usage=2)
            def exchange(self, request, matches, timeout):
                slot, index = request[1:3]
                if slot > 2:
                    raise TimeoutError("Offline")
                if index == 0:
                    # Feature 0x1004 at a different index on each paired device.
                    assert request[4:6] == b"\x10\x04"
                    payload = bytes((slot + 5, 0, 1))
                else:
                    assert index == slot + 5
                    assert request[3] == 0x1A
                    payload = bytes((slot * 30, 4, 0, 0))
                response = (request[:4] + payload).ljust(20, b"\x00")
                assert matches(response)
                return response
        readings = merge_readings(read_vendor(Fake(), "receiver"))
        self.assertEqual([r["battery"] for r in readings], [30, 60])
        self.assertNotEqual(readings[0]["instance_id"], readings[1]["instance_id"])

    def test_legacy_feature_fallback(self):
        class Fake:
            info = dict(vid=0x046D, pid=0xC539, usage_page=0xFF00, usage=2)
            def exchange(self, request, matches, timeout):
                if request[1] != 1:
                    raise TimeoutError()
                if request[2] == 0:
                    payload = bytes((0 if request[4:6] == b"\x10\x04" else 7, 0, 0))
                else:
                    assert request[2:4] == b"\x07\x0a"
                    payload = b"\x32\x14\x00"
                return (request[:4] + payload).ljust(20, b"\x00")
        self.assertEqual(read_vendor(Fake(), "receiver")[0]["battery"], 50)
