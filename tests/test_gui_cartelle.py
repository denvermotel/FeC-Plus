#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Preferenze e destinazione delle cartelle nella GUI."""

import os
import shutil
import sys
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_directory
import fec_deleghe
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
class TestGuiCartelle(unittest.TestCase):

    def setUp(self):
        self.protezione = DatiRealiProtetti().__enter__()
        self.addCleanup(self.protezione.__exit__, None, None, None)
        self.salva = patch.object(fec_store, "save_settings").start()
        patch.object(fec_store, "save_credentials").start()
        self.addCleanup(patch.stopall)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = fec_gui.FecGui(self.root)
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.app.std_destdir.set(self.base)
        for v in self.app.dirclassi.values():
            v["personalizza"].set(False)
            v["senza_sotto"].set(False)
            v["path"].set("")

    def test_chiavi_in_whitelist(self):
        self.assertIn("cartelle_modalita", fec_store.SETTINGS_KEYS)
        self.assertIn("cartelle_anno", fec_store.SETTINGS_KEYS)

    def test_config_legge_le_preferenze(self):
        self.app.cartelle_modalita.set("sessione")
        self.app.cartelle_anno.set(False)
        self.app.dirclassi["bolli"]["personalizza"].set(True)
        self.app.dirclassi["bolli"]["path"].set("G")
        self.app.dirclassi["bolli"]["senza_sotto"].set(True)
        config = self.app._config_cartelle()
        self.assertEqual((config.base, config.modalita, config.anno),
                         (self.base, "sessione", False))
        self.assertRegex(config.sessione, r"^\d{4}-\d{2}-\d{2}_\d{4}$")
        self.assertEqual(config.personalizzate, {"bolli": ("G", True)})

    def test_senza_sottocartella_senza_personalizza_resta_valido(self):
        self.app.dirclassi["emesse"]["senza_sotto"].set(True)
        self.assertEqual(self.app._config_cartelle().personalizzate,
                         {"emesse": ("", True)})

    def test_destinazione_con_denominazione_dal_login(self):
        self.app.cartelle_modalita.set("ditta")
        self.app.cartelle_anno.set(True)
        config = self.app._config_cartelle()
        res = SimpleNamespace(piva="01234567890", denominazione="ROSSI SRL")
        with patch.object(fec_deleghe, "load_deleghe", return_value=[]):
            d = self.app._destinazione(config, "emesse", res, "CFCLIENTE", "", "CFUT",
                                       lambda *_: None, per_documento=True)
        self.assertEqual(d.cartella, os.path.join(self.base, "ROSSI SRL - 01234567890",
                                                  "Fatture emesse"))
        self.assertTrue(d.per_anno)

    def test_destinazione_con_denominazione_dalle_deleghe(self):
        config = self.app._config_cartelle()
        res = SimpleNamespace(piva="", denominazione="")
        deleghe = [{"codice_fiscale": "CFCLIENTE", "denominazione": "BIANCHI SAS"}]
        with patch.object(fec_deleghe, "load_deleghe", return_value=deleghe):
            d = self.app._destinazione(config, "bolli", res, "CFCLIENTE", "", "CFUT",
                                       lambda *_: None, anno_periodo="2026")
        self.assertEqual(d.cartella, os.path.join(self.base, "BIANCHI SAS - CFCLIENTE",
                                                  "Bolli virtuali", "2026"))

    def test_casella_anno_visibile_solo_in_modalita_ditta(self):
        frame = tk.Frame(self.root)
        self.app._build_organizzazione_cartelle(frame, 0)
        self.app.cartelle_modalita.set("sessione")
        self.app._aggiorna_cartelle_anno()
        self.assertFalse(self.app._cartelle_anno_visibile())
        self.app.cartelle_modalita.set("ditta")
        self.app._aggiorna_cartelle_anno()
        self.assertTrue(self.app._cartelle_anno_visibile())


if __name__ == "__main__":
    unittest.main()
