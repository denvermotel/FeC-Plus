#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Test del canale di avanzamento `Progresso` (nessuna rete, nessuna GUI)."""

import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_download


class TestProgressoBase(unittest.TestCase):
    """La classe base è un osservatore inerte: la libreria chiama sempre,
    chi non guarda non paga."""

    def test_tutti_i_metodi_esistono_e_non_sollevano(self):
        p = fec_download.Progresso()
        p.fase("Emesse", 1, 3)
        p.totale(10)
        p.esito(fec_download.ESITO_OK)
        p.messaggio("ciao")
        p.conclusa()
        p.conclusa(annullato=True)

    def test_i_metodi_ritornano_none(self):
        p = fec_download.Progresso()
        self.assertIsNone(p.totale(1))
        self.assertIsNone(p.esito(fec_download.ESITO_ERRORE))

    def test_costanti_esito_distinte(self):
        valori = {fec_download.ESITO_OK,
                  fec_download.ESITO_SALTATO,
                  fec_download.ESITO_ERRORE}
        self.assertEqual(len(valori), 3)


class ProgressoSpia(fec_download.Progresso):
    """Registra la sequenza di eventi ricevuti, per poterla asserire."""

    def __init__(self):
        self.eventi = []

    def fase(self, etichetta, indice, totale_fasi):
        self.eventi.append(("fase", etichetta, indice, totale_fasi))

    def totale(self, n):
        self.eventi.append(("totale", n))

    def esito(self, tipo):
        self.eventi.append(("esito", tipo))

    def messaggio(self, testo):
        self.eventi.append(("messaggio", testo))

    def conclusa(self, annullato=False):
        self.eventi.append(("conclusa", annullato))

    def solo(self, *tipi):
        return [e for e in self.eventi if e[0] in tipi]


class _Risposta:
    """Risposta HTTP finta: nessuna rete nei test."""

    def __init__(self, payload=None, status=200, contenuto=b"<xml/>", filename="F.xml"):
        self._payload = payload
        self.status_code = status
        self.content = contenuto
        self.headers = {"content-disposition": f"filename={filename}"}

    def json(self):
        if self._payload is None:
            raise ValueError("non JSON")
        return self._payload


class _Sessione:
    """Sessione finta: la prima GET restituisce l'elenco, le successive i file.
    `esiti_file` e' consumata in ordine: 200 = file scaricato, 500 = errore."""

    def __init__(self, elenco, esiti_file):
        self.elenco = elenco
        self.esiti_file = list(esiti_file)
        self.chiamate = 0

    def get(self, url, **kwargs):
        self.chiamate += 1
        if self.chiamate == 1:
            return _Risposta(payload={"fatture": self.elenco})
        stato = self.esiti_file.pop(0) if self.esiti_file else 200
        return _Risposta(status=stato)


class _Auth:
    def __init__(self, sessione):
        self.session = sessione
        self.headers = {}


def _fattura(n):
    return {"tipoInvio": "T", "idFattura": str(n)}


class TestEventiScaricaDaLista(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_annuncia_il_totale_e_un_esito_per_fattura(self):
        auth = _Auth(_Sessione([_fattura(1), _fattura(2)], [200, 200, 200, 200]))
        spia = ProgressoSpia()
        fec_download._scarica_da_lista(
            auth, "http://x/lista", self.tmp, log=lambda *_: None,
            escludi_scartate_pa=False, progresso=spia)
        self.assertIn(("totale", 2), spia.eventi)
        self.assertEqual(spia.solo("esito"),
                         [("esito", fec_download.ESITO_OK)] * 2)

    def test_messaggio_prima_di_chiedere_l_elenco(self):
        auth = _Auth(_Sessione([], []))
        spia = ProgressoSpia()
        fec_download._scarica_da_lista(
            auth, "http://x/lista", self.tmp, log=lambda *_: None,
            escludi_scartate_pa=False, progresso=spia)
        self.assertEqual(spia.eventi[0][0], "messaggio")

    def test_elenco_vuoto_annuncia_totale_zero(self):
        auth = _Auth(_Sessione([], []))
        spia = ProgressoSpia()
        fec_download._scarica_da_lista(
            auth, "http://x/lista", self.tmp, log=lambda *_: None,
            escludi_scartate_pa=False, progresso=spia)
        self.assertIn(("totale", 0), spia.eventi)

    def test_file_non_scaricato_produce_un_esito_errore(self):
        # La GET del file fattura torna 500. `_get_con_retry` ritenta solo sugli
        # errori di CONNESSIONE, non sugli status HTTP: la Response 500 arriva
        # quindi al ramo `else` e la fattura conta come errore.
        auth = _Auth(_Sessione([_fattura(1)], [500]))
        spia = ProgressoSpia()
        fec_download._scarica_da_lista(
            auth, "http://x/lista", self.tmp, log=lambda *_: None,
            escludi_scartate_pa=False, progresso=spia)
        self.assertEqual(spia.solo("esito"),
                         [("esito", fec_download.ESITO_ERRORE)])

    def test_il_totale_e_quello_dopo_il_filtro_controparte(self):
        # Due fatture, una sola della controparte cercata: le tacche devono
        # essere quelle che verranno davvero tentate.
        elenco = [dict(_fattura(1), pivaCliente="11111111111"),
                  dict(_fattura(2), pivaCliente="22222222222")]
        auth = _Auth(_Sessione(elenco, [200, 200]))
        spia = ProgressoSpia()
        fec_download._scarica_da_lista(
            auth, "http://x/lista", self.tmp, log=lambda *_: None,
            escludi_scartate_pa=False, filtro_piva="11111111111",
            ruolo_controparte="cliente", progresso=spia)
        self.assertIn(("totale", 1), spia.eventi)

    def test_fattura_scartata_dalla_pa_produce_un_esito_saltato(self):
        # Il controllo reale interroga l'AdE: qui lo si sostituisce con uno che
        # dichiara scartata la sola fattura T1.
        auth = _Auth(_Sessione([_fattura(1), _fattura(2)], [200, 200]))
        spia = ProgressoSpia()
        with unittest.mock.patch.object(
                fec_download, "_e_scartata_pa",
                lambda _auth, fattura_file, _log: fattura_file == "T1"):
            fec_download._scarica_da_lista(
                auth, "http://x/lista", self.tmp, log=lambda *_: None,
                escludi_scartate_pa=True, progresso=spia)
        esiti = spia.solo("esito")
        self.assertEqual(len(esiti), 2)
        self.assertEqual(esiti.count(("esito", fec_download.ESITO_SALTATO)), 1)
        self.assertEqual(esiti.count(("esito", fec_download.ESITO_OK)), 1)

    def test_metadato_fallito_non_aggiunge_un_secondo_esito(self):
        # Il file fattura torna 200; la GET dei metadati cade per errore di
        # connessione su tutti i tentativi. La fattura e' gia' stata contata:
        # una tacca vale un documento, non un file.
        class _SessioneMetadatoRotto(_Sessione):
            def get(self, url, **kwargs):
                if "FILE_METADATI" in url:
                    raise fec_download.requests.exceptions.ConnectionError("giu'")
                return super().get(url, **kwargs)

        auth = _Auth(_SessioneMetadatoRotto([_fattura(1)], [200]))
        spia = ProgressoSpia()
        with unittest.mock.patch.object(fec_download.time, "sleep", lambda *_: None):
            fec_download._scarica_da_lista(
                auth, "http://x/lista", self.tmp, log=lambda *_: None,
                escludi_scartate_pa=False, progresso=spia)
        self.assertEqual(spia.solo("esito"), [("esito", fec_download.ESITO_OK)])

    def test_senza_progresso_il_comportamento_non_cambia(self):
        auth = _Auth(_Sessione([_fattura(1)], [200, 200]))
        n_fatture, _ = fec_download._scarica_da_lista(
            auth, "http://x/lista", self.tmp, log=lambda *_: None,
            escludi_scartate_pa=False)
        self.assertEqual(n_fatture, 1)


class TestFasiEseguiRichiesta(unittest.TestCase):
    """`esegui_richiesta` annuncia una fase per blocco di periodo."""

    def setUp(self):
        import fec_queue
        self.fq = fec_queue

    def _finta(self, registro):
        def _scarica(auth, dal, al, **kw):
            # Registra anche SE la chiave c'e', non solo il valore: `kw.get`
            # non distingue una chiave assente da una chiave con valore None.
            registro.append((dal, al, kw.get("progresso"), "progresso" in kw))
            return fec_download.DownloadResult("CF", "/tmp", 0, 0)
        return _scarica

    def test_una_fase_per_blocco(self):
        registro = []
        spia = ProgressoSpia()
        spec = self.fq._Spec(self._finta(registro), "%d%m%Y", "download")
        with unittest.mock.patch.dict(self.fq.TIPI, {"finto": spec}):
            self.fq.esegui_richiesta(None, "finto", dal="01012026", al="31082026",
                                     cf_cliente="CF", log=lambda *_: None,
                                     progresso=spia)
        fasi = spia.solo("fase")
        self.assertEqual(len(fasi), 3)            # 8 mesi -> 3 blocchi da 3
        self.assertEqual(fasi[0][2], 1)           # indice
        self.assertEqual(fasi[0][3], 3)           # totale blocchi
        self.assertIn("blocco 1/3", fasi[0][1])

    def test_blocco_unico_senza_suffisso(self):
        registro = []
        spia = ProgressoSpia()
        spec = self.fq._Spec(self._finta(registro), "%d%m%Y", "download")
        with unittest.mock.patch.dict(self.fq.TIPI, {"finto": spec}):
            self.fq.esegui_richiesta(None, "finto", dal="01012026", al="31012026",
                                     cf_cliente="CF", log=lambda *_: None,
                                     progresso=spia)
        fasi = spia.solo("fase")
        self.assertEqual(len(fasi), 1)
        self.assertNotIn("blocco", fasi[0][1])

    def test_il_progresso_arriva_alla_funzione_di_download(self):
        registro = []
        spia = ProgressoSpia()
        spec = self.fq._Spec(self._finta(registro), "%d%m%Y", "download")
        with unittest.mock.patch.dict(self.fq.TIPI, {"finto": spec}):
            self.fq.esegui_richiesta(None, "finto", dal="01012026", al="31012026",
                                     cf_cliente="CF", log=lambda *_: None,
                                     progresso=spia)
        self.assertIs(registro[0][2], spia)

    def test_senza_progresso_inoltra_none(self):
        # Come `control`: la chiave arriva sempre ai download, con valore None.
        registro = []
        spec = self.fq._Spec(self._finta(registro), "%d%m%Y", "download")
        with unittest.mock.patch.dict(self.fq.TIPI, {"finto": spec}):
            self.fq.esegui_richiesta(None, "finto", dal="01012026", al="31012026",
                                     cf_cliente="CF", log=lambda *_: None)
        self.assertTrue(registro[0][3], "la chiave «progresso» non e' stata inoltrata")
        self.assertIsNone(registro[0][2])


if __name__ == "__main__":
    unittest.main()
