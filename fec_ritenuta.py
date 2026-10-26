#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""
fec_ritenuta.py - Ritenute d'acconto lette dal file della fattura elettronica.

Il portale non espone la ritenuta né nell'elenco né nel dettaglio JSON: c'è solo
nell'XML, nei blocchi `DatiGeneraliDocumento/DatiRitenuta` (più d'uno dalla
versione 1.6 del tracciato, uno per tipo). Il file può arrivare firmato (.p7m),
anche codificato in base64.

Modulo puro: niente rete, niente Tk. `asn1crypto` serve solo per i .p7m.
"""

from __future__ import annotations

__version__ = "0.04 dev"

import base64
import binascii
import math
import xml.etree.ElementTree as ET
from typing import NamedTuple


class Ritenuta(NamedTuple):
    tipo: str                    # RT01 persone fisiche, RT02 giuridiche, RT03-RT06 contributi
    aliquota: float | None       # percentuale
    importo: float | None
    causale: str                 # causale del pagamento (modello 770), può mancare


def _numero(testo: str | None) -> float | None:
    try:
        valore = float((testo or "").strip())
    except ValueError:
        return None
    return valore if math.isfinite(valore) else None


def _locale(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_da_p7m(contenuto: bytes) -> bytes | None:
    """XML contenuto in una busta CMS (.p7m), binaria o in base64. None se non si può
    aprire, anche per `asn1crypto` mancante."""
    try:
        from asn1crypto import cms
    except ImportError:
        return None
    candidati = [contenuto]
    # Base64 semplice o PEM («-----BEGIN PKCS7-----»): le righe di intestazione e
    # gli a capo non fanno parte dei dati.
    righe = [r.strip() for r in contenuto.splitlines()
             if not r.strip().startswith(b"-----")]
    try:
        candidati.append(base64.b64decode(b"".join(b"".join(r.split()) for r in righe),
                                          validate=True))
    except (binascii.Error, ValueError):
        pass
    for dati in candidati:
        try:
            info = cms.ContentInfo.load(dati)
            return info["content"]["encap_content_info"]["content"].native
        except Exception:  # noqa: BLE001 - qualunque busta non valida vale «non leggibile»
            continue
    return None


_BOM_UTF8 = b"\xef\xbb\xbf"
_BOM_UTF16 = (b"\xff\xfe", b"\xfe\xff")


def _xml_pronto(contenuto: bytes) -> bytes | None:
    """L'XML da analizzare, senza BOM UTF-8 né spazi iniziali (expat rifiuta la
    dichiarazione se non è all'inizio), o None se non sembra un XML."""
    if contenuto.startswith(_BOM_UTF16):
        return contenuto
    if contenuto.startswith(_BOM_UTF8):
        contenuto = contenuto[len(_BOM_UTF8):]
    contenuto = contenuto.lstrip()
    return contenuto if contenuto.startswith(b"<") else None


def _corpi(radice: ET.Element, numero: str | None) -> list[ET.Element]:
    """Dove cercare le ritenute. In un lotto (più FatturaElettronicaBody nello stesso
    file) ogni fattura dell'elenco deve avere solo le sue: si sceglie il corpo con il
    `numero` indicato. Con un solo corpo, o se il numero non si trova, tutto il file:
    meglio una ritenuta in più che una persa."""
    corpi = [e for e in radice.iter() if _locale(e.tag) == "FatturaElettronicaBody"]
    if not numero or len(corpi) < 2:
        return [radice]
    numero = numero.strip()
    scelti = [c for c in corpi
              if any(_locale(e.tag) == "Numero" and (e.text or "").strip() == numero
                     for d in c.iter() if _locale(d.tag) == "DatiGeneraliDocumento"
                     for e in d)]
    return scelti or [radice]


def leggi_ritenute(contenuto: bytes, numero: str | None = None) -> list[Ritenuta] | None:
    """Ritenute della fattura (lista vuota se non ce ne sono), o None se il file non è
    leggibile: .p7m che non si apre, XML non valido. `numero` sceglie la fattura
    dentro un lotto (vedi `_corpi`)."""
    if not contenuto:
        return None
    xml = _xml_pronto(contenuto)
    if xml is None:
        estratto = _xml_da_p7m(contenuto)
        xml = _xml_pronto(estratto) if estratto else None
        if xml is None:
            return None
    try:
        radice = ET.fromstring(xml)
    except (ET.ParseError, LookupError, ValueError, UnicodeError):
        # LookupError: codifica dichiarata sconosciuta. Il file viene da fuori: un
        # contenuto strano vale «non leggibile», mai un errore che ferma il lavoro.
        return None
    ritenute = []
    blocchi = [b for corpo in _corpi(radice, numero) for b in corpo.iter()
               if _locale(b.tag) == "DatiRitenuta"]
    for blocco in blocchi:
        campi = {_locale(c.tag): (c.text or "").strip() for c in blocco}
        ritenute.append(Ritenuta(campi.get("TipoRitenuta", ""),
                                 _numero(campi.get("AliquotaRitenuta")),
                                 _numero(campi.get("ImportoRitenuta")),
                                 campi.get("CausalePagamento", "")))
    return ritenute


def _percentuale(valore: float | None) -> str:
    if valore is None:
        return "?"
    return f"{valore:g}".replace(".", ",")


def riepilogo(ritenute: list[Ritenuta]) -> tuple[str, str, float | None]:
    """(tipi, aliquote, importo totale) per una riga di elenco: più ritenute nella
    stessa fattura si elencano e gli importi si sommano. Vuoto senza ritenute."""
    if not ritenute:
        return "", "", None
    importi = [r.importo for r in ritenute if r.importo is not None]
    return (", ".join(r.tipo for r in ritenute),
            ", ".join(_percentuale(r.aliquota) for r in ritenute),
            round(sum(importi), 2) if importi else None)
