#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Download Standard: selettore dei soggetti, coda e opzione dei metadati."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_gui
import fec_selettore
from _appgui import AppGuiCase


class TestSelettoreNellaTab(AppGuiCase):

    def test_la_tab_ha_il_selettore(self):
        self.assertIsInstance(self.app.std_sel, fec_selettore.SelettoreSoggetti)
        self.assertFalse(hasattr(self.app, "std_cf_cl"))

    def test_le_deleghe_arrivano_al_selettore(self):
        self.carica_deleghe()
        self.assertEqual(self.app.std_sel.info_var.get(), "2 deleghe")

    def test_usa_per_download_imposta_il_selettore(self):
        self.carica_deleghe()
        self.app._deleghe_refresh()
        self.app.deleghe_tree.selection_set("0")
        self.app._deleghe_usa_in("_std_tab", "std_sel")
        self.assertEqual([(s.nome, s.cf, s.piva) for s in self.app.std_sel.scelti],
                         [("Rossi Mario", "RSSMRA80A01H501U", "01234567890")])


class TestRunStandard(AppGuiCase):

    def setUp(self):
        super().setUp()
        self.carica_deleghe()
        self.app.std_tipo.set("Fatture Emesse")
        self.app.std_dal.set("01012026")
        self.app.std_al.set("31032026")
        patch.object(self.app, "_get_creds",
                     return_value=("CFUTENTE", "1234", "pwd", "CFSTUDIO")).start()
        self.lancio = patch.object(self.app, "_esegui_per_soggetti").start()

    def test_senza_soggetti_non_parte(self):
        with patch.object(fec_selettore.messagebox, "showwarning") as avviso:
            self.app._run_standard()
        avviso.assert_called_once()
        self.lancio.assert_not_called()

    def test_due_soggetti_le_fasi_si_moltiplicano(self):
        self.app.std_sel.aggiungi_tutte()
        self.app._run_standard()
        soggetti, profilo, descrizione, op, fasi = self.lancio.call_args[0]
        self.assertEqual([s.cf for s in soggetti],
                         ["RSSMRA80A01H501U", "VRDLGI70B02F205X"])
        self.assertEqual(descrizione, "Fatture Emesse")
        self.assertEqual(fasi, 2)         # un blocco da 3 mesi x un tipo x due soggetti

    def test_periodo_di_un_anno_quattro_blocchi_per_soggetto(self):
        self.app.std_al.set("31122026")
        self.app.std_sel.aggiungi_tutte()
        self.app._run_standard()
        self.assertEqual(self.lancio.call_args[0][4], 8)

    def test_l_operazione_lavora_sul_soggetto_con_l_opzione_metadati(self):
        self.app.std_scarica_metadati.set(False)
        self.app.std_sel.imposta("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
        self.app._run_standard()
        op = self.lancio.call_args[0][3]
        fq = MagicMock()
        fq.esegui_richiesta.return_value = SimpleNamespace(
            id_invio_elenco=set(), fatture=0, metadati=0, saltati=0, errori=0, in_attesa=0)
        res = SimpleNamespace(piva="01234567890", denominazione="Rossi Mario")
        s = fec_selettore.Soggetto("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
        op(res, s, lambda _m: None, fq, None, None)
        kw = fq.esegui_richiesta.call_args.kwargs
        self.assertEqual(kw["cf_cliente"], "RSSMRA80A01H501U")
        self.assertIs(kw["scarica_metadati"], False)
        self.assertEqual(kw["dest_dir"], os.path.join(
            self.base, "Rossi Mario - 01234567890", "Fatture emesse"))

    def test_date_non_valide_non_parte(self):
        self.app.std_al.set("31132026")
        self.app.std_sel.aggiungi_tutte()
        with patch.object(fec_gui.messagebox, "showerror") as errore:
            self.app._run_standard()
        errore.assert_called_once()
        self.lancio.assert_not_called()


if __name__ == "__main__":
    unittest.main()
