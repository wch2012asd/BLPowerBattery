@echo off
setlocal
cd /d "%~dp0.."

for %%I in (python.exe) do set "PYTHON_EXE=%%~$PATH:I"
if not defined PYTHON_EXE (
    echo Python was not found in PATH.
    exit /b 1
)

for %%I in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpI"
rem Keep unrelated development tools from injecting incompatible VC/Qt DLLs.
set "PATH=%PYTHON_DIR%;%PYTHON_DIR%Scripts;%SystemRoot%\System32;%SystemRoot%"

"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean blpower_battery.spec
