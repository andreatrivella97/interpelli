# Interpelli

Raccoglie gli interpelli per supplenze pubblicati dagli istituti comprensivi della zona
(Legnano, Rho, Busto Arsizio, Saronno e dintorni) e li mostra in una pagina sola, con in
evidenza quelli per infanzia o primaria, da almeno 20 ore, che durano fino a giugno.

**Pagina:** https://andreatrivella97.github.io/interpelli/

Chi la usa non ha bisogno di account né di installare nulla: apre il link dal telefono.
Dal menu del browser può scegliere «Aggiungi a schermata Home» per averla come un'app.

## Come funziona

1. Ogni ora GitHub esegue da solo il programma in `scraper/`, che legge le pagine indicate in
   `scuole.yaml`, apre i documenti degli avvisi e ne ricava ordine di scuola, ore, durata e
   termine per candidarsi. Le scuole che non hanno risposto vengono riprovate ogni venti minuti.
2. Il risultato viene salvato in `docs/dati.json` (quello che la pagina mostra) e in
   `stato/archivio.json` (la memoria di ciò che è già stato visto e letto).
3. La pagina `docs/index.html` legge quel file. I segni «candidato» e «scartato» e i criteri
   modificati restano nel telefono di chi la usa, non vengono inviati da nessuna parte.

Non c'è nessun server da mantenere e nessun costo.

## Attivare la pagina (una volta sola)

Nel progetto su GitHub: **Settings → Pages → Build and deployment → Source: «Deploy from a
branch»**, poi branch **main** e cartella **/docs**, e **Save**. Dopo un minuto la pagina è
all'indirizzo qui sopra.

## Cambiare che cosa «fa per te»

In `criteri.yaml`: ordini di scuola, ore minime, mesi in cui deve finire il contratto. Sono
i valori di partenza; nella pagina, «Cambia criteri» permette a ciascuno di regolarli per sé.

## Aggiungere o correggere una scuola

In `scuole.yaml` ogni scuola ha un blocco con nome, comuni, sito e una o più «fonti»:

| tipo     | che cosa legge                                                                  |
|----------|---------------------------------------------------------------------------------|
| `pagina` | una pagina del sito con l'elenco degli interpelli (link a PDF o a notizie)      |
| `axios`  | la bacheca «Interpelli» del portale Axios; serve il codice fiscale della scuola |
| `albo`   | l'albo online dei siti ospitati da Spaggiari                                    |
| `wp`     | le notizie di un sito WordPress che parlano di interpello                       |

Basta copiare un blocco simile e cambiare i dati. Si può modificare il file direttamente da
GitHub (icona della matita): al controllo successivo la scuola compare nella pagina, sotto
«Scuole controllate», con l'esito della lettura.

## Se qualcosa non va

- In fondo alla pagina, **Scuole controllate** dice per ogni scuola quando è stata letta
  l'ultima volta e offre il link per guardarla a mano.
- Se in alto compare «I dati sono fermi a…», il controllo automatico non sta girando: nella
  scheda **Actions** del progetto si vede l'ultima esecuzione di «Aggiorna interpelli» e il
  suo registro. Da lì «Run workflow» fa partire subito un controllo completo.
- GitHub sospende i controlli programmati se il progetto resta fermo 60 giorni; qui non
  succede, perché ogni controllo salva i dati nel progetto.

## Limiti da conoscere

- Alcune scuole pubblicano gli avvisi (o i loro allegati) su portali che rifiutano le letture
  automatiche: il modulo Interpelli di Spaggiari, Trasparenza Scuole di Axios, il portale
  Argo. Per queste la pagina mostra ciò che si ricava dal titolo e rimanda al portale; in
  `scuole.yaml` sono segnate con `manuale`.
- Alcuni siti a volte non rispondono ai computer di GitHub. La scuola risulta «letta solo in
  parte» e viene riprovata al passaggio successivo; gli avvisi già visti restano in pagina.
- La lettura dei documenti segue regole scritte a mano e può sbagliare, soprattutto con le
  scansioni. Per questo ogni avviso mostra, sotto «Dettagli», il pezzo di testo da cui i dati
  sono stati presi, e quando un dato manca l'avviso finisce tra quelli «da verificare» invece
  di essere scartato. Prima di candidarsi fa sempre fede l'avviso originale.

## Per chi mette mano al programma

```
scuole.yaml, criteri.yaml     che cosa leggere e che cosa cercare
scraper/fonti/                un lettore per ogni tipo di fonte
scraper/classifica.py         le regole che ricavano i dati da titolo e testo
scraper/documenti.py          lettura di PDF (anche scansioni), pagine e file Word
scraper/archivio.py           memoria tra un controllo e l'altro, scelta di che cosa mostrare
scraper/__main__.py           il controllo completo
docs/                         la pagina pubblicata
tests/                        prove delle regole su avvisi veri (senza nomi di persone)
.github/workflows/            aggiorna.yml (ogni ora), prova.yml (sui rami di lavoro)
```

Per provare sul proprio computer servono Python 3.11 o successivo e, per i PDF, `poppler-utils`
e `tesseract-ocr` con la lingua italiana:

```
pip install -r requirements.txt
python -m unittest discover -s tests -t .      # le prove
python -m scraper --solo rho-grossi            # un controllo vero su una sola scuola
python -m http.server --directory docs         # la pagina, su http://localhost:8000
```

Quando una regola sbaglia su un avviso, il modo più sicuro per correggerla è aggiungere il
testo di quell'avviso in `tests/fixtures/testi/` con il risultato atteso, e poi cambiare la
regola finché tutte le prove passano.

Ogni modifica caricata su un ramo che comincia per `claude/` fa partire «Prova»: esegue le
prove e un controllo vero, e deposita il risultato nel ramo `prova-output` senza toccare la
pagina pubblicata. La prova riparte dalla memoria della prova precedente; scrivendo `[da capo]`
nel messaggio della modifica parte invece da zero, come un primo controllo.

Dopo aver cambiato le regole in `scraper/classifica.py` conviene aumentare di uno
`VERSIONE_REGOLE` nello stesso file: al controllo successivo gli avvisi ancora in pagina vengono
riletti con le regole nuove.

Il carattere della pagina è Andika (SIL Open Font License, vedi `docs/fonts/OFL.txt`).
