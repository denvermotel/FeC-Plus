#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Ritenuta d'acconto nella finestra: filtro di Download Standard, colonne di Utility."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_gui
import fec_selettore
import fec_store
import fec_utility
from _appgui import AppGuiCase


class TestStandardSoloRitenuta(AppGuiCase):

    def test_preferenza_spenta_di_default_e_salvata(self):
        self.assertIn("std_solo_ritenuta", fec_store.SETTINGS_KEYS)
        self.assertFalse(self.app.std_solo_ritenuta.get())
        self.app.std_solo_ritenuta.set(True)
        with patch.object(fec_gui.messagebox, "showinfo"):
            self.app._save_config()
        self.assertIs(self.salva.call_args[0][0]["std_solo_ritenuta"], True)

    def test_avviso_se_manca_asn1crypto(self):
        self.carica_deleghe()
        self.app.std_tipo.set("Fatture Emesse")
        self.app.std_dal.set("01012026")
        self.app.std_al.set("31032026")
        self.app.std_solo_ritenuta.set(True)
        self.app.std_sel.imposta("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
        with patch.object(self.app, "_get_creds",
                          return_value=("CFUTENTE", "1234", "pwd", "CFSTUDIO")), \
                patch.object(self.app, "_esegui_per_soggetti") as lancio, \
                patch.object(fec_gui.fec_deps, "find_missing",
                             return_value={"p7m": ["asn1crypto"]}), \
                patch.object(fec_gui.messagebox, "showwarning") as avviso:
            self.app._run_standard()
        avviso.assert_called_once()
        self.assertIn("asn1crypto", avviso.call_args[0][1])
        lancio.assert_called_once()

    def test_il_filtro_arriva_al_download(self):
        self.carica_deleghe()
        self.app.std_tipo.set("Fatture Ricevute")
        self.app.std_dal.set("01012026")
        self.app.std_al.set("31032026")
        self.app.std_solo_ritenuta.set(True)
        self.app.std_sel.imposta("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
        with patch.object(self.app, "_get_creds",
                          return_value=("CFUTENTE", "1234", "pwd", "CFSTUDIO")), \
                patch.object(self.app, "_esegui_per_soggetti") as lancio:
            self.app._run_standard()
        op = lancio.call_args[0][3]
        fq = MagicMock()
        fq.esegui_richiesta.return_value = SimpleNamespace(
            id_invio_elenco=set(), fatture=0, metadati=0, saltati=0, errori=0, in_attesa=0)
        s = fec_selettore.Soggetto("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
        op(SimpleNamespace(piva="01234567890", denominazione="Rossi Mario"), s,
           lambda _m: None, fq, None, None)
        self.assertIs(fq.esegui_richiesta.call_args.kwargs["solo_ritenuta"], True)


class TestUtilityRitenuta(AppGuiCase):

    def setUp(self):
        super().setUp()
        self.carica_deleghe()
        self.app.util_tipo.set("Fatture Emesse")
        self.app.util_dal.set("01012026")
        self.app.util_al.set("31032026")

    def test_preferenza_spenta_di_default_e_salvata(self):
        self.assertIn("util_ritenuta", fec_store.SETTINGS_KEYS)
        self.assertFalse(self.app.util_ritenuta.get())
        self.app.util_ritenuta.set(True)
        with patch.object(fec_gui.messagebox, "showinfo"):
            self.app._save_config()
        self.assertIs(self.salva.call_args[0][0]["util_ritenuta"], True)

    def test_corrispettivi_mai_con_ritenuta(self):
        self.app.util_tipo.set("Corrispettivi")
        op = self._op("excel")
        s = fec_selettore.Soggetto("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
        import fec_corrispettivi
        with patch.object(fec_corrispettivi, "elenco_corrispettivi_excel",
                          return_value=SimpleNamespace(percorsi=[], avvisi=[])) as corr, \
                patch.object(fec_utility, "elenco_fatture_excel") as fatture:
            op(SimpleNamespace(piva="01234567890", denominazione="Rossi Mario"), s,
               lambda _m: None, MagicMock(), None, None)
        fatture.assert_not_called()
        self.assertNotIn("ritenuta", corr.call_args.kwargs)

    def test_casella_disattivata_con_csv_e_corrispettivi(self):
        self.app.util_formato.set("excel")
        self.app.util_tipo.set("Fatture Emesse")
        self.assertFalse(self.app._util_ritenuta_cb.instate(["disabled"]))
        self.app.util_formato.set("csv")
        self.assertTrue(self.app._util_ritenuta_cb.instate(["disabled"]))
        self.app.util_formato.set("excel")
        self.app.util_tipo.set("Corrispettivi")
        self.assertTrue(self.app._util_ritenuta_cb.instate(["disabled"]))

    def _op(self, formato):
        self.app.util_formato.set(formato)
        self.app.util_ritenuta.set(True)
        self.app.util_sel.imposta("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
        with patch.object(self.app, "_get_creds",
                          return_value=("CFUTENTE", "1234", "pwd", "CFSTUDIO")), \
                patch.object(self.app, "_esegui_per_soggetti") as lancio, \
                patch.object(fec_gui.fec_deps, "find_missing", return_value={}):
            self.app._run_utility()
        return lancio.call_args[0][3]

    def _esegui_op(self, op, funzione):
        s = fec_selettore.Soggetto("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
        with patch.object(fec_utility, funzione, return_value="elenco") as genera:
            op(SimpleNamespace(piva="01234567890", denominazione="Rossi Mario"), s,
               lambda _m: None, MagicMock(), None, None)
        return genera

    def test_excel_con_ritenuta(self):
        genera = self._esegui_op(self._op("excel"), "elenco_fatture_excel")
        self.assertIs(genera.call_args.kwargs["ritenuta"], True)

    def test_csv_mai_con_ritenuta(self):
        genera = self._esegui_op(self._op("csv"), "elenco_fatture_csv_ade")
        self.assertNotIn("ritenuta", genera.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
