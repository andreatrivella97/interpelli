"""Regole che leggono un avviso e ne ricavano i dati utili.

Da titolo e testo (PDF o pagina) si ottengono:

* i **posti** offerti: ordine di scuola, tipo di posto, ore settimanali, data di fine
  contratto, ciascuno con il frammento di testo da cui e' stato ricavato;
* il **termine per candidarsi**;
* la **data di pubblicazione**.

Le regole sono volutamente prudenti: quando un dato non si riconosce resta vuoto, e la
pagina mostra l'avviso tra quelli "da verificare" invece di scartarlo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .testo import FINI_ANNO, DataTrovata, anno_scolastico, da_nome_file, piatto, trova_date, trova_ora

I = re.IGNORECASE

# --- ordine di scuola ---------------------------------------------------------------------
RE_ORDINE = {
    "infanzia": re.compile(r"infanzia|\bmaterna\b|\bAAAA\b|\bADAA\b", I),
    "primaria": re.compile(r"primaria|\belementar[ei]\b|\bEEEE?\b|\bADEE\b", I),
    "secondaria": re.compile(
        r"secondaria|\b(?:I|1|primo)\s?°?\s?grado\b|\bA-?0?\d{2}\b|\bA[A-Z]\d{2}\b|\bA[A-Z]\d[A-Z]\b"
        r"|\bADMM\b|\bADML\b|\bADSS\b|strumento\s+musicale|\bscuol[ae]\s+medi[ae]\b", I),
}
RE_CODICI = {
    "infanzia": re.compile(r"\bAAAA\b|\bADAA\b"),
    "primaria": re.compile(r"\bEEEE\b|\bADEE\b"),
    "secondaria": re.compile(r"\bA-?0\d{2}\b|\bA[A-Z]\d{2}\b|\bA[A-Z]\d[A-Z]\b|\bADMM\b|\bADML\b|\bADSS\b"),
}
# solo nei titoli: materie e modi di dire che indicano la scuola media
RE_MEDIA_NEL_TITOLO = re.compile(
    r"\bmedi[ae]\b|\btecnologia\b|\blettere\b|\bfrancese\b|\bspagnolo\b|\btedesco\b|matematica\s+e\s+scienze"
    r"|\barte\s+e\s+immagine\b", I)
RE_ATA = re.compile(
    r"collaborator[ei]\s+scolastic|assistent[ei]\s+amministrativ|assistent[ei]\s+tecnic|\bDSGA\b"
    r"|personale\s+A\.?T\.?A\b|\bprofilo\s+(?:AA|AT|CS)\b", I)
RE_SOSTEGNO = re.compile(r"sostegno|\bAD(?:AA|EE|MM|ML|SS)\b", I)
RE_COMUNE = re.compile(r"post[oi]\s+comun[ei]|\bcomun[ei]\b|\bAAAA\b|\bEEEE?\b", I)

# --- ore settimanali -----------------------------------------------------------------------
RE_ORE_SETT = re.compile(
    r"(?:\bore|\borario)[^.;\n]{0,40}?settimanal[ei]\w*\s*[:=]?\s*(?:di\s+|pari\s+a\s+|n\.?\s*)?"
    r"(\d{1,2})(?:[.,]\d)?\s?(?:h|ore)?\b(?![./:-]\d)", I)
RE_NUM_ORE = re.compile(r"(?<!\d[.,/:-])(?<!\d)(\d{1,2})(?:[.,]\d)?\s?(?:ore|hh?)\b(?!\s?\d)", I)
RE_ORE_NUM = re.compile(r"\bore\s+(?:n\.?\s*)?(\d{1,2})\b(?![:.,]\d)(?!\s*(?:del|dell|di)\b)", I)
RE_FRAZIONE = re.compile(r"(?<![\d/.-])(\d{1,2})\s?/\s?(18|22|24|25|36)\b(?!\s?[./-]\s?\d)")
RE_INTERO = re.compile(
    r"(?:post[oi]|cattedr[ae]|orario)\s+(?:a\s+)?(?:inter[oaie]|complet[oaie])|orario\s+pieno|full[\s-]?time", I)
RE_NON_ORE_DOPO = re.compile(
    r"^\s*(?:dopo|dall|dal\s+momento|dal\s+ricevimento|prima|successiv|di\s+preavviso|lavorativ|per\s+la\s+presa)", I)
RE_NON_ORE_PRIMA = re.compile(
    r"(?:entro|nelle|prossime|ultime|oltre|almeno|termine\s+(?:massimo\s+)?di|servizio\s+entro)\s*(?:le\s+)?$", I)
RE_ORARIO_PRIMA = re.compile(r"(?:\ble|alle|dalle|entro\s+le|dopo\s+le|fino\s+alle)\s*$", I)

# --- date: a che cosa si riferiscono --------------------------------------------------------
RE_PRIMA_FINE = re.compile(
    r"(?:fino\s+a(?:l|ll')?|sino\s+a(?:l|ll')?|\bal\b|termine(?:\s+(?:del\s+contratto|contrattuale|della\s+supplenza|incarico))?\s*:?"
    r"|scadenza(?:\s+del)?\s+contratto\s*:?|fine\s+(?:contratto|supplenza|incarico|rapporto)\s*:?)"
    r"\s*(?:giorno\s+|data\s+(?:del\s+)?)?$", I)
_FRASE = r"(?:[^.;]|(?<=\d)\.(?=\d))"      # dentro una frase; il punto e' ammesso solo tra due cifre
RE_PRIMA_INIZIO = re.compile(
    r"(?:\bdal(?:l')?|\bda\s+giorno|decorrere\s+dal?|partire\s+dal?|\binizio" + _FRASE + r"{0,30}"
    r"|presa\s+di\s+servizio" + _FRASE + r"{0,45}|decorrenza" + _FRASE + r"{0,15}|\bda\b)\s*(?:giorno\s+)?$", I)
RE_PRIMA_SCADENZA = re.compile(
    r"(?:\bentro\b|non\s+oltre|\bscadenza\b(?!\s+(?:del\s+)?contratto)|\bscade\b"
    r"|termine\s+(?:di\s+|per\s+la\s+|ultimo\s+)?(?:di\s+)?presentazione|fino\s+alle\s+ore|pervenire)"
    + _FRASE + r"{0,60}$", I)
RE_PRIMA_PROTOCOLLO = re.compile(
    r"(?:prot\w*\.?[^;]{0,30}|\b\d{2,6}\s?/\s?[A-Z]{1,2}\s+|interpell\w*[^;]{0,25}|avviso[^;]{0,20}|circolare[^;]{0,20})"
    r"\bdel(?:l')?\s*$", I)
RE_PRIMA_LUOGO = re.compile(r"[A-Z][A-Za-zàèéìòù' ]{2,25},\s*(?:l[iì]\s*)?$")

RE_FINE_DIDATTICHE = re.compile(r"termine\s+dell[e']\s*attivit[aà]'?\s+didattic", I)
RE_FINE_LEZIONI = re.compile(r"termine\s+delle\s+lezioni", I)
RE_FINE_APERTA = re.compile(r"rientro\s+del(?:la)?\s+titolare|avente\s+(?:diritto|titolo)", I)

# riga di tabella: codice del posto, numero di posti, ore, eventuale presa di servizio, scadenza del contratto
_DATA = r"\d{1,2}\s?[./-]\s?\d{1,2}\s?[./-]\s?(?:\d{4}|\d{2})"
RE_RIGA_TABELLA = re.compile(
    r"\b(AAAA|EEEE|ADAA|ADEE)\b[^\d]{0,45}?(\d{1,2})\s+(\d{1,2})\s+(" + _DATA + r")(?:\s+(" + _DATA + r"))?")

# --- che cosa non e' un interpello ----------------------------------------------------------
RE_NEGATIVO_FORTE = re.compile(
    r"annullament|nomina.{0,14}commissione|individua[_ ]docent|\bverbal[ei]\b|criteri\s+(?:di\s+)?individuazione"
    r"|determina\s+a\s+contrarre|\besit[oi]\b|come\s+funzionano|\bguida\b|decreto\s+di\s+individuazione", I)
RE_NEGATIVO_DEBOLE = re.compile(
    r"\bmodul[oi]\b|\bmodello\b|\ballegat[oi]\b|informativa|privacy|istruzioni|domanda\s+di\s+partecipazione|\bmad\b", I)
RE_NON_AVVISO = re.compile(RE_NEGATIVO_FORTE.pattern + "|" + RE_NEGATIVO_DEBOLE.pattern, I)
RE_AVVISO = re.compile(r"interpell|avviso.{0,40}supplen|selezione\s+personale\s+docente|reclutamento.{0,30}docent", I)

ORE_POSTO_INTERO = {"infanzia": 25, "primaria": 24, "secondaria": 18}


@dataclass
class Posto:
    ordini: list[str] = field(default_factory=list)
    tipo: str | None = None            # "comune" | "sostegno"
    ore: int | None = None
    intero: bool = False               # il testo parla di posto/cattedra intera senza dare le ore
    inizio: date | None = None
    fine: date | None = None
    fine_nota: str | None = None       # es. "termine delle attività didattiche", "anno corretto"
    prova: str = ""

    def come_dati(self) -> dict:
        return {
            "ordini": self.ordini, "tipo": self.tipo, "ore": self.ore, "intero": self.intero,
            "inizio": self.inizio.isoformat() if self.inizio else None,
            "fine": self.fine.isoformat() if self.fine else None,
            "fine_nota": self.fine_nota, "prova": self.prova,
        }


@dataclass
class Analisi:
    posti: list[Posto] = field(default_factory=list)
    ordini: list[str] = field(default_factory=list)
    personale: str = "docente"
    scadenza: datetime | None = None
    scadenza_prova: str = ""
    pubblicato: date | None = None

    def completezza(self) -> int:
        """Quanti dati utili contiene: serve a scegliere la lettura migliore tra piu' titoli."""
        return (sum((p.ore is not None or p.intero) + (p.fine is not None) + bool(p.ordini) for p in self.posti)
                + bool(self.scadenza) + bool(self.pubblicato))


@dataclass
class _Ore:
    inizio: int
    fine: int
    ore: int | None
    forza: int
    intero: bool = False
    usato: bool = False


def escluso(titolo: str) -> bool:
    """Moduli, allegati, esiti, verbali: documenti che accompagnano un interpello ma non lo sono.

    Parole come "modulo" o "allegato" escludono solo se vengono prima della parola
    "interpello" ("Modello istanza interpello"): dopo, descrivono l'avviso
    ("Interpello ... + modulo per la domanda").
    """
    if RE_NEGATIVO_FORTE.search(titolo):
        return True
    debole = RE_NEGATIVO_DEBOLE.search(titolo)
    if not debole:
        return False
    avviso = RE_AVVISO.search(titolo)
    return avviso is None or debole.start() < avviso.start()


def sembra_avviso(titolo: str) -> bool:
    """Un titolo che parla di interpello e non e' un modulo, un esito o un verbale."""
    return bool(RE_AVVISO.search(titolo)) and not escluso(titolo)


def _stacca_codici(testo: str) -> str:
    """ "posto comuneAAAA" -> "posto comune AAAA": i codici attaccati a una parola non si riconoscerebbero."""
    return re.sub(r"(?<=[a-zà-ù])(?=(?:AAAA|EEEE|ADAA|ADEE|ADMM|ADSS)(?![A-Za-z]))", " ", testo)


def _ordini_in(testo: str, solo_codici: bool = False) -> list[str]:
    regole = RE_CODICI if solo_codici else RE_ORDINE
    return [nome for nome, regola in regole.items() if regola.search(testo)]


def _tipo_in(testo: str) -> str | None:
    if RE_SOSTEGNO.search(testo):
        return "sostegno"
    if RE_COMUNE.search(testo):
        return "comune"
    return None


def trova_ore(testo: str) -> list[_Ore]:
    """Le indicazioni di orario settimanale, scartando gli orari di orologio ("ore 14:00")."""
    trovate: list[_Ore] = []

    def aggiungi(inizio, fine, ore, forza, intero=False):
        if ore is not None and not 1 <= ore <= 40:
            return
        for t in trovate:
            if inizio < t.fine and t.inizio < fine:      # stessa cifra letta da due regole
                t.forza = max(t.forza, forza)
                return
        trovate.append(_Ore(inizio, fine, ore, forza, intero))

    for m in RE_ORE_SETT.finditer(testo):
        aggiungi(m.start(1), m.end(1), int(m.group(1)), 3)
    for m in RE_NUM_ORE.finditer(testo):
        prima, dopo = testo[max(0, m.start() - 30):m.start()], testo[m.end():m.end() + 30]
        if RE_NON_ORE_DOPO.search(dopo) or RE_NON_ORE_PRIMA.search(prima):
            continue
        forte = re.search(r"settiman", dopo, I) or re.search(r"cattedr|spezzon|post[oi]|part.?time|\bn\.?\s*$|\bdi\s*$", prima, I)
        aggiungi(m.start(1), m.end(1), int(m.group(1)), 2 if forte else 1)
    for m in RE_ORE_NUM.finditer(testo):
        prima, dopo = testo[max(0, m.start() - 14):m.start()], testo[m.end():m.end() + 30]
        if RE_ORARIO_PRIMA.search(prima):
            continue
        forte = re.search(r"settiman|post[oi]|fino|\bdal\b|comune|sostegno", dopo, I)
        aggiungi(m.start(1), m.end(1), int(m.group(1)), 2 if forte else 1)
    for m in RE_FRAZIONE.finditer(testo):
        attorno = testo[max(0, m.start() - 25):m.end() + 25]
        if re.search(r"\bore\b|\bh\b|cattedr|orario|spezzon", attorno, I):
            aggiungi(m.start(1), m.end(2), int(m.group(1)), 2)
    for m in RE_INTERO.finditer(testo):
        aggiungi(m.start(), m.end(), None, 1, intero=True)
    trovate.sort(key=lambda t: t.inizio)
    return trovate


def _classifica_date(testo: str, date_trovate: list[DataTrovata]):
    """Divide le date tra fine contratto, inizio, termine per candidarsi e protocollo."""
    fini, inizi, scadenze, protocolli, altre = [], [], [], [], []
    for d in date_trovate:
        vicino = testo[max(0, d.inizio - 48):d.inizio]
        lontano = testo[max(0, d.inizio - 75):d.inizio]
        if RE_PRIMA_FINE.search(vicino):
            # "dal 02 al 06/03/2026": solo se subito prima non c'e' un'indicazione di scadenza
            if re.search(r"entro\s+(?:e\s+non\s+oltre\s+)?(?:il\s+)?$", vicino, I):
                scadenze.append(d)
            else:
                fini.append(d)
        elif RE_PRIMA_INIZIO.search(vicino):
            inizi.append(d)
        elif RE_PRIMA_SCADENZA.search(lontano):
            scadenze.append(d)
        elif RE_PRIMA_PROTOCOLLO.search(lontano) or RE_PRIMA_LUOGO.search(vicino):
            protocolli.append(d)
        else:
            altre.append(d)
    return fini, inizi, scadenze, protocolli, altre


def _scadenza(testo: str, scadenze: list[DataTrovata]) -> tuple[datetime | None, str]:
    if not scadenze:
        return None, ""
    d = scadenze[0]
    prima = testo[max(0, d.inizio - 45):d.inizio]
    dopo = testo[d.fine:d.fine + 28]
    # l'orario piu' vicino alla data: prima quello scritto appena prima, poi quello subito dopo
    ora = None
    orari_prima = list(re.finditer(r"(?:\bore|\bh\.?|\balle)\s*\d{1,2}(?:\s?[:.,]\s?\d{2})?", prima, I))
    if orari_prima:
        ora = trova_ora(orari_prima[-1].group(0))
    if ora is None:
        ora = trova_ora(dopo)
        if ora is None:
            m = re.match(r"\s*[,-]?\s*(\d{1,2})[:.](\d{2})\b", dopo)
            if m and int(m.group(1)) <= 23 and int(m.group(2)) <= 59:
                ora = (int(m.group(1)), int(m.group(2)))
    ore, minuti = ora if ora else (23, 59)
    prova = testo[max(0, d.inizio - 70):d.fine + 30].strip()
    return datetime(d.giorno.year, d.giorno.month, d.giorno.day, ore, minuti), prova


def analizza(titolo: str, testo: str = "", *, oggi: date, pubblicato: date | None = None,
             personale: str | None = None) -> Analisi:
    """Legge titolo e testo di un avviso e restituisce posti, scadenza e data di pubblicazione."""
    titolo_p = _stacca_codici(piatto(da_nome_file(titolo)))
    corpo = _stacca_codici(piatto(testo))
    riferimento = pubblicato or oggi
    fine_as = date(anno_scolastico(riferimento) + 1, 6, 30)
    esito = Analisi()

    # personale ATA: non riguarda chi cerca una supplenza da docente
    if personale:
        esito.personale = personale.lower()
    elif RE_ATA.search(titolo_p) or (RE_ATA.search(corpo[:1500]) and not _ordini_in(titolo_p)):
        esito.personale = "ata"

    # ordine di scuola a livello di documento: titolo, poi oggetto, poi codici nel testo
    oggetto = ""
    m = re.search(r"\boggetto\s*:?\s*(.{10,320}?)(?:\bIL\s+DIRIGENTE|\bVIST[AOEI]\b|$)", corpo, I)
    if m:
        oggetto = m.group(1)
    ordini_doc = _ordini_in(titolo_p) or _ordini_in(oggetto) or _ordini_in(corpo, solo_codici=True)
    if not ordini_doc and RE_MEDIA_NEL_TITOLO.search(titolo_p):
        ordini_doc = ["secondaria"]
    tipo_doc = _tipo_in(titolo_p) or _tipo_in(oggetto)

    # data dell'avviso (protocollo): serve anche a scartare le date piu' vecchie citate nel testo
    for sorgente in ([corpo] if corpo else []) + [titolo_p]:
        _, _, _, protocolli, _ = _classifica_date(sorgente, trova_date(sorgente, riferimento))
        if protocolli:
            esito.pubblicato = protocolli[0].giorno
            break
    if esito.pubblicato is None:
        # "INTERPELLO - 23.09.2026 PRIMARIA": una data con l'anno nel titolo, senza altro significato, e' quella dell'avviso
        *_, altre = _classifica_date(titolo_p, trova_date(titolo_p, riferimento))
        scritte = [d for d in altre if d.anno_scritto and d.giorno <= oggi]
        if scritte:
            esito.pubblicato = scritte[0].giorno
    if esito.pubblicato and esito.pubblicato > oggi:
        # una data d'avviso non puo' essere futura: l'anno era sottinteso ed e' quello prima
        try:
            esito.pubblicato = esito.pubblicato.replace(year=esito.pubblicato.year - 1)
        except ValueError:
            esito.pubblicato = None
    if esito.pubblicato is None:
        esito.pubblicato = pubblicato
    non_prima = esito.pubblicato

    posti: list[Posto] = []
    for sorgente in ([corpo] if corpo else []) + [titolo_p]:
        posti = _posti_da(sorgente, riferimento, fine_as, ordini_doc, tipo_doc, non_prima,
                          oggi if sorgente is titolo_p else None)
        if any(p.ore is not None or p.fine is not None or p.intero or p.fine_nota for p in posti):
            break
    if not posti or not any(p.ore is not None or p.fine or p.intero or p.fine_nota for p in posti):
        posti = [Posto(ordini=ordini_doc, tipo=tipo_doc, prova=titolo_p[:200])]
    # il titolo puo' dire cio' che il testo tace (PDF scansionati): completa i posti senza dati
    if corpo:
        dal_titolo = _posti_da(titolo_p, riferimento, fine_as, ordini_doc, tipo_doc, non_prima, oggi)
        if len(dal_titolo) == 1 and len(posti) == 1:
            t, p = dal_titolo[0], posti[0]
            if p.ore is None and not p.intero and t.ore is not None:
                p.ore = t.ore
            if p.fine is None and t.fine is not None:
                p.fine, p.fine_nota = t.fine, t.fine_nota
    if not ordini_doc:
        # ultima risorsa: le parole vicine ai dati dei posti
        ordini_doc = sorted({o for p in posti for o in p.ordini})
    esito.posti = posti
    esito.ordini = sorted({o for p in posti for o in p.ordini} | set(ordini_doc))

    # termine per candidarsi
    for sorgente in ([corpo] if corpo else []) + [titolo_p]:
        date_trovate = [d for d in trova_date(sorgente, riferimento)
                        if not any(m.start() <= d.inizio < m.end() for m in RE_RIGA_TABELLA.finditer(sorgente))]
        _, _, scadenze, _, _ = _classifica_date(sorgente, date_trovate)
        if non_prima:
            scadenze = [d for d in scadenze if d.giorno >= non_prima]
        if esito.scadenza is None:
            esito.scadenza, esito.scadenza_prova = _scadenza(sorgente, scadenze)
    return esito


def _data_sola(grezzo: str, riferimento: date) -> date | None:
    trovate = trova_date("al " + grezzo, riferimento)
    return trovate[0].giorno if trovate else None


def _posti_da(testo: str, riferimento: date, fine_as: date, ordini_doc: list[str], tipo_doc: str | None,
              non_prima: date | None = None, titolo_al: date | None = None) -> list[Posto]:
    # 1) tabelle: "EEEE 1 24 24/09/2026 22/12/2026" = codice, posti, ore, presa di servizio, scadenza
    da_tabella: list[Posto] = []
    for m in RE_RIGA_TABELLA.finditer(testo):
        ore_riga = int(m.group(3))
        if not 1 <= ore_riga <= 40:
            continue
        prima_data, seconda_data = _data_sola(m.group(4), riferimento), (_data_sola(m.group(5), riferimento) if m.group(5) else None)
        avvio, termine = (prima_data, seconda_data) if seconda_data else (None, prima_data)
        attorno = testo[m.start():m.end() + 60]
        da_tabella.append(Posto(
            ordini=_ordini_in(m.group(1), solo_codici=True), tipo=_tipo_in(attorno) or tipo_doc,
            ore=ore_riga, inizio=avvio, fine=termine, prova=testo[max(0, m.start() - 10):m.end() + 50].strip()))
    if da_tabella:
        return da_tabella

    # 2) testo libero: si parte dalle date di fine e si cercano le ore nella stessa frase
    date_trovate = trova_date(testo, riferimento)
    fini, inizi, _, _, altre = _classifica_date(testo, date_trovate)
    # "8 posti ADEE 30/06": giorno e mese di fine anno, anche senza un "fino al" davanti
    fini = fini + [d for d in altre if not d.anno_scritto and (d.giorno.day, d.giorno.month) in FINI_ANNO]
    if titolo_al:
        # in un titolo, una data futura senza altre indicazioni e' la fine della supplenza
        # ("INTERPELLO SOSTEGNO 26.11.2026"); una passata e' la data dell'avviso
        fini = fini + [d for d in altre if d.anno_scritto and d.giorno > titolo_al]
    fini.sort(key=lambda d: d.inizio)
    if non_prima:
        # una "fine" precedente alla data dell'avviso e' un riferimento ad altro (norme, requisiti)
        fini = [d for d in fini if d.giorno >= non_prima or
                any(0 < d.inizio - i.fine <= 45 and i.giorno >= non_prima for i in inizi)]
    ore = trova_ore(testo)

    # indicazioni di fine scritte a parole
    @dataclass
    class _Fine:
        inizio: int
        fine: int
        giorno: date | None
        nota: str | None

    punti: list[_Fine] = [_Fine(d.inizio, d.fine, d.giorno, None) for d in fini]
    for regola, giorno, nota in (
        (RE_FINE_DIDATTICHE, fine_as, "termine delle attività didattiche"),
        (RE_FINE_LEZIONI, date(fine_as.year, 6, 10), "termine delle lezioni (data indicativa)"),
        (RE_FINE_APERTA, None, "fino al rientro del titolare"),
    ):
        for m in regola.finditer(testo):
            # se subito dopo c'e' gia' la data esplicita ("... didattiche (30/06/2027)") vale quella
            if any(0 <= d.inizio - m.end() <= 12 for d in fini):
                continue
            punti.append(_Fine(m.start(), m.end(), giorno, nota))
    punti.sort(key=lambda p: p.inizio)

    posti: list[Posto] = []
    precedente = 0
    for n, punto in enumerate(punti):
        successivo = punti[n + 1].inizio if n + 1 < len(punti) else len(testo)
        # ore: prima quelle scritte prima della data (nella stessa frase), poi quelle subito dopo
        prima = [o for o in ore if not o.usato and max(precedente, punto.inizio - 220) <= o.inizio < punto.inizio]
        limite_dopo = min(successivo, punto.fine + 130)
        prossimo_dal = next((d.inizio for d in inizi if d.inizio > punto.fine), limite_dopo)
        dopo = [o for o in ore if not o.usato and punto.fine <= o.inizio < min(limite_dopo, prossimo_dal)]
        scelta = None
        if prima:
            scelta = max(prima, key=lambda o: (o.forza, o.ore or 0))
        elif dopo:
            scelta = dopo[0]
        if scelta:
            scelta.usato = True
        avvio = next((d.giorno for d in reversed(inizi) if precedente <= d.inizio < punto.inizio
                      and punto.inizio - d.fine <= 45), None)
        giorno, nota = punto.giorno, punto.nota
        if giorno and avvio and giorno < avvio:
            # "dal 21/09/2026 al 30/06/2026": anno sbagliato nell'avviso, e' quello dopo
            try:
                corretto = giorno.replace(year=giorno.year + 1)
                if corretto > avvio and corretto <= date(fine_as.year, 8, 31) + timedelta(days=366):
                    giorno, nota = corretto, "anno corretto: nell'avviso la fine precede l'inizio"
            except ValueError:
                pass
        finestra = testo[max(precedente, punto.inizio - 220):punto.inizio]
        ordini = _ordini_in(finestra) or _ordini_in(testo[punto.fine:punto.fine + 90])
        if ordini_doc:
            comuni = [o for o in ordini if o in ordini_doc]
            ordini = comuni or (ordini_doc if not ordini else ordini)
        tipo = _tipo_in(finestra[-140:]) or tipo_doc or _tipo_in(finestra)
        posti.append(Posto(
            ordini=ordini, tipo=tipo,
            ore=scelta.ore if scelta else None, intero=bool(scelta and scelta.intero),
            inizio=avvio, fine=giorno, fine_nota=nota,
            prova=testo[max(0, min(punto.inizio, scelta.inizio if scelta else punto.inizio) - 70):
                        max(punto.fine, scelta.fine if scelta else 0) + 40].strip(),
        ))
        precedente = punto.fine

    # ore senza una data di fine associata: posti di cui si conosce solo l'orario
    libere = [o for o in ore if not o.usato]
    solo_ore = bool(libere) and not posti
    if libere and not posti:
        viste = set()
        for o in sorted(libere, key=lambda o: (-o.forza, o.inizio)):
            chiave_ore = (o.ore, o.intero)
            if chiave_ore in viste or (o.forza < 2 and len(viste) >= 1):
                continue
            viste.add(chiave_ore)
            finestra = testo[max(0, o.inizio - 200):o.fine + 60]
            ordini = _ordini_in(finestra)
            if ordini_doc:
                ordini = [x for x in ordini if x in ordini_doc] or ordini_doc
            posti.append(Posto(ordini=ordini, tipo=_tipo_in(finestra[-200:]) or tipo_doc, ore=o.ore, intero=o.intero,
                               prova=testo[max(0, o.inizio - 80):o.fine + 60].strip()))
    if solo_ore and len(re.findall(r"\bpost[oi]\b", testo, I)) > len(posti):
        # l'avviso elenca piu' posti di quante ore dichiari: gli altri restano da leggere a mano
        posti.append(Posto(ordini=ordini_doc, tipo=tipo_doc, prova=testo[:200].strip()))
    # lo stesso posto ripetuto (titolo e sommario, intestazione e testo) conta una volta
    unici, visti = [], set()
    for p in posti:
        firma = (tuple(p.ordini), p.tipo, p.ore, p.intero, p.fine, p.fine_nota)
        if firma not in visti:
            visti.add(firma)
            unici.append(p)
    return unici


# --- confronto con i criteri -----------------------------------------------------------------

def valuta_posto(posto: Posto, criteri: dict, oggi: date) -> dict:
    """Per ogni criterio: True (rispettato), False (non rispettato), None (dato mancante)."""
    voluti = set(criteri.get("ordini", ["infanzia", "primaria"]))
    ordine = None if not posto.ordini else bool(voluti & set(posto.ordini))
    ore_min = criteri.get("ore_min", 20)
    if posto.ore is not None:
        ore = posto.ore >= ore_min
    elif posto.intero:
        ore = True
    else:
        ore = None
    mesi = set(criteri.get("mesi_fine", [6]))
    fine = None if posto.fine is None else (posto.fine.month in mesi and posto.fine >= oggi)
    return {"ordine": ordine, "ore": ore, "fine": fine}


def valuta(analisi: Analisi, criteri: dict, oggi: date) -> tuple[str, list[str]]:
    """Esito complessivo dell'avviso: "corrisponde", "da_verificare" o "non_corrisponde"."""
    if analisi.personale == "ata":
        return "non_corrisponde", ["riguarda personale ATA"]
    migliore, motivi_migliori = "non_corrisponde", []
    for posto in analisi.posti or [Posto(ordini=analisi.ordini)]:
        v = valuta_posto(posto, criteri, oggi)
        if all(x is True for x in v.values()):
            return "corrisponde", []
        if any(x is False for x in v.values()):
            continue
        motivi = []
        if v["ordine"] is None:
            motivi.append("ordine di scuola non indicato")
        if v["ore"] is None:
            motivi.append("ore non indicate")
        if v["fine"] is None:
            motivi.append(posto.fine_nota or "scadenza del contratto non indicata")
        if migliore != "da_verificare" or len(motivi) < len(motivi_migliori):
            migliore, motivi_migliori = "da_verificare", motivi
    return migliore, motivi_migliori
