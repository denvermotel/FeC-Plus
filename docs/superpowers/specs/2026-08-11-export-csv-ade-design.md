# Export CSV formato Agenzia delle Entrate - design

Data: 2026-08-11
Versione applicativa: 0.04 alpha (invariata)

## Problema

Il portale AdE «Consultazione fatture elettroniche» espone un pulsante «Esporta la
tabella» che produce un CSV dell'elenco fatture. Quel CSV è il formato che i
software di contabilità si aspettano per la riconciliazione, e oggi l'utente deve
ottenerlo a mano dal portale, delega per delega, anche quando FeC-Plus ha già
scaricato le stesse fatture.

## Vincolo tecnico accertato

**Il CSV non esiste lato server: non c'è nulla da scaricare.** Il pulsante apre una
modale (`#modal-2`, partial `resources/html/includes/download-modale-fe.html`) che
chiede solo il nome del file; la generazione è interamente client-side, in
JavaScript, tramite la libreria `ng-csv` alimentata da
`ExportCSVService.exportCSVFattureElettroniche()` (file `core-services.js`).

L'input di quella funzione è **lo stesso JSON di elenco** che FeC-Plus già richiede
per scaricare le fatture (`rs/fe/emesse|ricevute/dal/{dal}/al/{al}`, chiave
`fatture[]`). Non esiste quindi l'alternativa «scaricare l'originale»: o si
ricostruisce, o la funzione non si può fare. La ricostruzione può però essere
fedele al byte, perché ogni colonna è una trasformazione deterministica di campi
della lista, e il codice sorgente della trasformazione è leggibile per intero nel
materiale raccolto (`_materiale/fatture emesse_files/core-services_XbTA.js`).

Riferimenti nel repo:
- campione CSV reale: `_materiale/SALVO_GABRIELE_2026-07-01-2026-08-10.csv`
- pagina salvata corrispondente: `_materiale/fatture emesse.html` (stesso soggetto,
  P.IVA 02691860817, stesso periodo 01/07/2026-10/08/2026, 25 righe)
- dump JSON di elenco: `_materiale/dump_lista_emesse_01072026.json` (altro soggetto)

## Formato del file (regole verificate)

Dalla lettura di `ng-csv` (`stringify` / `stringifyField`) e confermate dal campione:

- separatore di campo `;`
- ogni campo racchiuso tra virgolette doppie (opzione `quoteStrings`); le `"`
  interne al valore sono raddoppiate (`"` → `""`)
- terminatore di riga CRLF (`\r\n`), anche sull'ultima riga
- codifica UTF-8 **senza** BOM (`addByteOrderMarker` non attivo: il campione inizia
  direttamente con `"Tipo fattura"`)
- l'ordine delle colonne è l'ordine dei literal JS (chiavi `a,b,c,d,e,f,g,z,h,i,y,
  j,k,l,m,n,o`), **non** l'ordine alfabetico delle chiavi
- un valore JS `undefined` produce un campo vuoto **non** quotato, mentre una
  stringa vuota produce `""`. Per riprodurlo serve un writer scritto a mano: il
  modulo `csv` della standard library con `QUOTE_ALL` quoterebbe anche i `None`.
  Caso raro (interessa solo colonne data eventualmente assenti); la scelta è
  documentata nel codice e coperta da test.

## Regole di trasformazione dei campi

Comuni a tutti i tipi fattura:

| Colonna | Origine | Trasformazione |
|---|---|---|
| Tipo fattura | `decodificaTipoInvio` | prefisso apice: `'Fattura tra privati'` |
| Tipo documento | `tipoDocumento` | invariato |
| Numero fattura / Documento | `numeroFattura` | prefisso apice |
| Data emissione | `dataFattura` | da `AAAA-MM-GG` a `GG/MM/AAAA` |
| Data trasmissione | `dataAccoglienzaFile` | da `AAAA-MM-GG` a `GG/MM/AAAA` |
| Codice fiscale fornitore | `cfEmittente` | prefisso apice; assente → `'Non presente'` |
| Partita IVA fornitore | `pivaEmittente` | prefisso apice; assente → `'Non presente'` |
| Denominazione fornitore | `denominazioneEmittente` | invariato |
| Codice fiscale cliente | `cfCliente` | prefisso apice; assente → `'Non presente'` |
| Partita IVA cliente | `pivaCliente` | prefisso apice; assente → `'Non presente'` |
| Denominazione cliente | `denominazioneCliente` | invariato |
| Imponibile/Importo (totale in euro) | `imponibile` | rimozione del `+` iniziale; il JSON è già zero-paddato con virgola decimale (`+000000000043,55` → `000000000043,55`) |
| Imposta (totale in euro) | `imposta` | come sopra |
| Sdi/file | `fileDownload.idInvio` | invariato |
| Fatture consegnate | `fileDownload.statoFile` | con suffisso `/Presa visione` se esiste `fileDownload.dataPresaVisione` |
| (colonna data finale) | vedi sotto | |
| Bollo virtuale | `bolloVirtuale` | `Y` → `Si`, altrimenti stringa vuota |

Il prefisso apice (`'…'`) serve a impedire a Excel di interpretare gli
identificativi come numeri e mangiarne gli zeri iniziali: va riprodotto.

Colonna data finale, dipendente dal tipo:
- **emesse**: intestazione `Data consegna/Presa visione`
- **ricevute**: intestazione `Data ricezione`
- **messe a disposizione**: la colonna non esiste (16 colonne invece di 17)

Il valore, per emesse e ricevute, è `fileDownload.dataPresaVisione` se presente,
altrimenti `dataConsegna`. Entrambi arrivano già in `GG/MM/AAAA` e non vengono
riformattati dal JS. Il campione lo conferma: la fattura Apple ha
`statoDiConsegna === 0` con presa visione al 10/08/2026 e nel CSV riporta
`"Mancata consegna/Presa visione"` e `"10/08/2026"`.

**Punto da verificare sul vivo:** nessun record disponibile in `_materiale` ha
`dataPresaVisione` valorizzato nel JSON, quindi il formato di quel campo è dedotto
(il JS non lo riformatta, quindi deve già essere `GG/MM/AAAA`). Da confermare al
primo confronto con un export reale.

Le transfrontaliere (emesse e ricevute) hanno un layout proprio, con paese
controparte, `dataRicezione` come data di registrazione, `stato` e `clienteFornitore`
al posto di `Fatture consegnate`/bollo. La mappatura completa è nel JS ed è
trasposta nella tabella `LAYOUT` del modulo.

Fuori ambito: i layout SDI, spesometro, tax free e transfrontaliere-per-SDI, che il
JS prevede ma che non corrispondono a tipi scaricabili da FeC-Plus.

## Architettura

### Nuovo modulo `fec_csv_ade.py`

Libreria pura, nessun I/O di rete, nessuna dipendenza da GUI o download. Contiene
solo la conoscenza del formato AdE.

```
LAYOUT: dict[str, Layout]                       # un layout per tipo elenco
righe_csv(voci: list[dict], tipo: str) -> list[list[str | None]]
scrivi_csv(percorso: str, voci: list[dict], tipo: str) -> str
```

`Layout` è una struttura dichiarativa: intestazione + lista di estrattori, uno per
colonna. I tipi accettati sono le chiavi già usate da `fec_utility.TIPI_ELENCO`
(`emesse`, `ricevute_ricezione`, `ricevute_emissione`, `trans_emesse`,
`trans_ricevute`) più `messe_a_disposizione`; `ricevute_ricezione` e
`ricevute_emissione` condividono lo stesso layout.

Perché un modulo a sé e non dentro `fec_utility.py`: quest'ultimo è già a 41 KB e
ha una responsabilità diversa (Excel con pivot per aliquota IVA, che richiede una
chiamata di *dettaglio* per ogni fattura). Il CSV AdE si costruisce dalla sola
lista, senza chiamate aggiuntive, ed è una tabella di trasformazioni testabile
offline. Tenerli separati mantiene entrambi i file leggibili e permette al test di
fedeltà di girare senza rete né credenziali.

### Integrazione 1 - durante il download

`fec_download._scarica_da_lista` guadagna un parametro opzionale
`voci_out: list | None = None`: se passato, vi accumula le voci **dopo** il filtro
per controparte. Nessuna chiamata HTTP aggiuntiva: il CSV nasce dalla stessa
risposta di elenco che il download consuma comunque.

`fec_queue.Richiesta` guadagna il campo `csv_ade: bool = False`, propagato da
`_kwargs_richiesta` ai soli tipi `kind == "download"`. `esegui_richiesta` accumula
le voci di **tutti** i blocchi del periodo e scrive **un solo** CSV a fine task,
nella stessa cartella di destinazione dei file scaricati.

Semantica decisa: il CSV contiene solo le righe effettivamente scaricate, cioè
quelle superstiti al filtro P.IVA/CF controparte. Il file rispecchia lo scarico, e
quindi quadra con gli XML presenti nella cartella.

### Integrazione 2 - tab Utility

`fec_utility.elenco_fatture_csv_ade(auth, cf_cliente, piva, tipo, dal, al, *,
dest_dir=None, sottocartella=True, control=None, log=print) -> str`

Riusa `_lista_fatture` (già esistente) e `spezza_periodo` come fa
`elenco_fatture_excel`, ma salta del tutto `_dettaglio_fattura`: nessuna chiamata
per singola fattura, generazione pressoché istantanea. Periodo vuoto → solleva
`NessunDato`, coerentemente con l'export Excel, e nessun file viene creato.

Nella GUI: nuova voce nel tab Utility accanto a «Fatture → Excel», con gli stessi
controlli (delega, tipo elenco, periodo).

### Integrazione 3 - CLI

Flag `--csv-ade` sui comandi di download (genera il CSV oltre ai file scaricati) e
un comando dedicato per la generazione stand-alone, allineato agli altri comandi di
`fec_cli.py`.

### Nome del file

`{piva|cf}_{dal}-{al}_{etichetta}.csv`, cioè la stessa convenzione dell'export
Excel esistente. L'AdE fa digitare il nome a mano nella modale, quindi non c'è una
convenzione ufficiale da rispettare.

## Test

**Test di fedeltà (golden), ricevute.** Il campione CSV e la pagina HTML salvata
appartengono allo stesso soggetto e allo stesso periodo. L'HTML fornisce i campi
grezzi che il CSV non mostra (`fileDownload.statoDiConsegna`, presa visione con la
sua data, `dataUnificata`, e da `href="#/fatture/dettaglio/1FPR15406120083"` anche
`tipoInvio` e `idFattura`). Incrociando le due fonti si costruisce una fixture JSON
dei 25 record, versionata nel repo, e si asserisce che `scrivi_csv` riproduca
`SALVO_GABRIELE_2026-07-01-2026-08-10.csv` **byte per byte**.

**Test unitari sulle regole**, con casi costruiti dal JS: CF/P.IVA assente →
`'Non presente'`; bollo `Y`/assente; presa visione presente/assente; virgolette
dentro una denominazione (raddoppio); importo negativo o con `+`; elenco vuoto.

**Test di layout** per messe a disposizione e transfrontaliere: verifica di
intestazione e ordine colonne contro la trascrizione dal JS. Per questi tipi non
esiste un campione CSV reale, quindi la fedeltà completa non è dimostrabile
offline.

**Verifica finale sul portale** (manuale, con l'utente): esportare dalla modale AdE
il CSV di una delega e di un periodo, generare il nostro sullo stesso periodo e
confrontare i file. È l'unico modo di chiudere il punto aperto su
`dataPresaVisione` e di validare i tipi privi di campione. Se in futuro finisce in
`_materiale` un CSV esportato per emesse, messe a disposizione o transfrontaliere,
diventa golden anche quello.

## Fuori ambito

- Generazione del CSV nel flusso delle richieste massive multi-delega.
- Layout SDI, spesometro, tax free, transfrontaliere-per-SDI.
- Qualunque modifica al formato dell'export Excel esistente.
