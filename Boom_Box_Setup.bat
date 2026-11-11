@echo off
rem Double-click once to create (or update) the 'boombox' Anaconda environment.
setlocal
cd /d "%~dp0"
call "%~dp0find_conda.bat" || goto :noconda

call conda env list | findstr /R /C:"^boombox " >nul
if errorlevel 1 (
    echo Creating the 'boombox' environment (a few minutes^)...
    call conda env create -f environment-windows.yml
) else (
    echo Updating the 'boombox' environment...
    call conda env update -n boombox -f environment-windows.yml --prune
)
if errorlevel 1 goto :failed
echo.
echo Done.
pause
exit /b 0

:failed
echo.
echo Setup FAILED (see the messages above).
pause
exit /b 1

:noconda
echo.
echo Could not find Anaconda, so nothing was set up.
pause
exit /b 1
