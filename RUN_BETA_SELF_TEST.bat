@echo off
cd /d "%~dp0"
echo Running WireVault FabOS Beta Readiness Self-Test...
python tools\beta_self_test.py
echo.
pause
