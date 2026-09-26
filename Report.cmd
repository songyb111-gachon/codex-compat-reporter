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
rem 3. python.exe in a folder on PATH, given there as a full path, and never the one in the current
rem folder or in this one, however PATH spells that folder (C:\x\., C:\y\..\x, a short name, a link).
rem A folder has many names, so the file is compared instead: a python.exe the same size and from
rem the same minute as one in either folder is taken to be that one.
set "CURRENT=%CD%"
if "%CURRENT:~-1%"=="\" set "CURRENT=%CURRENT:~0,-1%"
set "CURRENT_PYTHON="
set "HERE_PYTHON="
for %%F in ("%CURRENT%\python.exe") do if exist "%%~F" set "CURRENT_PYTHON=%%~zF %%~tF"
for %%F in ("%~dp0python.exe") do if exist "%%~F" set "HERE_PYTHON=%%~zF %%~tF"
rem PATH's own quotes are taken out first. Left in, a quoted entry such as "C:\Program Files (x86)\Foo"
rem turns the quoting of the list below inside out, its ) ends the list, and cmd stops with an error
rem before this file can say anything or wait.
set "ENTRIES="
if defined PATH set "ENTRIES=%PATH:"=%"
if defined ENTRIES for %%D in ("%ENTRIES:;=" "%") do if not defined PYTHON call :look "%%~D"
if defined PYTHON goto run
goto missing

:run
rem -I: isolated. Python would otherwise look first in the script's own folder - or, for a path too
rem long for it, in the current one - for every module the tool imports, and run a downloaded json.py
rem or argparse.py lying there. -I also leaves out PYTHONPATH and the other PYTHON* variables, and the
rem user's site-packages. The tool is one file of the standard library and needs none of them.
rem -X utf8: text in and out as UTF-8, on every Python this may find, whatever the code page.
"%PYTHON%" %PYTHON_FLAGS% -I -X utf8 "%SCRIPT%" guide
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
set "SEEN="
for %%F in ("%ENTRY%\python.exe") do if exist "%%~F" set "SEEN=%%~zF %%~tF"
if not defined SEEN exit /b 0
if "%SEEN%"=="%CURRENT_PYTHON%" exit /b 0
if "%SEEN%"=="%HERE_PYTHON%" exit /b 0
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
