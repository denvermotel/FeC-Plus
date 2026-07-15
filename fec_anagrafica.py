#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.03 alpha
"""
fec_anagrafica.py - Recupero dei dati anagrafici del cliente dal portale AdE, a partire
da una sessione GIÀ autenticata (`AuthResult` di ade_auth), e confronto con l'anagrafica
locale delle deleghe (fec_deleghe).

Serve al flusso «solo codice fiscale»: dopo il login su un CF, si ricavano da AdE
denominazione, P.IVA, conservazione dati fattura e codice destinatario/canale SDI, per
poter aggiornare il database deleghe proponendo all'utente i soli campi variati.

Fonti dati (tutte REST, nessuno scraping HTML):
  - denominazione / P.IVA / CF -> GET /instr/instradamento-fatture-rest/rs/fullTemplate
    (`infoBenvenuto`); in gran parte già presenti in `AuthResult` (da setUserChoice).
  - conservazione dati fattura -> GET /ser/api/fatture/v1/ul/me/adesione/stato
    (HTTP 200 con `nuovaAdesione == true` e `revoca == false` ⇒ attiva; 404 ⇒ non attiva).
  - codice destinatario / canale SDI -> GET /ser/api/censimenti/v1/registrazione/censimenti
    (campo `indirizzoStandard` quando `tipoIndirizzoStandard == "CODICE"`; 403/PEC ⇒ vuoto).

Modulo di solo data layer.
"""

from __future__ import annotations

__version__ = "0.03 alpha"

from datetime import date

import requests

from ade_auth import IVASERVIZI, INSTR_REST, X_APPL_DEFAULT, unix_time, _UA

# Endpoint del servizio di censimento indirizzo telematico (codice/canale SDI).
# NB: il segmento finale «censimenti» è nel path (dal config del webapp AngularJS:
# CENSIMENTI = "/ser/api/censimenti/v1/registrazione/" + "censimenti").
CENSIMENTI_URL = f"{IVASERVIZI}/ser/api/censimenti/v1/registrazione/censimenti"
# Stato adesione alla conservazione dati fattura (Profilo fatturazione).
ADESIONE_URL = f"{IVASERVIZI}/ser/api/fatture/v1/ul/me/adesione/stato"
FULLTEMPLATE_URL = f"{INSTR_REST}/fullTemplate"

# Campi dell'anagrafica delega ricavabili da AdE (allineati a fec_deleghe.FIELDS).
CAMPI_ADE = ("denominazione", "partita_iva", "conservazione", "codice_destinatario")

# Etichette leggibili per il popup di aggiornamento.
ETICHETTE = {
    "denominazione": "Denominazione",
    "partita_iva": "Partita IVA",
    "conservazione": "Conservazione",
    "codice_destinatario": "Codice destinatario (SDI)",
}

_HTTP_TIMEOUT = (15, 30)


def _headers_ser(auth) -> dict:
    """Header minimi per le API /ser/api/... (autorizzate dai cookie di sessione)."""
    return {
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{IVASERVIZI}/cons/cons-web/",
        "User-Agent": _UA,
    }


def _fetch_conservazione(auth) -> bool:
    """
    Stato conservazione dati fattura: GET adesione/stato. Attiva se HTTP 200 con
    `nuovaAdesione == true` e `revoca == false` (come mostra la home «Profilo
    fatturazione»). 404/errore ⇒ non attiva.
    """
    try:
        r = auth.session.get(ADESIONE_URL, headers=_headers_ser(auth),
                             verify=False, timeout=_HTTP_TIMEOUT)
        if r.status_code != 200:
            return False
        d = r.json() or {}
    except (requests.RequestException, ValueError):
        return False
    return bool(d.get("nuovaAdesione")) and not bool(d.get("revoca"))


def _fetch_full_template(auth) -> dict:
    """GET fullTemplate → dict `infoBenvenuto` (denominazione/piva/cf), o {} best-effort."""
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": IVASERVIZI,
        "Referer": f"{IVASERVIZI}/instr/InstradamentofcWeb/home",
        "x-appl": X_APPL_DEFAULT,
    }
    try:
        r = auth.session.get(f"{FULLTEMPLATE_URL}?v={unix_time()}", headers=headers,
                             verify=False, timeout=_HTTP_TIMEOUT)
        return (r.json() or {}).get("infoBenvenuto") or {}
    except (requests.RequestException, ValueError):
        return {}


def _fetch_codice_destinatario(auth) -> str:
    """
    GET censimenti/registrazione → codice destinatario SDI se registrato come «CODICE»
    (es. `W7YVJK9`). Ritorna "" per PEC, non registrato, non autorizzato o errore.
    """
    try:
        r = auth.session.get(f"{CENSIMENTI_URL}?v={date.today().isoformat()}",
                             headers=_headers_ser(auth), verify=False, timeout=_HTTP_TIMEOUT)
        if r.status_code != 200:
            return ""
        dati = r.json() or {}
    except (requests.RequestException, ValueError):
        return ""
    if str(dati.get("stato", "")) == "403":
        return ""
    if str(dati.get("tipoIndirizzoStandard", "")).upper() == "CODICE":
        return str(dati.get("indirizzoStandard", "") or "").strip()
    return ""


def recupera(auth, log=None) -> dict:
    """
    Ricava i dati anagrafici del cliente attivo come utenza di lavoro in `auth`.

    Ritorna un dict con le chiavi di fec_deleghe: `codice_fiscale`, `denominazione`,
    `partita_iva`, `conservazione` (bool), `codice_destinatario`. I campi non ottenibili
    restano vuoti (stringa vuota / False): ogni recupero è best-effort.
    """
    dati = {
        "codice_fiscale": "",
        "denominazione": (getattr(auth, "denominazione", "") or "").strip(),
        "partita_iva": (getattr(auth, "piva", "") or "").strip(),
        "conservazione": False,
        "codice_destinatario": "",
    }

    info = _fetch_full_template(auth)
    if info:
        dati["codice_fiscale"] = str(info.get("cfUtenteDiLavoro", "") or "").strip()
        if info.get("denominazioneUtenteDiLavoro"):
            dati["denominazione"] = str(info["denominazioneUtenteDiLavoro"]).strip()
        if info.get("pivaUtenteDiLavoro"):
            dati["partita_iva"] = str(info["pivaUtenteDiLavoro"]).strip()

    dati["conservazione"] = _fetch_conservazione(auth)
    dati["codice_destinatario"] = _fetch_codice_destinatario(auth)

    if log:
        log(f"Anagrafica AdE: denominazione={dati['denominazione']!r} "
            f"piva={dati['partita_iva']!r} conservazione={dati['conservazione']} "
            f"SDI={dati['codice_destinatario'] or '-'}")
    return dati


def differenze(saved_row: dict, dati_ade: dict, fields=CAMPI_ADE) -> dict:
    """
    Confronta l'anagrafica salvata con quella ricavata da AdE e ritorna i soli campi
    VARIATI come `{campo: (valore_salvato, valore_ade)}`.

    Regole: per i campi testuali si ignorano i valori vuoti forniti da AdE (non si
    propone di cancellare un dato). P.IVA e codice destinatario si confrontano in
    maiuscolo (come li normalizza fec_deleghe). `conservazione` è un bool e si propone
    ogni volta che differisce.
    """
    diffs: dict = {}
    for k in fields:
        nuovo = dati_ade.get(k)
        if k == "conservazione":
            nuovo_b, vecchio_b = bool(nuovo), bool(saved_row.get(k, False))
            if nuovo_b != vecchio_b:
                diffs[k] = (vecchio_b, nuovo_b)
            continue
        nuovo_s = str(nuovo or "").strip()
        if not nuovo_s:
            continue  # AdE non ha fornito il dato → non proporre
        vecchio_s = str(saved_row.get(k, "") or "").strip()
        if k in ("partita_iva", "codice_destinatario"):
            nuovo_s = nuovo_s.upper()
            if nuovo_s != vecchio_s.upper():
                diffs[k] = (vecchio_s, nuovo_s)
        elif nuovo_s != vecchio_s:
            diffs[k] = (vecchio_s, nuovo_s)
    return diffs
