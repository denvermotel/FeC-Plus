#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Fatture col file ancora in preparazione presso l'AdE (fileDownload = 2)."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_download
from _finti import Auth, ProgressoSpia, SessioneElenco, fattura


class TestPredisposizione(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_riconosce_il_valore_2_anche_come_stringa(self):
        self.assertTrue(fec_download._in_predisposizione(
            fattura(1, fileDownload={"fileDownload": 2})))
        self.assertTrue(fec_download._in_predisposizione(
            fattura(1, fileDownload={"fileDownload": "2"})))
        self.assertFalse(fec_download._in_predisposizione(
            fattura(1, fileDownload={"fileDownload": 1})))
        self.assertFalse(fec_download._in_predisposizione(fattura(1)))

    def test_salta_senza_chiamare_il_file(self):
        sessione = SessioneElenco({"fatture": [
            fattura(1, fileDownload={"fileDownload": 2}),
            fattura(2, fileDownload={"fileDownload": 1})]})
        spia = ProgressoSpia()
        righe = []
        esito = fec_download._scarica_da_lista(
            Auth(sessione), "http://x/lista", self.tmp, log=righe.append,
            escludi_scartate_pa=False, progresso=spia)
        self.assertEqual(esito, (1, 1))
        # elenco + file e metadati della sola fattura 2
        self.assertEqual(len(sessione.url), 3)
        self.assertEqual(spia.solo("esito"), [("esito", fec_download.ESITO_SALTATO),
                                              ("esito", fec_download.ESITO_OK)])
        self.assertTrue(any("72 ore" in r for r in righe))
        self.assertTrue(any("non ancora disponibil" in r for r in righe))


if __name__ == "__main__":
    unittest.main()
