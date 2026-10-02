"""Memoria tra un controllo e l'altro: che cosa e' gia' stato visto, letto e quando.

L'archivio (stato/archivio.json) conserva tutti gli avvisi incontrati; la pagina riceve
solo quelli ancora utili (docs/dati.json).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from .fonti import Voce
from .testo import chiave as chiave_testo

VERSIONE = 1
GIORNI_SCADUTI_VISIBILI = 7       # un avviso scaduto resta in pagina per questi giorni
GIORNI_SENZA_SCADENZA = 14        # senza termine noto, si mostra per questi giorni dalla pubblicazione
GIORNI_IN_ARCHIVIO = 150          # dopo, gli avvisi spariti dai siti vengono dimenticati


def chiave_url(url: str) -> str:
    """Indirizzo senza le parti che cambiano da una lettura all'altra (es. "?x49255" anti-cache)."""
    parti = urlparse(url)
    percorso = parti.path.rstrip("/")
    query = "" if re.search(r"\.(pdf|p7m|docx?|odt)$", percorso, re.IGNORECASE) else parti.query
    return f"{parti.netloc.lower().removeprefix('www.')}{percorso}{'?' + query if query else ''}"


def id_avviso(id_scuola: str, voce: Voce) -> str:
    base = voce.chiave if voce.chiave and not voce.chiave.startswith("http") else chiave_url(voce.chiave or voce.url)
    return hashlib.sha1(f"{id_scuola}|{base}".encode()).hexdigest()[:12]


def _data(valore: str | None) -> date | None:
    return date.fromisoformat(valore[:10]) if valore else None


def _momento(valore: str | None) -> datetime | None:
    return datetime.fromisoformat(valore) if valore else None


class Archivio:
    def __init__(self, percorso: Path):
        self.percorso = percorso
        self.avvisi: dict[str, dict] = {}
        self.scuole: dict[str, dict] = {}
        if percorso.exists():
            dati = json.loads(percorso.read_text(encoding="utf-8"))
            self.avvisi = dati.get("avvisi", {})
            self.scuole = dati.get("scuole", {})

    def di_scuola(self, id_scuola: str) -> dict[str, dict]:
        return {k: v for k, v in self.avvisi.items() if v.get("scuola") == id_scuola}

    def salva(self, ora: datetime) -> None:
        limite = (ora - timedelta(days=GIORNI_IN_ARCHIVIO)).isoformat()
        self.avvisi = {k: v for k, v in self.avvisi.items()
                       if v.get("presente") or (v.get("ultima_vista") or "") >= limite}
        self.percorso.parent.mkdir(parents=True, exist_ok=True)
        self.percorso.write_text(json.dumps(
            {"versione": VERSIONE, "scuole": self.scuole, "avvisi": self.avvisi},
            ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def chiavi_di_confronto(voce: Voce) -> tuple[str | None, str | None]:
    """(chiave del nome del file, chiave del titolo) per riconoscere lo stesso avviso da due fonti."""
    file = chiave_testo(voce.nome_file) if voce.nome_file else ""
    titolo = chiave_testo(voce.titolo)
    return (file if len(file) >= 12 else None, titolo if len(titolo) >= 18 else None)


def stesso_avviso(record: dict, voce: Voce) -> bool:
    file, titolo = chiavi_di_confronto(voce)
    if file and file in (record.get("chiavi_file") or []):
        return True
    if voce.fonte in (record.get("fonti") or []):
        return False        # dentro la stessa fonte due titoli uguali sono due avvisi diversi
    if titolo and titolo == record.get("chiave_titolo"):
        a, b = _data(record.get("pubblicato")), voce.pubblicato
        return a is None or b is None or abs((a - b).days) <= 2
    return False


def da_mostrare(record: dict, ora: datetime) -> bool:
    """Tiene gli avvisi aperti o scaduti da poco; lascia fuori lo storico delle pagine."""
    oggi = ora.date()
    if record.get("storico") or record.get("escluso"):
        return False
    scadenza = _momento(record.get("scadenza"))
    if scadenza:
        return scadenza >= ora - timedelta(days=GIORNI_SCADUTI_VISIBILI)
    riferimento = _data(record.get("pubblicato"))
    if riferimento is None and not record.get("iniziale"):
        riferimento = _data(record.get("prima_vista"))
    if riferimento:
        return riferimento >= oggi - timedelta(days=GIORNI_SENZA_SCADENZA)
    # gia' presente al primo controllo e senza date: si mostra finche' resta in pagina e non e' chiuso
    fini = [_data(p.get("fine")) for p in record.get("posti", []) if p.get("fine")]
    if fini and max(fini) < oggi:
        return False
    return bool(record.get("presente")) and not record.get("chiuso")
