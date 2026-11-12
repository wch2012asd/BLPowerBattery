import sys
from pathlib import Path
import unittest
import json
import subprocess
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from blpower.hid_battery import normalize, read_standard
from blpower.hid_service import scan_hid, run_worker


class StandardHidTests(unittest.TestCase):
    def test_range_scaling_and_null(self):
        self.assertEqual(normalize(127, 0, 254, 8), 50)
        self.assertIsNone(normalize(255, 0, 254, 8))
        self.assertIsNone(normalize(None, 0, 100, 8))
        self.assertIsNone(normalize(5, 5, 5, 8))
        self.assertEqual(normalize(0, 0, 100, 8), 0)
        self.assertEqual(normalize(100, 0, 100, 8), 100)
        self.assertEqual(normalize(0xFB, -10, 0, 8), 50)

    def test_feature_failure_falls_back_to_input(self):
        class Fake:
            info = {"name": "Keyboard"}
            def battery_fields(self):
                return [dict(kind=k, report_id=3, minimum=0, maximum=100, bits=8) for k in (2, 0)]
            def report(self, kind, report_id):
                if kind == 2:
                    raise OSError("Feature unavailable")
                return b"\x03\x3c"
            def value(self, field, report):
                return report[1]
        reading, errors = read_standard(Fake(), "HID\\test")
        self.assertEqual(reading["battery"], 60)
        self.assertEqual(len(errors), 1)

    def test_failed_interface_does_not_lose_success(self):
        def worker(request, timeout):
            if request["operation"] == "enumerate":
                return {"interfaces": [dict(instance_id=i) for i in ("A", "B")]}
            if request["interface"]["instance_id"] == "A":
                return {"error": "timeout"}
            return {"readings": [dict(instance_id="B", name="Headset", battery=70)]}
        result = scan_hid(worker)
        self.assertEqual(result["readings"][0]["battery"], 70)
        self.assertEqual(result["diagnostics"][0]["status"], "timeout")

    def test_enumeration_error_is_visible(self):
        result = scan_hid(lambda *a, **kw: {"error": "access-denied"})
        self.assertEqual(result["readings"], [])
        self.assertEqual(result["diagnostics"][0]["status"], "access-denied")

    @unittest.skipUnless(sys.platform == "win32", "Windows subprocess")
    def test_actual_worker_timeout(self):
        result = run_worker({"operation": "enumerate"}, timeout=0.001)
        self.assertEqual(result["error"], "timeout")

    @unittest.skipUnless(sys.platform == "win32", "Windows entry point")
    def test_app_worker_dispatch_before_qt(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            request = Path(folder) / "request.json"
            response = Path(folder) / "response.json"
            request.write_text(json.dumps({"operation": "probe", "interface": {
                "path": "\\\\?\\blpower-nonexistent-test-device", "instance_id": "test"}}))
            child = subprocess.run([sys.executable, str(root / "src/blpower/app.py"),
                                    "--battery-worker", str(request), str(response)],
                                   capture_output=True, timeout=5)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertIn("error", json.loads(response.read_text(encoding="utf-8")))
