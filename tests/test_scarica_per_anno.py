#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Download con sottocartella per anno della data documento e contatori degli esiti."""

import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_download as fd
import fec_queue as fq
from _finti import Auth, SessioneElenco, fattura


class TestPerAnno(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_file_e_metadati_nella_cartella_dell_anno(self):
        elenco = [fattura(1, dataFattura="2025-12-30"), fattura(2, dataFattura="2026-01-02"),
                  fattura(3)]
        fd._scarica_da_lista(Auth(SessioneElenco({"fatture": elenco})), "http://x/lista",
                             self.tmp, log=lambda *_: None, escludi_scartate_pa=False,
                             per_anno=True)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["2025", "2026", "senza data"])
        self.assertEqual(len(os.listdir(os.path.join(self.tmp, "2025"))), 2)  # xml + metadato

    def test_senza_per_anno_tutto_nella_cartella(self):
        fd._scarica_da_lista(Auth(SessioneElenco({"fatture": [fattura(1, dataFattura="2025-12-30")]})),
                             "http://x/lista", self.tmp, log=lambda *_: None,
                             escludi_scartate_pa=False)
        self.assertEqual(len(os.listdir(self.tmp)), 2)
        self.assertFalse(os.path.isdir(os.path.join(self.tmp, "2025")))


class TestContatori(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_saltati_errori_in_attesa(self):
        elenco = [fattura(1, fileDownload={"fileDownload": 2}), fattura(2), fattura(3),
                  fattura(4)]
        esiti = {}
        with unittest.mock.patch.object(fd, "_e_scartata_pa",
                                        lambda _a, ff, _l: ff == "T2"):
            fd._scarica_da_lista(Auth(SessioneElenco({"fatture": elenco}, esiti_file=[500])),
                                 "http://x/lista", self.tmp, log=lambda *_: None,
                                 escludi_scartate_pa=True, esiti_out=esiti)
        self.assertEqual(esiti, {"in_attesa": 1, "saltati": 1, "errori": 1})

    def test_download_result_e_somma(self):
        esito = fd.scarica_emesse(
            Auth(SessioneElenco({"fatture": [fattura(1, fileDownload={"fileDownload": 2}),
                                             fattura(2)]})),
            "01072026", "31072026", "CF", dest_dir=self.tmp, sottocartella=False,
            log=lambda *_: None, escludi_scartate_pa=False)
        self.assertEqual((esito.fatture, esito.in_attesa, esito.saltati, esito.errori),
                         (1, 1, 0, 0))
        somma = fq._somma_download([fd.DownloadResult("CF", "c", 1, 1, set(), 1, 2, 3),
                                    fd.DownloadResult("CF", "c", 2, 2, set(), 4, 5, 6)])
        self.assertEqual((somma.saltati, somma.errori, somma.in_attesa), (5, 7, 9))

    def test_per_anno_passa_da_esegui_richiesta(self):
        fd.scarica_emesse(Auth(SessioneElenco({"fatture": [fattura(1, dataFattura="2026-07-01")]})),
                          "01072026", "31072026", "CF", dest_dir=self.tmp, sottocartella=False,
                          log=lambda *_: None, escludi_scartate_pa=False, per_anno=True)
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "2026")))


if __name__ == "__main__":
    unittest.main()
