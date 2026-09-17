@echo off
setlocal
cd /d "%~dp0"

rem ---- 1. find python.exe on PATH ----
set "PYEXE="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYEXE set "PYEXE=%%P"
if not defined PYEXE goto nopython

rem ---- 2. find pythonw.exe next to it ----
for %%I in ("%PYEXE%") do set "PYDIR=%%~dpI"
set "PYWEXE=%PYDIR%pythonw.exe"
if not exist "%PYWEXE%" set "PYWEXE=%PYEXE%"

rem ---- 3. install PySide6 on first run ----
"%PYEXE%" -c "import PySide6" >nul 2>nul
if errorlevel 1 goto install
goto launch

:install
echo First run: installing PySide6, about 200 MB, please wait...
"%PYEXE%" -m pip install -r requirements.txt
if errorlevel 1 goto pipfail
goto launch

:launch
start "" "%PYWEXE%" main.py
goto end

:nopython
echo [ERROR] Python not found.
echo Please install Python 3.10 - 3.14 from https://www.python.org/downloads/
echo Tick "Add python.exe to PATH" during the installation, then double-click this file again.
pause
exit /b 1

:pipfail
echo [ERROR] Failed to install PySide6. Please check your network and try again.
pause
exit /b 1

:end
endlocal
exit /b 0
