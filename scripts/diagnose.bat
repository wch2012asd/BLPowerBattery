@echo off
setlocal
cd /d "%~dp0.."
python scripts\diagnose.py --output battery-diagnostics.json
if errorlevel 1 echo Diagnostic failed. Please check Python and the message above.
pause
