@echo off
rem codex-compat-reporter: double-click this to be guided, one question at a time, through writing
rem a report of how Codex Auto Resume behaved on this machine - and sending it only if you type send.
setlocal
rem Nothing is looked up in the current folder, where a downloaded python.exe could sit beside this
rem file: cmd is told not to look there, and every program below is named by its full path.
set "NoDefaultCurrentDirectoryInExePath=1"
"%SystemRoot%\System32\chcp.com" 65001 >nul
title codex-compat-reporter
set "EXIT_CODE=1"
set "SCRIPT=%~dp0codex_compat_report.py"
if not exist "%SCRIPT%" goto unzip

rem Which Python runs it: the first of these found. A PYTHON set outside this file is never used.
set "PYTHON="
set "PYTHON_FLAGS="
rem 1. The one Codex Auto Resume installs with itself: everyone with something to report has it.
if defined USERPROFILE if exist "%USERPROFILE%\.codex-auto-resume\runtime\python.exe" set "PYTHON=%USERPROFILE%\.codex-auto-resume\runtime\python.exe"
if defined PYTHON goto run
rem 2. The Python launcher, installed for everyone or for this user; -3 asks it for the newest Python 3.
if defined SystemRoot if exist "%SystemRoot%\py.exe" set "PYTHON=%SystemRoot%\py.exe"
if not defined PYTHON if defined LOCALAPPDATA if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" set "PYTHON=%LOCALAPPDATA%\Programs\Python\Launcher\py.exe"
if defined PYTHON set "PYTHON_FLAGS=-3"
if defined PYTHON goto run
rem 3. python.exe in a folder on PATH, given there as a full path, and neither the current folder
rem nor this one.
set "CURRENT=%CD%"
if "%CURRENT:~-1%"=="\" set "CURRENT=%CURRENT:~0,-1%"
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
if defined PATH for %%D in ("%PATH:;=" "%") do if not defined PYTHON call :look "%%~D"
if defined PYTHON goto run
goto missing

:run
rem -X utf8: text in and out as UTF-8, on every Python this may find, whatever the code page.
"%PYTHON%" %PYTHON_FLAGS% -X utf8 "%SCRIPT%" guide
set "EXIT_CODE=%ERRORLEVEL%"
rem 9009: Windows' own stand-in for python.exe, which only offers the Microsoft Store.
if "%EXIT_CODE%"=="9009" goto missing
goto finished

:look
set "ENTRY=%~1"
if not defined ENTRY exit /b 0
rem A full path only - C:\... or \\server\... - since anything else is found through the current folder.
if not "%ENTRY:~1,2%"==":\" if not "%ENTRY:~0,2%"=="\\" exit /b 0
if "%ENTRY:~-1%"=="\" set "ENTRY=%ENTRY:~0,-1%"
if /i "%ENTRY%"=="%CURRENT%" exit /b 0
if /i "%ENTRY%"=="%HERE%" exit /b 0
if exist "%ENTRY%\python.exe" set "PYTHON=%ENTRY%\python.exe"
exit /b 0

:missing
echo.
echo No Python was found to run the reporter. It looks, in this order, for:
echo   - the Python Codex Auto Resume installs, %%USERPROFILE%%\.codex-auto-resume\runtime\python.exe
echo   - the Python launcher, py.exe, which the python.org installer puts in Windows
echo   - python.exe in a folder on PATH
echo A report is about Codex Auto Resume: install it first, then double-click Report.cmd again.
set "EXIT_CODE=9009"
goto finished

:unzip
echo.
echo codex_compat_report.py is not beside this file. Unzip the whole ZIP first - right-click it and
echo choose Extract All - and then double-click Report.cmd in the folder that makes.
set "EXIT_CODE=2"
goto finished

:finished
echo.
pause
exit /b %EXIT_CODE%
