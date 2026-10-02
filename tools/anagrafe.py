#!/usr/bin/env python3
"""Sonda di sviluppo: ricava dagli open data del Ministero gli istituti dei comuni scelti.

Uso:  python tools/anagrafe.py out
Scrive out/anagrafe.json con, per ogni plesso dei comuni elencati, istituto di
riferimento, grado e sito web dichiarato.
"""
import csv
import io
import json
import sys
from pathlib import Path

import requests

UA = ("Mozilla/5.0 (compatible; interpelli-monitor/1.0; "
      "+https://github.com/andreatrivella97/interpelli)")
BASE = "https://dati.istruzione.it/opendata/opendata/catalogo/elements1/"
CANDIDATI = [
    "SCUANAGRAFESTAT20262720260901.csv",
    "SCUANAGRAFESTAT20252620250901.csv",
    "SCUANAGRAFESTAT20242520240901.csv",
]
COMUNI = {
    "SAN VITTORE OLONA", "SAN GIORGIO SU LEGNANO", "OLGIATE OLONA", "CUGGIONO", "CANEGRATE",
    "BUSTO GAROLFO", "BUSTO ARSIZIO", "VILLA CORTESE", "DAIRAGO", "ARLUNO", "CASOREZZO",
    "OSSONA", "CASTELLANZA", "LEGNANO", "LAINATE", "RHO", "VANZAGO", "POGLIANO MILANESE",
    "CERRO MAGGIORE", "INVERUNO", "MARCALLO CON CASONE", "ARCONATE", "BUSCATE", "BAREGGIO",
    "RESCALDINA", "MAGNAGO", "MARNATE", "GORLA MINORE", "GORLA MAGGIORE", "SOLBIATE OLONA",
    "FAGNANO OLONA", "GERENZANO", "SARONNO", "UBOLDO",
}


def main():
    uscita = Path(sys.argv[1])
    uscita.mkdir(parents=True, exist_ok=True)
    esito = {"tentativi": [], "righe": []}
    for nome in CANDIDATI:
        url = BASE + nome
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=120)
            esito["tentativi"].append({"url": url, "stato": r.status_code, "byte": len(r.content),
                                       "tipo": r.headers.get("content-type", "")})
            if r.status_code != 200 or len(r.content) < 100_000:
                continue
            testo = r.content.decode("utf-8", errors="replace")
            lettore = csv.DictReader(io.StringIO(testo))
            esito["colonne"] = lettore.fieldnames
            for riga in lettore:
                comune = (riga.get("DESCRIZIONECOMUNE") or "").strip().upper()
                nome_scuola = (riga.get("DENOMINAZIONESCUOLA") or "") + " " + (riga.get("DENOMINAZIONEISTITUTORIFERIMENTO") or "")
                indirizzo = (riga.get("INDIRIZZOSCUOLA") or "").upper()
                if comune in COMUNI or (comune == "MILANO" and ("CONSOLE MARCELLO" in nome_scuola.upper() or "CONSOLE MARCELLO" in indirizzo)):
                    esito["righe"].append(riga)
            esito["fonte"] = url
            break
        except Exception as e:  # noqa: BLE001
            esito["tentativi"].append({"url": url, "errore": f"{type(e).__name__}: {e}"[:300]})
    (uscita / "anagrafe.json").write_text(json.dumps(esito, ensure_ascii=False, indent=1), encoding="utf-8")
    print("righe trovate:", len(esito["righe"]), "| tentativi:", esito["tentativi"])


if __name__ == "__main__":
    main()
