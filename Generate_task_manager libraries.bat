@echo off
echo Generating requirements.txt...

:: Change directory to the location of the batch file
cd /d "%~dp0"

:: Generate requirements.txt in the current directory
pip freeze > requirements.txt

if %errorlevel% equ 0 (
    echo Requirements file generated successfully.
    echo File path: %cd%\requirements.txt
) else (
    echo Error generating requirements file.
)

pause
