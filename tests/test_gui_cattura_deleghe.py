#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Cattura HAR delle Deleghe: il login riparte dalla home del portale."""

import os
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ade_auth
from _appgui import AppGuiCase


class TestUrlLoginPortale(unittest.TestCase):

    def test_ritorno_alla_home_del_portale_senza_fatture(self):
        goto = parse_qs(urlparse(ade_auth.PORTALE_LOGIN_URL).query)["goto"][0]
        self.assertEqual(urlparse(goto).hostname, "portale.agenziaentrate.gov.it")
        self.assertTrue(goto.endswith("/PortaleWeb/home"))
        self.assertNotIn("FATBTB", ade_auth.PORTALE_LOGIN_URL)

    def test_il_login_di_fatture_resta_invariato(self):
        self.assertIn("FATBTB", ade_auth.SAM_LOGIN_URL)


class TestCatturaDeleghe(AppGuiCase):

    def test_parte_dal_portale(self):
        self.app._run_inprocess = lambda fn: fn(lambda _t: None)
        with patch.object(self.app, "_get_creds", return_value=("CF", "1234", "pwd", "")), \
                patch.object(ade_auth, "cattura_har_navigazione",
                             return_value=("a.har", "a.log")) as cattura:
            self.app._run_capture_deleghe()
        self.assertEqual(cattura.call_args.kwargs["login_url"], ade_auth.PORTALE_LOGIN_URL)
        self.assertEqual(cattura.call_args.kwargs["prefisso"], "capture_deleghe")


if __name__ == "__main__":
    unittest.main()
