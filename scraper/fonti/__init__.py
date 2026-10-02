"""Le fonti: ogni modulo sa leggere un tipo di pagina e restituisce un elenco di avvisi grezzi."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class Voce:
    """Un avviso cosi' come compare in elenco, prima di leggerne il documento."""
    titolo: str
    url: str                              # che cosa aprire: il documento, o la pagina che lo contiene
    pagina: str                           # la pagina dell'elenco
    fonte: str                            # "pagina" | "axios" | "albo" | "wp"
    chiave: str = ""                      # identificativo stabile dentro la scuola
    nome_file: str = ""                   # per riconoscere lo stesso avviso letto da due fonti
    contesto: str = ""                    # testo della riga in cui compare
    pubblicato: date | None = None
    scadenza: datetime | None = None
    chiuso: str | None = None             # "CHIUSO", "ASSEGNATO", ... se la pagina lo dichiara
    personale: str | None = None          # "docente" | "ata"
    testo: str | None = None              # testo gia' disponibile (es. corpo della notizia)
    documento: str | None = None          # indirizzo da cui leggere il testo, se diverso da url
    sessione: object = None               # sessione da riusare per scaricare il documento
    intestazioni: dict = field(default_factory=dict)
    candidatura: str | None = None        # dove ci si candida, se diverso da url


def fonti_disponibili():
    from . import albo_pvw, axios, pagina, wp
    return {"pagina": pagina.leggi, "albo": albo_pvw.leggi, "axios": axios.leggi, "wp": wp.leggi}
