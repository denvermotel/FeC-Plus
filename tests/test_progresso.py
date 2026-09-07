#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Test del canale di avanzamento `Progresso` (nessuna rete, nessuna GUI)."""

import os
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
