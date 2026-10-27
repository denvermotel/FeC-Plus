#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""File che il portale rifiuta per un momento (HTTP 304/503): riprovati a fine elenco."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_download
from _finti import Auth, ProgressoSpia, Risposta, fattura


def _di(n):
    return f"/file/T{n}?"


class SessioneStati:
    """Elenco di n fatture; per ogni file una coda di stati HTTP, consumata a ogni GET
    (l'ultimo stato si ripete)."""

    def __init__(self, stati_per_file):
        self.payload = {"fatture": [fattura(i + 1) for i in range(len(stati_per_file))]}
        self.stati = [list(s) for s in stati_per_file]
        self.url = []

    def get(self, url, **kwargs):
        self.url.append(url)
        if len(self.url) == 1:
            return Risposta(payload=self.payload)
        indice = next(i for i, f in enumerate(self.payload["fatture"])
                      if _di(i + 1) in url)
        coda = self.stati[indice]
        stato = coda.pop(0) if len(coda) > 1 else coda[0]
        return Risposta(status=stato, filename=f"F{indice + 1}.xml")


class TestRitentaAFineElenco(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        attesa = patch.object(fec_download.time, "sleep")
        self.sleep = attesa.start()
        self.addCleanup(attesa.stop)

    def _scarica(self, stati, **extra):
        self.sessione = SessioneStati(stati)
        self.righe = []
        self.spia = ProgressoSpia()
        self.esiti = {}
        return fec_download._scarica_da_lista(
            Auth(self.sessione), "http://x/lista", self.tmp, log=self.righe.append,
            escludi_scartate_pa=False, scarica_metadati=False, progresso=self.spia,
            esiti_out=self.esiti, **extra)

    def test_304_riprovato_dopo_le_altre(self):
        esito = self._scarica([[304, 200], [200]])
        self.assertEqual(esito, (2, 0))
        self.assertEqual(sorted(os.listdir(self.tmp)), ["F1.xml", "F2.xml"])
        # la seconda fattura passa prima del nuovo tentativo sulla prima
        self.assertIn(_di(2), self.sessione.url[2])
        self.assertIn(_di(1), self.sessione.url[3])
        self.assertEqual(self.spia.solo("esito"), [("esito", fec_download.ESITO_OK)] * 2)
        self.assertIsNone(self.esiti.get("errori"))
        self.assertTrue(any("alla fine" in r for r in self.righe))

    def test_503_riprovato(self):
        self.assertEqual(self._scarica([[503, 200]]), (1, 0))

    def test_errore_dopo_tutti_i_giri(self):
        esito = self._scarica([[304], [200]])
        self.assertEqual(esito, (1, 0))
        giri = len(fec_download._PAUSE_RITENTATIVI)
        self.assertEqual(sum(_di(1) in u for u in self.sessione.url),
                         1 + giri)
        self.assertEqual(self.spia.solo("esito"), [("esito", fec_download.ESITO_OK),
                                                   ("esito", fec_download.ESITO_ERRORE)])
        self.assertEqual(self.esiti.get("errori"), 1)
        self.assertTrue(any("non scaricata (HTTP 304)" in r for r in self.righe))

    def test_404_non_si_riprova(self):
        self._scarica([[404, 200]])
        self.assertEqual(len(self.sessione.url), 2)
        self.sleep.assert_not_called()
        self.assertEqual(self.esiti.get("errori"), 1)

    def test_annullamento_durante_l_attesa(self):
        class Annulla(Exception):
            pass

        class Controllo:
            def __init__(self):
                self.n = 0

            def check(self):
                self.n += 1
                if self.n > 1:   # il primo controllo è quello prima della fattura
                    raise Annulla

        with self.assertRaises(Annulla):
            self._scarica([[304, 200]], control=Controllo())
        self.assertEqual(len(self.sessione.url), 2)

    def test_ritenuta_controllata_anche_al_nuovo_tentativo(self):
        self.sessione = None
        senza = (b'<?xml version="1.0"?><FatturaElettronica><FatturaElettronicaBody>'
                 b'<DatiGenerali><DatiGeneraliDocumento><Numero>1</Numero>'
                 b'</DatiGeneraliDocumento></DatiGenerali></FatturaElettronicaBody>'
                 b'</FatturaElettronica>')
        originale = SessioneStati.get

        def get(sessione, url, **kwargs):
            r = originale(sessione, url, **kwargs)
            if r.status_code == 200 and len(sessione.url) > 1:
                r.content = senza
            return r

        with patch.object(SessioneStati, "get", get):
            esito = self._scarica([[304, 200]], solo_ritenuta=True)
        self.assertEqual(esito, (0, 0))
        self.assertEqual(self.esiti.get("senza_ritenuta"), 1)
        self.assertEqual(os.listdir(self.tmp), [])


if __name__ == "__main__":
    unittest.main()
