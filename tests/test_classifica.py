"""Prove delle regole di lettura sugli avvisi veri raccolti durante la messa a punto.

Si lanciano con:  python -m unittest discover -s tests
"""
import unittest
from datetime import date, datetime
from pathlib import Path

from scraper.classifica import analizza, sembra_avviso, valuta

OGGI = date(2026, 10, 2)
CRITERI = {"ordini": ["infanzia", "primaria"], "ore_min": 20, "mesi_fine": [6, 7, 8]}
TESTI = Path(__file__).parent / "fixtures" / "testi"


def leggi(nome, titolo, pubblicato=None):
    return analizza(titolo, (TESTI / f"{nome}.txt").read_text(encoding="utf-8"), oggi=OGGI, pubblicato=pubblicato)


def tipi(analisi):
    return [p.tipo for p in analisi.posti]


def esito(analisi):
    return valuta(analisi, CRITERI, OGGI)[0]


def posti(analisi):
    return [(p.ore, p.fine.isoformat() if p.fine else None) for p in analisi.posti]


class AvvisiInPdf(unittest.TestCase):
    def test_elenco_di_posti_con_frasi_di_rito(self):
        # "fino al termine dell'attivita' didattica ... al 30 giugno 2027" e' un posto solo; la frase
        # "lasciare tale supplenza per accettare una supplenza fino al 31/08/2027" non e' un posto
        a = leggi("consolemarcello_sostegno", "Interpello primaria SOSTEGNO ADEE", date(2026, 10, 1))
        self.assertEqual(posti(a), [(24, "2027-06-30"), (24, "2026-11-14"), (24, "2026-10-18")])
        self.assertEqual(tipi(a), ["sostegno", "comune", "comune"])
        self.assertEqual(a.scadenza, datetime(2026, 10, 5, 9, 0))
        self.assertEqual(a.pubblicato, date(2026, 10, 1))     # non la data della circolare ministeriale citata
        self.assertEqual(esito(a), "corrisponde")

    def test_supplenza_annuale_al_31_agosto(self):
        a = leggi("consolemarcello_primaria", "Interpello per supplenza- scuola primaria", date(2026, 9, 23))
        self.assertEqual(posti(a), [(24, "2027-06-30"), (24, "2026-11-14"), (24, "2027-08-31"), (24, "2027-06-30")])
        self.assertEqual(tipi(a), ["comune", "comune", "sostegno", "sostegno"])
        self.assertEqual(a.scadenza, datetime(2026, 9, 25, 10, 0))
        self.assertEqual(esito(a), "corrisponde")

    def test_tabella_con_le_righe_mescolate(self):
        # il PDF mette in disordine le celle: ore e date vanno abbinate al codice piu' vicino
        a = leggi("cuggiono", "Circolare 297 Interpelli", date(2026, 9, 24))
        self.assertEqual(posti(a), [(18, "2026-10-04"), (24, "2027-06-30"), (22, "2027-06-30"), (25, "2027-11-03"),
                                    (25, "2026-09-30")])
        self.assertEqual(a.posti[1].tipo, "sostegno")
        self.assertIn("primaria", a.posti[1].ordini)
        self.assertEqual((a.posti[2].ordini, a.posti[2].tipo), (["infanzia"], "comune"))
        self.assertEqual(a.scadenza, datetime(2026, 9, 25, 15, 30))
        self.assertEqual(esito(a), "corrisponde")

    def test_data_sbagliata_nella_tabella(self):
        # la tabella dice 14/09/2026 ma l'avviso e' del 2 ottobre: vale il "14 ottobre" scritto nel titolo
        a = leggi("carducci_breve", "Interpello per supplenza breve ore 24 fino al 14 ottobre 2026 posto COMUNE scuola primaria",
                  date(2026, 10, 2))
        self.assertEqual(posti(a), [(24, "2026-10-14")])
        self.assertEqual(esito(a), "non_corrisponde")

    def test_esito_di_una_procedura(self):
        a = leggi("consolemarcello_esito", "Interpello per supplenza scuola primaria Milano", date(2026, 9, 25))
        self.assertTrue(a.esito_procedura)
        self.assertFalse(leggi("consolemarcello_primaria", "Interpello per supplenza- scuola primaria").esito_procedura)

    def test_piu_posti_nella_stessa_frase(self):
        a = leggi("bustogarolfo", "Interpello n. 2 del 23-09-2026 - Posto comune.pdf")
        self.assertEqual(posti(a), [(24, "2026-10-04"), (24, "2026-11-03"), (6, "2026-10-25"), (6, "2027-06-08")])
        self.assertEqual(a.ordini, ["primaria"])
        self.assertEqual(a.scadenza, datetime(2026, 9, 24, 13, 15))
        self.assertEqual(a.pubblicato, date(2026, 9, 23))
        self.assertEqual(esito(a), "non_corrisponde")   # le 24 ore finiscono a novembre, fino a giugno ce ne sono 6

    def test_tabella_con_codice_posti_ore_scadenza(self):
        a = leggi("carducci", "Decreto_Interpello_del_05-10-2026_supplenza_PRIMARIA_ore_6_fino_al_30-06-2027.pdf")
        self.assertEqual(posti(a), [(6, "2027-06-30")])
        self.assertEqual(a.scadenza, datetime(2026, 10, 3, 14, 0))
        self.assertEqual(a.pubblicato, date(2026, 10, 2))
        self.assertEqual(esito(a), "non_corrisponde")

    def test_tabella_con_presa_di_servizio_e_scadenza(self):
        a = leggi("salici", "INTERPELLO EEEE POSTO COMUNE PRIMARIA")
        self.assertEqual(posti(a), [(24, "2026-12-22"), (5, "2026-12-22")])
        self.assertEqual(a.scadenza, datetime(2026, 9, 23, 12, 0))

    def test_ore_scritte_dopo_la_durata(self):
        a = leggi("franceschini", "AVVISO PER SELEZIONE PERSONALE DOCENTE SUPPLENTE SCUOLA PRIMARIA POSTO COMUNE (EEEE)")
        self.assertEqual(posti(a), [(24, "2026-10-06"), (17, "2027-06-30")])
        self.assertEqual(a.scadenza, datetime(2026, 9, 27, 12, 0))
        self.assertEqual(esito(a), "non_corrisponde")

    def test_orario_complessivo_settimanale(self):
        a = leggi("cerro", "A.S.2627 N.1 AVVISO INTERPELLO posto comune AAAA.docx.pdf")
        self.assertEqual(posti(a), [(25, "2026-10-23")])     # "24 ore dopo" non e' un orario settimanale
        self.assertEqual(a.ordini, ["infanzia"])
        self.assertEqual(a.scadenza, datetime(2026, 9, 25, 11, 0))

    def test_scheda_a_righe(self):
        a = leggi("grossi", "5766/U Interpello_ Primaria posto comune fino al 30/11/2026")
        self.assertEqual(posti(a), [(24, "2026-11-30")])
        self.assertEqual(a.scadenza, datetime(2026, 10, 2, 10, 0))

    def test_date_di_norme_e_requisiti_non_sono_posti(self):
        a = leggi("magnago", "INTERPELLO__infanzia_POSTO_comune fino al 30.10.pdf")
        self.assertEqual(posti(a), [(25, "2026-10-30")])     # "al 1° settembre 2024" e' un requisito d'eta'
        self.assertEqual(a.scadenza, datetime(2026, 10, 1, 12, 0))

    def test_anno_sbagliato_nell_avviso(self):
        a = leggi("villacortese", "01-_ADEE_INTERPELLO_SOSTEGNO_PRIMARIA_.pdf.pades")
        self.assertEqual(posti(a), [(None, "2027-08-31"), (None, "2027-06-30")])
        self.assertEqual(a.scadenza, datetime(2026, 9, 18, 13, 0))
        self.assertEqual(valuta(a, CRITERI, OGGI), ("da_verificare", ["ore non indicate"]))

    def test_pdf_scansionato_resta_il_titolo(self):
        a = leggi("davinci", "INTERPELLO n. 11 SUPPLENZE BREVI E FINO AL TERMINE DELLE ATTIVITA DIDATTICHE "
                             "POSTO COMUNE SCUOLA PRIMARIA Prot. n. 5341 del 16/09/2026")
        self.assertEqual(posti(a), [(None, "2027-06-30")])
        self.assertEqual(esito(a), "da_verificare")


    def test_pdf_scansionato_letto_con_ocr(self):
        a = leggi("davinci_ocr", "INTERPELLO n. 11 SUPPLENZE BREVI E FINO AL TERMINE DELLE ATTIVITA DIDATTICHE POSTO COMUNE SCUOLA PRIMARIA")
        self.assertEqual(posti(a), [(24, "2027-06-30")])
        self.assertEqual(a.scadenza, datetime(2026, 9, 17, 9, 30))
        self.assertEqual(esito(a), "corrisponde")


class SoloTitolo(unittest.TestCase):
    def caso(self, titolo, atteso, posti_attesi=None):
        a = analizza(titolo, oggi=OGGI)
        self.assertEqual(esito(a), atteso, titolo)
        if posti_attesi is not None:
            self.assertEqual(posti(a), posti_attesi, titolo)
        return a

    def test_due_posti_in_un_oggetto(self):
        self.caso("Interpello per la classe di concorso AAAA n. 25 ore dal 06.10.2026 al 30.06.2027 - "
                  "AAAA n.5 ore dal 06.10.2026 al 30.06.2027", "corrisponde", [(25, "2027-06-30"), (5, "2027-06-30")])

    def test_data_senza_anno(self):
        self.caso("Interpello n. 4 - n. 1 post EEEE - posto COMUNE primaria 24 ore al 30.06", "corrisponde", [(24, "2027-06-30")])
        self.caso("Interpello n. 5 - n. 1 posto ADEE - posto SOSTEGNO primaria 24 ore al 17.12", "non_corrisponde", [(24, "2026-12-17")])

    def test_ore_dopo_la_data(self):
        self.caso("INTERPELLO PER SELEZIONE PERSONALE n. 12 posti ADEE (SOSTEGNO) fino al 30/06/2027 ore 24 "
                  "Presso scuola primaria", "corrisponde", [(24, "2027-06-30")])

    def test_ore_prima_della_data_non_sono_un_orario(self):
        self.caso("Interpello per supplenza breve ore 24 fino al 14 ottobre 2026 posto COMUNE scuola primaria",
                  "non_corrisponde", [(24, "2026-10-14")])

    def test_nome_di_file(self):
        self.caso("INTERPELLO_N._7_POSTI_DI_SOSTEGNO_SULLA_SCUOLA_PRIMARIA_FINO_AL_30_06_27.pdf", "da_verificare", [(None, "2027-06-30")])

    def test_secondaria_e_ata_non_corrispondono(self):
        self.caso("Interpello del 15/09/2026 - classe di concorso AS2D dal 17/09/2026 al 31/12/2026", "non_corrisponde")
        self.caso('Interpello strumento musicale AI56 e AM56 del 02-10-26 -IC "BOSSI"', "non_corrisponde")
        a = self.caso("Interpello per collaboratore scolastico fino al 30/06/2027 36 ore", "non_corrisponde")
        self.assertEqual(a.personale, "ata")

    def test_dati_mancanti_vanno_verificati(self):
        self.caso("INTERPELLO PER SELEZIONE PERSONALE Classe di concorso AAAA posto comune nella Scuola dell'Infanzia", "da_verificare")
        self.caso("Interpello del 12 marzo 2026 scuola dell'infanzia posto comune 25 ore", "da_verificare", [(25, None)])

    def test_piu_posti_che_ore_dichiarate(self):
        # sette posti interi di sostegno senza ore, piu' uno spezzone da 9 ore: non si puo' escludere
        self.caso("5484/U Interpello n.1 posto INFANZIA SOSTEGNO_n.6 posti PRIMARIA SOSTEGNO_ 9h POSTO COMUNE PRIMARIA", "da_verificare")

    def test_posto_intero_e_termine_delle_lezioni(self):
        self.caso("Interpello scuola primaria posto intero fino al termine delle lezioni", "corrisponde")

    def test_fine_anno_senza_anno_e_senza_fino_al(self):
        a = analizza("INTERPELLO N. 1 DEL 18/09/2026 - 8 posti ADEE 30/06 + 1 fino al 05/10 esclusi sabati e domeniche",
                     oggi=OGGI)
        self.assertEqual(a.pubblicato, date(2026, 9, 18))
        self.assertEqual(posti(a), [(None, "2027-06-30"), (None, "2026-10-05")])
        self.assertEqual(valuta(a, CRITERI, OGGI), ("da_verificare", ["ore non indicate"]))

    def test_codice_attaccato_alla_parola(self):
        a = analizza("AVVISO INTERPELLO 11 posto comuneAAAA (2)", oggi=OGGI)
        self.assertEqual(a.ordini, ["infanzia"])
        a = analizza("AVVISO INTERPELLO 4 posto comuneADEE", oggi=OGGI)
        self.assertEqual(a.ordini, ["primaria"])

    def test_anno_scolastico_citato(self):
        from scraper.testo import anno_scolastico_citato
        self.assertEqual(anno_scolastico_citato("interpello-1-25-26"), 2025)
        self.assertEqual(anno_scolastico_citato("Interpello N.6 Primaria supplenza breve comune 2026 2027"), 2026)
        self.assertEqual(anno_scolastico_citato("Interpello a.s. 2025/26 posto comune"), 2025)
        self.assertIsNone(anno_scolastico_citato("Interpello supplenza 25-26 settembre"))
        self.assertIsNone(anno_scolastico_citato("Interpello del 18/09/2026 - 24 ore fino al 30/06/2027"))
        self.assertIsNone(anno_scolastico_citato("Interpello 24-25 ore"))

    def test_scuola_media_dal_titolo(self):
        a = analizza("interpello tecnologia completo media", oggi=OGGI)
        self.assertEqual(a.ordini, ["secondaria"])
        self.assertEqual(valuta(a, CRITERI, OGGI)[0], "non_corrisponde")
        # ma se il titolo nomina la primaria, vale quella
        a = analizza("Interpello primaria e media - 12 ore", oggi=OGGI)
        self.assertIn("primaria", a.ordini)

    def test_data_nel_titolo_passata_o_futura(self):
        a = analizza("INTERPELLO - 23.09.2026 PRIMARIA POSTI SOSTEGNO", oggi=OGGI)
        self.assertEqual(a.pubblicato, date(2026, 9, 23))           # passata: e' la data dell'avviso
        a = analizza("03-_INTERPELLO_n_1_SOSTEGNO_ADMM_26.11.2026.pdf.pades", oggi=OGGI)
        self.assertEqual(posti(a), [(None, "2026-11-26")])          # futura: e' la fine della supplenza
        self.assertIsNone(a.pubblicato)
        a = analizza("INTERPELLO_INFANZIA_DEL_03.12.pdf.pades", oggi=OGGI)
        self.assertEqual(a.pubblicato, date(2025, 12, 3))           # anno sottinteso: non puo' essere futura

    def test_data_di_pubblicazione_dal_titolo(self):
        self.assertEqual(analizza("Interpello n. 23 del 12-05--2026 -Infanzia posto comune.pdf", oggi=OGGI).pubblicato, date(2026, 5, 12))
        self.assertEqual(analizza("4194/E DEL 12/09/2024 (AAAA posto comune infanzia)", oggi=OGGI).pubblicato, date(2024, 9, 12))


class CosaEUnAvviso(unittest.TestCase):
    def test_avvisi(self):
        for titolo in ["Avviso per l'individuazione e il reclutamento di personale docente - interpello primaria",
                       "DECRETO INTERPELLO per supplenza breve fino al 14-10-2026 ore 24 posto comune primaria",
                       "Interpello per supplenza a.s. 2024/25 a seguito di esaurimento delle graduatorie d'Istituto",
                       "AVVISO PER SELEZIONE PERSONALE DOCENTE SUPPLENTE SCUOLA PRIMARIA POSTO COMUNE (EEEE)"]:
            self.assertTrue(sembra_avviso(titolo), titolo)

    def test_non_avvisi(self):
        for titolo in ["Decreto di annullamento Interpelli disposti con protocollo n. 4505",
                       "Individuazione docenti- Interpello per supplenza– scuola primaria Milano",
                       "Nomina_commissione_per_la_valutazione_delle_istanze_interpello_prot._5341",
                       "Individua_docente_interpello_prot._5341_del_16-09-2026.pdf.pades",
                       "Modello Istanza Partecipazione Interpello", "ALLEGATO A INTERPELLO 18/09/2026",
                       "Informativa Docenti- Interpelli", "Determina a contrarre acquisto modulo pronto mad & interpelli",
                       "Criteri individuazione docenti da interpelli per contratti a T.D.",
                       "Interpelli scuola: come funzionano e cosa devono fare le segreterie.pdf"]:
            self.assertFalse(sembra_avviso(titolo), titolo)


if __name__ == "__main__":
    unittest.main()
