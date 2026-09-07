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
