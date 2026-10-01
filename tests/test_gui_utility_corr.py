#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Tab Utility: scelta della modalità dei distributori automatici."""

import os
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_gui
import fec_store
from _protezione import DatiRealiProtetti


def _tk_disponibile() -> bool:
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(_tk_disponibile(), "richiede un display Tk")
class TestUtilityDistributori(unittest.TestCase):

    def setUp(self):
        self.protezione = DatiRealiProtetti().__enter__()
        self.addCleanup(self.protezione.__exit__, None, None, None)
        self.salva = patch.object(fec_store, "save_settings").start()
        patch.object(fec_store, "save_credentials").start()
        self.addCleanup(patch.stopall)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = fec_gui.FecGui(self.root)

    def tearDown(self):
        self.root.destroy()
        patch.stopall()

    def test_scelta_visibile_solo_coi_corrispettivi(self):
        self.app.util_tipo.set("Corrispettivi")
        self.assertEqual(self.app._util_da_frame.winfo_manager(), "grid")
        self.app.util_tipo.set("Fatture Emesse")
        self.assertEqual(self.app._util_da_frame.winfo_manager(), "")

    def test_cambio_modalita_salva_la_preferenza(self):
        with patch.object(fec_store, "load_settings", return_value={}):
            self.app.util_da_modalita.set("grezzi")
        salvato = self.salva.call_args[0][0]
        self.assertEqual(salvato["corr_da_modalita"], "grezzi")

    def test_chiave_in_whitelist(self):
        self.assertIn("corr_da_modalita", fec_store.SETTINGS_KEYS)


if __name__ == "__main__":
    unittest.main()
