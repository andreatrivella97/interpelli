"""Lettura del testo di un avviso: PDF (anche scansionati o firmati), pagine web, file Word."""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from .classifica import escluso
from .rete import ErroreRete, Rete, leggibile
from .testo import pulisci

RE_ESTENSIONE_DOC = re.compile(r"\.(pdf|p7m|docx?|odt)(\b|$)", re.IGNORECASE)
RE_LINK_DOCUMENTO = re.compile(
    r"\.(pdf|p7m|docx?|odt)(\?|$)|download|/allegat|/assets/files/|/wp-content/uploads/|/uploads/|"
    r"UploadDownloadHandler|view_doc|/documento/|/Documenti/|/public/files/", re.IGNORECASE)


RE_NOTIZIE_CORRELATE = re.compile(
    r"^(?:circolari, notizie, argomenti correlati|(?:articoli|notizie|contenuti|argomenti) correlat[ei]"
    r"|potrebbe(?:ro)? interessarti|altre notizie|ultime notizie|leggi anche)\b", re.IGNORECASE | re.MULTILINE)


@dataclass
class Documento:
    testo: str = ""
    come: str = "titolo"          # "testo" | "ocr" | "pagina" | "non_leggibile" | "errore"
    nota: str | None = None
    allegati: list[tuple[str, str]] = field(default_factory=list)   # (titolo, url)


class Lettore:
    def __init__(self, rete: Rete, max_ocr: int = 25):
        self.rete = rete
        self.ocr_rimasti = max_ocr
        self.ha_pdftotext = shutil.which("pdftotext") is not None
        self.ha_ocr = shutil.which("pdftoppm") is not None and shutil.which("tesseract") is not None
        self.lingua_ocr = "ita"
        if self.ha_ocr:
            try:
                lingue = subprocess.run(["tesseract", "--list-langs"], capture_output=True, timeout=20).stdout.decode()
                if "ita" not in lingue.split():
                    self.lingua_ocr = "eng"
            except (subprocess.SubprocessError, OSError):
                self.ha_ocr = False

    # ---- ingresso principale --------------------------------------------------------------
    def leggi(self, url: str, *, sessione=None, intestazioni=None, segui_allegati: bool = True) -> Documento:
        if not leggibile(url):
            return Documento(come="non_leggibile", nota="allegato su un portale che non consente la lettura automatica")
        try:
            r = self.rete.scarica(url, sessione=sessione, intestazioni=intestazioni)
        except ErroreRete as e:
            return Documento(come="errore", nota=str(e))
        documento = self.da_byte(r.corpo, r.tipo, r.url, r.testo if "html" in r.tipo.lower() else None,
                                 sessione=sessione, segui_allegati=segui_allegati)
        self.rete.conserva_testo(url, documento.come, documento.nota, documento.testo)
        return documento

    def da_byte(self, corpo: bytes, tipo: str, url: str, html: str | None = None, *, sessione=None,
                segui_allegati: bool = True) -> Documento:
        tipo = (tipo or "").lower()
        inizio = corpo[:1024]
        if b"%PDF" in corpo[:8192] or "pdf" in tipo:
            return self._pdf(corpo)
        if inizio[:2] == b"PK":
            testo = testo_docx(corpo)
            return Documento(testo=testo, come="testo" if testo else "non_leggibile")
        if html is not None or b"<html" in inizio.lower() or "html" in tipo:
            html = html if html is not None else corpo.decode("utf-8", errors="replace")
            testo, allegati = testo_pagina(html, url)
            doc = Documento(testo=testo, come="pagina", allegati=allegati)
            if segui_allegati:
                # il testo vero dell'avviso sta quasi sempre nel PDF allegato alla notizia
                scelti = [a for a in allegati if not escluso(a[0])][:2]
                for titolo, link in scelti:
                    figlio = self.leggi(link, sessione=sessione, segui_allegati=False)
                    if figlio.testo:
                        doc.testo += "\n\n" + figlio.testo
                        doc.come = figlio.come if figlio.come in ("testo", "ocr") else doc.come
                    elif figlio.nota and not doc.nota:
                        doc.nota = figlio.nota
            return doc
        return Documento(come="non_leggibile", nota=f"formato non riconosciuto ({tipo or 'sconosciuto'})")

    # ---- PDF ------------------------------------------------------------------------------
    def _pdf(self, corpo: bytes) -> Documento:
        i = corpo.find(b"%PDF")
        if i > 0:                      # PDF dentro una busta di firma (.p7m)
            fine = corpo.rfind(b"%%EOF")
            corpo = corpo[i:fine + 5] if fine > i else corpo[i:]
        with tempfile.TemporaryDirectory() as cartella:
            file = Path(cartella) / "avviso.pdf"
            file.write_bytes(corpo)
            testo = self._testo_pdf(file)
            if len(re.sub(r"[^A-Za-zÀ-ÿ]", "", senza_timbro(testo))) >= 250:
                return Documento(testo=testo, come="testo")
            if self.ha_ocr and self.ocr_rimasti > 0:
                self.ocr_rimasti -= 1
                letto = self._ocr(file, Path(cartella))
                if len(re.sub(r"[^A-Za-zÀ-ÿ]", "", letto)) >= 250:
                    return Documento(testo=testo + "\n" + letto, come="ocr")
            if self.ha_ocr and self.ocr_rimasti <= 0:
                return Documento(testo=testo, come="in_attesa", nota="PDF scansionato: sara' letto al prossimo controllo")
            nota = "PDF senza testo (scansione)" if self.ha_ocr else "PDF senza testo (scansione), lettura ottica non disponibile"
            return Documento(testo=testo, come="non_leggibile", nota=nota)

    def _testo_pdf(self, file: Path) -> str:
        if self.ha_pdftotext:
            try:
                esito = subprocess.run(["pdftotext", "-layout", "-l", "6", str(file), "-"],
                                       capture_output=True, timeout=60)
                return esito.stdout.decode("utf-8", errors="replace")
            except (subprocess.SubprocessError, OSError):
                pass
        try:
            from pypdf import PdfReader
            lettore = PdfReader(str(file))
            return "\n".join((pagina.extract_text() or "") for pagina in lettore.pages[:6])
        except Exception:  # noqa: BLE001 - un PDF rotto non deve fermare tutto
            return ""

    def _ocr(self, file: Path, cartella: Path) -> str:
        try:
            subprocess.run(["pdftoppm", "-r", "170", "-l", "2", "-gray", "-png", str(file), str(cartella / "p")],
                           capture_output=True, timeout=90, check=True)
            pezzi = []
            for immagine in sorted(cartella.glob("p*.png")):
                esito = subprocess.run(["tesseract", str(immagine), "-", "-l", self.lingua_ocr, "--psm", "6"],
                                       capture_output=True, timeout=120)
                pezzi.append(esito.stdout.decode("utf-8", errors="replace"))
            return "\n".join(pezzi)
        except (subprocess.SubprocessError, OSError):
            return ""


def senza_timbro(testo: str) -> str:
    """Toglie le righe del timbro di protocollo, che da sole farebbero sembrare leggibile una scansione."""
    righe = [r for r in testo.splitlines() if not re.search(r"C\.F\.|C\.M\.|Prot\.\s*\d|AOO|Segreteria", r)]
    return "\n".join(righe)


def testo_docx(corpo: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(corpo)) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError):
        return ""
    xml = re.sub(r"</w:p>", "\n", xml)
    return pulisci(re.sub(r"<[^>]+>", "", xml))


def radice_contenuto(soup: BeautifulSoup, selettore: str | None = None):
    """La parte della pagina con il contenuto, senza menu, testata e pie' di pagina."""
    for etichetta in soup(["script", "style", "noscript", "svg", "template", "iframe"]):
        etichetta.decompose()
    if selettore:
        scelto = soup.select_one(selettore)
        if scelto:
            return scelto
    radice = None
    for candidato in ("main", "#main-content", "#main", "#content", "article", ".main-content", ".container-main"):
        radice = soup.select_one(candidato)
        if radice and len(radice.get_text(strip=True)) > 200:
            break
        radice = None
    radice = radice or soup.body or soup
    for etichetta in radice.select("nav, header, footer, aside, .breadcrumb, .cookie, .share, .condividi"):
        etichetta.decompose()
    return radice


def testo_pagina(html: str, url: str) -> tuple[str, list[tuple[str, str]]]:
    soup = BeautifulSoup(html, "html.parser")
    radice = radice_contenuto(soup)
    allegati, visti = [], set()
    for a in radice.find_all("a", href=True):
        link = urljoin(url, a["href"].strip())
        nome = unquote(urlparse(link).path.rsplit("/", 1)[-1])
        if not (RE_ESTENSIONE_DOC.search(nome) or re.search(r"download|allegat|/assets/files/", link, re.IGNORECASE)):
            continue
        if link in visti:
            continue
        visti.add(link)
        allegati.append((pulisci(a.get_text(" ", strip=True)) or nome, link))
    testo = pulisci(radice.get_text("\n", strip=True))
    # sotto la notizia molti siti elencano altre notizie: i loro titoli confonderebbero la lettura
    coda = RE_NOTIZIE_CORRELATE.search(testo, 150)
    if coda:
        testo = testo[:coda.start()]
    return testo[:20000], allegati
