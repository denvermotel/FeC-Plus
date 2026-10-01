#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Distributori automatici: i valori trasmessi sono contatori progressivi."""

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_corrispettivi as fc


def _voce(id_invio, quando, importo, matricola="M1", modalita="CUMULATO"):
    return {"idInvio": id_invio, "timeRilevazione": quando, "matricolaDispositivo": matricola,
            "modalitaRilevazione": modalita, "importo": importo}


def _dettaglio(venduto):
    return {"datiContabiliDA": {"venduto": venduto, "vendutoContante": "1,00",
                                "incassatoNoContante": "2,00"}}


class TestLetturePrecedenti(unittest.TestCase):

    def test_ultima_lettura_prima_dell_inizio_per_matricola(self):
        voci = [_voce("1", "01/05/2026 10:00", "90000,00"),
                _voce("2", "20/06/2026 10:00", "95116,94"),
                _voce("3", "15/06/2026 10:00", "500,00", matricola="M2"),
                _voce("4", "02/07/2026 10:00", "99999,00")]
        self.assertEqual(fc.letture_precedenti(voci, datetime(2026, 7, 1)),
                         {"M1": 95116.94, "M2": 500.0})


class TestDifferenza(unittest.TestCase):

    def test_venduto_per_differenza(self):
        invii = [(_voce("11", "21/08/2026 10:00", "96462,94"), _dettaglio("96462,94")),
                 (_voce("10", "03/07/2026 10:00", "95500,00"), _dettaglio("95500,00"))]
        righe = fc.righe_da_differenza(invii, {"M1": 95116.94})
        self.assertEqual([r["ID Invio"] for r in righe], ["10", "11"])
        self.assertEqual(righe[0]["Lettura precedente"], 95116.94)
        self.assertAlmostEqual(righe[0]["Venduto dell'intervallo"], 383.06)
        self.assertEqual(righe[1]["Lettura precedente"], 95500.0)
        self.assertAlmostEqual(righe[1]["Venduto dell'intervallo"], 962.94)
        self.assertEqual(righe[1]["Totale venduto (contatore)"], 96462.94)
        self.assertEqual(righe[0]["_gruppo"], "M1")

    def test_senza_lettura_precedente(self):
        righe = fc.righe_da_differenza(
            [(_voce("10", "03/07/2026 10:00", "95500,00"), None)], {})
        self.assertIsNone(righe[0]["Lettura precedente"])
        self.assertIsNone(righe[0]["Venduto dell'intervallo"])
        self.assertIn("non trovata", righe[0]["Note"])

    def test_modalita_non_cumulativa(self):
        righe = fc.righe_da_differenza(
            [(_voce("10", "03/07/2026 10:00", "120,00", modalita="PUNTUALE"), None)],
            {"M1": 95116.94})
        self.assertEqual(righe[0]["Venduto dell'intervallo"], 120.0)
        self.assertIn("PUNTUALE", righe[0]["Note"])

    def test_contatore_in_calo_segnalato(self):
        righe = fc.righe_da_differenza(
            [(_voce("10", "03/07/2026 10:00", "100,00"), None)], {"M1": 95116.94})
        self.assertIn("inferiore", righe[0]["Note"])

    def test_venduto_dall_elenco_prima_che_dal_dettaglio(self):
        self.assertEqual(fc.venduto_da(_voce("1", "", "10,00"), _dettaglio("12,00")), 10.0)
        self.assertEqual(fc.venduto_da(_voce("1", "", ""), _dettaglio("12,00")), 12.0)

    def test_divergenza_dettaglio_elenco_segnalata(self):
        righe = fc.righe_da_differenza(
            [(_voce("10", "03/07/2026 10:00", "1100,00"), _dettaglio("1150,00"))],
            {"M1": 1000.0})
        self.assertAlmostEqual(righe[0]["Venduto dell'intervallo"], 100.0)
        self.assertIn("differisce", righe[0]["Note"])

    def test_lettura_non_cumulativa_non_fa_da_base(self):
        invii = [(_voce("1", "01/07/2026 10:00", "1100,00"), None),
                 (_voce("2", "02/07/2026 10:00", "50,00", modalita="PUNTUALE"), None),
                 (_voce("3", "03/07/2026 10:00", "1300,00"), None)]
        righe = fc.righe_da_differenza(invii, {"M1": 1000.0})
        self.assertEqual(righe[2]["Lettura precedente"], 1100.0)
        self.assertAlmostEqual(righe[2]["Venduto dell'intervallo"], 200.0)

    def test_letture_precedenti_ignora_non_cumulative(self):
        voci = [_voce("1", "01/07/2026 10:00", "1100,00"),
                _voce("2", "02/07/2026 10:00", "50,00", modalita="PUNTUALE"),
                _voce("3", "03/07/2026 10:00", "1150,00")]
        precedenti = fc.letture_precedenti(voci, datetime(2026, 7, 4))
        self.assertEqual(precedenti.get("M1"), 1150.0)

    def test_modalita_dal_dettaglio(self):
        voce = {"idInvio": "10", "timeRilevazione": "03/07/2026 10:00",
                "matricolaDispositivo": "M1", "importo": "95500,00"}
        dettaglio = {"datiContabiliDA": {"venduto": "95500,00", "vendutoContante": "1,00",
                                        "incassatoNoContante": "2,00",
                                        "modalitaRilevazione": "CUMULATO"}}
        righe = fc.righe_da_grezzi([(voce, dettaglio)])
        self.assertEqual(righe[0]["Modalità"], "CUMULATO")


class TestGrezzi(unittest.TestCase):

    def test_campi_del_dettaglio(self):
        righe = fc.righe_da_grezzi([(_voce("10", "03/07/2026 10:00", "95500,00"),
                                     _dettaglio("95500,00"))])
        self.assertEqual(righe[0]["Venduto"], 95500.0)
        self.assertEqual(righe[0]["Venduto contante"], 1.0)
        self.assertEqual(righe[0]["Totale incassato"], 2.0)
        self.assertEqual(righe[0]["Caricato manuale tubi resto"], 0.0)


if __name__ == "__main__":
    unittest.main()
