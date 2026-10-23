#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Flag CLI per saltare i metadati (nessun login, solo argomenti)."""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_cli

ACCESSO = ["--cf", "RSSMRA80A01H501U", "--pin", "1234", "--password", "x",
           "--cf-cliente", "09876543210"]
PERIODO = ["emesse", "--dal", "01072026", "--al", "31072026"]


class TestCliMetadati(unittest.TestCase):

    def test_metadati_scaricati_per_default(self):
        args = fec_cli.build_parser().parse_args(ACCESSO + PERIODO)
        self.assertTrue(args.scarica_metadati)

    def test_flag_senza_metadati(self):
        args = fec_cli.build_parser().parse_args(ACCESSO + ["--senza-metadati"] + PERIODO)
        self.assertFalse(args.scarica_metadati)

    def test_dry_run_mostra_l_opzione(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            codice = fec_cli.main(ACCESSO + ["--senza-metadati", "--dry-run"] + PERIODO)
        self.assertEqual(codice, 0)
        self.assertIn("scarica_metadati = False", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
