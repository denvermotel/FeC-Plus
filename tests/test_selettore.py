#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Selettore dei soggetti: logica di ricerca e widget a scelta multipla."""

import os
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_selettore as sel

ROWS = [
    {"codice_fiscale": "RSSMRA80A01H501U", "partita_iva": "01234567890",
     "denominazione": "Rossi Mario"},
    {"codice_fiscale": "VRDLGI70B02F205X", "partita_iva": "", "denominazione": "Verdi Luigi"},
    {"codice_fiscale": "BNCGNN60C03L219Z", "partita_iva": "09876543210",
     "denominazione": "Rossi Mario"},
    {"codice_fiscale": "", "partita_iva": "", "denominazione": "Senza codice"},
]


def _tk_disponibile() -> bool:
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


class TestLogica(unittest.TestCase):

    def test_opzioni_in_ordine_e_omonimi_distinti(self):
        voci = sel.opzioni_soggetti(ROWS)
        self.assertEqual([c for _, c in voci],
                         ["BNCGNN60C03L219Z", "RSSMRA80A01H501U", "VRDLGI70B02F205X"])
        self.assertEqual(voci[0][0], "Rossi Mario - BNCGNN60C03L219Z")
        self.assertEqual(voci[2][0], "Verdi Luigi")

    def test_riga_senza_identificativo_esclusa(self):
        self.assertNotIn("Senza codice", [t for t, _ in sel.opzioni_soggetti(ROWS)])

    def test_piva_per_cf(self):
        self.assertEqual(sel.piva_per_cf(ROWS)["RSSMRA80A01H501U"], "01234567890")
        self.assertEqual(sel.piva_per_cf(ROWS)["VRDLGI70B02F205X"], "")

    def test_filtra_per_nome_e_per_cf(self):
        opz = sel.opzioni_soggetti(ROWS)
        self.assertEqual(len(sel.filtra_opzioni(opz, "rossi")), 2)
        self.assertEqual(sel.filtra_opzioni(opz, "vrdlgi")[0][1], "VRDLGI70B02F205X")
        self.assertEqual(len(sel.filtra_opzioni(opz, "")), 3)

    def test_normalizza_cf(self):
        self.assertEqual(sel.normalizza_cf(" rssmra80a01h501u "), "RSSMRA80A01H501U")
        self.assertEqual(sel.normalizza_cf("01234567890"), "01234567890")
        with self.assertRaises(ValueError):
            sel.normalizza_cf("123")


@unittest.skipUnless(_tk_disponibile(), "richiede un display Tk")
class TestWidget(unittest.TestCase):

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.s = sel.SelettoreSoggetti(self.root, ROWS)
        self.s.pack()

    def tearDown(self):
        self.root.destroy()

    def test_informazione_deleghe(self):
        self.assertEqual(self.s.info_var.get(), "3 deleghe")

    def test_aggiungi_senza_duplicati(self):
        self.assertTrue(self.s.aggiungi("Verdi Luigi", "VRDLGI70B02F205X"))
        self.assertFalse(self.s.aggiungi("Verdi Luigi", "vrdlgi70b02f205x"))
        self.assertEqual(len(self.s.scelti), 1)

    def test_piva_dalla_delega(self):
        self.s.aggiungi("Rossi Mario", "RSSMRA80A01H501U")
        self.assertEqual(self.s.scelti[0].piva, "01234567890")

    def test_campo_piva_solo_con_un_soggetto(self):
        self.s.update_idletasks()
        self.assertFalse(self.s.piva_visibile())
        self.s.aggiungi("Rossi Mario", "RSSMRA80A01H501U")
        self.assertTrue(self.s.piva_visibile())
        self.assertEqual(self.s.piva_var.get(), "01234567890")
        self.s.aggiungi("Verdi Luigi", "VRDLGI70B02F205X")
        self.assertFalse(self.s.piva_visibile())

    def test_un_soggetto_usa_la_piva_del_campo(self):
        self.s.aggiungi("Verdi Luigi", "VRDLGI70B02F205X")
        self.s.piva_var.set(" 11111111111 ")
        self.assertEqual(self.s.soggetti()[0].piva, "11111111111")

    def test_piu_soggetti_usano_la_piva_della_delega(self):
        self.s.aggiungi("Rossi Mario", "RSSMRA80A01H501U")
        self.s.aggiungi("Verdi Luigi", "VRDLGI70B02F205X")
        self.s.piva_var.set("99999999999")
        self.assertEqual([x.piva for x in self.s.soggetti()], ["01234567890", ""])

    def test_aggiungi_tutte_e_svuota(self):
        self.s.aggiungi("Verdi Luigi", "VRDLGI70B02F205X")
        self.s.aggiungi_tutte()
        self.assertEqual(len(self.s.scelti), 3)
        self.s.svuota()
        self.assertEqual(self.s.scelti, [])

    def test_rimuovi(self):
        self.s.aggiungi_tutte()
        primo = self.s.scelti[0].cf
        self.s.rimuovi(0)
        self.assertEqual(len(self.s.scelti), 2)
        self.assertNotIn(primo, [x.cf for x in self.s.scelti])

    def test_imposta_sostituisce_la_scelta(self):
        self.s.aggiungi_tutte()
        self.s.imposta("Verdi Luigi", "VRDLGI70B02F205X")
        self.assertEqual([x.cf for x in self.s.scelti], ["VRDLGI70B02F205X"])

    def test_ricerca_esclude_i_gia_scelti(self):
        self.s.aggiungi("Verdi Luigi", "VRDLGI70B02F205X")
        self.s.nome_var.set("verdi")
        self.s._filtra()
        self.assertEqual(self.s.voci(), [])

    def test_ricerca_propone_cf_fuori_delega(self):
        self.s.nome_var.set("AAAAAA00A00A000A")
        self.s._filtra()
        self.assertEqual(self.s.voci(), ["Usa AAAAAA00A00A000A (non tra le deleghe)"])

    def test_scelta_dalla_tendina_aggiunge_e_svuota_la_ricerca(self):
        self.s.nome_var.set("verdi")
        self.s._filtra()
        self.s._scegli_indice(0)
        self.assertEqual([x.cf for x in self.s.scelti], ["VRDLGI70B02F205X"])
        self.assertEqual(self.s.nome_var.get(), "")
        self.assertFalse(self.s.aperta())

    def test_soggetti_senza_scelta_avvisa(self):
        with patch.object(sel.messagebox, "showwarning") as avviso:
            self.assertIsNone(self.s.soggetti())
        avviso.assert_called_once()

    def test_soggetti_risolve_il_testo_digitato(self):
        self.s.nome_var.set("Verdi Luigi")
        r = self.s.soggetti()
        self.assertEqual([x.cf for x in r], ["VRDLGI70B02F205X"])

    def test_soggetti_facoltativo_senza_scelta_torna_il_soggetto_vuoto(self):
        with patch.object(sel.messagebox, "showwarning") as avviso:
            r = self.s.soggetti(obbligatorio=False)
        avviso.assert_not_called()
        self.assertEqual(r, [sel.Soggetto("", "", "")])

    def test_soggetti_accetta_cf_fuori_delega(self):
        self.s.nome_var.set("AAAAAA00A00A000A")
        self.assertEqual(self.s.soggetti()[0].cf, "AAAAAA00A00A000A")

    def test_soggetti_testo_ambiguo_errore(self):
        self.s.nome_var.set("rossi")
        with patch.object(sel.messagebox, "showerror") as errore:
            self.assertIsNone(self.s.soggetti())
        errore.assert_called_once()

    def test_testo_scritto_si_aggiunge_ai_scelti(self):
        self.s.aggiungi("Rossi Mario", "RSSMRA80A01H501U")
        self.s.nome_var.set("Verdi Luigi")
        r = self.s.soggetti()
        self.assertEqual([x.cf for x in r], ["RSSMRA80A01H501U", "VRDLGI70B02F205X"])
        self.assertEqual(self.s.nome_var.get(), "")

    def test_testo_sconosciuto_con_scelti_errore(self):
        self.s.aggiungi("Rossi Mario", "RSSMRA80A01H501U")
        self.s.nome_var.set("Nessuno Qui")
        with patch.object(sel.messagebox, "showerror") as errore:
            self.assertIsNone(self.s.soggetti())
        errore.assert_called_once()
        self.assertIn("non riconosciuto", errore.call_args[0][1])

    def test_omonimi_errore_distinto(self):
        self.s.nome_var.set("Rossi Mario")
        with patch.object(sel.messagebox, "showerror") as errore:
            self.assertIsNone(self.s.soggetti())
        errore.assert_called_once_with(
            "Errore", "Più deleghe corrispondono a «Rossi Mario»: sceglila dall'elenco.")

    def test_focus_sulla_tendina_non_la_chiude(self):
        self.s.nome_var.set("verdi")
        self.s._filtra()
        self.assertTrue(self.s.aperta())
        with patch.object(self.s, "focus_get", return_value=self.s.albero):
            self.s._chiudi_se_fuori()
        self.assertTrue(self.s.aperta())
        with patch.object(self.s, "focus_get", return_value=self.root):
            self.s._chiudi_se_fuori()
        self.assertFalse(self.s.aperta())

    def test_contatore_al_singolare(self):
        self.s.aggiorna(ROWS[:1])
        self.s.nome_var.set("rossi")
        self.s._filtra()
        self.assertEqual(self.s.contatore_var.get(), "1 di 1 delega")

    def test_aggiorna_tiene_i_scelti(self):
        self.s.aggiungi("Verdi Luigi", "VRDLGI70B02F205X")
        self.s.aggiorna(ROWS[:1])
        self.assertEqual(self.s.info_var.get(), "1 delega")
        self.assertEqual(len(self.s.scelti), 1)


if __name__ == "__main__":
    unittest.main()
