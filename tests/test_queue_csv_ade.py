#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Test dell'aggancio del CSV AdE all'orchestratore (fec_queue)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_download as fd
import fec_queue as fq


def _voce(numero: str) -> dict:
    return {
        "decodificaTipoInvio": "Fattura tra privati",
        "tipoDocumento": "Fattura",
        "numeroFattura": numero,
        "dataFattura": "2026-07-10",
        "dataAccoglienzaFile": "2026-07-10",
        "pivaEmittente": "09876543210",
        "denominazioneEmittente": "FORNITORE ALFA SRL",
        "pivaCliente": "11223344556",
        "denominazioneCliente": "CLIENTE BETA SNC",
        "imponibile": "+000000000043,55",
        "imposta": "+000000000004,35",
        "fileDownload": {"idInvio": "10000000001", "statoFile": "Consegnata"},
        "dataConsegna": "10/07/2026",
    }


class TestCsvAdeNelDownload(unittest.TestCase):
    """Sostituisce la funzione di download con una finta: nessuna rete, si
    verifica solo l'orchestrazione (accumulo voci + scrittura di un unico file)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.chiamate = []
        spec_originale = fq.TIPI["emesse"]

        def finta(auth, dal, al, *, voci_out=None, **kw):
            self.chiamate.append((dal, al))
            if voci_out is not None:
                voci_out.append(_voce(f"{dal}-{al}"))
            return fd.DownloadResult("CFCLIENTE", self.tmp.name, 1, 1)

        fq.TIPI["emesse"] = fq._Spec(finta, spec_originale.fmt, spec_originale.kind)
        self.addCleanup(lambda: fq.TIPI.__setitem__("emesse", spec_originale))

    def _percorso(self, dal, al):
        return os.path.join(self.tmp.name, f"CFCLIENTE_{dal}-{al}_emesse.csv")

    def test_senza_flag_non_scrive_nulla(self):
        fq.esegui_richiesta(None, "emesse", dal="01072026", al="31072026",
                            cf_cliente="CFCLIENTE", log=lambda *a: None)
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_un_solo_csv_per_l_intero_periodo_spezzato(self):
        fq.esegui_richiesta(None, "emesse", dal="01012026", al="31122026",
                            cf_cliente="CFCLIENTE", csv_ade=True, log=lambda *a: None)
        self.assertGreater(len(self.chiamate), 1, "il periodo doveva essere spezzato")
        self.assertEqual(os.listdir(self.tmp.name),
                         ["CFCLIENTE_01012026-31122026_emesse.csv"])

    def test_il_csv_contiene_le_righe_di_tutti_i_blocchi(self):
        fq.esegui_richiesta(None, "emesse", dal="01012026", al="31122026",
                            cf_cliente="CFCLIENTE", csv_ade=True, log=lambda *a: None)
        with open(self._percorso("01012026", "31122026"), encoding="utf-8",
                  newline="") as fh:
            righe = fh.read().split("\r\n")[:-1]
        self.assertEqual(len(righe), 1 + len(self.chiamate))

    def test_periodo_senza_fatture_non_crea_il_file(self):
        spec = fq.TIPI["emesse"]
        fq.TIPI["emesse"] = fq._Spec(
            lambda auth, dal, al, *, voci_out=None, **kw:
                fd.DownloadResult("CFCLIENTE", self.tmp.name, 0, 0),
            spec.fmt, spec.kind)
        fq.esegui_richiesta(None, "emesse", dal="01072026", al="31072026",
                            cf_cliente="CFCLIENTE", csv_ade=True, log=lambda *a: None)
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_csv_ade_non_arriva_alla_funzione_di_download(self):
        """`csv_ade` è consumato da esegui_richiesta e NON deve raggiungere
        fec_download, che non lo accetta. La finta qui non ha **kw, quindi se
        filtrasse fallirebbe con TypeError invece di ingoiarlo in silenzio."""
        ricevuti = {}
        spec = fq.TIPI["emesse"]

        def severa(auth, dal, al, *, voci_out=None, control=None, cf_cliente="",
                   dest_dir=None, sottocartella=True, log=print,
                   escludi_scartate_pa=True, estrai_p7m=False,
                   filtro_piva="", filtro_cf=""):
            ricevuti["ok"] = True
            if voci_out is not None:
                voci_out.append(_voce("x"))
            return fd.DownloadResult("CFCLIENTE", self.tmp.name, 1, 1)

        fq.TIPI["emesse"] = fq._Spec(severa, spec.fmt, spec.kind)
        fq.esegui_richiesta(None, "emesse", dal="01072026", al="31072026",
                            cf_cliente="CFCLIENTE", csv_ade=True, log=lambda *a: None)
        self.assertTrue(ricevuti.get("ok"), "la funzione di download non è stata chiamata")
        self.assertTrue(os.path.exists(self._percorso("01072026", "31072026")))


class TestRichiestaCsvAde(unittest.TestCase):

    def test_campo_presente_e_disattivo_per_default(self):
        self.assertFalse(fq.Richiesta(tipo="emesse").csv_ade)

    def test_propagato_solo_ai_tipi_download(self):
        kw = fq._kwargs_richiesta(fq.Richiesta(tipo="emesse", csv_ade=True))
        self.assertTrue(kw["csv_ade"])
        kw = fq._kwargs_richiesta(fq.Richiesta(tipo="massive_emesse", csv_ade=True))
        self.assertNotIn("csv_ade", kw)


if __name__ == "__main__":
    unittest.main()
