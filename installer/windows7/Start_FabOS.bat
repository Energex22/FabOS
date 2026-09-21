@echo off
setlocal
cd /d "%~dp0\..\.."

echo ============================================
echo Starting FabOS
echo ============================================
set "APP_EXE=%CD%\dist\WireVault FabOS\WireVault FabOS.exe"
if not exist "%APP_EXE%" (
  echo ERROR: Built FabOS executable was not found:
  echo   %APP_EXE%
  echo.
  echo Run installer\windows7\Build_EXE.bat first.
  echo.
  pause
  exit /b 1
)

echo Launching:
echo   %APP_EXE%
echo.
echo If FabOS closes immediately, this window will remain open.
echo.
start "" /wait "%APP_EXE%"
set "RC=%ERRORLEVEL%"

echo.
echo FabOS process ended with exit code %RC%.
echo.
if not "%RC%"=="0" echo The packaged application reported a non-zero exit code.
pause
endlocal & exit /b %RC%
