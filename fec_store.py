#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.03 alpha
"""
fec_store.py - Persistenza separata di CREDENZIALI (cifrate) e PREFERENZE (in chiaro).

Due file accanto al modulo:
  - fec_credentials.dat : JSON {cf, pin, cfstudio} cifrato con Fernet.
  - fec_settings.json   : preferenze NON sensibili (login_backend, browser_headless,
                          std_profilo, std_destdir, salva_credenziali, …).

CIFRATURA LEGGERA E PORTABILE (scelta dell'utente): la chiave Fernet è derivata da un
segreto incluso nel codice (PBKDF2), quindi i file si possono spostare su un altro
computer/SO senza configurare keyring o passphrase. ⚠️ È protezione "obfuscation-grade":
evita la lettura casuale dei dati in chiaro su disco, ma NON resiste a chi dispone del
codice sorgente. La password Entratel non viene comunque mai salvata.
"""

from __future__ import annotations

__version__ = "0.03 alpha"

import base64
import json
import os
import sys

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Eseguibile PyInstaller: credenziali e impostazioni accanto all'exe (persistenti),
# non nella cartella temporanea del bundle. Da sorgente: accanto al modulo.
if getattr(sys, "frozen", False):
    SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CRED_FILE = os.path.join(SCRIPT_DIR, "fec_credentials.dat")
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "fec_settings.json")

# Campi sensibili (cifrati) vs preferenze (in chiaro).
CRED_KEYS = ("cf", "pin", "cfstudio")
SETTINGS_KEYS = ("login_backend", "browser_headless", "modalita",
                 "std_destdir", "salva_credenziali", "cartelle_documenti", "console_sash",
                 "deleghe_no_update", "std_escludi_scartate_pa", "std_estrai_p7m",
                 "std_includi_trans", "std_includi_disposizione",
                 "cred_espanse", "estrai_zip_risultati_massivi")

# Segreto "leggero" incluso nel codice → cifratura portabile (nessun OS/keyring), ma
# obfuscation-grade. Cambiarlo invalida i file credenziali già salvati.
_APP_SECRET = b"FeC-Plus/portable-light-credentials/v1"
_SALT = b"FeC-Plus/kdf-salt/v1"


def _fernet() -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=_SALT, iterations=200_000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(_APP_SECRET)))


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ── Credenziali (cifrate) ─────────────────────────────────────────────────────

def load_credentials() -> dict:
    """Ritorna {cf, pin, cfstudio} decifrati, o {} se assenti/illeggibili."""
    if not os.path.exists(CRED_FILE):
        return {}
    try:
        with open(CRED_FILE, "rb") as fh:
            blob = _fernet().decrypt(fh.read())
        data = json.loads(blob.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, InvalidToken, ValueError):
        return {}


def save_credentials(cred: dict) -> None:
    """Cifra e salva i soli campi credenziali."""
    payload = {k: str(cred.get(k, "")).strip() for k in CRED_KEYS}
    token = _fernet().encrypt(json.dumps(payload).encode("utf-8"))
    with open(CRED_FILE, "wb") as fh:
        fh.write(token)


def clear_credentials() -> None:
    """Rimuove il file credenziali (opzione «non salvare credenziali»)."""
    try:
        os.remove(CRED_FILE)
    except OSError:
        pass


def credentials_exist() -> bool:
    return os.path.exists(CRED_FILE)


# ── Preferenze (in chiaro) ────────────────────────────────────────────────────

def load_settings() -> dict:
    return _read_json(SETTINGS_FILE)


def save_settings(settings: dict) -> None:
    clean = {k: settings[k] for k in SETTINGS_KEYS if k in settings}
    with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, indent=2)
