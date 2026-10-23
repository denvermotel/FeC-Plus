#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Bolli Virtuali: selettore dei soggetti e coda."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_selettore
from _appgui import AppGuiCase


class TestRunBolli(AppGuiCase):

    def setUp(self):
        super().setUp()
        self.carica_deleghe()
        self.app.bolli_trim.set("2")
        self.app.bolli_anno.set("2026")
        patch.object(self.app, "_get_creds",
                     return_value=("CFUTENTE", "1234", "pwd", "CFSTUDIO")).start()
        self.lancio = patch.object(self.app, "_esegui_per_soggetti").start()

    def test_la_tab_ha_il_selettore(self):
        self.assertIsInstance(self.app.bolli_sel, fec_selettore.SelettoreSoggetti)
        self.assertFalse(hasattr(self.app, "bolli_cfcl"))

    def test_senza_soggetti_non_parte(self):
        with patch.object(fec_selettore.messagebox, "showwarning"):
            self.app._run_bolli()
        self.lancio.assert_not_called()

    def test_due_soggetti_partono_in_coda(self):
        self.app.bolli_sel.aggiungi_tutte()
        self.app._run_bolli()
        soggetti, profilo, descrizione, op, fasi = self.lancio.call_args[0]
        self.assertEqual(len(soggetti), 2)
        self.assertEqual(descrizione, "Bolli 2/2026")
        self.assertEqual(fasi, 2)
        self.assertIs(self.lancio.call_args.kwargs["conta_soggetti"], True)

    def test_l_operazione_lavora_sul_soggetto(self):
        self.app.bolli_sel.imposta("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
        self.app._run_bolli()
        op = self.lancio.call_args[0][3]
        fq = MagicMock()
        res = SimpleNamespace(piva="01234567890", denominazione="Rossi Mario")
        s = fec_selettore.Soggetto("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
        op(res, s, lambda _m: None, fq, None, None)
        kw = fq.esegui_richiesta.call_args.kwargs
        self.assertEqual((kw["cf_cliente"], kw["piva"], kw["trimestre"], kw["anno"]),
                         ("RSSMRA80A01H501U", "01234567890", "2", "2026"))
        self.assertEqual(kw["dest_dir"], os.path.join(
            self.base, "Rossi Mario - 01234567890", "Bolli virtuali", "2026"))


if __name__ == "__main__":
    unittest.main()
