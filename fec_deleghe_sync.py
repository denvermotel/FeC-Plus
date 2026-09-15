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

# Codici servizio rilevanti per Fatture&Corrispettivi (vedi fec_deleghe.SERVIZIO_FATTURE
# per il vecchio filtro testuale sul CSV): I42 = consultazione/acquisizione fatture,
# I31 = fatturazione elettronica e conservazione.
SERVIZI_RILEVANTI = ("I42", "I31")


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
