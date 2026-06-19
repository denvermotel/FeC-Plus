@echo off
chcp 65001 >nul
title FEC - Fatture e Corrispettivi
cd /d "%~dp0"
echo Avvio FEC - Fatture e Corrispettivi...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" fec_gui.py
) else (
    python fec_gui.py
)
if errorlevel 1 (
    echo.
    echo ERRORE: Python non trovato o errore di avvio.
    echo Verificare che Python sia installato e nel PATH.
    pause
)
