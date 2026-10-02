"""Controllo completo: legge le fonti di ogni scuola, aggiorna l'archivio e scrive i dati per la pagina.

Uso:
    python -m scraper                        controlla tutte le scuole
    python -m scraper --solo rho-grossi      controlla solo le scuole indicate (separate da virgola)
    python -m scraper --salta-recenti 50     rilegge solo le scuole non lette per intero negli ultimi 50 minuti

Con INTERPELLI_SALVA=cartella conserva in quella cartella ogni pagina e documento scaricato, per la messa a punto.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .archivio import Archivio, chiave_url, chiavi_di_confronto, da_mostrare, id_avviso, stesso_avviso
from .classifica import VERSIONE_REGOLE, analizza, valuta
from .documenti import Lettore
from .fonti import Voce, fonti_disponibili
from .fonti.axios import indirizzo_pagina
from .rete import ErroreRete, Rete
from .testo import anno_scolastico, anno_scolastico_citato, iso

ROMA = ZoneInfo("Europe/Rome")
RADICE = Path(__file__).resolve().parent.parent
MAX_DOCUMENTI_PER_SCUOLA = 25
GIORNI_VECCHIO = 45


class Bilancio:
    """Tetto ai documenti scaricati in un controllo: il resto viene letto ai controlli successivi."""

    def __init__(self, massimo: int):
        self.rimasti = massimo
        self._blocco = threading.Lock()

    def prendi(self) -> bool:
        with self._blocco:
            if self.rimasti <= 0:
                return False
            self.rimasti -= 1
            return True


def carica_configurazione(radice: Path) -> tuple[list[dict], dict]:
    scuole = yaml.safe_load((radice / "scuole.yaml").read_text(encoding="utf-8"))["scuole"]
    criteri = yaml.safe_load((radice / "criteri.yaml").read_text(encoding="utf-8"))
    return scuole, criteri


def etichetta_fonte(fonte: dict) -> str:
    return f"{fonte['tipo']}:{fonte.get('url') or fonte.get('cf') or ''}"


def troppo_vecchio(voce: Voce, analisi, ora: datetime) -> bool:
    """Avvisi dello storico: inutile scaricarne il documento."""
    oggi = ora.date()
    if voce.scadenza:
        return voce.scadenza < ora.replace(tzinfo=None) - timedelta(days=20)
    pubblicato = voce.pubblicato or analisi.pubblicato
    if pubblicato:
        return pubblicato < oggi - timedelta(days=GIORNI_VECCHIO)
    fini = [p.fine for p in analisi.posti if p.fine]
    if fini:
        return max(fini) < oggi - timedelta(days=7)
    return bool(voce.chiuso)


def data_rapida(voce: Voce, oggi: date) -> date | None:
    """La data piu' attendibile ricavabile dall'elenco, senza aprire il documento."""
    if voce.scadenza:
        return voce.scadenza.date()
    if voce.pubblicato:
        return voce.pubblicato
    return analizza(voce.titolo, "", oggi=oggi).pubblicato


def storico_per_posizione(voci: list[Voce], oggi: date) -> set[int]:
    """Indici delle voci senza data che, per come e' ordinato l'elenco, sono piu' vecchie di una gia' vecchia.

    Gli elenchi sono cronologici (dal piu' recente o dal piu' vecchio): una voce senza data che
    sta "dietro" a una voce vecchia di mesi appartiene allo storico e non va scaricata.
    """
    date_voci = [data_rapida(v, oggi) for v in voci]
    datate = [(i, d) for i, d in enumerate(date_voci) if d]
    if len(datate) < 2:
        return set()
    limite = oggi - timedelta(days=GIORNI_VECCHIO)
    discendente = datate[0][1] >= datate[-1][1]
    vecchie = [i for i, d in datate if d < limite]
    if not vecchie:
        return set()
    if discendente:
        soglia = min(vecchie)
        return {i for i, d in enumerate(date_voci) if d is None and i > soglia}
    soglia = max(vecchie)
    return {i for i, d in enumerate(date_voci) if d is None and i < soglia}


def controlla_scuola(scuola: dict, esistenti: dict[str, dict], memoria: dict, lettori: dict, rete: Rete,
                     lettore: Lettore, bilancio: Bilancio, ora: datetime) -> tuple[dict[str, dict], dict]:
    """Legge tutte le fonti di una scuola. Restituisce gli avvisi aggiornati e lo stato di salute."""
    oggi = ora.date()
    adesso = ora.strftime("%Y-%m-%dT%H:%M")
    avvisi = {k: dict(v) for k, v in esistenti.items()}
    for record in avvisi.values():
        record["presente"] = False
    salute = {"fonti": {}, "errori": []}
    letti_ora = 0
    fonti_viste = dict(memoria.get("fonti_viste", {}))
    conteggi = dict(memoria.get("conteggi", {}))
    # lo stesso avviso letto da due fonti ha due identificativi: il secondo rimanda al primo
    rimandi = {altro: k for k, r in avvisi.items() for altro in r.get("alias", [])}

    for fonte in scuola.get("fonti", []):
        nome = etichetta_fonte(fonte)
        try:
            voci = lettori[fonte["tipo"]](scuola, fonte, rete, oggi)
        except ErroreRete as e:
            salute["fonti"][nome] = f"errore: {e}"
            salute["errori"].append(str(e))
            # una fonte non letta non significa che i suoi avvisi siano spariti
            for record in avvisi.values():
                if nome in (record.get("letti_da") or []):
                    record["presente"] = True
            continue
        except Exception as e:  # noqa: BLE001 - una scuola rotta non deve fermare le altre
            salute["fonti"][nome] = f"errore: {type(e).__name__}: {e}"
            salute["errori"].append(f"{type(e).__name__}: {e}")
            traceback.print_exc()
            continue

        prima_lettura = nome not in fonti_viste
        fonti_viste.setdefault(nome, adesso)
        massimo_precedente = conteggi.get(nome, 0)
        conteggi[nome] = max(massimo_precedente, len(voci))
        salute["fonti"][nome] = "ok"
        if not voci and massimo_precedente >= 3 and fonte["tipo"] == "pagina":
            salute["fonti"][nome] = "vuota"
            salute["errori"].append("la pagina non elenca piu' avvisi: forse e' cambiata")

        storiche = storico_per_posizione(voci, oggi)
        for posizione, voce in enumerate(voci):
            id_ = id_avviso(scuola["id"], voce)
            id_ = rimandi.get(id_, id_)
            record = avvisi.get(id_)
            if record is None:
                id_simile = next((k for k, r in avvisi.items() if stesso_avviso(r, voce)), None)
                if id_simile:
                    record = avvisi[id_simile]
                    record.setdefault("alias", []).append(id_)
                    rimandi[id_] = id_simile
                    id_ = id_simile
            if record is None:
                record = {"id": id_, "scuola": scuola["id"], "titolo": voce.titolo, "url": voce.url,
                          "pagina": voce.pagina, "prima_vista": adesso, "iniziale": prima_lettura,
                          "fonti": [], "letti_da": [], "chiavi_file": [], "titoli": [], "letto": None, "tentativi": 0,
                          "posti": [], "ordini": [], "personale": "docente"}
                avvisi[id_] = record
            citato = anno_scolastico_citato(voce.titolo)
            if posizione in storiche or (citato is not None and citato < anno_scolastico(oggi)):
                record["storico"] = True        # elenco vecchio, o titolo che nomina un anno scolastico passato
            _aggiorna_da_voce(record, voce, nome, adesso)
            # si (ri)legge quando manca la lettura, quando e' fallita poche volte, quando un'altra fonte offre
            # un indirizzo non ancora provato per un avviso rimasto senza testo, e quando sono cambiate le regole
            indirizzo = _indirizzo_documento(voce)
            senza_testo = record.get("letto") not in ("testo", "ocr", "pagina")
            da_leggere = (record.get("letto") in (None, "in_attesa")
                          or (record.get("letto") == "errore" and record["tentativi"] < 3)
                          or (senza_testo and indirizzo and chiave_url(indirizzo) not in record.get("provati", [])))
            if da_leggere or record.get("regole") != VERSIONE_REGOLE:
                puo_leggere = letti_ora < MAX_DOCUMENTI_PER_SCUOLA
                if _leggi_e_classifica(record, voce, lettore, bilancio, ora, puo_leggere):
                    letti_ora += 1

    memoria_nuova = {"fonti_viste": fonti_viste, "conteggi": conteggi,
                     "ultimo_ok": memoria.get("ultimo_ok"), "ultimo_controllo": adesso}
    fallite = [n for n, s in salute["fonti"].items() if s.startswith("errore")]
    if not scuola.get("fonti"):
        salute["stato"] = "manuale"
    elif not fallite:
        salute["stato"] = "ok" if not salute["errori"] else "da_controllare"
        memoria_nuova["ultimo_ok"] = adesso
    elif len(fallite) < len(salute["fonti"]):
        salute["stato"] = "parziale"
    else:
        salute["stato"] = "errore"
    salute["memoria"] = memoria_nuova
    return avvisi, salute


def _aggiorna_da_voce(record: dict, voce: Voce, nome_fonte: str, adesso: str) -> None:
    record["presente"] = True
    record["ultima_vista"] = adesso
    if voce.fonte not in record["fonti"]:
        record["fonti"].append(voce.fonte)
    if nome_fonte not in record["letti_da"]:
        record["letti_da"].append(nome_fonte)
    file, titolo = chiavi_di_confronto(voce)
    if file and file not in record["chiavi_file"]:
        record["chiavi_file"].append(file)
    titoli = record.setdefault("titoli", [])
    if voce.titolo not in titoli and len(titoli) < 3:
        titoli.append(voce.titolo)
    record.setdefault("chiave_titolo", titolo)
    if voce.chiuso:
        record["chiuso"] = voce.chiuso
    if voce.pubblicato and not record.get("pubblicato"):
        record["pubblicato"] = iso(voce.pubblicato)
    if voce.scadenza and (voce.fonte == "axios" or not record.get("scadenza_certa")):
        record["scadenza"] = iso(voce.scadenza)
        record["scadenza_certa"] = True
        record["scadenza_prova"] = "termine indicato nell'elenco della scuola"
    if voce.candidatura:
        record["candidatura"] = voce.candidatura
    if voce.personale:
        record["personale"] = voce.personale
    # il link migliore da aprire e' il documento sul sito della scuola; il portale resta per candidarsi
    if voce.fonte != "axios" and record.get("url", "").startswith("https://serviziweb.axioscloud.it"):
        record["url"], record["pagina"] = voce.url, voce.pagina


def _indirizzo_documento(voce: Voce) -> str | None:
    """Da dove si puo' leggere il testo dell'avviso (None se la voce non offre nulla da aprire)."""
    return voce.documento or (voce.url if voce.fonte != "axios" and not voce.chiave.startswith("riga:") else None)


def _leggi_e_classifica(record: dict, voce: Voce, lettore: Lettore, bilancio: Bilancio, ora: datetime,
                        puo_leggere: bool) -> bool:
    """Legge il documento (se serve e se c'e' margine) e ricava posti, scadenza, pubblicazione."""
    oggi = ora.date()
    pubblicato = date.fromisoformat(record["pubblicato"]) if record.get("pubblicato") else None
    titoli = record.get("titoli") or [voce.titolo]

    def migliore(testo: str):
        # lo stesso avviso puo' avere titoli diversi nelle varie fonti: si tiene la lettura piu' completa
        letture = [analizza(t, testo, oggi=oggi, pubblicato=pubblicato, personale=record.get("personale")) for t in titoli]
        return max(letture, key=lambda a: a.completezza())

    solo_titolo = migliore("")
    testo, letto, nota, scaricato = voce.testo or "", "titolo", None, False
    indirizzo = _indirizzo_documento(voce)
    if indirizzo:
        provati = record.setdefault("provati", [])
        if chiave_url(indirizzo) not in provati and len(provati) < 6:
            provati.append(chiave_url(indirizzo))

    if record.get("storico") or troppo_vecchio(voce, solo_titolo, ora):
        letto, nota = "titolo", "avviso dello storico: letto solo il titolo"
    elif indirizzo:
        if puo_leggere and bilancio.prendi():
            documento = lettore.leggi(indirizzo, sessione=voce.sessione, intestazioni=voce.intestazioni or None)
            scaricato = True
            record["tentativi"] = record.get("tentativi", 0) + 1
            testo = (testo + "\n" + documento.testo).strip()
            letto, nota = documento.come, documento.nota
            if documento.come == "errore" and record["tentativi"] >= 3:
                letto, nota = "non_leggibile", documento.nota
        else:
            letto, nota = "in_attesa", "documento non ancora letto: sara' letto al prossimo controllo"
    elif testo:
        letto = "pagina"

    analisi = migliore(testo) if testo else solo_titolo
    if testo and letto in ("errore", "in_attesa", "non_leggibile") and solo_titolo.completezza() > analisi.completezza():
        analisi = solo_titolo
    record["posti"] = [p.come_dati() for p in analisi.posti]
    record.pop("escluso", None)
    if analisi.esito_procedura:
        record["escluso"] = "comunica l'esito di una procedura: non e' un avviso a cui candidarsi"
        record["posti"] = []
    record["ordini"] = analisi.ordini
    record["personale"] = analisi.personale
    record["letto"], record["nota"] = letto, nota
    if letto != "in_attesa":
        record["regole"] = VERSIONE_REGOLE
    if analisi.pubblicato and not record.get("pubblicato"):
        record["pubblicato"] = iso(analisi.pubblicato)
    if analisi.scadenza:
        nota_scadenza = iso(analisi.scadenza)
        attuale = record.get("scadenza") or ""
        if not record.get("scadenza_certa"):
            record["scadenza"], record["scadenza_prova"] = nota_scadenza, analisi.scadenza_prova
        elif attuale[:10] == nota_scadenza[:10] and attuale[11:] == "23:59" and nota_scadenza[11:] != "23:59":
            # l'elenco dava solo il giorno: l'ora precisa e' scritta nel documento
            record["scadenza"], record["scadenza_prova"] = nota_scadenza, analisi.scadenza_prova
    return scaricato


def pagine_di(scuola: dict) -> list[dict]:
    """Gli indirizzi da aprire a mano per controllare la scuola, con un nome che dica che cosa sono."""
    pagine = []
    for fonte in scuola.get("fonti", []):
        if fonte["tipo"] == "axios":
            pagine.append({"nome": "Portale delle candidature", "url": indirizzo_pagina(str(fonte["cf"]))})
        elif fonte["tipo"] == "albo":
            pagine.append({"nome": "Albo online", "url": (fonte.get("url") or scuola["sito"].rstrip("/") + "/albo-online")
                           + "?cerca=interpell"})
        elif fonte["tipo"] == "wp":
            pagine.append({"nome": "Notizie sul sito", "url": (fonte.get("url") or scuola["sito"]).rstrip("/") + "/?s=interpello"})
        else:
            pagine.append({"nome": fonte.get("nome") or "Pagina sul sito", "url": fonte["url"]})
    return pagine


def _senza_orari(dati: dict) -> dict:
    """I dati della pagina senza gli orari dei controlli: uguali se da un giro all'altro non e' cambiato nulla."""
    copia = json.loads(json.dumps(dati))
    copia.pop("generato", None)
    for scuola in copia.get("scuole", []):
        scuola.pop("ultimo_controllo", None)
    return copia


def main(argomenti: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Raccoglie gli interpelli dai siti delle scuole.")
    parser.add_argument("--radice", type=Path, default=RADICE, help="cartella con scuole.yaml e criteri.yaml")
    parser.add_argument("--solo", default="", help="id delle scuole da controllare, separati da virgola")
    parser.add_argument("--max-documenti", type=int, default=160, help="documenti da scaricare al massimo in un controllo")
    parser.add_argument("--max-ocr", type=int, default=30, help="PDF scansionati da leggere al massimo in un controllo")
    parser.add_argument("--pausa", type=float, default=2.0, help="secondi tra due richieste allo stesso server")
    parser.add_argument("--salta-recenti", type=int, default=0, metavar="MINUTI",
                        help="non rilegge le scuole lette con successo da meno di questi minuti")
    args = parser.parse_args(argomenti)

    scuole, criteri = carica_configurazione(args.radice)
    solo = {s.strip() for s in args.solo.split(",") if s.strip()}
    ora = datetime.now(ROMA).replace(tzinfo=None, second=0, microsecond=0)
    archivio = Archivio(args.radice / "stato" / "archivio.json")
    rete = Rete(pausa=args.pausa)
    lettore = Lettore(rete, max_ocr=args.max_ocr)
    bilancio = Bilancio(args.max_documenti)
    lettori = fonti_disponibili()

    def letta_da_poco(scuola: dict) -> bool:
        ultimo = archivio.scuole.get(scuola["id"], {}).get("ultimo_ok")
        return bool(args.salta_recenti and ultimo
                    and ora - datetime.fromisoformat(ultimo) < timedelta(minutes=args.salta_recenti))

    def lavora(scuola: dict):
        if (solo and scuola["id"] not in solo) or letta_da_poco(scuola):
            return scuola, None, None
        try:
            return (scuola, *controlla_scuola(scuola, archivio.di_scuola(scuola["id"]),
                                              archivio.scuole.get(scuola["id"], {}), lettori, rete, lettore, bilancio, ora))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return scuola, None, {"stato": "errore", "errori": [f"{type(e).__name__}: {e}"], "fonti": {},
                                  "memoria": archivio.scuole.get(scuola["id"], {})}

    with ThreadPoolExecutor(max_workers=10) as gruppo:
        risultati = list(gruppo.map(lavora, scuole))
    if args.salta_recenti and all(salute is None for _, _, salute in risultati):
        print("Tutte le scuole sono state lette da poco: niente da riprovare.")
        return 0

    stato_scuole = []
    for scuola, avvisi, salute in risultati:
        memoria = archivio.scuole.get(scuola["id"], {})
        if salute is not None:
            if avvisi is not None:
                archivio.avvisi.update(avvisi)
            memoria = salute.pop("memoria", memoria)
            memoria["stato"], memoria["errori"] = salute["stato"], salute["errori"][:3]
            archivio.scuole[scuola["id"]] = memoria
            print(f"{scuola['id']:26s} {salute['stato']:14s} "
                  f"{sum(1 for a in archivio.di_scuola(scuola['id']).values() if a.get('presente')):3d} avvisi in pagina"
                  f"{'  ' + '; '.join(salute['errori'][:2]) if salute['errori'] else ''}", flush=True)
        stato_scuole.append({
            "id": scuola["id"], "nome": scuola["nome"], "comuni": scuola.get("comuni", []), "sito": scuola.get("sito"),
            "pagine": pagine_di(scuola), "manuale": scuola.get("manuale"), "nota": scuola.get("nota"),
            "stato": memoria.get("stato", "mai_controllata"), "errori": memoria.get("errori", []),
            "ultimo_ok": memoria.get("ultimo_ok"), "ultimo_controllo": memoria.get("ultimo_controllo"),
        })

    visibili = []
    for record in archivio.avvisi.values():
        if not da_mostrare(record, ora):
            continue
        campi = ("id", "scuola", "titolo", "url", "pagina", "candidatura", "fonti", "pubblicato", "scadenza",
                 "scadenza_certa", "scadenza_prova", "chiuso", "personale", "ordini", "posti", "letto", "nota",
                 "prima_vista", "iniziale", "presente")
        visibili.append({c: record.get(c) for c in campi})
    # ordine sempre uguale a parita' di dati (per data, poi per identificativo): cosi' da un giro
    # all'altro il file cambia solo dove e' cambiato qualcosa
    visibili.sort(key=lambda a: a["id"])
    visibili.sort(key=lambda a: (a.get("pubblicato") or a.get("prima_vista") or "")[:10], reverse=True)

    dati = {"generato": ora.strftime("%Y-%m-%dT%H:%M"), "criteri": criteri, "scuole": stato_scuole, "avvisi": visibili}
    uscita = args.radice / "docs" / "dati.json"
    if args.salta_recenti and uscita.exists() and _senza_orari(json.loads(uscita.read_text(encoding="utf-8"))) == _senza_orari(dati):
        # un passaggio di recupero in cui le scuole riprovate non hanno risposto nemmeno stavolta: non c'e' nulla da salvare
        print("Le scuole riprovate non hanno risposto: dati lasciati come sono.")
        return 0
    archivio.salva(ora)
    uscita.parent.mkdir(parents=True, exist_ok=True)
    uscita.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")

    # riepilogo leggibile nel registro dell'esecuzione
    conteggio = {"corrisponde": 0, "da_verificare": 0, "non_corrisponde": 0}
    from .classifica import Analisi, Posto
    for a in visibili:
        posti = [Posto(ordini=p["ordini"], tipo=p["tipo"], ore=p["ore"], intero=p["intero"],
                       fine=date.fromisoformat(p["fine"]) if p["fine"] else None, fine_nota=p["fine_nota"]) for p in a["posti"]]
        esito, _ = valuta(Analisi(posti=posti, ordini=a["ordini"], personale=a["personale"]), criteri, ora.date())
        conteggio[esito] += 1
    guasti = [s["id"] for s in stato_scuole if s["stato"] in ("errore", "parziale", "da_controllare")]
    print(f"\n{len(visibili)} avvisi in pagina: {conteggio} | richieste: {rete.richieste} | "
          f"documenti ancora leggibili in questo giro: {bilancio.rimasti} | scuole con problemi: {guasti or 'nessuna'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
