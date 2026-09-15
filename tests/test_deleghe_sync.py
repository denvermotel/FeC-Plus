#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test di fec_deleghe_sync.elabora_deleganti (parsing/aggregazione, offline)."""

import json
import os
import unittest
from unittest.mock import MagicMock

import fec_deleghe_sync as sync

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                        "deleganti_campione.json")


def _carica_campione() -> list[dict]:
    with open(_FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)["lista"]


class TestElaboraDeleganti(unittest.TestCase):
    def setUp(self):
        self.lista = _carica_campione()

    def test_scarta_record_senza_servizi_rilevanti(self):
        righe = sync.elabora_deleganti(self.lista)
        cf_uv_irrilevante = next(
            r["cfDelegante"].strip() for r in self.lista
            if r["tipoDelega"] == "UV"
            and not any(s["idServizio"] in sync.SERVIZI_RILEVANTI
                        for s in r.get("servizi") or []))
        cf_presenti = {r["codice_fiscale"] for r in righe}
        self.assertNotIn(cf_uv_irrilevante, cf_presenti)

    def test_include_record_con_servizio_rilevante(self):
        righe = sync.elabora_deleganti(self.lista)
        cf_un_rilevante = next(
            r["cfDelegante"].strip() for r in self.lista
            if r["tipoDelega"] == "UN"
            and any(s["idServizio"] in sync.SERVIZI_RILEVANTI
                    for s in r.get("servizi") or []))
        cf_presenti = {r["codice_fiscale"] for r in righe}
        self.assertIn(cf_un_rilevante, cf_presenti)

    def test_cf_con_spazi_finali_normalizzato(self):
        righe = sync.elabora_deleganti(self.lista)
        for r in righe:
            self.assertEqual(r["codice_fiscale"], r["codice_fiscale"].strip())
            self.assertNotIn(" ", r["codice_fiscale"])

    def test_aggrega_piu_record_stesso_cf_prendendo_scadenza_piu_lontana(self):
        # Nel campione due UV rilevanti condividono lo stesso cfDelegante con
        # dataFineDel diverse (vedi genera_fixture_deleganti.py, "secondo").
        righe = sync.elabora_deleganti(self.lista)
        uv_rilevanti = [r for r in self.lista if r["tipoDelega"] == "UV"
                        and any(s["idServizio"] in sync.SERVIZI_RILEVANTI
                                for s in r.get("servizi") or [])]
        cf = uv_rilevanti[0]["cfDelegante"].strip()
        duplicati = [r for r in uv_rilevanti if r["cfDelegante"].strip() == cf]
        self.assertGreaterEqual(len(duplicati), 2,
            "la fixture deve avere almeno 2 record rilevanti con lo stesso CF")
        riga = next(r for r in righe if r["codice_fiscale"] == cf)
        # Una sola riga per CF (aggregato), non una per record.
        self.assertEqual(sum(1 for r in righe if r["codice_fiscale"] == cf), 1)
        attesa = max(sync._parse_data_it(r["dataFineDel"]) for r in duplicati)
        self.assertEqual(sync._parse_data_it(riga["data_fine_delega"]), attesa)

    def test_filtro_soglia_data_esclude_deleghe_vecchie(self):
        tutte = sync.elabora_deleganti(self.lista)
        recenti = sync.elabora_deleganti(self.lista, soglia_data="01/01/2025")
        self.assertLess(len(recenti), len(tutte))

    def test_soglia_data_vuota_non_filtra(self):
        tutte = sync.elabora_deleganti(self.lista)
        con_soglia_vuota = sync.elabora_deleganti(self.lista, soglia_data="")
        self.assertEqual(len(tutte), len(con_soglia_vuota))

    def test_denominazione_presente_nella_riga(self):
        righe = sync.elabora_deleganti(self.lista)
        self.assertTrue(all(r["denominazione"] for r in righe))


class _RispostaFinta:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


class TestFetchDelegantiRaw(unittest.TestCase):
    def _auth_finto(self, risposte_per_url):
        """risposte_per_url: dict che mappa una sottostringa dell'URL a una
        _RispostaFinta; il primo match (in ordine di inserimento) vince."""
        session = MagicMock()

        def get(url, **kwargs):
            for frammento, risposta in risposte_per_url.items():
                if frammento in url:
                    return risposta
            raise AssertionError(f"GET non atteso: {url}")

        def post(url, **kwargs):
            for frammento, risposta in risposte_per_url.items():
                if frammento in url:
                    return risposta
            raise AssertionError(f"POST non atteso: {url}")

        session.get.side_effect = get
        session.post.side_effect = post
        auth = MagicMock()
        auth.session = session
        return auth

    def test_fetch_ok_ritorna_lista_grezza(self):
        lista = [{"cfDelegante": "X"}]
        auth = self._auth_finto({
            "PortaleWeb/home": _RispostaFinta(200, text="<html></html>"),
            "initPortale": _RispostaFinta(200, text="{}"),
            "initLight": _RispostaFinta(200, text=""),
            "delegheUniche/deleganti": _RispostaFinta(200, {"lista": lista}),
        })
        risultato = sync.fetch_deleganti_raw(auth, log=lambda _m: None)
        self.assertEqual(risultato, lista)

    def test_fetch_403_solleva_sincronizzazione_bloccata(self):
        auth = self._auth_finto({
            "PortaleWeb/home": _RispostaFinta(200, text="<html></html>"),
            "initPortale": _RispostaFinta(200, text="{}"),
            "initLight": _RispostaFinta(200, text=""),
            "delegheUniche/deleganti": _RispostaFinta(
                403, text="<H1>Access Denied</H1>"),
        })
        with self.assertRaises(sync.SincronizzazioneBloccata):
            sync.fetch_deleganti_raw(auth, log=lambda _m: None)

    def test_fetch_risposta_senza_campo_lista_solleva_errore(self):
        auth = self._auth_finto({
            "PortaleWeb/home": _RispostaFinta(200, text="<html></html>"),
            "initPortale": _RispostaFinta(200, text="{}"),
            "initLight": _RispostaFinta(200, text=""),
            "delegheUniche/deleganti": _RispostaFinta(200, {"errore": "boh"}),
        })
        with self.assertRaises(sync.SincronizzazioneBloccata):
            sync.fetch_deleganti_raw(auth, log=lambda _m: None)

    def test_fetch_json_invalido_solleva_sincronizzazione_bloccata(self):
        auth = self._auth_finto({
            "PortaleWeb/home": _RispostaFinta(200, text="<html></html>"),
            "initPortale": _RispostaFinta(200, text="{}"),
            "initLight": _RispostaFinta(200, text=""),
            "delegheUniche/deleganti": _RispostaFinta(200, json_data=None),
        })
        with self.assertRaises(sync.SincronizzazioneBloccata):
            sync.fetch_deleganti_raw(auth, log=lambda _m: None)


if __name__ == "__main__":
    unittest.main()
