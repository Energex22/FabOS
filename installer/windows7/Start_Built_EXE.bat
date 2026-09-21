@echo off
setlocal
cd /d "%~dp0\..\.."

set "APP_EXE=%CD%\dist\WireVault FabOS\WireVault FabOS.exe"
if not exist "%APP_EXE%" (
  echo ERROR: Built executable was not found.
  echo Run installer\windows7\Build_EXE.bat first.
  exit /b 1
)

echo Starting:
echo   %APP_EXE%
start "" "%APP_EXE%"
if errorlevel 1 (
  echo ERROR: Windows could not start the packaged application.
  echo.
  echo The packaged application must be launched from dist\WireVault FabOS.
  echo If Windows reports a missing python311.dll, rebuild with Build_EXE.bat.
  exit /b 1
)

endlocal
exit /b 0
