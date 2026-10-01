#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""
Accanto al codice ci sono i file veri dell'utente. Ogni test che istanzia FecGui
li protegge: copia con sha256 prima, ripristino e verifica dopo.
"""

import hashlib
import os
import shutil
import tempfile

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE_REALI = ("fec_settings.json", "fec_credentials.dat", "fec_deleghe.json",
              "fec_richieste_massive.json")


def _sha256(percorso: str) -> str:
    with open(percorso, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class DatiRealiProtetti:
    def __enter__(self):
        self._copia = tempfile.mkdtemp(prefix="fec_backup_")
        self._stato = {}
        for nome in FILE_REALI:
            percorso = os.path.join(RADICE, nome)
            if os.path.exists(percorso):
                shutil.copy2(percorso, os.path.join(self._copia, nome))
                self._stato[nome] = _sha256(percorso)
            else:
                self._stato[nome] = None
        return self

    def __exit__(self, *_):
        try:
            for nome, sha in self._stato.items():
                percorso = os.path.join(RADICE, nome)
                if sha is None:
                    if os.path.exists(percorso):
                        os.remove(percorso)
                    continue
                if not os.path.exists(percorso) or _sha256(percorso) != sha:
                    shutil.copy2(os.path.join(self._copia, nome), percorso)
                if _sha256(percorso) != sha:
                    raise AssertionError(f"{nome}: ripristino non riuscito")
        finally:
            shutil.rmtree(self._copia, True)
        return False
