#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.03 alpha
"""
fec_deleghe.py - Anagrafica locale delle «deleghe ricevute».

Database LOCALE dei clienti che hanno delegato lo studio, popolabile/modificabile a mano
(CRUD), così da scegliere il cliente da una lista invece di digitare CF/P.IVA ad ogni
download. Indipendente dall'AdE (l'aggiornamento automatico via portale non è disponibile,
vedi `fec_deleghe_beta.py`).

Persistenza: file JSON `fec_deleghe.json` accanto al modulo (stessa logica di percorso di
`fec_store.py`). Dati NON sensibili, quindi nessuna cifratura.

Modulo separato e riusabile da GUI desktop e futuro server web, sul modello di
`fec_store.py`. Qui sta solo il data layer (modello + persistenza + import/export CSV):
nessuna dipendenza da Tk o dalla rete.

Tre vie di caricamento tabella:
  - CRUD manuale (`upsert`);
  - CSV «formato app» (round-trip import/export dei 6 campi) -> `import_csv_app` / `export_csv_app`;
  - CSV «Elenco deleganti» esportato dal portale AdE -> `import_csv_ade`.

In tutti i casi il merge (`upsert`/`merge_many`) aggiorna automaticamente SOLO
`data_fine_delega`: gli altri campi restano quelli già in tabella.

ℹ️ Il popolamento automatico dal portale Deleghe è stato tentato e poi accantonato
(bloccato da un WAF lato AdE): codice parcheggiato in `fec_deleghe_beta.py`, non
collegato alla GUI.
"""

from __future__ import annotations

__version__ = "0.03 alpha"

import csv
import json
import os
import sys
from datetime import datetime

# File accanto al modulo / all'eseguibile (PyInstaller), come fec_store.py.
if getattr(sys, "frozen", False):
    SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DELEGHE_FILE = os.path.join(SCRIPT_DIR, "fec_deleghe.json")

# Schema riga della tabella deleghe. `conservazione` è un bool; gli altri sono stringhe.
FIELDS = ("denominazione", "codice_fiscale", "partita_iva",
          "data_fine_delega", "conservazione", "codice_destinatario")

# ── Match servizi nel CSV AdE (sottostringhe, facili da aggiornare) ───────────
# Delega che abilita lo scarico delle fatture da Fatture & Corrispettivi.
SERVIZIO_FATTURE = "Consultazione e acquisizione delle fatture elettroniche"

# Intestazioni del CSV AdE «Elenco deleganti».
_ADE_CF = "Codice fiscale delegante"
_ADE_DATA_FINE = "Data fine delega"
_ADE_SERVIZIO = "Tipo servizio"

# ⚠️ NON affidabile come link diretto: il pulsante reale del portale porta altrove.
# Percorso di navigazione: Home portale -> selezione P.IVA Studio -> Deleghe ->
# Intermediari (menu, non un URL fisso). Usata solo come hint testuale nella cattura
# HAR investigativa (ade_auth.cattura_har_navigazione). L'endpoint dati reale (JSON,
# non serve raggiungere una pagina precisa) è
# POST apptel.agenziaentrate.gov.it/deleghe-portale-rest/rs/delegheUniche/deleganti.
URL_RICERCA_DELEGANTI = ("https://portale.agenziaentrate.gov.it/PortaleWeb/profilo/"
                         "deleghe/intermediari/ricerca-deleganti")


# ── Normalizzazione ───────────────────────────────────────────────────────────

def _truthy(v) -> bool:
    """Interpreta sì/si/true/1/x come True (per il campo conservazione da CSV)."""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("sì", "si", "true", "1", "x", "vero")


def _norm_row(row: dict) -> dict:
    """Ritorna una riga con tutti i campi di FIELDS, stringhe trim e CF in maiuscolo."""
    out = {}
    for k in FIELDS:
        if k == "conservazione":
            out[k] = _truthy(row.get(k, False))
        else:
            out[k] = str(row.get(k, "") or "").strip()
    out["codice_fiscale"] = out["codice_fiscale"].upper()
    out["partita_iva"] = out["partita_iva"].upper()
    out["codice_destinatario"] = out["codice_destinatario"].upper()
    return out


# ── Persistenza JSON ──────────────────────────────────────────────────────────

def load_deleghe() -> list[dict]:
    """Ritorna la lista di righe deleghe, [] se assente/illeggibile."""
    try:
        with open(DELEGHE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            return []
        return [_norm_row(r) for r in data if isinstance(r, dict)]
    except (OSError, ValueError):
        return []


def save_deleghe(rows: list[dict]) -> None:
    """Salva la lista di righe (normalizzate) come JSON."""
    clean = [_norm_row(r) for r in rows]
    with open(DELEGHE_FILE, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, indent=2, ensure_ascii=False)


# ── CRUD / merge ──────────────────────────────────────────────────────────────

def upsert(rows: list[dict], nuova: dict) -> list[dict]:
    """
    Inserisce o aggiorna `nuova` nella lista `rows`, con chiave `codice_fiscale`.

    Su un CF già presente l'UNICO campo che l'import può aggiornare è
    `data_fine_delega` (e solo se il valore importato non è vuoto): tutti gli altri
    campi (denominazione, P.IVA, conservazione, codice destinatario) restano quelli
    già in tabella, qualunque cosa contenga la riga importata: modificabili solo a
    mano dal form CRUD (`FecGui._deleghe_save`, che non passa da qui). Una riga con
    CF non ancora presente viene inserita per intero. Modifica e ritorna la lista.
    """
    nuova = _norm_row(nuova)
    cf = nuova["codice_fiscale"]
    if not cf:
        rows.append(nuova)
        return rows
    for i, r in enumerate(rows):
        if r.get("codice_fiscale", "").upper() == cf:
            merged = dict(r)
            if nuova["data_fine_delega"]:
                merged["data_fine_delega"] = nuova["data_fine_delega"]
            rows[i] = _norm_row(merged)
            return rows
    rows.append(nuova)
    return rows


def merge_many(rows: list[dict], nuove: list[dict]) -> tuple[list[dict], int, int]:
    """Applica `upsert` per ciascuna riga; ritorna (rows, aggiunte, aggiornate)."""
    esistenti = {r.get("codice_fiscale", "").upper() for r in rows}
    aggiunte = aggiornate = 0
    for n in nuove:
        cf = str(n.get("codice_fiscale", "")).strip().upper()
        if cf and cf in esistenti:
            aggiornate += 1
        else:
            aggiunte += 1
            if cf:
                esistenti.add(cf)
        upsert(rows, n)
    return rows, aggiunte, aggiornate


# ── CSV «formato app» (round-trip) ────────────────────────────────────────────

def import_csv_app(path: str) -> list[dict]:
    """Legge un CSV nel formato app (header = FIELDS, separatore ';')."""
    out = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for row in reader:
            out.append(_norm_row(row))
    return out


def export_csv_app(rows: list[dict], path: str) -> None:
    """Scrive l'intera tabella nel formato app (header = FIELDS, separatore ';')."""
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(FIELDS), delimiter=";")
        writer.writeheader()
        for r in rows:
            nr = _norm_row(r)
            nr["conservazione"] = "Sì" if nr["conservazione"] else "No"
            writer.writerow(nr)


# ── CSV AdE «Elenco deleganti» ────────────────────────────────────────────────

def _parse_data(s: str):
    """gg/mm/aaaa → datetime, o None se non valida."""
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y")
    except (ValueError, AttributeError):
        return None


def import_csv_ade(path: str) -> list[dict]:
    """
    Parser dell'export AdE «Elenco deleganti» (separatore ';'). Importa SOLO i CF con
    delega F&C (SERVIZIO_FATTURE) e aggrega una riga per CF:
      - data_fine_delega = la più lontana tra le deleghe F&C del CF;
      - denominazione / partita_iva / codice_destinatario / conservazione restano vuoti.

    NB: la `conservazione` NON si deduce dal CSV. La presenza della delega al servizio di
    conservazione non implica che l'adesione sia attiva: lo stato reale è leggibile solo
    dal portale (vedi fec_anagrafica), quindi qui la si lascia intatta. Il merge (`upsert`)
    aggiorna comunque SOLO `data_fine_delega`, mai gli altri campi.
    """
    agg: dict[str, dict] = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for row in reader:
            cf = str(row.get(_ADE_CF, "") or "").strip().upper()
            servizio = str(row.get(_ADE_SERVIZIO, "") or "")
            if not cf or SERVIZIO_FATTURE not in servizio:
                continue
            rec = agg.setdefault(cf, {"data": None})
            d = _parse_data(row.get(_ADE_DATA_FINE, ""))
            if d and (rec["data"] is None or d > rec["data"]):
                rec["data"] = d

    return [_norm_row({
        "codice_fiscale": cf,
        "data_fine_delega": rec["data"].strftime("%d/%m/%Y") if rec["data"] else "",
    }) for cf, rec in agg.items()]
