@echo off
chcp 65001 >nul
cd /d "%~dp0"
call .venv\Scripts\activate
echo Ornek: paket.bat turkcell 5321234567   (ya da: paket.bat avea 5051234567)
python robot.py paket %1 %2
pause
