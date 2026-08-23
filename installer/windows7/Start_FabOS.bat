@echo off
cd /d "%~dp0\..\.."
python -m fabos_desktop.main
if errorlevel 1 pause
