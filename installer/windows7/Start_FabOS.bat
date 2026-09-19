@echo off
setlocal
cd /d "%~dp0\..\.."

echo Starting FabOS...
set "APP_EXE=%CD%\dist\WireVault FabOS\WireVault FabOS.exe"
if not exist "%APP_EXE%" (
  echo ERROR: Built FabOS executable was not found:
  echo   %APP_EXE%
  echo.
  echo Run installer\windows7\Build_EXE.bat first.
  pause
  exit /b 1
)

start "FabOS" "%APP_EXE%"
if errorlevel 1 (
  echo ERROR: Windows could not start FabOS.
  pause
  exit /b 1
)

endlocal
exit /b 0
