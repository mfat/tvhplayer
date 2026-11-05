@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Missing development virtual environment.
  exit /b 1
)
if not exist "windows\build\libmpv-2.dll" (
  echo Missing playback library. See windows\backend\README.md.
  exit /b 1
)
set "TVHPLAYER_EXPERIMENTAL_WSLC=1"
set "PATH=%CD%\windows\build;%PATH%"
".venv\Scripts\python.exe" -m tvhplayer.tvhplayer
exit /b %errorlevel%
