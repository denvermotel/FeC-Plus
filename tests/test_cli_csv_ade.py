#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Test del parsing CLI per l'export CSV AdE (nessun login, solo argomenti)."""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_cli

ACCESSO = ["--cf", "RSSMRA80A01H501U", "--pin", "1234", "--password", "x",
           "--cf-cliente", "09876543210"]


class TestParserCsvAde(unittest.TestCase):

    def test_flag_csv_ade_assente_per_default(self):
        args = fec_cli.build_parser().parse_args(
            ACCESSO + ["emesse", "--dal", "01072026", "--al", "31072026"])
        self.assertFalse(args.csv_ade)

    def test_flag_csv_ade_attivabile(self):
        args = fec_cli.build_parser().parse_args(
            ACCESSO + ["--csv-ade", "emesse", "--dal", "01072026", "--al", "31072026"])
        self.assertTrue(args.csv_ade)

    def test_comando_csv_fatture(self):
        args = fec_cli.build_parser().parse_args(
            ACCESSO + ["csv-fatture", "--tipo", "ricevute_ricezione",
                       "--dal", "01072026", "--al", "31072026"])
        self.assertEqual(args.comando, "csv-fatture")
        self.assertEqual(args.tipo, "ricevute_ricezione")

    def test_comando_csv_fatture_rifiuta_tipo_sconosciuto(self):
        with self.assertRaises(SystemExit):
            fec_cli.build_parser().parse_args(
                ACCESSO + ["csv-fatture", "--tipo", "pippo",
                           "--dal", "01072026", "--al", "31072026"])

    def test_sso_non_richiede_le_credenziali(self):
        args = fec_cli.build_parser().parse_args(
            ["--backend", "sso", "emesse", "--dal", "01072026", "--al", "31072026"])
        self.assertIsNone(fec_cli._verifica_accesso(args))
        self.assertEqual(fec_cli._risolvi_password(args), "")

    def test_senza_sso_le_credenziali_restano_obbligatorie(self):
        args = fec_cli.build_parser().parse_args(
            ["emesse", "--dal", "01072026", "--al", "31072026"])
        with self.assertRaises(SystemExit) as ctx:
            fec_cli._verifica_accesso(args)
        for atteso in ("--cf", "--pin", "--password", "sso"):
            self.assertIn(atteso, str(ctx.exception))

    def test_dry_run_con_sso_non_esplode_senza_cf(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            codice = fec_cli.main(["--backend", "sso", "--dry-run", "emesse",
                                   "--dal", "01072026", "--al", "31072026"])
        self.assertEqual(codice, 0)
        self.assertIn("backend=sso", buf.getvalue())

    def test_dry_run_mostra_csv_ade(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            codice = fec_cli.main(ACCESSO + ["--csv-ade", "--dry-run", "emesse",
                                             "--dal", "01072026", "--al", "31072026"])
        self.assertEqual(codice, 0)
        self.assertIn("csv_ade = True", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
