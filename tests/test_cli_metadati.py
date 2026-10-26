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

    def test_flag_solo_ritenuta(self):
        args = fec_cli.build_parser().parse_args(ACCESSO + PERIODO)
        self.assertFalse(args.solo_ritenuta)
        args = fec_cli.build_parser().parse_args(ACCESSO + ["--solo-ritenuta"] + PERIODO)
        self.assertTrue(args.solo_ritenuta)
        buf = io.StringIO()
        with redirect_stdout(buf):
            fec_cli.main(ACCESSO + ["--solo-ritenuta", "--dry-run"] + PERIODO)
        self.assertIn("solo_ritenuta = True", buf.getvalue())

    def test_solo_ritenuta_senza_asn1crypto_avvisa(self):
        import fec_deps
        from contextlib import redirect_stderr
        from unittest.mock import patch
        import ade_auth
        err = io.StringIO()
        with patch.object(fec_deps, "find_missing",
                          return_value={"core": [], "browser": [], "gui": [],
                                        "p7m": ["asn1crypto"], "excel": []}), \
                patch.object(ade_auth, "autentica",
                             side_effect=ade_auth.AuthError("login", "prova")), \
                redirect_stderr(err), redirect_stdout(io.StringIO()):
            fec_cli.main(ACCESSO + ["--solo-ritenuta"] + PERIODO)
        self.assertIn("asn1crypto", err.getvalue())

    def test_dry_run_mostra_l_opzione(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            codice = fec_cli.main(ACCESSO + ["--senza-metadati", "--dry-run"] + PERIODO)
        self.assertEqual(codice, 0)
        self.assertIn("scarica_metadati = False", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
