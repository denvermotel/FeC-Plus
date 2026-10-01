#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Oggetti finti condivisi dai test: nessuna rete, nessun dato reale."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_download


class Risposta:
    def __init__(self, payload=None, status=200, contenuto=b"<xml/>", filename="F.xml"):
        self._payload = payload
        self.status_code = status
        self.content = contenuto
        self.text = "" if payload is None else str(payload)
        self.headers = {"content-disposition": f"filename={filename}"}

    def json(self):
        if self._payload is None:
            raise ValueError("non JSON")
        return self._payload


class SessioneElenco:
    """La prima GET restituisce `payload_elenco`, le successive i file.
    `esiti_file` si consuma in ordine (200 scaricato, 500 errore; default 200)."""

    def __init__(self, payload_elenco, esiti_file=()):
        self.payload = payload_elenco
        self.esiti_file = list(esiti_file)
        self.url = []

    def get(self, url, **kwargs):
        self.url.append(url)
        if len(self.url) == 1:
            return Risposta(payload=self.payload)
        stato = self.esiti_file.pop(0) if self.esiti_file else 200
        return Risposta(status=stato, filename=f"F{len(self.url)}.xml")


class SessioneRotte:
    """Risponde in base alla prima sottostringa di `rotte` contenuta nell'URL:
    `rotte` è una lista di (sottostringa, payload). Registra gli URL chiamati."""

    def __init__(self, rotte):
        self.rotte = list(rotte)
        self.url = []

    def get(self, url, **kwargs):
        self.url.append(url)
        for sottostringa, payload in self.rotte:
            if sottostringa in url:
                return Risposta(payload=payload)
        return Risposta(status=404)


class Auth:
    def __init__(self, sessione, piva=""):
        self.session = sessione
        self.headers = {}
        self.piva = piva


class ProgressoSpia(fec_download.Progresso):
    def __init__(self):
        self.eventi = []

    def fase(self, etichetta, indice, totale_fasi):
        self.eventi.append(("fase", etichetta, indice, totale_fasi))

    def totale(self, n):
        self.eventi.append(("totale", n))

    def esito(self, tipo):
        self.eventi.append(("esito", tipo))

    def messaggio(self, testo):
        self.eventi.append(("messaggio", testo))

    def conclusa(self, annullato=False):
        self.eventi.append(("conclusa", annullato))

    def solo(self, *tipi):
        return [e for e in self.eventi if e[0] in tipi]


def fattura(n, **extra) -> dict:
    voce = {"tipoInvio": "T", "idFattura": str(n)}
    voce.update(extra)
    return voce
