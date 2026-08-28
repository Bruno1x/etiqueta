@echo off
setlocal
cd /d "%~dp0"
start "Restaurar Etiquetas Bot" ".venv\Scripts\pythonw.exe" update_bootstrap.py --rollback
