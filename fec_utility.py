#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus — v0.03 dev
"""
fec_utility.py — Utility di riepilogo (C.9/G.6): export Excel «Elenco fatture».

Libreria pura, separata da `fec_download.py` (che resta il motore di download):
riceve un `AuthResult` già autenticato (vedi `ade_auth.autentica`) e genera un
file .xlsx di riepilogo con una riga per fattura e colonne pivot per aliquota
IVA / codice natura (formato ricalcato dallo userscript FE-Utility,
https://github.com/denvermotel/fe-utility, che però scrapa il DOM del portale:
qui si usano le API JSON di consultazione già note a `fec_download.py`).

Funzione pubblica:
    elenco_fatture_excel(auth, cf_cliente, piva, tipo, dal, al,
                         dest_dir=None, sottocartella=True,
                         control=None, log=print) -> str   # percorso xlsx

`tipo` (vedi TIPI_ELENCO): "emesse" | "ricevute_ricezione" | "ricevute_emissione"
| "trans_emesse" | "trans_ricevute". Date `dal`/`al` in formato GGMMAAAA; i
periodi > 3 mesi vengono spezzati internamente (fec_queue.spezza_periodo, con la
guardia dei 12 mesi) e le liste concatenate: l'output è comunque UN solo file.

Dipendenza opzionale `openpyxl` (ruolo "excel" in fec_deps), import lazy solo
alla scrittura del file.

Export «Elenco corrispettivi»: NON ancora implementato — gli endpoint JSON di
consultazione corrispettivi non sono noti (serve una cattura HAR sul portale).
"""

from __future__ import annotations

__version__ = "0.03 dev"

import json
import os

import requests

from ade_auth import AuthResult, IVASERVIZI, unix_time
from fec_download import (_cartella, Controllo, DownloadError,  # noqa: F401
                          HTTP_TIMEOUT)
from fec_queue import spezza_periodo


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint di consultazione (gli stessi di fec_download, sola lettura elenco)
# ─────────────────────────────────────────────────────────────────────────────

# tipo → (frammento URL lista, etichetta per log/nome file)
TIPI_ELENCO: dict[str, tuple[str, str]] = {
    "emesse":             ("fe/emesse/dal/{dal}/al/{al}",                     "emesse"),
    "ricevute_ricezione": ("fe/ricevute/dal/{dal}/al/{al}/ricerca/ricezione", "ricevute"),
    "ricevute_emissione": ("fe/ricevute/dal/{dal}/al/{al}/ricerca/emissione", "ricevute"),
    "trans_emesse":       ("ft/emesse/dal/{dal}/al/{al}",                     "trans_emesse"),
    "trans_ricevute":     ("ft/ricevute/dal/{dal}/al/{al}",                   "trans_ricevute"),
}


def _lista_fatture(auth: AuthResult, tipo: str, dal: str, al: str) -> list[dict]:
    """
    Elenco fatture (voci JSON grezze) per il blocco [dal, al] (GGMMAAAA).
    Stesse liste usate da `fec_download._scarica_da_lista`, qui senza scaricare i file.
    """
    try:
        frammento, _ = TIPI_ELENCO[tipo]
    except KeyError:
        raise DownloadError(f"Tipo elenco sconosciuto: {tipo!r} "
                            f"(validi: {', '.join(TIPI_ELENCO)}).")
    url = (f"{IVASERVIZI}/cons/cons-services/rs/"
           f"{frammento.format(dal=dal, al=al)}?v={unix_time()}")
    try:
        r = auth.session.get(url, headers=auth.headers, verify=False, timeout=HTTP_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        raise DownloadError(
            f"Nessuna risposta dall'AdE per l'elenco fatture entro il tempo limite "
            f"({HTTP_TIMEOUT[1]}s): {exc}. Riprova; se persiste, riduci il periodo.")
    if r.status_code != 200:
        raise DownloadError(
            f"La richiesta dell'elenco fatture è fallita (HTTP {r.status_code}). "
            "La sessione potrebbe essere scaduta o l'utenza di lavoro non attiva.")
    try:
        data = r.json()
    except ValueError:
        raise DownloadError("Risposta non in formato JSON: probabile sessione "
                            "scaduta o redirect alla pagina di login.")
    return data.get("fatture") or []


def _dettaglio_fattura(auth: AuthResult, fattura_file: str) -> dict | None:
    """
    Dettaglio JSON di una fattura (`fattura_file` = tipoInvio + idFattura), lo stesso
    endpoint usato da `fec_download._e_scartata_pa`. Contiene le righe di riepilogo
    IVA (imponibile/aliquota/imposta/natura). Su errore ritorna None (il chiamante
    logga e produce una riga con i soli dati di lista, senza bloccare l'export).
    """
    url = (f"{IVASERVIZI}/cons/cons-services/rs/fatture/dettaglio/{fattura_file}"
           f"?v={unix_time()}")
    try:
        r = auth.session.get(url, headers=auth.headers, verify=False, timeout=HTTP_TIMEOUT)
    except requests.exceptions.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Funzione pubblica
# ─────────────────────────────────────────────────────────────────────────────

def elenco_fatture_excel(auth: AuthResult, cf_cliente: str, piva: str, tipo: str,
                         dal: str, al: str, *, dest_dir: str | None = None,
                         sottocartella: bool = True,
                         control: "Controllo | None" = None, log=print) -> str:
    """
    Genera l'Excel «Elenco fatture» per il periodo [dal, al] (GGMMAAAA) e ritorna
    il percorso del file .xlsx creato. Periodi > 3 mesi spezzati internamente
    (guardia 12 mesi di spezza_periodo); un solo file in output.
    """
    _, etichetta = TIPI_ELENCO.get(tipo, (None, tipo))
    blocchi = spezza_periodo(dal, al, "%d%m%Y")
    log(f"Elenco fatture {etichetta} per {cf_cliente}  ({dal} -> {al})"
        + (f"  [{len(blocchi)} blocchi]" if len(blocchi) > 1 else ""))

    voci: list[dict] = []
    for b_dal, b_al in blocchi:
        if control:
            control.check()
        if len(blocchi) > 1:
            log(f"  Blocco {b_dal} -> {b_al}: richiedo l'elenco...")
        voci.extend(_lista_fatture(auth, tipo, b_dal, b_al))
    log(f"Trovate {len(voci)} fatture nell'intervallo.")
    if not voci:
        raise DownloadError("Nessuna fattura trovata nell'intervallo richiesto: "
                            "nessun file Excel generato.")

    # TODO (step 4-5 del piano C.9): dettaglio per fattura + pivot aliquote + xlsx.
    raise DownloadError("Export Excel in sviluppo: parser non ancora implementato.")
