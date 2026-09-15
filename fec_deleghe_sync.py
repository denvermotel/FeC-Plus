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

from datetime import datetime
import requests

# Codici servizio rilevanti per Fatture&Corrispettivi (vedi fec_deleghe.SERVIZIO_FATTURE
# per il vecchio filtro testuale sul CSV): I42 = consultazione/acquisizione fatture,
# I31 = fatturazione elettronica e conservazione.
SERVIZI_RILEVANTI = ("I42", "I31")

PORTALE = "https://portale.agenziaentrate.gov.it"
APPTEL = "https://apptel.agenziaentrate.gov.it"
DELEGANTI_URL = f"{APPTEL}/deleghe-portale-rest/rs/delegheUniche/deleganti"

# Valore osservato in una cattura HAR reale del 2026-09-15: come X_APPL_DEFAULT in
# ade_auth.py, può cambiare a un redeploy AdE - in tal caso va ricatturato un HAR
# (pulsante Test Login -> "Cattura HAR generico", navigando fino al portale Deleghe).
X_APPL_DELEGHE_DEFAULT = "ad9ff8e015bfc8c2737e6ea0c5299518485b811"

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


def _headers_apptel() -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": PORTALE,
        "Referer": f"{PORTALE}/",
        "x-appl": X_APPL_DELEGHE_DEFAULT,
    }


class SincronizzazioneBloccata(RuntimeError):
    """Il fetch via requests è stato rifiutato (probabile blocco anti-bot Akamai
    sul dominio apptel/portale-rest) o ha risposto in una forma inattesa."""


def _bootstrap_portale(session: requests.Session, log) -> None:
    """Visita le pagine che, per il portale Deleghe, impostano i cookie di sessione
    necessari (stesso pattern già noto per ivaservizi in ade_auth: la prima
    initPortale può rispondere 501 ma imposta comunque i cookie)."""
    session.get(f"{PORTALE}/PortaleWeb/home?to=FATBTB", verify=False,
               timeout=_HTTP_TIMEOUT)
    for _ in range(2):
        r = session.get(f"{PORTALE}/portale-rest/rs/initPortale?v={_unix_time()}",
                        verify=False, timeout=_HTTP_TIMEOUT)
        if r.status_code == 200:
            break
    log("Bootstrap portale Deleghe completato.")


def fetch_deleganti_raw(auth, *, log=print) -> list[dict]:
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
        _bootstrap_portale(session, log)
        session.get(f"{APPTEL}/deleghe-portale-rest/rs/initLight?v={_unix_time()}",
                   headers=_headers_apptel(), verify=False, timeout=_HTTP_TIMEOUT)
        r = session.post(f"{DELEGANTI_URL}?v={_unix_time()}",
                        headers=_headers_apptel(), data='{"stato":"A"}',
                        verify=False, timeout=_HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise SincronizzazioneBloccata(f"Errore di rete: {exc}") from exc

    if r.status_code != 200:
        raise SincronizzazioneBloccata(
            f"Il portale ha risposto HTTP {r.status_code} (probabile blocco "
            "anti-bot): serve il backend browser per questa operazione.")
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

    if not forza_browser:
        log("Sincronizzazione deleghe: provo il backend leggero (requests)...")
        auth = ade_auth.autentica(creds, backend="requests", log=log)
        try:
            return fetch_deleganti_raw(auth, log=log)
        except SincronizzazioneBloccata as exc:
            log(f"Backend requests non utilizzabile: {exc}")

    mancanti = fec_deps.find_missing().get("browser", [])
    if mancanti:
        raise PlaywrightNonDisponibile(
            "Il portale Deleghe ha bloccato il tentativo leggero e Playwright "
            f"non è installato ({', '.join(mancanti)}): installa Playwright per "
            "usare questa funzione, oppure importa le deleghe dal CSV manuale.")

    log("Riprovo con il backend browser (Playwright)...")
    auth = ade_auth.autentica(creds, backend="browser", headless=True, log=log)
    return fetch_deleganti_raw(auth, log=log)
