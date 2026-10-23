#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Base dei test della finestra: FecGui con salvataggi e dati reali neutralizzati."""

import os
import shutil
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_deleghe
import fec_gui
import fec_store
from _protezione import DatiRealiProtetti

# Deleghe di comodo (mai dati reali).
DELEGHE = [
    {"codice_fiscale": "RSSMRA80A01H501U", "partita_iva": "01234567890",
     "denominazione": "Rossi Mario"},
    {"codice_fiscale": "VRDLGI70B02F205X", "partita_iva": "",
     "denominazione": "Verdi Luigi"},
]


def tk_disponibile() -> bool:
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(tk_disponibile(), "richiede un display Tk")
class AppGuiCase(unittest.TestCase):
    """`self.app` è una FecGui con cartella base temporanea (`self.base`), cartelle in
    modalità «ditta», nessun salvataggio su disco e nessuna chiamata di rete."""

    def setUp(self):
        self.protezione = DatiRealiProtetti().__enter__()
        self.addCleanup(self.protezione.__exit__, None, None, None)
        self.salva = patch.object(fec_store, "save_settings").start()
        patch.object(fec_store, "save_credentials").start()
        # _save_config senza «salva credenziali» cancellerebbe fec_credentials.dat.
        patch.object(fec_store, "clear_credentials").start()
        patch.object(fec_deleghe, "save_deleghe").start()
        self.addCleanup(patch.stopall)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.addCleanup(self._ferma_callback)
        self.app =fec_gui.FecGui(self.root)
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.app.std_destdir.set(self.base)
        for v in self.app.dirclassi.values():
            v["personalizza"].set(False)
            v["senza_sotto"].set(False)
            v["path"].set("")
        self.app.cartelle_modalita.set("ditta")
        self.app.cartelle_anno.set(True)
        self.app.std_includi_trans.set(False)
        self.app.std_includi_disposizione.set(False)
        self.app.deleghe_no_update_var.set(True)
        self.app.popup_fine_task.set(False)
        patch.object(fec_deleghe, "load_deleghe",
                     return_value=[dict(r) for r in DELEGHE]).start()

    def _ferma_callback(self):
        """Gira prima della distruzione della root: niente `after` pendenti su una finestra
        che non c'è più (pompa del progresso, riposizionamento dei pannelli)."""
        progresso = getattr(getattr(self, "app", None), "progresso", None)
        if progresso is not None:
            try:
                progresso.ferma()
            except Exception:  # noqa: BLE001 - pulizia best effort
                pass
        try:
            for i in self.root.tk.call("after", "info"):
                # Annullo a livello Tcl: `after_cancel` cancellerebbe anche il comando
                # Python, che la destroy dei widget (DateEntry) poi tenta di rimuovere.
                self.root.tk.call("after", "cancel", i)
        except tk.TclError:
            pass

    def carica_deleghe(self):
        """Mette le deleghe di comodo nella finestra e nei selettori."""
        self.app.deleghe_rows = [dict(r) for r in DELEGHE]
        self.app._aggiorna_selettori()
