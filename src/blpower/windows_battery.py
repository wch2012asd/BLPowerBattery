"""Windows device-property battery provider; independent of Qt."""
import ctypes
from ctypes import wintypes
import json
import logging
import os
import re
import subprocess
import time
import traceback

try:
    from blpower.battery import is_candidate, merge_readings
except ModuleNotFoundError:
    from battery import is_candidate, merge_readings

_log = logging.getLogger(__name__).debug
BATTERY_PROP_KEY = "{104EA319-6ee2-4701-bd47-8ddbf425bbe5},2"

def _powershell_exe():
    """可靠地定位 PowerShell：优先 pwsh(7)，回退 Windows PowerShell 5.1 的完整路径"""
    for cand in ("pwsh", "powershell"):
        # 让系统在 PATH 中查找
        from shutil import which
        found = which(cand)
        if found:
            return found
    root = os.environ.get("SystemRoot", r"C:\Windows")
    fallback = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if os.path.isfile(fallback):
        return fallback
    return "powershell"

# ------------------------------------------------------------------ 电量查询 (SetupAPI 直调)
_setupapi = ctypes.WinDLL("setupapi", use_last_error=True)

DIGCF_PRESENT = 0x00000002
DIGCF_ALLCLASSES = 0x00000004
SPDRP_FRIENDLYNAME = 0x0000000C
SPDRP_DEVICEDESC = 0x00000000
DEVPROP_TYPE_BYTE = 0x00000003
DEVPROP_TYPE_UINT32 = 0x00000007


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _DEVPROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.ULONG)]


class _SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("ClassGuid", _GUID),
        ("DevInst", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


# DEVPKEY_Device_BatteryLevel = {104EA319-6EE2-4701-BD47-8DDBF425BBE5}, 2
_BATTERY_PROPKEY = _DEVPROPKEY()
_BATTERY_PROPKEY.fmtid.Data1 = 0x104EA319
_BATTERY_PROPKEY.fmtid.Data2 = 0x6EE2
_BATTERY_PROPKEY.fmtid.Data3 = 0x4701
_BATTERY_PROPKEY.fmtid.Data4 = (wintypes.BYTE * 8)(
    0xBD, 0x47, 0x8D, 0xDB, 0xF4, 0x25, 0xBB, 0xE5)
_BATTERY_PROPKEY.pid = 2

_setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
_setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
_setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
_setupapi.SetupDiEnumDeviceInfo.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(_SP_DEVINFO_DATA)]
_setupapi.SetupDiGetDevicePropertyW.restype = wintypes.BOOL
_setupapi.SetupDiGetDevicePropertyW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(_SP_DEVINFO_DATA),
    ctypes.POINTER(_DEVPROPKEY), ctypes.POINTER(wintypes.ULONG),
    wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
_setupapi.SetupDiGetDeviceInstanceIdW.restype = wintypes.BOOL
_setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(_SP_DEVINFO_DATA),
    wintypes.LPWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
_setupapi.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL
_setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(_SP_DEVINFO_DATA),
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    wintypes.LPBYTE, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
_setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

# ------------------------------------------------------------------ 连接状态
# cfg.h: DN_DEVICE_DISCONNECTED (0x02000000) 置位表示设备当前未连接
DN_DEVICE_DISCONNECTED = 0x02000000
_BTH_ROOT_RE = re.compile(
    r"^(?:BTHENUM|BTHLE)\\DEV_([0-9A-Fa-f]{12})\\", re.IGNORECASE)
_MAC_DEV_RE = re.compile(r"DEV_([0-9A-Fa-f]{12})")
_MAC_TAIL_RE = re.compile(r"&([0-9A-Fa-f]{12})(?:_|$)")

_cm = ctypes.WinDLL("cfgmgr32", use_last_error=True)
_cm.CM_Get_DevNode_Status.restype = ctypes.c_ulong  # CONFIGRET, 0 = CR_SUCCESS
_cm.CM_Get_DevNode_Status.argtypes = [
    ctypes.POINTER(wintypes.ULONG), ctypes.POINTER(wintypes.ULONG),
    wintypes.ULONG, wintypes.ULONG]


def _devnode_disconnected(devinst):
    """读取设备节点状态；查询失败按未断开处理，避免误隐藏。"""
    status = wintypes.ULONG(0)
    problem = wintypes.ULONG(0)
    if _cm.CM_Get_DevNode_Status(
            ctypes.byref(status), ctypes.byref(problem), devinst, 0) != 0:
        return False
    return bool(status.value & DN_DEVICE_DISCONNECTED)


def _extract_bt_mac(instance_id):
    """从蓝牙实例 ID 提取 12 位 MAC 以定位根设备节点；非蓝牙返回 None。"""
    if not instance_id:
        return None
    match = _MAC_DEV_RE.search(instance_id)
    if match:
        return match.group(1).lower()
    match = _MAC_TAIL_RE.search(instance_id.rsplit("\\", 1)[-1])
    if match:
        return match.group(1).lower()
    return None


def _scan_bth_root_flags():
    """枚举根设备节点，返回 {mac小写: 是否DN_DEVICE_DISCONNECTED}。"""
    flags = {}
    hDevInfo = _setupapi.SetupDiGetClassDevsW(
        None, None, None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if not hDevInfo or hDevInfo == ctypes.c_void_p(-1).value:
        raise OSError("SetupDiGetClassDevsW failed")
    try:
        idx = 0
        while True:
            di = _SP_DEVINFO_DATA()
            di.cbSize = ctypes.sizeof(_SP_DEVINFO_DATA)
            if not _setupapi.SetupDiEnumDeviceInfo(hDevInfo, idx, ctypes.byref(di)):
                if ctypes.get_last_error() == 259:  # ERROR_NO_MORE_ITEMS
                    break
                raise ctypes.WinError(ctypes.get_last_error())
            idx += 1
            iid_buf = ctypes.create_unicode_buffer(200)
            iid_sz = wintypes.DWORD(0)
            if not _setupapi.SetupDiGetDeviceInstanceIdW(
                    hDevInfo, ctypes.byref(di), iid_buf, 200, ctypes.byref(iid_sz)):
                continue
            match = _BTH_ROOT_RE.match(iid_buf.value)
            if match:
                flags[match.group(1).lower()] = _devnode_disconnected(di.DevInst)
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(hDevInfo)
    _log(f"蓝牙根节点连接状态: {len(flags)} 个, "
         f"已断开 {sum(1 for v in flags.values() if v)} 个")
    return flags


def _filter_disconnected(readings):
    """隐藏所属蓝牙设备已断开的读数（Windows 设置显示“未连接”的设备）。"""
    if not readings:
        return readings
    macs = {mac for mac in
            (_extract_bt_mac(reading.get("instance_id")) for reading in readings)
            if mac}
    if not macs:
        return readings
    try:
        flags = _scan_bth_root_flags()
    except Exception as exc:
        _log(f"连接状态扫描失败，跳过过滤: {exc}")
        return readings
    kept = []
    for reading in readings:
        mac = _extract_bt_mac(reading.get("instance_id"))
        if mac and flags.get(mac):
            _log(f"跳过未连接设备: {reading.get('name')} ({mac.upper()})")
            continue
        kept.append(reading)
    return kept


def _query_via_setupapi():
    """读取当前蓝牙、USB、HID 设备提供的 Windows 电量属性。"""
    result = []
    _log("_query_via_setupapi: 调用 SetupDiGetClassDevsW")
    hDevInfo = _setupapi.SetupDiGetClassDevsW(
        None, None, None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    _log(f"_query_via_setupapi: hDevInfo={hDevInfo}")
    if not hDevInfo or hDevInfo == ctypes.c_void_p(-1).value:
        raise OSError("SetupDiGetClassDevsW failed")

    try:
        idx = 0
        bth_count = 0
        while True:
            di = _SP_DEVINFO_DATA()
            di.cbSize = ctypes.sizeof(_SP_DEVINFO_DATA)
            if not _setupapi.SetupDiEnumDeviceInfo(hDevInfo, idx, ctypes.byref(di)):
                error = ctypes.get_last_error()
                if error == 259:  # ERROR_NO_MORE_ITEMS
                    break
                raise ctypes.WinError(error)
            idx += 1

            # 获取 InstanceId
            iid_buf = ctypes.create_unicode_buffer(200)
            iid_sz = wintypes.DWORD(0)
            if not _setupapi.SetupDiGetDeviceInstanceIdW(
                hDevInfo, ctypes.byref(di), iid_buf, 200, ctypes.byref(iid_sz)):
                continue
            instance_id = iid_buf.value
            if not is_candidate(instance_id):
                continue
            bth_count += 1
            _log(f"_query_via_setupapi: 候选设备 #{bth_count}: {instance_id[:50]}")

            # 查询电量属性
            ptype = wintypes.ULONG(0)
            bval = wintypes.UINT(0)
            rsz = wintypes.DWORD(0)
            if not _setupapi.SetupDiGetDevicePropertyW(
                hDevInfo, ctypes.byref(di), ctypes.byref(_BATTERY_PROPKEY),
                ctypes.byref(ptype), ctypes.byref(bval),
                ctypes.sizeof(wintypes.UINT), ctypes.byref(rsz), 0):
                _log(f"  -> 无电量属性")
                continue
            if ptype.value not in (DEVPROP_TYPE_BYTE, DEVPROP_TYPE_UINT32):
                _log(f"  -> 属性类型不匹配: {ptype.value}")
                continue
            if rsz.value != (1 if ptype.value == DEVPROP_TYPE_BYTE else 4):
                continue
            level = bval.value
            if level < 0 or level > 100:
                _log(f"  -> 电量值异常: {level}")
                continue
            _log(f"  -> 电量: {level}%")

            # 获取设备名称
            name_buf = ctypes.create_unicode_buffer(512)
            name_sz = wintypes.DWORD(0)
            name = instance_id
            for prop in (SPDRP_FRIENDLYNAME, SPDRP_DEVICEDESC):
                if _setupapi.SetupDiGetDeviceRegistryPropertyW(
                    hDevInfo, ctypes.byref(di), prop, None,
                    ctypes.cast(name_buf, wintypes.LPBYTE),
                    ctypes.sizeof(name_buf), ctypes.byref(name_sz)):
                    name = name_buf.value or instance_id
                    break

            result.append({"name": name, "battery": level,
                           "instance_id": instance_id, "source": "windows-property"})
        _log(f"_query_via_setupapi: 扫描 {idx} 个设备, {bth_count} 个 BTH, {len(result)} 个有电量")
    except Exception as e:
        _log(f"_query_via_setupapi: 异常 {e}\n{traceback.format_exc()}")
        raise
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(hDevInfo)

    return merge_readings(result)


def _query_via_powershell():
    """通过 PowerShell 读取蓝牙设备电量（回退方案，较慢但兼容性好）"""
    ps_script = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$result = @()
$bthDevices = Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match '^(BTH|USB\\|HID\\)' }
foreach ($d in $bthDevices) {
    $iid = $d.InstanceId
    $batt = Get-PnpDeviceProperty -InstanceId $iid -KeyName '%s' -ErrorAction SilentlyContinue
    if ($batt -and $null -ne $batt.Data -and $batt.Data -ge 0 -and $batt.Data -le 100) {
        $name = $d.FriendlyName
        if (-not $name) { $name = $iid }
        $result += [PSCustomObject]@{ Name=$name; Battery=[int]$batt.Data; InstanceId=$iid }
    }
}
if ($result.Count -eq 0) { '[]' } else { $result | ConvertTo-Json -Compress }
""" % BATTERY_PROP_KEY

    try:
        proc = subprocess.run(
            [_powershell_exe(), "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        text = (proc.stdout or "").strip()
        if not text or text.lower() == "null":
            return []
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        dedup = {}
        for item in data:
            try:
                name = str(item.get("Name", "未知设备")).strip()
                batt = int(item.get("Battery", -1))
            except (ValueError, TypeError):
                continue
            if not 0 <= batt <= 100:
                continue
            key = str(item.get("InstanceId", "")).casefold()
            if key not in dedup or batt > dedup[key]["battery"]:
                dedup[key] = {"name": name, "battery": batt,
                              "instance_id": str(item.get("InstanceId", ""))}
        return merge_readings(dedup.values())
    except Exception:
        return []


def query_windows_devices():
    """正常空结果直接返回，仅在 Windows API 失败时回退。"""
    try:
        t0 = time.time()
        devs = _query_via_setupapi()
        _log(f"Windows 电量扫描: {len(devs)} 个设备, {time.time()-t0:.3f}s")
        return _filter_disconnected(devs)
    except Exception as e:
        _log(f"query_bluetooth_devices: SetupAPI 异常: {e}\n{traceback.format_exc()}")
    try:
        t0 = time.time()
        devs = _query_via_powershell()
        _log(f"query_bluetooth_devices: PowerShell 完成, 耗时={time.time()-t0:.3f}s, 找到 {len(devs)} 个设备")
        return _filter_disconnected(devs)
    except Exception as e:
        _log(f"query_bluetooth_devices: PowerShell 异常: {e}\n{traceback.format_exc()}")
        return []
