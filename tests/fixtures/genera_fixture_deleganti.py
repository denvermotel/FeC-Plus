#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""
Genera la fixture di test per fec_deleghe_sync dalla cattura HAR reale del portale
Deleghe (fuori da Git). Da rieseguire solo se serve rinnovare il campione.

    python3 tests/fixtures/genera_fixture_deleganti.py

Il campione contiene CF/denominazioni reali: qui vengono ANONIMIZZATI prima di
scrivere il file versionato. Restano intatti forma dei record, valori di
tipoDelega/servizi/date che il test deve poter distinguere.
"""

import base64
import json
import os

_QUI = os.path.dirname(os.path.abspath(__file__))
_HAR = os.path.join(_QUI, "..", "..", "dev", "HAR-Debug",
                    "capture_deleghe_20260915_235225.har")
_OUT = os.path.join(_QUI, "deleganti_campione.json")


def _estrai_lista_da_har(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        har = json.load(fh)
    for entry in har["log"]["entries"]:
        req = entry["request"]
        if req["method"] == "POST" and "delegheUniche/deleganti" in req["url"]:
            content = entry["response"]["content"]
            testo = content.get("text", "")
            if content.get("encoding") == "base64":
                testo = base64.b64decode(testo).decode("utf-8", "replace")
            return json.loads(testo)["lista"]
    raise RuntimeError("Nessuna chiamata delegheUniche/deleganti trovata nell'HAR.")


def _anonimizza(record: dict, indice: int) -> dict:
    """Sostituisce CF/denominazioni con valori sintetici stabili (stesso indice
    per record con lo stesso cfDelegante originale, per preservare i duplicati)."""
    out = dict(record)
    out["cfDelegante"] = f"CFDELEG{indice:05d}0"[:16]
    out["denomDelegante"] = f"Delegante Anonimo {indice}"
    out["cfDelegato"] = "01820310819"  # CF studio, gia' pubblico nel repo
    if record.get("denomDelegato"):
        out["denomDelegato"] = "Studio Anonimo"
    out["idRichiesta"] = f"ID{indice:015d}"
    return out


def main():
    if not os.path.exists(_HAR):
        print(f"Campione non trovato ({_HAR}): fixture non rigenerata.")
        return
    lista = _estrai_lista_da_har(_HAR)

    # Indicizza per cfDelegante ORIGINALE cosi' i duplicati restano coerenti
    # dopo l'anonimizzazione (stesso indice = stesso CF sintetico).
    indice_per_cf: dict[str, int] = {}

    def indice_di(cf_originale: str) -> int:
        cf = (cf_originale or "").strip()
        if cf not in indice_per_cf:
            indice_per_cf[cf] = len(indice_per_cf) + 1
        return indice_per_cf[cf]

    campione = []

    def aggiungi(record):
        campione.append(_anonimizza(record, indice_di(record.get("cfDelegante", ""))))

    # Un UV irrilevante (solo servizio M05).
    uv_irrilevante = next(r for r in lista if r.get("tipoDelega") == "UV"
                          and not any(s.get("idServizio") in ("I42", "I31")
                                      for s in r.get("servizi") or []))
    aggiungi(uv_irrilevante)

    # Un UN con I42/I31 tra i servizi.
    un_rilevante = next(r for r in lista if r.get("tipoDelega") == "UN"
                        and any(s.get("idServizio") in ("I42", "I31")
                                for s in r.get("servizi") or []))
    aggiungi(un_rilevante)

    # Un CE (servizi vuoto, verifica anche lo strip degli spazi nel CF).
    ce = next(r for r in lista if r.get("tipoDelega") == "CE")
    ce = dict(ce)
    aggiungi(ce)
    campione[-1]["cfDelegante"] = campione[-1]["cfDelegante"] + "   "  # spazi finali nel CF sintetico

    # Due UV rilevanti con lo STESSO cfDelegante (per l'aggregazione), se esistono;
    # altrimenti li costruiamo a partire da uno rilevante esistente.
    uv_rilevante = next(r for r in lista if r.get("tipoDelega") == "UV"
                        and any(s.get("idServizio") in ("I42", "I31")
                                for s in r.get("servizi") or []))
    aggiungi(uv_rilevante)
    secondo = dict(uv_rilevante)
    secondo["servizi"] = [{"idServizio": "I31", "descrizione":
                           "Fatturazione elettronica e conservazione delle "
                           "fatture elettroniche", "servizio": "FAI31"}]
    secondo["dataFineDel"] = "01/01/2099"  # scadenza piu' lontana del primo
    aggiungi(secondo)  # stesso cfDelegante originale -> stesso indice/CF sintetico

    # Un record con dataInizioDel vecchia e uno recente, per il filtro data.
    vecchio = dict(un_rilevante)
    vecchio["dataInizioDel"] = "01/01/2022"
    aggiungi(vecchio)
    recente = dict(un_rilevante)
    recente["dataInizioDel"] = "01/09/2026"
    aggiungi(recente)

    with open(_OUT, "w", encoding="utf-8") as fh:
        json.dump({"lista": campione}, fh, indent=2, ensure_ascii=False)
    print(f"Fixture scritta: {_OUT} ({len(campione)} record).")


if __name__ == "__main__":
    main()
