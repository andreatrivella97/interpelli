"""Siti WordPress: ricerca delle notizie che parlano di interpello tramite l'interfaccia del sito.

Restituisce data, titolo e testo della notizia in un'unica richiesta; il PDF allegato viene
poi letto come per le altre fonti.
"""
from __future__ import annotations

import html as html_lib
import json
from datetime import date, datetime

from ..classifica import escluso, sembra_avviso
from ..documenti import testo_pagina
from ..testo import pulisci
from . import Voce


def estrai(corpo: str, url_base: str) -> list[Voce]:
    try:
        notizie = json.loads(corpo)
    except ValueError:
        return []
    voci: list[Voce] = []
    for notizia in notizie if isinstance(notizie, list) else []:
        titolo = pulisci(html_lib.unescape((notizia.get("title") or {}).get("rendered", "")))
        if not sembra_avviso(titolo):
            continue
        testo, allegati = testo_pagina("<main>" + (notizia.get("content") or {}).get("rendered", "") + "</main>", url_base)
        pubblicato = None
        try:
            pubblicato = datetime.fromisoformat(notizia.get("date", "")).date()
        except ValueError:
            pass
        utili = [a for a in allegati if not escluso(a[0])]
        voci.append(Voce(
            titolo=titolo, url=notizia.get("link") or url_base, pagina=url_base, fonte="wp",
            chiave=(notizia.get("link") or f"wp:{notizia.get('id')}").rstrip("/"),
            contesto=testo[:400], pubblicato=pubblicato, testo=testo,
            documento=utili[0][1] if utili else None,
            nome_file=utili[0][1].rsplit("/", 1)[-1] if utili else ""))
    return voci


def leggi(scuola: dict, fonte: dict, rete, oggi: date) -> list[Voce]:
    base = (fonte.get("url") or scuola["sito"]).rstrip("/")
    risposta = rete.scarica(base + "/wp-json/wp/v2/posts?search=interpell&per_page=20&orderby=date"
                                   "&_fields=id,date,link,title,content")
    return estrai(risposta.testo, base + "/")
