#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.03 alpha
"""
fec_download.py - Download fatture elettroniche dal portale AdE "Fatture e
Corrispettivi", a partire da una sessione GIÀ autenticata.

A differenza dei vecchi script `fec_*.py` (che autenticavano da soli leggendo
le credenziali da `sys.argv`), qui le funzioni ricevono un `AuthResult`
prodotto da `ade_auth.autentica(...)`: l'autenticazione avviene UNA sola volta
nel chiamante (la GUI), in-process, senza password sulla riga di comando.

Gli endpoint sono portati 1:1 dai vecchi script `fec_*.py`.

Download di consultazione (date `ddmmyyyy`); tutte accettano anche
`escludi_scartate_pa=True` (salta le fatture rifiutate dalla P.A.) e
`estrai_p7m=False` (estrae l'XML dai file firmati .p7m al posto dell'originale):
    scarica_emesse(auth, dal, al, cf_cliente, dest_dir=None, log=print)
    scarica_ricevute(auth, dal, al, cf_cliente, tipo_data=1, dest_dir=None, log=print)
    scarica_transfrontaliere_emesse(auth, dal, al, cf_cliente, dest_dir=None, log=print)
    scarica_transfrontaliere_ricevute(auth, dal, al, cf_cliente, dest_dir=None, log=print)
    scarica_messe_a_disposizione(auth, dal, al, cf_cliente, dest_dir=None, log=print)

Richieste massive / corrispettivi (genera XML e lo carica; date `AAAA-MM-GG`):
    richiesta_massiva_emesse(auth, dal, al, cf_cliente, piva, dest_dir=None, log=print)
    richiesta_massiva_ricevute_emissione(auth, dal, al, cf_cliente, piva, dest_dir=None, log=print)
    richiesta_massiva_ricevute_ricezione(auth, dal, al, cf_cliente, piva, dest_dir=None, log=print)
    richiesta_massiva_disposizione(auth, dal, al, cf_cliente, piva, dest_dir=None, log=print)
    richiesta_corrispettivi(auth, dal, al, cf_cliente, piva, dest_dir=None, log=print)

Bolli virtuali (riepilogo CSV: elenco A/B, importo, stato pagamento):
    scarica_bolli(auth, cf_cliente, piva, trimestre, anno, dest_dir=None, log=print)

Risultati delle Richieste Massive:
    elenco_risposte_massive(auth, log=print) -> list[dict]
    dettaglio_risposta_massiva(auth, id_richiesta, log=print) -> dict
    scarica_risposta_massiva(auth, id_richiesta, cf_cliente="", tipo_label="", dal="", al="",
                            dest_dir=None, sottocartella=True, estrai_zip=False,
                            log=print) -> list[str]
    estrai_zip_risultato(zip_path, log=print) -> str  (estrazione differita, GUI)
"""

from __future__ import annotations

__version__ = "0.03 alpha"

import csv
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime

import requests

from ade_auth import AuthResult, IVASERVIZI, unix_time

# Eseguibile PyInstaller: cartella Download di default accanto all'exe.
if getattr(sys, "frozen", False):
    SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DEST_DIR = os.path.join(SCRIPT_DIR, "Download")

# Timeout HTTP (secondi): (connessione, inattività in lettura). Il read-timeout è
# l'inattività del socket, NON la durata totale → non spezza i download grandi che
# scaricano a flusso continuo, ma evita che una risposta mai inviata blocchi la GUI
# all'infinito (→ DownloadError leggibile invece di freeze).
HTTP_TIMEOUT = (15, 120)


class DownloadError(RuntimeError):
    """Errore durante lo scarico (lista non ottenuta, sessione scaduta, ...)."""


class DownloadAnnullato(DownloadError):
    """Sollevato quando l'utente interrompe il download (annullamento cooperativo)."""


class Controllo:
    """
    Controllo cooperativo di PAUSA/ANNULLAMENTO di un download, per-sessione (nessuno
    stato globale, adatto anche a un server multi-utente). Un thread Python non si
    può uccidere a forza: il loop di download chiama `check()` nei punti interrompibili
    (tra un file e l'altro), dove questo blocca finché è in pausa e solleva
    DownloadAnnullato se è stato annullato.
    """

    def __init__(self):
        import threading
        self._pausa = threading.Event()      # set = in pausa
        self._annulla = threading.Event()    # set = annullato

    def pausa(self):    self._pausa.set()
    def riprendi(self): self._pausa.clear()
    def annulla(self):
        self._annulla.set()
        self._pausa.clear()                  # sblocca un'eventuale pausa in corso

    def in_pausa(self):  return self._pausa.is_set()
    def annullato(self): return self._annulla.is_set()

    def check(self):
        """Blocca finché in pausa; solleva DownloadAnnullato se annullato."""
        while self._pausa.is_set() and not self._annulla.is_set():
            self._annulla.wait(0.1)
        if self._annulla.is_set():
            raise DownloadAnnullato("Download interrotto dall'utente.")


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


def _e_scartata_pa(auth: AuthResult, fattura_file: str, log) -> bool:
    """
    True se la fattura è stata rifiutata dalla P.A. destinataria.

    Chiama l'endpoint di dettaglio (`rs/fatture/dettaglio/<fattura_file>`, lo stesso
    usato dal frontend AdE per la pagina "Dettaglio fattura") e cerca la sottostringa
    "rifiutat" (case-insensitive) nel corpo grezzo della risposta: euristica robusta
    a non conoscere il nome esatto del campo JSON restituito dall'endpoint. Su
    qualunque errore (HTTP/JSON) non blocca il download: considera
    la fattura non scartata e prosegue (log di avviso).
    """
    url = (f"{IVASERVIZI}/cons/cons-services/rs/fatture/dettaglio/{fattura_file}"
           f"?v={unix_time()}")
    try:
        r = auth.session.get(url, headers=auth.headers, verify=False, timeout=HTTP_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        log(f"   ⚠️  Dettaglio {fattura_file} non ottenuto ({exc}); considero non scartata.")
        return False
    if r.status_code != 200:
        log(f"   ⚠️  Dettaglio {fattura_file}: HTTP {r.status_code}; considero non scartata.")
        return False
    return "rifiutat" in r.text.lower()


def _estrai_p7m(contenuto_p7m: bytes, log) -> bytes | None:
    """
    Estrae il contenuto firmato (XML) da una busta CMS/PKCS7 (.p7m).

    Ritorna i byte dell'XML originale, o None se l'estrazione non è possibile
    (libreria `asn1crypto` mancante, o busta non decodificabile): in quel caso il
    chiamante deve mantenere il `.p7m` originale per non perdere il file.
    """
    try:
        from asn1crypto import cms
    except ImportError:
        import fec_deps
        log("   ⚠️  Estrazione p7m richiesta ma «asn1crypto» non è installato "
            f"({fec_deps.pip_install_hint(['asn1crypto'])}); salvo il .p7m originale.")
        return None
    try:
        info = cms.ContentInfo.load(contenuto_p7m)
        return info["content"]["encap_content_info"]["content"].native
    except Exception as exc:
        log(f"   ⚠️  Estrazione p7m fallita ({exc}); salvo il .p7m originale.")
        return None


def _get_con_retry(auth: AuthResult, url: str, log, tentativi: int = 3):
    """
    GET con ritentativi sugli errori di connessione (es. 'RemoteDisconnected' su
    connessioni keep-alive riutilizzate dall'AdE durante download lunghi/a blocchi).
    Ritorna la Response, o solleva DownloadError se falliscono tutti i tentativi.
    """
    ultimo_errore: Exception | None = None
    for tentativo in range(1, tentativi + 1):
        try:
            return auth.session.get(url, verify=False, timeout=HTTP_TIMEOUT)
        except requests.exceptions.RequestException as exc:
            ultimo_errore = exc
            if tentativo < tentativi:
                log(f"   ⚠️  Connessione interrotta ({exc}); ritento "
                    f"({tentativo}/{tentativi - 1})...")
                time.sleep(1.5 * tentativo)
    raise DownloadError(
        f"Connessione interrotta dopo {tentativi} tentativi: {ultimo_errore}. "
        "Riprova; se persiste, riduci il periodo."
    )


def _scarica_da_lista(auth: AuthResult, url_lista: str, dest_dir: str,
                      log=print, control: "Controllo | None" = None,
                      escludi_scartate_pa: bool = True,
                      estrai_p7m: bool = False) -> tuple[int, int]:
    """
    Scarica file fattura + metadati per ogni voce restituita da `url_lista`.

    Ciclo identico a `fec_emesse.py` / `fec_ricevute.py`: per ogni fattura,
    `fatturaFile = tipoInvio + idFattura`, poi GET FILE_FATTURA e FILE_METADATI.
    Ritorna (n_fatture, n_metadati). Se `control` è passato, tra un file e l'altro
    rispetta pausa/annullamento (solleva DownloadAnnullato se annullato).

    `escludi_scartate_pa` (default True): prima di scaricare FILE_FATTURA/FILE_METADATI,
    verifica via `_e_scartata_pa` se la fattura è stata rifiutata dalla P.A. destinataria
    e, in caso, la salta interamente (nessun file scritto, contatori invariati).

    `estrai_p7m` (default False): se il file scaricato è firmato (`.p7m`), estrae l'XML
    e lo salva al posto dell'originale (mai entrambi); se l'estrazione non riesce, salva
    comunque il `.p7m` originale.
    """
    log("Richiedo l'elenco fatture all'AdE...")
    try:
        r = auth.session.get(url_lista, headers=auth.headers, verify=False, timeout=HTTP_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        raise DownloadError(
            f"Nessuna risposta dall'AdE per l'elenco fatture entro il tempo limite "
            f"({HTTP_TIMEOUT[1]}s): {exc}. Riprova; se persiste, riduci il periodo."
        )
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

    log(f"Trovate {len(fatture)} fatture nell'intervallo. Avvio download dei file...")
    n_fatture = n_metadati = 0
    for fattura in fatture:
        if control is not None:
            control.check()   # pausa/annullamento cooperativo tra un file e l'altro
        fattura_file = fattura["tipoInvio"] + fattura["idFattura"]

        if escludi_scartate_pa and _e_scartata_pa(auth, fattura_file, log):
            log(f"   ⏭️  Fattura {fattura_file} rifiutata dalla P.A.: saltata.")
            continue

        try:
            r2 = _get_con_retry(auth, _file_url(fattura_file, "FILE_FATTURA"), log)
        except DownloadError as exc:
            log(f"   ❌ Fattura {fattura_file} saltata: {exc}")
            continue
        fmetadato = None
        if r2.status_code == 200:
            n_fatture += 1
            fname = re.findall("filename=(.+)", r2.headers["content-disposition"])[0]
            fmetadato = fname
            contenuto = r2.content
            if estrai_p7m and fname.lower().endswith(".p7m"):
                estratto = _estrai_p7m(contenuto, log)
                if estratto is not None:
                    fname = fname[:-len(".p7m")]
                    fmetadato = fname
                    contenuto = estratto
            log(f"Scarico {fname}  (tot. {n_fatture})")
            with open(os.path.join(dest_dir, fname), "wb") as f:
                f.write(contenuto)

        try:
            r3 = _get_con_retry(auth, _file_url(fattura_file, "FILE_METADATI"), log)
        except DownloadError as exc:
            log(f"   ❌ Metadato {fattura_file} saltato: {exc}")
            continue
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
                   log=print, control: "Controllo | None" = None,
                   escludi_scartate_pa: bool = True,
                   estrai_p7m: bool = False) -> DownloadResult:
    """
    Scarica le fatture EMESSE nell'intervallo [dal, al] (formato ddmmyyyy).
    `auth` deve essere già autenticato (vedi `ade_auth.autentica`).
    """
    cartella = _cartella(dest_dir, "FattureEmesse", cf_cliente, sottocartella)
    log(f"Scarico fatture emesse per {cf_cliente}  ({dal} -> {al})")
    url = f"{IVASERVIZI}/cons/cons-services/rs/fe/emesse/dal/{dal}/al/{al}?v={unix_time()}"
    n_fatture, n_metadati = _scarica_da_lista(auth, url, cartella, log, control,
                                              escludi_scartate_pa, estrai_p7m)
    log(f"\nCliente: {cf_cliente}")
    log(f"Fatture scaricate:  {n_fatture}")
    log(f"Metadati scaricati: {n_metadati}")
    log(f"Cartella: {cartella}")
    return DownloadResult(cf_cliente, cartella, n_fatture, n_metadati)


def scarica_ricevute(auth: AuthResult, dal: str, al: str, cf_cliente: str,
                     tipo_data: int = 1, dest_dir: str | None = None,
                     sottocartella: bool = True, log=print,
                     control: "Controllo | None" = None,
                     escludi_scartate_pa: bool = True,
                     estrai_p7m: bool = False) -> DownloadResult:
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
    n_fatture, n_metadati = _scarica_da_lista(auth, url, cartella, log, control,
                                              escludi_scartate_pa, estrai_p7m)
    log(f"\nCliente: {cf_cliente}")
    log(f"Fatture ricevute scaricate:  {n_fatture}")
    log(f"Metadati scaricati: {n_metadati}")
    log(f"Cartella: {cartella}")
    return DownloadResult(cf_cliente, cartella, n_fatture, n_metadati)


def scarica_transfrontaliere_emesse(auth: AuthResult, dal: str, al: str,
                                    cf_cliente: str, dest_dir: str | None = None,
                                    sottocartella: bool = True,
                                    log=print,
                                    control: "Controllo | None" = None,
                                    escludi_scartate_pa: bool = True,
                                    estrai_p7m: bool = False) -> DownloadResult:
    """Fatture transfrontaliere EMESSE nell'intervallo [dal, al] (ddmmyyyy)."""
    cartella = _cartella(dest_dir, "FattureEmesseTRAN", cf_cliente, sottocartella)
    log(f"Scarico fatture transfrontaliere emesse per {cf_cliente}  ({dal} -> {al})")
    url = f"{IVASERVIZI}/cons/cons-services/rs/ft/emesse/dal/{dal}/al/{al}?v={unix_time()}"
    n_fatture, n_metadati = _scarica_da_lista(auth, url, cartella, log, control,
                                              escludi_scartate_pa, estrai_p7m)
    log(f"\nCliente: {cf_cliente}")
    log(f"Transfrontaliere emesse scaricate: {n_fatture}")
    log(f"Metadati scaricati: {n_metadati}")
    log(f"Cartella: {cartella}")
    return DownloadResult(cf_cliente, cartella, n_fatture, n_metadati)


def scarica_transfrontaliere_ricevute(auth: AuthResult, dal: str, al: str,
                                      cf_cliente: str, dest_dir: str | None = None,
                                      sottocartella: bool = True,
                                      log=print,
                                      control: "Controllo | None" = None,
                                      escludi_scartate_pa: bool = True,
                                      estrai_p7m: bool = False) -> DownloadResult:
    """Fatture transfrontaliere RICEVUTE nell'intervallo [dal, al] (ddmmyyyy)."""
    cartella = _cartella(dest_dir, "FattureRicevuteTRAN", cf_cliente, sottocartella)
    log(f"Scarico fatture transfrontaliere ricevute per {cf_cliente}  ({dal} -> {al})")
    url = f"{IVASERVIZI}/cons/cons-services/rs/ft/ricevute/dal/{dal}/al/{al}?v={unix_time()}"
    n_fatture, n_metadati = _scarica_da_lista(auth, url, cartella, log, control,
                                              escludi_scartate_pa, estrai_p7m)
    log(f"\nCliente: {cf_cliente}")
    log(f"Transfrontaliere ricevute scaricate: {n_fatture}")
    log(f"Metadati scaricati: {n_metadati}")
    log(f"Cartella: {cartella}")
    return DownloadResult(cf_cliente, cartella, n_fatture, n_metadati)


def scarica_messe_a_disposizione(auth: AuthResult, dal: str, al: str,
                                 cf_cliente: str, dest_dir: str | None = None,
                                 sottocartella: bool = True,
                                 log=print,
                                 control: "Controllo | None" = None,
                                 escludi_scartate_pa: bool = True,
                                 estrai_p7m: bool = False) -> DownloadResult:
    """Fatture ricevute "messe a disposizione" nell'intervallo [dal, al] (ddmmyyyy)."""
    cartella = _cartella(dest_dir, "FattureRicevuteDisposizione", cf_cliente, sottocartella)
    log(f"Scarico fatture messe a disposizione per {cf_cliente}  ({dal} -> {al})")
    url = f"{IVASERVIZI}/cons/cons-services/rs/fe/mc/dal/{dal}/al/{al}?v={unix_time()}"
    n_fatture, n_metadati = _scarica_da_lista(auth, url, cartella, log, control,
                                              escludi_scartate_pa, estrai_p7m)
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


def _xml_massivo_disposizione(piva: str, dal: str, al: str) -> str:
    """
    Corpo XML di una richiesta massiva fatture MESSE A DISPOSIZIONE (fatture
    elettroniche non recapitabili al destinatario, rese disponibili sul portale
    lato CESSIONARIO). A differenza di `_xml_massivo_fatture` usa il tag dedicato
    `<FattureFEDisposizione>` (solo `DataEmissione` + `Ruolo`, senza `<Flusso>`).
    """
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
\t\t\t<ns1:FattureFEDisposizione>
\t\t\t\t<ns1:DataEmissione>
\t\t\t\t\t<ns1:Da>{dal}</ns1:Da>
\t\t\t\t\t<ns1:A>{al}</ns1:A>
\t\t\t\t</ns1:DataEmissione>
\t\t\t\t<ns1:Ruolo>CESSIONARIO</ns1:Ruolo>
\t\t\t</ns1:FattureFEDisposizione>
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
        base_nome, ext = os.path.splitext(nome_xml)
        nuovo_nome = f"{base_nome}_inviato_il_{now.strftime('%Y-%m-%d')}{ext}"
        os.replace(percorso, os.path.join(cartella, nuovo_nome))
    except OSError:
        pass
    return codice


def richiesta_massiva_emesse(auth: AuthResult, dal: str, al: str, cf_cliente: str,
                             piva: str, dest_dir: str | None = None,
                             sottocartella: bool = True, suffisso_nome: str = "",
                             log=print) -> str:
    """Richiesta massiva fatture EMESSE (per data emissione). Date AAAA-MM-GG."""
    _valida_intervallo_iso(dal, al)
    xml = _xml_massivo_fatture(piva, dal, al, "FattureEmesse", "DataEmissione", "CEDENTE")
    return _invia_xml(auth, "inviomassivo", f"FATT_{cf_cliente}{suffisso_nome}.xml", xml,
                      "FATT", "fattura_massiva", cf_cliente, dest_dir, sottocartella, log)


def richiesta_massiva_ricevute_emissione(auth: AuthResult, dal: str, al: str,
                                         cf_cliente: str, piva: str,
                                         dest_dir: str | None = None,
                                         sottocartella: bool = True,
                                         suffisso_nome: str = "",
                                         log=print) -> str:
    """Richiesta massiva fatture RICEVUTE per data EMISSIONE. Date AAAA-MM-GG."""
    _valida_intervallo_iso(dal, al)
    xml = _xml_massivo_fatture(piva, dal, al, "FattureRicevute", "DataEmissione", "CESSIONARIO")
    return _invia_xml(auth, "inviomassivo", f"FATT_M_RICEVUTE_EMISSIONE{cf_cliente}{suffisso_nome}.xml",
                      xml, "FATT", "fattura_massiva", cf_cliente, dest_dir, sottocartella, log)


def richiesta_massiva_ricevute_ricezione(auth: AuthResult, dal: str, al: str,
                                         cf_cliente: str, piva: str,
                                         dest_dir: str | None = None,
                                         sottocartella: bool = True,
                                         suffisso_nome: str = "",
                                         log=print) -> str:
    """Richiesta massiva fatture RICEVUTE per data RICEZIONE. Date AAAA-MM-GG."""
    _valida_intervallo_iso(dal, al)
    xml = _xml_massivo_fatture(piva, dal, al, "FattureRicevute", "DataRicezione", "CESSIONARIO")
    return _invia_xml(auth, "inviomassivo", f"FATT_M_RICEVUTE_RICEZIONE{cf_cliente}{suffisso_nome}.xml",
                      xml, "FATT", "fattura_massiva", cf_cliente, dest_dir, sottocartella, log)


def richiesta_massiva_disposizione(auth: AuthResult, dal: str, al: str, cf_cliente: str,
                                   piva: str, dest_dir: str | None = None,
                                   sottocartella: bool = True, suffisso_nome: str = "",
                                   log=print) -> str:
    """Richiesta massiva fatture MESSE A DISPOSIZIONE (per data emissione, ruolo
    CESSIONARIO). Date AAAA-MM-GG."""
    _valida_intervallo_iso(dal, al)
    xml = _xml_massivo_disposizione(piva, dal, al)
    return _invia_xml(auth, "inviomassivo", f"FATT_M_DISPOSIZIONE{cf_cliente}{suffisso_nome}.xml",
                      xml, "FATT", "fattura_massiva", cf_cliente, dest_dir, sottocartella, log)


def richiesta_corrispettivi(auth: AuthResult, dal: str, al: str, cf_cliente: str,
                            piva: str, dest_dir: str | None = None,
                            sottocartella: bool = True, suffisso_nome: str = "",
                            log=print) -> str:
    """Richiesta massiva CORRISPETTIVI (tipo RT). Date AAAA-MM-GG."""
    _valida_intervallo_iso(dal, al)
    xml = _xml_corrispettivi(piva, dal, al)
    return _invia_xml(auth, "inviocorrispettivi", f"COR_{cf_cliente}{suffisso_nome}.xml", xml,
                      "CORR", "corrispettivi", cf_cliente, dest_dir, sottocartella, log)


def elenco_risposte_massive(auth: AuthResult, log=print) -> list[dict]:
    """
    Elenca le risposte (risultati) disponibili sul portale per le Richieste Massive
    inviate in precedenza, pagina Angular `.../cons/mass-web/?v=...#/risposte/elenco`.

    `GET /cons/mass-services/rs/consultazione/richieste` ritorna `{"richiesteMassive":
    [{idRichiesta, dataInserimento, stato, dataElaborazione, tipoRichiesta ("FATT"|
    "CORR"), descrizioneTipoRichiesta, ...}, ...]}`. `stato == "Elaborata"` = pronta
    per il download (altro stato osservato: "Acquisita - in elaborazione").
    """
    url = f"{IVASERVIZI}/cons/mass-services/rs/consultazione/richieste?v={unix_time()}"
    try:
        r = auth.session.get(url, headers=auth.headers, verify=False, timeout=HTTP_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        raise DownloadError(
            f"Nessuna risposta dall'AdE per l'elenco risultati entro il tempo limite "
            f"({HTTP_TIMEOUT[1]}s): {exc}.")
    if r.status_code != 200:
        raise DownloadError(
            f"Elenco risultati non ottenuto (HTTP {r.status_code}). La sessione potrebbe "
            "essere scaduta o l'utenza di lavoro non attiva.")
    try:
        data = r.json()
    except ValueError:
        raise DownloadError(
            "Risposta non in formato JSON: probabile sessione scaduta o redirect al login.")
    richieste = data.get("richiesteMassive")
    if richieste is None:
        raise DownloadError(
            "La risposta non contiene l'elenco 'richiesteMassive' atteso "
            f"(chiavi ricevute: {sorted(data)[:8]}).")
    log(f"Trovate {len(richieste)} richieste massive sul portale.")
    return richieste


def dettaglio_risposta_massiva(auth: AuthResult, id_richiesta: str, log=print) -> dict:
    """
    Dettaglio di una singola richiesta massiva: dà l'elenco `fileProdotto`
    (normalmente uno, `{numeroElementiContenuti, size, file}`) necessario per costruire
    l'URL di download. `GET /cons/mass-services/rs/consultazione/richiesta/{id}`.
    """
    url = f"{IVASERVIZI}/cons/mass-services/rs/consultazione/richiesta/{id_richiesta}?v={unix_time()}"
    try:
        r = auth.session.get(url, headers=auth.headers, verify=False, timeout=HTTP_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        raise DownloadError(
            f"Nessuna risposta dall'AdE per il dettaglio della richiesta {id_richiesta} "
            f"entro il tempo limite ({HTTP_TIMEOUT[1]}s): {exc}.")
    if r.status_code != 200:
        raise DownloadError(
            f"Dettaglio della richiesta {id_richiesta} non ottenuto (HTTP {r.status_code}).")
    try:
        return r.json()
    except ValueError:
        raise DownloadError("Risposta dettaglio non in formato JSON.")


def _slug(testo: str) -> str:
    """Riduce un'etichetta leggibile (es. «Fatture Ricevute (per emissione)») a un
    frammento sicuro per nomi file: solo lettere/cifre, senza spazi/parentesi/accenti."""
    return re.sub(r"[^A-Za-z0-9]+", "", testo or "")


def _data_compatta(data: str) -> str:
    """Riduce una data (qualunque formato coi soli separatori non numerici, es.
    2026-04-01 o 01/04/2026) alla sola sequenza di cifre (AAAAMMGG)."""
    return re.sub(r"\D", "", data or "")


def scarica_risposta_massiva(auth: AuthResult, id_richiesta: str, cf_cliente: str = "",
                             tipo_label: str = "", dal: str = "", al: str = "",
                             dest_dir: str | None = None, sottocartella: bool = True,
                             estrai_zip: bool = False, log=print) -> list[str]:
    """
    Scarica il/i file prodotto/i dall'AdE per `id_richiesta`.

    Interroga il dettaglio per ottenere `fileProdotto[]` (`file` = nome interno, es.
    "fileProdotto1"), poi per ciascuno replica la sequenza del portale: prima
    `GET .../rs/tracc/download/id/{id}/nomeFile/{file}` (solo tracciamento lato AdE,
    risposta vuota; errori qui non bloccano il download vero), poi
    `GET .../rs/file/download/id/{id}/nomeFile/{file}/` che ritorna lo zip
    (`Content-Disposition: attachment; filename={id}_{file}.zip`, contenuto: coppie
    `<fattura>.xml` / `<fattura>.xml_metaDato.xml`, stesso schema dei metadati di
    consultazione).

    Il file salvato viene rinominato in `<cf>_<tipo>_<dal><al>.zip` (`tipo_label`
    ridotta a lettere/cifre, date compattate AAAAMMGG) quando `cf_cliente`/
    `tipo_label` sono noti; il periodo compare solo se sono passati sia `dal` sia
    `al` (per le richieste "scoperte" sul portale, non inviate da questa
    applicazione, il periodo non è mai recuperabile dall'AdE). Se non si ha né CF né
    tipo, resta il nome storico `<idRichiesta>_<fileProdotto>.zip`.

    Con `estrai_zip=True` lo zip viene estratto in una sottocartella (nome senza
    `.zip`) e poi rimosso, mai entrambi (stessa logica dell'estrazione dei p7m).
    Ritorna la lista dei percorsi salvati (zip, o cartelle estratte).
    """
    dettaglio = dettaglio_risposta_massiva(auth, id_richiesta, log=log)
    files = dettaglio.get("fileProdotto") or []
    if not files:
        raise DownloadError(
            f"Richiesta {id_richiesta}: nessun file prodotto disponibile (verifica che lo "
            "stato sia «Elaborata»).")

    cartella = _cartella(dest_dir, "RisultatiMassivi", cf_cliente or id_richiesta, sottocartella)

    parti = [p for p in (cf_cliente.strip(), _slug(tipo_label)) if p]
    if dal and al:
        parti.append(f"{_data_compatta(dal)}_{_data_compatta(al)}")
    nome_base_comune = "_".join(parti) if parti else ""

    salvati = []
    for i, f in enumerate(files, start=1):
        nome_file = str(f.get("file", "")).strip()
        if not nome_file:
            continue
        try:
            auth.session.get(
                f"{IVASERVIZI}/cons/mass-services/rs/tracc/download/id/{id_richiesta}"
                f"/nomeFile/{nome_file}?v={unix_time()}",
                headers=auth.headers, verify=False, timeout=HTTP_TIMEOUT)
        except requests.exceptions.RequestException:
            pass  # solo tracciamento lato AdE: un errore qui non deve bloccare il download

        r = auth.session.get(
            f"{IVASERVIZI}/cons/mass-services/rs/file/download/id/{id_richiesta}"
            f"/nomeFile/{nome_file}/?v={unix_time()}",
            headers=auth.headers, verify=False, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            raise DownloadError(
                f"Download di {nome_file} (richiesta {id_richiesta}) fallito "
                f"(HTTP {r.status_code}).")

        if nome_base_comune:
            # più file prodotti per la stessa richiesta (raro): suffisso numerico
            # per non sovrascriverli a vicenda.
            nome_base = nome_base_comune if len(files) == 1 else f"{nome_base_comune}_{i}"
        else:
            nome_base = f"{id_richiesta}_{nome_file}"
        zip_path = os.path.join(cartella, f"{nome_base}.zip")
        with open(zip_path, "wb") as fh:
            fh.write(r.content)
        log(f"Scaricato {nome_base}.zip ({len(r.content)} byte).")

        if estrai_zip:
            salvati.append(estrai_zip_risultato(zip_path, log=log))
        else:
            salvati.append(zip_path)
    return salvati


def estrai_zip_risultato(zip_path: str, log=print) -> str:
    """
    Estrae `zip_path` (uno zip scaricato da `scarica_risposta_massiva`) in una
    sottocartella accanto ad esso, con lo stesso nome senza `.zip`, e rimuove lo zip
    originale (mai entrambi, stessa logica dell'estrazione dei p7m).

    Riusata sia da `scarica_risposta_massiva` (quando `estrai_zip=True`, estrazione
    immediata) sia dalla GUI per l'estrazione differita, quando l'utente sceglie di
    estrarre dopo il download uno zip lasciato con l'impostazione «estrai automaticamente»
    disattivata. Ritorna il percorso della cartella estratta.
    """
    import zipfile
    estratti_dir = zip_path[:-len(".zip")] if zip_path.lower().endswith(".zip") else zip_path
    os.makedirs(estratti_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(estratti_dir)
    os.remove(zip_path)
    log(f"Estratto in {estratti_dir} (zip rimosso).")
    return estratti_dir


# ─────────────────────────────────────────────────────────────────────────────
# Bolli virtuali (riepilogo CSV: elenco A/B, importo, stato pagamento)
# ─────────────────────────────────────────────────────────────────────────────

_BOLLI_CSV_CAMPI = [
    "anno", "trimestre", "partita_iva", "codice_fiscale",
    "num_documenti_elenco_a", "num_documenti_elenco_b",
    "importo_bollo_calcolato", "data_scadenza",
    "importo_versato", "data_versamento", "codice_tributo", "tipo_pagamento",
]

# Codice tributo F24 per l'imposta di bollo su fatture elettroniche, fisso per
# trimestre (Risoluzione AdE): usato per abbinare ogni versamento (`bolloVersato`,
# che l'AdE riporta senza indicazione esplicita di trimestre) al trimestre giusto,
# indipendentemente da come/quante volte la singola richiesta HTTP lo restituisce.
_BOLLI_CODICE_TRIBUTO_TRIM = {"1": "2521", "2": "2522", "3": "2523", "4": "2524"}
_BOLLI_TRIM_DA_CODICE = {v: k for k, v in _BOLLI_CODICE_TRIBUTO_TRIM.items()}


def _pulisci_importo(raw: str) -> str:
    """
    Converte un importo AdE (es. "+000000000012,00") in un numero pulito
    ("12", o "12,50" se ha decimali non nulli) per un CSV più leggibile.
    """
    if not raw:
        return ""
    s = raw.strip().lstrip("+")
    segno = ""
    if s.startswith("-"):
        segno, s = "-", s[1:]
    intera, _, decimale = s.partition(",")
    intera = intera.lstrip("0") or "0"
    parte_decimale = f",{decimale}" if decimale and decimale.strip("0") else ""
    return f"{segno}{intera}{parte_decimale}"


def scarica_bolli(auth: AuthResult, cf_cliente: str, piva: str, trimestre: str,
                  anno: str, dest_dir: str | None = None,
                  sottocartella: bool = True, log=print,
                  control: "Controllo | None" = None) -> str | None:
    """
    Genera un riepilogo CSV dell'imposta di bollo virtuale: una riga per
    trimestre con dovuto (elenco A/B, importo, scadenza) e versato (importo,
    data, codice tributo) affiancati, utile per verificare dovuto vs versato.

    NB: il portale AdE, per questa procedura, permette solo la CONSULTAZIONE
    dell'imposta calcolata, non la generazione autonoma del modello F24 (va
    fatta a mano sul portale). Tutti i dati del riepilogo sono già presenti
    nella risposta dell'elenco (compresi i versamenti, in `bolloVersato`).

    `trimestre`: "1".."4" per un solo trimestre, oppure vuoto/"tutti"
    (case-insensitive) per l'intero anno (una richiesta per trimestre).
    `piva`: se indicata, filtra il riepilogo dovuto a quella sola P.IVA; se
    vuota (accesso "solo CF"), include tutte le P.IVA del CF trovate dall'AdE
    (i versamenti non riportano la P.IVA, solo il CF).
    Ritorna il percorso del CSV salvato, o None se non ci sono bolli né
    versamenti.
    """
    trimestri = ["1", "2", "3", "4"] if not trimestre or trimestre.strip().lower() == "tutti" \
        else [trimestre]
    if len(trimestri) > 1:
        log(f"Anno {anno}: richiesta su tutti i {len(trimestri)} trimestri.")

    righe_fatture: list[dict] = []
    versamenti: dict[str, dict] = {}  # codice_tributo -> versamento (deduplicato)
    for t in trimestri:
        if control is not None:
            control.check()
        log(f"Bolli virtuali {cf_cliente} - trim.{t}/{anno}")
        r = auth.session.get(
            f"{IVASERVIZI}/cons/cons-services/rs/fe/bollo/elenco/X/{anno}/{t}?v={unix_time()}",
            headers=auth.headers, verify=False)
        if r.status_code != 200:
            log(f"   ⚠️  elenco bolli trim.{t} non ottenuto (HTTP {r.status_code}); salto.")
            continue
        try:
            data = r.json()
        except ValueError:
            log(f"   ⚠️  risposta trim.{t} non in JSON (sessione scaduta?); salto.")
            continue

        trovate = data.get("fattureBollo") or []
        if piva:
            trovate = [b for b in trovate if str(b.get("partitaIva", "")).strip() == piva]
        if not trovate:
            log(f"   Nessun bollo trovato per il trim.{t}.")
        righe_fatture.extend(trovate)

        for v in (data.get("bolloVersato") or []):
            codice = str(v.get("codiceTributo", "")).strip()
            if codice:
                versamenti[codice] = v

    if not righe_fatture and not versamenti:
        log("Nessun bollo trovato per il periodo indicato.")
        return None

    cartella = _cartella(dest_dir, "Bolli", cf_cliente, sottocartella)
    suffisso_trim = "" if len(trimestri) > 1 else f"_T{trimestri[0]}"
    csv_path = os.path.join(cartella, f"{cf_cliente}_Bolli_{anno}{suffisso_trim}.csv")

    # Abbina ogni riga "dovuto" al versamento del suo trimestre (via codice tributo).
    codici_usati: set[str] = set()
    output: list[dict] = []
    for b in righe_fatture:
        codice_atteso = _BOLLI_CODICE_TRIBUTO_TRIM.get(str(b.get("trimestre", "")).strip())
        v = versamenti.get(codice_atteso, {}) if codice_atteso else {}
        if codice_atteso:
            codici_usati.add(codice_atteso)
        output.append({
            "anno": b.get("anno", anno),
            "trimestre": b.get("trimestre", ""),
            # ="..." forza Excel a trattare la P.IVA come testo (altrimenti la
            # converte in numero, perdendo eventuali zeri iniziali).
            "partita_iva": f'="{b.get("partitaIva", "")}"',
            "codice_fiscale": b.get("codiceFiscale", ""),
            "num_documenti_elenco_a": b.get("numDocumenti", ""),
            "num_documenti_elenco_b": b.get("numDocumentiB", ""),
            "importo_bollo_calcolato": _pulisci_importo(b.get("totCalcolato", "")),
            "data_scadenza": b.get("dataScadenza", ""),
            "importo_versato": _pulisci_importo(v.get("importoVersato", "")),
            "data_versamento": v.get("dataVersamento", ""),
            "codice_tributo": v.get("codiceTributo", ""),
            "tipo_pagamento": v.get("tipoPagamento", ""),
        })

    # Versamenti che non hanno trovato un dovuto corrispondente (es. codice
    # tributo inatteso, o trimestre versato ma senza righe fatture): righe extra,
    # per non perdere l'informazione.
    for codice, v in versamenti.items():
        if codice in codici_usati:
            continue
        output.append({
            "anno": v.get("anno", anno),
            "trimestre": _BOLLI_TRIM_DA_CODICE.get(codice, ""),
            "partita_iva": "",
            "codice_fiscale": v.get("codiceFiscale", ""),
            "num_documenti_elenco_a": "",
            "num_documenti_elenco_b": "",
            "importo_bollo_calcolato": "",
            "data_scadenza": "",
            "importo_versato": _pulisci_importo(v.get("importoVersato", "")),
            "data_versamento": v.get("dataVersamento", ""),
            "codice_tributo": v.get("codiceTributo", ""),
            "tipo_pagamento": v.get("tipoPagamento", ""),
        })

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=_BOLLI_CSV_CAMPI, delimiter=";")
        writer.writeheader()
        for row in output:
            writer.writerow(row)

    log(f"\nCliente: {cf_cliente}")
    log(f"Righe riepilogo: {len(output)}")
    log(f"CSV: {csv_path}")
    return csv_path
