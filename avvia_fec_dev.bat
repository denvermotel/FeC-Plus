@echo off
chcp 65001 >nul
title FeC-Plus (DEV) - Fatture e Corrispettivi
cd /d "%~dp0"
set FEC_DEV=1
echo.
type assets\banner.txt
echo.
echo Avvio FeC-Plus in modalita SVILUPPO (Test Login, cattura HAR, backend/headless)...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" fec_gui.py --dev
) else (
    python fec_gui.py --dev
)
if errorlevel 1 (
    echo.
    echo ERRORE: Python non trovato o errore di avvio.
    echo Verificare che Python sia installato e nel PATH.
    pause
)
