# FeC-Plus 🧾 - Changelog

Tutte le novità delle versioni e la roadmap delle funzioni future. Progetto in fase **alpha**.

## [0.03 alpha] - versione attuale (luglio 2026)

### Modalità di accesso
- **NEW** **modalità di accesso utente-friendly**, scelte da un unico selettore nel riquadro «Credenziali Entratel»: **Studio - Delega Cliente**, **Studio - Cassetto proprio**, **Azienda**, **Libero professionista / Me stesso**.
- **NEW** Supporto all'accesso come **Azienda** (utente incaricato direttamente su una P.IVA aziendale, non tramite delega)**.

### Richieste massive e download
- **NEW** **Spezzettamento automatico dei periodi lunghi**: richieste superiori a 3 mesi (fino a un massimo di 12) vengono divise in blocchi ed eseguite in sequenza, sia per i download di consultazione sia per le richieste massive/corrispettivi.
- **NEW** Nuovo tipo di richiesta massiva **«Messe a Disposizione»**, oltre a emesse/ricevute (per emissione o ricezione)/corrispettivi.
- **NEW** **Scaricamento dei risultati** prodotti dal portale per le richieste massive inviate in precedenza (anche richieste effettuate direttamente dal portale e non dall'applicativo): elenco delle richieste disponibili con denominazione del soggetto, selezione e scarico, estrazione automatica o differita dello zip, eliminazione delle richieste già scaricate (con periodo di sicurezza prima della rimozione definitiva).
- **NEW** Nella scheda **Download Standard**, due opzioni per accodare nello stesso periodo un secondo download: **«Includi fatture transfrontaliere»** (con le fatture emesse) e **«Includi fatture Messe a Disposizione»** (con le fatture ricevute).
- **NEW** **Esclusione automatica delle fatture scartate dalla Pubblica Amministrazione** dal download (attiva di default, disattivabile).
- **NEW** **Estrazione dell'XML** dalle fatture firmate digitalmente (`.p7m`), al posto del file firmato originale (opzionale).
- **FIX** Maggiore resistenza alle disconnessioni del portale AdE durante download lunghi (nuovi tentativi automatici invece di far fallire l'intero blocco).

### Bolli virtuali
- **CHG** La funzione ora produce un **riepilogo CSV** (elenco A/B, importo calcolato, scadenza, importo versato e dati di pagamento), anche per l'intero anno oltre che per singolo trimestre.

### Anagrafica deleghe
- **NEW** Nuova scheda **«Deleghe»**: archivio locale dei clienti delegati, con inserimento manuale e import/export CSV (compatibile con l'esportazione ufficiale del portale AdE); un nuovo import aggiorna in sicurezza solo la scadenza della delega, senza toccare gli altri dati già presenti.

### Esportazione Excel
- **NEW** Nuova scheda **«Utility»**: esporta in **Excel (.xlsx)** l'elenco delle fatture (emesse, ricevute, transfrontaliere) o dei corrispettivi, con dettaglio per documento e riepilogo per aliquota/natura IVA; per l'anno intero è possibile scegliere un file unico oppure uno per trimestre/mese.

### Interfaccia
- **NEW** Tutte le schede sono ora disponibili nella **GUI pubblica** (in precedenza riservate alla versione sviluppatore), esclusa «Test Login» che resta uno strumento diagnostico interno.
- **CHG** Le schede «Fatture Massive» e «Corrispettivi» sono state unificate in un'unica scheda **«Richieste Massive»**.
- **NEW** Su Windows è disponibile un eseguibile standalone **`FeC-Plus.exe`**: si scarica e si avvia direttamente, senza installare Python o altre dipendenze.

### Dipendenze
- **NEW** **Controllo delle dipendenze all'avvio**: GUI e CLI verificano i pacchetti richiesti e segnalano quelli mancanti. **Playwright** è trattato come **opzionale** (il backend «requests» funziona senza browser); nella GUI l'avviso è inline e non bloccante, nella CLI è testuale.
- **CHG** Pulsante **«Installa dipendenze»**: ora fa **scegliere** se installare tutto (incluso Playwright + Chromium) o solo il set leggero per il backend «requests». Corretto un bug per cui non venivano installati tutti i pacchetti.
- **NEW** *(versione sviluppatore)* Strumento **«Disinstalla dipendenze»** per rimuovere i pacchetti selezionati, utile a verificare il controllo all'avvio.

## [0.02 alpha] - giugno 2026

### Autenticazione
- **NEW** Login **«solo requests»** senza browser, completo e verificato: l'app si autentica via API JSON (`/api/login/telematico`) e configura l'utenza di lavoro tramite le API REST di instradamento - niente più Playwright per l'accesso.
- **CHG** Il backend **requests** è ora il **default** della versione pubblica (più leggero, nessun browser da installare).
- **NEW** Modalità **headless** del browser attiva di default, con interruttore in ogni scheda (versione sviluppatore).
- **NEW** Strumento di **cattura del login** (HAR) per diagnostica e manutenzione.

### Interfaccia
- **NEW** **Due interfacce dalla stessa base**: versione *pubblica* (pulita) e versione *sviluppatore* (Test Login, cattura HAR, scelta backend), con launcher dedicati `avvia_fec_dev`.
- **NEW** **Selettore date a calendario** con periodi predefiniti (trimestri, mesi, anno): si sceglie l'anno e il periodo, le date si compilano da sole. I periodi futuri sono in grigio e non selezionabili; di default è proposto il **trimestre in corso** fino a oggi (l'AdE non ammette date future).
- **NEW** **Form Impostazioni** per le preferenze (cartella di download, profilo) e opzione **«non salvare le credenziali»**.
- **NEW** **Cartelle di download per tipo di documento**: si può assegnare una cartella diversa a ciascuna classe (fatture emesse, ricevute, transfrontaliere, massive, corrispettivi, bolli) oppure tenere un'unica cartella. Per ogni tipo è disponibile l'opzione **«senza sottocartella»** (file salvati direttamente nella cartella, comodo per importarli nei gestionali di contabilità). La scheda Download Standard mostra (sola lettura) dove verranno salvati i file.
- **NEW** Icona dell'app, logo e banner ASCII «FeC-Plus» mostrato all'avvio dei launcher.

### Dati e sicurezza
- **NEW** **Credenziali separate dalle preferenze**: le credenziali (CF, PIN, CF studio) sono salvate **cifrate** con cifratura leggera e portabile; le preferenze restano in chiaro. La password non viene mai salvata.

### Riga di comando e documentazione
- **NEW** **Interfaccia a riga di comando** (`fec_cli.py`): tutti i download senza GUI, passando accesso e parametri come argomenti. Vedi la [Guida](https://denvermotel.github.io/FeC-Plus/guida.html).
- **NEW** Pagina **Guida di utilizzo** e questo **Changelog**.

## [0.01 alpha] - prima release (giugno 2026)

- **NEW** Prima versione pubblica di **FeC-Plus**, evoluzione con interfaccia grafica del progetto FeCscraper.
- **NEW** **Nuovo login al portale AdE** (SAM/ForgeRock + scelta dell'utenza di lavoro) con backend **browser** (Playwright); un'unica autenticazione riusata per ogni operazione.
- **NEW** **Download fatture**: emesse, ricevute, transfrontaliere (emesse/ricevute) e messe a disposizione, con i relativi metadati.
- **NEW** **Richieste massive** (fatture emesse e ricevute) e **corrispettivi**: generazione e invio dell'XML all'AdE.
- **NEW** **Bolli virtuali**: generazione del modello **F24 in PDF** per il trimestre selezionato.
- **NEW** **Profili utenza**: studio → cliente (delega), cassetto dello studio, «me stesso».
- **NEW** **GUI tkinter cross-platform** (Windows/macOS) con launcher a doppio click.

## Roadmap - funzioni future

Funzionalità in programma, non ancora disponibili.

- 🔐 **Autenticazione tramite SPID/CIE** - accesso al portale anche con SPID e CIE (oltre a Fisconline/Entratel), con apertura del browser per l'inserimento delle credenziali presso l'Identity Provider.
- 🎨 **Nuova GUI** - La GUI attuale è un mezzo per testare le funzioni che vengono man mano implementate e testate. Nelle future versioni si vuole ridisegnare la GUI con un approccio moderno e user-friendly.
