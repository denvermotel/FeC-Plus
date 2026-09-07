#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Test dell'export CSV AdE autonomo (fec_utility, senza dettaglio fatture)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_utility


def _voce() -> dict:
    return {
        "decodificaTipoInvio": "Fattura tra privati",
        "tipoDocumento": "Fattura",
        "numeroFattura": "385/A",
        "dataFattura": "2026-07-10",
        "dataAccoglienzaFile": "2026-07-10",
        "pivaEmittente": "09876543210",
        "denominazioneEmittente": "FORNITORE ALFA SRL",
        "pivaCliente": "11223344556",
        "denominazioneCliente": "CLIENTE BETA SNC",
        "imponibile": "+000000000043,55",
        "imposta": "+000000000004,35",
        "fileDownload": {"idInvio": "10000000001", "statoFile": "Consegnata"},
        "dataConsegna": "10/07/2026",
    }


class TestElencoFattureCsvAde(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.blocchi = []
        self.voci = [_voce()]
        originale = fec_utility._lista_fatture

        def finta(auth, tipo, dal, al):
            self.blocchi.append((dal, al))
            return list(self.voci)

        fec_utility._lista_fatture = finta
        self.addCleanup(lambda: setattr(fec_utility, "_lista_fatture", originale))

    def test_scrive_il_csv_e_ne_ritorna_il_percorso(self):
        percorso = fec_utility.elenco_fatture_csv_ade(
            None, "CFCLIENTE", "01234567890", "ricevute_ricezione",
            "01072026", "31072026", dest_dir=self.tmp.name, sottocartella=False,
            log=lambda *a: None)
        self.assertTrue(os.path.isfile(percorso))
        self.assertEqual(os.path.basename(percorso),
                         "01234567890_01072026-31072026_ricevute.csv")
        with open(percorso, encoding="utf-8", newline="") as fh:
            testo = fh.read()
        self.assertTrue(testo.startswith('"Tipo fattura";'))
        self.assertTrue(testo.endswith("\r\n"))

    def test_prefisso_dal_cf_se_la_piva_manca(self):
        percorso = fec_utility.elenco_fatture_csv_ade(
            None, "CFCLIENTE", "", "emesse", "01072026", "31072026",
            dest_dir=self.tmp.name, sottocartella=False, log=lambda *a: None)
        self.assertEqual(os.path.basename(percorso),
                         "CFCLIENTE_01072026-31072026_emesse.csv")

    def test_periodo_lungo_spezzato_ma_file_unico(self):
        percorso = fec_utility.elenco_fatture_csv_ade(
            None, "CFCLIENTE", "", "emesse", "01012026", "31122026",
            dest_dir=self.tmp.name, sottocartella=False, log=lambda *a: None)
        self.assertGreater(len(self.blocchi), 1)
        with open(percorso, encoding="utf-8", newline="") as fh:
            righe = fh.read().split("\r\n")[:-1]
        self.assertEqual(len(righe), 1 + len(self.blocchi))

    def test_nessuna_fattura_solleva_nessun_dato_senza_creare_file(self):
        self.voci = []
        with self.assertRaises(fec_utility.NessunDato):
            fec_utility.elenco_fatture_csv_ade(
                None, "CFCLIENTE", "", "emesse", "01072026", "31072026",
                dest_dir=self.tmp.name, sottocartella=False, log=lambda *a: None)
        self.assertEqual(os.listdir(self.tmp.name), [])


if __name__ == "__main__":
    unittest.main()
