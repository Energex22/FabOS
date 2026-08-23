@echo off
cd /d "%~dp0\..\.."
python -m pip install "Pillow==9.5.0"
echo.
echo Pillow image support installed. Restart FabOS.
pause
