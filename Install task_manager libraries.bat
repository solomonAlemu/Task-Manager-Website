@echo off
 
pip install pipreqs
pipreqs . --force
 
pip install -r requirements.txt

pause