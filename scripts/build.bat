@echo off
setlocal
cd /d "%~dp0.."

set "PYTHON_EXE="
if exist "%CD%\.venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
if not defined PYTHON_EXE for %%I in (python.exe) do set "PYTHON_EXE=%%~$PATH:I"
if not defined PYTHON_EXE (
    echo Python was not found in PATH.
    exit /b 1
)

for %%I in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpI"
rem Keep unrelated development tools from injecting incompatible VC/Qt DLLs.
set "PATH=%PYTHON_DIR%;%PYTHON_DIR%Scripts;%SystemRoot%\System32;%SystemRoot%"
set "PYTHONNOUSERSITE=1"
set "PYTHONUSERBASE=%CD%\.build-userbase"

"%PYTHON_EXE%" -m PyInstaller --noconfirm --clean blpower_battery.spec %*
