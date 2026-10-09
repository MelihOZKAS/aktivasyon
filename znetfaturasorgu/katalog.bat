@echo off
chcp 65001 >nul
cd /d "%~dp0"
call .venv\Scripts\activate
echo Kurum listesi yenileniyor (yalnizca istedigin zaman calistir)...
python isci.py katalog
pause
