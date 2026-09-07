#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Test dei profili di accesso: delega diretta e backend SSO (nessuna rete)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ade_auth


class TestPayloadDelegaDiretta(unittest.TestCase):

    def test_codice_fiscale(self):
        self.assertEqual(
            ade_auth._payload_delega_diretta("RSSMRA80A01H501U"),
            {"tipoutenza": "delegaDiretta", "tipoDelega": "delDiretta",
             "cf": "RSSMRA80A01H501U"})

    def test_normalizza_spazi_e_minuscole(self):
        self.assertEqual(ade_auth._payload_delega_diretta("  rssmra80a01h501u  ")["cf"],
                         "RSSMRA80A01H501U")

    def test_partita_iva_passata_anche_come_piva(self):
        # 11 cifre: il portale la usa per individuare il soggetto.
        payload = ade_auth._payload_delega_diretta("01234567890")
        self.assertEqual(payload["cf"], "01234567890")
        self.assertEqual(payload["pIva"], "01234567890")

    def test_codice_fiscale_non_numerico_non_ha_piva(self):
        self.assertNotIn("pIva", ade_auth._payload_delega_diretta("RSSMRA80A01H501U"))

    def test_undici_caratteri_non_numerici_non_sono_una_piva(self):
        self.assertNotIn("pIva", ade_auth._payload_delega_diretta("ABCDE123456"))

    def test_vuoto_resta_vuoto(self):
        self.assertEqual(ade_auth._payload_delega_diretta("")["cf"], "")

    def test_profilo_dedicato_distinto_dagli_altri(self):
        profili = {ade_auth.PROFILO_STUDIO_CLIENTE, ade_auth.PROFILO_STUDIO_CASSETTO,
                   ade_auth.PROFILO_ME_STESSO, ade_auth.PROFILO_AZIENDA,
                   ade_auth.PROFILO_DELEGA_DIRETTA}
        self.assertEqual(len(profili), 5)

    def test_delega_diretta_non_usa_un_incarico(self):
        # Il flusso non passa da `incaricante`/`tipoincaricante`: se comparisse nella
        # mappa vorrebbe dire che qualcuno l'ha trattato come i profili studio/azienda.
        self.assertNotIn(ade_auth.PROFILO_DELEGA_DIRETTA, ade_auth._PROFILO_TIPOINCARICANTE)


class TestBackendSso(unittest.TestCase):

    def test_backend_sconosciuto_elenca_anche_sso(self):
        with self.assertRaises(ade_auth.AuthError) as ctx:
            ade_auth.autentica(ade_auth.Creds(nomeutente="x", pin="1", password="p"),
                               backend="pippo")
        self.assertIn("sso", str(ctx.exception))

    def test_costanti_del_flusso_sso(self):
        self.assertEqual(ade_auth.COOKIE_LOGIN_FATTO, "FATSC")
        self.assertEqual(ade_auth.LS_TOKEN_B2B, "FattCorrActiveB2B")
        self.assertEqual(ade_auth.LS_TOKEN, "FattCorrActiveToken")


if __name__ == "__main__":
    unittest.main()
