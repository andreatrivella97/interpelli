"""Cruscotto pubblico "Interpelli" del portale di segreteria Axios.

Per ogni scuola che lo usa, il portale elenca gli interpelli aperti con data di
pubblicazione, oggetto, documento e periodo di validita': la fine del periodo e' il
termine esatto per candidarsi. E' la stessa pagina che la scuola indica ai candidati.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import date, datetime
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..testo import pulisci
from . import Voce

BASE = "https://serviziweb.axioscloud.it/"
PAGINA = BASE + "Pages/Interpelli/gestioneinterpelli.aspx?cid="
CRUSCOTTO = BASE + "Pages/Interpelli/INT_Ajax_Get.aspx?Action=INT_DASHBOARD"
DOCUMENTO = BASE + "Handlers/SD_UploadDownloadHandler.aspx"
# il portale identifica la scuola con il codice fiscale, offuscato con questa chiave fissa
_CHIAVE = bytes.fromhex("F582DBF5AA23E131913C63")
RE_MOMENTO = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})")


def codice_scuola(codice_fiscale: str) -> str:
    testo = ""
    for cifra, k in zip(codice_fiscale.encode(), _CHIAVE):
        b = bytes([cifra ^ k])
        try:
            testo += b.decode("cp1252")
        except UnicodeDecodeError:
            testo += b.decode("latin-1")
    return base64.b64encode(testo.encode("utf-8")).decode()


def indirizzo_pagina(codice_fiscale: str) -> str:
    return PAGINA + quote(codice_scuola(codice_fiscale))


def _momenti(testo: str) -> list[datetime]:
    return [datetime(int(a), int(m), int(g), int(h), int(mi)) for g, m, a, h, mi in RE_MOMENTO.findall(testo)]


def estrai(html: str, url_pagina: str, sessione=None) -> list[Voce]:
    soup = BeautifulSoup(html, "html.parser")
    tabella = soup.find("table", id="elenco-interpelli-attivi")
    if tabella is None:
        return []          # "procedura non disponibile": la scuola non ha interpelli attivi sul portale
    colonne = [pulisci(th.get_text(" ", strip=True)).lower() for th in tabella.select("thead th")]

    def indice(nome: str, predefinito: int) -> int:
        return next((i for i, c in enumerate(colonne) if nome in c), predefinito)

    i_id, i_pub, i_pers = indice("id", 0), indice("pubblicazione", 2), indice("personale", 5)
    i_ogg, i_doc, i_val = indice("oggetto", 7), indice("documento", 8), indice("validit", 9)
    voci: list[Voce] = []
    for riga in tabella.select("tbody tr"):
        celle = riga.find_all("td")
        if len(celle) <= max(i_ogg, i_val):
            continue
        oggetto = pulisci(celle[i_ogg].get_text(" ", strip=True))
        if not oggetto:
            continue
        pubblicazione = _momenti(celle[i_pub].get_text(" ", strip=True))
        validita = _momenti(celle[i_val].get_text(" ", strip=True))
        voce = Voce(
            titolo=oggetto, url=url_pagina, pagina=url_pagina, fonte="axios",
            chiave="axios:" + celle[i_id].get_text(strip=True),
            contesto=pulisci(riga.get_text(" ", strip=True))[:400],
            pubblicato=pubblicazione[0].date() if pubblicazione else None,
            scadenza=validita[-1] if len(validita) >= 2 else None,
            personale=pulisci(celle[i_pers].get_text(" ", strip=True)).lower() or None,
            candidatura=url_pagina, sessione=sessione, intestazioni={"Referer": url_pagina})
        collegamento = celle[i_doc].find("a", attrs={"data-doc": True})
        if collegamento is not None:
            try:
                dati = json.loads(base64.b64decode(collegamento["data-doc"]).decode("utf-8"))
                voce.nome_file = dati.get("source_file_name", "")
                voce.documento = (f"{DOCUMENTO}?CustomerID={quote(dati['codice_fiscale'])}&Folder={quote(dati['foler_name'])}"
                                  f"&file={quote(dati['storage_file_name'])}&faction=0000"
                                  f"&SourceFileName={quote(dati.get('source_file_name', 'avviso.pdf'))}")
            except (ValueError, KeyError):
                pass
        voci.append(voce)
    return voci


def leggi(scuola: dict, fonte: dict, rete, oggi: date) -> list[Voce]:
    url_pagina = indirizzo_pagina(str(fonte["cf"]))
    sessione = rete.nuova_sessione()
    rete.scarica(url_pagina, sessione=sessione)            # apre la sessione sul portale
    risposta = rete.scarica(CRUSCOTTO, sessione=sessione,
                            intestazioni={"X-Requested-With": "XMLHttpRequest", "Referer": url_pagina})
    return estrai(risposta.testo, url_pagina, sessione)
