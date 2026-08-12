# 蓝牙电量桌面显示 · BLPowerBattery

一个 Windows 桌面小部件：透明、无边框、置顶，实时显示已连接蓝牙设备的电量。

![icon](app_preview.png)

## 功能特性

- **透明无边框置顶**：桌面常驻小部件，不占任务栏，背景透出桌面
- **自动读取电量**：通过 Windows PnP 设备属性读取，与系统「设置 → 蓝牙」同一数据源，无需连接设备、无需驱动
- **右键菜单全功能设置**：
  - 窗口大小（小 / 中 / 大）
  - 背景透明度、字体透明度（分别可调）
  - 字体颜色（预设 + 自定义取色）
  - 刷新间隔（15 秒 ~ 10 分钟，默认 10 分钟）
  - 低电量阈值
  - 开机启动、隐藏托盘图标、窗口置顶
- **低电量托盘提醒**：低于阈值自动弹窗提醒
- **单实例运行**：重复启动不会开第二个窗口
- **可打包为单文件 exe**

## 电量读取原理

通过 Windows 设备属性 `DEVPKEY_Device_BatteryLevel`
（`{104EA319-6EE2-4701-BD47-8DDBF425BBE5},2`）读取，使用 PowerShell
`Get-PnpDevice` + `Get-PnpDeviceProperty` 获取所有InstanceId含 `BTH` 的设备电量。

> 能否读取取决于设备是否向 Windows 上报电量属性，绝大多数现代蓝牙鼠标 / 键盘 / 耳机 / 手环都支持。

## 使用方法

### 方式一：运行打包好的 exe

双击 `BLPowerBattery.exe`（见 [Releases](../../releases)），无需安装 Python。

### 方式二：从源码运行

```bash
pip install -r requirements.txt
python bluetooth_battery.py
```

## 打包为 exe

```bash
pip install pyinstaller pillow
# 生成图标（可选，仓库已附带 app.ico）
python gen_icon.py
# 打包
pyinstaller --noconsole --onefile --icon app.ico --name BLPowerBattery bluetooth_battery.py
# 或使用附带的 spec
pyinstaller BLPowerBattery.spec
```

生成的 exe 位于 `dist/BLPowerBattery.exe`。

## 操作说明

| 操作 | 功能 |
|------|------|
| 左键拖动 | 移动窗口（位置自动记忆） |
| 双击 | 立即刷新电量 |
| 右键 | 打开设置菜单 |
| 托盘图标单击 | 显示 / 隐藏 |
| 关闭窗口 | 最小化到托盘（托盘隐藏时为退出） |

## 项目结构

```
blpower/
├── bluetooth_battery.py   # 主程序源码
├── requirements.txt       # Python 依赖
├── app.ico                # 应用图标
├── app_preview.png        # 图标预览
├── BLPowerBattery.spec    # PyInstaller 打包配置
├── 启动.bat                # 双击运行（pythonw 无控制台）
├── gen_icon.py            # 图标生成脚本
├── README.md
└── LICENSE
```

## 依赖

- Python 3.10+
- PySide6（GUI 框架）
- 打包可选：PyInstaller、Pillow（生成图标）

## License

MIT
