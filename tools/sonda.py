#!/usr/bin/env python3
"""Sonda di sviluppo: scarica un elenco di indirizzi e salva le risposte grezze.

Uso:  python tools/sonda.py tools/sonda_urls.txt out

Serve solo durante la messa a punto, per vedere dal vero come sono fatti i siti
delle scuole. Non fallisce mai: ogni errore finisce nell'indice.
"""
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

UA = ("Mozilla/5.0 (compatible; interpelli-monitor/1.0; "
      "+https://github.com/andreatrivella97/interpelli)")
MAX_BYTES = 4_000_000
EXT = {"html": ".html", "json": ".json", "xml": ".xml", "pdf": ".pdf", "plain": ".txt"}


def estensione(content_type: str) -> str:
    for chiave, ext in EXT.items():
        if chiave in (content_type or ""):
            return ext
    return ".bin"


def scarica(sessione, url):
    info = {"url": url}
    inizio = time.time()
    try:
        try:
            r = sessione.get(url, timeout=40, allow_redirects=True)
        except requests.exceptions.SSLError as e:
            info["avviso_tls"] = str(e)[:200]
            r = sessione.get(url, timeout=40, allow_redirects=True, verify=False)
        corpo = r.content[:MAX_BYTES]
        info.update(
            stato=r.status_code,
            url_finale=r.url,
            tipo=r.headers.get("content-type", ""),
            server=r.headers.get("server", ""),
            link=r.headers.get("link", "")[:300],
            totale_wp=r.headers.get("x-wp-total", ""),
            byte=len(r.content),
            redirect=[h.status_code for h in r.history],
        )
        return info, corpo
    except Exception as e:  # noqa: BLE001
        info.update(errore=f"{type(e).__name__}: {e}"[:300])
        return info, b""
    finally:
        info["secondi"] = round(time.time() - inizio, 2)


def main():
    elenco, uscita = Path(sys.argv[1]), Path(sys.argv[2])
    (uscita / "pagine").mkdir(parents=True, exist_ok=True)
    sessione = requests.Session()
    sessione.headers.update({"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
    indice, ultimo_host = [], {}
    for riga in elenco.read_text(encoding="utf-8").splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#"):
            continue
        etichetta, _, url = riga.rpartition("|")
        etichetta, url = etichetta.strip(), url.strip()
        host = urlparse(url).netloc
        attesa = 1.0 - (time.time() - ultimo_host.get(host, 0))
        if attesa > 0:
            time.sleep(attesa)
        info, corpo = scarica(sessione, url)
        ultimo_host[host] = time.time()
        info["etichetta"] = etichetta
        if corpo:
            nome = re.sub(r"[^a-z0-9]+", "-", (etichetta or host).lower()).strip("-")[:60]
            nome += "-" + hashlib.sha1(url.encode()).hexdigest()[:8] + estensione(info.get("tipo", ""))
            (uscita / "pagine" / nome).write_bytes(corpo)
            info["file"] = "pagine/" + nome
        indice.append(info)
        print(info.get("stato", "ERR"), info.get("byte", 0), url, info.get("errore", ""), flush=True)
    (uscita / "indice.json").write_text(json.dumps(indice, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
