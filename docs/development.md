# 开发与发布

当前正式版本为 `1.0.0`。应用版本号维护在 `src/blpower/version.py`，Windows EXE 文件信息同步维护在 `scripts/windows_version_info.txt`。

## 环境要求

- Windows 10 或 Windows 11
- Python 3.10+

安装运行依赖：

```powershell
python -m pip install -r requirements.txt
```

运行依赖使用 `PySide6-Essentials`，包含本程序所需的 QtCore、QtGui、QtWidgets。

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

构建脚本优先使用项目 `.venv`，并支持额外的 PyInstaller 参数。旧版正在运行时，可输出到独立目录：

```powershell
scripts/build.bat --distpath dist/2.0.0.dev2
```

`build.bat` 会在调用 PyInstaller 前净化 `PATH`，避免其他开发工具附带的 VC 或 Qt DLL 混入发布包。正式版本应通过该脚本或等价的干净环境构建。
