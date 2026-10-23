#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Metadati delle fatture: scaricati di default, saltabili con `scarica_metadati=False`."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_download
import fec_queue
from _finti import Auth, SessioneElenco, fattura


class TestMetadatiOpzionali(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _metadati_su_disco(self):
        return [f for f in os.listdir(self.tmp) if f.endswith("_metadato.xml")]

    def _da_lista(self, **extra):
        sessione = SessioneElenco({"fatture": [fattura(1), fattura(2)]})
        esito = fec_download._scarica_da_lista(
            Auth(sessione), "http://x/lista", self.tmp, log=lambda _m: None,
            escludi_scartate_pa=False, **extra)
        return sessione, esito

    def test_di_default_scarica_file_e_metadati(self):
        sessione, esito = self._da_lista()
        self.assertEqual(esito, (2, 2))
        self.assertEqual(len(sessione.url), 5)       # elenco + 2 x (file e metadati)
        self.assertEqual(len(self._metadati_su_disco()), 2)

    def test_senza_metadati_una_sola_chiamata_per_fattura(self):
        sessione, esito = self._da_lista(scarica_metadati=False)
        self.assertEqual(esito, (2, 0))
        self.assertEqual(len(sessione.url), 3)       # elenco + 2 file
        self.assertEqual(self._metadati_su_disco(), [])

    def test_senza_metadati_il_nastro_conta_comunque_un_esito_per_fattura(self):
        from _finti import ProgressoSpia
        spia = ProgressoSpia()
        self._da_lista(scarica_metadati=False, progresso=spia)
        self.assertEqual(spia.solo("esito"), [("esito", fec_download.ESITO_OK)] * 2)

    def test_funzione_pubblica_inoltra_l_opzione(self):
        sessione = SessioneElenco({"fatture": [fattura(1), fattura(2)]})
        righe = []
        esito = fec_download.scarica_emesse(
            Auth(sessione), "01012026", "31012026", "RSSMRA80A01H501U",
            dest_dir=self.tmp, sottocartella=False, log=righe.append,
            escludi_scartate_pa=False, scarica_metadati=False)
        self.assertEqual((esito.fatture, esito.metadati), (2, 0))
        self.assertFalse(any("Metadati scaricati" in r for r in righe))
        self.assertEqual(self._metadati_su_disco(), [])

    def test_richiesta_passa_l_opzione_solo_ai_download(self):
        kw = fec_queue._kwargs_richiesta(fec_queue.Richiesta("emesse", scarica_metadati=False))
        self.assertIs(kw["scarica_metadati"], False)
        kw = fec_queue._kwargs_richiesta(fec_queue.Richiesta("emesse"))
        self.assertIs(kw["scarica_metadati"], True)
        kw = fec_queue._kwargs_richiesta(fec_queue.Richiesta("bolli", scarica_metadati=False))
        self.assertNotIn("scarica_metadati", kw)


if __name__ == "__main__":
    unittest.main()
