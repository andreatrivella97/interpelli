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


class DatiPerLaPagina(unittest.TestCase):
    """Il controllo completo, con fonti finte: che cosa finisce nei file che la pagina e i giri successivi leggono."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        import scraper.__main__ as principale

        self.principale = principale
        self.cartella = tempfile.TemporaryDirectory()
        self.radice = Path(self.cartella.name)
        (self.radice / "scuole.yaml").write_text(
            "scuole:\n"
            "  - id: prova\n    nome: IC di prova\n    comuni: [Legnano]\n    sito: https://scuola.example/\n"
            "    fonti:\n      - {tipo: sito, url: 'https://scuola.example/interpelli/'}\n"
            "  - id: muta\n    nome: IC che non risponde\n    comuni: [Rho]\n    sito: https://muta.example/\n"
            "    fonti:\n      - {tipo: guasta, url: 'https://muta.example/interpelli/'}\n", encoding="utf-8")
        (self.radice / "criteri.yaml").write_text("ordini: [infanzia, primaria]\nore_min: 20\nmesi_fine: [6, 7, 8]\n",
                                                  encoding="utf-8")

        def guasta(*_):
            raise ErroreRete("ConnectTimeout da muta.example")

        avviso = dal_sito("Interpello primaria posto comune 24 ore fino al 30/06/2027", "https://scuola.example/avviso-1/")
        avviso.pubblicato = None
        fonti = {"sito": lambda *_: [avviso], "guasta": guasta}
        for nome, finto in (("fonti_disponibili", lambda: fonti), ("Rete", lambda **_: mock.Mock(richieste=0)),
                            ("Lettore", lambda *_, **__: LettoreFinto("Si cerca un docente. Candidature entro il 31/12/2030."))):
            sostituto = mock.patch.object(principale, nome, finto)
            sostituto.start()
            self.addCleanup(sostituto.stop)
        self.addCleanup(self.cartella.cleanup)

    def dati(self):
        import json
        return json.loads((self.radice / "docs" / "dati.json").read_text(encoding="utf-8"))

    def giro(self, *argomenti):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):          # il riepilogo del controllo qui non serve
            return self.principale.main(["--radice", str(self.radice), *argomenti])

    def test_che_cosa_riceve_la_pagina(self):
        self.assertEqual(self.giro(), 0)
        dati = self.dati()
        self.assertEqual(set(dati), {"generato", "criteri", "scuole", "avvisi"})
        self.assertEqual([(s["id"], s["stato"]) for s in dati["scuole"]], [("prova", "ok"), ("muta", "errore")])
        self.assertEqual(dati["scuole"][0]["pagine"], [{"nome": "Pagina sul sito", "url": "https://scuola.example/interpelli/"}])
        self.assertIsNone(dati["scuole"][1]["ultimo_ok"])
        (avviso,) = dati["avvisi"]
        for campo in ("id", "scuola", "titolo", "url", "pagina", "pubblicato", "scadenza", "chiuso", "personale", "posti",
                      "letto", "prima_vista", "iniziale", "presente"):
            self.assertIn(campo, avviso)
        self.assertEqual(avviso["scadenza"], "2030-12-31T23:59")
        self.assertEqual({k: avviso["posti"][0][k] for k in ("ordini", "tipo", "ore", "fine")},
                         {"ordini": ["primaria"], "tipo": "comune", "ore": 24, "fine": "2027-06-30"})

    def test_un_passaggio_di_recupero_senza_novita_non_riscrive_i_dati(self):
        self.giro()
        file = self.radice / "docs" / "dati.json"
        segnato = file.read_text(encoding="utf-8") + "\n"         # un segno per accorgersi se il file viene riscritto
        file.write_text(segnato, encoding="utf-8")
        self.giro("--salta-recenti", "50")                        # riprova solo la scuola che non risponde: nessuna novita'
        self.assertEqual(file.read_text(encoding="utf-8"), segnato)
        self.giro()                                               # un controllo completo invece salva sempre
        self.assertNotEqual(file.read_text(encoding="utf-8"), segnato)
        self.assertEqual(len(self.dati()["avvisi"]), 1)
