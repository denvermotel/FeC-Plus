#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus — v0.02 alpha
"""
fec_download.py — Download fatture elettroniche dal portale AdE "Fatture e
Corrispettivi", a partire da una sessione GIÀ autenticata.

A differenza dei vecchi script `fec_*.py` (che autenticavano da soli leggendo
le credenziali da `sys.argv`), qui le funzioni ricevono un `AuthResult`
prodotto da `ade_auth.autentica(...)`: l'autenticazione avviene UNA sola volta
nel chiamante (la GUI), in-process, senza password sulla riga di comando.

Gli endpoint sono portati 1:1 dai vecchi script `fec_*.py`.

Download di consultazione (date `ddmmyyyy`):
    scarica_emesse(auth, dal, al, cf_cliente, dest_dir=None, log=print)
    scarica_ricevute(auth, dal, al, cf_cliente, tipo_data=1, dest_dir=None, log=print)
    scarica_transfrontaliere_emesse(auth, dal, al, cf_cliente, dest_dir=None, log=print)
    scarica_transfrontaliere_ricevute(auth, dal, al, cf_cliente, dest_dir=None, log=print)
    scarica_messe_a_disposizione(auth, dal, al, cf_cliente, dest_dir=None, log=print)

Richieste massive / corrispettivi (genera XML e lo carica; date `AAAA-MM-GG`):
    richiesta_massiva_emesse(auth, dal, al, cf_cliente, piva, dest_dir=None, log=print)
    richiesta_massiva_ricevute_emissione(auth, dal, al, cf_cliente, piva, dest_dir=None, log=print)
    richiesta_massiva_ricevute_ricezione(auth, dal, al, cf_cliente, piva, dest_dir=None, log=print)
    richiesta_corrispettivi(auth, dal, al, cf_cliente, piva, dest_dir=None, log=print)

Bolli virtuali (genera PDF F24):
    scarica_bolli(auth, cf_cliente, piva, trimestre, anno, dest_dir=None, log=print)
"""

from __future__ import annotations

__version__ = "0.02 alpha"

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime

from ade_auth import AuthResult, IVASERVIZI, unix_time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DEST_DIR = os.path.join(SCRIPT_DIR, "Download")


class DownloadError(RuntimeError):
    """Errore durante lo scarico (lista non ottenuta, sessione scaduta, ...)."""


@dataclass
class DownloadResult:
    """Esito di uno scarico: quante fatture/metadati e in quale cartella."""
    cf_cliente: str
    cartella: str
    fatture: int
    metadati: int


# ─────────────────────────────────────────────────────────────────────────────
# Helper interni
# ─────────────────────────────────────────────────────────────────────────────

def _cartella(dest_dir: str | None, prefisso: str, cf_cliente: str,
              sottocartella: bool = True) -> str:
    """
    Costruisce e crea la cartella di destinazione.

    Con `sottocartella=True` (default) usa `<dest>/<prefisso>_<cf>`; con `False`
    salva direttamente in `<dest>` (file senza sottocartella, utile per i gestionali).
    """
    base = dest_dir or DEFAULT_DEST_DIR
    if not sottocartella:
        os.makedirs(base, exist_ok=True)
        return base
    path = os.path.join(base, f"{prefisso}_{cf_cliente}")
    os.makedirs(path, exist_ok=True)
    return path


def _file_url(fattura_file: str, tipo_file: str) -> str:
    return (f"{IVASERVIZI}/cons/cons-services/rs/fatture/file/{fattura_file}"
            f"?tipoFile={tipo_file}&download=1&v={unix_time()}")


def _scarica_da_lista(auth: AuthResult, url_lista: str, dest_dir: str,
                      log=print) -> tuple[int, int]:
    """
    Scarica file fattura + metadati per ogni voce restituita da `url_lista`.

    Ciclo identico a `fec_emesse.py` / `fec_ricevute.py`: per ogni fattura,
    `fatturaFile = tipoInvio + idFattura`, poi GET FILE_FATTURA e FILE_METADATI.
    Ritorna (n_fatture, n_metadati).
    """
    r = auth.session.get(url_lista, headers=auth.headers, verify=False)
    if r.status_code != 200:
        raise DownloadError(
            f"La richiesta dell'elenco fatture è fallita (HTTP {r.status_code}). "
            "La sessione potrebbe essere scaduta o l'utenza di lavoro non attiva."
        )
    try:
        data = r.json()
    except ValueError:
        raise DownloadError(
            "Risposta non in formato JSON: probabile sessione scaduta o redirect "
            "alla pagina di login."
        )

    fatture = data.get("fatture")
    if fatture is None:
        raise DownloadError(
            "La risposta non contiene l'elenco 'fatture' atteso "
            f"(chiavi ricevute: {sorted(data)[:8]})."
        )
    if not fatture:
        log("Nessuna fattura trovata nell'intervallo richiesto.")
        return 0, 0

    n_fatture = n_metadati = 0
    for fattura in fatture:
        fattura_file = fattura["tipoInvio"] + fattura["idFattura"]

        r2 = auth.session.get(_file_url(fattura_file, "FILE_FATTURA"), verify=False)
        fmetadato = None
        if r2.status_code == 200:
            n_fatture += 1
            fname = re.findall("filename=(.+)", r2.headers["content-disposition"])[0]
            fmetadato = fname
            log(f"Scarico {fname}  (tot. {n_fatture})")
            with open(os.path.join(dest_dir, fname), "wb") as f:
                f.write(r2.content)

        r3 = auth.session.get(_file_url(fattura_file, "FILE_METADATI"), verify=False)
        if r3.status_code == 200 and fmetadato:
            n_metadati += 1
            log(f"Scarico metadati -> {fmetadato}_metadato.xml")
            with open(os.path.join(dest_dir, f"{fmetadato}_metadato.xml"), "wb") as f:
                f.write(r3.content)

    return n_fatture, n_metadati


# ─────────────────────────────────────────────────────────────────────────────
# API pubblica
# ─────────────────────────────────────────────────────────────────────────────

def scarica_emesse(auth: AuthResult, dal: str, al: str, cf_cliente: str,
                   dest_dir: str | None = None, sottocartella: bool = True,
                   log=print) -> DownloadResult:
    """
    Scarica le fatture EMESSE nell'intervallo [dal, al] (formato ddmmyyyy).
    `auth` deve essere già autenticato (vedi `ade_auth.autentica`).
    """
    cartella = _cartella(dest_dir, "FattureEmesse", cf_cliente, sottocartella)
    log(f"Scarico fatture emesse per {cf_cliente}  ({dal} -> {al})")
    url = f"{IVASERVIZI}/cons/cons-services/rs/fe/emesse/dal/{dal}/al/{al}?v={unix_time()}"
    n_fatture, n_metadati = _scarica_da_lista(auth, url, cartella, log)
    log(f"\nCliente: {cf_cliente}")
    log(f"Fatture scaricate:  {n_fatture}")
    log(f"Metadati scaricati: {n_metadati}")
    log(f"Cartella: {cartella}")
    return DownloadResult(cf_cliente, cartella, n_fatture, n_metadati)


def scarica_ricevute(auth: AuthResult, dal: str, al: str, cf_cliente: str,
                     tipo_data: int = 1, dest_dir: str | None = None,
                     sottocartella: bool = True, log=print) -> DownloadResult:
    """
    Scarica le fatture RICEVUTE nell'intervallo [dal, al] (formato ddmmyyyy).
    `tipo_data`: 1 = ricerca per data ricezione (default), 2 = per data emissione.
    `auth` deve essere già autenticato (vedi `ade_auth.autentica`).
    """
    cartella = _cartella(dest_dir, "FattureRicevute", cf_cliente, sottocartella)
    ricerca = "ricezione" if tipo_data == 1 else "emissione"
    log(f"Scarico fatture ricevute per {cf_cliente}  ({dal} -> {al})  "
        f"ricerca per {ricerca}")
    url = (f"{IVASERVIZI}/cons/cons-services/rs/fe/ricevute/dal/{dal}/al/{al}"
           f"/ricerca/{ricerca}?v={unix_time()}")
    n_fatture, n_metadati = _scarica_da_lista(auth, url, cartella, log)
    log(f"\nCliente: {cf_cliente}")
    log(f"Fatture ricevute scaricate:  {n_fatture}")
    log(f"Metadati scaricati: {n_metadati}")
    log(f"Cartella: {cartella}")
    return DownloadResult(cf_cliente, cartella, n_fatture, n_metadati)


def scarica_transfrontaliere_emesse(auth: AuthResult, dal: str, al: str,
                                    cf_cliente: str, dest_dir: str | None = None,
                                    sottocartella: bool = True,
                                    log=print) -> DownloadResult:
    """Fatture transfrontaliere EMESSE nell'intervallo [dal, al] (ddmmyyyy)."""
    cartella = _cartella(dest_dir, "FattureEmesseTRAN", cf_cliente, sottocartella)
    log(f"Scarico fatture transfrontaliere emesse per {cf_cliente}  ({dal} -> {al})")
    url = f"{IVASERVIZI}/cons/cons-services/rs/ft/emesse/dal/{dal}/al/{al}?v={unix_time()}"
    n_fatture, n_metadati = _scarica_da_lista(auth, url, cartella, log)
    log(f"\nCliente: {cf_cliente}")
    log(f"Transfrontaliere emesse scaricate: {n_fatture}")
    log(f"Metadati scaricati: {n_metadati}")
    log(f"Cartella: {cartella}")
    return DownloadResult(cf_cliente, cartella, n_fatture, n_metadati)


def scarica_transfrontaliere_ricevute(auth: AuthResult, dal: str, al: str,
                                      cf_cliente: str, dest_dir: str | None = None,
                                      sottocartella: bool = True,
                                      log=print) -> DownloadResult:
    """Fatture transfrontaliere RICEVUTE nell'intervallo [dal, al] (ddmmyyyy)."""
    cartella = _cartella(dest_dir, "FattureRicevuteTRAN", cf_cliente, sottocartella)
    log(f"Scarico fatture transfrontaliere ricevute per {cf_cliente}  ({dal} -> {al})")
    url = f"{IVASERVIZI}/cons/cons-services/rs/ft/ricevute/dal/{dal}/al/{al}?v={unix_time()}"
    n_fatture, n_metadati = _scarica_da_lista(auth, url, cartella, log)
    log(f"\nCliente: {cf_cliente}")
    log(f"Transfrontaliere ricevute scaricate: {n_fatture}")
    log(f"Metadati scaricati: {n_metadati}")
    log(f"Cartella: {cartella}")
    return DownloadResult(cf_cliente, cartella, n_fatture, n_metadati)


def scarica_messe_a_disposizione(auth: AuthResult, dal: str, al: str,
                                 cf_cliente: str, dest_dir: str | None = None,
                                 sottocartella: bool = True,
                                 log=print) -> DownloadResult:
    """Fatture ricevute "messe a disposizione" nell'intervallo [dal, al] (ddmmyyyy)."""
    cartella = _cartella(dest_dir, "FattureRicevuteDisposizione", cf_cliente, sottocartella)
    log(f"Scarico fatture messe a disposizione per {cf_cliente}  ({dal} -> {al})")
    url = f"{IVASERVIZI}/cons/cons-services/rs/fe/mc/dal/{dal}/al/{al}?v={unix_time()}"
    n_fatture, n_metadati = _scarica_da_lista(auth, url, cartella, log)
    log(f"\nCliente: {cf_cliente}")
    log(f"Fatture messe a disposizione scaricate: {n_fatture}")
    log(f"Metadati scaricati: {n_metadati}")
    log(f"Cartella: {cartella}")
    return DownloadResult(cf_cliente, cartella, n_fatture, n_metadati)


# ─────────────────────────────────────────────────────────────────────────────
# Richieste massive / corrispettivi (genera XML e lo carica su /cons/mass-services)
# ─────────────────────────────────────────────────────────────────────────────

# Header dell'upload XML (oltre a x-b2bcookie/x-token/x-nome-file, aggiunti a runtime).
_UPLOAD_HEADERS = {
    "Host": "ivaservizi.agenziaentrate.gov.it",
    "accept": "application/json, text/plain, */*",
    "accept-encoding": "gzip, deflate",
    "accept-language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": IVASERVIZI,
    "Content-Type": "application/xml;charset=utf-8",
    "x-frame-options": "deny",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=16070400; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
}


def _valida_intervallo_iso(dal: str, al: str) -> None:
    """Valida date AAAA-MM-GG e l'ordine; solleva DownloadError se non valide."""
    try:
        d = datetime.strptime(dal, "%Y-%m-%d")
        a = datetime.strptime(al, "%Y-%m-%d")
    except ValueError:
        raise DownloadError("Date non valide: usare il formato AAAA-MM-GG.")
    if d > a:
        raise DownloadError("La data inizio è successiva alla data fine.")


def _xml_massivo_fatture(piva: str, dal: str, al: str, sezione: str,
                         tag_data: str, ruolo: str) -> str:
    """Corpo XML di una richiesta massiva fatture (emesse o ricevute)."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ns1:InputMassivo
\txsi:schemaLocation="http://www.sogei.it/InputPubblico untitled.xsd"
\txmlns:ns1="http://www.sogei.it/InputPubblico"
\txmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
\t<ns1:TipoRichiesta>
\t\t<ns1:Fatture>
\t\t\t<ns1:Richiesta>FATT</ns1:Richiesta>
\t\t\t<ns1:ElencoPiva>
\t\t\t\t<ns1:Piva>{piva}</ns1:Piva>
\t\t\t</ns1:ElencoPiva>
\t\t\t<ns1:TipoRicerca>COMPLETA</ns1:TipoRicerca>
\t\t\t<ns1:{sezione}>
\t\t\t\t<ns1:{tag_data}>
\t\t\t\t\t<ns1:Da>{dal}</ns1:Da>
\t\t\t\t\t<ns1:A>{al}</ns1:A>
\t\t\t\t</ns1:{tag_data}>
\t\t\t\t<ns1:Flusso><ns1:Tutte>ALL</ns1:Tutte></ns1:Flusso>
\t\t\t\t<ns1:Ruolo>{ruolo}</ns1:Ruolo>
\t\t\t</ns1:{sezione}>
\t\t</ns1:Fatture>
\t</ns1:TipoRichiesta>
</ns1:InputMassivo>
"""


def _xml_corrispettivi(piva: str, dal: str, al: str) -> str:
    """Corpo XML di una richiesta massiva corrispettivi."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ns1:InputMassivo
\txsi:schemaLocation="http://www.sogei.it/InputPubblico untitled.xsd"
\txmlns:ns1="http://www.sogei.it/InputPubblico"
\txmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
\t<ns1:TipoRichiesta>
\t\t<ns1:Corrispettivi>
\t\t\t<ns1:Richiesta>CORR</ns1:Richiesta>
\t\t\t<ns1:DataRilevazione>
\t\t\t\t<ns1:Da>{dal}</ns1:Da>
\t\t\t\t<ns1:A>{al}</ns1:A>
\t\t\t</ns1:DataRilevazione>
\t\t\t<ns1:ElencoPiva>
\t\t\t\t<ns1:Piva>{piva}</ns1:Piva>
\t\t\t</ns1:ElencoPiva>
\t\t\t<ns1:TipoCorrispettivo>RT</ns1:TipoCorrispettivo>
\t\t</ns1:Corrispettivi>
\t</ns1:TipoRichiesta>
</ns1:InputMassivo>
"""


def _invia_xml(auth: AuthResult, nome_sottocartella: str, nome_xml: str, xml_body: str,
               tipo_richiesta: str, csv_suffix: str, cf_cliente: str,
               dest_dir: str | None, sottocartella: bool, log) -> str:
    """
    Scrive `xml_body` (in `<dest>/<nome_sottocartella>/<nome_xml>`, o direttamente in
    `<dest>` se `sottocartella=False`), lo carica su
    `/cons/mass-services/rs/file/upload?tipoRichiesta=<tipo>` e registra l'esito.
    Ritorna il codice di richiesta restituito dall'AdE. Solleva DownloadError su errore.
    """
    base = dest_dir or DEFAULT_DEST_DIR
    cartella = base if not sottocartella else os.path.join(base, nome_sottocartella)
    os.makedirs(cartella, exist_ok=True)
    percorso = os.path.join(cartella, nome_xml)
    with open(percorso, "w", encoding="utf-8") as f:
        f.write(xml_body)
    log(f"File XML creato: {percorso}")

    headers = {
        **_UPLOAD_HEADERS,
        "x-b2bcookie": auth.xb2bcookie,
        "x-token": auth.xtoken,
        "x-nome-file": nome_xml,
    }
    log(f"Invio {nome_xml}...")
    with open(percorso, "rb") as f:
        r = auth.session.post(
            f"{IVASERVIZI}/cons/mass-services/rs/file/upload?tipoRichiesta={tipo_richiesta}",
            headers=headers, data=f, verify=False)

    log(f"Status: {r.status_code}")
    if r.status_code == 500:
        raise DownloadError("Servizio AdE non disponibile (HTTP 500). Riprovare più tardi.")
    if r.status_code != 200:
        raise DownloadError(f"Invio non riuscito (HTTP {r.status_code}): {r.text[:300]}")

    codice = r.text.strip()
    log(f"Inviato con successo. Codice richiesta: {codice}")
    now = datetime.now()
    with open(os.path.join(cartella, f"{cf_cliente}_{csv_suffix}_inviati.csv"),
              "a", encoding="utf-8") as csv:
        csv.write(f"{nome_xml},{codice},{now}\n")
    try:
        os.replace(percorso, f"{percorso}_inviato_il_{now.strftime('%Y-%m-%d')}")
    except OSError:
        pass
    return codice


def richiesta_massiva_emesse(auth: AuthResult, dal: str, al: str, cf_cliente: str,
                             piva: str, dest_dir: str | None = None,
                             sottocartella: bool = True, log=print) -> str:
    """Richiesta massiva fatture EMESSE (per data emissione). Date AAAA-MM-GG."""
    _valida_intervallo_iso(dal, al)
    xml = _xml_massivo_fatture(piva, dal, al, "FattureEmesse", "DataEmissione", "CEDENTE")
    return _invia_xml(auth, "inviomassivo", f"FATT_{cf_cliente}.xml", xml,
                      "FATT", "fattura_massiva", cf_cliente, dest_dir, sottocartella, log)


def richiesta_massiva_ricevute_emissione(auth: AuthResult, dal: str, al: str,
                                         cf_cliente: str, piva: str,
                                         dest_dir: str | None = None,
                                         sottocartella: bool = True,
                                         log=print) -> str:
    """Richiesta massiva fatture RICEVUTE per data EMISSIONE. Date AAAA-MM-GG."""
    _valida_intervallo_iso(dal, al)
    xml = _xml_massivo_fatture(piva, dal, al, "FattureRicevute", "DataEmissione", "CESSIONARIO")
    return _invia_xml(auth, "inviomassivo", f"FATT_M_RICEVUTE_EMISSIONE{cf_cliente}.xml",
                      xml, "FATT", "fattura_massiva", cf_cliente, dest_dir, sottocartella, log)


def richiesta_massiva_ricevute_ricezione(auth: AuthResult, dal: str, al: str,
                                         cf_cliente: str, piva: str,
                                         dest_dir: str | None = None,
                                         sottocartella: bool = True,
                                         log=print) -> str:
    """Richiesta massiva fatture RICEVUTE per data RICEZIONE. Date AAAA-MM-GG."""
    _valida_intervallo_iso(dal, al)
    xml = _xml_massivo_fatture(piva, dal, al, "FattureRicevute", "DataRicezione", "CESSIONARIO")
    return _invia_xml(auth, "inviomassivo", f"FATT_M_RICEVUTE_RICEZIONE{cf_cliente}.xml",
                      xml, "FATT", "fattura_massiva", cf_cliente, dest_dir, sottocartella, log)


def richiesta_corrispettivi(auth: AuthResult, dal: str, al: str, cf_cliente: str,
                            piva: str, dest_dir: str | None = None,
                            sottocartella: bool = True, log=print) -> str:
    """Richiesta massiva CORRISPETTIVI (tipo RT). Date AAAA-MM-GG."""
    _valida_intervallo_iso(dal, al)
    xml = _xml_corrispettivi(piva, dal, al)
    return _invia_xml(auth, "inviocorrispettivi", f"COR_{cf_cliente}.xml", xml,
                      "CORR", "corrispettivi", cf_cliente, dest_dir, sottocartella, log)


# ─────────────────────────────────────────────────────────────────────────────
# Bolli virtuali (genera PDF F24)
# ─────────────────────────────────────────────────────────────────────────────

def scarica_bolli(auth: AuthResult, cf_cliente: str, piva: str, trimestre: str,
                  anno: str, dest_dir: str | None = None,
                  sottocartella: bool = True, log=print) -> str | None:
    """
    Scarica i dati dei bolli virtuali per `trimestre`/`anno` e genera il PDF F24.
    Ritorna il percorso del PDF salvato, o None se non ci sono bolli.
    """
    log(f"Scarico bolli virtuali per {cf_cliente}  Trim.{trimestre}/{anno}")
    # GET di "riscaldamento" sull'app di consultazione (innocua, come nell'originale).
    auth.session.get(f"{IVASERVIZI}/cons/cons-web/?v={unix_time()}",
                     headers=auth.headers, verify=False)

    r = auth.session.get(
        f"{IVASERVIZI}/cons/cons-services/rs/fe/bollo/elenco/X/{anno}/{trimestre}?v={unix_time()}",
        headers=auth.headers, verify=False)
    if r.status_code != 200:
        raise DownloadError(f"Elenco bolli non ottenuto (HTTP {r.status_code}).")
    try:
        data = r.json()
    except ValueError:
        raise DownloadError("Risposta elenco bolli non in JSON (sessione scaduta?).")

    bolli = data.get("fattureBollo") or []
    if not bolli:
        log("Nessun bollo trovato per il trimestre/anno indicato.")
        return None
    bollojson = bolli[0]
    log(f"Dettaglio bollo: {bollojson}")

    # Dettaglio (come nell'originale: prepara il contesto lato server).
    auth.session.get(
        f"{IVASERVIZI}/cons/cons-services/rs/fe/bollo/dettaglio/{trimestre}{anno}{piva}?v={unix_time()}",
        headers=auth.headers, verify=False)

    base = dest_dir or DEFAULT_DEST_DIR
    cartella = base if not sottocartella else os.path.join(base, f"F24_Bolli_{trimestre}{anno}")
    os.makedirs(cartella, exist_ok=True)

    headers_json = {**auth.headers, "Content-Type": "application/json"}
    r_pdf = auth.session.post(
        f"{IVASERVIZI}/cons/cons-services/rs/fe/bollo/stampa/F24",
        data=json.dumps(bollojson).encode("utf-8"),
        headers=headers_json, verify=False)
    if r_pdf.status_code != 200:
        raise DownloadError(f"Errore generazione PDF F24 (HTTP {r_pdf.status_code}).")

    pdf_path = os.path.join(cartella, f"{cf_cliente}_F24_BOLLI.PDF")
    with open(pdf_path, "wb") as f:
        f.write(r_pdf.content)
    log(f"PDF salvato: {pdf_path}")
    return pdf_path
