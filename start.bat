cd /d "%~dp0"

echo Running batch file...
echo Running batch file... > logfile.txt 2>&1
python app.py
pause