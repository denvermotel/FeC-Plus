#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""
fec_directory.py - Dove salvare i file scaricati.

Ogni soggetto ha una sua cartella, `<Denominazione> - <P.IVA>`, ritrovata per
P.IVA anche se la denominazione cambia. Dentro, due organizzazioni:
- «ditta»: una sottocartella per tipo di documento, divisa per anno (archivio);
- «sessione»: una sottocartella per ogni lancio, `AAAA-MM-GG_HHMM`.
Le cartelle personalizzate dalle Impostazioni restano valide per chi importa i
file da una cartella fissa del gestionale.

Modulo puro: niente Tk, niente rete. Legge e crea solo cartelle.
"""

from __future__ import annotations

__version__ = "0.04 dev"

import os
import re
from dataclasses import dataclass, field
from datetime import datetime

# chiave logica -> (sottocartella, classe di personalizzazione nelle Impostazioni)
CARTELLE: dict[str, tuple[str, str]] = {
    "emesse":                  ("Fatture emesse", "emesse"),
    "ricevute":                ("Fatture ricevute", "ricevute"),
    "trans_emesse":            ("Transfrontaliere emesse", "trans_emesse"),
    "trans_ricevute":          ("Transfrontaliere ricevute", "trans_ricevute"),
    "messe_disposizione":      ("Messe a disposizione", "messe_disposizione"),
    "massive":                 ("Richieste massive", "massive"),
    "massive_corrispettivi":   ("Richieste massive", "corrispettivi"),
    "bolli":                   ("Bolli virtuali", "bolli"),
    "elenchi":                 ("Elenchi", "utility"),
    "elenco_corrispettivi":    ("Corrispettivi", "utility"),
    "risultati_massive":       ("Risultati richieste massive", "risultati_massive"),
    "risultati_corrispettivi": ("Risultati richieste massive", "risultati_corrispettivi"),
}

# Gli XML delle richieste inviate non hanno un anno proprio: il periodo è nel nome.
SENZA_ANNO = {"massive", "massive_corrispettivi"}

# tipo di fec_queue.TIPI -> chiave logica
TIPO_CHIAVE: dict[str, str] = {
    "emesse": "emesse", "ricevute": "ricevute", "trans_emesse": "trans_emesse",
    "trans_ricevute": "trans_ricevute", "messe_disposizione": "messe_disposizione",
    "massive_emesse": "massive", "massive_ricevute_emissione": "massive",
    "massive_ricevute_ricezione": "massive", "massive_disposizione": "massive",
    "corrispettivi": "massive_corrispettivi", "bolli": "bolli",
}

SENZA_DATA = "senza data"
_VIETATI = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _pulisci(testo: str) -> str:
    return re.sub(r"\s+", " ", _VIETATI.sub(" ", testo or "")).strip()


def nome_ditta(denominazione: str, identificativo: str) -> str:
    """Nome della cartella del soggetto, valido su Windows."""
    ident = _pulisci(identificativo).rstrip(" .")
    denom = _pulisci(denominazione).rstrip(" .")[:40].rstrip(" .")
    return f"{denom} - {ident}" if denom else ident


def trova_cartella_ditta(base: str, identificativo: str) -> tuple[str | None, int]:
    """Cartella esistente del soggetto (la più recente) e quante ce ne sono."""
    ident = _pulisci(identificativo).rstrip(" .")
    try:
        nomi = os.listdir(base)
    except OSError:
        return None, 0
    trovate = [os.path.join(base, n) for n in nomi
               if (n == ident or n.endswith(f" - {ident}"))
               and os.path.isdir(os.path.join(base, n))]
    if not trovate:
        return None, 0
    return max(trovate, key=os.path.getmtime), len(trovate)


def cartella_ditta(base: str, identificativo: str, denominazione: str = "",
                   log=print) -> str:
    """Cartella del soggetto: quella già esistente per identificativo, altrimenti
    una nuova col nome attuale (non viene creata qui)."""
    esistente, n = trova_cartella_ditta(base, identificativo)
    if esistente is None:
        return os.path.join(base, nome_ditta(denominazione, identificativo))
    if n > 1:
        log(f"Trovate {n} cartelle per {identificativo}: uso la più recente "
            f"({os.path.basename(esistente)}).")
    return esistente


def anno_da_data(val) -> str | None:
    """Anno da una data AdE: AAAA-MM-GG[...], GG/MM/AAAA[...] o GGMMAAAA."""
    s = str(val or "").strip()
    for modello in (r"^(\d{4})-\d{2}-\d{2}", r"^\d{2}/\d{2}/(\d{4})", r"^\d{4}(\d{4})$"):
        trovato = re.match(modello, s)
        if trovato:
            return trovato.group(1)
    return None


def anno_cartella(val) -> str:
    """Sottocartella per anno di un documento: senza data riconoscibile, `senza data`."""
    return anno_da_data(val) or SENZA_DATA


def timestamp_sessione(quando: datetime) -> str:
    """Nome della cartella di un lancio: si ordina da solo, senza i «:» vietati."""
    return quando.strftime("%Y-%m-%d_%H%M")


@dataclass(frozen=True)
class ConfigCartelle:
    base: str
    modalita: str = "ditta"          # "ditta" | "sessione"
    anno: bool = True                # sottocartella per anno, solo modalità ditta
    sessione: str = ""               # timestamp del lancio, solo modalità sessione
    personalizzate: dict = field(default_factory=dict)  # classe -> (path, senza_sotto)
    # Identifica il lancio dentro sessione.txt: due lanci nello stesso minuto
    # finiscono in cartelle diverse (`_2`, `_3`, ...) invece di mescolarsi.
    lancio: str = ""


@dataclass(frozen=True)
class Destinazione:
    cartella: str           # dove scrivere
    per_anno: bool          # solo XML: sottocartella per anno della data documento
    radice: str             # cartella da aprire a fine operazione
    sessione: bool = False  # la radice è la cartella di un lancio (riceve sessione.txt)


NOME_RIEPILOGO = "sessione.txt"


def _cartella_sessione(ditta: str, config: ConfigCartelle) -> str:
    """Cartella del lancio: quella col timestamp, o `_2`, `_3`, ... se un altro
    lancio dello stesso minuto l'ha già presa."""
    if not config.lancio:
        return os.path.join(ditta, config.sessione)
    n = 1
    while True:
        nome = config.sessione if n == 1 else f"{config.sessione}_{n}"
        radice = os.path.join(ditta, nome)
        riepilogo = os.path.join(radice, NOME_RIEPILOGO)
        if not os.path.exists(riepilogo):
            scrivi_sessione(radice, {"Lancio": config.lancio})
            return radice
        with open(riepilogo, encoding="utf-8", errors="replace") as fh:
            if f"Lancio: {config.lancio}\n" in fh.read():
                return radice
        n += 1


def risolvi(config: ConfigCartelle, chiave: str, identificativo: str,
            denominazione: str = "", anno_periodo: str | None = None, *,
            per_documento: bool = False, log=print) -> Destinazione:
    """Destinazione di un tipo di output; crea la cartella."""
    if config.modalita not in ("ditta", "sessione"):
        raise ValueError(f"Organizzazione delle cartelle sconosciuta: {config.modalita!r}.")
    sottocartella, classe = CARTELLE[chiave]
    path_pers, senza_sotto = config.personalizzate.get(classe, ("", False))
    if senza_sotto:
        fissa = path_pers or config.base
        os.makedirs(fissa, exist_ok=True)
        return Destinazione(fissa, False, fissa)
    ditta = cartella_ditta(path_pers or config.base, identificativo, denominazione, log)
    per_anno = False
    if config.modalita == "sessione":
        if not config.sessione:
            raise ValueError("Modalità sessione senza timestamp del lancio.")
        radice = _cartella_sessione(ditta, config)
        cartella = os.path.join(radice, sottocartella)
        os.makedirs(cartella, exist_ok=True)
        return Destinazione(cartella, False, radice, True)
    else:
        radice = ditta
        cartella = os.path.join(ditta, sottocartella)
        if config.anno and chiave not in SENZA_ANNO:
            if per_documento:
                per_anno = True
            elif anno_periodo:
                cartella = os.path.join(cartella, anno_periodo)
    os.makedirs(cartella, exist_ok=True)
    return Destinazione(cartella, per_anno, radice)


def soggetto(res_piva: str, res_denominazione: str, piva: str, cf_cliente: str,
             cf_utente: str, deleghe: list[dict]) -> tuple[str, str]:
    """(identificativo, denominazione) del soggetto per cui si scarica: P.IVA
    dell'utenza, del form o dell'elenco deleghe locale, altrimenti CF;
    denominazione dal login, altrimenti dall'elenco deleghe."""
    p = (res_piva or "").strip() or (piva or "").strip()
    cf = (cf_cliente or "").strip().upper() or (cf_utente or "").strip().upper()
    if not p and cf:
        # senza P.IVA dal login lo stesso soggetto finirebbe in una seconda
        # cartella intestata al CF
        for riga in deleghe or []:
            if str(riga.get("codice_fiscale", "")).strip().upper() == cf:
                p = str(riga.get("partita_iva", "") or "").strip()
                if p:
                    break
    identificativo = p or cf
    denominazione = (res_denominazione or "").strip()
    if not denominazione:
        for riga in deleghe or []:
            if ((cf and str(riga.get("codice_fiscale", "")).strip().upper() == cf)
                    or (p and str(riga.get("partita_iva", "")).strip() == p)):
                denominazione = str(riga.get("denominazione", "") or "").strip()
                if denominazione:
                    break
    return identificativo, denominazione


def descrizione(config: ConfigCartelle, chiave: str) -> str:
    """Testo per la GUI: dove finiranno i file di quel tipo."""
    sottocartella, classe = CARTELLE[chiave]
    path_pers, senza_sotto = config.personalizzate.get(classe, ("", False))
    if senza_sotto:
        return f"{path_pers or config.base}\n→ i file vanno direttamente in questa cartella."
    base = path_pers or config.base
    if config.modalita == "sessione":
        return (f"{base}\n→ <Denominazione - P.IVA>/AAAA-MM-GG_HHMM/{sottocartella}, "
                "una cartella per ogni lancio.")
    dove = f"{base}\n→ <Denominazione - P.IVA>/{sottocartella}"
    if config.anno and chiave not in SENZA_ANNO:
        dove += "/<anno>"
    return dove + "."


def scrivi_sessione(cartella: str, info: dict) -> str:
    """Scrive `sessione.txt` (una riga `Chiave: valore` per voce) e ne ritorna il percorso."""
    os.makedirs(cartella, exist_ok=True)
    percorso = os.path.join(cartella, NOME_RIEPILOGO)
    with open(percorso, "w", encoding="utf-8", newline="\n") as fh:
        for chiave, valore in info.items():
            fh.write(f"{chiave}: {valore}\n")
    return percorso


def radici(destinazioni) -> list[str]:
    """Cartelle da aprire a fine lavoro, senza doppioni e nell'ordine d'uso."""
    viste: list[str] = []
    for d in destinazioni:
        if d is not None and d.radice not in viste:
            viste.append(d.radice)
    return viste


def info_sessione(periodo: str, tipi, modalita_accesso: str, versione: str, lancio: str,
                  esiti=(), esito: str = "completata") -> dict:
    """Contenuto di sessione.txt. I conteggi compaiono solo se `esiti` contiene
    risultati di download (oggetti con `fatture`, `metadati`, `saltati`, ...)."""
    info = {"Lancio": lancio, "Periodo": periodo, "Tipi": ", ".join(tipi),
            "Modalità di accesso": modalita_accesso, "Esito": esito}
    scarichi = [e for e in esiti if hasattr(e, "fatture")]
    if scarichi:
        info["Fatture scaricate"] = sum(e.fatture for e in scarichi)
        info["Metadati scaricati"] = sum(e.metadati for e in scarichi)
        info["Saltate"] = sum(e.saltati for e in scarichi)
        info["Errori"] = sum(e.errori for e in scarichi)
        info["Non ancora disponibili"] = sum(e.in_attesa for e in scarichi)
        senza = sum(getattr(e, "senza_ritenuta", 0) for e in scarichi)
        if senza:
            info["Senza ritenuta d'acconto (non salvate)"] = senza
    info["Versione"] = versione
    return info


def scrivi_sessioni(destinazioni, info: dict) -> list[str]:
    """Scrive sessione.txt nelle sole cartelle di lancio (mai in una cartella fissa
    «senza sottocartella»). Ritorna i percorsi scritti."""
    scritti: list[str] = []
    for d in destinazioni:
        if d is None or not d.sessione:
            continue
        percorso = os.path.join(d.radice, NOME_RIEPILOGO)
        if percorso not in scritti:
            scrivi_sessione(d.radice, info)
            scritti.append(percorso)
    return scritti
