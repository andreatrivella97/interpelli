"""Prove del controllo di una scuola: che cosa succede da un giro all'altro.

Le fonti e i documenti sono finti: qui non si legge nessun sito.
"""
import unittest
from datetime import date, datetime, timedelta

from scraper.__main__ import Bilancio, controlla_scuola
from scraper.archivio import da_mostrare
from scraper.documenti import Documento
from scraper.fonti import Voce
from scraper.rete import ErroreRete

ORA = datetime(2026, 10, 2, 10, 17)
SCUOLA = {"id": "prova", "nome": "IC di prova", "sito": "https://scuola.example/",
          "fonti": [{"tipo": "portale", "url": "https://portale.example/scuola"},
                    {"tipo": "sito", "url": "https://scuola.example/interpelli/"}]}
TESTO = ("AVVISO per il conferimento di supplenza: n. 1 posto di sostegno scuola primaria "
         "24 ore settimanali fino al 30/06/2027. Candidature entro le ore 9.00 del 5 ottobre 2026.")


def dal_portale():
    return Voce(titolo="Interpello primaria SOSTEGNO ADEE -", url="https://portale.example/scuola",
                pagina="https://portale.example/scuola", fonte="axios", chiave="axios:41",
                pubblicato=date(2026, 10, 1), scadenza=datetime(2026, 10, 5, 9, 0),
                documento="https://portale.example/doc/41")


def dal_sito(titolo="Interpello primaria SOSTEGNO ADEE", indirizzo="https://scuola.example/interpello-primaria-sostegno/"):
    return Voce(titolo=titolo, url=indirizzo, pagina="https://scuola.example/interpelli/", fonte="pagina",
                chiave=indirizzo, pubblicato=date(2026, 10, 1))


class LettoreFinto:
    def __init__(self, testo=TESTO):
        self.testo, self.aperti = testo, []

    def leggi(self, url, **_):
        self.aperti.append(url)
        return Documento(testo=self.testo, come="testo")


def controlla(lettori, prima=None, memoria=None, ora=ORA, lettore=None):
    return controlla_scuola(SCUOLA, prima or {}, memoria or {}, lettori, None, lettore or LettoreFinto(), Bilancio(20), ora)


class DaUnGiroAllAltro(unittest.TestCase):
    def test_lo_stesso_avviso_da_due_fonti_resta_uno(self):
        lettori = {"portale": lambda *_: [dal_portale()], "sito": lambda *_: [dal_sito()]}
        lettore = LettoreFinto()
        avvisi, salute = controlla(lettori, lettore=lettore)
        self.assertEqual(len(avvisi), 1)
        self.assertEqual(lettore.aperti, ["https://portale.example/doc/41"])      # il documento si apre una volta sola
        # al giro dopo non deve nascere un doppione, ne' si deve riaprire il documento
        avvisi, salute = controlla(lettori, avvisi, salute["memoria"], ORA + timedelta(hours=1), lettore)
        self.assertEqual(len(avvisi), 1)
        self.assertEqual(len(lettore.aperti), 1)
        record = next(iter(avvisi.values()))
        self.assertEqual(sorted(record["fonti"]), ["axios", "pagina"])
        self.assertTrue(record["iniziale"])                                         # c'era gia' al primo controllo
        self.assertEqual(record["scadenza"], "2026-10-05T09:00")
        self.assertEqual([(p["ore"], p["fine"]) for p in record["posti"]], [(24, "2027-06-30")])
        self.assertEqual(salute["stato"], "ok")

    def test_un_avviso_comparso_dopo_e_nuovo(self):
        avvisi, salute = controlla({"portale": lambda *_: [], "sito": lambda *_: [dal_sito()]})
        dopo = {"portale": lambda *_: [], "sito": lambda *_: [dal_sito(), dal_sito(
            "Interpello infanzia posto comune 25 ore fino al 30/06/2027", "https://scuola.example/interpello-infanzia/")]}
        avvisi, salute = controlla(dopo, avvisi, salute["memoria"], ORA + timedelta(hours=1))
        self.assertEqual(sorted(r["iniziale"] for r in avvisi.values()), [False, True])
        nuovo = next(r for r in avvisi.values() if not r["iniziale"])
        self.assertEqual(nuovo["prima_vista"], "2026-10-02T11:17")

    def test_una_fonte_che_non_risponde_non_cancella_i_suoi_avvisi(self):
        avvisi, salute = controlla({"portale": lambda *_: [], "sito": lambda *_: [dal_sito()]})

        def guasto(*_):
            raise ErroreRete("ConnectTimeout da scuola.example")

        avvisi, salute = controlla({"portale": lambda *_: [], "sito": guasto}, avvisi, salute["memoria"],
                                   ORA + timedelta(hours=1))
        record = next(iter(avvisi.values()))
        self.assertTrue(record["presente"])
        self.assertEqual(salute["stato"], "parziale")
        self.assertEqual(salute["memoria"]["ultimo_ok"], "2026-10-02T10:17")          # l'ultima lettura completa resta quella

    def test_un_avviso_tolto_dal_sito_non_e_piu_presente(self):
        avvisi, salute = controlla({"portale": lambda *_: [], "sito": lambda *_: [dal_sito()]})
        avvisi, salute = controlla({"portale": lambda *_: [], "sito": lambda *_: []}, avvisi, salute["memoria"],
                                   ORA + timedelta(hours=1))
        self.assertFalse(next(iter(avvisi.values()))["presente"])

    def test_l_esito_di_una_procedura_non_va_in_pagina(self):
        esito = LettoreFinto("LA DIRIGENTE SCOLASTICA RENDE NOTO gli esiti della procedura di interpello in oggetto. "
                             "I docenti in elenco sono invitati alla presa di servizio il giorno 28 settembre 2026.")
        avvisi, _ = controlla({"portale": lambda *_: [], "sito": lambda *_: [dal_sito(
            "Interpello per supplenza scuola primaria - decreto", "https://scuola.example/decreto/")]}, lettore=esito)
        record = next(iter(avvisi.values()))
        self.assertTrue(record.get("escluso"))
        self.assertEqual(record["posti"], [])
        self.assertFalse(da_mostrare(record, ORA))

    def test_un_avviso_aperto_si_mostra_e_dopo_una_settimana_dalla_scadenza_no(self):
        avvisi, _ = controlla({"portale": lambda *_: [dal_portale()], "sito": lambda *_: []})
        record = next(iter(avvisi.values()))
        self.assertTrue(da_mostrare(record, ORA))
        self.assertTrue(da_mostrare(record, datetime(2026, 10, 9, 12, 0)))            # scaduto da quattro giorni
        self.assertFalse(da_mostrare(record, datetime(2026, 10, 13, 12, 0)))          # scaduto da piu' di una settimana


if __name__ == "__main__":
    unittest.main()
