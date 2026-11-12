"""Bounded process isolation for HID: one stuck device cannot freeze other devices."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from blpower.battery import merge_readings


def run_worker(request, timeout=3.0):
    with tempfile.TemporaryDirectory(prefix="blpower-hid-") as folder:
        request_path, response_path = Path(folder) / "request.json", Path(folder) / "response.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--battery-worker"]
        else:
            command = [sys.executable, "-m", "blpower.hid_worker"]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
        try:
            # subprocess.run kills AND reaps timed-out children before returning.
            proc = subprocess.run(command + [str(request_path), str(response_path)],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, env=env, timeout=timeout,
                                  creationflags=0x08000000 if os.name == "nt" else 0)
            if proc.returncode or not response_path.exists():
                return {"error": f"worker-exit-{proc.returncode}"}
            return json.loads(response_path.read_text(encoding="utf-8"))
        except subprocess.TimeoutExpired:
            return {"error": "timeout"}
        except (OSError, ValueError) as exc:
            return {"error": str(exc)}


def scan_hid(worker=run_worker, budget=20.0):
    start = time.monotonic()
    enumeration = worker({"operation": "enumerate"}, timeout=min(4.0, budget))
    if "error" in enumeration:
        return {"readings": [], "diagnostics": [{"status": enumeration["error"]}]}
    interfaces = enumeration.get("interfaces", [])

    def probe(interface):
        remaining = budget - (time.monotonic() - start)
        if remaining <= 0:
            return {"error": "scan-budget-exhausted"}
        return worker({"operation": "probe", "interface": interface}, timeout=min(3.0, remaining))

    readings, diagnostics = [], []
    # The native API handles in each process are independent; no shared input queues.
    with ThreadPoolExecutor(max_workers=4) as pool:
        for interface, result in zip(interfaces, pool.map(probe, interfaces)):
            readings.extend(result.get("readings", []))
            diagnostics.append(result.get("diagnostic", {
                "instance_id": interface["instance_id"], "status": result.get("error", "unknown")}))
    return {"readings": merge_readings(readings), "diagnostics": diagnostics}


def query_hid_devices():
    return scan_hid()["readings"]
