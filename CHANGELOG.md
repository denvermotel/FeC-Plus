# FeC-Plus 🧾 — Changelog

Tutte le novità delle versioni e la roadmap delle funzioni future. Progetto in fase **alpha**.

## [0.02 alpha] — in corso (giugno 2026)

### Autenticazione
- **NEW** Login **«solo requests»** senza browser, completo e verificato: l'app si autentica via API JSON (`/api/login/telematico`) e configura l'utenza di lavoro tramite le API REST di instradamento — niente più Playwright per l'accesso.
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

## [0.01 alpha] — prima release (giugno 2026)

- **NEW** Prima versione pubblica di **FeC-Plus**, evoluzione con interfaccia grafica del progetto FeCscraper.
- **NEW** **Nuovo login al portale AdE** (SAM/ForgeRock + scelta dell'utenza di lavoro) con backend **browser** (Playwright); un'unica autenticazione riusata per ogni operazione.
- **NEW** **Download fatture**: emesse, ricevute, transfrontaliere (emesse/ricevute) e messe a disposizione, con i relativi metadati.
- **NEW** **Richieste massive** (fatture emesse e ricevute) e **corrispettivi**: generazione e invio dell'XML all'AdE.
- **NEW** **Bolli virtuali**: generazione del modello **F24 in PDF** per il trimestre selezionato.
- **NEW** **Profili utenza**: studio → cliente (delega), cassetto dello studio, «me stesso».
- **NEW** **GUI tkinter cross-platform** (Windows/macOS) con launcher a doppio click.

## Roadmap — funzioni future

Funzionalità in programma, non ancora disponibili.

- 🔐 **Autenticazione tramite SPID** — accesso al portale anche con SPID (oltre a Fisconline/Entratel), con apertura del browser per l'inserimento delle credenziali presso l'Identity Provider.
- 👥 **Anagrafica deleghe ricevute** — elenco locale dei clienti delegati (deleghe ricevute dallo studio) per scegliere il soggetto da una lista ed eseguire i download in sequenza, senza digitare ogni volta CF e P.IVA.
