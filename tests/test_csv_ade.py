#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Test del modulo fec_csv_ade (formato CSV «Esporta la tabella» dell'AdE)."""

import os
import sys
import unittest

# Il progetto non usa package: i moduli stanno nella radice del repo.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_csv_ade


class TestFormattaRighe(unittest.TestCase):

    def test_campi_quotati_separati_da_punto_e_virgola_e_crlf(self):
        testo = fec_csv_ade.formatta_righe([["a", "b"], ["c", "d"]])
        self.assertEqual(testo, '"a";"b"\r\n"c";"d"\r\n')

    def test_virgolette_interne_raddoppiate(self):
        testo = fec_csv_ade.formatta_righe([['DITTA "ALFA" SRL']])
        self.assertEqual(testo, '"DITTA ""ALFA"" SRL"\r\n')

    def test_stringa_vuota_resta_quotata(self):
        testo = fec_csv_ade.formatta_righe([["", "x"]])
        self.assertEqual(testo, '"";"x"\r\n')

    def test_none_produce_campo_vuoto_non_quotato(self):
        # ng-csv: stringifyField(undefined) torna undefined -> join lo rende ""
        testo = fec_csv_ade.formatta_righe([[None, "x"]])
        self.assertEqual(testo, ';"x"\r\n')

    def test_elenco_vuoto_produce_stringa_vuota(self):
        self.assertEqual(fec_csv_ade.formatta_righe([]), "")


def _voce(**extra) -> dict:
    """Voce di elenco minima e valida, sul modello di
    _materiale/dump_lista_emesse_01072026.json. `extra` sovrascrive o aggiunge."""
    voce = {
        "decodificaTipoInvio": "Fattura tra privati",
        "tipoDocumento": "Fattura",
        "numeroFattura": "385/A",
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
    voce.update(extra)
    return voce


class TestRigheEmesseRicevute(unittest.TestCase):

    def test_intestazione_emesse(self):
        righe = fec_csv_ade.righe_csv([], "emesse")
        self.assertEqual(righe[0], [
            "Tipo fattura", "Tipo documento", "Numero fattura / Documento",
            "Data emissione", "Data trasmissione", "Codice fiscale fornitore",
            "Partita IVA fornitore", "Denominazione fornitore",
            "Codice fiscale cliente", "Partita IVA cliente", "Denominazione cliente",
            "Imponibile/Importo (totale in euro)", "Imposta (totale in euro)",
            "Sdi/file", "Fatture consegnate", "Data consegna/Presa visione",
            "Bollo virtuale"])

    def test_intestazione_ricevute_cambia_solo_la_colonna_data(self):
        em = fec_csv_ade.righe_csv([], "emesse")[0]
        ri = fec_csv_ade.righe_csv([], "ricevute")[0]
        self.assertEqual(ri[15], "Data ricezione")
        self.assertEqual(em[:15], ri[:15])
        self.assertEqual(em[16], ri[16])

    def test_riga_completa(self):
        riga = fec_csv_ade.righe_csv([_voce()], "emesse")[1]
        self.assertEqual(riga, [
            "'Fattura tra privati'", "Fattura", "'385/A'", "10/07/2026", "10/07/2026",
            "'Non presente'", "'09876543210'", "FORNITORE ALFA SRL",
            "'Non presente'", "'11223344556'", "CLIENTE BETA SNC",
            "000000000043,55", "000000000004,35", "10000000001",
            "Consegnata", "10/07/2026", ""])

    def test_identificativi_assenti_diventano_non_presente(self):
        riga = fec_csv_ade.righe_csv([_voce()], "emesse")[1]
        self.assertEqual(riga[5], "'Non presente'")   # cfEmittente assente
        self.assertEqual(riga[8], "'Non presente'")   # cfCliente assente

    def test_identificativi_presenti_hanno_l_apice(self):
        riga = fec_csv_ade.righe_csv(
            [_voce(cfEmittente="RSSMRA80A01H501U")], "emesse")[1]
        self.assertEqual(riga[5], "'RSSMRA80A01H501U'")

    def test_presa_visione_aggiunge_il_suffisso_e_usa_la_sua_data(self):
        # Caso reale del campione: statoFile «Mancata consegna» + presa visione.
        voce = _voce(fileDownload={"idInvio": "10000000002",
                                   "statoFile": "Mancata consegna",
                                   "dataPresaVisione": "10/08/2026"})
        riga = fec_csv_ade.righe_csv([voce], "ricevute")[1]
        self.assertEqual(riga[14], "Mancata consegna/Presa visione")
        self.assertEqual(riga[15], "10/08/2026")

    def test_bollo_virtuale(self):
        self.assertEqual(fec_csv_ade.righe_csv([_voce(bolloVirtuale="Y")], "emesse")[1][16], "Si")
        self.assertEqual(fec_csv_ade.righe_csv([_voce(bolloVirtuale="N")], "emesse")[1][16], "")
        self.assertEqual(fec_csv_ade.righe_csv([_voce()], "emesse")[1][16], "")

    def test_importo_negativo_conserva_il_segno(self):
        riga = fec_csv_ade.righe_csv([_voce(imponibile="-000000000043,55")], "emesse")[1]
        self.assertEqual(riga[11], "-000000000043,55")

    def test_ricevute_ricezione_ed_emissione_condividono_il_layout(self):
        base = fec_csv_ade.righe_csv([_voce()], "ricevute")
        for alias in ("ricevute_ricezione", "ricevute_emissione"):
            self.assertEqual(fec_csv_ade.righe_csv([_voce()], alias), base)

    def test_importo_col_punto_decimale_diventa_virgola(self):
        # Il JS fa .replace('.', ',') prima di togliere il '+': se il portale
        # mandasse il punto, un gestionale italiano importerebbe il valore sbagliato.
        riga = fec_csv_ade.righe_csv([_voce(imponibile="+000000001689.50",
                                            imposta="+000000000323.50")], "emesse")[1]
        self.assertEqual(riga[11], "000000001689,50")
        self.assertEqual(riga[12], "000000000323,50")

    def test_campi_grezzi_assenti_restano_non_quotati(self):
        # ng-csv: i campi passati così come sono restano `undefined` se mancano,
        # e finiscono nel CSV come vuoti NON quotati (qui: None).
        voce = _voce()
        for chiave in ("tipoDocumento", "denominazioneEmittente", "denominazioneCliente"):
            del voce[chiave]
        voce["fileDownload"] = {}
        del voce["dataConsegna"]
        riga = fec_csv_ade.righe_csv([voce], "ricevute")[1]
        for indice in (1, 7, 10, 13, 14, 15):
            self.assertIsNone(riga[indice], f"colonna {indice}")

    def test_riga_senza_stato_ne_data_produce_campi_non_quotati(self):
        voce = _voce()
        voce["fileDownload"] = {}
        del voce["dataConsegna"]
        testo = fec_csv_ade.formatta_righe(fec_csv_ade.righe_csv([voce], "ricevute"))
        ultima = testo.split("\r\n")[1]
        self.assertTrue(ultima.endswith(';;""'), ultima[-20:])

    def test_stringa_vuota_nel_json_resta_quotata(self):
        # Diverso da «assente»: il JS distingue "" (quotata) da undefined (nuda).
        riga = fec_csv_ade.righe_csv([_voce(tipoDocumento="")], "emesse")[1]
        self.assertEqual(riga[1], "")

    def test_tipo_sconosciuto_solleva_errore(self):
        with self.assertRaises(ValueError):
            fec_csv_ade.righe_csv([], "pippo")


class TestNomeFile(unittest.TestCase):

    def test_convenzione_uguale_all_export_excel(self):
        self.assertEqual(
            fec_csv_ade.nome_file("01234567890", "01072026", "10082026", "ricevute"),
            "01234567890_01072026-10082026_ricevute.csv")

    def test_usa_l_etichetta_del_layout_non_l_alias(self):
        self.assertEqual(
            fec_csv_ade.nome_file("X", "01012026", "31012026", "ricevute_emissione"),
            "X_01012026-31012026_ricevute.csv")

    def test_prefisso_ripulito(self):
        self.assertEqual(
            fec_csv_ade.nome_file("  X  ", "01012026", "31012026", "emesse"),
            "X_01012026-31012026_emesse.csv")


class TestAltriLayout(unittest.TestCase):

    def test_messe_a_disposizione_non_ha_la_colonna_data_finale(self):
        intestazione = fec_csv_ade.righe_csv([], "messe_disposizione")[0]
        self.assertEqual(len(intestazione), 16)
        self.assertEqual(intestazione[14], "Fatture consegnate")
        self.assertEqual(intestazione[15], "Bollo virtuale")

    def test_messe_a_disposizione_riga(self):
        riga = fec_csv_ade.righe_csv([_voce(bolloVirtuale="Y")], "messe_disposizione")[1]
        self.assertEqual(len(riga), 16)
        self.assertEqual(riga[13], "10000000001")
        self.assertEqual(riga[14], "Consegnata")
        self.assertEqual(riga[15], "Si")

    def test_alias_messe_a_disposizione(self):
        self.assertEqual(fec_csv_ade.righe_csv([], "messe_a_disposizione"),
                         fec_csv_ade.righe_csv([], "messe_disposizione"))

    def test_intestazione_trans_emesse(self):
        self.assertEqual(fec_csv_ade.righe_csv([], "trans_emesse")[0], [
            "Codice fiscale fornitore", "Partita IVA fornitore",
            "Denominazione fornitore", "Tipo documento", "Numero fattura/Documento",
            "Data emissione fattura", "Data trasmissione fattura",
            "Codice fiscale cliente estero", "Paese cliente estero",
            "Partita IVA cliente estero", "Denominazione cliente estero",
            "Imponibile/Importo (totale in euro)", "Imposta (totale in euro)",
            "Trasmessa da", "Stato", "Sdi/file"])

    def test_riga_trans_emesse(self):
        voce = _voce(idPaeseCessionario="DE", clienteFornitore="Fornitore",
                     stato="Emessa")
        riga = fec_csv_ade.righe_csv([voce], "trans_emesse")[1]
        self.assertEqual(riga, [
            "'Non presente'", "'09876543210'", "FORNITORE ALFA SRL", "Fattura",
            "'385/A'", "10/07/2026", "10/07/2026", "'Non presente'", "DE",
            "'11223344556'", "CLIENTE BETA SNC",
            "000000000043,55", "000000000004,35", "Fornitore", "Emessa",
            "10000000001"])

    def test_intestazione_trans_ricevute(self):
        self.assertEqual(fec_csv_ade.righe_csv([], "trans_ricevute")[0], [
            "Codice fiscale fornitore estero", "Paese fornitore estero",
            "Partita IVA fornitore estero", "Denominazione fornitore estero",
            "Tipo documento", "Numero fattura/Documento", "Data emissione fattura",
            "Data trasmissione fattura", "Data registrazione fattura",
            "Codice fiscale cliente", "Partita IVA cliente", "Denominazione cliente",
            "Imponibile/Importo (totale in euro)", "Imposta (totale in euro)",
            "Stato", "Sdi/File"])

    def test_trans_ricevute_data_registrazione_da_iso(self):
        voce = _voce(idPaeseCedente="FR", dataRicezione="2026-07-12", stato="Ricevuta")
        riga = fec_csv_ade.righe_csv([voce], "trans_ricevute")[1]
        self.assertEqual(riga[1], "FR")
        self.assertEqual(riga[8], "12/07/2026")
        self.assertEqual(riga[14], "Ricevuta")

    def test_tutti_i_layout_hanno_intestazione_e_campi_allineati(self):
        for tipo, lay in fec_csv_ade.LAYOUT.items():
            with self.subTest(tipo=tipo):
                self.assertEqual(len(lay.intestazione), len(lay.campi))


FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _campione_reale() -> str | None:
    """Percorso del campione vero in `_materiale/`, se presente su questa macchina.

    Individuato dalla STRUTTURA e non dal nome (che contiene dati di una persona
    reale e non va scritto in un file versionato), con la stessa regola usata dal
    generatore della fixture. `None` se non c'è: il test che lo usa si salta.
    """
    import csv as _csv
    materiale = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_materiale")
    try:
        nomi = sorted(os.listdir(materiale))
    except OSError:
        return None
    for nome in nomi:
        if not nome.lower().endswith(".csv"):
            continue
        percorso = os.path.join(materiale, nome)
        try:
            with open(percorso, encoding="utf-8", newline="") as fh:
                intestazione = next(_csv.reader(fh, delimiter=";"))
        except (OSError, StopIteration, UnicodeDecodeError):
            continue
        if len(intestazione) == 17 and intestazione[15] == "Data ricezione":
            return percorso
    return None


CAMPIONE_REALE = _campione_reale()


class TestGoldenRicevute(unittest.TestCase):
    """Confronto con un CSV esportato davvero dal portale AdE (25 fatture
    ricevute, 01/07/2026-10/08/2026), anonimizzato per poterlo versionare."""

    def setUp(self):
        import json
        with open(os.path.join(FIXTURES, "elenco_ricevute_25.json"), encoding="utf-8") as fh:
            self.voci = json.load(fh)
        with open(os.path.join(FIXTURES, "elenco_ricevute_25_atteso.csv"),
                  encoding="utf-8", newline="") as fh:
            self.atteso = fh.read()

    def test_testo_identico_alla_fixture(self):
        prodotto = fec_csv_ade.formatta_righe(
            fec_csv_ade.righe_csv(self.voci, "ricevute"))
        self.assertEqual(prodotto, self.atteso)

    def test_file_scritto_identico_byte_a_byte(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            percorso = fec_csv_ade.scrivi_csv(
                os.path.join(tmp, "out.csv"), self.voci, "ricevute")
            with open(percorso, "rb") as fh:
                prodotto = fh.read()
        with open(os.path.join(FIXTURES, "elenco_ricevute_25_atteso.csv"), "rb") as fh:
            self.assertEqual(prodotto, fh.read())

    def test_nessun_bom_in_testa(self):
        with open(os.path.join(FIXTURES, "elenco_ricevute_25_atteso.csv"), "rb") as fh:
            self.assertFalse(fh.read(3).startswith(b"\xef\xbb\xbf"))

    @unittest.skipUnless(CAMPIONE_REALE,
                         "campione reale non presente (_materiale/ è fuori da Git)")
    def test_struttura_identica_al_campione_reale(self):
        """Verifica più forte, solo in locale: sul campione vero devono
        combaciare intestazione, numero di righe e struttura di ogni riga."""
        import csv as _csv
        with open(CAMPIONE_REALE, encoding="utf-8", newline="") as fh:
            reali = list(_csv.reader(fh, delimiter=";"))
        prodotte = fec_csv_ade.righe_csv(self.voci, "ricevute")
        self.assertEqual(prodotte[0], reali[0])
        self.assertEqual(len(prodotte), len(reali))
        for prodotta, reale in zip(prodotte[1:], reali[1:]):
            self.assertEqual(len(prodotta), len(reale))
            # Colonne non anonimizzate: devono coincidere valore per valore.
            for col in (0, 1, 3, 4, 11, 12, 14, 15, 16):
                self.assertEqual(prodotta[col], reale[col], f"colonna {col}")


class TestGoldenMesseDisposizione(unittest.TestCase):
    """Secondo golden, su un export vero del portale (2° trimestre 2026): valida un
    layout che finora era coperto solo da casi sintetici. Fixture anonimizzata."""

    def setUp(self):
        import json
        percorso = os.path.join(FIXTURES, "elenco_md.json")
        if not os.path.exists(percorso):
            self.skipTest("fixture «messe a disposizione» non generata")
        with open(percorso, encoding="utf-8") as fh:
            self.voci = json.load(fh)
        with open(os.path.join(FIXTURES, "elenco_md_atteso.csv"),
                  encoding="utf-8", newline="") as fh:
            self.atteso = fh.read()

    def test_testo_identico_alla_fixture(self):
        prodotto = fec_csv_ade.formatta_righe(
            fec_csv_ade.righe_csv(self.voci, "messe_disposizione"))
        self.assertEqual(prodotto, self.atteso)

    def test_sedici_colonne_senza_data_finale(self):
        righe = fec_csv_ade.righe_csv(self.voci, "messe_disposizione")
        self.assertTrue(all(len(r) == 16 for r in righe))


if __name__ == "__main__":
    unittest.main()
