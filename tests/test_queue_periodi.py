#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Test di fec_queue.spezza_periodo (blocchi in mesi e in giorni)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_queue as fq


class TestSpezzaPeriodo(unittest.TestCase):

    def test_senza_max_giorni_comportamento_invariato(self):
        self.assertEqual(fq.spezza_periodo("01012026", "31052026"),
                         [("01012026", "31032026"), ("01042026", "31052026")])

    def test_mese_per_mese(self):
        self.assertEqual(fq.spezza_periodo("01012026", "31032026", max_mesi=1),
                         [("01012026", "31012026"), ("01022026", "28022026"),
                          ("01032026", "31032026")])

    def test_blocchi_settimanali(self):
        self.assertEqual(fq.spezza_periodo("01012026", "20012026", max_giorni=7),
                         [("01012026", "07012026"), ("08012026", "14012026"),
                          ("15012026", "20012026")])

    def test_max_giorni_su_un_giorno(self):
        self.assertEqual(fq.spezza_periodo("05012026", "05012026", max_giorni=7),
                         [("05012026", "05012026")])

    def test_guardia_dodici_mesi_vale_anche_coi_giorni(self):
        with self.assertRaises(fq.DownloadError):
            fq.spezza_periodo("01012026", "01022027", max_giorni=7)


if __name__ == "__main__":
    unittest.main()
