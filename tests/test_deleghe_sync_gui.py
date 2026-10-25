#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sincronizzazione delle deleghe dal portale e controllo dei canali delle deleghe
nuove, sulla finestra protetta di `AppGuiCase` (dati reali con sha256, salvataggi
neutralizzati, compreso `fec_deleghe.save_deleghe`)."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_download
from _appgui import AppGuiCase

_RIGA_A = {"codice_fiscale": "AAA", "denominazione": "Cliente A",
           "partita_iva": "", "data_fine_delega": "", "conservazione": False,
           "codice_destinatario": "", "pec": "", "canale_massivo": "",
           "etichetta1": "", "etichetta2": ""}


class TestDelegheControllaCanaliNuovi(AppGuiCase):
    def setUp(self):
        super().setUp()
        # In produzione self.control viene creato dal chiamante (il dialogo di
        # sincronizzazione da portale, sul thread Tk) prima di lanciare il
        # worker, come per le altre operazioni in-process con pausa/interrompi;
        # qui lo simuliamo direttamente.
        self.app.control = fec_download.Controllo()
        self.app.deleghe_rows = [dict(_RIGA_A)]

    @patch("fec_anagrafica.recupera")
    @patch("ade_auth.seleziona_utenza")
    @patch("ade_auth.autentica")
    def test_applica_dati_ade_al_cf_nuovo(self, mock_autentica, mock_scelta,
                                          mock_recupera):
        mock_autentica.return_value = MagicMock()
        mock_scelta.return_value = MagicMock()
        mock_recupera.return_value = {
            "denominazione": "Cliente A", "partita_iva": "01234567890",
            "conservazione": True, "codice_destinatario": "ABC1234",
            "pec": "", "canale_massivo": "Fornitore (SCARICO FATTURE)",
        }
        self.app._get_creds = MagicMock(return_value=("cf", "pin", "pwd", "cfst"))
        self.app.modalita = MagicMock()
        self.app.modalita.get.return_value = "Studio - Delega Cliente"

        self.app._deleghe_controlla_canali_nuovi(["AAA"])

        riga = self.app.deleghe_rows[0]
        self.assertEqual(riga["codice_destinatario"], "ABC1234")
        self.assertEqual(riga["canale_massivo"], "Fornitore (SCARICO FATTURE)")
        self.assertTrue(riga["conservazione"])

    @patch("fec_anagrafica.recupera")
    @patch("ade_auth.seleziona_utenza")
    @patch("ade_auth.autentica")
    def test_cf_fallito_non_interrompe_il_lotto(self, mock_autentica, mock_scelta,
                                                mock_recupera):
        from ade_auth import AuthError
        self.app.deleghe_rows.append({
            "codice_fiscale": "BBB", "denominazione": "Cliente B",
            "partita_iva": "", "data_fine_delega": "", "conservazione": False,
            "codice_destinatario": "", "pec": "", "canale_massivo": "",
            "etichetta1": "", "etichetta2": "",
        })
        mock_autentica.return_value = MagicMock()
        mock_scelta.side_effect = [AuthError("utenza", "Delegante non trovato"),
                                   MagicMock()]
        mock_recupera.return_value = {
            "denominazione": "Cliente B", "partita_iva": "",
            "conservazione": False, "codice_destinatario": "XYZ9999",
            "pec": "", "canale_massivo": "",
        }
        self.app._get_creds = MagicMock(return_value=("cf", "pin", "pwd", "cfst"))
        self.app.modalita = MagicMock()
        self.app.modalita.get.return_value = "Studio - Delega Cliente"

        self.app._deleghe_controlla_canali_nuovi(["AAA", "BBB"])

        riga_b = next(r for r in self.app.deleghe_rows
                     if r["codice_fiscale"] == "BBB")
        self.assertEqual(riga_b["codice_destinatario"], "XYZ9999")


class TestDelegheSincronizzaDaPortale(AppGuiCase):
    def setUp(self):
        super().setUp()
        self.app.deleghe_rows = [dict(_RIGA_A)]

    @patch("fec_gui.messagebox.askyesno", return_value=False)
    @patch("fec_deleghe_sync.sincronizza")
    def test_nuove_deleghe_propone_controllo_con_stima_e_lo_rifiuta(
            self, mock_sync, mock_askyesno):
        mock_sync.return_value = [
            {"cfDelegante": "BBB", "denomDelegante": "Cliente B",
            "servizi": [{"idServizio": "I42"}],
            "dataInizioDel": "01/01/2020", "dataFineDel": "01/01/2030"},
        ]
        self.app._get_creds = MagicMock(return_value=("cf", "pin", "pwd", "cfst"))
        self.app.modalita = MagicMock()
        self.app.modalita.get.return_value = "Studio - Delega Cliente"
        self.app._deleghe_controlla_canali_nuovi = MagicMock()

        esito = self.app._deleghe_sincronizza_da_portale(soglia_data="", forza_tutte=False)

        cf_presenti = {r["codice_fiscale"] for r in self.app.deleghe_rows}
        self.assertIn("BBB", cf_presenti)
        mock_askyesno.assert_called_once()
        # L'utente ha rifiutato (return_value=False): il check costoso non parte.
        self.app._deleghe_controlla_canali_nuovi.assert_not_called()
        # Il merge/salvataggio e' comunque avvenuto: esito positivo.
        self.assertTrue(esito)

    @patch("fec_gui.messagebox.askyesno", return_value=True)
    @patch("fec_deleghe_sync.sincronizza")
    def test_conferma_stima_avvia_il_controllo(self, mock_sync, mock_askyesno):
        mock_sync.return_value = [
            {"cfDelegante": "CCC", "denomDelegante": "Cliente C",
            "servizi": [{"idServizio": "I31"}],
            "dataInizioDel": "01/01/2020", "dataFineDel": "01/01/2030"},
        ]
        self.app._get_creds = MagicMock(return_value=("cf", "pin", "pwd", "cfst"))
        self.app.modalita = MagicMock()
        self.app.modalita.get.return_value = "Studio - Delega Cliente"
        self.app._deleghe_controlla_canali_nuovi = MagicMock()

        esito = self.app._deleghe_sincronizza_da_portale(soglia_data="", forza_tutte=False)

        self.app._deleghe_controlla_canali_nuovi.assert_called_once_with(["CCC"])
        self.assertTrue(esito)

    @patch("fec_gui.messagebox.askyesno")
    @patch("fec_deleghe_sync.sincronizza")
    def test_nessuna_delega_nuova_non_chiede_conferma(self, mock_sync, mock_askyesno):
        # AAA e' gia' in anagrafica: nessun CF nuovo.
        mock_sync.return_value = [
            {"cfDelegante": "AAA", "denomDelegante": "Cliente A",
            "servizi": [{"idServizio": "I42"}],
            "dataInizioDel": "01/01/2020", "dataFineDel": "01/01/2035"},
        ]
        self.app._get_creds = MagicMock(return_value=("cf", "pin", "pwd", "cfst"))
        self.app.modalita = MagicMock()
        self.app.modalita.get.return_value = "Studio - Delega Cliente"
        self.app._deleghe_controlla_canali_nuovi = MagicMock()

        esito = self.app._deleghe_sincronizza_da_portale(soglia_data="", forza_tutte=False)

        mock_askyesno.assert_not_called()
        self.app._deleghe_controlla_canali_nuovi.assert_not_called()
        self.assertTrue(esito)

    @patch("fec_deleghe_sync.sincronizza")
    def test_playwright_non_disponibile_ritorna_false(self, mock_sync):
        import fec_deleghe_sync
        mock_sync.side_effect = fec_deleghe_sync.PlaywrightNonDisponibile(
            "playwright non installato")
        self.app._get_creds = MagicMock(return_value=("cf", "pin", "pwd", "cfst"))
        self.app.modalita = MagicMock()
        self.app.modalita.get.return_value = "Studio - Delega Cliente"
        self.app._deleghe_controlla_canali_nuovi = MagicMock()

        esito = self.app._deleghe_sincronizza_da_portale(soglia_data="", forza_tutte=False)

        self.assertFalse(esito)
        # Nessun merge/salvataggio, nessun controllo canali: e' tornata subito.
        self.app._deleghe_controlla_canali_nuovi.assert_not_called()

    @patch("fec_deleghe_sync.sincronizza")
    def test_login_fallito_ritorna_false(self, mock_sync):
        from ade_auth import AuthError
        mock_sync.side_effect = AuthError("login", "credenziali non valide")
        self.app._get_creds = MagicMock(return_value=("cf", "pin", "pwd", "cfst"))
        self.app.modalita = MagicMock()
        self.app.modalita.get.return_value = "Studio - Delega Cliente"
        self.app._deleghe_controlla_canali_nuovi = MagicMock()

        esito = self.app._deleghe_sincronizza_da_portale(soglia_data="", forza_tutte=False)

        self.assertFalse(esito)
        self.app._deleghe_controlla_canali_nuovi.assert_not_called()
        self.root.update()
        self.assertEqual(self.app.stato_var.get(), "Accesso non riuscito.")

    @patch("fec_deleghe_sync.sincronizza")
    def test_la_barra_segue_il_collegamento(self, mock_sync):
        visti = []

        def sincronizza(creds, log):
            log("Invio le credenziali al login telematico AdE...")
            self.root.update()
            visti.append(self.app.stato_var.get())
            return [{"cfDelegante": "AAA", "denomDelegante": "Cliente A",
                     "servizi": [{"idServizio": "I42"}],
                     "dataInizioDel": "01/01/2020", "dataFineDel": "01/01/2030"}]
        mock_sync.side_effect = sincronizza
        self.app._get_creds = MagicMock(return_value=("cf", "pin", "pwd", "cfst"))

        self.app._deleghe_sincronizza_da_portale(soglia_data="", forza_tutte=False)

        self.assertEqual(visti, ["Accesso in corso..."])
        self.root.update()
        self.assertEqual(self.app.stato_var.get(), "Deleghe aggiornate: 0 nuove, 1 già note.")

    @patch("fec_deleghe_sync.sincronizza")
    def test_portale_che_rifiuta_ritorna_false_e_lo_dice(self, mock_sync):
        import fec_deleghe_sync
        mock_sync.side_effect = fec_deleghe_sync.SincronizzazioneBloccata("HTTP 403")
        self.app._get_creds = MagicMock(return_value=("cf", "pin", "pwd", "cfst"))
        self.app._mostra_errore = MagicMock()

        esito = self.app._deleghe_sincronizza_da_portale(soglia_data="", forza_tutte=False)

        self.assertFalse(esito)
        self.root.update()
        self.assertEqual(self.app.stato_var.get(), "Sincronizzazione delle deleghe non riuscita.")
        self.app._mostra_errore.assert_called_once()

    @patch("fec_deleghe_sync.sincronizza", side_effect=RuntimeError("imprevisto"))
    def test_errore_imprevisto_aggiorna_la_barra_e_rilancia(self, mock_sync):
        self.app._get_creds = MagicMock(return_value=("cf", "pin", "pwd", "cfst"))
        with self.assertRaises(RuntimeError):
            self.app._deleghe_sincronizza_da_portale(soglia_data="", forza_tutte=False)
        self.root.update()
        self.assertEqual(self.app.stato_var.get(), "Sincronizzazione delle deleghe non riuscita.")

    @patch("fec_deleghe_sync.sincronizza", return_value=[])
    def test_elenco_vuoto_non_fa_avanzare_la_data(self, mock_sync):
        self.app._get_creds = MagicMock(return_value=("cf", "pin", "pwd", "cfst"))
        self.app._deleghe_controlla_canali_nuovi = MagicMock()

        esito = self.app._deleghe_sincronizza_da_portale(soglia_data="", forza_tutte=False)

        self.assertFalse(esito)
        self.app._deleghe.save_deleghe.assert_not_called()
        self.root.update()
        self.assertEqual(self.app.stato_var.get(),
                         "Il portale ha restituito un elenco di deleghe vuoto.")


if __name__ == "__main__":
    unittest.main()
