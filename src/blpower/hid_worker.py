"""Qt-free, disposable HID worker. Private file IPC also works in windowed EXEs."""
import json
import sys
from pathlib import Path


def execute(request):
    if request["operation"] == "selftest":
        # Exercise bundled Qt DLLs and nested frozen workers without opening a
        # second widget or disturbing the user's running instance.
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtCore import qVersion
        from blpower.app import QApplication, DeviceCard
        from blpower.hid_service import scan_hid
        app = QApplication.instance() or QApplication([])
        card = DeviceCard("Build verification", 75, "#FFFFFF", 100, 92)
        card.resize(300, 80)
        app.processEvents()
        pixmap = card.grab()
        scan = scan_hid()
        return {"qt_version": qVersion(), "render_ok": not pixmap.isNull(),
                "hid_scan": scan}
    from blpower.hid_native import Device, enumerate_interfaces
    if request["operation"] == "enumerate":
        return {"interfaces": list(enumerate_interfaces())}
    from blpower.hid_battery import read_standard
    from blpower.vendor_battery import read_vendor, match_adapter
    interface = request["interface"]
    with Device(interface["path"]) as device:
        fields = device.battery_fields()
        adapter = match_adapter(device.info)
        diagnostics = dict(device.info, instance_id=interface["instance_id"],
                           fields=fields, adapter=adapter.name if adapter else None)
        reading, errors = read_standard(device, interface["instance_id"])
        diagnostics["errors"] = errors
        readings = [reading] if reading else []
        if reading is None and adapter is not None:
            try:
                readings = read_vendor(device, interface["instance_id"], adapter)
            except (OSError, ValueError) as exc:
                diagnostics["errors"].append(str(exc))
        diagnostics["errors"].extend(device.vendor_errors)
        diagnostics["status"] = ("ok" if readings else "query-failed" if diagnostics["errors"]
                                 else "no-battery" if fields or adapter else "unsupported")
        return {"readings": readings, "diagnostic": diagnostics}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    request_file, response_file = map(Path, args)
    try:
        result = execute(json.loads(request_file.read_text(encoding="utf-8")))
    except Exception as exc:
        result = {"error": f"{type(exc).__name__}: {exc}"}
    response_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
