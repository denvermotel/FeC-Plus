#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Parsing dei corrispettivi (funzioni pure, dati inventati sulla forma reale)."""

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_corrispettivi as fc


def _riga_rt(aliquota, imponibile, imposta, natura="", resi="+000000000000,00"):
    return {"aliquota": aliquota, "imponibile": imponibile, "imposta": imposta,
            "natura": natura, "ventilazione": "", "resi": resi,
            "annullato": "+000000000000,00", "progressivo": 1}


class TestDate(unittest.TestCase):

    def test_formato_corrispettivi(self):
        self.assertEqual(fc.data_ora("30/03/2025 00:00"), datetime(2025, 3, 30, 0, 0))

    def test_iso_e_non_valida(self):
        self.assertEqual(fc.data_ora("2026-07-10"), datetime(2026, 7, 10))
        self.assertEqual(fc.data_ora("2026-07-10T08:30:00.123Z"),
                         datetime(2026, 7, 10, 8, 30))
        self.assertIsNone(fc.data_ora("boh"))

    def test_ordine_per_data_e_non_per_stringa(self):
        voci = [{"timeRilevazione": "02/04/2025 10:00"},
                {"timeRilevazione": "30/03/2025 10:00"}]
        voci.sort(key=fc.ordine)
        self.assertEqual(voci[0]["timeRilevazione"], "30/03/2025 10:00")


class TestRegistro(unittest.TestCase):

    def test_sette_tipi(self):
        self.assertEqual(set(fc.TIPI), {"RT", "MC", "DA", "CA", "DC", "RC", "COL"})

    def test_url_dettaglio(self):
        self.assertTrue(fc.url_dettaglio("RT", {"idInvio": "123"}, "P")
                        .split("?")[0].endswith("/corrispettivi/dettaglio/RT123"))
        self.assertTrue(fc.url_dettaglio("CA", {"idInvio": "9"}, "P")
                        .split("?")[0].endswith("/dettagliocarburanti/CA9"))
        self.assertTrue(fc.url_dettaglio("DC", {"id": "77"}, "P")
                        .split("?")[0].endswith("/dc/dettaglio/77"))
        self.assertTrue(fc.url_dettaglio("RC", {"idInvio": "1", "idUnivoco": "U5"}, "P")
                        .split("?")[0].endswith("/rc/dettaglio/U5"))
        self.assertTrue(fc.url_dettaglio(
            "COL", {"idInvio": "4", "idRigaPresa": "2"}, "01234567890")
            .split("?")[0].endswith("/col/dettaglio/piva/01234567890/idInvio/4/idRigaPresa/2"))
        self.assertIsNone(fc.url_dettaglio("COL", {"idInvio": "4"}, "P"))
        self.assertIsNone(fc.url_dettaglio("RT", {}, "P"))

    def test_nome_file(self):
        self.assertEqual(fc.nome_file("01234567890", "01012026", "31032026", "RT", "M1"),
                         "01234567890_01012026-31032026_corrispettivi_M1.xlsx")
        self.assertEqual(fc.nome_file("01234567890", "01012026", "31032026", "DC", ""),
                         "01234567890_01012026-31032026_documenti_commerciali.xlsx")
        self.assertEqual(fc.nome_file("P", "01012026", "31032026", "RT", ""),
                         "P_01012026-31032026_corrispettivi_senza_matricola.xlsx")
        self.assertEqual(fc.nome_file("P", "01012026", "31032026", "CA", "A/B 1"),
                         "P_01012026-31032026_carburanti_A_B_1.xlsx")


class TestRigaPivot(unittest.TestCase):

    def test_rt_con_dettaglio(self):
        voce = {"idInvio": "1", "timeRilevazione": "30/03/2025 20:00",
                "matricolaDispositivo": "M1", "tipoDispositivo": "Registratore telematico",
                "dettaglio": True}
        dettaglio = {"datiContabiliRT_MC": [
            _riga_rt("10.00", "+000000000100,00", "+000000000010,00"),
            _riga_rt("22.00", "+000000000200,00", "+000000000044,00", resi="+000000000005,00")],
            "resi": "+000000000005,00", "annullato": "+000000000000,00"}
        r = fc.estrai_riga_pivot("RT", voce, dettaglio)
        self.assertEqual(r["iva"], {"10%": [100.0, 10.0], "22%": [200.0, 44.0]})
        self.assertEqual(r["Tot. Imponibile"], 300.0)
        self.assertEqual(r["Tot. IVA"], 54.0)
        self.assertEqual(r["Totale Corrispettivi"], 354.0)
        self.assertEqual(r["Resi"], 5.0)
        self.assertEqual(r["Data"], "30/03/2025")
        self.assertEqual(r["_gruppo"], "M1")

    def test_rt_senza_dettaglio_usa_i_totali_di_elenco(self):
        voce = {"idInvio": "1", "timeRilevazione": "30/03/2025 20:00",
                "matricolaDispositivo": "M1", "ammontareTotale": "+000000000050,00",
                "impostaTotale": "+000000000005,00"}
        r = fc.estrai_riga_pivot("RT", voce, None)
        self.assertEqual((r["Tot. Imponibile"], r["Tot. IVA"]), (50.0, 5.0))
        self.assertEqual(r["iva"], {})

    def test_dc_con_nature_e_numeri(self):
        voce = {"id": "77", "dataEmissione": "2026-09-22"}
        dettaglio = {"listaAliquota": [
            {"aliquotaIva": 0, "natura": "N1", "imponibile": 12.5, "imposta": 0,
             "resi": 0, "annulli": 1.0},
            {"aliquotaIva": 10, "natura": "", "imponibile": 100, "imposta": 10,
             "resi": 2, "annulli": 0}]}
        r = fc.estrai_riga_pivot("DC", voce, dettaglio)
        self.assertEqual(r["iva"], {"N1": [12.5, 0.0], "10%": [100.0, 10.0]})
        self.assertEqual((r["Resi"], r["Annulli"]), (2.0, 1.0))
        self.assertEqual(r["_gruppo"], "")
        self.assertEqual(r["Tipo dispositivo"], "Documenti commerciali online")

    def test_rc_usa_lista(self):
        dettaglio = {"lista": [{"aliquotaIva": "22", "imponibile": "100,00",
                                "imposta": "22,00", "natura": ""}]}
        r = fc.estrai_riga_pivot("RC", {"idInvio": "1", "dataFattura": "2026-08-01"},
                                 dettaglio)
        self.assertEqual(r["iva"], {"22%": [100.0, 22.0]})


class TestCarburanti(unittest.TestCase):

    def test_somma_benzina_e_gas(self):
        voce = {"idInvio": "9", "timeRilevazione": "01/08/2026 10:00",
                "codiceDitta": "D1", "riferimentoDal": "2026-07-01",
                "riferimentoAl": "2026-07-31"}
        dettaglio = {"datiContabili_AC": [
            {"dataRiferimento": "2026-07-01", "imponibile": "100,00", "imposta": "22,00",
             "imponibileGas": "10,00", "impostaGas": "2,20"},
            {"dataRiferimento": "2026-07-02", "imponibile": "50,00", "imposta": "11,00",
             "imponibileGas": "0,00", "impostaGas": "0,00"}]}
        r = fc.estrai_riga_ca(voce, dettaglio)
        self.assertEqual(r["Imp. benzina/gasolio"], 150.0)
        self.assertEqual(r["IVA benzina/gasolio"], 33.0)
        self.assertEqual(r["Imp. gas"], 10.0)
        self.assertAlmostEqual(r["IVA gas"], 2.2)
        self.assertAlmostEqual(r["Totale"], 195.2)
        self.assertEqual(r["_gruppo"], "D1")
        self.assertEqual(r["Periodo dal"], "01/07/2026")

    def test_annullato(self):
        self.assertTrue(fc.e_annullato_ca({"statoIdInvio": 1}))
        self.assertTrue(fc.e_annullato_ca({"statoIdInvio": "1"}))
        self.assertTrue(fc.e_annullato_ca({"statoIdInvio": 1.0}))
        self.assertTrue(fc.e_annullato_ca({"statoIdInvio": "1.0"}))
        self.assertFalse(fc.e_annullato_ca({"statoIdInvio": 0}))
        self.assertFalse(fc.e_annullato_ca({}))


if __name__ == "__main__":
    unittest.main()
