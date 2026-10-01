#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Elenchi corrispettivi: URL, avvisi AdE, frazionamento degli elenchi troncati."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_corrispettivi as fc
import fec_download
from _finti import Auth, SessioneRotte


class TestElencoBlocco(unittest.TestCase):

    def test_rt_restituisce_voci_e_totale(self):
        sessione = SessioneRotte([("tipoCorrispettivo/RT", {
            "corrispettivi": [{"idInvio": "1"}], "totaleCorrispettivi": 1})])
        voci, totale = fc.elenco_blocco(Auth(sessione), "RT", "01072026", "31072026",
                                        "01234567890", log=lambda *_: None)
        self.assertEqual((len(voci), totale), (1, 1))
        self.assertIn("/sintesi/elenco/dal/01072026/al/31072026/piva/01234567890/"
                      "tipoCorrispettivo/RT", sessione.url[0])

    def test_dc_usa_elenco_e_totale_elementi(self):
        sessione = SessioneRotte([("/dc/ricerca/", {
            "elenco": [{"id": "1"}, {"id": "2"}], "totaleElementi": "5"})])
        voci, totale = fc.elenco_blocco(Auth(sessione), "DC", "01072026", "31072026",
                                        "P", log=lambda *_: None)
        self.assertEqual((len(voci), totale), (2, 5))

    def test_totale_assente(self):
        sessione = SessioneRotte([("/rc/ricerca/", {"elenco": []})])
        self.assertEqual(fc.elenco_blocco(Auth(sessione), "RC", "01072026", "31072026",
                                          "P", log=lambda *_: None), ([], None))

    def test_avviso_ade_con_elenco_vuoto(self):
        sessione = SessioneRotte([("tipoCorrispettivo/RT", {
            "corrispettivi": [], "messages": [
                {"severity": "ERROR", "message": "Servizio non disponibile"}]})])
        with self.assertRaises(fec_download.DownloadError):
            fc.elenco_blocco(Auth(sessione), "RT", "01072026", "31072026", "P",
                             log=lambda *_: None)

    def test_risposta_non_json(self):
        with self.assertRaises(fec_download.DownloadError):
            fc.elenco_blocco(Auth(SessioneRotte([])), "RT", "01072026", "31072026",
                             "P", log=lambda *_: None)

    def test_dettaglio_none_su_errore(self):
        self.assertIsNone(fc.dettaglio(Auth(SessioneRotte([])), "RT",
                                       {"idInvio": "1"}, "P"))
        self.assertEqual(fc.dettaglio(Auth(SessioneRotte([("/dettaglio/RT1", {"a": 1})])),
                                      "RT", {"idInvio": "1"}, "P"), {"a": 1})


class TestElencoCompleto(unittest.TestCase):

    def test_non_troncato_una_sola_chiamata(self):
        chiamate = []

        def scarica(d, a):
            chiamate.append((d, a))
            return [{"x": 1}], 1

        self.assertEqual(len(fc.elenco_completo(scarica, "01012026", "31032026", "RT",
                                                log=lambda *_: None)), 1)
        self.assertEqual(chiamate, [("01012026", "31032026")])

    def test_troncato_si_rifa_mese_per_mese(self):
        def scarica(d, a):
            if (d, a) == ("01012026", "31032026"):
                return [{"n": 0}] * 2, 3        # troncato: 2 su 3
            return [{"n": d}], 1

        avvisi = []
        voci = fc.elenco_completo(scarica, "01012026", "31032026", "RT",
                                  log=lambda *_: None, avvisi=avvisi)
        self.assertEqual([v["n"] for v in voci], ["01012026", "01022026", "01032026"])
        self.assertEqual(avvisi, [])

    def test_troncato_anche_a_mesi_si_rifa_a_settimane(self):
        def scarica(d, a):
            if (d, a) == ("01012026", "31012026"):
                return [{}], 2                   # gennaio intero troncato
            return [{"d": d}], 1

        voci = fc.elenco_completo(scarica, "01012026", "31012026", "RT",
                                  log=lambda *_: None)
        self.assertEqual([v["d"] for v in voci],
                         ["01012026", "08012026", "15012026", "22012026", "29012026"])

    def test_troncato_fino_in_fondo_produce_un_avviso(self):
        avvisi = []
        voci = fc.elenco_completo(lambda d, a: ([{}], 9), "01012026", "07012026", "RT",
                                  log=lambda *_: None, avvisi=avvisi)
        self.assertEqual(len(voci), 1)
        self.assertEqual(len(avvisi), 1)
        self.assertIn("1 su 9", avvisi[0])

    def test_sottoblocco_senza_elenco_non_blocca_gli_altri(self):
        def scarica(d, a):
            if (d, a) == ("01012026", "31032026"):
                return [{}] * 2, 3
            if d == "01022026":
                raise fec_download.DownloadError("avviso AdE")
            return [{"n": d}], 1

        avvisi = []
        voci = fc.elenco_completo(scarica, "01012026", "31032026", "RT",
                                  log=lambda *_: None, avvisi=avvisi)
        self.assertEqual([v["n"] for v in voci], ["01012026", "01032026"])
        self.assertEqual(len(avvisi), 1)
        self.assertIn("01022026-28022026", avvisi[0])
        self.assertIn("elenco non ottenuto", avvisi[0])


if __name__ == "__main__":
    unittest.main()
