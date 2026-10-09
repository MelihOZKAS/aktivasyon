@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   FATURA ROBOTU - KURULUM (bir kere calisir)
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
  echo HATA: Python bulunamadi.
  echo python.org adresinden Python 3.11+ kur, "Add to PATH" kutusunu isaretle.
  pause
  exit /b 1
)

echo [1/3] Ortam hazirlaniyor...
python -m venv .venv || goto hata
call .venv\Scripts\activate

echo [2/3] Playwright kuruluyor...
python -m pip install --upgrade pip >nul
pip install playwright==1.48.0 || goto hata

echo [3/3] Chromium tarayicisi iniyor (biraz surebilir)...
python -m playwright install chromium || goto hata

echo.
echo Kurulum tamam. Simdi calistir.bat ile baslat.
pause
exit /b 0

:hata
echo.
echo Kurulumda hata olustu. Yukaridaki mesaja bak.
pause
exit /b 1
