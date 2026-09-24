@echo off
setlocal EnableExtensions
cd /d "%~dp0"

:menu
cls
echo ============================================
echo              FABVEX FabOS
echo           Windows Control Panel
echo ============================================
echo.
echo  1. Start FabOS Desktop
echo  2. Start FabOS API Server
echo  3. Start Built EXE (debug window)
echo  4. Run Test Suite
echo  5. Run Beta Readiness Self-Test
echo  6. Install Image Support (Pillow)
echo  7. Exit
echo.
choice /C 1234567 /N /M "Select an option: "
if errorlevel 7 goto :done
if errorlevel 6 goto :image
if errorlevel 5 goto :selftest
if errorlevel 4 goto :tests
if errorlevel 3 goto :debug
if errorlevel 2 goto :server
if errorlevel 1 goto :desktop
goto :menu

:desktop
call :launch_desktop 0
pause
goto :menu

:debug
call :launch_desktop 1
pause
goto :menu

:launch_desktop
set "DEBUG_MODE=%~1"
set "APP_EXE=%CD%\dist\WireVault FabOS\WireVault FabOS.exe"
if "%DEBUG_MODE%"=="1" set "APP_EXE=%CD%\dist\WireVault FabOS Debug\WireVault FabOS Debug.exe"

if not exist "%APP_EXE%" (
    echo.
    echo ERROR: Built application was not found:
    echo   %APP_EXE%
    echo.
    echo Run installer\windows7\Build_EXE.bat first.
    echo.
    exit /b 1
)

echo.
echo Launching:
echo   %APP_EXE%
echo.
if "%DEBUG_MODE%"=="1" (
    echo Debug mode: this window will remain attached to the application.
    echo.
    start "" /wait "%APP_EXE%"
    set "RC=%ERRORLEVEL%"
    echo.
    echo FabOS debug process ended with exit code %RC%.
    exit /b %RC%
)

start "" "%APP_EXE%"
if errorlevel 1 (
    echo ERROR: Windows could not start FabOS.
    exit /b 1
)
echo FabOS started.
exit /b 0

:server
echo.
echo ============================================
echo           FabOS API Server
echo ============================================
echo.
echo This starts the FastAPI/Uvicorn server on the configured
echo FABOS_API_HOST/FABOS_API_PORT values (default: 127.0.0.1:8000).
echo Press Ctrl+C to stop the server.
echo.
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python was not found on PATH.
    pause
    goto :menu
)
python -m fabos_core.cli serve
echo.
echo FabOS API server stopped.
pause
goto :menu

:tests
echo.
echo ============================================
echo              FabOS Test Suite
echo ============================================
echo.
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python was not found on PATH.
    pause
    goto :menu
)
python -m unittest discover -s tests -v
echo.
echo Test suite finished with exit code %ERRORLEVEL%.
pause
goto :menu

:selftest
echo.
echo ============================================
echo       FabOS Beta Readiness Self-Test
echo ============================================
echo.
if /I "%FABOS_PYTHON%"=="python" where python >nul 2>nul
if /I "%FABOS_PYTHON%"=="python" if errorlevel 1 (
    echo ERROR: Python was not found on PATH.
    echo Install Python 3.11 and run this launcher again.
    pause
    goto :menu
)
"%FABOS_PYTHON%" tools\beta_self_test.py
echo.
echo Self-test finished with exit code %ERRORLEVEL%.
pause
goto :menu

:image
echo.
echo ============================================
echo          Install Image Support
echo ============================================
echo.
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python was not found on PATH.
    pause
    goto :menu
)
python -m pip install "Pillow==9.5.0"
echo.
if errorlevel 1 (
    echo ERROR: Pillow installation failed.
) else (
    echo Pillow image support installed successfully.
    echo Restart FabOS before testing image features.
)
pause
goto :menu

:done
echo.
echo FabOS launcher closed.
endlocal
exit /b 0
