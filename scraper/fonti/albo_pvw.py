"""Albo online dei siti ospitati da Spaggiari, interrogato con la ricerca "interpell".

L'albo riporta protocollo, oggetto e data di pubblicazione. Gli allegati stanno su un
portale che non consente la lettura automatica: l'avviso viene quindi classificato dal
solo oggetto, e chi apre la pagina puo' scaricare il PDF dal link.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..classifica import sembra_avviso
from ..testo import pulisci, trova_date
from . import Voce


def estrai(html: str, url_pagina: str, oggi: date) -> list[Voce]:
    soup = BeautifulSoup(html, "html.parser")
    voci: list[Voce] = []
    for elemento in soup.select(".at-item"):
        intestazione = elemento.select_one(".media-heading")
        if intestazione is None:
            continue
        titolo = pulisci(intestazione.get_text(" ", strip=True))
        if not sembra_avviso(titolo):
            continue
        testo = pulisci(elemento.get_text(" ", strip=True))
        pubblicato = None
        m = re.search(r"Pubblicato il:\s*(\S+)", testo)
        if m:
            trovate = trova_date("il " + m.group(1), oggi)
            pubblicato = trovate[0].giorno if trovate else None
        protocollo = re.search(r"Protocollo\s+(\S+)", testo)
        allegato = next((urljoin(url_pagina, a["href"]) for a in elemento.find_all("a", href=True)
                         if "download=1" not in a["href"]), None)
        numero = elemento.select_one(".media-left h3")
        chiave = f"albo:{protocollo.group(1) if protocollo else ''}:{numero.get_text(strip=True) if numero else titolo[:60]}"
        voci.append(Voce(titolo=titolo, url=allegato or url_pagina, pagina=url_pagina, fonte="albo", chiave=chiave,
                         contesto=testo[:400], pubblicato=pubblicato))
    return voci


def leggi(scuola: dict, fonte: dict, rete, oggi: date) -> list[Voce]:
    base = fonte.get("url") or scuola["sito"].rstrip("/") + "/albo-online"
    risposta = rete.scarica(base + "?categoria=&cerca=interpell&storico=&aoo=")
    return estrai(risposta.testo, base, oggi)
