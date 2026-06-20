#!/bin/bash
# Launcher macOS — GUI FEC in modalità SVILUPPO (G.1): aggiunge la scheda Test Login,
# la cattura HAR e i selettori backend/headless. Doppio click da Finder per avviare.
cd "$(dirname "$0")" || exit 1

echo
cat assets/banner.txt
echo

export FEC_DEV=1

if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
else
    PY="python3"
fi

echo "Avvio FeC-Plus (DEV) con: $PY"
"$PY" fec_gui.py --dev
status=$?

if [ $status -ne 0 ]; then
    echo
    echo "ERRORE: avvio fallito (codice $status)."
    echo "Verifica che Python 3 e le dipendenze siano installati"
    echo "(usa il pulsante 'Installa dipendenze' nella GUI)."
    read -n 1 -s -r -p "Premi un tasto per chiudere..."
fi
