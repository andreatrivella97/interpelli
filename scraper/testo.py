"""Funzioni di base sul testo: pulizia, date in italiano, anno scolastico."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime

MESI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6,
    "lug": 7, "ago": 8, "set": 9, "sett": 9, "ott": 10, "nov": 11, "dic": 12,
}
_MESI_RE = "|".join(sorted(MESI, key=len, reverse=True))

# 30/06/2027 · 30.06.27 · 30-06-2027 · 30/06 (l'anno puo' mancare)
RE_DATA_NUM = re.compile(
    r"(?<![\d/.-])(\d{1,2})\s?[./-]\s?(\d{1,2})(?:\s?[./-]{1,2}\s?(\d{4}|\d{2}))?(?![\d/-])(?!\.\d)")
# 30 giugno 2027 · 1° ottobre · 18 settembre 2026
RE_DATA_TESTO = re.compile(
    rf"(?<!\d)(\d{{1,2}})\s?[°º]?\s+({_MESI_RE})\.?(?:\s+(\d{{4}}))?(?![a-z])", re.IGNORECASE)
# ore 14:00 · ore 13.15 · h 9 · alle 12
RE_ORA = re.compile(r"(?:\bore|\bh\.?|\balle)\s*(\d{1,2})(?:\s?[:.,]\s?(\d{2}))?(?!\d)", re.IGNORECASE)


# giorno e mese in cui finiscono le supplenze lunghe: termine delle attivita' didattiche e fine anno
FINI_ANNO = {(30, 6), (31, 8)}
# 2025/2026 · 2025-26 · a.s. 25/26 · interpello-1-25-26
RE_ANNO_SCOLASTICO = re.compile(
    rf"(?<![\d/.])(?:(20\d{{2}})\s?[-/ ]\s?(?:20)?(\d{{2}})|(2\d|3\d)\s?[-/]\s?(2\d|3\d))(?![\d/.])"
    rf"(?!\s*-?\s*(?:{_MESI_RE}|ore)\b)", re.IGNORECASE)


def pulisci(testo: str) -> str:
    """Spazi uniformi, apostrofi e trattini normalizzati, niente caratteri invisibili."""
    testo = unicodedata.normalize("NFKC", testo or "")
    testo = testo.replace("​", "").replace("﻿", "").replace("\xad", "")
    testo = re.sub(r"[’‘`´]", "'", testo)
    testo = re.sub(r"[–—−]", "-", testo)
    testo = re.sub(r"[“”«»]", '"', testo)
    testo = re.sub(r"[ \t\r\f\v\xa0]+", " ", testo)
    testo = re.sub(r" ?\n ?", "\n", testo)
    return testo.strip()


def piatto(testo: str) -> str:
    """Tutto su una riga: i PDF spezzano le frasi a meta', le regole lavorano meglio cosi'."""
    return re.sub(r"\s+", " ", pulisci(testo)).strip()


def senza_accenti(testo: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", testo) if unicodedata.category(c) != "Mn")


def chiave(testo: str) -> str:
    """Forma ridotta per confrontare titoli e nomi di file: solo lettere e cifre minuscole."""
    testo = senza_accenti(testo or "").lower().replace("_", " ")
    testo = re.sub(r"\.(pdf|p7m|pades|docx?|odt)\b", " ", testo)
    testo = re.sub(r"\b(timbro|timbrato|firmato|signed|protocollo|copia|conforme)\b", " ", testo)
    return re.sub(r"[^a-z0-9]+", "", testo)


def da_nome_file(nome: str) -> str:
    """Rende leggibile un nome di file: "Interpello_fino_al_30_06_27.pdf" -> "Interpello fino al 30/06/27"."""
    nome = re.sub(r"(\.pdf|\.p7m|\.pades|\.docx?|\.odt)+\s*$", "", nome or "", flags=re.IGNORECASE)
    nome = re.sub(r"(?<!\d)(\d{1,2})_(\d{1,2})_(\d{4}|\d{2})(?!\d)", r"\1/\2/\3", nome)
    nome = re.sub(r"[_]+", " ", nome)
    nome = re.sub(r"\.(pdf|pades|p7m|docx?)\b", " ", nome, flags=re.IGNORECASE)
    # prefissi aggiunti dai programmi di protocollo e firma
    nome = re.sub(r"^\s*(?:(?:copia\s+conforme|timbrato|timbro|firmato|protocollo|signed)\s*\d*\s*)+", "", nome,
                  flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", nome).strip(" -._")


def anno_scolastico(riferimento: date) -> int:
    """Anno in cui inizia l'anno scolastico che contiene la data (2026 per ottobre 2026 e per giugno 2027)."""
    return riferimento.year if riferimento.month >= 8 else riferimento.year - 1


def anno_scolastico_citato(testo: str) -> int | None:
    """Anno d'inizio dell'anno scolastico nominato nel testo ("a.s. 2025/26" -> 2025), se c'e'."""
    trovati = []
    for m in RE_ANNO_SCOLASTICO.finditer(testo or ""):
        primo = int(m.group(1)) if m.group(1) else 2000 + int(m.group(3))
        secondo = int(m.group(2) or m.group(4))
        if (primo + 1) % 100 == secondo:
            trovati.append(primo)
    return max(trovati) if trovati else None


@dataclass
class DataTrovata:
    inizio: int          # posizione nel testo
    fine: int
    giorno: date
    anno_scritto: bool   # False se l'anno e' stato dedotto
    grezzo: str


def _anno_dedotto(mese: int, riferimento: date) -> int:
    avvio = anno_scolastico(riferimento)
    return avvio if mese >= 8 else avvio + 1


def trova_date(testo: str, riferimento: date) -> list[DataTrovata]:
    """Tutte le date riconoscibili nel testo, in ordine di posizione."""
    trovate: list[DataTrovata] = []
    for m in RE_DATA_NUM.finditer(testo):
        g, me, a = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= g <= 31 and 1 <= me <= 12):
            continue
        if a is None:
            # senza anno un "12.30" e' quasi sempre un orario: serve un contesto da data
            # (30/06 e 31/08 no: sono le date in cui finiscono le supplenze lunghe)
            prima = testo[max(0, m.start() - 12):m.start()].lower()
            if (g, me) not in FINI_ANNO and not re.search(r"(\bal|\bdal|\bil|\bdel|\bentro|fino a)l?\s*$", prima):
                continue
            anno, scritto = _anno_dedotto(me, riferimento), False
        else:
            anno = int(a) if len(a) == 4 else 2000 + int(a)
            scritto = True
        if not 2020 <= anno <= 2040:
            continue
        try:
            trovate.append(DataTrovata(m.start(), m.end(), date(anno, me, g), scritto, m.group(0)))
        except ValueError:
            continue
    for m in RE_DATA_TESTO.finditer(testo):
        g, me = int(m.group(1)), MESI[m.group(2).lower()]
        a = m.group(3)
        anno = int(a) if a else _anno_dedotto(me, riferimento)
        if not (1 <= g <= 31 and 2020 <= anno <= 2040):
            continue
        try:
            trovate.append(DataTrovata(m.start(), m.end(), date(anno, me, g), bool(a), m.group(0)))
        except ValueError:
            continue
    trovate.sort(key=lambda d: d.inizio)
    # una data scritta due volte nello stesso punto (numerica e testuale) conta una volta
    uniche: list[DataTrovata] = []
    for d in trovate:
        if uniche and d.inizio < uniche[-1].fine:
            continue
        uniche.append(d)
    return uniche


def trova_ora(testo: str) -> tuple[int, int] | None:
    """Primo orario del tipo "ore 14:00" nel frammento, come (ore, minuti)."""
    m = RE_ORA.search(testo)
    if not m:
        return None
    ore, minuti = int(m.group(1)), int(m.group(2) or 0)
    if ore > 24 or minuti > 59:
        return None
    return (0, 0) if ore == 24 else (ore, minuti)


def iso(valore: date | datetime | None) -> str | None:
    if valore is None:
        return None
    if isinstance(valore, datetime):
        return valore.strftime("%Y-%m-%dT%H:%M")
    return valore.isoformat()
