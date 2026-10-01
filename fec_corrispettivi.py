#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""
fec_corrispettivi.py - Export Excel dei corrispettivi telematici.

Libreria pura sopra le API di consultazione `rs/corrispettivi/...`: riceve un
`AuthResult` già autenticato e scrive un file .xlsx per dispositivo, o uno unico
per i canali senza dispositivo. La P.IVA è obbligatoria: fa parte degli URL.

Tipi gestiti in `TIPI`. Solo i registratori telematici sono confermati su JSON
reale: per gli altri i nomi dei campi vengono dal frontend del portale, quindi
si leggono sempre con alias (`_campo`) e gli importi passano da `_importo`, che
accetta numeri e stringhe in entrambi i formati.
"""

from __future__ import annotations

__version__ = "0.04 dev"

import json
import os
import re
import requests
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

from ade_auth import IVASERVIZI, unix_time
from fec_download import (_cartella, Controllo, DownloadError, HTTP_TIMEOUT,  # noqa: F401
                          controlla_avviso_elenco)
from fec_queue import spezza_periodo
from fec_utility import (NessunDato, _campo, _data_it, _importo, _ordina_chiavi_pivot,
                         _righe_riepilogo_iva, _scrivi_xlsx)

BASE = f"{IVASERVIZI}/cons/cons-services/rs/corrispettivi"


@dataclass(frozen=True)
class TipoCorr:
    codice: str
    etichetta: str
    campo_sintesi: str       # conteggio degli invii nella sintesi
    percorso_elenco: str     # dopo BASE, con {dal} {al} {piva}
    chiave_elenco: str       # array delle voci nella risposta di elenco
    campo_totale: str        # totale reale, per riconoscere un elenco troncato
    campo_gruppo: str        # campo della voce che separa i file; "" = file unico
    suffisso_file: str


_ELENCO_SINTESI = "/sintesi/elenco/dal/{dal}/al/{al}/piva/{piva}/tipoCorrispettivo/"

TIPI: dict[str, TipoCorr] = {
    "RT": TipoCorr("RT", "Registratori telematici", "registratoriInvii",
                   _ELENCO_SINTESI + "RT", "corrispettivi", "totaleCorrispettivi",
                   "matricolaDispositivo", "corrispettivi"),
    "MC": TipoCorr("MC", "Multicassa", "multicassaInvii",
                   _ELENCO_SINTESI + "MC", "corrispettivi", "totaleCorrispettivi",
                   "matricolaDispositivo", "multicassa"),
    "DA": TipoCorr("DA", "Distributori automatici", "distributoriInvii",
                   _ELENCO_SINTESI + "DA", "corrispettivi", "totaleCorrispettivi",
                   "matricolaDispositivo", "distributori"),
    "CA": TipoCorr("CA", "Distributori di carburante", "carburantiInvii",
                   _ELENCO_SINTESI + "CA", "corrispettivi", "totaleCorrispettivi",
                   "codiceDitta", "carburanti"),
    "DC": TipoCorr("DC", "Documenti commerciali online", "documentiCommerciali",
                   "/dc/ricerca/dal/{dal}/al/{al}/piva/{piva}", "elenco", "totaleElementi",
                   "", "documenti_commerciali"),
    "RC": TipoCorr("RC", "Registratori di cassa", "registratoriCassa",
                   "/rc/ricerca/dal/{dal}/al/{al}/piva/{piva}", "elenco", "totaleElementi",
                   "", "registratori_cassa"),
    "COL": TipoCorr("COL", "Colonnine di ricarica", "torretteEnergia",
                    "/col/ricerca/dal/{dal}/al/{al}/piva/{piva}", "elenco", "totaleElementi",
                    "matrServerEnergia", "colonnine"),
}

# Array delle righe contabili nel dettaglio, per i tipi con ripartizione IVA.
_CHIAVE_RIGHE = {"RT": "datiContabiliRT_MC", "MC": "datiContabiliRT_MC",
                 "DC": "listaAliquota", "RC": "lista", "COL": "datiContabili"}

COLONNE_FISSE = ["ID Invio", "Data", "Tipo dispositivo"]
COLONNE_NUM = ["Tot. Imponibile", "Tot. IVA", "Resi", "Annulli", "Totale Corrispettivi"]
COLONNE_FISSE_CA = ["ID Invio", "Data", "Codice ditta", "Periodo dal", "Periodo al"]
COLONNE_NUM_CA = ["Imp. benzina/gasolio", "IVA benzina/gasolio", "Imp. gas", "IVA gas",
                  "Tot. Imponibile", "Tot. IVA", "Totale"]


def _s(d, *nomi) -> str:
    return str(_campo(d, *nomi, default="") or "").strip()


_FORMATI_DATA = ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
                 "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def data_ora(val) -> datetime | None:
    """Data AdE eterogenea: `GG/MM/AAAA HH:MM` nei corrispettivi, ISO altrove."""
    s = str(val or "").strip().rstrip("Z").split(".")[0]
    for fmt in _FORMATI_DATA:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def ordine(voce: dict) -> datetime:
    """Chiave di ordinamento cronologico di una voce di elenco."""
    return (data_ora(_campo(voce, "timeRilevazione", "dataEmissione", "dataFattura",
                            "dataAccoglienzaFile")) or datetime.min)


def chiave_aliquota(riga: dict) -> str:
    """
    Chiave pivot di una riga contabile: ventilazione, aliquota numerica («10%»),
    codice natura, altrimenti «Esente/N.I.».
    """
    if _s(riga, "ventilazione"):
        return "Ventilazione IVA"
    aliquota = _campo(riga, "aliquota", "aliquotaIVA", "aliquotaIva")
    if aliquota is not None and _importo(aliquota) > 0:
        return f"{_importo(aliquota):g}%".replace(".", ",")
    natura = _s(riga, "natura", "codiceNatura")
    if natura:
        return natura.upper()
    return "Esente/N.I."


def righe_contabili(codice: str, dettaglio: dict | None) -> list[dict]:
    """Righe contabili del dettaglio: per nome se noto, altrimenti ricerca generica."""
    if not isinstance(dettaglio, dict):
        return []
    righe = _campo(dettaglio, _CHIAVE_RIGHE.get(codice, "-"))
    if not isinstance(righe, list):
        righe = _righe_riepilogo_iva(dettaglio)
    return [r for r in righe if isinstance(r, dict)]


def url_dettaglio(codice: str, voce: dict, piva: str) -> str | None:
    """URL del dettaglio di una voce, o None se mancano gli identificativi."""
    if codice in ("RT", "MC", "DA"):
        id_invio = _s(voce, "idInvio")
        percorso = f"/dettaglio/{codice}{id_invio}" if id_invio else None
    elif codice == "CA":
        id_invio = _s(voce, "idInvio")
        percorso = f"/dettagliocarburanti/CA{id_invio}" if id_invio else None
    elif codice == "DC":
        id_voce = _s(voce, "id")
        percorso = f"/dc/dettaglio/{id_voce}" if id_voce else None
    elif codice == "RC":
        # il dettaglio delle comunicazioni RC si chiede per idUnivoco, non per idInvio
        id_univoco = _s(voce, "idUnivoco")
        percorso = f"/rc/dettaglio/{id_univoco}" if id_univoco else None
    elif codice == "COL":
        id_invio, riga = _s(voce, "idInvio"), _s(voce, "idRigaPresa")
        p = _s(voce, "piva") or piva
        percorso = (f"/col/dettaglio/piva/{p}/idInvio/{id_invio}/idRigaPresa/{riga}"
                    if id_invio and riga else None)
    else:
        percorso = None
    return f"{BASE}{percorso}?v={unix_time()}" if percorso else None


def _data_voce(voce: dict) -> str:
    return _data_it(_campo(voce, "timeRilevazione", "dataEmissione", "dataFattura",
                           "dataAccoglienzaFile"))


def estrai_riga_pivot(codice: str, voce: dict, dettaglio: dict | None) -> dict:
    """
    Riga Excel per i tipi con ripartizione IVA (RT, MC, DC, RC, COL): pivot per
    aliquota/natura, resi e annulli a memo (fuori dal Totale Corrispettivi). Senza
    dettaglio usa i totali dell'elenco.
    """
    tipo = TIPI[codice]
    righe = righe_contabili(codice, dettaglio)
    iva: dict[str, list[float]] = {}
    tot_imp = tot_iva = resi_righe = annulli_righe = 0.0
    for r in righe:
        imponibile = _importo(_campo(r, "imponibile", "imponibileImporto"))
        imposta = _importo(_campo(r, "imposta", "impostaImporto"))
        coppia = iva.setdefault(chiave_aliquota(r), [0.0, 0.0])
        coppia[0] += imponibile
        coppia[1] += imposta
        tot_imp += imponibile
        tot_iva += imposta
        resi_righe += _importo(_campo(r, "resi"))
        annulli_righe += _importo(_campo(r, "annulli", "annullato"))
    if not righe:
        tot_imp = _importo(_campo(voce, "ammontareTotale", "importoParzialeTotale",
                                  "imponibileGiornata", "totaleImponibile", "imponibile"))
        tot_iva = _importo(_campo(voce, "impostaTotale", "totaleImposta", "imposta"))
    fonte = dettaglio if righe else voce
    resi = _importo(_campo(fonte, "resi", "importoReso")) or resi_righe
    annulli = (_importo(_campo(fonte, "annullato", "annulli", "importoAnnullato"))
               or annulli_righe)
    return {
        "ID Invio": _s(voce, "idInvio", "id", "idUnivoco"),
        "Data": _data_voce(voce),
        "Tipo dispositivo": _s(voce, "tipoDispositivo") or tipo.etichetta,
        "_gruppo": _s(voce, tipo.campo_gruppo) if tipo.campo_gruppo else "",
        "_ordinamento": ordine(voce),
        "iva": iva,
        "Tot. Imponibile": tot_imp,
        "Tot. IVA": tot_iva,
        "Resi": resi,
        "Annulli": annulli,
        "Totale Corrispettivi": tot_imp + tot_iva,
    }


def e_annullato_ca(voce: dict) -> bool:
    """Invio carburanti annullato (`statoIdInvio` = 1): non va nei totali."""
    return _s(voce, "statoIdInvio") == "1"


def estrai_riga_ca(voce: dict, dettaglio: dict | None) -> dict:
    """Riga Excel di un invio carburanti: benzina/gasolio e gas sommati sui giorni."""
    righe = _campo(dettaglio, "datiContabili_AC") if isinstance(dettaglio, dict) else None
    righe = [r for r in righe if isinstance(r, dict)] if isinstance(righe, list) else []
    imp_b = sum(_importo(_campo(r, "imponibile")) for r in righe)
    iva_b = sum(_importo(_campo(r, "imposta")) for r in righe)
    imp_g = sum(_importo(_campo(r, "imponibileGas")) for r in righe)
    iva_g = sum(_importo(_campo(r, "impostaGas")) for r in righe)
    if not righe:
        imp_b = _importo(_campo(voce, "importo"))
        iva_b = _importo(_campo(voce, "imposta"))
    return {
        "ID Invio": _s(voce, "idInvio"),
        "Data": _data_voce(voce),
        "Codice ditta": _s(voce, "codiceDitta"),
        "Periodo dal": _data_it(_campo(voce, "riferimentoDal")),
        "Periodo al": _data_it(_campo(voce, "riferimentoAl")),
        "_gruppo": _s(voce, "codiceDitta"),
        "_ordinamento": ordine(voce),
        "iva": {},
        "Imp. benzina/gasolio": imp_b,
        "IVA benzina/gasolio": iva_b,
        "Imp. gas": imp_g,
        "IVA gas": iva_g,
        "Tot. Imponibile": imp_b + imp_g,
        "Tot. IVA": iva_b + iva_g,
        "Totale": imp_b + imp_g + iva_b + iva_g,
    }


def nome_file(piva: str, dal: str, al: str, codice: str, gruppo: str) -> str:
    """Nome del file xlsx; per i tipi con dispositivo include l'identificativo."""
    tipo = TIPI[codice]
    nome = f"{piva}_{dal}-{al}_{tipo.suffisso_file}"
    if tipo.campo_gruppo:
        nome += "_" + (re.sub(r"[^A-Za-z0-9_-]+", "_", gruppo) or "senza_matricola")
    return nome + ".xlsx"


# ─────────────────────────────────────────────────────────────────────────────
# Distributori automatici: ogni invio riporta il totale venduto dall'attivazione
# della macchina (modalità CUMULATO), non il venduto dell'intervallo. Sommare gli
# invii come per i registratori moltiplicherebbe il fatturato.
# ─────────────────────────────────────────────────────────────────────────────

COLONNE_FISSE_DA = ["ID Invio", "Data", "Matricola", "Modalità"]
COLONNE_NUM_DA_DIFF = ["Lettura precedente", "Totale venduto (contatore)",
                       "Venduto dell'intervallo"]
NON_SOMMARE_DA = ("Lettura precedente", "Totale venduto (contatore)")
CAMPI_DA_GREZZI = [
    ("Venduto", "venduto"), ("Venduto contante", "vendutoContante"),
    ("Venduto non contante", "vendutoNoContante"),
    ("Totale incassato", "incassatoNoContante"),
    ("Incassato ricarica", "incassatoRicarica"), ("Incassato vendita", "incassatoVendita"),
    ("Totale reso tubi resto", "totaleResoTubiResto"),
    ("Totale versato tubi resto", "totaleVersoTubiResto"),
    ("Reso manuale tubi resto", "resoManualTubiResto"),
    ("Caricato manuale tubi resto", "caricatoManualTubiResto"),
]


def _dati_da(dettaglio) -> dict:
    dati = _campo(dettaglio, "datiContabiliDA") if isinstance(dettaglio, dict) else None
    return dati if isinstance(dati, dict) else {}


def _matricola(voce: dict) -> str:
    return _s(voce, "matricolaDispositivo") or "senza_matricola"


def _modalita_da(voce: dict, dettaglio: dict | None = None) -> str:
    """Modalità di rilevazione: voce > datiContabiliDA > dettaglio root > default CUMULATO."""
    return (_s(voce, "modalitaRilevazione") or
            _s(_campo(dettaglio, "datiContabiliDA"), "modalitaRilevazione") or
            _s(dettaglio or {}, "modalitaRilevazione") or "CUMULATO")


def _nota_divergenza(voce: dict, dettaglio: dict | None) -> str:
    """Avviso divergenza tra venduto del dettaglio e importo dell'elenco."""
    importo = _importo(_campo(voce, "importo"))
    venduto_detail = _campo(_dati_da(dettaglio), "venduto")
    if venduto_detail not in (None, ""):
        venduto_detail_val = _importo(venduto_detail)
        if abs(venduto_detail_val - importo) > 0.005:
            return (f"Il venduto del dettaglio ({venduto_detail_val:.2f}) differisce dal totale "
                    f"dell'elenco ({importo:.2f}): verificare.")
    return ""


def _unisci_note(nota1: str, nota2: str) -> str:
    """Unisce due note con un singolo spazio, scartando stringhe vuote."""
    parti = [n for n in [nota1, nota2] if n]
    return " ".join(parti)


def venduto_da(voce: dict, dettaglio: dict | None) -> float:
    """Contatore del venduto: `importo` dell'elenco; fallback al dettaglio `venduto` se assente."""
    importo = _campo(voce, "importo")
    if importo not in (None, ""):
        return _importo(importo)
    venduto = _campo(_dati_da(dettaglio), "venduto")
    return _importo(venduto)


def letture_precedenti(voci: list[dict], inizio: datetime) -> dict[str, float]:
    """Per ogni matricola, il contatore dell'ultimo invio CUMULATO anteriore a `inizio`."""
    ultime: dict[str, tuple[datetime, float]] = {}
    for voce in voci:
        quando = ordine(voce)
        if quando >= inizio:
            continue
        if _modalita_da(voce).upper() != "CUMULATO":
            continue
        m = _matricola(voce)
        if m not in ultime or quando > ultime[m][0]:
            ultime[m] = (quando, _importo(_campo(voce, "importo")))
    return {m: valore for m, (_, valore) in ultime.items()}


def _base_da(voce: dict, dettaglio: dict | None = None) -> dict:
    return {"ID Invio": _s(voce, "idInvio"), "Data": _data_voce(voce),
            "Matricola": _matricola(voce), "Modalità": _modalita_da(voce, dettaglio),
            "_gruppo": _matricola(voce), "_ordinamento": ordine(voce), "iva": {}}


def righe_da_differenza(invii: list[tuple[dict, dict | None]],
                        precedenti: dict[str, float]) -> list[dict]:
    """Una riga per invio con lettura precedente, contatore e venduto per differenza."""
    per_matricola: dict[str, list[tuple[dict, dict | None]]] = {}
    for voce, det in invii:
        per_matricola.setdefault(_matricola(voce), []).append((voce, det))
    righe: list[dict] = []
    for m, lista in per_matricola.items():
        lista.sort(key=lambda vd: ordine(vd[0]))
        prec = precedenti.get(m)
        for voce, det in lista:
            contatore = venduto_da(voce, det)
            modalita = _modalita_da(voce, det)
            riga = _base_da(voce, det)
            riga["Totale venduto (contatore)"] = contatore
            riga["Note"] = ""
            if modalita.upper() != "CUMULATO":
                riga["Lettura precedente"] = None
                riga["Venduto dell'intervallo"] = contatore
                riga["Note"] = (f"Modalità di rilevazione «{modalita}»: "
                                "importo riportato così com'è.")
            elif prec is None:
                riga["Lettura precedente"] = None
                riga["Venduto dell'intervallo"] = None
                riga["Note"] = ("Lettura precedente non trovata: venduto dell'intervallo "
                                "non calcolabile.")
            else:
                riga["Lettura precedente"] = prec
                riga["Venduto dell'intervallo"] = round(contatore - prec, 2)
                if contatore < prec:
                    riga["Note"] = ("Contatore inferiore alla lettura precedente "
                                    "(azzeramento o sostituzione della scheda?): verificare.")
            riga["Note"] = _unisci_note(riga["Note"], _nota_divergenza(voce, det))
            if modalita.upper() == "CUMULATO":
                prec = contatore
            righe.append(riga)
    return righe


def righe_da_grezzi(invii: list[tuple[dict, dict | None]]) -> list[dict]:
    """Una riga per invio con i campi del dettaglio, senza differenze."""
    righe: list[dict] = []
    for voce, det in invii:
        dati = _dati_da(det)
        riga = _base_da(voce, det)
        for intestazione, campo in CAMPI_DA_GREZZI:
            riga[intestazione] = _importo(_campo(dati, campo))
        if not dati:
            riga["Venduto"] = _importo(_campo(voce, "importo"))
        righe.append(riga)
    return righe


# ─────────────────────────────────────────────────────────────────────────────
# Chiamate HTTP
# ─────────────────────────────────────────────────────────────────────────────

def _get_json(auth, url: str, cosa: str) -> dict:
    try:
        r = auth.session.get(url, headers=auth.headers, verify=False, timeout=HTTP_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        raise DownloadError(f"Nessuna risposta dall'AdE per {cosa}: {exc}.")
    if r.status_code != 200:
        raise DownloadError(f"Richiesta non riuscita per {cosa} (HTTP {r.status_code}). "
                            "La sessione potrebbe essere scaduta o la P.IVA non "
                            "appartenere all'utenza.")
    try:
        dati = r.json()
    except ValueError:
        raise DownloadError(f"Risposta non in formato JSON per {cosa}: probabile "
                            "sessione scaduta.")
    return dati if isinstance(dati, dict) else {}


def sintesi(auth, dal: str, al: str, piva: str) -> dict:
    """Conteggio degli invii del periodo per canale."""
    return _get_json(auth, f"{BASE}/sintesi/dal/{dal}/al/{al}/piva/{piva}?v={unix_time()}",
                     "la sintesi corrispettivi")


def elenco_blocco(auth, codice: str, dal: str, al: str, piva: str,
                  log=print) -> tuple[list[dict], int | None]:
    """Voci di un canale per un blocco di periodo e totale dichiarato dal portale."""
    tipo = TIPI[codice]
    url = f"{BASE}{tipo.percorso_elenco.format(dal=dal, al=al, piva=piva)}?v={unix_time()}"
    dati = _get_json(auth, url, f"l'elenco «{tipo.etichetta}»")
    voci = [v for v in (dati.get(tipo.chiave_elenco) or []) if isinstance(v, dict)]
    controlla_avviso_elenco(dati, voci, log, f"l'elenco «{tipo.etichetta}»")
    totale = dati.get(tipo.campo_totale)
    return voci, (int(_importo(totale)) if totale not in (None, "") else None)


def dettaglio(auth, codice: str, voce: dict, piva: str) -> dict | None:
    """Dettaglio JSON di una voce; None su qualunque errore (riga coi soli totali)."""
    url = url_dettaglio(codice, voce, piva)
    if url is None:
        return None
    try:
        return _get_json(auth, url, "il dettaglio")
    except DownloadError:
        return None


# Un blocco troncato si richiede di nuovo a pezzi più piccoli: prima mese per mese,
# poi settimana per settimana.
_LIVELLI = ({"max_mesi": 1}, {"max_giorni": 7})


def elenco_completo(scarica, dal: str, al: str, etichetta: str, log=print,
                    avvisi: list | None = None) -> list[dict]:
    """
    Voci del periodo [dal, al] (GGMMAAAA) per un canale. `scarica(dal, al)`
    restituisce (voci, totale). Se il portale tronca l'elenco, il periodo si
    frazioni finché le righe tornano tutte; se non basta, `avvisi` riceve una riga.
    """
    voci, totale = scarica(dal, al)
    if totale is None or len(voci) >= totale:
        return voci
    log(f"   ⚠️  Elenco «{etichetta}» {dal}-{al} troncato dall'AdE ({len(voci)} su "
        f"{totale}): lo richiedo a periodi più brevi.")
    return _frazionato(scarica, dal, al, etichetta, log,
                       avvisi if avvisi is not None else [], 0)


def _frazionato(scarica, dal, al, etichetta, log, avvisi, livello) -> list[dict]:
    risultato: list[dict] = []
    for d, a in spezza_periodo(dal, al, "%d%m%Y", **_LIVELLI[livello]):
        voci, totale = scarica(d, a)
        if totale is not None and len(voci) < totale:
            if livello + 1 < len(_LIVELLI):
                risultato.extend(_frazionato(scarica, d, a, etichetta, log, avvisi,
                                             livello + 1))
                continue
            avvisi.append(f"{etichetta} {d}-{a}: elenco troncato dall'AdE "
                          f"({len(voci)} su {totale}).")
            log(f"   ⚠️  {avvisi[-1]}")
        risultato.extend(voci)
    return risultato


# ─────────────────────────────────────────────────────────────────────────────
# Export Excel
# ─────────────────────────────────────────────────────────────────────────────

MODALITA_DA = ("differenza", "grezzi")


@dataclass
class EsitoCorrispettivi:
    percorsi: list[str] = field(default_factory=list)
    avvisi: list[str] = field(default_factory=list)


def _dettagli(auth, codice: str, voci: list[dict], piva: str, control, log
              ) -> list[tuple[dict, dict | None]]:
    coppie: list[tuple[dict, dict | None]] = []
    for i, voce in enumerate(voci, start=1):
        if control:
            control.check()
        det = None
        if _campo(voce, "dettaglio", default=True):
            det = dettaglio(auth, codice, voce, piva)
            if det is None:
                log(f"   ⚠️  Dettaglio {codice} {_s(voce, 'idInvio', 'id', 'idUnivoco')} "
                    "non ottenuto: riga coi soli totali di elenco.")
        coppie.append((voce, det))
        if i % 10 == 0 or i == len(voci):
            log(f"  Dettaglio {TIPI[codice].etichetta}: {i}/{len(voci)}")
    return coppie


def _letture_precedenti_da(auth, piva: str, dal: str, log) -> dict[str, float]:
    """Contatori dei distributori nei 3 mesi prima del periodo (prima lettura utile)."""
    inizio = datetime.strptime(dal, "%d%m%Y")
    p_dal = (inizio - relativedelta(months=3)).strftime("%d%m%Y")
    p_al = (inizio - timedelta(days=1)).strftime("%d%m%Y")
    try:
        voci = elenco_completo(lambda d, a: elenco_blocco(auth, "DA", d, a, piva, log),
                               p_dal, p_al, "Distributori automatici (letture precedenti)",
                               log=log)
    except DownloadError as exc:
        log(f"   ⚠️  Letture precedenti dei distributori non disponibili ({exc}).")
        return {}
    return letture_precedenti(voci, inizio)


def _scrivi_tipo(auth, codice: str, voci: list[dict], piva: str, dal: str, al: str,
                 cartella: str, control, log, modalita_da: str) -> list[str]:
    tipo = TIPI[codice]
    if codice == "CA":
        annullati = [v for v in voci if e_annullato_ca(v)]
        if annullati:
            log(f"   {len(annullati)} invii carburanti annullati: esclusi.")
        voci = [v for v in voci if not e_annullato_ca(v)]
        if not voci:
            return []
    coppie = _dettagli(auth, codice, voci, piva, control, log)
    escludi: tuple = ()
    testo: list[str] = []
    if codice == "DA" and modalita_da == "differenza":
        righe = righe_da_differenza(coppie, _letture_precedenti_da(auth, piva, dal, log))
        fisse, num, testo, escludi = (COLONNE_FISSE_DA, COLONNE_NUM_DA_DIFF, ["Note"],
                                      NON_SOMMARE_DA)
    elif codice == "DA":
        righe = righe_da_grezzi(coppie)
        fisse, num = COLONNE_FISSE_DA, [nome for nome, _ in CAMPI_DA_GREZZI]
    elif codice == "CA":
        righe = [estrai_riga_ca(v, d) for v, d in coppie]
        fisse, num = COLONNE_FISSE_CA, COLONNE_NUM_CA
    else:
        righe = [estrai_riga_pivot(codice, v, d) for v, d in coppie]
        fisse, num = COLONNE_FISSE, COLONNE_NUM

    gruppi: dict[str, list[dict]] = {}
    for riga in righe:
        gruppi.setdefault(riga["_gruppo"], []).append(riga)
    percorsi: list[str] = []
    for gruppo, righe_g in sorted(gruppi.items()):
        righe_g.sort(key=lambda r: r["_ordinamento"])
        chiavi = _ordina_chiavi_pivot({k for r in righe_g for k in r["iva"]})
        percorso = os.path.join(cartella, nome_file(piva, dal, al, codice, gruppo))
        _scrivi_xlsx(percorso, fisse, chiavi, num, testo, righe_g,
                     titolo=tipo.etichetta[:31], escludi_da_totali=escludi)
        log(f"File «{tipo.etichetta}» ({len(righe_g)} righe"
            + (f", {gruppo}" if gruppo else "") + f"): {percorso}")
        percorsi.append(percorso)
    return percorsi


def elenco_corrispettivi_excel(auth, cf_cliente: str, piva: str, dal: str, al: str, *,
                               dest_dir: str | None = None, sottocartella: bool = True,
                               control: "Controllo | None" = None, log=print,
                               modalita_da: str = "differenza") -> EsitoCorrispettivi:
    """
    Excel «Elenco corrispettivi» per il periodo [dal, al] (GGMMAAAA): un file per
    canale e dispositivo (o uno unico per documenti commerciali online e registratori
    di cassa). Per i distributori automatici `modalita_da` sceglie fra il venduto per
    differenza fra letture e i dati grezzi del dettaglio.
    """
    piva = (piva or "").strip()
    if not piva:
        raise DownloadError("Per i corrispettivi la P.IVA è obbligatoria (fa parte "
                            "dell'indirizzo delle chiamate AdE) e non è stato possibile "
                            "ricavarla dall'utenza di lavoro attiva: indicala a mano.")
    if modalita_da not in MODALITA_DA:
        raise DownloadError(f"Modalità distributori automatici sconosciuta: {modalita_da!r}.")
    esito = EsitoCorrispettivi()
    blocchi = spezza_periodo(dal, al, "%d%m%Y")
    log(f"Elenco corrispettivi per P.IVA {piva}  ({dal} -> {al})"
        + (f"  [{len(blocchi)} blocchi]" if len(blocchi) > 1 else ""))

    voci_per_tipo: dict[str, list[dict]] = {codice: [] for codice in TIPI}
    for b_dal, b_al in blocchi:
        if control:
            control.check()
        sint = sintesi(auth, b_dal, b_al, piva)
        for codice, tipo in TIPI.items():
            n = int(_importo(_campo(sint, tipo.campo_sintesi, default=0)))
            if n <= 0:
                continue
            log(f"  {b_dal} -> {b_al}: {n} invii «{tipo.etichetta}», scarico l'elenco...")
            voci_per_tipo[codice].extend(elenco_completo(
                lambda d, a, c=codice: elenco_blocco(auth, c, d, a, piva, log),
                b_dal, b_al, tipo.etichetta, log=log, avvisi=esito.avvisi))

    totale = sum(len(v) for v in voci_per_tipo.values())
    log(f"Trovati {totale} invii nell'intervallo.")
    if not totale:
        raise NessunDato("Nessun corrispettivo trovato nell'intervallo richiesto: "
                         "nessun file Excel generato.")

    cartella = _cartella(dest_dir, "ElencoCorrispettivi", cf_cliente, sottocartella)
    for codice, voci in voci_per_tipo.items():
        if voci:
            esito.percorsi.extend(_scrivi_tipo(auth, codice, voci, piva, dal, al,
                                               cartella, control, log, modalita_da))
    log(f"\nGenerati {len(esito.percorsi)} file.")
    return esito


# ─────────────────────────────────────────────────────────────────────────────
# Dump dei JSON reali (solo sviluppo): servono a confermare i nomi dei campi dei
# canali non ancora visti su dati veri. Contengono dati reali: restano fuori da Git.
# ─────────────────────────────────────────────────────────────────────────────

def dump_json(auth, piva: str, dal: str, al: str, dest_dir: str, log=print) -> list[str]:
    """Sintesi, primo elenco e primo dettaglio di ogni canale con invii nel periodo."""
    b_dal, b_al = spezza_periodo(dal, al, "%d%m%Y")[0]
    os.makedirs(dest_dir, exist_ok=True)
    percorsi: list[str] = []

    def _salva(nome: str, dati) -> None:
        percorso = os.path.join(dest_dir, nome)
        with open(percorso, "w", encoding="utf-8") as fh:
            json.dump(dati, fh, indent=2, ensure_ascii=False)
        percorsi.append(percorso)
        log(f"Salvato {percorso}")

    sint = sintesi(auth, b_dal, b_al, piva)
    _salva("dump_corr_sintesi.json", sint)
    for codice, tipo in TIPI.items():
        if int(_importo(_campo(sint, tipo.campo_sintesi, default=0))) <= 0:
            continue
        url = (f"{BASE}{tipo.percorso_elenco.format(dal=b_dal, al=b_al, piva=piva)}"
               f"?v={unix_time()}")
        try:
            dati = _get_json(auth, url, f"l'elenco «{tipo.etichetta}»")
        except DownloadError as exc:
            log(f"   ⚠️  {exc}")
            continue
        _salva(f"dump_corr_elenco_{codice}.json", dati)
        voci = [v for v in (dati.get(tipo.chiave_elenco) or []) if isinstance(v, dict)]
        if voci:
            det = dettaglio(auth, codice, voci[0], piva)
            if det is not None:
                _salva(f"dump_corr_dettaglio_{codice}.json", det)
    return percorsi
