@echo off
rem Double-click to install Boom Box, or to update it after downloading a new version.
rem Creates the 'boombox' Anaconda environment, or updates an existing one in place.
setlocal
cd /d "%~dp0app"
call "%~dp0app\find_conda.bat" || goto :noconda

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
echo Install FAILED (see the messages above).
pause
exit /b 1

:noconda
echo.
echo Could not find Anaconda, so nothing was installed.
pause
exit /b 1
