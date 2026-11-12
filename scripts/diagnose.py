"""Export a shareable HID compatibility report without Qt or third-party packages."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from blpower.hid_service import scan_hid
from blpower.windows_battery import query_windows_devices
from blpower.version import __version__


def main():
    parser = argparse.ArgumentParser(description="BLPower wireless battery diagnostics")
    parser.add_argument("--output", default="battery-diagnostics.json")
    args = parser.parse_args()
    report = scan_hid()
    report["windows_readings"] = query_windows_devices()
    report["version"] = __version__
    # Preserve cross-source correlation while excluding device serials and paths.
    for rows in (report["readings"], report["diagnostics"], report["windows_readings"]):
        for row in rows:
            identity = row.pop("instance_id", None)
            if identity:
                row["device_id"] = hashlib.sha256(identity.casefold().encode()).hexdigest()[:16]
            row.pop("path", None)
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved: {Path(args.output).resolve()}")
    print(f"HID interfaces: {len(report['diagnostics'])}; battery readings: {len(report['readings'])}")


if __name__ == "__main__":
    main()
