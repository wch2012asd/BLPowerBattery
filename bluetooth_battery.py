# -*- coding: utf-8 -*-
"""
蓝牙设备电量桌面显示
- 无边框、背景透明、置顶桌面小部件
- 右键菜单：窗口大小 / 背景透明度 / 字体透明度 / 字体颜色 / 刷新间隔 / 低电量阈值 / 刷新 / 退出
- 低电量托盘提醒
- 通过 Windows PnP 设备属性 DEVPKEY_Device_BatteryLevel 读取蓝牙设备电量
"""

import os
import sys
import json
import subprocess
import threading
import ctypes
import winreg
from ctypes import wintypes
from pathlib import Path


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


# ------------------------------------------------------------------ 开机启动
AUTORUN_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTORUN_VALUE_NAME = "BLPowerBattery"


def _is_frozen():
    return getattr(sys, "frozen", False)


def _autostart_command():
    """开机启动时执行的命令"""
    if _is_frozen():
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'


def is_autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTORUN_REG_KEY,
                            0, winreg.KEY_QUERY_VALUE) as k:
            winreg.QueryValueEx(k, AUTORUN_VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_autostart(enabled):
    """写入/删除注册表 HKCU\\...\\Run 实现开机启动"""
    try:
        if enabled:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTORUN_REG_KEY,
                                0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, AUTORUN_VALUE_NAME, 0, winreg.REG_SZ,
                                  _autostart_command())
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTORUN_REG_KEY,
                                    0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, AUTORUN_VALUE_NAME)
            except FileNotFoundError:
                pass
        return True
    except OSError:
        return False

from PySide6.QtCore import Qt, QTimer, Signal, QPoint, QRect
from PySide6.QtGui import (
    QColor, QPainter, QFont, QAction, QIcon, QPixmap, QGuiApplication,
    QFontDatabase, QContextMenuEvent, QMouseEvent,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
    QMenu, QSystemTrayIcon, QSlider, QWidgetAction, QColorDialog,
    QGraphicsDropShadowEffect, QSizePolicy, QSpacerItem,
)

# ------------------------------------------------------------------ 配置
CONFIG_PATH = Path.home() / ".blpower_config.json"

# DEVPKEY_Device_BatteryLevel = {104EA319-6EE2-4701-BD47-8DDBF425BBE5}, 2
BATTERY_PROP_KEY = "{104EA319-6ee2-4701-bd47-8ddbf425bbe5},2"

DEFAULT_CONFIG = {
    "config_version": 2,        # 配置版本，用于自动迁移
    "bg_opacity": 92,           # 背景透明度(不透明度) 0~100
    "font_opacity": 100,        # 字体透明度(不透明度) 0~100
    "font_color": "#FFFFFF",    # 字体颜色
    "size_preset": "medium",    # small / medium / large
    "threshold": 20,            # 低电量阈值 %
    "refresh_interval": 600,    # 刷新间隔 秒，默认 10 分钟
    "always_on_top": True,      # 置顶
    "tray_visible": True,       # 显示托盘图标
    "pos_x": None,              # 记忆位置
    "pos_y": None,
}

SIZE_PRESETS = {
    "small": 230,
    "medium": 290,
    "large": 360,
}

# 电量颜色分级
def battery_color(level: int) -> str:
    if level >= 50:
        return "#3ee07a"   # 绿
    if level >= 20:
        return "#ffce4d"   # 黄
    return "#ff5b5b"       # 红


def _hex_to_rgb(h):
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgba_a(hex_color, alpha_0_255):
    """将十六进制颜色 + alpha(0~255) 转为 stylesheet 可用的 rgba()"""
    r, g, b = _hex_to_rgb(hex_color)
    a = max(0, min(255, int(round(alpha_0_255))))
    return f"rgba({r},{g},{b},{a})"


def _pct_to_alpha(pct):
    """不透明度百分比(0~100) -> alpha(0~255)"""
    return max(0.0, min(100.0, float(pct))) / 100.0 * 255.0


def device_icon(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ["耳", "headphone", "earbud", "buds", "airpods", "buds"]):
        return "🎧"
    if any(k in n for k in ["mouse", "鼠标"]):
        return "🖱️"
    if any(k in n for k in ["keyboard", "键盘", "key"]):
        return "⌨️"
    if any(k in n for k in ["pen", "stylus", "笔", "pencil"]):
        return "✏️"
    if any(k in n for k in ["speaker", "音箱", "sound"]):
        return "🔊"
    if any(k in n for k in ["watch", "手表", "band", "手环"]):
        return "⌚"
    if any(k in n for k in ["phone", "手机"]):
        return "📱"
    return "🔋"


# ------------------------------------------------------------------ 电量查询 (SetupAPI 直调)
_setupapi = ctypes.windll.setupapi

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


def query_bluetooth_devices():
    """直接通过 Windows SetupAPI 读取蓝牙设备电量，无需启动 PowerShell，速度快数十倍"""
    result = []
    hDevInfo = _setupapi.SetupDiGetClassDevsW(
        None, None, None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if not hDevInfo:
        return result

    try:
        idx = 0
        while True:
            di = _SP_DEVINFO_DATA()
            di.cbSize = ctypes.sizeof(_SP_DEVINFO_DATA)
            if not _setupapi.SetupDiEnumDeviceInfo(hDevInfo, idx, ctypes.byref(di)):
                break
            idx += 1

            # 获取 InstanceId
            iid_buf = ctypes.create_unicode_buffer(200)
            iid_sz = wintypes.DWORD(0)
            if not _setupapi.SetupDiGetDeviceInstanceIdW(
                hDevInfo, ctypes.byref(di), iid_buf, 200, ctypes.byref(iid_sz)):
                continue
            instance_id = iid_buf.value
            if "BTH" not in instance_id.upper():
                continue

            # 查询电量属性
            ptype = wintypes.ULONG(0)
            bval = wintypes.UINT(0)
            rsz = wintypes.DWORD(0)
            if not _setupapi.SetupDiGetDevicePropertyW(
                hDevInfo, ctypes.byref(di), ctypes.byref(_BATTERY_PROPKEY),
                ctypes.byref(ptype), ctypes.byref(bval),
                ctypes.sizeof(wintypes.UINT), ctypes.byref(rsz), 0):
                continue
            if ptype.value not in (DEVPROP_TYPE_BYTE, DEVPROP_TYPE_UINT32):
                continue
            level = bval.value
            if level < 0 or level > 100:
                continue

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
                           "instance_id": instance_id})
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(hDevInfo)

    # 按名称去重，保留电量较高的一条
    dedup = {}
    for item in result:
        key = item["name"].lower()
        if key not in dedup or item["battery"] > dedup[key]["battery"]:
            dedup[key] = item
    return list(dedup.values())


# ------------------------------------------------------------------ 设备卡片
class DeviceCard(QFrame):
    def __init__(self, name, battery, font_color, font_opacity, bg_opacity, parent=None):
        super().__init__(parent)
        self._name = name
        self._battery = battery
        self._font_color = font_color
        self._font_opacity = font_opacity
        self._bg_opacity = bg_opacity
        self.setObjectName("deviceCard")
        self._refresh_style()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)

        self.icon_lbl = QLabel(device_icon(name))
        self.icon_lbl.setObjectName("icon")
        self.name_lbl = QLabel(name)
        self.name_lbl.setObjectName("name")
        self.name_lbl.setToolTip(name)
        # 过长名称省略
        fm = self.name_lbl.fontMetrics()
        if fm.horizontalAdvance(name) > 150:
            self.name_lbl.setText(fm.elidedText(name, Qt.ElideRight, 150))

        self.pct_lbl = QLabel(f"{battery}%")
        self.pct_lbl.setObjectName("pct")
        self.pct_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.bar = QFrame(self)
        self.bar.setObjectName("bar")
        self.bar.setFixedHeight(7)
        self.fill = QFrame(self.bar)
        self.fill.setObjectName("fill")
        self.fill.move(0, 0)
        self.fill.setFixedHeight(7)

        # 左图标
        lay.addWidget(self.icon_lbl)
        # 中间：名称+进度条
        mid = QVBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(3)
        mid.addWidget(self.name_lbl)
        mid.addWidget(self.bar)
        lay.addLayout(mid, 1)
        # 右百分比
        lay.addWidget(self.pct_lbl)

        self._update_bar()

    def _refresh_style(self):
        col = battery_color(self._battery)
        fa = _pct_to_alpha(self._font_opacity)
        ba = _pct_to_alpha(self._bg_opacity)
        font_c = _rgba_a(self._font_color, fa)
        pct_c = _rgba_a(col, fa)
        fill_c = _rgba_a(col, fa)
        dev_bg = _rgba_a("#FFFFFF", ba * (18.0 / 255.0))
        track_c = _rgba_a("#FFFFFF", ba * (40.0 / 255.0))
        self.setStyleSheet(f"""
            #deviceCard {{
                background-color: {dev_bg};
                border-radius: 10px;
            }}
            #icon {{ color: {font_c}; font-size: 16px; }}
            #name {{ color: {font_c}; font-size: 13px; }}
            #pct  {{ color: {pct_c}; font-size: 14px; font-weight: 600; }}
            #bar  {{ background-color: {track_c}; border-radius: 3px; }}
            #fill {{ background-color: {fill_c}; border-radius: 3px; }}
        """)

    def update_style(self, font_color, font_opacity, bg_opacity):
        """实时更新透明度/颜色，不重建部件（避免拖动滑块时的残影与堆叠）"""
        self._font_color = font_color
        self._font_opacity = font_opacity
        self._bg_opacity = bg_opacity
        self._refresh_style()

    def _update_bar(self):
        self.bar.updateGeometry()
        # 等 layout 算出宽度后设置 fill 宽度
        QTimer.singleShot(0, self._resize_fill)

    def _resize_fill(self):
        w = self.bar.width()
        fw = max(2, int(w * (self._battery / 100.0)))
        self.fill.setFixedWidth(fw)
        self.fill.setFixedHeight(7)
        self.fill.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._resize_fill()


# ------------------------------------------------------------------ 主窗口
class BatteryWidget(QWidget):
    devices_updated = Signal(list)

    SIZE_LABELS = {"small": "小", "medium": "中", "large": "大"}

    def __init__(self):
        super().__init__()
        self.config = self._load_config()
        self._devices = []
        self._notified = {}      # instance_id -> last notified battery
        self._refreshing = False
        self._drag_pos = None
        self._user_hidden = False    # 用户主动隐藏标志，区分 Win+D 系统隐藏

        self._init_window()
        self._init_ui()
        self._init_tray()
        self._restore_position()

        self.devices_updated.connect(self._on_devices_updated)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self._apply_refresh_interval()
        self.refresh()

        # Win+D 守护：定时检查窗口是否被系统隐藏，自动恢复
        self._guard_timer = QTimer(self)
        self._guard_timer.timeout.connect(self._guard_visibility)
        self._guard_timer.start(300)

    # ----- 配置
    def _load_config(self):
        cfg = dict(DEFAULT_CONFIG)
        try:
            if CONFIG_PATH.exists():
                cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
        # 版本迁移：v1 -> v2
        ver = int(cfg.get("config_version", 1))
        if ver < 2:
            # 旧版整体 opacity 拆分为背景透明度
            if "opacity" in cfg and "bg_opacity" not in cfg:
                try:
                    cfg["bg_opacity"] = int(float(cfg["opacity"]) * 100)
                except (ValueError, TypeError):
                    pass
            cfg.pop("opacity", None)
            # 旧版默认刷新间隔 60s，升级为新默认 10 分钟
            if cfg.get("refresh_interval") == 60:
                cfg["refresh_interval"] = 600
            cfg["config_version"] = 2
        return cfg

    def _save_config(self):
        try:
            CONFIG_PATH.write_text(json.dumps(self.config, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        except Exception:
            pass

    # ----- 窗口
    def _init_window(self):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self.config.get("always_on_top", True):
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("蓝牙电量")
        self.setFixedWidth(SIZE_PRESETS.get(self.config.get("size_preset", "medium"), 290))
        self.setMinimumHeight(40)

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.card.setGraphicsEffect(shadow)

        self.vlay = QVBoxLayout(self.card)
        self.vlay.setContentsMargins(10, 10, 10, 10)
        self.vlay.setSpacing(6)

        # 设备列表容器
        self.list_lay = QVBoxLayout()
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(4)
        self.vlay.addLayout(self.list_lay)

        self._placeholder = QLabel("正在检测蓝牙设备…")
        self._placeholder.setObjectName("hint")
        self.list_lay.addWidget(self._placeholder)

        outer.addWidget(self.card)
        self._apply_style()
        self.adjustSize()

    def _apply_style(self):
        fc = self.config.get("font_color", "#FFFFFF")
        fo = int(self.config.get("font_opacity", 100))
        bo = int(self.config.get("bg_opacity", 92))
        ba = _pct_to_alpha(bo)
        fa = _pct_to_alpha(fo)
        card_bg = _rgba_a("#16181e", ba)
        border_c = _rgba_a("#FFFFFF", ba * (30.0 / 255.0))
        hint_c = _rgba_a(fc, fa * (140.0 / 255.0))
        self.card.setStyleSheet(f"""
            #card {{
                background-color: {card_bg};
                border-radius: 16px;
                border: 1px solid {border_c};
            }}
            #hint {{ color: {hint_c}; font-size: 10px; }}
            #placeholder {{ color: {hint_c}; font-size: 12px; }}
        """)

    # ----- 托盘
    def _make_icon(self):
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 235))
        p.drawRoundedRect(8, 18, 44, 28, 5, 5)
        p.drawRoundedRect(52, 26, 6, 12, 2, 2)
        p.setBrush(QColor("#3ee07a"))
        p.drawRoundedRect(14, 24, 30, 16, 3, 3)
        p.end()
        return QIcon(pm)

    def _init_tray(self):
        self.tray = QSystemTrayIcon(self._make_icon(), self)
        self.tray.setToolTip("蓝牙电量")
        self.tray.activated.connect(self._on_tray_activated)
        m = QMenu()
        a_show = QAction("显示/隐藏", self)
        a_show.triggered.connect(self._toggle_visible)
        a_refresh = QAction("立即刷新", self)
        a_refresh.triggered.connect(self.refresh)
        a_hide_tray = QAction("隐藏托盘图标", self)
        a_hide_tray.triggered.connect(lambda: self._set_tray_visible(False))
        a_exit = QAction("退出程序", self)
        a_exit.triggered.connect(self._quit)
        m.addAction(a_show)
        m.addAction(a_refresh)
        m.addAction(a_hide_tray)
        m.addSeparator()
        m.addAction(a_exit)
        self.tray.setContextMenu(m)
        self.tray.show()
        if not self.config.get("tray_visible", True):
            self.tray.hide()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_visible()

    def _toggle_visible(self):
        if self.isVisible():
            self._user_hidden = True
            self.hide()
        else:
            self._user_hidden = False
            self.show()
            self.raise_()

    # ----- 位置
    def _restore_position(self):
        x = self.config.get("pos_x")
        y = self.config.get("pos_y")
        if x is not None and y is not None:
            self.move(int(x), int(y))
        else:
            screen = QGuiApplication.primaryScreen().availableGeometry()
            self.move(screen.right() - self.width() - 20, screen.top() + 20)

    # ----- 刷新
    def _apply_refresh_interval(self):
        secs = int(self.config.get("refresh_interval", 60))
        self.timer.start(max(10, secs) * 1000)

    def refresh(self):
        if self._refreshing:
            return
        self._refreshing = True
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        devs = query_bluetooth_devices()
        self.devices_updated.emit(devs)

    def _on_devices_updated(self, devs):
        self._refreshing = False
        self._devices = devs
        self._rebuild_list()
        self._check_low_battery(devs)

    def _rebuild_list(self):
        # 清空旧卡片：先解除父子关系立即隐藏，再延迟删除，避免残影/堆叠
        while self.list_lay.count():
            it = self.list_lay.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        if not self._devices:
            ph = QLabel("未检测到带电量信息的蓝牙设备")
            ph.setObjectName("hint")
            ph.setAlignment(Qt.AlignCenter)
            self.list_lay.addWidget(ph)
        else:
            fc = self.config.get("font_color", "#FFFFFF")
            fo = int(self.config.get("font_opacity", 100))
            bo = int(self.config.get("bg_opacity", 92))
            for d in self._devices:
                card = DeviceCard(d["name"], d["battery"], fc, fo, bo, self)
                self.list_lay.addWidget(card)
        self._make_pass_through()
        self.adjustSize()

    def _update_cards_style(self):
        """仅更新现有卡片的透明度/颜色，不重建（用于滑块实时调节）"""
        fc = self.config.get("font_color", "#FFFFFF")
        fo = int(self.config.get("font_opacity", 100))
        bo = int(self.config.get("bg_opacity", 92))
        for c in self.findChildren(DeviceCard):
            c.update_style(fc, fo, bo)

    def _make_pass_through(self):
        # 让子部件对鼠标透明，整窗可拖动/右键
        for c in self.findChildren(QWidget):
            c.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    # ----- 低电量提醒
    def _check_low_battery(self, devs):
        thr = int(self.config.get("threshold", 20))
        for d in devs:
            iid = d.get("instance_id") or d.get("name")
            batt = d["battery"]
            prev = self._notified.get(iid)
            if batt < thr:
                # 新低电量 或 比上次再降 10% 才提醒，避免刷屏
                if prev is None or (prev - batt) >= 10:
                    self.tray.showMessage(
                        "低电量提醒",
                        f"{d['name']} 电量仅剩 {batt}%，请及时充电。",
                        QSystemTrayIcon.Warning, 6000,
                    )
                    self._notified[iid] = batt
            else:
                # 回到安全区，重置以便下次再次提醒
                if batt >= thr + 5 and iid in self._notified:
                    self._notified.pop(iid, None)

    # ----- 鼠标拖动
    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e: QMouseEvent):
        if self._drag_pos is not None and (e.buttons() & Qt.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e: QMouseEvent):
        if self._drag_pos is not None:
            self._drag_pos = None
            self.config["pos_x"] = self.x()
            self.config["pos_y"] = self.y()
            self._save_config()
            e.accept()

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self.refresh()
            e.accept()

    # ----- 右键菜单
    def contextMenuEvent(self, e: QContextMenuEvent):
        m = QMenu(self)
        m.setStyleSheet("""
            QMenu { background:#22252c; color:#fff; border:1px solid #3a3f4b; }
            QMenu::item { padding:6px 22px; }
            QMenu::item:selected { background:#3a8bff; }
            QMenu::separator { height:1px; background:#3a3f4b; margin:4px 8px; }
        """)

        # 窗口大小
        size_menu = m.addMenu("窗口大小")
        cur = self.config.get("size_preset", "medium")
        for key, label in self.SIZE_LABELS.items():
            act = QAction(label, size_menu, checkable=True)
            act.setChecked(key == cur)
            act.triggered.connect(lambda _=False, k=key: self._set_size(k))
            size_menu.addAction(act)

        # 背景透明度（滑块）
        bg_wa = self._slider_action("背景透明度", 0, 100,
                                    100 - int(self.config.get("bg_opacity", 92)),
                                    self._set_bg_transparency)
        m.addAction(bg_wa)

        # 字体透明度（滑块）
        ft_wa = self._slider_action("字体透明度", 0, 100,
                                    100 - int(self.config.get("font_opacity", 100)),
                                    self._set_font_transparency)
        m.addAction(ft_wa)

        # 字体颜色
        color_menu = m.addMenu("字体颜色")
        presets = [
            ("白色", "#FFFFFF"), ("黑色", "#101012"), ("绿色", "#3ee07a"),
            ("黄色", "#ffd84d"), ("青色", "#4fd6ff"), ("粉色", "#ff7eb6"),
            ("橙色", "#ff9f43"),
        ]
        for label, c in presets:
            act = QAction(label, color_menu, checkable=True)
            act.setChecked(self.config.get("font_color", "").upper() == c.upper())
            act.triggered.connect(lambda _=False, col=c: self._set_font_color(col))
            color_menu.addAction(act)
        color_menu.addSeparator()
        cust = QAction("自定义…", color_menu)
        cust.triggered.connect(self._pick_font_color)
        color_menu.addAction(cust)

        # 刷新间隔
        interval_menu = m.addMenu("刷新间隔")
        cur_int = int(self.config.get("refresh_interval", 60))
        for secs, label in [(15, "15 秒"), (30, "30 秒"), (60, "1 分钟"),
                            (120, "2 分钟"), (300, "5 分钟"), (600, "10 分钟")]:
            act = QAction(label, interval_menu, checkable=True)
            act.setChecked(secs == cur_int)
            act.triggered.connect(lambda _=False, s=secs: self._set_interval(s))
            interval_menu.addAction(act)

        # 低电量阈值（滑块）
        thr_wa = self._slider_action("低电量阈值", 5, 50,
                                     int(self.config.get("threshold", 20)),
                                     self._set_threshold)
        m.addAction(thr_wa)

        m.addSeparator()
        # 置顶
        a_top = QAction("窗口置顶", m, checkable=True)
        a_top.setChecked(self.config.get("always_on_top", True))
        a_top.triggered.connect(self._toggle_top)
        m.addAction(a_top)

        # 隐藏托盘图标（勾选=隐藏）
        a_tray = QAction("隐藏托盘图标", m, checkable=True)
        a_tray.setChecked(not self.config.get("tray_visible", True))
        a_tray.triggered.connect(lambda checked: self._set_tray_visible(not checked))
        m.addAction(a_tray)

        # 开机启动（勾选=开机自启）
        a_auto = QAction("开机启动", m, checkable=True)
        a_auto.setChecked(is_autostart_enabled())
        a_auto.triggered.connect(lambda checked: set_autostart(checked))
        m.addAction(a_auto)

        a_refresh = QAction("立即刷新", m)
        a_refresh.triggered.connect(self.refresh)
        m.addAction(a_refresh)

        if self.config.get("tray_visible", True):
            a_hide = QAction("隐藏到托盘", m)
            a_hide.triggered.connect(self.hide)
            m.addAction(a_hide)

        m.addSeparator()
        a_exit = QAction("退出程序", m)
        a_exit.triggered.connect(self._quit)
        m.addAction(a_exit)

        m.exec(e.globalPos())

    def _slider_action(self, title, vmin, vmax, val, callback):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(4)
        lbl = QLabel(f"{title}：{val}")
        lbl.setStyleSheet("color:#fff;")
        sld = QSlider(Qt.Horizontal)
        sld.setRange(vmin, vmax)
        sld.setValue(val)
        sld.setStyleSheet(
            "QSlider::groove:horizontal{height:4px;background:#3a3f4b;border-radius:2px;}"
            "QSlider::handle:horizontal{width:14px;margin:-5px 0;border-radius:7px;background:#3a8bff;}"
        )

        def on_change(v):
            lbl.setText(f"{title}：{v}")
            callback(v)

        sld.valueChanged.connect(on_change)
        lay.addWidget(lbl)
        lay.addWidget(sld)
        wa = QWidgetAction(self)
        wa.setDefaultWidget(w)
        return wa

    # ----- 设置回调
    def _set_size(self, key):
        self.config["size_preset"] = key
        self.setFixedWidth(SIZE_PRESETS.get(key, 290))
        self._save_config()
        self._rebuild_list()

    def _set_bg_transparency(self, transparency_val):
        # 透明度(0=不透明,100=全透明) -> 不透明度
        self.config["bg_opacity"] = 100 - int(transparency_val)
        self._save_config()
        self._apply_style()
        self._update_cards_style()

    def _set_font_transparency(self, transparency_val):
        self.config["font_opacity"] = 100 - int(transparency_val)
        self._save_config()
        self._apply_style()
        self._update_cards_style()

    def _set_font_color(self, col):
        self.config["font_color"] = col
        self._save_config()
        self._apply_style()
        self._update_cards_style()

    def _pick_font_color(self):
        dlg = QColorDialog(self)
        dlg.setCurrentColor(QColor(self.config.get("font_color", "#FFFFFF")))
        if dlg.exec():
            c = dlg.currentColor().name()
            self._set_font_color(c)

    def _set_interval(self, secs):
        self.config["refresh_interval"] = secs
        self._save_config()
        self._apply_refresh_interval()

    def _set_threshold(self, val):
        self.config["threshold"] = val
        self._save_config()
        self._notified.clear()  # 阈值改变后允许重新提醒

    def _toggle_top(self):
        self.config["always_on_top"] = not self.config.get("always_on_top", True)
        self._save_config()
        self._init_window_flags_only()

    def _set_tray_visible(self, visible):
        """显示/隐藏托盘图标。隐藏后窗口不可再隐藏到托盘，避免无法恢复。"""
        self.config["tray_visible"] = bool(visible)
        self._save_config()
        if visible:
            self.tray.show()
        else:
            self.tray.hide()

    def _init_window_flags_only(self):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self.config.get("always_on_top", True):
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.show()

    # ----- 退出
    def _quit(self):
        self.config["pos_x"] = self.x()
        self.config["pos_y"] = self.y()
        self._save_config()
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, e):
        if self.config.get("tray_visible", True):
            # 有托盘：关闭即最小化到托盘
            self._user_hidden = True
            e.ignore()
            self.hide()
        else:
            # 托盘已隐藏：直接退出，避免窗口隐藏后无法恢复
            self._quit()
            e.accept()

    # ----- Win+D 桌面切换保持显示
    def _guard_visibility(self):
        """定时检查：如果窗口被系统隐藏（Win+D）且用户未主动隐藏，则恢复显示"""
        if self._user_hidden:
            return
        if not self.isVisible() or self.isMinimized():
            self.showNormal()
            self.show()
            self.raise_()


# ------------------------------------------------------------------ 入口
SINGLE_INSTANCE_MUTEX = "BLPowerBattery_SingleInstance"


def _ensure_single_instance():
    """通过命名互斥量确保只运行一个实例。返回 (mutex_handle, ok)。ok=False 表示已有实例在运行。"""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
    handle = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX)
    # ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == 183:
        return None, False
    return handle, True


def main():
    # 单实例检测：已运行则提示并退出
    _mutex, ok = _ensure_single_instance()
    if not ok:
        ctypes.windll.user32.MessageBoxW(
            0, "蓝牙电量程序已在运行中。", "BLPowerBattery", 0x40)  # MB_ICONINFORMATION
        return

    # 高 DPI
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 关闭窗口仍驻留托盘

    # 尝试加载 emoji 字体回退
    QFontDatabase.addApplicationFont("Segoe UI Emoji")

    w = BatteryWidget()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
