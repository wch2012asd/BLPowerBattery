# 2.0.0 开发版设备兼容性与测试

当前为 2.0.0.dev2。下面的“已实现”指代码和合成协议样本测试通过，不能等同于已完成型号实机认证。

| 层级 | 已实现范围 | 实机状态 |
| --- | --- | --- |
| Windows 属性 | 当前存在的 BTH / USB / HID 设备电量属性 | 本机 AJ159 APEX 蓝牙读取成功 |
| 标准 HID | Generic Device Controls 0x06 / Battery Strength 0x20，Feature 与 Input 报告 | 接口枚举已验证；有电量报告的硬件待测试 |
| SteelSeries | VID 1038，PID 1260（Arctis 7）、12AD（Arctis 7 2019）；接口 5 的厂商集合 | 协议样本测试通过，实机待测试 |
| Logitech | VID 046D，PID C52B / C532 / C539；Usage Page FF00、Usage 2；HID++ 2.0 功能 1004 / 1000 | 协议样本测试通过，实机待测试 |

Logitech 每个配对槽位动态发现电量功能，最多读取 6 个槽位；暂显示“Logitech 无线设备 N”。接收器型号匹配不保证每个配对设备都支持这些功能。暂不支持 HID++ 1.0、Bolt、仅电压/粗略等级上报、其他接收器 PID。不会把未知电量伪造为 0%。

SteelSeries 暂不覆盖 Nova / 7+ / Pro。请求仅查询电量，不写入设备配置；目前协议未提供明确离线/充电标志，接收器可能返回缓存电量，关机和重新连接行为需重点实测。

标准 HID 依照系统解析的描述符确定报告长度、ID、逻辑范围和字段。Feature 失败后尝试 Input；仅读取首个可用电量字段，不解释厂商自定义字段或一个集合内的多电池语义。USB/HID 本身不能证明设备一定使用 2.4G。

## 运行诊断

在项目根目录执行：

```powershell
python scripts/diagnose.py --output battery-diagnostics.json
```

也可以双击 `scripts/diagnose.bat`。诊断无需安装 PySide6。输出包含设备 VID/PID、固件版本、HID usage、标准电量字段、匹配适配器、错误及读数。实例路径被替换为散列标识，不导出原始序列号或 HID 路径。

- `ok`：得到有效读数。
- `unsupported`：无标准电量字段，也没有匹配当前厂商适配器。
- `no-battery`：存在适配路径，但设备未返回有效百分比（例如休眠或只上报粗略等级）。
- `query-failed` / 错误文字：报告读取或访问失败。
- `timeout`：单接口工作进程超时，已终止回收。
- `scan-budget-exhausted`：本轮时间用尽，该接口未执行；再次刷新重试。

单接口最多 3 秒，总 HID 扫描预算 20 秒，并发 4 个工作进程；枚举单独限时 4 秒。Windows 属性结果先显示，随后补充 HID 结果。未知设备只检查标准描述符，不发送厂商查询。与官方软件同时运行时可能遇到独占占用，应分别测试开启和关闭官方软件的情况。

## 实机测试记录建议

每个型号记录设备名、接收器 VID/PID、固件、Windows 版本、官方软件显示值与本程序显示值，并附诊断 JSON。依次检查：正常连接、低电量、充电、休眠唤醒、关机、接收器拔插、同接收器多设备、官方软件同时运行。报告错误电量时注明是否曾长时间断连。

## 协议依据

实现根据协议常量与字段布局独立编写，没有引入外部项目源码或依赖。

- [Microsoft HID API](https://learn.microsoft.com/en-us/windows-hardware/drivers/hid/hid-api)
- [HidD_GetFeature](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/hidsdi/nf-hidsdi-hidd_getfeature)
- [HeadsetControl Arctis 7 定义](https://github.com/Sapd/HeadsetControl/blob/master/lib/devices/steelseries_arctis_7.hpp)
- [HeadsetControl SteelSeries 传输协议](https://github.com/Sapd/HeadsetControl/blob/master/lib/devices/protocols/steelseries_protocol.hpp)
- [Solaar HID++ 功能发现和电量字段](https://github.com/pwr-Solaar/Solaar/blob/master/lib/logitech_receiver/hidpp20.py)

后续适配新型号应先确认协议、接口和响应字段，再加入白名单与协议测试；不能只添加一个 VID/PID 就宣称兼容。
