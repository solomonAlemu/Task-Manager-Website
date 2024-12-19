@echo off
echo Installing requirements.txt...
 
cd /d "%~dp0"
python -m pip install --upgrade pip

pip install -r requirements.txt
pip list

pause
