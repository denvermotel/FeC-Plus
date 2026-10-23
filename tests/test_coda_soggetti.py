#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Coda per soggetti di fec_queue: un login, un ciclo di richieste per soggetto."""

import os
import sys
import unittest
from typing import NamedTuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_download as fd
import fec_queue as fq
from ade_auth import AuthError


class S(NamedTuple):
    nome: str
    cf: str
    piva: str = ""


A, B, C = S("A", "CFA"), S("B", "CFB"), S("C", "CFC")


class TestCodaSoggetti(unittest.TestCase):

    def setUp(self):
        self.log = []
        self.chiamate = []

    def _accedi(self, rotti=(), step="utenza"):
        def accedi(s, precedente):
            self.chiamate.append((s.cf, precedente))
            if s.cf in rotti:
                raise AuthError(step, f"{s.cf} non raggiungibile")
            return f"auth-{s.cf}"
        return accedi

    def test_un_login_poi_cambio_utenza(self):
        esiti = fq.esegui_per_soggetti([A, B], self._accedi(), lambda auth, s: f"{auth}/{s.cf}",
                                       log=self.log.append)
        self.assertEqual(self.chiamate, [("CFA", None), ("CFB", "auth-CFA")])
        self.assertEqual([e.esito for e in esiti], ["auth-CFA/CFA", "auth-CFB/CFB"])
        self.assertTrue(all(e.ok for e in esiti))

    def test_un_solo_soggetto_non_scrive_l_intestazione(self):
        fq.esegui_per_soggetti([A], self._accedi(), lambda auth, s: None, log=self.log.append)
        self.assertEqual(self.log, [])

    def test_accesso_fallito_a_meta_non_ferma_gli_altri(self):
        esiti = fq.esegui_per_soggetti([A, B, C], self._accedi(rotti={"CFB"}),
                                       lambda auth, s: s.cf, log=self.log.append)
        self.assertEqual([e.ok for e in esiti], [True, False, True])
        self.assertEqual(esiti[1].fase, "accesso")
        self.assertEqual(esiti[1].step, "utenza")
        # il terzo riparte dall'ultima sessione valida, non da quella fallita
        self.assertEqual(self.chiamate[-1], ("CFC", "auth-CFA"))

    def test_primo_login_fallito_non_si_ripete(self):
        esiti = fq.esegui_per_soggetti([A, B, C], self._accedi(rotti={"CFA"}, step="login"),
                                       lambda auth, s: s.cf, log=self.log.append)
        self.assertEqual(len(self.chiamate), 1)
        self.assertEqual([e.fase for e in esiti], ["accesso"] * 3)
        self.assertEqual([e.soggetto for e in esiti], [A, B, C])

    def test_primo_soggetto_senza_delega_non_ferma_gli_altri(self):
        # Credenziali giuste, utenza del primo non selezionabile: il secondo rifà il login.
        esiti = fq.esegui_per_soggetti([A, B, C], self._accedi(rotti={"CFA"}),
                                       lambda auth, s: s.cf, log=self.log.append)
        self.assertEqual([e.ok for e in esiti], [False, True, True])
        self.assertEqual(self.chiamate, [("CFA", None), ("CFB", None), ("CFC", "auth-CFB")])

    def test_errore_imprevisto_non_ferma_gli_altri(self):
        def operazione(auth, s):
            if s.cf == "CFA":
                raise OSError("percorso troppo lungo")
            return s.cf
        esiti = fq.esegui_per_soggetti([A, B], self._accedi(), operazione, log=self.log.append)
        self.assertEqual([e.ok for e in esiti], [False, True])
        self.assertTrue(esiti[0].imprevisto)
        self.assertEqual(esiti[0].errore, "percorso troppo lungo")

    def test_errore_imprevisto_all_accesso_non_ferma_gli_altri(self):
        def accedi(s, precedente):
            self.chiamate.append((s.cf, precedente))
            if s.cf == "CFB":
                raise OSError("rete caduta")
            return f"auth-{s.cf}"
        esiti = fq.esegui_per_soggetti([A, B, C], accedi, lambda auth, s: s.cf,
                                       log=self.log.append)
        self.assertEqual([e.ok for e in esiti], [True, False, True])
        self.assertEqual(esiti[1].fase, "accesso")
        self.assertTrue(esiti[1].imprevisto)
        self.assertEqual(esiti[1].errore, "rete caduta")
        self.assertEqual(self.chiamate[-1], ("CFC", "auth-CFA"))

    def test_errore_imprevisto_al_primo_accesso_segna_tutti(self):
        def accedi(s, precedente):
            self.chiamate.append((s.cf, precedente))
            raise OSError("rete caduta")
        esiti = fq.esegui_per_soggetti([A, B, C], accedi, lambda auth, s: s.cf,
                                       log=self.log.append)
        self.assertEqual(len(self.chiamate), 1)
        self.assertEqual([e.fase for e in esiti], ["accesso"] * 3)
        self.assertTrue(all(e.imprevisto for e in esiti))
        self.assertEqual([e.soggetto for e in esiti], [A, B, C])

    def test_operazione_fallita_non_ferma_gli_altri(self):
        def operazione(auth, s):
            if s.cf == "CFA":
                raise fq.DownloadError("lista non ottenuta")
            return s.cf
        esiti = fq.esegui_per_soggetti([A, B], self._accedi(), operazione, log=self.log.append)
        self.assertEqual([e.ok for e in esiti], [False, True])
        self.assertEqual(esiti[0].fase, "operazione")
        self.assertEqual(esiti[0].errore, "lista non ottenuta")

    def test_interruzione_dell_utente_ferma_la_coda(self):
        def operazione(auth, s):
            raise fd.DownloadAnnullato("Download interrotto dall'utente.")
        with self.assertRaises(fd.DownloadAnnullato):
            fq.esegui_per_soggetti([A, B], self._accedi(), operazione, log=self.log.append)
        self.assertEqual(len(self.chiamate), 1)

    def test_controllo_annullato_prima_di_iniziare(self):
        controllo = fd.Controllo()
        controllo.annulla()
        with self.assertRaises(fd.DownloadAnnullato):
            fq.esegui_per_soggetti([A], self._accedi(), lambda auth, s: None,
                                   control=controllo, log=self.log.append)
        self.assertEqual(self.chiamate, [])


class TestProgressoPrefissato(unittest.TestCase):

    def test_antepone_il_soggetto_e_inoltra_il_resto(self):
        from _finti import ProgressoSpia
        spia = ProgressoSpia()
        p = fq.ProgressoPrefissato(spia, "Rossi")
        p.fase("Emesse · blocco 1/2", 1, 2)
        p.totale(5)
        p.esito(fd.ESITO_OK)
        p.conclusa()
        self.assertEqual(spia.eventi, [("fase", "Rossi · Emesse · blocco 1/2", 1, 2),
                                       ("totale", 5), ("esito", fd.ESITO_OK),
                                       ("conclusa", False)])


if __name__ == "__main__":
    unittest.main()
