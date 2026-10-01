#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Cartelle di destinazione nella riga di comando."""

import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_cli
import fec_deleghe
import fec_queue


class TestCliCartelle(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        patch.object(fec_deleghe, "load_deleghe", return_value=[]).start()
        self.addCleanup(patch.stopall)
        self.chiamate = []

        def finta(auth, tipo, dal=None, al=None, **kw):
            self.chiamate.append((tipo, kw))
            return None

        patch.object(fec_queue, "esegui_richiesta", finta).start()
        self.auth = SimpleNamespace(piva="01234567890", denominazione="ROSSI SRL")

    def _args(self, *extra):
        return fec_cli.build_parser().parse_args(
            ["--cf", "X", "--pin", "1", "--password", "p", "--dest", self.base, *extra])

    def test_default_ditta_con_anno(self):
        args = self._args("--cf-cliente", "CFCL", "emesse", "--dal", "01072026",
                          "--al", "31072026")
        self.assertEqual((args.cartelle, args.no_anno), ("ditta", False))
        fec_cli._dispatch(args, self.auth, fec_queue)
        tipo, kw = self.chiamate[0]
        self.assertEqual(kw["dest_dir"], os.path.join(self.base, "ROSSI SRL - 01234567890",
                                                      "Fatture emesse"))
        self.assertEqual((kw["sottocartella"], kw["per_anno"]), (False, True))

    def test_sessione(self):
        args = self._args("--cartelle", "sessione", "--cf-cliente", "CFCL", "emesse",
                          "--dal", "01072026", "--al", "31072026")
        fec_cli._dispatch(args, self.auth, fec_queue)
        _, kw = self.chiamate[0]
        self.assertRegex(os.path.basename(os.path.dirname(kw["dest_dir"])),
                         r"^\d{4}-\d{2}-\d{2}_\d{4}$")
        self.assertFalse(kw["per_anno"])

    def test_no_anno_bolli(self):
        args = self._args("--no-anno", "--cf-cliente", "CFCL", "bolli", "--trimestre", "1",
                          "--anno", "2026")
        fec_cli._dispatch(args, self.auth, fec_queue)
        _, kw = self.chiamate[0]
        self.assertEqual(kw["dest_dir"], os.path.join(self.base, "ROSSI SRL - 01234567890",
                                                      "Bolli virtuali"))


if __name__ == "__main__":
    unittest.main()
