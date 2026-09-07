#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Test della logica pura del nastro di avanzamento (nessun Tk)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_nastro
from fec_nastro import ESITO_OK, ESITO_SALTATO, ESITO_ERRORE


class TestCostantiAllineate(unittest.TestCase):
    """`fec_nastro` non importa `fec_download` (vedi la docstring del modulo):
    le costanti sono duplicate, quindi serve un test che le tenga allineate."""

    def test_stesse_costanti_di_fec_download(self):
        import fec_download
        self.assertEqual(fec_nastro.ESITO_OK, fec_download.ESITO_OK)
        self.assertEqual(fec_nastro.ESITO_SALTATO, fec_download.ESITO_SALTATO)
        self.assertEqual(fec_nastro.ESITO_ERRORE, fec_download.ESITO_ERRORE)


class TestRiepilogo(unittest.TestCase):

    def test_modello_vuoto(self):
        m = fec_nastro.ModelloNastro()
        r = m.riepilogo()
        self.assertEqual((r.ok, r.saltati, r.errori, r.fatti), (0, 0, 0, 0))
        self.assertIsNone(r.totale)

    def test_conta_gli_esiti_di_un_segmento(self):
        m = fec_nastro.ModelloNastro()
        m.nuovo_segmento("Emesse")
        m.imposta_totale(5)
        m.aggiungi_esito(ESITO_OK)
        m.aggiungi_esito(ESITO_OK)
        m.aggiungi_esito(ESITO_SALTATO)
        m.aggiungi_esito(ESITO_ERRORE)
        r = m.riepilogo()
        self.assertEqual((r.ok, r.saltati, r.errori), (2, 1, 1))
        self.assertEqual(r.fatti, 4)
        self.assertEqual(r.totale, 5)

    def test_somma_piu_segmenti(self):
        m = fec_nastro.ModelloNastro()
        m.nuovo_segmento("blocco 1")
        m.imposta_totale(3)
        m.aggiungi_esito(ESITO_OK)
        m.nuovo_segmento("blocco 2")
        m.imposta_totale(2)
        m.aggiungi_esito(ESITO_ERRORE)
        r = m.riepilogo()
        self.assertEqual(r.totale, 5)
        self.assertEqual(r.fatti, 2)
        self.assertEqual((r.ok, r.errori), (1, 1))

    def test_segmento_senza_totale_non_inventa_un_totale(self):
        # Fase senza conteggio (es. "Richiedo l'elenco all'AdE"): il totale
        # resta ignoto finche l'elenco non arriva.
        m = fec_nastro.ModelloNastro()
        m.nuovo_segmento("Emesse")
        self.assertIsNone(m.riepilogo().totale)

    def test_totale_zero_e_un_totale_noto(self):
        # Nessuna fattura nel periodo: 0 e' un'informazione, non un'assenza.
        m = fec_nastro.ModelloNastro()
        m.nuovo_segmento("Emesse")
        m.imposta_totale(0)
        self.assertEqual(m.riepilogo().totale, 0)

    def test_azzera_riporta_allo_stato_iniziale(self):
        m = fec_nastro.ModelloNastro()
        m.nuovo_segmento("Emesse")
        m.imposta_totale(2)
        m.aggiungi_esito(ESITO_OK)
        m.azzera()
        r = m.riepilogo()
        self.assertEqual(r.fatti, 0)
        self.assertIsNone(r.totale)

    def test_esito_senza_segmento_ne_apre_uno(self):
        # Difensivo: un chiamante che emette esito() prima di fase() non deve
        # far esplodere la barra.
        m = fec_nastro.ModelloNastro()
        m.aggiungi_esito(ESITO_OK)
        self.assertEqual(m.riepilogo().ok, 1)


if __name__ == "__main__":
    unittest.main()
