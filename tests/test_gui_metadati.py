#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Casella dei metadati e preferenza salvata."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_gui
import fec_store
from _appgui import AppGuiCase


class TestGuiMetadati(AppGuiCase):

    def test_chiave_tra_le_preferenze_ammesse(self):
        self.assertIn("std_scarica_metadati", fec_store.SETTINGS_KEYS)

    def test_acceso_di_default(self):
        self.assertTrue(self.app.std_scarica_metadati.get())

    def test_preferenza_salvata(self):
        self.app.std_scarica_metadati.set(False)
        with patch.object(fec_gui.messagebox, "showinfo"):
            self.app._save_config()
        preferenze = self.salva.call_args[0][0]
        self.assertIs(preferenze["std_scarica_metadati"], False)


if __name__ == "__main__":
    unittest.main()
