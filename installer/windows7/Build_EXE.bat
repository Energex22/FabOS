@echo off
setlocal
cd /d "%~dp0\..\.."

echo ============================================
echo FabOS Windows executable build
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python was not found on PATH.
  echo Install/use Python 3.11 and run this script again.
  exit /b 1
)

python -c "import sys; print('Python:', sys.version); raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)"
if errorlevel 1 (
  echo ERROR: This build must use Python 3.11.x.
  echo The packaged application requires the Python 3.11 runtime.
  exit /b 1
)

echo.
echo Installing the pinned PyInstaller version...
python -m pip install "pyinstaller==5.13.2"
if errorlevel 1 exit /b 1

echo.
echo Removing stale PyInstaller output...
if exist "build" rmdir /s /q "build"
if exist "dist\WireVault FabOS" rmdir /s /q "dist\WireVault FabOS"

echo.
echo Building a self-contained onedir application...
python -m PyInstaller --noconfirm --clean --onedir --windowed --name "WireVault FabOS" fabos_desktop\main.py
if errorlevel 1 (
  echo ERROR: PyInstaller failed.
  exit /b 1
)

set "APP_DIR=%CD%\dist\WireVault FabOS"
set "APP_EXE=%APP_DIR%\WireVault FabOS.exe"

echo.
echo Verifying packaged Python runtime...
if not exist "%APP_DIR%\python311.dll" (
  echo ERROR: python311.dll is missing from the final application directory:
  echo   %APP_DIR%
  echo This indicates an incomplete or incorrect PyInstaller package.
  exit /b 1
)

if not exist "%APP_EXE%" (
  echo ERROR: The built executable is missing:
  echo   %APP_EXE%
  exit /b 1
)

echo.
echo BUILD OK
echo Final application:
echo   %APP_DIR%
echo Executable:
echo   %APP_EXE%
echo.
echo IMPORTANT: Launch the EXE from dist\WireVault FabOS.
echo Do not launch the analysis files under build\.
echo.
pause
endlocal
