# 开发与发布

当前正式版本为 `1.0.0`。应用版本号维护在 `src/blpower/version.py`，Windows EXE 文件信息同步维护在 `scripts/windows_version_info.txt`。

## 环境要求

- Windows 10 或 Windows 11
- Python 3.10+

安装运行依赖：

```powershell
python -m pip install -r requirements.txt
```

## 本地运行

PowerShell：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m blpower
```

也可以双击 `scripts/run.bat`。

## 测试

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests -v
```

## 生成资源

生成图标需要 Pillow：

```powershell
python -m pip install pillow
python scripts/generate_icon.py
```

## 打包

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm blpower_battery.spec
```

也可以双击 `scripts/build.bat`。生成文件位于 `dist/BLPowerBattery.exe`。

`build.bat` 会在调用 PyInstaller 前净化 `PATH`，避免其他开发工具附带的 VC 或 Qt DLL 混入发布包。正式版本应通过该脚本或等价的干净环境构建。
