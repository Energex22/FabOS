@echo off
setlocal
cd /d "%~dp0"
call "%CD%\installer\windows7\Start_FabOS.bat"
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
