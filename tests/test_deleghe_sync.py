#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test di fec_deleghe_sync.elabora_deleganti (parsing/aggregazione, offline)."""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

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
    def __init__(self, status_code, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self.headers = headers or {}

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

    def _x_appl_inviato(self, auth, metodo, frammento):
        chiamate = getattr(auth.session, metodo).call_args_list
        chiamata = next(c for c in chiamate if frammento in c.args[0])
        return chiamata.kwargs["headers"]["x-appl"]

    def test_x_appl_preso_dalle_risposte(self):
        # Il portale rinnova x-appl a ogni passaggio: initPortale lo passa a initLight
        # di apptel, che risponde con quello da usare per l'elenco deleganti.
        auth = self._auth_finto({
            "PortaleWeb/home": _RispostaFinta(200, text="<html></html>"),
            "initPortale": _RispostaFinta(200, text="{}", headers={"x-appl": "AAA"}),
            "initLight": _RispostaFinta(200, text="", headers={"x-appl": "BBB"}),
            "delegheUniche/deleganti": _RispostaFinta(200, {"lista": []}),
        })
        sync.fetch_deleganti_raw(auth, log=lambda _m: None)
        self.assertEqual(self._x_appl_inviato(auth, "get", "initLight"), "AAA")
        self.assertEqual(self._x_appl_inviato(auth, "post", "delegheUniche/deleganti"), "BBB")

    def test_x_appl_di_riserva_se_nessuna_risposta_lo_porta(self):
        auth = self._auth_finto({
            "PortaleWeb/home": _RispostaFinta(200, text="<html></html>"),
            "initPortale": _RispostaFinta(200, text="{}"),
            "initLight": _RispostaFinta(200, text=""),
            "delegheUniche/deleganti": _RispostaFinta(200, {"lista": []}),
        })
        sync.fetch_deleganti_raw(auth, log=lambda _m: None)
        self.assertEqual(self._x_appl_inviato(auth, "post", "delegheUniche/deleganti"),
                         sync.X_APPL_DELEGHE_DEFAULT)

    def test_bootstrap_dalla_home_del_portale_non_da_fatture(self):
        auth = self._auth_finto({
            "PortaleWeb/home": _RispostaFinta(200, text="<html></html>"),
            "initPortale": _RispostaFinta(200, text="{}"),
            "initLight": _RispostaFinta(200, text=""),
            "delegheUniche/deleganti": _RispostaFinta(200, {"lista": []}),
        })
        sync.fetch_deleganti_raw(auth, log=lambda _m: None)
        url = [c.args[0] for c in auth.session.get.call_args_list]
        self.assertTrue(any("PortaleWeb/home" in u for u in url))
        self.assertFalse(any("FATBTB" in u for u in url))

    def _risposte_con_incarichi(self, cambio_status=409):
        return {
            "PortaleWeb/home": _RispostaFinta(200, text="<html></html>"),
            "listaIncarichi": _RispostaFinta(200, {"listaIncarichi": [
                {"chiave": "T0000001", "codicefiscale": "01234567890", "sede": "000",
                 "tipoIncarico": "GESTORE", "stato": "1"},
                {"chiave": "RSSMRA80A01H501U", "codicefiscale": "RSSMRA80A01H501U",
                 "sede": "FOL"},
            ]}, headers={"x-appl": "INC"}),
            "rs/cambiautenza": _RispostaFinta(cambio_status, text="",
                                              headers={"x-appl": "CAMBIO"}),
            "initPortale": _RispostaFinta(200, text="{}", headers={"x-appl": "AAA"}),
            "initLight": _RispostaFinta(200, text=""),
            "delegheUniche/deleganti": _RispostaFinta(200, {"lista": [{"cfDelegante": "X"}]}),
        }

    def test_passa_all_utenza_dello_studio_prima_delle_deleghe(self):
        # Dopo il login l'utenza di lavoro è la persona: le Deleghe restituiscono
        # l'elenco dello studio solo dopo «Cambia utenza» sull'incarico dello studio.
        auth = self._auth_finto(self._risposte_con_incarichi())
        lista = sync.fetch_deleganti_raw(auth, cf_studio=" 01234567890 ",
                                         log=lambda _m: None)
        self.assertEqual(lista, [{"cfDelegante": "X"}])
        post = [c for c in auth.session.post.call_args_list if "rs/cambiautenza" in c.args[0]]
        self.assertEqual(len(post), 1)
        self.assertEqual(json.loads(post[0].kwargs["data"]),
                         {"chiave": "T0000001", "typeRole": "2"})
        url = [c.args[0] for c in auth.session.mock_calls if c.args]
        cambio = next(i for i, u in enumerate(url) if "rs/cambiautenza" in u)
        deleganti = next(i for i, u in enumerate(url) if "delegheUniche/deleganti" in u)
        self.assertLess(cambio, deleganti)

    def test_cambio_utenza_accetta_anche_200(self):
        auth = self._auth_finto(self._risposte_con_incarichi(cambio_status=200))
        self.assertEqual(sync.fetch_deleganti_raw(auth, cf_studio="01234567890",
                                                  log=lambda _m: None),
                         [{"cfDelegante": "X"}])

    def test_cambio_utenza_rifiutato_solleva_errore(self):
        auth = self._auth_finto(self._risposte_con_incarichi(cambio_status=403))
        with self.assertRaises(sync.SincronizzazioneBloccata) as ctx:
            sync.fetch_deleganti_raw(auth, cf_studio="01234567890", log=lambda _m: None)
        self.assertIn("utenza", str(ctx.exception))

    def test_studio_non_tra_gli_incarichi_resta_sull_utenza_personale(self):
        righe = []
        auth = self._auth_finto(self._risposte_con_incarichi())
        sync.fetch_deleganti_raw(auth, cf_studio="99999999999", log=righe.append)
        self.assertFalse(any("rs/cambiautenza" in c.args[0]
                             for c in auth.session.post.call_args_list))
        self.assertTrue(any("99999999999" in r for r in righe))

    def test_senza_cf_studio_nessun_cambio_utenza(self):
        auth = self._auth_finto(self._risposte_con_incarichi())
        sync.fetch_deleganti_raw(auth, log=lambda _m: None)
        self.assertFalse(any("listaIncarichi" in c.args[0]
                             for c in auth.session.get.call_args_list))

    def test_403_dice_quale_chiamata_ha_rifiutato(self):
        auth = self._auth_finto({
            "PortaleWeb/home": _RispostaFinta(200, text="<html></html>"),
            "initPortale": _RispostaFinta(200, text="{}"),
            "initLight": _RispostaFinta(200, text=""),
            "delegheUniche/deleganti": _RispostaFinta(403, text="<H1>Access Denied</H1>"),
        })
        with self.assertRaises(sync.SincronizzazioneBloccata) as ctx:
            sync.fetch_deleganti_raw(auth, log=lambda _m: None)
        self.assertIn("403", str(ctx.exception))
        self.assertIn("deleganti", str(ctx.exception))

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


class TestSincronizza(unittest.TestCase):
    """Il tentativo leggero entra dal login del portale (`ade_auth.login_portale`,
    senza la scelta utenza di Fatture e Corrispettivi); il ripiego resta il backend
    browser di `ade_auth.autentica`."""

    @patch("fec_deleghe_sync.fetch_deleganti_raw")
    @patch("ade_auth.autentica")
    @patch("ade_auth.login_portale")
    def test_successo_al_primo_tentativo_requests(self, mock_login, mock_autentica,
                                                   mock_fetch):
        sessione = MagicMock()
        mock_login.return_value = sessione
        mock_fetch.return_value = [{"cfDelegante": "X"}]

        risultato = sync.sincronizza(MagicMock(cfstudio="01234567890"), log=lambda _m: None)

        self.assertEqual(risultato, [{"cfDelegante": "X"}])
        mock_login.assert_called_once()
        mock_autentica.assert_not_called()
        self.assertIs(mock_fetch.call_args.args[0].session, sessione)
        self.assertEqual(mock_fetch.call_args.kwargs["cf_studio"], "01234567890")

    @patch("fec_deps.find_missing")
    @patch("fec_deleghe_sync.fetch_deleganti_raw")
    @patch("ade_auth.autentica")
    @patch("ade_auth.login_portale")
    def test_fallback_browser_se_requests_bloccato(
            self, mock_login, mock_autentica, mock_fetch, mock_missing):
        mock_missing.return_value = {"browser": []}  # Playwright installato
        mock_autentica.return_value = MagicMock()
        mock_fetch.side_effect = [
            sync.SincronizzazioneBloccata("bloccato"),
            [{"cfDelegante": "Y"}],
        ]

        risultato = sync.sincronizza(MagicMock(), log=lambda _m: None)

        self.assertEqual(risultato, [{"cfDelegante": "Y"}])
        mock_login.assert_called_once()
        mock_autentica.assert_called_once()
        self.assertEqual(mock_autentica.call_args.kwargs.get("backend"), "browser")

    @patch("fec_deps.find_missing")
    @patch("fec_deleghe_sync.fetch_deleganti_raw")
    @patch("ade_auth.autentica")
    @patch("ade_auth.login_portale")
    def test_playwright_non_disponibile_se_requests_fallisce_e_manca_browser(
            self, mock_login, mock_autentica, mock_fetch, mock_missing):
        mock_missing.return_value = {"browser": ["playwright"]}  # NON installato
        mock_fetch.side_effect = sync.SincronizzazioneBloccata("bloccato")

        with self.assertRaises(sync.PlaywrightNonDisponibile):
            sync.sincronizza(MagicMock(), log=lambda _m: None)
        mock_autentica.assert_not_called()  # niente secondo tentativo

    @patch("fec_deps.find_missing")
    @patch("fec_deleghe_sync.fetch_deleganti_raw")
    @patch("ade_auth.autentica")
    @patch("ade_auth.login_portale")
    def test_forza_browser_salta_il_tentativo_requests(
            self, mock_login, mock_autentica, mock_fetch, mock_missing):
        mock_missing.return_value = {"browser": []}  # Playwright installato
        mock_autentica.return_value = MagicMock()
        mock_fetch.return_value = [{"cfDelegante": "Z"}]

        sync.sincronizza(MagicMock(), log=lambda _m: None, forza_browser=True)

        mock_login.assert_not_called()
        mock_autentica.assert_called_once()
        self.assertEqual(mock_autentica.call_args.kwargs.get("backend"), "browser")

    @patch("fec_deps.find_missing")
    @patch("fec_deleghe_sync.fetch_deleganti_raw")
    @patch("ade_auth.autentica")
    @patch("ade_auth.login_portale")
    def test_fallback_browser_se_login_requests_fallisce(
            self, mock_login, mock_autentica, mock_fetch, mock_missing):
        # Il blocco anti-bot puo' colpire gia' il login: anche un AuthError del
        # tentativo leggero fa scattare il ripiego sul browser.
        from ade_auth import AuthError
        mock_missing.return_value = {"browser": []}  # Playwright installato
        mock_login.side_effect = AuthError("login", "bloccato")
        mock_autentica.return_value = MagicMock()
        mock_fetch.return_value = [{"cfDelegante": "Y"}]

        risultato = sync.sincronizza(MagicMock(), log=lambda _m: None)

        self.assertEqual(risultato, [{"cfDelegante": "Y"}])
        mock_autentica.assert_called_once()
        mock_fetch.assert_called_once()  # solo dopo il login riuscito sul browser

    @patch("fec_deps.find_missing")
    @patch("fec_deleghe_sync.fetch_deleganti_raw")
    @patch("ade_auth.autentica")
    @patch("ade_auth.login_portale")
    def test_login_fallisce_anche_su_browser_propaga_autherror(
            self, mock_login, mock_autentica, mock_fetch, mock_missing):
        from ade_auth import AuthError
        mock_missing.return_value = {"browser": []}  # Playwright installato
        mock_login.side_effect = AuthError("login", "bloccato requests")
        mock_autentica.side_effect = AuthError("login", "bloccato anche browser")

        with self.assertRaises(AuthError):
            sync.sincronizza(MagicMock(), log=lambda _m: None)
        mock_fetch.assert_not_called()


class TestLoginPortale(unittest.TestCase):
    """`ade_auth.login_portale`: login telematico con ritorno alla home del
    portale, senza scelta utenza di Fatture e Corrispettivi."""

    def _sessione(self, login_ok=True):
        import ade_auth
        s = MagicMock()
        s.headers = {}
        cookie = {"SIAMPE": "x"} if login_ok else {}
        s.cookies.get_dict.return_value = cookie
        s.post.return_value = _RispostaFinta(200 if login_ok else 401,
                                             json_data={} if login_ok else {"error": "no"})
        s.get.return_value = _RispostaFinta(200, text="")
        return s, ade_auth

    def test_login_poi_home_del_portale(self):
        s, ade_auth = self._sessione()
        with patch.object(ade_auth, "_nuova_sessione", return_value=s):
            risultato = ade_auth.login_portale(MagicMock(nomeutente="U", password="P",
                                                         pin="1"), log=lambda _m: None)
        self.assertIs(risultato, s)
        self.assertEqual(s.post.call_args.args[0], ade_auth.LOGIN_API)
        url = [c.args[0] for c in s.get.call_args_list]
        self.assertIn(ade_auth.PORTALE_LOGIN_URL, url)
        self.assertTrue(any(u.endswith("/PortaleWeb/home") for u in url))
        self.assertFalse(any("FATBTB" in u or "ivaservizi" in u for u in url))

    def test_credenziali_rifiutate_autherror(self):
        s, ade_auth = self._sessione(login_ok=False)
        with patch.object(ade_auth, "_nuova_sessione", return_value=s):
            with self.assertRaises(ade_auth.AuthError):
                ade_auth.login_portale(MagicMock(nomeutente="U", password="P", pin="1"),
                                       log=lambda _m: None)


if __name__ == "__main__":
    unittest.main()
