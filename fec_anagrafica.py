#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
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
  - canale forniture massive -> GET /sm/sm-censimento-puntuale-rest/api/me/canali/providers
    (elenco dei provider censiti per lo scarico massivo di fatture/corrispettivi/bollo/IVA
    precompilata senza portale; riepilogo testuale di denominazione + servizi abilitati per
    provider, vuoto se nessun canale censito o chiamata non autorizzata).

Modulo di solo data layer.
"""

from __future__ import annotations

__version__ = "0.04 dev"

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
# Provider censiti per lo scarico massivo (pagina «Censimento canale per forniture
# massive»), ricavato dai bundle JS della webapp (`doAjaxMassivo`... in realtà il
# servizio usato da quella pagina è «puntuale», non «massivo»: base
# /sm/sm-censimento-puntuale-rest/api, endpoint GET /me/canali/providers).
CANALI_MASSIVO_URL = f"{IVASERVIZI}/sm/sm-censimento-puntuale-rest/api/me/canali/providers"

# Campi dell'anagrafica delega ricavabili da AdE (allineati a fec_deleghe.FIELDS).
CAMPI_ADE = ("denominazione", "partita_iva", "conservazione", "codice_destinatario", "pec",
             "canale_massivo")

# Etichette leggibili per il popup di aggiornamento.
ETICHETTE = {
    "denominazione": "Denominazione",
    "partita_iva": "Partita IVA",
    "conservazione": "Conservazione",
    "codice_destinatario": "Codice destinatario (SDI)",
    "pec": "PEC",
    "canale_massivo": "Canale forniture massive",
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


def _fetch_canale(auth) -> tuple[str, str]:
    """
    GET censimenti/registrazione → canale di ricezione delle fatture, come coppia
    `(codice_destinatario, pec)`: sono mutuamente esclusivi, uno solo è valorizzato.

    Ramo «CODICE» → codice destinatario SDI (es. `W7YVJK9`), pec "".
    Ramo «PEC»    → indirizzo PEC in `indirizzoStandard`, codice "".
    Ritorna ("", "") per non registrato, non autorizzato (403) o errore.
    """
    try:
        r = auth.session.get(f"{CENSIMENTI_URL}?v={date.today().isoformat()}",
                             headers=_headers_ser(auth), verify=False, timeout=_HTTP_TIMEOUT)
        if r.status_code != 200:
            return "", ""
        dati = r.json() or {}
    except (requests.RequestException, ValueError):
        return "", ""
    if str(dati.get("stato", "")) == "403":
        return "", ""
    tipo = str(dati.get("tipoIndirizzoStandard", "")).upper()
    indirizzo = str(dati.get("indirizzoStandard", "") or "").strip()
    if tipo == "CODICE":
        return indirizzo, ""
    if tipo == "PEC":
        return "", indirizzo
    return "", ""


def _fetch_canale_massivo(auth) -> str:
    """
    Riepilogo dei canali censiti per lo scarico massivo (fatture, corrispettivi, bollo,
    IVA precompilata) senza passare dal portale: GET /me/canali/providers.

    Ogni provider censito ha una denominazione e un elenco di servizi abilitati; li
    concateno in una riga per provider (`Denominazione (SERVIZIO, SERVIZIO, ...)`), più
    provider uniti da «; ». Nessun provider censito (200 con lista vuota) o chiamata non
    autorizzata/errore ⇒ "" (best-effort, mai eccezioni).
    """
    try:
        r = auth.session.get(CANALI_MASSIVO_URL, headers=_headers_ser(auth),
                             verify=False, timeout=_HTTP_TIMEOUT)
        if r.status_code != 200:
            return ""
        providers = r.json() or []
    except (requests.RequestException, ValueError):
        return ""
    if not isinstance(providers, list):
        return ""
    righe = []
    for p in providers:
        if not isinstance(p, dict):
            continue
        # `denominazione` è la ragione sociale del fornitore del servizio (es. "Sistemi
        # S.p.a."), quella mostrata dal portale in colonna «Denominazione». Non va
        # confusa con `denominazioneCanale`, che è il tipo di canale (es. "WebService",
        # colonna «Tipo canale») - non identifica il fornitore.
        nome = str(p.get("denominazione") or "").strip()
        servizi = p.get("tipologiaServizi") or p.get("servizi") or []
        if isinstance(servizi, list):
            servizi_s = ", ".join(str(s).strip() for s in servizi if str(s).strip())
        else:
            servizi_s = str(servizi or "").strip()
        if nome and servizi_s:
            righe.append(f"{nome} ({servizi_s})")
        elif nome:
            righe.append(nome)
    return "; ".join(righe)


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
        "pec": "",
        "canale_massivo": "",
    }

    info = _fetch_full_template(auth)
    if info:
        dati["codice_fiscale"] = str(info.get("cfUtenteDiLavoro", "") or "").strip()
        if info.get("denominazioneUtenteDiLavoro"):
            dati["denominazione"] = str(info["denominazioneUtenteDiLavoro"]).strip()
        if info.get("pivaUtenteDiLavoro"):
            dati["partita_iva"] = str(info["pivaUtenteDiLavoro"]).strip()

    dati["conservazione"] = _fetch_conservazione(auth)
    dati["codice_destinatario"], dati["pec"] = _fetch_canale(auth)
    dati["canale_massivo"] = _fetch_canale_massivo(auth)

    if log:
        canale = (f"SDI={dati['codice_destinatario']}" if dati["codice_destinatario"]
                  else f"PEC={dati['pec']}" if dati["pec"] else "canale=-")
        log(f"Anagrafica AdE: denominazione={dati['denominazione']!r} "
            f"piva={dati['partita_iva']!r} conservazione={dati['conservazione']} {canale} "
            f"canale_massivo={dati['canale_massivo']!r}")
    return dati


# I due canali di ricezione, trattati come coppia mutuamente esclusiva in `differenze`.
_CANALE = ("codice_destinatario", "pec")


def differenze(saved_row: dict, dati_ade: dict, fields=CAMPI_ADE) -> dict:
    """
    Confronta l'anagrafica salvata con quella ricavata da AdE e ritorna i soli campi
    VARIATI come `{campo: (valore_salvato, valore_ade)}`.

    Regole: per i campi testuali si ignorano i valori vuoti forniti da AdE (non si
    propone di cancellare un dato). P.IVA e codice destinatario si confrontano in
    maiuscolo (come li normalizza fec_deleghe). `conservazione` è un bool e si propone
    ogni volta che differisce.

    Eccezione: `codice_destinatario` e `pec` sono i due canali di ricezione, mutuamente
    esclusivi. Se AdE ha riportato un canale (almeno uno dei due valorizzato), si propone
    di impostare quello attivo **e azzerare l'altro**; se AdE non ha letto alcun canale
    (entrambi vuoti) non si tocca nulla.
    """
    diffs: dict = {}
    for k in fields:
        if k in _CANALE:
            continue  # gestiti insieme sotto
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
        if k == "partita_iva":
            nuovo_s = nuovo_s.upper()
            if nuovo_s != vecchio_s.upper():
                diffs[k] = (vecchio_s, nuovo_s)
        elif nuovo_s != vecchio_s:
            diffs[k] = (vecchio_s, nuovo_s)

    # Canale di ricezione (coppia esclusiva).
    if any(c in fields for c in _CANALE):
        cod_ade = str(dati_ade.get("codice_destinatario", "") or "").strip().upper()
        pec_ade = str(dati_ade.get("pec", "") or "").strip()
        if cod_ade or pec_ade:  # AdE ha letto un canale
            cod_old = str(saved_row.get("codice_destinatario", "") or "").strip().upper()
            pec_old = str(saved_row.get("pec", "") or "").strip()
            if cod_ade != cod_old:
                diffs["codice_destinatario"] = (cod_old, cod_ade)
            if pec_ade != pec_old:
                diffs["pec"] = (pec_old, pec_ade)
    return diffs
