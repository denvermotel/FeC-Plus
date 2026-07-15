# FeC-Plus 🧾

**Versione 0.03 alpha**

**FeC-Plus** è uno strumento per automatizzare l'accesso e lo scaricamento dei dati dal portale "Fatture e Corrispettivi" dell'Agenzia delle Entrate, tramite una semplice interfaccia grafica.

Nasce come evoluzione del progetto `FeCscraper`, aggiungendo al core originale nuove funzionalità e una GUI user-friendly.

## ✨ Cosa fa

* **Login unico:** una sola autenticazione al portale AdE (SAM/ForgeRock + scelta dell'utenza di lavoro), riusata per tutte le operazioni - niente password sulla riga di comando.
* **4 modalità di accesso:** Studio (delega cliente o cassetto proprio), Azienda, Libero professionista/Me stesso - un unico selettore comune a tutte le operazioni.
* **Download fatture:** emesse, ricevute, transfrontaliere (emesse/ricevute) e messe a disposizione, con i relativi metadati; periodi lunghi spezzati e scaricati automaticamente in blocchi.
* **Richieste massive:** fatture emesse/ricevute/messe a disposizione e corrispettivi (genera e invia l'XML all'AdE), con scaricamento dei risultati prodotti dal portale per le richieste già inviate.
* **Anagrafica deleghe:** archivio locale dei clienti delegati, con import/export CSV.
* **Esportazione Excel:** elenco fatture o corrispettivi in un file .xlsx, con riepilogo per aliquota/natura IVA.
* **Bolli virtuali:** riepilogo CSV (elenco A/B, importo, stato pagamento) per trimestre o anno intero.
* **Cross-platform:** interfaccia grafica (tkinter) per Windows e macOS.

## 🚀 Installazione e avvio

* **Windows, senza installare nulla:** scarica ed esegui `FeC-Plus.exe` (sezione Releases del repository) - non richiede Python né altre dipendenze.
* **Da sorgente** (Windows/macOS), richiede **Python 3.12**:

```bash
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium      # browser per il login (backend "browser")
```

Avvio della GUI:
* **macOS:** doppio click su `avvia_fec.command` (usa `.venv` se presente)
* **Windows:** `avvia_fec.bat`, oppure direttamente `FeC-Plus.exe`
* In alternativa: `python fec_gui.py`

Il pulsante **«Installa dipendenze»** nella GUI esegue gli stessi passi di pip/playwright.

## 🧱 Struttura

* `ade_auth.py` - autenticazione al nuovo portale AdE (backend `browser` Playwright o `requests`).
* `fec_download.py` - funzioni di download/invio a partire da una sessione già autenticata (libreria pura).
* `fec_queue.py` - orchestrazione delle richieste (spezzettamento periodi lunghi in blocchi).
* `fec_utility.py` - esportazione dell'elenco fatture/corrispettivi in Excel.
* `fec_deleghe.py` - anagrafica locale dei clienti delegati (CRUD e import/export CSV).
* `fec_gui.py` - interfaccia grafica (schede Download Standard, Richieste Massive, Bolli, Utility, Deleghe).
* `fec_cli.py` - **download da riga di comando** (senza GUI): login + scarico passando accesso e parametri come argomenti. Vedi la [Guida](https://denvermotel.github.io/FeC-Plus/guida.html).
* `fec_store.py` - salvataggio di credenziali (cifrate) e preferenze, separati.

Esempio d'uso da riga di comando:

```bash
python fec_cli.py --cf RSSMRA80A01H501U --pin 1234 --password-env FEC_PWD \
    --cfstudio 01234567890 --cf-cliente 09876543210 \
    emesse --dal 01012026 --al 31012026
```

> ⚙️ Le **credenziali** (CF, PIN, CF studio) vengono salvate cifrate in `fec_credentials.dat`
> e le **preferenze** (cartelle di download per tipo di documento, profilo, ecc.) in
> `fec_settings.json`, dalla GUI («Salva credenziali» e «⚙ Impostazioni»). La password non
> viene mai salvata.

## 🤝 Credits e Riconoscimenti

FeC-Plus nasce come evoluzione e ampliamento di progetti open source preesistenti. L'aggiunta dell'interfaccia grafica e delle nuove logiche si poggia su solide fondamenta scritte da altri sviluppatori.

Un ringraziamento speciale va agli autori originali:
- Claudio Pizzillo per aver ideato e sviluppato il core originale di FeCscraper https://github.com/claudiopizzillo/FeCscraper
- Salvatore Crapanzano (@socrat3) per le successive e preziose migliorie introdotte nel suo fork https://github.com/socrat3/FeCscraper
- Il progetto attuale (FeC-Plus) è sviluppato e mantenuto da Giovanni Genna. https://github.com/denvermotel/

## 📄 Licenza

Questo progetto è distribuito sotto licenza MIT. Per maggiori dettagli, consulta il file LICENSE. Le note di copyright degli autori originali sono state mantenute come da licenza.


---