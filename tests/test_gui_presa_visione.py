#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Avviso sulla presa visione delle fatture messe a disposizione."""

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
class TestAvvisoPresaVisione(unittest.TestCase):

    def setUp(self):
        self.protezione = DatiRealiProtetti().__enter__()
        self.addCleanup(self.protezione.__exit__, None, None, None)
        self.salva = patch.object(fec_store, "save_settings").start()
        patch.object(fec_store, "save_credentials").start()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = fec_gui.FecGui(self.root)
        self.app.avviso_presa_visione.set(True)

    def tearDown(self):
        self.root.destroy()
        patch.stopall()

    def _avvisi_aperti(self):
        return [w for w in self.root.winfo_children()
                if isinstance(w, tk.Toplevel) and "presa visione" in w.title().lower()]

    def test_nessun_avviso_all_avvio(self):
        root = tk.Tk()
        root.withdraw()
        try:
            fec_gui.FecGui(root)
            self.assertEqual([w for w in root.winfo_children()
                              if isinstance(w, tk.Toplevel)
                              and "presa visione" in w.title().lower()], [])
        finally:
            root.destroy()

    def test_disattivato_non_apre_nulla(self):
        self.app.avviso_presa_visione.set(False)
        self.assertIsNone(self.app._avviso_presa_visione())
        self.assertEqual(self._avvisi_aperti(), [])

    def test_non_mostrare_piu(self):
        win = self.app._avviso_presa_visione()
        self.assertIsNotNone(win)
        win.non_mostrare.set(True)
        with patch.object(fec_store, "load_settings", return_value={}):
            win.chiudi()
        self.assertFalse(self.app.avviso_presa_visione.get())
        self.assertEqual(self.salva.call_args[0][0]["avviso_presa_visione"], False)

    def test_chiudere_senza_spunta_lascia_attivo(self):
        win = self.app._avviso_presa_visione()
        win.chiudi()
        self.assertTrue(self.app.avviso_presa_visione.get())

    def test_tipo_messe_a_disposizione_nel_download_standard(self):
        self.app.std_tipo.set("Messe a Disposizione")
        self.app._std_tipo_cb.event_generate("<<ComboboxSelected>>")
        self.assertEqual(len(self._avvisi_aperti()), 1)

    def test_altro_tipo_non_avvisa(self):
        self.app.std_tipo.set("Fatture Emesse")
        self.app._std_tipo_cb.event_generate("<<ComboboxSelected>>")
        self.assertEqual(self._avvisi_aperti(), [])

    def test_casella_includi(self):
        self.app.std_includi_disposizione.set(True)
        self.app._includi_disposizione_cambiato()
        self.assertEqual(len(self._avvisi_aperti()), 1)

    def test_casella_includi_spenta_non_avvisa(self):
        self.app.std_includi_disposizione.set(False)
        self.app._includi_disposizione_cambiato()
        self.assertEqual(self._avvisi_aperti(), [])

    def test_richieste_massive(self):
        self.app.mass_tipo.set("Ft. Messe a Disposizione")
        self.app._mass_tipo_cb.event_generate("<<ComboboxSelected>>")
        self.assertEqual(len(self._avvisi_aperti()), 1)

    def test_chiave_in_whitelist(self):
        self.assertIn("avviso_presa_visione", fec_store.SETTINGS_KEYS)


if __name__ == "__main__":
    unittest.main()
