# 架构说明

BLPowerBattery 是仅面向 Windows 的 PySide6 桌面小组件，目前保持单进程、单窗口结构。

## 运行流程

1. `blpower.app.main()` 创建 Qt 应用并进行单实例检查。
2. `BatteryWidget` 初始化窗口、托盘、配置和刷新定时器。
3. 后台线程通过 Windows SetupAPI 读取蓝牙设备电量。
4. SetupAPI 未返回结果时，程序使用 PowerShell 作为兼容回退。
5. 查询结果通过 Qt 信号回到 UI 线程并更新设备卡片。

## 模块职责

- `src/blpower/app.py`：应用入口、Windows API、电量查询和界面逻辑。
- `src/blpower/display.py`：颜色、透明度和设备图标等纯函数。
- `assets/`：应用图标及其预览图。
- `scripts/`：本地运行、打包和资源生成脚本。
- `tests/`：不依赖实际蓝牙设备的基础测试。

当前体量仍适合让主要流程集中在 `app.py`。未来如果继续增长，可继续拆分 `battery.py`、`window.py` 和 `config.py`，但应避免为了目录数量而提前复杂化。
