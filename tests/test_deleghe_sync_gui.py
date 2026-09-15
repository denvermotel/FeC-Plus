#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test di FecGui._deleghe_controlla_canali_nuovi, in isolamento dal resto
della GUI (stesso approccio di test_nastro.py/test_progresso.py)."""

import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

import fec_download
import fec_gui


def _tk_disponibile() -> bool:
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(_tk_disponibile(), "richiede un display Tk")
class TestDelegheControllaCanaliNuovi(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = fec_gui.FecGui(self.root)
        # Mai toccare fec_deleghe.json reale: mock esplicito, come richiesto
        # dalle regole del progetto per ogni test che arriva a save_deleghe.
        self._patch_save = patch.object(self.app._deleghe, "save_deleghe")
        self._patch_save.start()
        # In produzione self.control viene creato dal chiamante (il dialogo di
        # sincronizzazione da portale, sul thread Tk) prima di lanciare il
        # worker, come per le altre operazioni in-process con pausa/interrompi;
        # qui lo simuliamo direttamente.
        self.app.control = fec_download.Controllo()
        self.app.deleghe_rows = [
            {"codice_fiscale": "AAA", "denominazione": "Cliente A",
            "partita_iva": "", "data_fine_delega": "", "conservazione": False,
            "codice_destinatario": "", "pec": "", "canale_massivo": "",
            "etichetta1": "", "etichetta2": ""},
        ]

    def tearDown(self):
        self._patch_save.stop()
        self.root.destroy()

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


@unittest.skipUnless(_tk_disponibile(), "richiede un display Tk")
class TestDelegheSincronizzaDaPortale(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = fec_gui.FecGui(self.root)
        self._patch_save = patch.object(self.app._deleghe, "save_deleghe")
        self._patch_save.start()
        self.app.deleghe_rows = [
            {"codice_fiscale": "AAA", "denominazione": "Cliente A",
            "partita_iva": "", "data_fine_delega": "", "conservazione": False,
            "codice_destinatario": "", "pec": "", "canale_massivo": "",
            "etichetta1": "", "etichetta2": ""},
        ]

    def tearDown(self):
        self._patch_save.stop()
        self.root.destroy()

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


if __name__ == "__main__":
    unittest.main()
