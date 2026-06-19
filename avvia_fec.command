#!/bin/bash
# Launcher macOS per la GUI FEC – Fatture e Corrispettivi.
# Doppio click da Finder per avviare. Usa il virtualenv .venv se presente.
cd "$(dirname "$0")" || exit 1

if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
else
    PY="python3"
fi

echo "Avvio FEC con: $PY"
"$PY" fec_gui.py
status=$?

if [ $status -ne 0 ]; then
    echo
    echo "ERRORE: avvio fallito (codice $status)."
    echo "Verifica che Python 3 e le dipendenze siano installati"
    echo "(usa il pulsante 'Installa dipendenze' nella GUI)."
    read -n 1 -s -r -p "Premi un tasto per chiudere..."
fi
