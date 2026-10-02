#!/usr/bin/env python3
"""Sonda di sviluppo: legge il cruscotto pubblico "Interpelli" di Axios per alcune scuole.

Uso:  python tools/sonda_axios.py out
"""
import base64
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

UA = ("Mozilla/5.0 (compatible; interpelli-monitor/1.0; "
      "+https://github.com/andreatrivella97/interpelli)")
BASE = "https://serviziweb.axioscloud.it/Pages/Interpelli/"
CHIAVE = bytes.fromhex("F582DBF5AA23E131913C63")
SCUOLE = {
    "magnago": "93018880158", "canegrate": "84004750158", "sanvittore": "84004470153",
    "cerro": "84004130153", "rescaldina-manzoni": "84004990150", "rescaldina-alighieri": "84004110155",
    "legnano-manzoni": "84003650151", "ossona": "93018820154", "legnano-salici": "84003710153",
    "arluno": "93527540152", "bareggio": "82004830152", "lainate-lamarmora": "93528430155",
    "lainate-cairoli": "93527590157", "pogliano": "93527530153", "rho-deandre": "93527170158",
    "milano-consolemarcello": "80193870153", "legnano-bonvesin": "92044520150",
    "villacortese": "92034300159", "legnano-carducci": "84005530153", "rho-grossi": "93546620159",
    "rho-annafrank": "93546630158", "rho-franceschini": "93546600151", "castellanza": "81009410127",
    "saronno-moro": "94000200124", "saronno-davinci": "94011740126", "busto-pertini": "81014010128",
}


def cid(cf: str) -> str:
    testo = ""
    for cifra, k in zip(cf.encode(), CHIAVE):
        b = bytes([cifra ^ k])
        try:
            testo += b.decode("cp1252")
        except UnicodeDecodeError:
            testo += b.decode("latin-1")
    return base64.b64encode(testo.encode("utf-8")).decode()


def main():
    uscita = Path(sys.argv[1]) / "axios"
    uscita.mkdir(parents=True, exist_ok=True)
    esiti = {}
    for sid, cf in SCUOLE.items():
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
        url = BASE + "gestioneinterpelli.aspx?cid=" + quote(cid(cf))
        info = {"url": url}
        try:
            r = s.get(url, timeout=40)
            info["stato_pagina"] = r.status_code
            m = re.search(r'id="_AXToken"\s+value="([^"]*)"', r.text)
            token = m.group(1) if m else ""
            info["token"] = bool(token)
            info["cookie"] = sorted(s.cookies.keys())
            time.sleep(1.0)
            r2 = s.get(BASE + "INT_Ajax_Get.aspx?Action=INT_DASHBOARD", timeout=40,
                       headers={"RVT": token, "X-Requested-With": "XMLHttpRequest", "Referer": url})
            info["stato_cruscotto"] = r2.status_code
            info["byte"] = len(r2.content)
            (uscita / f"{sid}.html").write_bytes(r2.content)
        except Exception as e:  # noqa: BLE001
            info["errore"] = f"{type(e).__name__}: {e}"[:300]
        esiti[sid] = info
        print(sid, info, flush=True)
        time.sleep(1.5)
    (uscita / "indice.json").write_text(json.dumps(esiti, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
