#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""
Genera la fixture del golden test dal campione reale in «_materiale/» (che è
fuori da Git). Da rieseguire solo se il campione cambia.

    python3 tests/fixtures/genera_fixture_ricevute.py

Il campione contiene dati personali reali: qui vengono ANONIMIZZATI cella per
cella (CF, P.IVA, denominazioni, numeri documento, identificativi SDI) prima di
scrivere i file versionati. Restano intatti struttura, ordine colonne, quoting,
date e importi, cioè tutto ciò che il golden test deve verificare.

Produce due file coerenti fra loro:
  - elenco_ricevute_25.json        voci di elenco (input di fec_csv_ade)
  - elenco_ricevute_25_atteso.csv  CSV atteso (output di fec_csv_ade)

Il CSV atteso è riscritto da questo script con un serializzatore suo, di tre righe,
indipendente da fec_csv_ade: un errore introdotto nel modulo non può spostare da solo
il bersaglio del test.

⚠️ LIMITE DA CONOSCERE: la fixture JSON è ricavata INVERTENDO il CSV (`_voce`), non da
un dump JSON autentico. Struttura, ordine colonne, quoting, CRLF, assenza di BOM e
zero-padding restano verificati sul serio, perché vengono dal file del portale; ma un
errore SIMMETRICO fra `_voce` qui e la trasformazione in `fec_csv_ade` non verrebbe
intercettato (es. se entrambe invertissero giorno e mese). A coprire quel rischio ci
sono i test unitari, scritti a partire dal sorgente JS e non da questa inversione.
"""

import csv
import json
import os
import re

# I CSV prodotti da FeC-Plus stesso (`<prefisso>_GGMMAAAA-GGMMAAAA_<tipo>.csv`, vedi
# `fec_csv_ade.nome_file`) vanno ESCLUSI dai candidati: confrontare il nostro output
# con sé stesso renderebbe il golden test del tutto circolare. Servono gli export
# scaricati dal portale.
_NOSTRO_OUTPUT = re.compile(r"_\d{8}-\d{8}_[a-z_]+\.csv$", re.IGNORECASE)


def _candidato(nome: str) -> bool:
    return nome.lower().endswith(".csv") and not _NOSTRO_OUTPUT.search(nome)

QUI = os.path.dirname(os.path.abspath(__file__))
RADICE = os.path.dirname(os.path.dirname(QUI))
MATERIALE = os.path.join(RADICE, "_materiale")


def trova_campione() -> str:
    """
    Individua il campione da anonimizzare fra i CSV in `_materiale/` (cartella fuori
    da Git), riconoscendolo dalla STRUTTURA e non dal nome: il nome contiene dati di
    una persona reale e non va scritto in un file versionato.

    Si può forzare con la variabile d'ambiente `FEC_CAMPIONE_CSV`.
    """
    forzato = os.environ.get("FEC_CAMPIONE_CSV", "").strip()
    if forzato:
        return forzato
    for nome in sorted(os.listdir(MATERIALE)):
        if not _candidato(nome):
            continue
        percorso = os.path.join(MATERIALE, nome)
        try:
            with open(percorso, encoding="utf-8", newline="") as fh:
                intestazione = next(csv.reader(fh, delimiter=";"))
        except (OSError, StopIteration, UnicodeDecodeError):
            continue
        if len(intestazione) == 17 and intestazione[15] == "Data ricezione":
            return percorso
    raise SystemExit("Nessun campione «fatture ricevute» trovato in _materiale/: "
                     "indicane uno con FEC_CAMPIONE_CSV=/percorso/al/file.csv")

# Colonna -> prefisso del valore sintetico. Le colonne non elencate restano
# invariate: tipo fattura/documento, date, importi, stato consegna, bollo.
ANONIMI = {2: "DOC", 5: "CF", 6: "PI", 7: "FORNITORE",
           8: "CFC", 9: "PIC", 10: "CLIENTE", 13: "SDI"}


def _iso(data_it: str) -> str:
    giorno, mese, anno = data_it.split("/")
    return f"{anno}-{mese}-{giorno}"


def _spoglia(valore: str) -> str:
    """Toglie l'apice che l'AdE mette davanti agli identificativi."""
    return valore[1:-1] if valore.startswith("'") and valore.endswith("'") else valore


def _anonimizza(righe: list[list[str]]) -> list[list[str]]:
    """Sostituisce i valori identificativi con valori sintetici, mantenendo la
    corrispondenza: lo stesso fornitore resta lo stesso in tutte le sue righe."""
    mappe: dict[int, dict[str, str]] = {c: {} for c in ANONIMI}
    fuori = []
    for riga in righe:
        nuova = list(riga)
        for col, prefisso in ANONIMI.items():
            grezzo = _spoglia(riga[col])
            if grezzo == "Non presente" or grezzo == "":
                continue          # va conservato com'è: è un caso da testare
            mappa = mappe[col]
            if grezzo not in mappa:
                mappa[grezzo] = f"{prefisso}{len(mappa) + 1:04d}"
            sostituto = mappa[grezzo]
            nuova[col] = f"'{sostituto}'" if riga[col].startswith("'") else sostituto
        fuori.append(nuova)
    return fuori


def _serializza(righe: list[list[str]]) -> str:
    """Serializzatore indipendente da fec_csv_ade: tutti i campi quotati, «"»
    raddoppiate, separatore «;», CRLF. Nel campione ogni campo è quotato,
    intestazione compresa, quindi questa è una riproduzione fedele."""
    return "".join(
        ";".join('"' + c.replace('"', '""') + '"' for c in riga) + "\r\n"
        for riga in righe)


def _voce(r: list[str]) -> dict:
    """Voce di elenco JSON ricostruita da una riga CSV (già anonimizzata)."""
    consegna, data = r[14], r[15]
    file_download = {"idInvio": r[13]}
    if consegna.endswith("/Presa visione"):
        file_download["statoFile"] = consegna[:-len("/Presa visione")]
        file_download["dataPresaVisione"] = data
    else:
        file_download["statoFile"] = consegna
    voce = {
        "decodificaTipoInvio": _spoglia(r[0]),
        "tipoDocumento": r[1],
        "numeroFattura": _spoglia(r[2]),
        "dataFattura": _iso(r[3]),
        "dataAccoglienzaFile": _iso(r[4]),
        "denominazioneEmittente": r[7],
        "denominazioneCliente": r[10],
        "imponibile": "+" + r[11],
        "imposta": "+" + r[12],
        "fileDownload": file_download,
    }
    if not consegna.endswith("/Presa visione"):
        voce["dataConsegna"] = data
    # «Non presente» = campo assente nel JSON, non stringa vuota.
    for indice, chiave in ((5, "cfEmittente"), (6, "pivaEmittente"),
                           (8, "cfCliente"), (9, "pivaCliente")):
        valore = _spoglia(r[indice])
        if valore != "Non presente":
            voce[chiave] = valore
    if r[16] == "Si":
        voce["bolloVirtuale"] = "Y"
    return voce


def trova_campione_md() -> str | None:
    """Campione «messe a disposizione» in `_materiale/`: 16 colonne e nessuna colonna
    data finale. `None` se non c'è. Fra più candidati prende quello con più righe."""
    migliore, righe_migliore = None, 0
    try:
        nomi = sorted(os.listdir(MATERIALE))
    except OSError:
        return None
    for nome in nomi:
        if not _candidato(nome):
            continue
        percorso = os.path.join(MATERIALE, nome)
        try:
            with open(percorso, encoding="utf-8", newline="") as fh:
                righe = list(csv.reader(fh, delimiter=";"))
        except (OSError, UnicodeDecodeError):
            continue
        if (righe and len(righe[0]) == 16 and righe[0][15] == "Bollo virtuale"
                and len(righe) - 1 > righe_migliore):
            migliore, righe_migliore = percorso, len(righe) - 1
    return migliore


def _voce_md(r: list[str]) -> dict:
    """Voce di elenco per le messe a disposizione (nessuna colonna data finale)."""
    voce = {
        "decodificaTipoInvio": _spoglia(r[0]),
        "tipoDocumento": r[1],
        "numeroFattura": _spoglia(r[2]),
        "dataFattura": _iso(r[3]),
        "dataAccoglienzaFile": _iso(r[4]),
        "denominazioneEmittente": r[7],
        "denominazioneCliente": r[10],
        "imponibile": "+" + r[11],
        "imposta": "+" + r[12],
        "fileDownload": {"idInvio": r[13], "statoFile": r[14]},
    }
    for indice, chiave in ((5, "cfEmittente"), (6, "pivaEmittente"),
                           (8, "cfCliente"), (9, "pivaCliente")):
        valore = _spoglia(r[indice])
        if valore != "Non presente":
            voce[chiave] = valore
    if r[15] == "Si":
        voce["bolloVirtuale"] = "Y"
    return voce


def genera_md() -> None:
    """Secondo golden, su un layout che i test coprivano solo con dati sintetici."""
    campione = trova_campione_md()
    if not campione:
        print("Nessun campione «messe a disposizione» in _materiale/: fixture saltata.")
        return
    with open(campione, encoding="utf-8", newline="") as fh:
        righe = list(csv.reader(fh, delimiter=";"))
    intestazione, dati = righe[0], _anonimizza(righe[1:])
    voci = [_voce_md(r) for r in dati]
    with open(os.path.join(QUI, "elenco_md.json"), "w", encoding="utf-8") as fh:
        json.dump(voci, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    with open(os.path.join(QUI, "elenco_md_atteso.csv"), "w",
              encoding="utf-8", newline="") as fh:
        fh.write(_serializza([intestazione] + dati))
    print(f"Fixture «messe a disposizione» generata e anonimizzata: {len(voci)} voci.")


def main() -> None:
    campione = trova_campione()
    with open(campione, encoding="utf-8", newline="") as fh:
        righe = list(csv.reader(fh, delimiter=";"))
    intestazione, dati = righe[0], righe[1:]
    assert intestazione[15] == "Data ricezione", intestazione[15]

    dati = _anonimizza(dati)
    voci = [_voce(r) for r in dati]

    with open(os.path.join(QUI, "elenco_ricevute_25.json"), "w", encoding="utf-8") as fh:
        json.dump(voci, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    with open(os.path.join(QUI, "elenco_ricevute_25_atteso.csv"), "w",
              encoding="utf-8", newline="") as fh:
        fh.write(_serializza([intestazione] + dati))
    print(f"Fixture generata e anonimizzata: {len(voci)} voci.")
    genera_md()


if __name__ == "__main__":
    main()
