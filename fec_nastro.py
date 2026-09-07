#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""
fec_nastro.py - Il nastro di avanzamento: una tacca per documento.

Due parti nettamente separate:

- `ModelloNastro`: logica pura, NESSUN import di Tk. Accumula i segmenti (uno
  per fase) con i rispettivi esiti e sa dire, data una larghezza in pixel, quali
  rettangoli disegnare. Qui vive l'aggregazione oltre `MAX_TACCHE`. Testabile
  senza aprire una finestra, ed e' la parte dove i bug si nascondono.
- `WidgetNastro`: un `tk.Canvas` sottile che chiede i rettangoli al modello e li
  disegna. Nessuna logica propria.

Il nastro e' CUMULATIVO sull'intero task: i segmenti si accodano e il nastro
cresce man mano che ogni blocco rivela il proprio elenco. A fine ciclo resta
come resoconto di tutto quello che e' appena successo - che e' il motivo per
cui esiste, mutuato dal progetto gemello FE-Utility.

NON importa `fec_download`, di proposito: `fec_gui` importa a livello di modulo
solo stdlib e `fec_deps`, cosi' la GUI parte e sa offrire l'installazione delle
dipendenze anche quando `requests` manca. Tirare dentro `fec_download` da qui
lo romperebbe. Le tre costanti di esito sono quindi duplicate e tenute allineate
da un test (`tests/test_nastro.py::TestCostantiAllineate`).
"""

from __future__ import annotations

__version__ = "0.04 dev"

import math
from dataclasses import dataclass, field

# Devono coincidere con `fec_download.ESITO_*` (vedi docstring di modulo).
ESITO_OK      = "ok"
ESITO_SALTATO = "saltato"
ESITO_ERRORE  = "errore"

# Oltre questo numero di tacche si aggrega: piu' documenti per tacca, che prende
# l'esito peggiore. Si perde la posizione esatta, non il fatto che qualcosa sia
# andato storto.
MAX_TACCHE = 300

# Quando due esiti finiscono nella stessa tacca, vince il piu' grave.
GRAVITA = {ESITO_OK: 1, ESITO_SALTATO: 2, ESITO_ERRORE: 3}

# Palette del nastro. Fondo chiaro, coerente col tema ttk della finestra (la
# console scura resta un'altra cosa).
COL_DA_FARE  = "#d0d0d0"
COL_OK       = "#2e7d32"
COL_SALTATO  = "#f9a825"
COL_ERRORE   = "#c62828"
COL_CORRENTE = "#1565c0"
COL_FONDO    = "#f0f0f0"

# Spazio vuoto fra un segmento (fase) e il successivo.
GAP_SEGMENTO = 2

# Le tacche in errore e quella in lavorazione salgono a tutta altezza: e' il
# dettaglio che fa saltare all'occhio DOVE e' andato storto qualcosa.
_ALTEZZA_PIENA = (COL_ERRORE, COL_CORRENTE)


@dataclass
class Segmento:
    """Una fase del task: un blocco di periodo, un cliente, una richiesta."""
    etichetta: str
    totale: int | None = None          # None finche' l'elenco non e' arrivato
    esiti: list[str] = field(default_factory=list)

    def tacche(self) -> int:
        """Quante posizioni occupa: il totale dichiarato, o almeno gli esiti
        gia' arrivati (difesa contro un totale dichiarato troppo basso)."""
        return max(self.totale or 0, len(self.esiti))


@dataclass(frozen=True)
class Riepilogo:
    ok: int
    saltati: int
    errori: int
    fatti: int
    totale: int | None


@dataclass(frozen=True)
class Rettangolo:
    """Un rettangolo da disegnare, in pixel. Il modello non sa cosa sia un
    Canvas: produce numeri, il widget li usa."""
    x: int
    larghezza: int
    y: int
    altezza: int
    colore: str


def _aggrega(esiti: list[str], fattore: int, n_blocchi: int) -> list[str | None]:
    """Riduce gli esiti a UN esito per blocco: quando piu' documenti condividono
    un blocco vince il piu' grave. I blocchi non ancora elaborati restano None."""
    peggiore: list[str | None] = [None] * n_blocchi
    for i, e in enumerate(esiti):
        b = min(i // fattore, n_blocchi - 1)
        if peggiore[b] is None or GRAVITA[e] > GRAVITA[peggiore[b]]:
            peggiore[b] = e
    return peggiore


class ModelloNastro:
    """Stato del nastro. Non conosce Tk e non conosce i pixel finche' non
    glieli si passa in `rettangoli()`."""

    def __init__(self):
        self.segmenti: list[Segmento] = []

    # ── Costruzione ───────────────────────────────────────────────────────

    def azzera(self) -> None:
        self.segmenti = []

    def nuovo_segmento(self, etichetta: str) -> None:
        self.segmenti.append(Segmento(etichetta))

    def imposta_totale(self, n: int) -> None:
        """Totale documenti del segmento corrente (0 e' legittimo)."""
        if not self.segmenti:
            self.nuovo_segmento("")
        self.segmenti[-1].totale = max(0, int(n))

    def aggiungi_esito(self, tipo: str) -> None:
        if not self.segmenti:            # difensivo: esito prima di fase()
            self.nuovo_segmento("")
        self.segmenti[-1].esiti.append(tipo)

    # ── Lettura ───────────────────────────────────────────────────────────

    def riepilogo(self) -> Riepilogo:
        ok = saltati = errori = fatti = 0
        totale: int | None = None
        for seg in self.segmenti:
            for e in seg.esiti:
                fatti += 1
                if e == ESITO_OK:
                    ok += 1
                elif e == ESITO_SALTATO:
                    saltati += 1
                elif e == ESITO_ERRORE:
                    errori += 1
            if seg.totale is not None:
                totale = (totale or 0) + seg.totale
        return Riepilogo(ok=ok, saltati=saltati, errori=errori,
                         fatti=fatti, totale=totale)

    # ── Geometria ─────────────────────────────────────────────────────────

    def _fattore(self) -> int:
        """Quanti documenti condividono una tacca. 1 finche' si sta sotto
        `MAX_TACCHE`; poi si aggrega, perche' tacche piu' sottili di un pixel
        non le vedrebbe nessuno."""
        totali = sum(seg.tacche() for seg in self.segmenti)
        if totali <= MAX_TACCHE:
            return 1
        return math.ceil(totali / MAX_TACCHE)

    def _indice_corrente(self) -> tuple[int, int] | None:
        """(indice segmento, indice tacca) della posizione in lavorazione, cioe'
        la prima non ancora riempita dell'ULTIMO segmento con totale noto.

        Se quel segmento e' gia' completo la ricerca si ferma li' e torna None:
        non si va a cercare piu' indietro. Un segmento precedente rimasto
        incompleto e' lavoro abbandonato, non lavoro in corso - dipingerlo di
        blu su un resoconto concluso direbbe il falso.
        """
        for i in range(len(self.segmenti) - 1, -1, -1):
            seg = self.segmenti[i]
            if seg.totale is None:
                continue
            if len(seg.esiti) < seg.totale:
                return (i, len(seg.esiti))
            return None
        return None

    def rettangoli(self, larghezza_px: int, altezza_px: int) -> list[Rettangolo]:
        """Traduce lo stato in rettangoli da disegnare su una superficie
        `larghezza_px` x `altezza_px`. Nessuno stato viene modificato: si puo'
        chiamare a ogni resize senza conseguenze."""
        fattore = self._fattore()
        blocchi_per_segmento = [math.ceil(seg.tacche() / fattore) if seg.tacche() else 0
                                for seg in self.segmenti]
        blocchi_totali = sum(blocchi_per_segmento)
        if blocchi_totali <= 0 or larghezza_px <= 0:
            return []

        # I gap fra segmenti si tolgono prima di spartire lo spazio; se il
        # nastro e' cosi' stretto da non lasciare spazio alle tacche, i gap
        # saltano (meglio senza separatori che senza tacche).
        gap = GAP_SEGMENTO
        n_gap = max(0, sum(1 for b in blocchi_per_segmento if b) - 1)
        if larghezza_px - n_gap * gap < blocchi_totali:
            gap = 0
        utile = max(blocchi_totali, larghezza_px - n_gap * gap)
        passo = utile / blocchi_totali

        corrente = self._indice_corrente()
        meta = max(1, altezza_px // 2)

        out: list[Rettangolo] = []
        x = 0.0
        visti = 0
        for i, seg in enumerate(self.segmenti):
            n_blocchi = blocchi_per_segmento[i]
            if not n_blocchi:
                continue
            if visti:                                  # gap prima di ogni
                x += gap                               # segmento tranne il primo
            peggiore = _aggrega(seg.esiti, fattore, n_blocchi)
            blocco_corrente = (corrente[1] // fattore) if (corrente and corrente[0] == i) else -1
            for b in range(n_blocchi):
                esito = peggiore[b]
                if esito is not None:
                    colore = {ESITO_OK: COL_OK,
                              ESITO_SALTATO: COL_SALTATO,
                              ESITO_ERRORE: COL_ERRORE}[esito]
                elif b == blocco_corrente:
                    colore = COL_CORRENTE
                else:
                    colore = COL_DA_FARE
                x0 = int(round(x + b * passo))
                x1 = int(round(x + (b + 1) * passo))
                pieno = colore in _ALTEZZA_PIENA
                out.append(Rettangolo(
                    x=x0,
                    larghezza=max(1, x1 - x0),
                    y=0 if pieno else altezza_px - meta,
                    altezza=altezza_px if pieno else meta,
                    colore=colore))
            x += n_blocchi * passo
            visti += n_blocchi
        return out
