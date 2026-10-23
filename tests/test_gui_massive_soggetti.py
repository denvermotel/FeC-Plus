#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Richieste Massive: selettore dei soggetti e coda."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_selettore
from _appgui import AppGuiCase


class TestRichiestaMassiva(AppGuiCase):

    def setUp(self):
        super().setUp()
        self.carica_deleghe()
        self.app.mass_tipo.set("Ft. Emesse")
        self.app.mass_dal.set("2026-01-01")
        self.app.mass_al.set("2026-03-31")
        patch.object(self.app, "_get_creds",
                     return_value=("CFUTENTE", "1234", "pwd", "CFSTUDIO")).start()
        self.lancio = patch.object(self.app, "_esegui_per_soggetti").start()

    def test_la_tab_ha_il_selettore(self):
        self.assertIsInstance(self.app.mass_sel, fec_selettore.SelettoreSoggetti)
        self.assertFalse(hasattr(self.app, "mass_cfcl"))

    def test_senza_soggetti_non_parte(self):
        with patch.object(fec_selettore.messagebox, "showwarning"):
            self.app._run_richiesta_massiva()
        self.lancio.assert_not_called()

    def test_due_soggetti_partono_in_coda(self):
        self.app.mass_sel.aggiungi_tutte()
        self.app._run_richiesta_massiva()
        soggetti, profilo, descrizione, op, fasi = self.lancio.call_args[0]
        self.assertEqual(len(soggetti), 2)
        self.assertEqual(descrizione, "Richiesta Massiva Ft. Emesse")
        self.assertEqual(fasi, 2)
        self.assertIs(self.lancio.call_args.kwargs["conta_soggetti"], True)

    def test_l_operazione_invia_e_registra_per_soggetto(self):
        self.app.mass_sel.imposta("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
        self.app._run_richiesta_massiva()
        op = self.lancio.call_args[0][3]
        fq = MagicMock()
        fq.esegui_richiesta.return_value = ['{"idRichiesta": "ID1"}']
        res = SimpleNamespace(piva="01234567890", denominazione="Rossi Mario")
        s = fec_selettore.Soggetto("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
        with patch.object(self.app, "_registra_richieste_massive") as registra:
            op(res, s, lambda _m: None, fq, None, None)
        kw = fq.esegui_richiesta.call_args.kwargs
        self.assertEqual((kw["cf_cliente"], kw["piva"]), ("RSSMRA80A01H501U", "01234567890"))
        self.assertEqual(registra.call_args[0][2:4], ("RSSMRA80A01H501U", "01234567890"))


class TestControllaRisultati(AppGuiCase):

    def setUp(self):
        super().setUp()
        self.carica_deleghe()
        patch.object(self.app, "_get_creds",
                     return_value=("CFUTENTE", "1234", "pwd", "CFSTUDIO")).start()
        self.lancio = patch.object(self.app, "_esegui_per_soggetti").start()

    def test_senza_scelta_lavora_sull_utenza_di_accesso(self):
        with patch.object(fec_selettore.messagebox, "showwarning") as avviso:
            self.app._run_controlla_risultati_massivi()
        avviso.assert_not_called()
        soggetti = self.lancio.call_args[0][0]
        self.assertEqual(soggetti, [fec_selettore.Soggetto("", "", "")])

    def test_un_solo_popup_con_le_righe_di_tutti(self):
        self.app.mass_sel.aggiungi_tutte()
        self.app._run_controlla_risultati_massivi()
        op = self.lancio.call_args[0][3]
        fine = self.lancio.call_args.kwargs["fine"]
        soggetti = self.lancio.call_args[0][0]
        res = SimpleNamespace()
        with patch.object(self.app, "_costruisci_righe_risultati",
                          side_effect=lambda r, log, cf_default, piva_default:
                          [{"id_richiesta": "R-" + cf_default}]):
            for s in soggetti:
                op(res, s, lambda _m: None, None, None, None)
        with patch.object(self.app, "_mostra_popup_risultati_massivi") as popup:
            fine([])
            self.root.update()
        popup.assert_called_once()
        self.assertEqual([r["id_richiesta"] for r in popup.call_args[0][0]],
                         ["R-RSSMRA80A01H501U", "R-VRDLGI70B02F205X"])


if __name__ == "__main__":
    unittest.main()
