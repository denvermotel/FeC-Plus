#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus — v0.03 dev
"""
fec_deps.py — Controllo dipendenze (G.8), punto unico riusabile da GUI e CLI.

Verifica che i pacchetti di `requirements.txt` siano installati e costruisce i comandi
pip per installarli. La logica è qui sola per non duplicarla tra `fec_gui.py` e `fec_cli.py`.

Ruoli delle dipendenze:
  - core    : sempre richieste (login + persistenza credenziali).
  - browser : opzionali, servono solo al backend «browser» (Playwright) / SPID-CIE (C.7).
              La loro assenza NON blocca il backend leggero «requests» (C.1).
  - gui     : opzionali, solo per la GUI desktop; hanno già un fallback (es. tkcalendar → G.2)
              e non servono alla CLI.
  - p7m     : opzionale, serve solo se l'utente attiva «Estrai p7m» nel download; non
              installata di default (install_commands) per restare leggeri.
  - excel   : opzionale, serve solo all'export Excel della tab Utility (C.9/G.6,
              fec_utility.py); non installata di default, come p7m.
"""

from __future__ import annotations

__version__ = "0.03 dev"

import importlib.util
import sys
from typing import NamedTuple


class Dep(NamedTuple):
    pip: str      # nome del pacchetto per pip (come in requirements.txt)
    module: str   # nome del modulo per l'import (può differire dal pip name)
    role: str     # "core" | "browser" | "gui" | "p7m" | "excel"


# Allineato a requirements.txt. NB: python-dateutil si importa come «dateutil».
DEPS: tuple[Dep, ...] = (
    Dep("requests",        "requests",   "core"),
    Dep("python-dateutil", "dateutil",   "core"),
    Dep("cryptography",    "cryptography", "core"),
    Dep("playwright",      "playwright", "browser"),
    Dep("tkcalendar",      "tkcalendar", "gui"),
    Dep("asn1crypto",      "asn1crypto", "p7m"),
    Dep("openpyxl",        "openpyxl",   "excel"),
)


def _is_installed(module: str) -> bool:
    """True se il modulo è importabile (senza importarlo davvero)."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def find_missing() -> dict[str, list[str]]:
    """Ritorna le dipendenze mancanti raggruppate per ruolo: {"core": [...],
    "browser": [...], "gui": [...], "p7m": [...], "excel": [...]}. I nomi sono i pip name."""
    missing: dict[str, list[str]] = {"core": [], "browser": [], "gui": [], "p7m": [], "excel": []}
    for dep in DEPS:
        if not _is_installed(dep.module):
            missing[dep.role].append(dep.pip)
    return missing


def install_commands(include_playwright: bool, python: str = sys.executable) -> list[list[str]]:
    """Comandi pip per installare le dipendenze.

    Set completo = core + gui (sempre). Se `include_playwright` è True aggiunge anche il
    pacchetto browser (Playwright) e il download del browser Chromium.
    """
    packages = [d.pip for d in DEPS if d.role in ("core", "gui")]
    if include_playwright:
        packages += [d.pip for d in DEPS if d.role == "browser"]

    commands = [[python, "-m", "pip", "install", "--upgrade", *packages]]
    if include_playwright:
        commands.append([python, "-m", "playwright", "install", "chromium"])
    return commands


def uninstall_command(packages: list[str], python: str = sys.executable) -> list[list[str]]:
    """Comando pip per disinstallare i pacchetti indicati (uso dev/diagnostico)."""
    return [[python, "-m", "pip", "uninstall", "-y", *packages]]


def installed_deps() -> list[Dep]:
    """Sottoinsieme di DEPS attualmente installato (per popolare l'elenco da disinstallare)."""
    return [d for d in DEPS if _is_installed(d.module)]


def pip_install_hint(packages: list[str], python: str = "python") -> str:
    """Stringa suggerimento «python -m pip install …» per i messaggi all'utente."""
    return f"{python} -m pip install {' '.join(packages)}"
