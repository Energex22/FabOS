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
python -m PyInstaller --noconfirm --clean --onedir --windowed --name "WireVault FabOS" --add-data "fabos_core\db\schema.sql;fabos_core\db" --add-data "data;data" fabos_desktop\main.py
if errorlevel 1 (
  echo ERROR: PyInstaller failed.
  exit /b 1
)

echo.
echo Building a console-debug version for startup diagnostics...
if exist "dist\WireVault FabOS Debug" rmdir /s /q "dist\WireVault FabOS Debug"
python -m PyInstaller --noconfirm --clean --onedir --console --name "WireVault FabOS Debug" --add-data "fabos_core\db\schema.sql;fabos_core\db" --add-data "data;data" fabos_desktop\main.py
if errorlevel 1 (
  echo ERROR: PyInstaller debug build failed.
  exit /b 1
)

set "APP_DIR=%CD%\dist\WireVault FabOS"
set "APP_EXE=%APP_DIR%\WireVault FabOS.exe"
set "LEGACY_DIR=%CD%\build\wirevaultfabos"
set "LEGACY_EXE=%LEGACY_DIR%\wirevaultfabos.exe"

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
echo Creating a legacy-compatible EXE location...
if exist "%LEGACY_DIR%" rmdir /s /q "%LEGACY_DIR%"
mkdir "%LEGACY_DIR%"
xcopy "%APP_DIR%\*" "%LEGACY_DIR%\" /E /I /Y >nul
if errorlevel 1 (
  echo ERROR: Could not create the legacy-compatible package.
  exit /b 1
)
copy /Y "%APP_EXE%" "%LEGACY_EXE%" >nul
if errorlevel 1 (
  echo ERROR: Could not create the legacy EXE name.
  exit /b 1
)

if not exist "%LEGACY_DIR%\python311.dll" (
  echo ERROR: Legacy-compatible package is missing python311.dll:
  echo   %LEGACY_DIR%\python311.dll
  exit /b 1
)

if not exist "%LEGACY_EXE%" (
  echo ERROR: Legacy-compatible EXE is missing:
  echo   %LEGACY_EXE%
  exit /b 1
)

if not exist "%CD%\dist\WireVault FabOS Debug\WireVault FabOS Debug.exe" (
  echo ERROR: Debug executable is missing.
  exit /b 1
)

echo.
echo BUILD OK
echo Primary application:
echo   %APP_EXE%
echo Compatibility application:
echo   %LEGACY_EXE%
echo.
echo Both locations contain the complete packaged runtime.
echo.
endlocal
exit /b 0
