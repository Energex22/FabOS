@echo off
cd /d "%~dp0\..\.."
python -m pip install "pyinstaller==5.13.2"
python -m PyInstaller --noconfirm --windowed --name "WireVault FabOS" fabos_desktop\main.py
pause
