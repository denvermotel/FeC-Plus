#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test di fec_deleghe.merge_many_con_nuovi."""

import unittest

import fec_deleghe as d


class TestMergeManyConNuovi(unittest.TestCase):
    def test_cf_nuovo_riportato(self):
        rows = [d._norm_row({"codice_fiscale": "AAA"})]
        rows, nuovi = d.merge_many_con_nuovi(
            rows, [{"codice_fiscale": "BBB", "data_fine_delega": "01/01/2030"}])
        self.assertEqual(nuovi, ["BBB"])
        self.assertEqual({r["codice_fiscale"] for r in rows}, {"AAA", "BBB"})

    def test_cf_gia_presente_non_riportato_come_nuovo(self):
        rows = [d._norm_row({"codice_fiscale": "AAA",
                             "data_fine_delega": "01/01/2025"})]
        rows, nuovi = d.merge_many_con_nuovi(
            rows, [{"codice_fiscale": "AAA", "data_fine_delega": "01/01/2030"}])
        self.assertEqual(nuovi, [])
        # merge_many_con_nuovi deve comunque aggiornare la scadenza (stessa
        # regola di upsert/merge_many).
        riga = next(r for r in rows if r["codice_fiscale"] == "AAA")
        self.assertEqual(riga["data_fine_delega"], "01/01/2030")

    def test_ordine_nuovi_rispetta_ordine_input(self):
        rows: list[dict] = []
        rows, nuovi = d.merge_many_con_nuovi(rows, [
            {"codice_fiscale": "CCC"},
            {"codice_fiscale": "AAA"},
            {"codice_fiscale": "BBB"},
        ])
        self.assertEqual(nuovi, ["CCC", "AAA", "BBB"])

    def test_cf_vuoto_non_riportato_come_nuovo(self):
        rows: list[dict] = []
        rows, nuovi = d.merge_many_con_nuovi(rows, [{"codice_fiscale": ""}])
        self.assertEqual(nuovi, [])


if __name__ == "__main__":
    unittest.main()
