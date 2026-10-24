#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""La finestra esegue un'operazione su più soggetti con un solo accesso."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_download
import fec_queue
from ade_auth import AuthError
from fec_selettore import Soggetto
from _appgui import AppGuiCase

ROSSI = Soggetto("Rossi Mario", "RSSMRA80A01H501U", "01234567890")
VERDI = Soggetto("Verdi Luigi", "VRDLGI70B02F205X", "")


def _res(nome):
    return SimpleNamespace(piva="", backend="requests", denominazione=nome)


class TestEseguiPerSoggetti(AppGuiCase):

    def setUp(self):
        super().setUp()
        # Il worker gira nel thread di Tk: nessun thread, i popup si registrano.
        self.app._run_inprocess = lambda fn: fn(lambda _t: None)
        self.errori = []
        self.app._mostra_errore = lambda titolo, testo: self.errori.append((titolo, testo))
        self.autentica = patch("ade_auth.autentica",
                               side_effect=lambda *a, **k: _res("login")).start()
        self.cambio = patch("ade_auth.seleziona_utenza",
                            side_effect=lambda auth, creds, **k: _res(creds.cf_cliente)).start()
        self.chiamate = []

    def _esegui(self, soggetti, operazione=None, **kw):
        def op(res, s, log, fq, ctrl, prog):
            self.chiamate.append((s.cf, res.denominazione, prog))
            return operazione(res, s) if operazione else None
        self.app._esegui_per_soggetti(soggetti, 1, "Prova", op, **kw)
        self.root.update()

    def test_la_barra_segue_login_e_cambio_utenza(self):
        import fec_gui

        def login(*a, log=print, **k):
            log("Invio le credenziali al login telematico AdE...")
            log("Configuro l'utenza di lavoro...")
            return _res("login")
        self.autentica.side_effect = login
        messaggi = []
        with patch.object(fec_gui.ProgressoGUI, "messaggio",
                          lambda _self, testo: messaggi.append(testo)):
            self._esegui([ROSSI, VERDI])
        self.assertEqual(messaggi[:4], ["Collegamento al portale dell'Agenzia...",
                                        "Accesso in corso...",
                                        "Scelta dell'utenza di lavoro...",
                                        "Accesso riuscito, avvio l'operazione..."])
        self.assertIn("Cambio utenza: Verdi Luigi...", messaggi)

    def test_stati_legati_a_righe_di_log_reali(self):
        # Se ade_auth o fec_deleghe_sync cambiano il testo del log, lo stato sparirebbe
        # in silenzio: ogni prefisso deve esistere nel sorgente.
        import fec_gui
        radice = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sorgente = ""
        for nome in ("ade_auth.py", "fec_deleghe_sync.py"):
            with open(os.path.join(radice, nome), encoding="utf-8") as fh:
                sorgente += fh.read()
        for prefisso, _stato in fec_gui.STATI_DA_LOG:
            self.assertIn(prefisso, sorgente)
        self.assertEqual(fec_gui.stato_da_log("  Login riuscito (cookie SSO ottenuti)."),
                         "Accesso riuscito, preparo la sessione...")
        self.assertIsNone(fec_gui.stato_da_log("Scarico IT01234567890_00001.xml"))

    def test_un_soggetto_un_solo_login(self):
        self._esegui([ROSSI])
        self.assertEqual(self.autentica.call_count, 1)
        self.cambio.assert_not_called()
        self.assertEqual([c[:2] for c in self.chiamate], [(ROSSI.cf, "login")])
        self.assertEqual(self.errori, [])

    def test_un_soggetto_riceve_il_progresso_della_finestra(self):
        self._esegui([ROSSI])
        self.assertIs(self.chiamate[0][2], self.app.progresso)

    def test_due_soggetti_login_e_cambio_utenza(self):
        self._esegui([ROSSI, VERDI])
        self.assertEqual(self.autentica.call_count, 1)
        self.assertEqual(self.cambio.call_count, 1)
        self.assertEqual([c[:2] for c in self.chiamate],
                         [(ROSSI.cf, "login"), (VERDI.cf, VERDI.cf)])
        self.assertIsInstance(self.chiamate[1][2], fec_queue.ProgressoPrefissato)
        self.assertEqual(self.errori, [])

    def test_accesso_fallito_con_un_soggetto_stesso_messaggio_di_prima(self):
        self.autentica.side_effect = AuthError("password", "credenziali errate")
        self._esegui([ROSSI])
        self.assertEqual(self.errori, [(
            "Accesso non riuscito",
            "Login fallito allo step «password».\n\ncredenziali errate")])
        self.assertEqual(self.chiamate, [])

    def test_operazione_fallita_con_un_soggetto_stesso_messaggio_di_prima(self):
        def operazione(res, s):
            raise fec_download.DownloadError("elenco non ottenuto")
        self._esegui([ROSSI], operazione)
        self.assertEqual(self.errori, [("Prova: operazione non riuscita",
                                        "elenco non ottenuto")])

    def test_errore_imprevisto_con_un_soggetto_stesso_popup_di_prima(self):
        def operazione(res, s):
            raise OSError("disco pieno")
        self._esegui([ROSSI], operazione)
        self.assertEqual(self.errori, [("Errore imprevisto", "disco pieno")])

    def test_errore_imprevisto_all_accesso_stesso_popup_di_prima(self):
        self.autentica.side_effect = OSError("rete")
        self._esegui([ROSSI])
        self.assertEqual(self.errori, [("Errore imprevisto", "rete")])

    def test_credenziali_errate_con_piu_soggetti_un_solo_messaggio_di_accesso(self):
        self.autentica.side_effect = AuthError("login", "credenziali errate")
        self._esegui([ROSSI, VERDI])
        self.assertEqual(self.autentica.call_count, 1)
        self.assertEqual(self.errori, [(
            "Accesso non riuscito",
            "Login fallito allo step «login».\n\ncredenziali errate")])

    def test_popup_di_fine_letto_al_lancio(self):
        # La preferenza vale com'era al lancio: il worker non legge variabili Tk.
        partiti = []
        self.app._run_inprocess = partiti.append
        self.app.popup_fine_task.set(True)
        self.app._esegui_per_soggetti([ROSSI], 1, "Prova", lambda *a: None)
        self.app.popup_fine_task.set(False)
        with patch.object(self.app, "_conferma_completato_da_nastro") as conferma:
            partiti[0](lambda _t: None)
            self.root.update()
        conferma.assert_called_once()

    def test_una_tacca_per_soggetto_se_richiesto(self):
        self.cambio.side_effect = AuthError("utenza", "delega non valida")
        self._esegui([ROSSI, VERDI], conta_soggetti=True)
        self.app.progresso.svuota()
        segmenti = self.app.modello_nastro.segmenti
        self.assertEqual([s.etichetta for s in segmenti], ["Rossi Mario", "Verdi Luigi"])
        self.assertEqual([s.esiti for s in segmenti],
                         [[fec_download.ESITO_OK], [fec_download.ESITO_ERRORE]])

    def test_secondo_soggetto_fallito_un_solo_popup_con_il_nome(self):
        self.cambio.side_effect = AuthError("utenza", "delega non valida")
        self._esegui([ROSSI, VERDI])
        self.assertEqual(len(self.errori), 1)
        titolo, testo = self.errori[0]
        self.assertIn("1 soggetto non completato", titolo)
        self.assertIn("Verdi Luigi", testo)
        self.assertIn("delega non valida", testo)
        self.assertEqual([c[0] for c in self.chiamate], [ROSSI.cf])

    def test_fine_gira_solo_se_qualcuno_e_riuscito(self):
        visti = []
        self._esegui([ROSSI, VERDI], fine=visti.append)
        self.assertEqual(len(visti), 1)
        self.assertEqual([e.ok for e in visti[0]], [True, True])
        self.autentica.side_effect = AuthError("password", "no")
        visti.clear()
        self._esegui([ROSSI], fine=visti.append)
        self.assertEqual(visti, [])

    def test_interruzione_dell_utente_non_apre_popup(self):
        def operazione(res, s):
            raise fec_download.DownloadAnnullato("Download interrotto dall'utente.")
        self._esegui([ROSSI, VERDI], operazione)
        self.assertEqual(self.errori, [])
        self.assertEqual(len(self.chiamate), 1)

    def _con_anagrafica(self, soggetti):
        self.app.deleghe_no_update_var.set(False)
        righe = []
        self.app._applica_aggiornamento_delega = lambda *a, **k: righe.append(a)
        with patch("fec_anagrafica.recupera", return_value={}) as recupera:
            self._esegui(soggetti)
        return recupera, righe

    def test_piu_soggetti_non_aggiorna_l_anagrafica(self):
        recupera, righe = self._con_anagrafica([ROSSI, VERDI])
        recupera.assert_not_called()
        self.assertEqual(righe, [])
        self.assertEqual(len(self.chiamate), 2)

    def test_un_soggetto_aggiorna_l_anagrafica(self):
        recupera, righe = self._con_anagrafica([ROSSI])
        recupera.assert_called_once()
        self.assertEqual(len(righe), 1)

    def test_firma_di_prima_ancora_valida(self):
        viste = []
        self.app._esegui_in_process(
            "RSSMRA80A01H501U", "01234567890", 1, "Vecchia",
            lambda res, log, fq, ctrl, prog: viste.append((res.denominazione, fq, prog)))
        self.root.update()
        self.assertEqual(viste, [("login", fec_queue, self.app.progresso)])


if __name__ == "__main__":
    unittest.main()
