@echo off
rem Double-click to start Boom Box.
setlocal
cd /d "%~dp0app"
call "%~dp0app\find_conda.bat" || goto :fail

call conda env list | findstr /R /C:"^boombox " >nul
if errorlevel 1 (
    echo The 'boombox' environment is missing. Running first-time install...
    call conda env create -f environment-windows.yml || goto :fail
)

call conda activate boombox || goto :fail
python -m boombox
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Boom Box could not start or exited with an error (see the messages above).
pause
exit /b 1
