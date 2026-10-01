#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Avvisi AdE (`messages[]`) negli elenchi: non vanno scambiati per elenchi vuoti."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_download
import fec_utility
from _finti import Auth, SessioneElenco, fattura

_NON_DISPONIBILI = [{"severity": "WARNING", "message": "Dati momentaneamente non disponibili."}]
_NON_TROVATI = [{"severity": "WARNING", "message": "Documenti non trovati"}]


class TestAvvisoAde(unittest.TestCase):

    def test_warning_restituisce_il_testo(self):
        self.assertEqual(fec_download.avviso_ade({"messages": _NON_DISPONIBILI}),
                         "Dati momentaneamente non disponibili.")

    def test_info_e_assenza_restituiscono_none(self):
        self.assertIsNone(fec_download.avviso_ade(
            {"messages": [{"severity": "INFO", "message": "ok"}]}))
        self.assertIsNone(fec_download.avviso_ade({}))
        self.assertIsNone(fec_download.avviso_ade(None))


class TestControllaAvvisoElenco(unittest.TestCase):

    def test_elenco_vuoto_con_avviso_e_un_errore(self):
        with self.assertRaises(fec_download.DownloadError) as ctx:
            fec_download.controlla_avviso_elenco({"messages": _NON_DISPONIBILI}, [],
                                                 log=lambda *_: None)
        self.assertIn("momentaneamente non disponibili", str(ctx.exception))

    def test_documenti_non_trovati_e_un_elenco_vuoto_normale(self):
        fec_download.controlla_avviso_elenco({"messages": _NON_TROVATI}, [],
                                             log=lambda *_: None)

    def test_elenco_non_vuoto_con_avviso_va_nel_log(self):
        righe = []
        fec_download.controlla_avviso_elenco({"messages": _NON_DISPONIBILI}, [{}],
                                             log=righe.append)
        self.assertEqual(len(righe), 1)
        self.assertIn("momentaneamente non disponibili", righe[0])


class TestAvvisoNelleListe(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_scarica_da_lista_solleva(self):
        auth = Auth(SessioneElenco({"fatture": [], "messages": _NON_DISPONIBILI}))
        with self.assertRaises(fec_download.DownloadError):
            fec_download._scarica_da_lista(auth, "http://x/lista", self.tmp,
                                           log=lambda *_: None, escludi_scartate_pa=False)

    def test_scarica_da_lista_periodo_vuoto_normale(self):
        auth = Auth(SessioneElenco({"fatture": [], "messages": _NON_TROVATI}))
        self.assertEqual(fec_download._scarica_da_lista(
            auth, "http://x/lista", self.tmp, log=lambda *_: None,
            escludi_scartate_pa=False), (0, 0))

    def test_lista_fatture_utility_solleva(self):
        auth = Auth(SessioneElenco({"fatture": [], "messages": _NON_DISPONIBILI}))
        with self.assertRaises(fec_download.DownloadError):
            fec_utility._lista_fatture(auth, "emesse", "01072026", "31072026",
                                       log=lambda *_: None)

    def test_lista_fatture_utility_restituisce_le_voci(self):
        auth = Auth(SessioneElenco({"fatture": [fattura(1)]}))
        self.assertEqual(len(fec_utility._lista_fatture(
            auth, "emesse", "01072026", "31072026", log=lambda *_: None)), 1)


if __name__ == "__main__":
    unittest.main()
