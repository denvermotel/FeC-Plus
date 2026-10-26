#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Download con «solo fatture con ritenuta d'acconto»."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_download
import fec_queue
from _finti import Auth, ProgressoSpia, Risposta, fattura

CON = (b'<?xml version="1.0"?><FatturaElettronica><FatturaElettronicaBody><DatiGenerali>'
       b'<DatiGeneraliDocumento><DatiRitenuta><TipoRitenuta>RT01</TipoRitenuta>'
       b'<ImportoRitenuta>200.00</ImportoRitenuta><AliquotaRitenuta>20.00</AliquotaRitenuta>'
       b'</DatiRitenuta></DatiGeneraliDocumento></DatiGenerali></FatturaElettronicaBody>'
       b'</FatturaElettronica>')
SENZA = (b'<?xml version="1.0"?><FatturaElettronica><FatturaElettronicaBody><DatiGenerali>'
         b'<DatiGeneraliDocumento><Numero>1</Numero></DatiGeneraliDocumento></DatiGenerali>'
         b'</FatturaElettronicaBody></FatturaElettronica>')


class SessioneContenuti:
    """Elenco, poi per ogni fattura il file con il contenuto indicato e i metadati."""

    def __init__(self, contenuti):
        self.payload = {"fatture": [fattura(i + 1) for i in range(len(contenuti))]}
        self.contenuti = list(contenuti)
        self.url = []
        self.n_file = 0

    def get(self, url, **kwargs):
        self.url.append(url)
        if len(self.url) == 1:
            return Risposta(payload=self.payload)
        if "FILE_METADATI" in url:
            return Risposta(contenuto=b"<meta/>", filename=f"M{self.n_file}_metadato.xml")
        contenuto = self.contenuti[self.n_file]
        self.n_file += 1
        return Risposta(contenuto=contenuto, filename=f"F{self.n_file}.xml")


class TestSoloRitenuta(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _scarica(self, contenuti, **extra):
        sessione = SessioneContenuti(contenuti)
        self.righe = []
        esito = fec_download._scarica_da_lista(
            Auth(sessione), "http://x/lista", self.tmp, log=self.righe.append,
            escludi_scartate_pa=False, **extra)
        return sessione, esito

    def test_salva_solo_le_fatture_con_ritenuta(self):
        sessione, esito = self._scarica([SENZA, CON, SENZA], solo_ritenuta=True)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["F2.xml", "F2.xml_metadato.xml"])
        self.assertEqual(esito, (1, 1))
        # niente metadati per le fatture scartate
        self.assertEqual(sum("FILE_METADATI" in u for u in sessione.url), 1)

    def test_le_scartate_sono_saltate_sul_nastro(self):
        spia = ProgressoSpia()
        esiti = {}
        self._scarica([SENZA, CON], solo_ritenuta=True, progresso=spia, esiti_out=esiti)
        self.assertEqual(spia.solo("esito"), [("esito", fec_download.ESITO_SALTATO),
                                              ("esito", fec_download.ESITO_OK)])
        self.assertEqual(esiti.get("senza_ritenuta"), 1)
        self.assertIsNone(esiti.get("saltati"))

    def test_file_illeggibile_si_tiene_con_un_avviso(self):
        self._scarica([b"\x30\x82\x00\x10non una busta"], solo_ritenuta=True,
                      scarica_metadati=False)
        self.assertEqual(os.listdir(self.tmp), ["F1.xml"])
        self.assertTrue(any("ritenuta" in r.lower() and "verific" in r.lower()
                            for r in self.righe))

    def test_csv_ade_solo_con_le_fatture_salvate(self):
        voci = []
        self._scarica([SENZA, CON], solo_ritenuta=True, scarica_metadati=False,
                      voci_out=voci)
        self.assertEqual(len(voci), 1)

    def test_messe_a_disposizione_escluse_dal_filtro(self):
        # Scaricare il file di una messa a disposizione ne registra la presa visione:
        # scaricarlo per poi scartarlo fisserebbe la ricezione di un documento che
        # l'utente non ha in cartella.
        sessione = SessioneContenuti([SENZA, CON])
        righe = []
        esito = fec_download.scarica_messe_a_disposizione(
            Auth(sessione), "01012026", "31012026", "RSSMRA80A01H501U",
            dest_dir=self.tmp, sottocartella=False, log=righe.append,
            escludi_scartate_pa=False, scarica_metadati=False, solo_ritenuta=True)
        self.assertEqual(esito.fatture, 2)
        self.assertTrue(any("presa visione" in r for r in righe))

    def test_risultato_conta_le_fatture_senza_ritenuta(self):
        sessione = SessioneContenuti([SENZA, SENZA, CON])
        esito = fec_download.scarica_emesse(
            Auth(sessione), "01012026", "31012026", "RSSMRA80A01H501U",
            dest_dir=self.tmp, sottocartella=False, log=lambda _m: None,
            escludi_scartate_pa=False, scarica_metadati=False, solo_ritenuta=True)
        self.assertEqual((esito.fatture, esito.senza_ritenuta, esito.saltati), (1, 2, 0))

    def test_xml_con_codifica_sconosciuta_non_interrompe(self):
        strano = b'<?xml version="1.0" encoding="x-inesistente"?><a/>'
        self._scarica([strano, CON], solo_ritenuta=True, scarica_metadati=False)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["F1.xml", "F2.xml"])

    def test_senza_filtro_salva_tutto(self):
        self._scarica([SENZA, CON], scarica_metadati=False)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["F1.xml", "F2.xml"])

    def test_funzione_pubblica_e_coda_passano_l_opzione(self):
        sessione = SessioneContenuti([SENZA, CON])
        esito = fec_download.scarica_emesse(
            Auth(sessione), "01012026", "31012026", "RSSMRA80A01H501U",
            dest_dir=self.tmp, sottocartella=False, log=lambda _m: None,
            escludi_scartate_pa=False, scarica_metadati=False, solo_ritenuta=True)
        self.assertEqual(esito.fatture, 1)
        kw = fec_queue._kwargs_richiesta(fec_queue.Richiesta("emesse", solo_ritenuta=True))
        self.assertIs(kw["solo_ritenuta"], True)
        kw = fec_queue._kwargs_richiesta(fec_queue.Richiesta("bolli", solo_ritenuta=True))
        self.assertNotIn("solo_ritenuta", kw)


if __name__ == "__main__":
    unittest.main()
