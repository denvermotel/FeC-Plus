#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""Lettura delle ritenute d'acconto (DatiRitenuta) dal file della fattura."""

import base64
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fec_ritenuta as rit

_TESTA = ('<?xml version="1.0" encoding="UTF-8"?>'
          '<p:FatturaElettronica versione="FPR12" '
          'xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2">'
          '<FatturaElettronicaBody><DatiGenerali><DatiGeneraliDocumento>'
          '<TipoDocumento>TD06</TipoDocumento><Numero>12</Numero>')
_CODA = ('</DatiGeneraliDocumento></DatiGenerali></FatturaElettronicaBody>'
         '</p:FatturaElettronica>')


def _ritenuta(tipo="RT01", importo="200.00", aliquota="20.00", causale="A"):
    return (f"<DatiRitenuta><TipoRitenuta>{tipo}</TipoRitenuta>"
            f"<ImportoRitenuta>{importo}</ImportoRitenuta>"
            f"<AliquotaRitenuta>{aliquota}</AliquotaRitenuta>"
            f"<CausalePagamento>{causale}</CausalePagamento></DatiRitenuta>")


def _xml(*blocchi) -> bytes:
    return (_TESTA + "".join(blocchi) + _CODA).encode("utf-8")


class TestLeggiRitenute(unittest.TestCase):

    def test_parcella_con_ritenuta(self):
        r = rit.leggi_ritenute(_xml(_ritenuta()))
        self.assertEqual(r, [rit.Ritenuta("RT01", 20.0, 200.0, "A")])

    def test_fattura_senza_ritenuta(self):
        self.assertEqual(rit.leggi_ritenute(_xml()), [])

    def test_piu_ritenute(self):
        r = rit.leggi_ritenute(_xml(_ritenuta(), _ritenuta("RT04", "8.00", "4.00", "")))
        self.assertEqual([x.tipo for x in r], ["RT01", "RT04"])
        self.assertEqual(r[1].causale, "")

    def test_xml_non_valido_ritorna_none(self):
        self.assertIsNone(rit.leggi_ritenute(b"<FatturaElettronica><non chiusa"))
        self.assertIsNone(rit.leggi_ritenute(b""))

    def test_bom_iniziale(self):
        self.assertEqual(len(rit.leggi_ritenute(b"\xef\xbb\xbf" + _xml(_ritenuta()))), 1)

    def test_importo_non_numerico_resta_none(self):
        r = rit.leggi_ritenute(_xml(_ritenuta(importo="boh")))
        self.assertIsNone(r[0].importo)

    def test_codifica_sconosciuta_ritorna_none(self):
        self.assertIsNone(rit.leggi_ritenute(
            b'<?xml version="1.0" encoding="x-inesistente"?><a/>'))

    def test_spazi_e_a_capo_prima_della_dichiarazione(self):
        self.assertEqual(len(rit.leggi_ritenute(b"\r\n  " + _xml(_ritenuta()))), 1)
        self.assertEqual(len(rit.leggi_ritenute(b"\xef\xbb\xbf\r\n" + _xml(_ritenuta()))), 1)

    def test_utf16_con_bom(self):
        testo = _xml(_ritenuta()).decode("utf-8").replace('encoding="UTF-8"', 'encoding="UTF-16"')
        self.assertEqual(len(rit.leggi_ritenute(testo.encode("utf-16"))), 1)

    def test_valori_non_finiti_scartati(self):
        r = rit.leggi_ritenute(_xml(_ritenuta(importo="nan", aliquota="inf")))
        self.assertEqual((r[0].importo, r[0].aliquota), (None, None))

    def test_lotto_con_numero_prende_solo_la_sua_fattura(self):
        corpo = ("<FatturaElettronicaBody><DatiGenerali><DatiGeneraliDocumento>"
                 "<Numero>{n}</Numero>{r}</DatiGeneraliDocumento></DatiGenerali>"
                 "</FatturaElettronicaBody>")
        lotto = ('<?xml version="1.0"?><p:FatturaElettronica xmlns:p="urn:x">'
                 + corpo.format(n="1", r=_ritenuta(importo="100.00"))
                 + corpo.format(n="2", r=_ritenuta(importo="50.00"))
                 + corpo.format(n="3", r="") + "</p:FatturaElettronica>").encode()
        self.assertEqual([x.importo for x in rit.leggi_ritenute(lotto)], [100.0, 50.0])
        self.assertEqual([x.importo for x in rit.leggi_ritenute(lotto, numero="2")], [50.0])
        self.assertEqual(rit.leggi_ritenute(lotto, numero="3"), [])
        # numero non trovato nel lotto: meglio tutte che nessuna
        self.assertEqual(len(rit.leggi_ritenute(lotto, numero="99")), 2)

    def test_fattura_singola_ignora_il_numero(self):
        # Una sola fattura nel file: il numero dell'elenco può avere un formato
        # diverso da quello dell'XML, e non serve a scegliere.
        self.assertEqual(len(rit.leggi_ritenute(_xml(_ritenuta()), numero="A-12")), 1)

    def test_riepilogo(self):
        r = [rit.Ritenuta("RT01", 20.0, 200.0, "A"), rit.Ritenuta("RT04", 4.0, 8.0, "")]
        self.assertEqual(rit.riepilogo(r), ("RT01, RT04", "20, 4", 208.0))
        self.assertEqual(rit.riepilogo([]), ("", "", None))


class TestP7m(unittest.TestCase):

    def setUp(self):
        try:
            from asn1crypto import cms
        except ImportError:
            self.skipTest("asn1crypto non installato")
        self.cms = cms

    def _busta(self, contenuto: bytes) -> bytes:
        cms = self.cms
        firmati = cms.SignedData({
            "version": "v1", "digest_algorithms": [],
            "encap_content_info": {"content_type": "data", "content": contenuto},
            "signer_infos": []})
        return cms.ContentInfo({"content_type": "signed_data", "content": firmati}).dump()

    def test_p7m_binario(self):
        r = rit.leggi_ritenute(self._busta(_xml(_ritenuta())))
        self.assertEqual([x.tipo for x in r], ["RT01"])

    def test_p7m_in_base64(self):
        r = rit.leggi_ritenute(base64.b64encode(self._busta(_xml(_ritenuta()))))
        self.assertEqual([x.tipo for x in r], ["RT01"])

    def test_p7m_pem(self):
        pem = (b"-----BEGIN PKCS7-----\n"
               + base64.encodebytes(self._busta(_xml(_ritenuta())))
               + b"-----END PKCS7-----\n")
        self.assertEqual([x.tipo for x in rit.leggi_ritenute(pem)], ["RT01"])

    def test_p7m_illeggibile_ritorna_none(self):
        self.assertIsNone(rit.leggi_ritenute(b"\x30\x82\x00\x10non una busta"))


if __name__ == "__main__":
    unittest.main()
