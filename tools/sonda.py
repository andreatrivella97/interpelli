#!/usr/bin/env python3
"""Sonda di sviluppo: scarica un elenco di indirizzi e salva le risposte grezze.

Uso:  python tools/sonda.py tools/sonda_urls.txt out

Serve solo durante la messa a punto, per vedere dal vero come sono fatti i siti
delle scuole. Non fallisce mai: ogni errore finisce nell'indice.
"""
import hashlib
import json
import re
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import requests

UA = ("Mozilla/5.0 (compatible; interpelli-monitor/1.0; "
      "+https://github.com/andreatrivella97/interpelli)")
UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/140.0.0.0 Safari/537.36")
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


PAUSA = 2.5
_ip = {}


def gruppo_di(host):
    """Siti diversi ospitati sullo stesso server finiscono nella stessa coda."""
    if host not in _ip:
        try:
            _ip[host] = socket.gethostbyname(host)
        except OSError:
            _ip[host] = host
    return _ip[host]


def lavora_host(righe, uscita):
    """Scarica in sequenza gli indirizzi di uno stesso sito, con una pausa tra l'uno e l'altro."""
    sessione = requests.Session()
    sessione.headers.update({"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
    risultati = []
    for n, (posizione, etichetta, url) in enumerate(righe):
        if n:
            time.sleep(PAUSA)
        if etichetta.endswith("@browser"):
            sessione.headers["User-Agent"] = UA_BROWSER
        else:
            sessione.headers["User-Agent"] = UA
        info, corpo = scarica(sessione, url)
        info["etichetta"] = etichetta
        if corpo:
            nome = re.sub(r"[^a-z0-9]+", "-", (etichetta or urlparse(url).netloc).lower()).strip("-")[:60]
            nome += "-" + hashlib.sha1(url.encode()).hexdigest()[:8] + estensione(info.get("tipo", ""))
            (uscita / "pagine" / nome).write_bytes(corpo)
            info["file"] = "pagine/" + nome
        print(info.get("stato", "ERR"), info.get("byte", 0), url, info.get("errore", ""), flush=True)
        risultati.append((posizione, info))
    return risultati


def main():
    elenco, uscita = Path(sys.argv[1]), Path(sys.argv[2])
    (uscita / "pagine").mkdir(parents=True, exist_ok=True)
    per_host = {}
    posizione = 0
    for riga in elenco.read_text(encoding="utf-8").splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#"):
            continue
        etichetta, _, url = riga.rpartition("|")
        etichetta, url = etichetta.strip(), url.strip()
        per_host.setdefault(gruppo_di(urlparse(url).netloc), []).append((posizione, etichetta, url))
        posizione += 1
    risultati = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        for gruppo in pool.map(lambda righe: lavora_host(righe, uscita), per_host.values()):
            risultati.extend(gruppo)
    indice = [info for _, info in sorted(risultati, key=lambda t: t[0])]
    (uscita / "indice.json").write_text(json.dumps(indice, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
