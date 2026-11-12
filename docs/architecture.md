# 架构说明

BLPowerBattery 是仅面向 Windows 的 PySide6 桌面小组件，目前保持单进程、单窗口结构。

## 运行流程

1. `blpower.app.main()` 创建 Qt 应用并进行单实例检查。
2. `BatteryWidget` 初始化窗口、托盘、配置和刷新定时器。
3. 后台线程通过数据源聚合入口调用 Windows SetupAPI，读取蓝牙、USB、HID 设备电量。
4. SetupAPI 失败时使用 PowerShell 回退；正常空结果直接返回。
5. 查询结果通过 Qt 信号回到 UI 线程并更新设备卡片。

## 模块职责

- `src/blpower/app.py`：应用入口、窗口 API 和界面逻辑。
- `src/blpower/battery.py`：数据源聚合、值校验及实例 ID 去重。
- `src/blpower/windows_battery.py`：Windows 属性读取及 PowerShell 回退，不依赖 Qt。
- `src/blpower/hid_native.py`：Windows HID ABI、接口枚举、报告解析、限时重叠 I/O。
- `src/blpower/hid_battery.py`：标准电量报告读取与百分比校验。
- `src/blpower/vendor_battery.py`：白名单厂商适配器及协议解析。
- `src/blpower/hid_service.py` / `hid_worker.py`：并发工作进程、文件 IPC、超时回收；冻结 EXE 在 Qt 和单实例检查前分流。
- `scripts/diagnose.py`：导出不含原始设备路径的诊断报告。
- `src/blpower/display.py`：颜色、透明度和设备图标等纯函数。
- `assets/`：应用图标及其预览图。
- `scripts/`：本地运行、打包和资源生成脚本。
- `tests/`：不依赖实际蓝牙设备的基础测试。

Windows 查询结果通过预览信号先更新 UI，不提前释放刷新锁；HID 扫描完成后合并当前结果并结束刷新。相同实例优先使用 Windows 属性；不同实例不按名称或接收器容器粗暴合并。
