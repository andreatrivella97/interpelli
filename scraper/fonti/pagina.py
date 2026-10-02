"""Fonte generica: una pagina del sito della scuola che elenca gli interpelli come link.

Funziona con elenchi di PDF, tabelle, archivi di notizie e risultati di ricerca. Per ogni
link che parla di interpello ricava un titolo leggibile e, se la riga li riporta, la data
di scadenza e l'esito ("CHIUSO", "ASSEGNATO", ...).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import unquote, urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from ..classifica import RE_AVVISO, escluso
from ..documenti import RE_LINK_DOCUMENTO, radice_contenuto
from ..testo import MESI, da_nome_file, pulisci, trova_date, trova_ora
from . import Voce

I = re.IGNORECASE
RE_CONDIVISIONE = re.compile(
    r"facebook\.|twitter\.|linkedin\.|whatsapp|t\.me/|^mailto:|^tel:|^javascript:|sharer|classroom\.google|[?&]pdf=true", I)
RE_GENERICO = re.compile(
    r"^(download|scarica\w*(\s+\w+){0,3}|visualizza(\s+\w+){0,3}|leggi(\s+di\s+pi[uù]| tutto)?|apri(\s+\w+){0,3}|vai(\s+a.*)?"
    r"|file\s+pdf|pdf|allegat[oi]|link|qui|accedi|dettagli\w*|continua.*|vedi.*|\d+)?$", I)
# voci di menu e pagine di servizio: parlano di interpelli ma non sono un avviso
RE_ETICHETTA = re.compile(
    r"^(invio\s+)?(mad\s*(/|e)\s*)?interpell[oi](\s*(/|e)\s*mad)?(\s*\(ex\s+mad\))?(\s*-?\s*ricerca\s+\w+)?(\s+docenti)?$", I)
RE_URL_DI_SERVIZIO = re.compile(r"/argomento/|/tag/|/categor|/servizi?o?/|/tipologia|/page/\d|[?&]s=|/cerca\b|/pagine?/", I)
RE_ESITO = re.compile(r"\b(CHIUS[OA]|ASSEGNAT[OAI]|DESERT[OA]|ANNULLAT[OA]|CONCLUS[OA]|REVOCAT[OA])\b")
RE_SCARTI_TITOLO = re.compile(
    r"\bFile\s+PDF\b|Contatore\s+click\s*:?\s*\d*|\bpdf\s*-\s*\d+\s*kb\b|\b\d+(?:[.,]\d+)?\s*(?:kb|mb)\b|\bDownload\b|Leggi\s+di\s+pi[uù]", I)
RE_DATA_SCHEDA = re.compile(r"^\s*(20\d{2})\s+(\d{1,2})\s+([A-Za-z]{3,4})\b\.?\s*")     # "2026 30 Set" nelle schede
MAX_VOCI = 60


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _blocco(a):
    """Il contenitore piu' piccolo che descrive il link: riga di tabella, voce di elenco, scheda."""
    for antenato in a.parents:
        nome = antenato.name
        if nome in ("main", "body", "section", "table", "tbody", "ul", "ol", "html"):
            break
        testo = antenato.get_text(" ", strip=True)
        if nome in ("tr", "li", "article"):
            return antenato if len(testo) <= 900 else None
        classi = " ".join(antenato.get("class") or [])
        if nome == "div" and re.search(r"card|item|media|allegat|document|post|entry|result|news|scheda", classi, I):
            if len(testo) <= 700:
                return antenato
    genitore = a.parent
    return genitore if genitore is not None and len(genitore.get_text(" ", strip=True)) <= 500 else None


def _titolo(testo_link: str, testo_blocco: str, nome_file: str) -> str:
    candidato = testo_link
    if not candidato or RE_GENERICO.match(candidato) or len(candidato) < 6:
        candidato = RE_SCARTI_TITOLO.sub(" ", testo_blocco)
    if not candidato.strip() or RE_GENERICO.match(candidato.strip()):
        candidato = nome_file
    candidato = RE_SCARTI_TITOLO.sub(" ", candidato)
    if "_" in candidato or re.search(r"\.(pdf|p7m|pades|docx?)\b", candidato, I):
        candidato = da_nome_file(candidato)
    candidato = re.sub(r"https?://\S+", " ", candidato)
    candidato = re.sub(r"\s+", " ", candidato).strip(" -|·")
    # le schede ripetono il titolo all'inizio del sommario: basta una volta
    for k in range(len(candidato) // 2, 11, -1):
        testa = candidato[:k].strip()
        if candidato[k:].lstrip().lower().startswith(testa.lower()):
            candidato = candidato[k:].lstrip()
            break
    return candidato[:260]


def _date_di_riga(riga, cella_link, oggi: date) -> tuple[date | None, datetime | None]:
    """Le date scritte nelle altre celle della riga: (pubblicazione, scadenza).

    Se la tabella ha una colonna "scadenza" la data e' il termine per candidarsi, altrimenti
    e' la data dell'avviso.
    """
    tabella = riga.find_parent("table")
    if tabella is None:
        return None, None
    celle = [c for c in riga.find_all(["td", "th"]) if c is not cella_link]
    testo = pulisci(" ".join(c.get_text(" ", strip=True) for c in celle))
    prefisso = "il "
    date_trovate = [d for d in trova_date(prefisso + testo, oggi) if d.anno_scritto]
    if not date_trovate:
        return None, None
    giorno = date_trovate[0].giorno
    if not re.search(r"scad", tabella.get_text(" ", strip=True)[:1500], I):
        return giorno, None
    resto = testo[max(0, date_trovate[0].fine - len(prefisso)):][:30]
    ora = trova_ora(resto)
    if ora is None:
        m = re.search(r"\b(\d{1,2})\s?[:.]\s?(\d{2})\b", resto)
        if m and int(m.group(1)) <= 23 and int(m.group(2)) <= 59:
            ora = (int(m.group(1)), int(m.group(2)))
    ore, minuti = ora or (23, 59)
    return None, datetime(giorno.year, giorno.month, giorno.day, ore, minuti)


def estrai(html: str, url_pagina: str, fonte: dict, oggi: date) -> list[Voce]:
    soup = BeautifulSoup(html, "html.parser")
    radice = radice_contenuto(soup, fonte.get("selettore"))
    filtro = re.compile(fonte["filtro"], I) if fonte.get("filtro") else None
    escludi = re.compile(fonte["escludi"], I) if fonte.get("escludi") else None
    pagina_pulita = urldefrag(url_pagina)[0].rstrip("/")
    voci: dict[str, Voce] = {}

    for a in radice.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or RE_CONDIVISIONE.search(href):
            continue
        url = urldefrag(urljoin(url_pagina, href))[0]
        if not url.startswith("http") or url.rstrip("/") == pagina_pulita:
            continue
        testo_link = pulisci(a.get_text(" ", strip=True)) or pulisci(a.get("title") or "")
        blocco = _blocco(a)
        testo_blocco = pulisci(blocco.get_text(" ", strip=True)) if blocco is not None else ""
        nome_file = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
        e_documento = bool(RE_LINK_DOCUMENTO.search(url))
        descrizione = f"{testo_link} {nome_file}"

        if filtro:
            if not filtro.search(f"{descrizione} {testo_blocco}"):
                continue
        elif fonte.get("tutti_i_documenti"):
            if not e_documento:
                continue
        elif not (RE_AVVISO.search(descrizione) or (e_documento and RE_AVVISO.search(testo_blocco))):
            continue
        if escludi and escludi.search(f"{descrizione} {testo_blocco}"):
            continue
        if RE_ETICHETTA.match(testo_link) and not e_documento:
            continue
        if not e_documento and _host(url) != _host(url_pagina):
            continue      # rimando a un portale esterno (modulo di candidatura), non un avviso
        if not e_documento and RE_URL_DI_SERVIZIO.search(urlparse(url).path + "?" + urlparse(url).query):
            continue
        titolo = _titolo(testo_link, testo_blocco, nome_file)
        if escluso(titolo) or (e_documento and escluso(da_nome_file(nome_file)) and not RE_AVVISO.search(testo_link)):
            continue

        pubblicato = None
        m = RE_DATA_SCHEDA.match(titolo)
        if m and m.group(3).lower() in MESI:
            try:
                pubblicato = date(int(m.group(1)), MESI[m.group(3).lower()], int(m.group(2)))
            except ValueError:
                pubblicato = None
            titolo = _titolo(titolo[m.end():], "", nome_file)
        if pubblicato is None:
            m = re.search(r"/(20\d{2})/(\d{2})/(\d{2})/", url)        # le notizie WordPress portano la data nell'indirizzo
            if m:
                try:
                    pubblicato = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    pass

        chiuso, scadenza = None, None
        riga = a.find_parent("tr")
        if riga is not None:
            cella = a.find_parent(["td", "th"])
            altre = " ".join(c.get_text(" ", strip=True) for c in riga.find_all(["td", "th"]) if c is not cella)
            m = RE_ESITO.search(altre)
            chiuso = m.group(1).capitalize() if m else None
            data_riga, scadenza = _date_di_riga(riga, cella, oggi)
            pubblicato = pubblicato or data_riga
        elif blocco is not None:
            m = RE_ESITO.search(testo_blocco.replace(testo_link, " "))
            chiuso = m.group(1).capitalize() if m else None

        chiave = url if e_documento or "?" in url else url.rstrip("/")
        if chiave in voci:
            # lo stesso documento linkato due volte (icona e titolo): si tiene il titolo piu' ricco
            if len(titolo) > len(voci[chiave].titolo):
                voci[chiave].titolo = titolo
            continue
        voci[chiave] = Voce(
            titolo=titolo, url=url, pagina=url_pagina, fonte="pagina", chiave=chiave,
            nome_file=nome_file if e_documento else "", contesto=testo_blocco[:400],
            pubblicato=pubblicato, scadenza=scadenza, chiuso=chiuso)
        if len(voci) >= int(fonte.get("max", MAX_VOCI)):
            break

    if fonte.get("righe"):
        voci.update(_righe_senza_link(radice, url_pagina, oggi, set(v.titolo for v in voci.values())))
    return list(voci.values())


def _righe_senza_link(radice, url_pagina: str, oggi: date, gia_visti: set[str]) -> dict[str, Voce]:
    """Tabelle in cui ogni riga e' un interpello ma senza link (protocollo, scadenza, esito)."""
    trovate: dict[str, Voce] = {}
    for tabella in radice.find_all("table"):
        if not RE_AVVISO.search(tabella.get_text(" ", strip=True)[:600]):
            continue
        for riga in tabella.find_all("tr"):
            celle = riga.find_all(["td", "th"])
            if len(celle) < 2 or riga.find("a", href=True):
                continue
            prima = pulisci(celle[0].get_text(" ", strip=True))
            if len(prima) < 8 or not re.search(r"\d", prima) or re.search(r"^num|^data|^esito|scadenza$", prima, I):
                continue
            if prima in gia_visti:
                continue
            resto = " ".join(c.get_text(" ", strip=True) for c in celle[1:])
            m = RE_ESITO.search(resto)
            trovate["riga:" + prima] = Voce(
                titolo="Interpello " + prima, url=url_pagina, pagina=url_pagina, fonte="pagina",
                chiave="riga:" + prima, contesto=pulisci(riga.get_text(" ", strip=True))[:400],
                scadenza=_date_di_riga(riga, celle[0], oggi)[1], chiuso=m.group(1).capitalize() if m else None)
    return trovate


def leggi(scuola: dict, fonte: dict, rete, oggi: date) -> list[Voce]:
    risposta = rete.scarica(fonte["url"])
    return estrai(risposta.testo, risposta.url, fonte, oggi)
