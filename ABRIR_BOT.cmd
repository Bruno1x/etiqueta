@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto :launch

echo Preparando o ambiente na primeira execucao...
where python >nul 2>nul
if not errorlevel 1 goto :use_python
where py >nul 2>nul
if not errorlevel 1 goto :use_py

echo Python 3.11 ou superior nao foi encontrado.
echo Instale o Python e marque a opcao Add Python to PATH.
pause
exit /b 1

:use_python
python -m venv .venv
goto :install

:use_py
py -3 -m venv .venv

:install
if errorlevel 1 goto :failure
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failure
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failure

:launch
".venv\Scripts\python.exe" -c "import cv2, PIL, pyautogui" >nul 2>nul
if errorlevel 1 (
  echo Instalando ou reparando as dependencias...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :failure
)
start "Etiquetas Bot" ".venv\Scripts\pythonw.exe" update_bootstrap.py
exit /b 0

:failure
echo.
echo Nao foi possivel preparar o Etiquetas Bot.
pause
exit /b 1
