# FeC-Plus - v0.04 dev
"""Avvio della GUI in modalità sviluppo senza finestra di console (pythonw)."""

import os
import runpy
import sys
import tempfile
import traceback

RADICE = os.path.dirname(os.path.abspath(__file__))
os.chdir(RADICE)
sys.path.insert(0, RADICE)
os.environ["FEC_DEV"] = "1"
if "--dev" not in sys.argv:
    sys.argv.append("--dev")

# Con pythonw stdout e stderr non esistono: gli errori dei callback Tk, che finiscono
# su stderr, sparirebbero in silenzio. Si scrivono in un file fuori da Git.
if sys.stderr is None or sys.stdout is None:
    flusso = None
    for cartella in (os.path.join(RADICE, "dev", "HAR-Debug"), tempfile.gettempdir()):
        try:
            # Un errore qui chiuderebbe il programma in silenzio: si prova altrove.
            flusso = open(os.path.join(cartella, "avvia_fec_dev.log"), "a",
                          encoding="utf-8", buffering=1)
            break
        except OSError:
            continue
    if flusso is None:
        flusso = open(os.devnull, "w", encoding="utf-8")
    sys.stdout = sys.stdout or flusso
    sys.stderr = sys.stderr or flusso

try:
    runpy.run_path(os.path.join(RADICE, "fec_gui.py"), run_name="__main__")
except Exception:
    # Senza console un errore di avvio sparirebbe in silenzio.
    traceback.print_exc()
    import tkinter as tk
    from tkinter import messagebox
    radice = tk.Tk()
    radice.withdraw()
    messagebox.showerror("FeC-Plus - errore di avvio", traceback.format_exc())
    radice.destroy()
