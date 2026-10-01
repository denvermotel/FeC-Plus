#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Una fattura estera passata dallo SdI compare sia fra le emesse sia fra le
transfrontaliere emesse: la seconda copia non va scaricata."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_download as fd
import fec_queue as fq
from _finti import Auth, SessioneElenco, fattura


def _con_id(n, id_invio):
    return fattura(n, fileDownload={"idInvio": id_invio, "fileDownload": 1})


class TestScaricaDaListaIdInvio(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_raccoglie_gli_id_dell_elenco(self):
        ids = set()
        fd._scarica_da_lista(Auth(SessioneElenco({"fatture": [
            _con_id(1, "100"), _con_id(2, "200"), fattura(3)]})),
            "http://x/lista", self.tmp, log=lambda *_: None,
            escludi_scartate_pa=False, id_invio_out=ids)
        self.assertEqual(ids, {"100", "200"})

    def test_salta_gli_id_gia_visti(self):
        sessione = SessioneElenco({"fatture": [_con_id(1, "100"), _con_id(2, "300"),
                                               fattura(3)]})
        righe = []
        esito = fd._scarica_da_lista(Auth(sessione), "http://x/lista", self.tmp,
                                     log=righe.append, escludi_scartate_pa=False,
                                     escludi_id_invio={"100"})
        self.assertEqual(esito, (2, 2))
        self.assertEqual(len(sessione.url), 1 + 2 * 2)
        self.assertTrue(any("già presenti tra le emesse" in r for r in righe))

    def test_senza_id_non_si_salta_nulla(self):
        esito = fd._scarica_da_lista(Auth(SessioneElenco({"fatture": [fattura(1)]})),
                                     "http://x/lista", self.tmp, log=lambda *_: None,
                                     escludi_scartate_pa=False, escludi_id_invio={"100"})
        self.assertEqual(esito, (1, 1))

    def test_download_result_espone_gli_id(self):
        esito = fd.scarica_transfrontaliere_emesse(
            Auth(SessioneElenco({"fatture": [_con_id(1, "100"), _con_id(2, "200")]})),
            "01072026", "31072026", "CFCLIENTE", dest_dir=self.tmp, sottocartella=False,
            log=lambda *_: None, escludi_scartate_pa=False, escludi_id_invio={"100"})
        self.assertEqual(esito.fatture, 1)
        self.assertEqual(esito.id_invio_elenco, {"100", "200"})


class TestQueueIdInvio(unittest.TestCase):

    def setUp(self):
        self.chiamate = []

        def finta(auth, dal, al, log=print, **kw):
            self.chiamate.append(kw)
            return fd.DownloadResult("CF", "/tmp", 1, 1, {f"ID{dal}"})

        originale = fq.TIPI["emesse"]
        fq.TIPI["emesse"] = fq._Spec(finta, "%d%m%Y", "download")
        self.addCleanup(fq.TIPI.__setitem__, "emesse", originale)

    def test_unisce_gli_id_dei_blocchi_e_inoltra_l_esclusione(self):
        esito = fq.esegui_richiesta(None, "emesse", dal="01012026", al="31052026",
                                    log=lambda *_: None, cf_cliente="CF",
                                    escludi_id_invio={"X"})
        self.assertEqual(esito.id_invio_elenco, {"ID01012026", "ID01042026"})
        self.assertEqual(len(self.chiamate), 2)
        self.assertTrue(all(k["escludi_id_invio"] == {"X"} for k in self.chiamate))

    def test_download_result_senza_id_resta_compatibile(self):
        self.assertEqual(fd.DownloadResult("CF", "/tmp", 0, 0).id_invio_elenco, set())


if __name__ == "__main__":
    unittest.main()
