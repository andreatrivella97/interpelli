"""Accesso ai siti: una richiesta alla volta per server, con pause e un secondo tentativo."""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

UA = ("Mozilla/5.0 (compatible; interpelli-monitor/1.0; "
      "+https://github.com/andreatrivella97/interpelli)")
STATI_DA_RIPROVARE = {429, 500, 502, 503, 504, 509}
# portali che rifiutano le letture automatiche: inutile provarci, il link resta per chi apre la pagina
HOST_NON_LEGGIBILI = ("web.spaggiari.eu", "trasparenzascuole.it", "www.mim.gov.it", "docs.google.com", "forms.gle",
                      "forms.cloud.microsoft", "forms.office.com")


class ErroreRete(Exception):
    pass


@dataclass
class Risposta:
    url: str
    stato: int
    tipo: str
    corpo: bytes
    codifica: str | None = None

    @property
    def testo(self) -> str:
        for codifica in (self.codifica, "utf-8", "cp1252"):
            if not codifica:
                continue
            try:
                return self.corpo.decode(codifica)
            except (UnicodeDecodeError, LookupError):
                continue
        return self.corpo.decode("utf-8", errors="replace")


def leggibile(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return not any(host == h or host.endswith("." + h) for h in HOST_NON_LEGGIBILI)


class Rete:
    def __init__(self, pausa: float = 2.0, attesa: float = 35.0):
        self.pausa = pausa
        self.attesa = attesa
        self._ip: dict[str, str] = {}
        self._blocchi: dict[str, threading.Lock] = {}
        self._ultima: dict[str, float] = {}
        self._guardia = threading.Lock()
        self.richieste = 0
        # per la messa a punto: con INTERPELLI_SALVA=cartella ogni risposta viene conservata cosi' com'e'
        self._copie = Path(os.environ["INTERPELLI_SALVA"]) if os.environ.get("INTERPELLI_SALVA") else None
        if self._copie:
            self._copie.mkdir(parents=True, exist_ok=True)

    def nuova_sessione(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
        return s

    def _gruppo(self, url: str) -> str:
        """Siti diversi sullo stesso server condividono la coda, cosi' non lo si sovraccarica."""
        host = urlparse(url).netloc
        with self._guardia:
            if host not in self._ip:
                try:
                    self._ip[host] = socket.gethostbyname(host.split(":")[0])
                except OSError:
                    self._ip[host] = host
            gruppo = self._ip[host]
            self._blocchi.setdefault(gruppo, threading.Lock())
        return gruppo

    def scarica(self, url: str, *, sessione: requests.Session | None = None, intestazioni: dict | None = None,
                max_byte: int = 8_000_000, tentativi: int = 2) -> Risposta:
        sessione = sessione or self.nuova_sessione()
        gruppo = self._gruppo(url)
        ultimo_errore = ""
        for tentativo in range(tentativi):
            with self._blocchi[gruppo]:
                attesa = self.pausa - (time.time() - self._ultima.get(gruppo, 0))
                if attesa > 0:
                    time.sleep(attesa)
                try:
                    self.richieste += 1
                    try:
                        r = sessione.get(url, timeout=self.attesa, headers=intestazioni, stream=True)
                    except requests.exceptions.SSLError:
                        # certificati configurati male su alcuni siti scolastici: si leggono solo avvisi pubblici
                        r = sessione.get(url, timeout=self.attesa, headers=intestazioni, stream=True, verify=False)
                    corpo = b""
                    for pezzo in r.iter_content(65536):
                        corpo += pezzo
                        if len(corpo) > max_byte:
                            break
                    r.close()
                except requests.exceptions.RequestException as e:
                    ultimo_errore = f"{type(e).__name__}"
                    continue
                finally:
                    self._ultima[gruppo] = time.time()
            if r.status_code in STATI_DA_RIPROVARE and tentativo + 1 < tentativi:
                ultimo_errore = f"risposta {r.status_code}"
                time.sleep(5)
                continue
            self._conserva(url, r.url, r.status_code, r.headers.get("content-type", ""), corpo)
            if r.status_code >= 400:
                raise ErroreRete(f"risposta {r.status_code} da {urlparse(url).netloc}")
            return Risposta(r.url, r.status_code, r.headers.get("content-type", ""), corpo, r.encoding)
        self._conserva(url, None, None, ultimo_errore or "nessuna risposta", b"")
        raise ErroreRete(f"{ultimo_errore or 'nessuna risposta'} da {urlparse(url).netloc}")

    def _conserva(self, url: str, finale: str | None, stato: int | None, tipo: str, corpo: bytes) -> None:
        if not self._copie:
            return
        nome = None
        e_pdf = b"%PDF" in corpo[:8192]
        if corpo and (not e_pdf or len(corpo) <= 300_000):       # i PDF grandi si riconoscono dal testo estratto
            estensione = "pdf" if e_pdf else "json" if "json" in tipo else "html" if "html" in tipo else "bin"
            nome = self._nome_copia(url) + "." + estensione
            (self._copie / nome).write_bytes(corpo[:1_500_000])
        with self._guardia, open(self._copie / "indice.jsonl", "a", encoding="utf-8") as indice:
            indice.write(json.dumps({"url": url, "finale": finale, "stato": stato, "tipo": tipo, "byte": len(corpo),
                                     "file": nome}, ensure_ascii=False) + "\n")

    @staticmethod
    def _nome_copia(url: str) -> str:
        return (re.sub(r"[^a-z0-9]+", "-", urlparse(url).netloc.lower()).strip("-") + "-"
                + hashlib.sha1(url.encode()).hexdigest()[:10])

    def conserva_testo(self, url: str, come: str, nota: str | None, testo: str) -> None:
        """Per la messa a punto: il testo ricavato da un documento, accanto alla copia della risposta."""
        if not self._copie:
            return
        (self._copie / "testi").mkdir(exist_ok=True)
        (self._copie / "testi" / (self._nome_copia(url) + ".txt")).write_text(
            f"{url}\nletto: {come}\nnota: {nota}\n{'-' * 60}\n{testo}", encoding="utf-8")

