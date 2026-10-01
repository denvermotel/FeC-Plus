#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Organizzazione delle cartelle di destinazione (modulo puro, cartelle temporanee)."""

import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_directory as fc


class TestNomi(unittest.TestCase):

    def test_nome_con_denominazione(self):
        self.assertEqual(fc.nome_ditta("ROSSI SRL", "01234567890"), "ROSSI SRL - 01234567890")

    def test_caratteri_vietati_spazi_e_punti_finali(self):
        self.assertEqual(fc.nome_ditta('A/B: "C"  D*.', "01234567890"),
                         "A B C D - 01234567890")

    def test_troncata_a_quaranta(self):
        nome = fc.nome_ditta("X" * 60, "P")
        self.assertEqual(nome, "X" * 40 + " - P")

    def test_senza_denominazione(self):
        self.assertEqual(fc.nome_ditta("", "01234567890"), "01234567890")
        self.assertEqual(fc.nome_ditta("  ...  ", "01234567890"), "01234567890")

    def test_anno_da_data(self):
        self.assertEqual(fc.anno_da_data("2026-07-10"), "2026")
        self.assertEqual(fc.anno_da_data("2026-07-10T08:00:00"), "2026")
        self.assertEqual(fc.anno_da_data("10/07/2025"), "2025")
        self.assertEqual(fc.anno_da_data("01012024"), "2024")
        self.assertIsNone(fc.anno_da_data(""))
        self.assertIsNone(fc.anno_da_data(None))
        self.assertIsNone(fc.anno_da_data("boh"))

    def test_timestamp_sessione(self):
        self.assertEqual(fc.timestamp_sessione(datetime(2026, 9, 24, 15, 7)),
                         "2026-09-24_1507")


class TestCartellaDitta(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)

    def test_nuova(self):
        self.assertEqual(fc.cartella_ditta(self.base, "01234567890", "ROSSI SRL",
                                           log=lambda *_: None),
                         os.path.join(self.base, "ROSSI SRL - 01234567890"))

    def test_riusa_se_la_denominazione_cambia(self):
        vecchia = os.path.join(self.base, "ROSSI SNC - 01234567890")
        os.makedirs(vecchia)
        self.assertEqual(fc.cartella_ditta(self.base, "01234567890", "ROSSI SRL",
                                           log=lambda *_: None), vecchia)

    def test_riusa_quella_col_solo_identificativo(self):
        sola = os.path.join(self.base, "01234567890")
        os.makedirs(sola)
        self.assertEqual(fc.cartella_ditta(self.base, "01234567890", "ROSSI SRL",
                                           log=lambda *_: None), sola)

    def test_non_confonde_identificativi_che_finiscono_uguale(self):
        os.makedirs(os.path.join(self.base, "ALTRA - 101234567890"))
        self.assertEqual(fc.trova_cartella_ditta(self.base, "01234567890"), (None, 0))

    def test_piu_cartelle_usa_la_piu_recente_e_lo_dice(self):
        a = os.path.join(self.base, "A - 01234567890")
        b = os.path.join(self.base, "B - 01234567890")
        os.makedirs(a)
        os.makedirs(b)
        ora = time.time()
        os.utime(a, (ora - 100, ora - 100))
        os.utime(b, (ora, ora))
        righe = []
        self.assertEqual(fc.cartella_ditta(self.base, "01234567890", "C", log=righe.append), b)
        self.assertEqual(len(righe), 1)
        self.assertIn("2 cartelle", righe[0])

    def test_base_inesistente(self):
        self.assertEqual(fc.trova_cartella_ditta(os.path.join(self.base, "no"), "X"),
                         (None, 0))


class TestRisolvi(unittest.TestCase):

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.ditta = os.path.join(self.base, "ROSSI SRL - 01234567890")

    def _r(self, config, chiave, **kw):
        return fc.risolvi(config, chiave, "01234567890", "ROSSI SRL", log=lambda *_: None, **kw)

    def test_ditta_xml_per_anno_del_documento(self):
        d = self._r(fc.ConfigCartelle(self.base), "emesse", per_documento=True)
        self.assertEqual(d, fc.Destinazione(os.path.join(self.ditta, "Fatture emesse"),
                                            True, self.ditta))
        self.assertTrue(os.path.isdir(d.cartella))

    def test_ditta_elenco_con_anno_del_periodo(self):
        d = self._r(fc.ConfigCartelle(self.base), "elenchi", anno_periodo="2026")
        self.assertEqual(d.cartella, os.path.join(self.ditta, "Elenchi", "2026"))
        self.assertFalse(d.per_anno)

    def test_ditta_senza_anno(self):
        d = self._r(fc.ConfigCartelle(self.base, anno=False), "emesse", per_documento=True)
        self.assertEqual(d, fc.Destinazione(os.path.join(self.ditta, "Fatture emesse"),
                                            False, self.ditta))
        d = self._r(fc.ConfigCartelle(self.base, anno=False), "bolli", anno_periodo="2026")
        self.assertEqual(d.cartella, os.path.join(self.ditta, "Bolli virtuali"))

    def test_richieste_massive_mai_con_anno(self):
        d = self._r(fc.ConfigCartelle(self.base), "massive_corrispettivi", anno_periodo="2026")
        self.assertEqual(d.cartella, os.path.join(self.ditta, "Richieste massive"))

    def test_sessione(self):
        config = fc.ConfigCartelle(self.base, modalita="sessione", sessione="2026-09-24_1507")
        d = self._r(config, "trans_emesse", per_documento=True)
        radice = os.path.join(self.ditta, "2026-09-24_1507")
        self.assertEqual(d, fc.Destinazione(os.path.join(radice, "Transfrontaliere emesse"),
                                            False, radice))

    def test_sessione_senza_timestamp_e_un_errore(self):
        with self.assertRaises(ValueError):
            self._r(fc.ConfigCartelle(self.base, modalita="sessione"), "emesse")

    def test_modalita_sconosciuta(self):
        with self.assertRaises(ValueError):
            self._r(fc.ConfigCartelle(self.base, modalita="boh"), "emesse")

    def test_personalizzata_senza_sottocartella_ha_la_precedenza(self):
        fissa = os.path.join(self.base, "gestionale")
        config = fc.ConfigCartelle(self.base, personalizzate={"emesse": (fissa, True)})
        d = self._r(config, "emesse", per_documento=True)
        self.assertEqual(d, fc.Destinazione(fissa, False, fissa))

    def test_senza_sottocartella_senza_percorso_usa_la_base(self):
        config = fc.ConfigCartelle(self.base, personalizzate={"bolli": ("", True)})
        d = self._r(config, "bolli", anno_periodo="2026")
        self.assertEqual(d, fc.Destinazione(self.base, False, self.base))

    def test_personalizzata_sostituisce_la_base(self):
        altra = os.path.join(self.base, "altra")
        config = fc.ConfigCartelle(self.base, personalizzate={"utility": (altra, False)})
        d = self._r(config, "elenco_corrispettivi", anno_periodo="2025")
        self.assertEqual(d.cartella, os.path.join(altra, "ROSSI SRL - 01234567890",
                                                  "Corrispettivi", "2025"))

    def test_chiavi_note(self):
        self.assertEqual(set(fc.CARTELLE), {
            "emesse", "ricevute", "trans_emesse", "trans_ricevute", "messe_disposizione",
            "massive", "massive_corrispettivi", "bolli", "elenchi", "elenco_corrispettivi",
            "risultati_massive", "risultati_corrispettivi"})
        self.assertEqual(fc.TIPO_CHIAVE["massive_emesse"], "massive")
        self.assertEqual(fc.TIPO_CHIAVE["corrispettivi"], "massive_corrispettivi")
        self.assertEqual(fc.TIPO_CHIAVE["emesse"], "emesse")


class TestSoggetto(unittest.TestCase):

    def test_login_prima_di_tutto(self):
        self.assertEqual(fc.soggetto("01234567890", "ROSSI SRL", "", "CFCLIENTE", "CFUT", []),
                         ("01234567890", "ROSSI SRL"))

    def test_piva_del_form_e_denominazione_dalle_deleghe(self):
        deleghe = [{"codice_fiscale": "CFCLIENTE", "partita_iva": "01234567890",
                    "denominazione": "BIANCHI SAS"}]
        self.assertEqual(fc.soggetto("", "", "01234567890", "CFCLIENTE", "CFUT", deleghe),
                         ("01234567890", "BIANCHI SAS"))

    def test_solo_cf(self):
        self.assertEqual(fc.soggetto("", "", "", "cfcliente", "CFUT", []), ("CFCLIENTE", ""))
        self.assertEqual(fc.soggetto("", "", "", "", "cfut", []), ("CFUT", ""))


class TestTesti(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_sessione_txt(self):
        percorso = fc.scrivi_sessione(self.tmp, {"Periodo": "01072026 - 31072026",
                                                 "Fatture scaricate": 3})
        self.assertEqual(percorso, os.path.join(self.tmp, "sessione.txt"))
        with open(percorso, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "Periodo: 01072026 - 31072026\nFatture scaricate: 3\n")

    def test_descrizione(self):
        self.assertIn("Fatture emesse", fc.descrizione(fc.ConfigCartelle("B"), "emesse"))
        self.assertIn("anno", fc.descrizione(fc.ConfigCartelle("B"), "emesse"))
        self.assertIn("AAAA-MM-GG_HHMM", fc.descrizione(
            fc.ConfigCartelle("B", modalita="sessione"), "emesse"))
        self.assertIn("direttamente", fc.descrizione(
            fc.ConfigCartelle("B", personalizzate={"emesse": ("G", True)}), "emesse"))


if __name__ == "__main__":
    unittest.main()
