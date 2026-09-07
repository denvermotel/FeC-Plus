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


class TestRettangoli(unittest.TestCase):

    def _modello(self, totale, esiti):
        m = fec_nastro.ModelloNastro()
        m.nuovo_segmento("Emesse")
        m.imposta_totale(totale)
        for e in esiti:
            m.aggiungi_esito(e)
        return m

    def test_modello_vuoto_non_disegna_nulla(self):
        self.assertEqual(fec_nastro.ModelloNastro().rettangoli(100, 10), [])

    def test_totale_zero_non_disegna_nulla(self):
        m = self._modello(0, [])
        self.assertEqual(m.rettangoli(100, 10), [])

    def test_una_tacca_per_documento_sotto_il_massimo(self):
        m = self._modello(4, [ESITO_OK, ESITO_OK])
        self.assertEqual(len(m.rettangoli(400, 10)), 4)

    def test_colori_per_esito(self):
        m = self._modello(3, [ESITO_OK, ESITO_SALTATO, ESITO_ERRORE])
        colori = [r.colore for r in m.rettangoli(300, 10)]
        self.assertEqual(colori, [fec_nastro.COL_OK,
                                  fec_nastro.COL_SALTATO,
                                  fec_nastro.COL_ERRORE])

    def test_la_tacca_corrente_e_quella_dopo_l_ultimo_esito(self):
        m = self._modello(4, [ESITO_OK, ESITO_OK])
        r = m.rettangoli(400, 10)
        self.assertEqual(r[2].colore, fec_nastro.COL_CORRENTE)
        self.assertEqual(r[3].colore, fec_nastro.COL_DA_FARE)

    def test_errore_e_corrente_a_tutta_altezza(self):
        m = self._modello(3, [ESITO_OK, ESITO_ERRORE])
        r = m.rettangoli(300, 10)
        self.assertEqual(r[0].altezza, 5)     # normale: meta'
        self.assertEqual(r[0].y, 5)           # allineata in basso
        self.assertEqual(r[1].altezza, 10)    # errore: piena
        self.assertEqual(r[1].y, 0)
        self.assertEqual(r[2].altezza, 10)    # corrente: piena

    def test_segmento_completo_non_ha_tacca_corrente(self):
        m = self._modello(2, [ESITO_OK, ESITO_OK])
        colori = [r.colore for r in m.rettangoli(200, 10)]
        self.assertNotIn(fec_nastro.COL_CORRENTE, colori)

    def test_aggregazione_oltre_il_massimo(self):
        m = self._modello(fec_nastro.MAX_TACCHE * 2, [ESITO_OK])
        r = m.rettangoli(600, 10)
        self.assertEqual(len(r), fec_nastro.MAX_TACCHE)

    def test_nel_blocco_aggregato_vince_l_esito_peggiore(self):
        # fattore 2: il primo blocco contiene un ok e un errore -> rosso.
        m = self._modello(fec_nastro.MAX_TACCHE * 2,
                          [ESITO_OK, ESITO_ERRORE, ESITO_OK, ESITO_SALTATO])
        r = m.rettangoli(600, 10)
        self.assertEqual(r[0].colore, fec_nastro.COL_ERRORE)
        self.assertEqual(r[1].colore, fec_nastro.COL_SALTATO)

    def test_due_segmenti_hanno_un_gap_in_mezzo(self):
        m = fec_nastro.ModelloNastro()
        m.nuovo_segmento("uno")
        m.imposta_totale(2)
        m.aggiungi_esito(ESITO_OK)
        m.aggiungi_esito(ESITO_OK)
        m.nuovo_segmento("due")
        m.imposta_totale(2)
        m.aggiungi_esito(ESITO_OK)
        m.aggiungi_esito(ESITO_OK)
        r = m.rettangoli(402, 10)
        self.assertEqual(len(r), 4)
        fine_primo = r[1].x + r[1].larghezza
        self.assertGreaterEqual(r[2].x - fine_primo, fec_nastro.GAP_SEGMENTO)

    def test_i_rettangoli_stanno_dentro_la_larghezza(self):
        m = self._modello(37, [ESITO_OK] * 10)
        for r in m.rettangoli(250, 10):
            self.assertGreaterEqual(r.x, 0)
            self.assertLessEqual(r.x + r.larghezza, 250)

    def test_ogni_tacca_e_larga_almeno_un_pixel(self):
        # Nastro stretto e molti documenti: nessun rettangolo invisibile.
        m = self._modello(200, [ESITO_OK] * 50)
        for r in m.rettangoli(120, 10):
            self.assertGreaterEqual(r.larghezza, 1)


if __name__ == "__main__":
    unittest.main()
