"""Small Windows HID backend. Call only inside a disposable worker process."""
import ctypes as c
import re
import time
from ctypes import wintypes as w

from blpower.windows_battery import _GUID, _SP_DEVINFO_DATA, _setupapi

P = c.c_void_p
U16, U32, I32, U8 = c.c_uint16, c.c_uint32, c.c_int32, c.c_ubyte
SUCCESS = 0x00110000


class Interface(c.Structure):
    _fields_ = [("size", U32), ("guid", _GUID), ("flags", U32), ("reserved", P)]


class Caps(c.Structure):
    _fields_ = [("usage", U16), ("page", U16), ("input_length", U16),
                ("output_length", U16), ("feature_length", U16), ("reserved", U16 * 17),
                ("links", U16), ("input_buttons", U16), ("input_values", U16),
                ("input_indices", U16), ("output_buttons", U16), ("output_values", U16),
                ("output_indices", U16), ("feature_buttons", U16),
                ("feature_values", U16), ("feature_indices", U16)]


class ValueCaps(c.Structure):
    _fields_ = [("page", U16), ("report_id", U8), ("alias", U8),
                ("bit_field", U16), ("link", U16), ("link_usage", U16),
                ("link_page", U16), ("is_range", U8), ("string_range", U8),
                ("designator_range", U8), ("absolute", U8), ("has_null", U8),
                ("reserved", U8), ("bits", U16), ("count", U16),
                ("reserved2", U16 * 5), ("units_exp", U32), ("units", U32),
                ("logical_min", I32), ("logical_max", I32),
                ("physical_min", I32), ("physical_max", I32), ("ranges", U16 * 8)]


class Attributes(c.Structure):
    _fields_ = [("size", U32), ("vid", U16), ("pid", U16), ("version", U16)]


class Overlapped(c.Structure):
    _fields_ = [("internal", c.c_size_t), ("internal_high", c.c_size_t),
                ("offset", U32), ("offset_high", U32), ("event", P)]


hid = c.WinDLL("hid", use_last_error=True)
kernel = c.WinDLL("kernel32", use_last_error=True)


def bind(dll, name, args, result):
    fn = getattr(dll, name)
    fn.argtypes, fn.restype = args, result
    return fn


bind(hid, "HidD_GetHidGuid", [P], None)
bind(hid, "HidD_GetAttributes", [P, P], U8)
bind(hid, "HidD_GetProductString", [P, P, U32], U8)
bind(hid, "HidD_GetPreparsedData", [P, P], U8)
bind(hid, "HidD_FreePreparsedData", [P], U8)
bind(hid, "HidP_GetCaps", [P, P], I32)
bind(hid, "HidP_GetValueCaps", [c.c_int, P, P, P], I32)
bind(hid, "HidP_GetUsageValue", [c.c_int, U16, U16, U16, P, P, P, U32], I32)
for name in ("HidD_GetFeature", "HidD_GetInputReport", "HidD_SetOutputReport"):
    bind(hid, name, [P, P, U32], U8)
bind(kernel, "CreateFileW", [w.LPCWSTR, U32, U32, P, U32, U32, P], P)
bind(kernel, "CloseHandle", [P], w.BOOL)
bind(kernel, "CreateEventW", [P, w.BOOL, w.BOOL, w.LPCWSTR], P)
bind(kernel, "WaitForSingleObject", [P, U32], U32)
bind(kernel, "GetOverlappedResult", [P, P, P, w.BOOL], w.BOOL)
bind(kernel, "CancelIoEx", [P, P], w.BOOL)
bind(kernel, "ReadFile", [P, P, U32, P, P], w.BOOL)
bind(kernel, "WriteFile", [P, P, U32, P, P], w.BOOL)
bind(_setupapi, "SetupDiEnumDeviceInterfaces", [P, P, P, U32, P], w.BOOL)
bind(_setupapi, "SetupDiGetDeviceInterfaceDetailW", [P, P, P, U32, P, P], w.BOOL)


def enumerate_interfaces():
    guid = _GUID()
    hid.HidD_GetHidGuid(c.byref(guid))
    info = _setupapi.SetupDiGetClassDevsW(c.byref(guid), None, None, 0x12)
    if info in (None, c.c_void_p(-1).value):
        raise c.WinError(c.get_last_error())
    try:
        index = 0
        while True:
            interface = Interface()
            interface.size = c.sizeof(interface)
            if not _setupapi.SetupDiEnumDeviceInterfaces(info, None, c.byref(guid), index, c.byref(interface)):
                if c.get_last_error() == 259:
                    break
                raise c.WinError(c.get_last_error())
            index += 1
            needed = U32()
            _setupapi.SetupDiGetDeviceInterfaceDetailW(info, c.byref(interface), None, 0, c.byref(needed), None)
            if not 4 < needed.value <= 65536:
                continue
            detail = c.create_string_buffer(needed.value)
            c.cast(detail, c.POINTER(U32))[0] = 8 if c.sizeof(P) == 8 else 6
            di = _SP_DEVINFO_DATA()
            di.cbSize = c.sizeof(di)
            if not _setupapi.SetupDiGetDeviceInterfaceDetailW(info, c.byref(interface), detail,
                                                            needed, None, c.byref(di)):
                continue
            iid = c.create_unicode_buffer(1024)
            if not _setupapi.SetupDiGetDeviceInstanceIdW(info, c.byref(di), iid, 1024, None):
                continue
            yield {"path": c.wstring_at(c.addressof(detail) + 4), "instance_id": iid.value}
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(info)


class Device:
    def __init__(self, path):
        self.path, self.handle, self.preparsed = path, None, P()
        self.io_handle = None
        self.vendor_errors = []

    def __enter__(self):
        # Zero access permits descriptor/feature queries on mouse/keyboard collections.
        self.handle = kernel.CreateFileW(self.path, 0, 3, None, 3, 0, None)
        if self.handle in (None, c.c_void_p(-1).value):
            self.handle = None
            raise c.WinError(c.get_last_error())
        try:
            if not hid.HidD_GetPreparsedData(self.handle, c.byref(self.preparsed)):
                raise c.WinError(c.get_last_error())
            self.caps = Caps()
            if hid.HidP_GetCaps(self.preparsed, c.byref(self.caps)) != SUCCESS:
                raise OSError("Invalid HID capabilities")
            attr = Attributes()
            attr.size = c.sizeof(attr)
            if not hid.HidD_GetAttributes(self.handle, c.byref(attr)):
                raise c.WinError(c.get_last_error())
            name = c.create_unicode_buffer(256)
            hid.HidD_GetProductString(self.handle, name, c.sizeof(name))
            self.info = dict(vid=attr.vid, pid=attr.pid, firmware=attr.version,
                             name=name.value or f"HID {attr.vid:04X}:{attr.pid:04X}",
                             usage_page=self.caps.page, usage=self.caps.usage)
            interface = re.search(r"&mi_([0-9a-f]{2})", self.path, re.I)
            self.info["interface"] = int(interface[1], 16) if interface else None
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.io_handle:
            kernel.CloseHandle(self.io_handle)
            self.io_handle = None
        if self.preparsed:
            hid.HidD_FreePreparsedData(self.preparsed)
            self.preparsed = P()
        if self.handle:
            kernel.CloseHandle(self.handle)
            self.handle = None

    def battery_fields(self):
        fields = []
        for kind, count in ((2, self.caps.feature_values), (0, self.caps.input_values)):
            if not count:
                continue
            values = (ValueCaps * count)()
            size = U16(count)
            if hid.HidP_GetValueCaps(kind, values, c.byref(size), self.preparsed) != SUCCESS:
                continue
            for value in values[:size.value]:
                low = value.ranges[0]
                high = value.ranges[1] if value.is_range else low
                if (value.page == 6 and low <= 0x20 <= high and value.absolute
                        and not value.bit_field & 1 and (value.is_range or value.count == 1)):
                    fields.append(dict(kind=kind, report_id=value.report_id, link=value.link,
                                       minimum=value.logical_min, maximum=value.logical_max,
                                       bits=value.bits, has_null=bool(value.has_null)))
        return fields

    def report(self, kind, report_id):
        length = self.caps.feature_length if kind == 2 else self.caps.input_length
        if not 1 <= length <= 65535:
            raise ValueError("Invalid HID report length")
        buf = (U8 * length)()
        buf[0] = report_id
        fn = hid.HidD_GetFeature if kind == 2 else hid.HidD_GetInputReport
        if not fn(self.handle, buf, length):
            raise c.WinError(c.get_last_error())
        if buf[0] != report_id:
            raise ValueError("Unexpected report ID")
        return bytes(buf)

    def value(self, field, report):
        raw = U32()
        buf = c.create_string_buffer(report)
        status = hid.HidP_GetUsageValue(field["kind"], 6, field["link"], 0x20,
                                       c.byref(raw), self.preparsed, buf, len(report))
        if status != SUCCESS:
            return None
        return raw.value

    def _io(self, function, buffer, deadline):
        overlapped = Overlapped()
        overlapped.event = kernel.CreateEventW(None, True, False, None)
        if not overlapped.event:
            raise c.WinError(c.get_last_error())
        count = U32()
        try:
            if not function(self.io_handle, buffer, len(buffer), c.byref(count), c.byref(overlapped)):
                if c.get_last_error() != 997:  # ERROR_IO_PENDING
                    raise c.WinError(c.get_last_error())
                milliseconds = max(0, int((deadline - time.monotonic()) * 1000))
                wait = kernel.WaitForSingleObject(overlapped.event, milliseconds)
                if wait != 0:
                    kernel.CancelIoEx(self.io_handle, c.byref(overlapped))
                    # Keep the buffer/OVERLAPPED alive until cancellation completes.
                    # A broken cancellation is still bounded by the parent process.
                    kernel.GetOverlappedResult(self.io_handle, c.byref(overlapped), c.byref(count), True)
                    raise TimeoutError("HID request timed out")
                if not kernel.GetOverlappedResult(self.io_handle, c.byref(overlapped), c.byref(count), False):
                    raise c.WinError(c.get_last_error())
            return count.value
        finally:
            kernel.CloseHandle(overlapped.event)

    def exchange(self, request, matches, timeout=0.2):
        """Used ONLY after a vendor adapter has matched this collection."""
        if not self.io_handle:
            handle = kernel.CreateFileW(self.path, 0xC0000000, 3, None, 3, 0x40000000, None)
            if handle in (None, c.c_void_p(-1).value):
                raise c.WinError(c.get_last_error())
            self.io_handle = handle
        if len(request) > self.caps.output_length or not self.caps.input_length:
            raise ValueError("Vendor report incompatible with descriptor")
        deadline = time.monotonic() + timeout
        output = (U8 * self.caps.output_length).from_buffer_copy(
            request.ljust(self.caps.output_length, b"\x00"))
        if self._io(kernel.WriteFile, output, deadline) != len(output):
            raise OSError("Short HID write")
        while time.monotonic() < deadline:
            buffer = (U8 * self.caps.input_length)()
            length = self._io(kernel.ReadFile, buffer, deadline)
            response = bytes(buffer[:length])
            if matches(response):
                return response
        raise TimeoutError("No matching HID response")
