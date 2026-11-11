@echo off
rem Called by the Boom Box .bat files: finds Anaconda/Miniconda and activates its base.
set "CONDA_ROOT="
for %%D in ("%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "%USERPROFILE%\miniforge3" "%LOCALAPPDATA%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%LOCALAPPDATA%\miniforge3" "%ProgramData%\anaconda3" "%ProgramData%\miniconda3" "%ProgramData%\miniforge3" "C:\anaconda3" "C:\miniconda3") do (
    if not defined CONDA_ROOT if exist "%%~D\Scripts\activate.bat" set "CONDA_ROOT=%%~D"
)
if not defined CONDA_ROOT (
    for /f "delims=" %%P in ('conda info --base 2^>nul') do set "CONDA_ROOT=%%P"
)
if not defined CONDA_ROOT (
    echo Could not find Anaconda. Install Anaconda or Miniconda first.
    exit /b 1
)
call "%CONDA_ROOT%\Scripts\activate.bat" "%CONDA_ROOT%"
exit /b 0
