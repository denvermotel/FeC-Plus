#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""
fec_csv_ade.py - Ricostruzione del CSV «Esporta la tabella» del portale AdE.

Libreria pura: nessun I/O di rete, nessuna dipendenza da GUI o download, così i
test girano offline senza credenziali.

Il CSV NON esiste lato server. Nel portale «Consultazione fatture elettroniche»
il pulsante «Esporta la tabella» apre una modale che chiede solo il nome del
file: la generazione è client-side, in JavaScript, tramite `ng-csv` alimentato da
`ExportCSVService.exportCSVFattureElettroniche()` (file `core-services.js`).
L'input di quella funzione è lo STESSO JSON di elenco che fec_download già
richiede per scaricare le fatture, quindi il file si può ricostruire fedelmente.

Regole di formato (da `ng-csv`, confermate sul campione reale
`_materiale/<campione reale, in _materiale/ fuori da Git>`):
  - separatore «;», ogni campo tra virgolette, «"» interne raddoppiate;
  - terminatore CRLF su ogni riga, ultima compresa;
  - UTF-8 SENZA BOM;
  - ordine colonne = ordine dei literal JS, non alfabetico delle chiavi;
  - un valore JS `undefined` produce un campo vuoto NON quotato (qui: None),
    mentre una stringa vuota produce «""».

Riferimenti nel repo: sorgente JS in
`_materiale/fatture emesse_files/core-services_XbTA.js`; spec in
`docs/superpowers/specs/2026-08-11-export-csv-ade-design.md`.
"""

from __future__ import annotations

__version__ = "0.04 dev"

from dataclasses import dataclass
from typing import Callable

SEP = ";"
EOL = "\r\n"


def _campo(valore) -> str:
    """Un campo secondo `ng-csv.stringifyField`: None (JS `undefined`) resta vuoto
    e NON quotato; qualsiasi altro valore è quotato con le «"» raddoppiate."""
    if valore is None:
        return ""
    return '"' + str(valore).replace('"', '""') + '"'


def formatta_righe(righe: list[list]) -> str:
    """Testo CSV completo (intestazione inclusa, se presente tra le righe)."""
    return "".join(SEP.join(_campo(c) for c in riga) + EOL for riga in righe)


# ─────────────────────────────────────────────────────────────────────────────
# Trasformazioni dei singoli campi (trascritte da exportCSVFattureElettroniche)
# ─────────────────────────────────────────────────────────────────────────────

def _data_it(iso: str | None) -> str:
    """«2026-07-10» -> «10/07/2026». Valore assente -> stringa vuota (nel JS la
    variabile è inizializzata a '', quindi esce come campo vuoto QUOTATO).

    Il JS fa `$filter('date')(v+'T00:00:00.001Z', 'dd/MM/yyyy')`, che rende la data
    nel fuso ORARIO LOCALE: in Italia coincide, a ovest di UTC darebbe il giorno
    prima. Qui si invertono i pezzi e basta: divergenza consapevole e voluta, il
    risultato è indipendente dal fuso della macchina."""
    if not iso:
        return ""
    pezzi = str(iso).split("T", 1)[0].split("-")   # tollera anche un eventuale orario
    if len(pezzi) != 3:
        return str(iso)      # già in formato italiano o inatteso: lascia com'è
    anno, mese, giorno = pezzi
    return f"{giorno}/{mese}/{anno}"


def _apice(valore: str) -> str:
    """Prefisso apice usato dall'AdE sugli identificativi, così Excel non li
    interpreta come numeri mangiandone gli zeri iniziali."""
    return f"'{valore}'"


def _ident(voce: dict, chiave: str) -> str:
    """CF/P.IVA con l'apice; se il campo manca, il letterale «Non presente»."""
    return _apice(voce.get(chiave) or "Non presente")


def _importo(valore) -> str:
    """Importo come lo scrive il JS: `imponibile.replace('.', ',').replace('+', '')`.

    Nei dati osservati arriva già zero-paddato e con la virgola decimale
    («+000000000043,55»), quindi in pratica si toglie solo il «+»; ma la conversione
    del punto in virgola va replicata lo stesso, perché il JS la mette in conto e un
    gestionale italiano che ricevesse il punto importerebbe l'importo sbagliato.
    `str.replace` in JavaScript sostituisce **solo la prima occorrenza**: qui il
    conteggio `1` fa lo stesso."""
    return str(valore or "").replace(".", ",", 1).replace("+", "", 1)


def _file_download(voce: dict) -> dict:
    return voce.get("fileDownload") or {}


def _grezzo(valore):
    """Campo che il JS passa a ng-csv COSÌ COM'È: se manca resta `undefined` e
    produce un campo vuoto **non** quotato. Qui `None` ha lo stesso effetto (vedi
    `_campo`); una stringa vuota nel JSON resta invece `""` quotata, come nel JS."""
    return valore if valore is not None else None


def _consegna(voce: dict):
    """Colonna «Fatture consegnate»: lo stato SDI del file, con il suffisso
    «/Presa visione» se la fattura risulta presa in visione.

    Senza `statoFile` e senza presa visione il JS lascia `undefined` → campo non
    quotato. Con presa visione ma senza `statoFile` il JS produrrebbe la stringa
    letterale «undefined/Presa visione» (concatenazione JavaScript): qui si scrive il
    solo suffisso, deviazione consapevole - riprodurre quel «undefined» sarebbe
    fedeltà a un bug del portale."""
    fd = _file_download(voce)
    stato = fd.get("statoFile")
    if fd.get("dataPresaVisione"):
        return f"{stato}/Presa visione" if stato else "/Presa visione"
    return _grezzo(stato)


def _data_consegna(voce: dict):
    """Colonna data finale: la data di presa visione se c'è, altrimenti la data di
    consegna. Entrambe arrivano già in GG/MM/AAAA e il JS non le riformatta; se
    mancano entrambe resta `undefined` → campo vuoto non quotato."""
    fd = _file_download(voce)
    return _grezzo(fd.get("dataPresaVisione") or voce.get("dataConsegna"))


def _bollo(voce: dict) -> str:
    return "Si" if voce.get("bolloVirtuale") == "Y" else ""


# ─────────────────────────────────────────────────────────────────────────────
# Layout per tipo di elenco
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Layout:
    """Un layout CSV: intestazione, estrattori (uno per colonna, nello stesso
    ordine) ed etichetta usata nel nome del file."""
    intestazione: list[str]
    campi: list[Callable[[dict], object]]
    etichetta: str


def _layout_fe(colonna_data: str, etichetta: str) -> Layout:
    """Layout di emesse e ricevute: identici tranne l'intestazione della colonna
    data finale («Data consegna/Presa visione» vs «Data ricezione»)."""
    return Layout(
        intestazione=[
            "Tipo fattura", "Tipo documento", "Numero fattura / Documento",
            "Data emissione", "Data trasmissione", "Codice fiscale fornitore",
            "Partita IVA fornitore", "Denominazione fornitore",
            "Codice fiscale cliente", "Partita IVA cliente", "Denominazione cliente",
            "Imponibile/Importo (totale in euro)", "Imposta (totale in euro)",
            "Sdi/file", "Fatture consegnate", colonna_data, "Bollo virtuale"],
        campi=[
            lambda v: _apice(v.get("decodificaTipoInvio") or ""),
            lambda v: _grezzo(v.get("tipoDocumento")),
            lambda v: _apice(v.get("numeroFattura") or ""),
            lambda v: _data_it(v.get("dataFattura")),
            lambda v: _data_it(v.get("dataAccoglienzaFile")),
            lambda v: _ident(v, "cfEmittente"),
            lambda v: _ident(v, "pivaEmittente"),
            lambda v: _grezzo(v.get("denominazioneEmittente")),
            lambda v: _ident(v, "cfCliente"),
            lambda v: _ident(v, "pivaCliente"),
            lambda v: _grezzo(v.get("denominazioneCliente")),
            lambda v: _importo(v.get("imponibile")),
            lambda v: _importo(v.get("imposta")),
            lambda v: _grezzo(_file_download(v).get("idInvio")),
            _consegna,
            _data_consegna,
            _bollo],
        etichetta=etichetta)


# Messe a disposizione: come emesse/ricevute ma SENZA la colonna data finale.
_LAYOUT_MD = Layout(
    intestazione=[
        "Tipo fattura", "Tipo documento", "Numero fattura / Documento",
        "Data emissione", "Data trasmissione", "Codice fiscale fornitore",
        "Partita IVA fornitore", "Denominazione fornitore",
        "Codice fiscale cliente", "Partita IVA cliente", "Denominazione cliente",
        "Imponibile/Importo (totale in euro)", "Imposta (totale in euro)",
        "Sdi/file", "Fatture consegnate", "Bollo virtuale"],
    campi=[
        lambda v: _apice(v.get("decodificaTipoInvio") or ""),
        lambda v: _grezzo(v.get("tipoDocumento")),
        lambda v: _apice(v.get("numeroFattura") or ""),
        lambda v: _data_it(v.get("dataFattura")),
        lambda v: _data_it(v.get("dataAccoglienzaFile")),
        lambda v: _ident(v, "cfEmittente"),
        lambda v: _ident(v, "pivaEmittente"),
        lambda v: _grezzo(v.get("denominazioneEmittente")),
        lambda v: _ident(v, "cfCliente"),
        lambda v: _ident(v, "pivaCliente"),
        lambda v: _grezzo(v.get("denominazioneCliente")),
        lambda v: _importo(v.get("imponibile")),
        lambda v: _importo(v.get("imposta")),
        lambda v: _grezzo(_file_download(v).get("idInvio")),
        _consegna,
        _bollo],
    etichetta="messe_disposizione")

# Transfrontaliere: paese della controparte, «Stato»/«Trasmessa da» al posto di
# «Fatture consegnate», nessun bollo virtuale.
_LAYOUT_TE = Layout(
    intestazione=[
        "Codice fiscale fornitore", "Partita IVA fornitore",
        "Denominazione fornitore", "Tipo documento", "Numero fattura/Documento",
        "Data emissione fattura", "Data trasmissione fattura",
        "Codice fiscale cliente estero", "Paese cliente estero",
        "Partita IVA cliente estero", "Denominazione cliente estero",
        "Imponibile/Importo (totale in euro)", "Imposta (totale in euro)",
        "Trasmessa da", "Stato", "Sdi/file"],
    campi=[
        lambda v: _ident(v, "cfEmittente"),
        lambda v: _ident(v, "pivaEmittente"),
        lambda v: _grezzo(v.get("denominazioneEmittente")),
        lambda v: _grezzo(v.get("tipoDocumento")),
        lambda v: _apice(v.get("numeroFattura") or ""),
        lambda v: _data_it(v.get("dataFattura")),
        lambda v: _data_it(v.get("dataAccoglienzaFile")),
        lambda v: _ident(v, "cfCliente"),
        lambda v: _grezzo(v.get("idPaeseCessionario")),
        lambda v: _ident(v, "pivaCliente"),
        lambda v: _grezzo(v.get("denominazioneCliente")),
        lambda v: _importo(v.get("imponibile")),
        lambda v: _importo(v.get("imposta")),
        lambda v: _grezzo(v.get("clienteFornitore")),
        lambda v: _grezzo(v.get("stato")),
        lambda v: _grezzo(_file_download(v).get("idInvio"))],
    etichetta="trans_emesse")

_LAYOUT_TR = Layout(
    intestazione=[
        "Codice fiscale fornitore estero", "Paese fornitore estero",
        "Partita IVA fornitore estero", "Denominazione fornitore estero",
        "Tipo documento", "Numero fattura/Documento", "Data emissione fattura",
        "Data trasmissione fattura", "Data registrazione fattura",
        "Codice fiscale cliente", "Partita IVA cliente", "Denominazione cliente",
        "Imponibile/Importo (totale in euro)", "Imposta (totale in euro)",
        "Stato", "Sdi/File"],
    campi=[
        lambda v: _ident(v, "cfEmittente"),
        lambda v: _grezzo(v.get("idPaeseCedente")),
        lambda v: _ident(v, "pivaEmittente"),
        lambda v: _grezzo(v.get("denominazioneEmittente")),
        lambda v: _grezzo(v.get("tipoDocumento")),
        lambda v: _apice(v.get("numeroFattura") or ""),
        lambda v: _data_it(v.get("dataFattura")),
        lambda v: _data_it(v.get("dataAccoglienzaFile")),
        lambda v: _data_it(v.get("dataRicezione")),
        lambda v: _ident(v, "cfCliente"),
        lambda v: _ident(v, "pivaCliente"),
        lambda v: _grezzo(v.get("denominazioneCliente")),
        lambda v: _importo(v.get("imponibile")),
        lambda v: _importo(v.get("imposta")),
        lambda v: _grezzo(v.get("stato")),
        lambda v: _grezzo(_file_download(v).get("idInvio"))],
    etichetta="trans_ricevute")


LAYOUT: dict[str, Layout] = {
    "emesse":             _layout_fe("Data consegna/Presa visione", "emesse"),
    "ricevute":           _layout_fe("Data ricezione", "ricevute"),
    "messe_disposizione": _LAYOUT_MD,
    "trans_emesse":       _LAYOUT_TE,
    "trans_ricevute":     _LAYOUT_TR,
}

# Sinonimi accettati in ingresso. `ricevute_ricezione`/`ricevute_emissione` sono le
# chiavi di `fec_utility.TIPI_ELENCO` e puntano allo stesso layout, perché la ricerca
# per ricezione o per emissione cambia l'endpoint, non il file prodotto.
# `messe_a_disposizione` non è usato da nessun chiamante (`fec_queue.TIPI` usa
# `messe_disposizione`): è tenuto solo per tolleranza sulla forma del nome.
_ALIAS = {
    "ricevute_ricezione":   "ricevute",
    "ricevute_emissione":   "ricevute",
    "messe_a_disposizione": "messe_disposizione",
}


def _layout(tipo: str) -> Layout:
    chiave = _ALIAS.get(tipo, tipo)
    try:
        return LAYOUT[chiave]
    except KeyError:
        raise ValueError(f"Tipo elenco senza layout CSV: {tipo!r} "
                         f"(validi: {', '.join(sorted(LAYOUT))}).")


def righe_csv(voci: list[dict], tipo: str) -> list[list]:
    """Intestazione + una riga per voce di elenco, già nell'ordine di colonna
    dell'AdE. `voci` sono le voci grezze della lista JSON (chiave «fatture»)."""
    lay = _layout(tipo)
    righe: list[list] = [list(lay.intestazione)]
    for voce in voci:
        righe.append([estrai(voce) for estrai in lay.campi])
    return righe


def nome_file(prefisso: str, dal: str, al: str, tipo: str) -> str:
    """Nome del CSV, stessa convenzione dell'export Excel di fec_utility:
    «{piva|cf}_{dal}-{al}_{etichetta}.csv» (date in GGMMAAAA). L'AdE fa digitare
    il nome a mano nella modale, quindi non c'è una convenzione da rispettare."""
    return f"{(prefisso or '').strip()}_{dal}-{al}_{_layout(tipo).etichetta}.csv"


def scrivi_csv(percorso: str, voci: list[dict], tipo: str) -> str:
    """Scrive il CSV in `percorso` e lo ritorna. UTF-8 senza BOM, CRLF scritti a
    mano (`newline=""` impedisce a Python di tradurre a sua volta i fine riga)."""
    testo = formatta_righe(righe_csv(voci, tipo))
    with open(percorso, "w", encoding="utf-8", newline="") as fh:
        fh.write(testo)
    return percorso
