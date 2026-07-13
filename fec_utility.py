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
# Parser difensivo (i nomi campo JSON dell'AdE vanno confermati col dump di
# discovery: qui si prova una rosa di alias e si degrada a vuoto se assenti)
# ─────────────────────────────────────────────────────────────────────────────

# Colonne fisse dell'Excel (prima delle coppie pivot per aliquota).
COLONNE_FISSE = ["Data", "N. Fattura", "ID SDI", "Tipo Documento",
                 "Cliente/Fornitore", "Partita IVA"]
COLONNE_TOTALI = ["Tot. Imponibile", "Tot. IVA", "Totale Fattura", "Bollo Virtuale"]

# Tipi documento che rappresentano note di credito (importi da negare).
_TIPI_NOTA_CREDITO = ("TD04", "TD08")


def _campo(d: dict | None, *nomi: str, default=None):
    """Primo valore non-None tra gli alias `nomi` (match case-insensitive sulle chiavi)."""
    if not isinstance(d, dict):
        return default
    minuscole = {k.lower(): v for k, v in d.items()}
    for nome in nomi:
        val = minuscole.get(nome.lower())
        if val is not None:
            return val
    return default


def _importo(val) -> float:
    """
    Converte un importo AdE in float: gestisce numeri nativi, il formato grezzo
    `+000000000012,00`, separatori italiani `1.234,56` e stringhe vuote → 0.0.
    """
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace("€", "").strip()
    if not s:
        return 0.0
    segno = -1.0 if s.startswith("-") else 1.0
    s = s.lstrip("+-")
    if "," in s:                       # formato italiano: la virgola è il decimale
        s = s.replace(".", "").replace(",", ".")
    try:
        return segno * float(s)
    except ValueError:
        return 0.0


def _chiave_aliquota(riga_iva: dict) -> str | None:
    """
    Chiave pivot di una riga di riepilogo IVA: `"22%"` per le aliquote numeriche,
    il codice natura (`"N2.1"`) per le operazioni senza imposta, None se indeterminabile.
    """
    aliquota = _campo(riga_iva, "aliquotaIVA", "aliquota", "aliquotaIva")
    natura = _campo(riga_iva, "natura", "codiceNatura", "naturaOperazione")
    if aliquota is not None and str(aliquota).strip():
        n = _importo(aliquota)
        if n > 0 or not natura:
            return f"{n:g}%".replace(".", ",")     # 22.0 → "22%", 10.5 → "10,5%"
    if natura and str(natura).strip():
        return str(natura).strip().upper()
    return None


def _righe_riepilogo_iva(dettaglio: dict | None) -> list[dict]:
    """
    Trova nel JSON di dettaglio la lista delle righe di riepilogo IVA, senza conoscere
    la chiave contenitore: cerca ricorsivamente la prima lista di dict che abbia sia
    un campo imponibile sia un campo imposta/aliquota (struttura della tabella
    «Riepiloghi» della pagina Dettaglio fattura del portale).
    """
    def _sembra_riepilogo(lst) -> bool:
        return (isinstance(lst, list) and lst and isinstance(lst[0], dict)
                and _campo(lst[0], "imponibile", "imponibileImporto") is not None
                and (_campo(lst[0], "imposta", "aliquotaIVA", "aliquota",
                            "aliquotaIva") is not None))

    def _cerca(nodo):
        if _sembra_riepilogo(nodo):
            return nodo
        if isinstance(nodo, dict):
            for v in nodo.values():
                trovato = _cerca(v)
                if trovato is not None:
                    return trovato
        elif isinstance(nodo, list):
            for v in nodo:
                trovato = _cerca(v)
                if trovato is not None:
                    return trovato
        return None

    return _cerca(dettaglio) or []


def _e_nota_credito(tipo_doc: str) -> bool:
    t = (tipo_doc or "").upper()
    return any(td in t for td in _TIPI_NOTA_CREDITO) or "NOTA DI CREDITO" in t


def _estrai_riga(voce: dict, dettaglio: dict | None) -> dict:
    """
    Riga Excel per una fattura: unisce i campi della voce di lista con le righe di
    riepilogo IVA del dettaglio. Ritorna un dict con le chiavi di COLONNE_FISSE,
    più `iva` = {chiave_aliquota: [imponibile, imposta]} e i tre totali numerici.
    Per le note di credito tutti gli importi sono negati.
    """
    intestazione = dettaglio if isinstance(dettaglio, dict) else {}
    tipo_doc = str(_campo(voce, "tipoDocumento", "tipoDoc", "descTipoDocumento",
                          default=_campo(intestazione, "tipoDocumento", "tipoDoc",
                                         default="")) or "")
    controparte = _campo(voce, "denominazione", "denominazioneCedente",
                         "denominazioneCessionario", "cliente", "fornitore",
                         "ragioneSociale", "nome", default="") or ""
    riga = {
        "Data": _campo(voce, "dataEmissione", "dataFattura", "data",
                       "dataRicezione", default="") or "",
        "N. Fattura": _campo(voce, "numeroFattura", "numero", "numFattura",
                             default="") or "",
        "ID SDI": _campo(voce, "idSdi", "idSDI", "identificativoSdi",
                         "idFattura", default="") or "",
        "Tipo Documento": tipo_doc,
        "Cliente/Fornitore": str(controparte).strip(),
        "Partita IVA": _campo(voce, "pivaCliente", "pivaFornitore", "partitaIva",
                              "piva", "pivaCedente", "pivaCessionario",
                              default="") or "",
        "Bollo Virtuale": _campo(voce, "bolloVirtuale", "bollo", default="") or "",
    }

    segno = -1.0 if _e_nota_credito(tipo_doc) else 1.0
    iva: dict[str, list[float]] = {}
    tot_imp = tot_iva = 0.0
    for riga_iva in _righe_riepilogo_iva(dettaglio):
        chiave = _chiave_aliquota(riga_iva)
        if chiave is None:
            continue
        imponibile = segno * _importo(_campo(riga_iva, "imponibile",
                                             "imponibileImporto"))
        imposta = segno * _importo(_campo(riga_iva, "imposta", "impostaImporto"))
        coppia = iva.setdefault(chiave, [0.0, 0.0])
        coppia[0] += imponibile
        coppia[1] += imposta
        tot_imp += imponibile
        tot_iva += imposta

    riga["iva"] = iva
    riga["Tot. Imponibile"] = tot_imp
    riga["Tot. IVA"] = tot_iva
    riga["Totale Fattura"] = tot_imp + tot_iva
    return riga


def _ordina_chiavi_pivot(chiavi) -> list[str]:
    """Aliquote numeriche crescenti prima ("4%", "10%", "22%"), poi nature alfabetiche."""
    def _ordine(chiave: str):
        if chiave.endswith("%"):
            return (0, _importo(chiave[:-1]), "")
        return (1, 0.0, chiave)
    return sorted(chiavi, key=_ordine)


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


# ─────────────────────────────────────────────────────────────────────────────
# Discovery (dev-only): dump dei JSON reali per confermare i nomi campo
# ─────────────────────────────────────────────────────────────────────────────

def dump_json_esempio(auth: AuthResult, tipo: str, dal: str, al: str,
                      dest_dir: str = "_materiale", log=print) -> None:
    """
    Salva in `dest_dir` la lista fatture del PRIMO blocco del periodo e il dettaglio
    della PRIMA fattura (`dump_lista_{tipo}.json` / `dump_dettaglio_{tipo}.json`).
    Serve solo in sviluppo, per confermare i nomi dei campi JSON (la lista espone di
    certo solo tipoInvio/idFattura; il resto va verificato sul vivo). ⚠️ I dump possono
    contenere dati personali reali: tenerli in `_materiale/` (fuori da Git).
    """
    b_dal, b_al = spezza_periodo(dal, al, "%d%m%Y")[0]
    voci = _lista_fatture(auth, tipo, b_dal, b_al)
    os.makedirs(dest_dir, exist_ok=True)
    percorso = os.path.join(dest_dir, f"dump_lista_{tipo}.json")
    with open(percorso, "w", encoding="utf-8") as fh:
        json.dump(voci, fh, indent=2, ensure_ascii=False)
    log(f"Lista ({len(voci)} voci) salvata in {percorso}")
    if not voci:
        log("Nessuna fattura nel blocco: dettaglio non scaricabile.")
        return
    fattura_file = f"{voci[0].get('tipoInvio', '')}{voci[0].get('idFattura', '')}"
    dettaglio = _dettaglio_fattura(auth, fattura_file)
    percorso = os.path.join(dest_dir, f"dump_dettaglio_{tipo}.json")
    with open(percorso, "w", encoding="utf-8") as fh:
        json.dump(dettaglio, fh, indent=2, ensure_ascii=False)
    log(f"Dettaglio fattura {fattura_file} salvato in {percorso}")


if __name__ == "__main__":
    # Uso dev:  python fec_utility.py --tipo emesse --dal 01012026 --al 31032026 \
    #               --cf-cliente 12345678901 [--profilo 1] [--backend requests]
    # Credenziali: cf/pin/cfstudio da fec_store (come la GUI); password da
    # variabile d'ambiente FEC_PASSWORD o richiesta a video (mai salvata, C.3).
    import argparse
    import getpass

    import ade_auth
    import fec_store

    ap = argparse.ArgumentParser(description="Dump JSON di discovery per l'export Excel (dev)")
    ap.add_argument("--tipo", default="emesse", choices=sorted(TIPI_ELENCO))
    ap.add_argument("--dal", required=True, help="data inizio GGMMAAAA")
    ap.add_argument("--al", required=True, help="data fine GGMMAAAA")
    ap.add_argument("--cf-cliente", required=True)
    ap.add_argument("--profilo", type=int, default=1)
    ap.add_argument("--backend", default="requests", choices=["requests", "browser"])
    args = ap.parse_args()

    cred = fec_store.load_credentials()
    if not cred:
        raise SystemExit("Nessuna credenziale salvata (fec_credentials.dat): "
                         "salva le credenziali dalla GUI prima di usare il dump.")
    password = os.environ.get("FEC_PASSWORD") or getpass.getpass("Password Entratel: ")
    creds = ade_auth.Creds(nomeutente=cred.get("cf", ""), pin=cred.get("pin", ""),
                           password=password, cfstudio=cred.get("cfstudio", ""),
                           cf_cliente=args.cf_cliente, profilo=args.profilo)
    auth = ade_auth.autentica(creds, backend=args.backend)
    dump_json_esempio(auth, args.tipo, args.dal, args.al)
