#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Utility: selettore dei soggetti e coda."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_selettore
import fec_utility
from _appgui import AppGuiCase


class TestRunUtility(AppGuiCase):

    def setUp(self):
        super().setUp()
        self.carica_deleghe()
        self.app.util_tipo.set("Fatture Emesse")
        self.app.util_formato.set("csv")           # niente openpyxl nei test
        self.app.util_dal.set("01012026")
        self.app.util_al.set("31032026")
        patch.object(self.app, "_get_creds",
                     return_value=("CFUTENTE", "1234", "pwd", "CFSTUDIO")).start()
        self.lancio = patch.object(self.app, "_esegui_per_soggetti").start()

    def test_la_tab_ha_il_selettore(self):
        self.assertIsInstance(self.app.util_sel, fec_selettore.SelettoreSoggetti)
        self.assertFalse(hasattr(self.app, "util_cfcl"))
        self.assertFalse(hasattr(self.app, "util_piva"))

    def test_l_etichetta_piva_segue_il_tipo_elenco(self):
        self.app.util_tipo.set("Corrispettivi")
        self.assertEqual(self.app.util_sel.etichetta_piva_var.get(),
                         "P.IVA (se vuota, quella attiva):")
        self.app.util_tipo.set("Fatture Emesse")
        self.assertEqual(self.app.util_sel.etichetta_piva_var.get(), "P.IVA (opzionale):")

    def test_senza_soggetti_non_parte(self):
        with patch.object(fec_selettore.messagebox, "showwarning"):
            self.app._run_utility()
        self.lancio.assert_not_called()

    def test_due_soggetti_partono_in_coda(self):
        self.app.util_sel.aggiungi_tutte()
        self.app._run_utility()
        soggetti, profilo, descrizione, op, fasi = self.lancio.call_args[0]
        self.assertEqual(len(soggetti), 2)
        self.assertEqual(descrizione, "Elenco CSV Fatture Emesse")
        self.assertEqual(fasi, 2)
        self.assertIs(self.lancio.call_args.kwargs["conta_soggetti"], True)

    def test_l_operazione_lavora_sul_soggetto(self):
        self.app.util_sel.imposta("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
        self.app._run_utility()
        op = self.lancio.call_args[0][3]
        res = SimpleNamespace(piva="01234567890", denominazione="Rossi Mario")
        s = fec_selettore.Soggetto("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
        with patch.object(fec_utility, "elenco_fatture_csv_ade",
                          return_value="elenco.csv") as genera:
            esito = op(res, s, lambda _m: None, MagicMock(), None, None)
        self.assertEqual(genera.call_args[0][1:4], ("RSSMRA80A01H501U", "01234567890", "emesse"))
        self.assertEqual(genera.call_args.kwargs["dest_dir"], os.path.join(
            self.base, "Rossi Mario - 01234567890", "Elenchi", "2026"))
        self.assertEqual(esito, [os.path.join(self.base, "Rossi Mario - 01234567890")])

    def test_dump_con_piu_soggetti_si_rifiuta(self):
        self.app.util_sel.aggiungi_tutte()
        with patch.object(fec_selettore.messagebox, "showwarning") as avviso, \
                patch.object(self.app, "_esegui_in_process") as lancio:
            self.app._run_utility_dump()
        avviso.assert_called_once()
        lancio.assert_not_called()


if __name__ == "__main__":
    unittest.main()
