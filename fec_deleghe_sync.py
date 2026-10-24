#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""
fec_deleghe_sync.py - Sincronizzazione dell'anagrafica deleghe direttamente dal
portale Deleghe di Agenzia delle Entrate (portale.agenziaentrate.gov.it), invece
del CSV "Elenco deleganti" da caricare a mano (fec_deleghe.import_csv_ade).

Endpoint (scoperto da cattura HAR): POST delegheUniche/deleganti sul dominio
apptel.agenziaentrate.gov.it, condiviso con Cassetto Fiscale e Agenzia Entrate
Riscossione - lo stesso elenco riporta anche le deleghe di riscossione, filtrate
qui fuori tramite `servizi[].idServizio`. Il fetch grezzo (`fetch_deleganti_raw`,
vedi più sotto) resta quindi utilizzabile anche per servizi diversi da
Fatture&Corrispettivi.

Modulo di solo data layer (nessuna dipendenza da Tk).
"""

from __future__ import annotations

__version__ = "0.04 dev"

import json
from datetime import datetime
from types import SimpleNamespace

import requests

# Codici servizio rilevanti per Fatture&Corrispettivi (vedi fec_deleghe.SERVIZIO_FATTURE
# per il vecchio filtro testuale sul CSV): I42 = consultazione/acquisizione fatture,
# I31 = fatturazione elettronica e conservazione.
SERVIZI_RILEVANTI = ("I42", "I31")

PORTALE = "https://portale.agenziaentrate.gov.it"
APPTEL = "https://apptel.agenziaentrate.gov.it"
DELEGANTI_URL = f"{APPTEL}/deleghe-portale-rest/rs/delegheUniche/deleganti"

# Il portale rinnova `x-appl` a ogni passaggio di sessione e lo restituisce
# nell'header delle risposte (initPortale, poi initLight di apptel): un valore
# vecchio fa rispondere 403 a delegheUniche/deleganti. Questo è solo il ripiego
# quando nessuna risposta lo porta.
X_APPL_DELEGHE_DEFAULT = "8b4242aff2c22e1addf87b79b101788f656151"

_HTTP_TIMEOUT = (15, 60)


def _parse_data_it(s: str):
    """GG/MM/AAAA -> datetime, o None se vuota/non valida (date come "07/06/10007"
    compaiono nel campione reale per deleghe senza vera scadenza: non valide per
    strptime, trattate come "nessuna data")."""
    try:
        return datetime.strptime((s or "").strip(), "%d/%m/%Y")
    except (ValueError, AttributeError):
        return None


def _e_rilevante(record: dict) -> bool:
    return any(s.get("idServizio") in SERVIZI_RILEVANTI
              for s in record.get("servizi") or [])


def elabora_deleganti(lista_grezza: list[dict], *, soglia_data: str = "") -> list[dict]:
    """
    Filtra la lista grezza di delegheUniche/deleganti sui soli servizi rilevanti
    per Fatture&Corrispettivi (SERVIZI_RILEVANTI), aggrega più record dello stesso
    cfDelegante in una riga (data_fine_delega = la più lontana), e ritorna righe
    compatibili con fec_deleghe.FIELDS (solo denominazione/codice_fiscale/
    data_fine_delega valorizzati - gli altri campi sono responsabilità del merge
    in fec_deleghe.upsert, che li lascia intatti su un CF già noto).

    `soglia_data` (GG/MM/AAAA, opzionale): se valorizzata, scarta i record con
    `dataInizioDel` precedente. Non tocca l'aggregazione: un CF con più record,
    di cui solo alcuni sotto soglia, aggrega comunque tutti quelli SOPRA soglia.
    """
    soglia = _parse_data_it(soglia_data) if soglia_data else None

    aggregati: dict[str, dict] = {}
    for record in lista_grezza:
        if not _e_rilevante(record):
            continue
        inizio = _parse_data_it(record.get("dataInizioDel", ""))
        if soglia is not None and (inizio is None or inizio < soglia):
            continue
        cf = str(record.get("cfDelegante", "")).strip().upper()
        if not cf:
            continue
        entry = aggregati.setdefault(cf, {
            "denominazione": str(record.get("denomDelegante", "")).strip(),
            "fine": None,
        })
        if not entry["denominazione"]:
            entry["denominazione"] = str(record.get("denomDelegante", "")).strip()
        fine = _parse_data_it(record.get("dataFineDel", ""))
        if fine and (entry["fine"] is None or fine > entry["fine"]):
            entry["fine"] = fine

    return [{
        "codice_fiscale": cf,
        "denominazione": dati["denominazione"],
        "data_fine_delega": dati["fine"].strftime("%d/%m/%Y") if dati["fine"] else "",
    } for cf, dati in aggregati.items()]


def _unix_time() -> str:
    import time
    return str(int(time.time() * 1000))


def _headers_apptel(x_appl: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": PORTALE,
        "Referer": f"{PORTALE}/",
        "x-appl": x_appl,
    }


def _x_appl(risposta, precedente: str) -> str:
    """`x-appl` restituito da una risposta, o `precedente` se non c'è."""
    valore = (getattr(risposta, "headers", None) or {}).get("x-appl") or ""
    return valore.strip() or precedente


class SincronizzazioneBloccata(RuntimeError):
    """Il fetch via requests è stato rifiutato (probabile blocco anti-bot Akamai
    sul dominio apptel/portale-rest) o ha risposto in una forma inattesa."""


def _bootstrap_portale(session: requests.Session, log) -> str:
    """Visita la home del portale (non quella di Fatture e Corrispettivi) e
    initPortale, che impostano i cookie di sessione del portale Deleghe (la prima
    initPortale può rispondere 501 ma imposta comunque i cookie). Ritorna l'x-appl
    restituito, o il ripiego."""
    session.get(f"{PORTALE}/PortaleWeb/home", verify=False, timeout=_HTTP_TIMEOUT)
    x_appl = X_APPL_DELEGHE_DEFAULT
    for _ in range(2):
        r = session.get(f"{PORTALE}/portale-rest/rs/initPortale?v={_unix_time()}",
                        verify=False, timeout=_HTTP_TIMEOUT)
        x_appl = _x_appl(r, x_appl)
        if r.status_code == 200:
            break
    log("Bootstrap portale Deleghe completato.")
    return x_appl


def _utenza_studio(session: requests.Session, cf_studio: str, x_appl: str, log) -> str:
    """Porta l'utenza di lavoro del portale sullo studio, come «Cambia utenza»: dopo
    il login è la persona che accede, e per lei l'elenco deleganti è vuoto. Ritorna
    l'x-appl aggiornato. Senza `cf_studio`, o se non è tra gli incarichi, resta
    sull'utenza personale."""
    cf_studio = (cf_studio or "").strip().upper()
    if not cf_studio:
        return x_appl
    r = session.get(f"{PORTALE}/portale-rest/rs/listaIncarichi?v={_unix_time()}",
                    headers=_headers_apptel(x_appl), verify=False, timeout=_HTTP_TIMEOUT)
    x_appl = _x_appl(r, x_appl)
    try:
        incarichi = (r.json() or {}).get("listaIncarichi") or []
    except ValueError:
        incarichi = []
    chiave = next((str(i.get("chiave", "")) for i in incarichi
                   if str(i.get("codicefiscale", "")).strip().upper() == cf_studio), "")
    if not chiave:
        log(f"⚠️  Lo studio {cf_studio} non è tra gli incarichi dell'utente: resto "
            "sull'utenza personale.")
        return x_appl
    if chiave.upper() == cf_studio:      # lo studio è l'utente stesso: niente da cambiare
        return x_appl
    r = session.post(f"{PORTALE}/portale-rest/rs/cambiautenza?v={_unix_time()}",
                     headers=_headers_apptel(x_appl),
                     data=json.dumps({"chiave": chiave, "typeRole": "2"}),
                     verify=False, timeout=_HTTP_TIMEOUT)
    # Il portale risponde 409 anche quando il cambio riesce (verificato dalle
    # infouser successive in una cattura reale).
    if r.status_code not in (200, 204, 409):
        raise SincronizzazioneBloccata(
            f"Cambio dell'utenza di lavoro sullo studio {cf_studio} rifiutato "
            f"(HTTP {r.status_code}).")
    x_appl = _x_appl(r, x_appl)
    r = session.get(f"{PORTALE}/portale-rest/rs/initPortale?v={_unix_time()}",
                    headers=_headers_apptel(x_appl), verify=False, timeout=_HTTP_TIMEOUT)
    log(f"Utenza di lavoro: studio {cf_studio}.")
    return _x_appl(r, x_appl)


def fetch_deleganti_raw(auth, *, cf_studio: str = "", log=print) -> list[dict]:
    """
    Tenta di ottenere l'elenco grezzo delle deleghe (tutti i servizi, non solo
    Fatture&Corrispettivi - vedi SERVIZI_RILEVANTI/elabora_deleganti per il
    filtro) riusando la sessione `requests` già autenticata in `auth.session`
    (funziona con qualunque backend di login: entrambi producono un
    `requests.Session`).

    Solleva `SincronizzazioneBloccata` se una qualunque chiamata risponde in modo
    inatteso (status diverso da 200, corpo non JSON, campo "lista" assente) - il
    chiamante decide se ripiegare sul backend browser (vedi `sincronizza`).
    """
    session = auth.session
    try:
        x_appl = _bootstrap_portale(session, log)
        x_appl = _utenza_studio(session, cf_studio, x_appl, log)
        r_init = session.get(f"{APPTEL}/deleghe-portale-rest/rs/initLight?v={_unix_time()}",
                             headers=_headers_apptel(x_appl), verify=False,
                             timeout=_HTTP_TIMEOUT)
        x_appl = _x_appl(r_init, x_appl)
        r = session.post(f"{DELEGANTI_URL}?v={_unix_time()}",
                        headers=_headers_apptel(x_appl), data='{"stato":"A"}',
                        verify=False, timeout=_HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise SincronizzazioneBloccata(f"Errore di rete: {exc}") from exc

    if r.status_code != 200:
        raise SincronizzazioneBloccata(
            f"Il portale ha risposto HTTP {r.status_code} all'elenco deleganti "
            f"(initLight apptel: HTTP {getattr(r_init, 'status_code', '?')}).")
    try:
        dati = r.json()
    except ValueError as exc:
        raise SincronizzazioneBloccata(
            "Risposta non in formato JSON (probabile pagina di blocco anti-bot "
            "invece dei dati).") from exc
    lista = dati.get("lista") if isinstance(dati, dict) else None
    if lista is None:
        raise SincronizzazioneBloccata(
            "La risposta non contiene il campo 'lista' atteso.")
    log(f"Elenco deleghe ottenuto via requests: {len(lista)} record.")
    if not lista:
        log("⚠️  Elenco vuoto: controlla che «CF Studio» nelle credenziali sia il codice "
            "fiscale dello studio delegato.")
    return lista


class PlaywrightNonDisponibile(RuntimeError):
    """Il fetch via requests è fallito (probabile blocco anti-bot) e Playwright
    non è installato: la sincronizzazione non è disponibile in questa
    installazione finché non si installa Playwright (ruolo "browser" in
    fec_deps.py)."""


def sincronizza(creds, *, log=print, forza_browser: bool = False) -> list[dict]:
    """
    Ottiene l'elenco grezzo delle deleghe (tutti i servizi) per il CF studio in
    `creds`, tentando prima il backend leggero `requests` (funziona solo se AdE
    non applica un blocco anti-bot alla sessione) e ripiegando in automatico sul
    backend browser (Playwright, richiede l'installazione) se il primo tentativo
    fallisce. Con `forza_browser=True` salta direttamente al backend browser.

    Solleva `ade_auth.AuthError` se il login fallisce (con entrambi i tentativi),
    `PlaywrightNonDisponibile` se il tentativo requests fallisce e Playwright non
    è installato.
    """
    import ade_auth
    import fec_deps

    cf_studio = getattr(creds, "cfstudio", "") or ""
    if not forza_browser:
        log("Sincronizzazione deleghe: provo il backend leggero (requests)...")
        try:
            # Le Deleghe stanno sul portale: niente scelta utenza di Fatture e
            # Corrispettivi, che costava tempo e non serve.
            sessione = ade_auth.login_portale(creds, log=log)
            return fetch_deleganti_raw(SimpleNamespace(session=sessione),
                                       cf_studio=cf_studio, log=log)
        except (SincronizzazioneBloccata, ade_auth.AuthError) as exc:
            log(f"Backend requests non utilizzabile: {exc}")

    mancanti = fec_deps.find_missing().get("browser", [])
    if mancanti:
        raise PlaywrightNonDisponibile(
            "Il portale Deleghe ha bloccato il tentativo leggero e Playwright "
            f"non è installato ({', '.join(mancanti)}): installa Playwright per "
            "usare questa funzione, oppure importa le deleghe dal CSV manuale.")

    log("Riprovo con il backend browser (Playwright)...")
    auth = ade_auth.autentica(creds, backend="browser", headless=True, log=log)
    return fetch_deleganti_raw(auth, cf_studio=cf_studio, log=log)
