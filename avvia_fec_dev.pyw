# FeC-Plus - v0.04 dev
"""Avvio della GUI in modalità sviluppo senza finestra di console (pythonw)."""

import os
import runpy
import sys
import traceback

RADICE = os.path.dirname(os.path.abspath(__file__))
os.chdir(RADICE)
sys.path.insert(0, RADICE)
os.environ["FEC_DEV"] = "1"
if "--dev" not in sys.argv:
    sys.argv.append("--dev")

try:
    runpy.run_path(os.path.join(RADICE, "fec_gui.py"), run_name="__main__")
except SystemExit:
    raise
except Exception:
    # Senza console un errore di avvio sparirebbe in silenzio.
    import tkinter as tk
    from tkinter import messagebox
    radice = tk.Tk()
    radice.withdraw()
    messagebox.showerror("FeC-Plus - errore di avvio", traceback.format_exc())
    radice.destroy()
