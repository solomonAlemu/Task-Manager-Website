cd /d "%~dp0"

echo Running batch file...
echo Running batch file... > logfile.txt 2>&1
netsh interface ip show interfaces

netsh interface ip add address name="Ethernet" addr=10.0.47.92 mask=255.255.255.0
 

ping 10.0.47.92
python server.py
pause