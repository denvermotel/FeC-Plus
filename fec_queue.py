#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""
fec_queue.py - Orchestrazione delle richieste, SOPRA l'engine di fec_download.py.

Questo livello tiene separata la logica di "periodi e accodamento" dal motore
di download (fec_download.py, che resta libreria pura). Fornisce:

- `spezza_periodo(dal, al, fmt)`: spezzettamento automatico dei periodi. L'AdE
  consente intervalli <= 3 mesi, quindi gli intervalli più lunghi vengono divisi in
  sotto-richieste da max 3 mesi (con un blocco di sicurezza a 12 mesi totali).
- `esegui_richiesta(auth, tipo, ...)`: esegue una richiesta sull'AuthResult già
  autenticato, spezzando e unendo i risultati. Riusato da GUI e CLI.
- `esegui_task(creds, richiesta)`: facade unica che autentica ed esegue la
  richiesta in un solo passo, punto d'ingresso comune ai frontend (GUI desktop,
  CLI, eventuale server web).

Nessuno stato globale mutabile: ogni chiamata lavora sul proprio `AuthResult`/
sessione, requisito per un eventuale server multi-utente.
"""

from __future__ import annotations

__version__ = "0.04 dev"

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from dateutil.relativedelta import relativedelta

import fec_download as fd
from fec_download import DownloadResult, DownloadError

# Limiti AdE / di sicurezza.
MAX_MESI_BLOCCO = 3      # l'AdE consente richieste su periodi <= 3 mesi
MAX_MESI_TOTALE = 12     # blocco di sicurezza sull'ampiezza totale dell'intervallo


# ─────────────────────────────────────────────────────────────────────────────
# Spezzettamento periodi (+ blocco di sicurezza 12 mesi)
# ─────────────────────────────────────────────────────────────────────────────

def _descr_fmt(fmt: str) -> str:
    return {"%d%m%Y": "GGMMAAAA", "%Y-%m-%d": "AAAA-MM-GG"}.get(fmt, fmt)


def spezza_periodo(dal: str, al: str, fmt: str = "%d%m%Y",
                   max_mesi: int = MAX_MESI_BLOCCO,
                   max_totale_mesi: int = MAX_MESI_TOTALE) -> list[tuple[str, str]]:
    """
    Spezza l'intervallo [dal, al] in blocchi da al massimo `max_mesi` mesi.

    Le date sono stringhe nel formato `fmt` (`%d%m%Y` per la consultazione,
    `%Y-%m-%d` per massive/corrispettivi). I blocchi partono da `dal` e coprono
    finestre di `max_mesi` mesi calendariali; l'ultimo è tagliato a `al`.
    Un intervallo già <= max_mesi torna come SINGOLO blocco (comportamento storico).

    Blocco di sicurezza: se l'intervallo totale supera `max_totale_mesi` mesi,
    solleva DownloadError (evita di sovraccaricare il programma e i server AdE).

    Esempio (fmt ddmmyyyy): 01012026 → 31052026 ⇒
        [("01012026", "31032026"), ("01042026", "31052026")]
    """
    try:
        d0 = datetime.strptime(dal, fmt).date()
        a0 = datetime.strptime(al, fmt).date()
    except (ValueError, TypeError):
        raise DownloadError(f"Date non valide: usare il formato {_descr_fmt(fmt)}.")
    if d0 > a0:
        raise DownloadError("La data inizio è successiva alla data fine.")

    # Blocco di sicurezza sull'ampiezza complessiva.
    limite = d0 + relativedelta(months=max_totale_mesi) - timedelta(days=1)
    if a0 > limite:
        raise DownloadError(
            f"Intervallo troppo ampio: massimo {max_totale_mesi} mesi per richiesta "
            f"(da {dal} il limite è {limite.strftime(fmt)}). "
            "Riduci il periodo ed esegui più richieste.")

    blocchi: list[tuple[str, str]] = []
    start = d0
    while start <= a0:
        end = min(start + relativedelta(months=max_mesi) - timedelta(days=1), a0)
        blocchi.append((start.strftime(fmt), end.strftime(fmt)))
        start = end + timedelta(days=1)
    return blocchi


# ─────────────────────────────────────────────────────────────────────────────
# Registro dei tipi di richiesta + orchestratore
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Spec:
    func: Callable     # funzione di fec_download da invocare
    fmt: str | None    # formato date ("%d%m%Y"/"%Y-%m-%d"); None = niente intervallo (bolli)
    kind: str          # "download" (DownloadResult) | "invio" (codice) | "diretto" (bolli)


# Nomi leggibili dei tipi, per la riga di stato della barra di avanzamento.
# Il log ha i suoi messaggi; questi stanno in una fascia larga poche parole.
ETICHETTE: dict[str, str] = {
    "emesse": "Emesse", "ricevute": "Ricevute",
    "trans_emesse": "Transfrontaliere emesse",
    "trans_ricevute": "Transfrontaliere ricevute",
    "messe_disposizione": "Messe a disposizione",
    "massive_emesse": "Massiva emesse",
    "massive_ricevute_emissione": "Massiva ricevute (emissione)",
    "massive_ricevute_ricezione": "Massiva ricevute (ricezione)",
    "massive_disposizione": "Massiva messe a disposizione",
    "corrispettivi": "Corrispettivi", "bolli": "Bolli virtuali",
}

# Chiavi canoniche usate da GUI e CLI per identificare la richiesta.
TIPI: dict[str, _Spec] = {
    "emesse":                     _Spec(fd.scarica_emesse,                     "%d%m%Y", "download"),
    "ricevute":                   _Spec(fd.scarica_ricevute,                   "%d%m%Y", "download"),
    "trans_emesse":               _Spec(fd.scarica_transfrontaliere_emesse,    "%d%m%Y", "download"),
    "trans_ricevute":             _Spec(fd.scarica_transfrontaliere_ricevute,  "%d%m%Y", "download"),
    "messe_disposizione":         _Spec(fd.scarica_messe_a_disposizione,       "%d%m%Y", "download"),
    "massive_emesse":             _Spec(fd.richiesta_massiva_emesse,             "%Y-%m-%d", "invio"),
    "massive_ricevute_emissione": _Spec(fd.richiesta_massiva_ricevute_emissione, "%Y-%m-%d", "invio"),
    "massive_ricevute_ricezione": _Spec(fd.richiesta_massiva_ricevute_ricezione, "%Y-%m-%d", "invio"),
    "massive_disposizione":       _Spec(fd.richiesta_massiva_disposizione,       "%Y-%m-%d", "invio"),
    "corrispettivi":              _Spec(fd.richiesta_corrispettivi,              "%Y-%m-%d", "invio"),
    "bolli":                      _Spec(fd.scarica_bolli,                        None,       "diretto"),
}


def _somma_download(risultati: list[DownloadResult]) -> DownloadResult:
    """Unisce i DownloadResult dei vari blocchi (stessa cartella, contatori sommati)."""
    primo = risultati[0]
    return DownloadResult(
        cf_cliente=primo.cf_cliente,
        cartella=primo.cartella,
        fatture=sum(r.fatture for r in risultati),
        metadati=sum(r.metadati for r in risultati),
    )


def esegui_richiesta(auth, tipo: str, *, dal: str | None = None, al: str | None = None,
                     max_mesi: int = MAX_MESI_BLOCCO, control=None, log=print,
                     progresso=None, **kwargs):
    """
    Esegue la richiesta `tipo` (chiave di TIPI) sull'AuthResult `auth` già autenticato,
    spezzando automaticamente l'intervallo [dal, al] in blocchi <= max_mesi e
    unendo i risultati. I parametri specifici della funzione di fec_download
    (cf_cliente, piva, tipo_data, dest_dir, sottocartella, ...) passano via **kwargs.

    `control` (opzionale, `fec_download.Controllo`): pausa/annullamento cooperativo,
    controllato tra un blocco e l'altro e passato ai download per il controllo tra i file.

    `progresso` (opzionale, `fec_download.Progresso`): riceve una `fase()` per
    blocco di periodo e, come `control`, viene inoltrato ai soli tipi download
    (anche quando e' None), che vi emettono totale ed esiti. Gli indici di fase sono LOCALI a questa chiamata: comporre gli offset
    di un task con piu' richieste spetta al chiamante (vedi `fec_gui`).

    `csv_ade` (solo tipi "download"): oltre ai file scaricati genera nella stessa
    cartella il CSV formato AdE dell'elenco (`fec_csv_ade`), UNO per l'intera
    richiesta anche se il periodo è stato spezzato, con le sole righe superstiti
    all'eventuale filtro per controparte.

    Ritorna:
      - tipo "download": un DownloadResult con i contatori sommati;
      - tipo "invio" (massive/corrispettivi): la lista dei codici richiesta (uno per blocco);
      - tipo "diretto" (bolli): il risultato della singola chiamata.
    """
    try:
        spec = TIPI[tipo]
    except KeyError:
        raise DownloadError(f"Tipo di richiesta sconosciuto: {tipo!r}.")

    # CSV formato AdE: opzione dei soli download. Va consumata qui (non deve
    # arrivare a fec_download) perché il file è UNO per l'intera richiesta,
    # anche quando il periodo è stato spezzato in più blocchi.
    csv_ade = bool(kwargs.pop("csv_ade", False)) and spec.kind == "download"
    voci_csv: list = []

    # Bolli: nessun intervallo da spezzare (lo spezzettamento per trimestre è
    # gestito internamente da fec_download.scarica_bolli); inoltra comunque
    # `control` per il pausa/annullamento cooperativo tra un trimestre e l'altro.
    if spec.fmt is None:
        return spec.func(auth, log=log, control=control, **kwargs)

    blocchi = spezza_periodo(dal, al, spec.fmt, max_mesi)
    multi = len(blocchi) > 1
    if multi:
        log(f"Periodo {dal} → {al}: spezzato in {len(blocchi)} richieste da max {max_mesi} mesi.")

    risultati = []
    for i, (d, a) in enumerate(blocchi, 1):
        if control is not None:
            control.check()   # pausa/annullamento cooperativo tra un blocco e l'altro
        if progresso is not None:
            nome = ETICHETTE.get(tipo, tipo)
            etichetta = f"{nome} · blocco {i}/{len(blocchi)}" if multi else nome
            progresso.fase(etichetta, i, len(blocchi))
        if multi:
            log(f"\n- Blocco {i}/{len(blocchi)}: {d} → {a}")
        extra = dict(kwargs)
        if spec.kind == "download":
            # I download passano il control all'engine (controllo tra i file).
            extra["control"] = control
            extra["progresso"] = progresso
            if csv_ade:
                extra["voci_out"] = voci_csv
        elif spec.kind == "invio" and multi:
            # Nome XML univoco per blocco, così le richieste massive non si sovrascrivono.
            extra["suffisso_nome"] = f"_{d}_{a}"
        risultati.append(spec.func(auth, d, a, log=log, **extra))

    if spec.kind == "download":
        esito = _somma_download(risultati)
        if multi:
            log(f"\n✓ Totale {len(blocchi)} blocchi - "
                f"fatture: {esito.fatture}, metadati: {esito.metadati}\nCartella: {esito.cartella}")
        if csv_ade and voci_csv:
            import fec_csv_ade
            # Prefisso dal CF: nei download la P.IVA non fa parte dei kwargs (la
            # consultazione usa solo il CF). L'export dalla tab Utility, che la
            # conosce, usa `piva or cf` - quindi i due percorsi possono produrre
            # nomi diversi per lo stesso soggetto: differenza nota e innocua.
            percorso = fec_csv_ade.scrivi_csv(
                os.path.join(esito.cartella,
                             fec_csv_ade.nome_file(kwargs.get("cf_cliente", ""),
                                                   dal, al, tipo)),
                voci_csv, tipo)
            log(f"CSV Agenzia Entrate ({len(voci_csv)} righe): {percorso}")
        elif csv_ade:
            log("CSV Agenzia Entrate non generato: nessuna fattura nel periodo.")
        return esito

    codici = [c for c in risultati if c]
    if multi:
        log(f"\n✓ {len(codici)} richieste inviate. Codici: {', '.join(codici)}")
    return codici


# ─────────────────────────────────────────────────────────────────────────────
# Facade unica: autentica + esegui_richiesta (ingresso comune ai frontend)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Richiesta:
    """Descrive una singola richiesta utente, indipendente dal frontend."""
    tipo: str
    dal: str | None = None
    al: str | None = None
    cf_cliente: str = ""
    piva: str = ""
    tipo_data: int = 1
    trimestre: str = ""
    anno: str = ""
    dest_dir: str | None = None
    sottocartella: bool = True
    escludi_scartate_pa: bool = True
    estrai_p7m: bool = False
    csv_ade: bool = False


def _kwargs_richiesta(r: Richiesta) -> dict:
    """Costruisce i kwargs giusti per `esegui_richiesta` a seconda del tipo."""
    spec = TIPI.get(r.tipo)
    kw: dict = {"cf_cliente": r.cf_cliente,
                "dest_dir": r.dest_dir, "sottocartella": r.sottocartella}
    if r.tipo == "ricevute":
        kw["tipo_data"] = r.tipo_data
    if spec is not None and spec.kind == "download":
        kw["escludi_scartate_pa"] = r.escludi_scartate_pa
        kw["estrai_p7m"] = r.estrai_p7m
        kw["csv_ade"] = r.csv_ade
    if spec is not None and spec.kind == "invio":
        kw["piva"] = r.piva
    if r.tipo == "bolli":
        kw.update(piva=r.piva, trimestre=r.trimestre, anno=r.anno)
    return kw


def esegui_task(creds, richiesta: Richiesta, *, backend: str = "requests",
                headless: bool = True, log=print):
    """
    Facade unica: autentica con `creds` ed esegue `richiesta`.

    Incapsula `ade_auth.autentica()` + `esegui_richiesta()` in un'unica chiamata,
    punto d'ingresso comune ai frontend (GUI desktop, CLI, eventuale server web).
    GUI e CLI, che già autenticano per conto loro, usano direttamente
    `esegui_richiesta()` sull'AuthResult; questa facade serve a chi parte da `creds`.
    """
    import ade_auth
    auth = ade_auth.autentica(creds, backend=backend, headless=headless, log=log)
    return esegui_richiesta(auth, richiesta.tipo, dal=richiesta.dal, al=richiesta.al,
                            log=log, **_kwargs_richiesta(richiesta))
