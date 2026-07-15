#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.03 alpha
"""
fec_richieste_massive.py - Anagrafica locale delle «Richieste Massive» inviate.

Il portale AdE (pagina Angular «risposte/elenco») distingue, tra i risultati disponibili,
solo fatture vs corrispettivi, non il sottotipo esatto (emesse / ricevute per
emissione / ricevute per ricezione). Per rivestire questa ambiguità, ogni richiesta
inviata dalla tab «Richieste Massive» viene ricordata qui (tipo esatto interno, CF,
P.IVA, periodo, idRichiesta) così che, quando l'utente controlla i risultati disponibili,
si possa etichettare correttamente ogni voce incrociandola per `id_richiesta`.

Persistenza: file JSON `fec_richieste_massive.json` accanto al modulo (stessa logica di
percorso di `fec_store.py`/`fec_deleghe.py`). Dati NON sensibili, quindi nessuna cifratura.

Modulo separato e riusabile da GUI desktop e futuro server web, sul modello di
`fec_deleghe.py`: qui sta solo il data layer (modello + persistenza), nessuna dipendenza
da Tk o dalla rete.
"""

from __future__ import annotations

__version__ = "0.03 alpha"

import json
import os
import sys
from datetime import datetime, timedelta

if getattr(sys, "frozen", False):
    SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RICHIESTE_FILE = os.path.join(SCRIPT_DIR, "fec_richieste_massive.json")

# Giorni di "standby" prima della rimozione definitiva di una richiesta eliminata
# dall'utente (vedi `segna_eliminata`/`purge_scadute`).
GIORNI_STANDBY_ELIMINAZIONE = 30

# Schema riga: `tipo_richiesta` = una delle chiavi interne di
# `FecGui._RICHIESTA_MASSIVA_OPS` (massive_emesse / massive_ricevute_emissione /
# massive_ricevute_ricezione / massive_disposizione / corrispettivi), oppure "" per
# le richieste "scoperte" sul portale ma non inviate da questa applicazione (vedi
# `registra_scoperta`). `stato`: "inviata" | "scaricata" |
# "eliminata" (nascosta dall'utente, in standby per `GIORNI_STANDBY_ELIMINAZIONE`
# giorni prima della rimozione definitiva, vedi `purge_scadute`).
FIELDS = ("id_richiesta", "tipo_richiesta", "cf_cliente", "piva", "denominazione",
          "dal", "al", "data_invio", "stato", "data_eliminazione")


def _norm_row(row: dict) -> dict:
    """Ritorna una riga con tutti i campi di FIELDS, stringhe trim."""
    out = {}
    for k in FIELDS:
        out[k] = str(row.get(k, "") or "").strip()
    if not out["stato"]:
        out["stato"] = "inviata"
    return out


def load_richieste(includi_eliminate: bool = True) -> list[dict]:
    """Ritorna la lista di richieste massive ricordate, [] se assente/illeggibile.

    Con `includi_eliminate=False` (usato dalle liste mostrate all'utente) esclude le
    righe `stato == "eliminata"`: restano nel file per il periodo di standby (vedi
    `segna_eliminata`), ma non compaiono più nei popup di scelta.
    """
    try:
        with open(RICHIESTE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            return []
        rows = [_norm_row(r) for r in data if isinstance(r, dict)]
    except (OSError, ValueError):
        return []
    if not includi_eliminate:
        rows = [r for r in rows if r["stato"] != "eliminata"]
    return rows


def save_richieste(rows: list[dict]) -> None:
    """Salva la lista di richieste (normalizzate) come JSON."""
    clean = [_norm_row(r) for r in rows]
    with open(RICHIESTE_FILE, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, indent=2, ensure_ascii=False)


def upsert(rows: list[dict], nuova: dict) -> list[dict]:
    """Inserisce o aggiorna `nuova` nella lista `rows`, con chiave `id_richiesta`."""
    nuova = _norm_row(nuova)
    idr = nuova["id_richiesta"]
    if not idr:
        rows.append(nuova)
        return rows
    for i, r in enumerate(rows):
        if r.get("id_richiesta", "") == idr:
            rows[i] = nuova
            return rows
    rows.append(nuova)
    return rows


def registra_invio(id_richiesta: str, tipo_richiesta: str, cf_cliente: str,
                   piva: str, dal: str, al: str) -> None:
    """Carica, aggiunge/aggiorna la richiesta appena inviata e salva subito.

    Helper di comodo per il chiamante GUI: evita di dover gestire manualmente
    load/upsert/save per una singola registrazione.
    """
    rows = load_richieste()
    upsert(rows, {
        "id_richiesta": id_richiesta,
        "tipo_richiesta": tipo_richiesta,
        "cf_cliente": cf_cliente,
        "piva": piva,
        "dal": dal,
        "al": al,
        "data_invio": datetime.now().isoformat(timespec="seconds"),
        "stato": "inviata",
    })
    save_richieste(rows)


def registra_scoperta(id_richiesta: str, cf_cliente: str = "", piva: str = "",
                      denominazione: str = "") -> dict:
    """
    Ricorda una richiesta vista sul portale (`fec_download.elenco_risposte_massive`),
    anche se non inviata da questa applicazione (o non più ricordata, es. installazione
    diversa), così che, una volta scaricata, `segna_scaricata` la marchi e non
    ricompaia più nei popup come "tipo non ricordato" ad ogni controllo.

    Su una riga già presente aggiorna SOLO i campi mancanti (`denominazione`/`cf_cliente`/
    `piva`), senza toccare `tipo_richiesta`/`stato` già noti. Su un CF nuovo inserisce una
    riga con `tipo_richiesta=""` (sconosciuto: il portale non lo rivela). Ritorna la riga
    (aggiornata o nuova).
    """
    rows = load_richieste()
    for r in rows:
        if r.get("id_richiesta", "") == id_richiesta:
            aggiornata = False
            if denominazione and not r.get("denominazione"):
                r["denominazione"] = denominazione
                aggiornata = True
            if cf_cliente and not r.get("cf_cliente"):
                r["cf_cliente"] = cf_cliente
                aggiornata = True
            if piva and not r.get("piva"):
                r["piva"] = piva
                aggiornata = True
            if aggiornata:
                save_richieste(rows)
            return r
    nuova = _norm_row({
        "id_richiesta": id_richiesta,
        "tipo_richiesta": "",
        "cf_cliente": cf_cliente,
        "piva": piva,
        "denominazione": denominazione,
        "data_invio": datetime.now().isoformat(timespec="seconds"),
        "stato": "inviata",
    })
    rows.append(nuova)
    save_richieste(rows)
    return nuova


def segna_scaricata(id_richiesta: str) -> None:
    """Aggiorna lo stato della richiesta a "scaricata" (no-op se non trovata)."""
    rows = load_richieste()
    for r in rows:
        if r.get("id_richiesta", "") == id_richiesta:
            r["stato"] = "scaricata"
            save_richieste(rows)
            return


def segna_eliminata(id_richiesta: str) -> None:
    """«Elimina» la richiesta (no-op se non trovata): in realtà solo un soft-delete,
    la riga resta nel file, marcata `stato="eliminata"` con la data odierna, così da
    non comparire più nei popup ma essere comunque recuperabile per
    `GIORNI_STANDBY_ELIMINAZIONE` giorni prima della rimozione definitiva (vedi
    `purge_scadute`)."""
    rows = load_richieste()
    for r in rows:
        if r.get("id_richiesta", "") == id_richiesta:
            r["stato"] = "eliminata"
            r["data_eliminazione"] = datetime.now().isoformat(timespec="seconds")
            save_richieste(rows)
            return


def purge_scadute(giorni: int = GIORNI_STANDBY_ELIMINAZIONE) -> int:
    """Rimuove definitivamente le richieste «eliminata» più vecchie di `giorni`
    giorni (standby prima della cancellazione reale, vedi `segna_eliminata`).
    Ritorna quante ne sono state rimosse. Da chiamare periodicamente (es. all'avvio
    della GUI): nessun effetto se non ce ne sono di scadute."""
    rows = load_richieste()
    soglia = datetime.now() - timedelta(days=giorni)
    tenute = []
    rimosse = 0
    for r in rows:
        if r["stato"] == "eliminata":
            try:
                scaduta = datetime.fromisoformat(r["data_eliminazione"]) < soglia
            except ValueError:
                scaduta = False
            if scaduta:
                rimosse += 1
                continue
        tenute.append(r)
    if rimosse:
        save_richieste(tenute)
    return rimosse


def trova(id_richiesta: str) -> dict | None:
    """Ritorna la riga ricordata per `id_richiesta`, o None se non presente."""
    for r in load_richieste():
        if r.get("id_richiesta", "") == id_richiesta:
            return r
    return None
