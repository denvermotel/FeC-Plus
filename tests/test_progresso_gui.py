#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Test di `fec_gui.ProgressoGUI` senza Tk: riga di stato e nastro a ogni fine
operazione. Un'app finta sostituisce la finestra (nessuna rete, nessuna GUI)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_gui
import fec_nastro


class _Root:
    """`root.after` che non fa nulla: la pompa non gira, si usa `svuota()`."""

    def after(self, *_a, **_k):
        return None


class _Nastro:
    def __init__(self):
        self.ridisegni = 0

    def ridisegna(self):
        self.ridisegni += 1


class _Var:
    def __init__(self):
        self._valore = ""

    def set(self, valore):
        self._valore = valore

    def get(self):
        return self._valore


class _App:
    def __init__(self):
        self.root = _Root()
        self.nastro = _Nastro()
        self.stato_var = _Var()
        self.modello_nastro = fec_nastro.ModelloNastro()


class TestRigaDiStato(unittest.TestCase):

    def setUp(self):
        self.app = _App()
        self.p = fec_gui.ProgressoGUI(self.app, 2)

    def _riga(self):
        self.p.svuota()
        return self.app.stato_var.get()

    def test_il_totale_toglie_il_messaggio_di_richiesta_elenco(self):
        self.p.fase("Emesse", 1, 2)
        self.p.messaggio("Richiedo l'elenco all'AdE…")
        self.p.totale(3)
        self.assertNotIn("Richiedo", self._riga())

    def test_periodo_vuoto(self):
        self.p.fase("Emesse", 1, 2)
        self.p.totale(0)
        self.p.conclusa()
        riga = self._riga()
        self.assertIn("Nessuna fattura nel periodo", riga)
        self.assertNotIn("0/0", riga)

    def test_messaggio_dopo_conclusa_vince(self):
        self.p.conclusa()
        self.p.messaggio("Accesso non riuscito.")
        riga = self._riga()
        self.assertIn("Accesso non riuscito", riga)
        self.assertNotIn("completata", riga)

    def test_senza_fasi_niente_fase_zero(self):
        self.p.conclusa()
        self.assertNotIn("fase", self._riga())

    def test_interrotto_dall_utente(self):
        self.p.conclusa(annullato=True)
        self.assertIn("Interrotto dall'utente", self._riga())


class TestNastroChiusoAllaFine(unittest.TestCase):

    def test_conclusa_toglie_la_tacca_in_lavorazione(self):
        app = _App()
        p = fec_gui.ProgressoGUI(app, 1)
        p.fase("Emesse", 1, 1)
        p.totale(3)
        p.esito("ok")
        p.conclusa()
        p.svuota()
        colori = [r.colore for r in app.modello_nastro.rettangoli(300, 10)]
        self.assertNotIn(fec_nastro.COL_CORRENTE, colori)


if __name__ == "__main__":
    unittest.main()
