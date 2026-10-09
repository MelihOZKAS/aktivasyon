@echo off
chcp 65001 >nul
cd /d "%~dp0"
call .venv\Scripts\activate
echo Ornek: sorgu.bat vodafone 5332590138
python robot.py sorgu %1 %2
pause
