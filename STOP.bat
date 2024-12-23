cd /d "%~dp0"

echo Running batch file...
echo Running batch file... > logfile.txt 2>&1
netsh interface ip show interfaces

netsh interface ip delete address name="Local Area Connection* 1" addr=10.0.47.92

ping 10.0.47.92 > logfile.txt 2>&1

pause