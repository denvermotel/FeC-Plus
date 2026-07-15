#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.03 alpha
"""
FEC GUI - Fatture Elettroniche e Corrispettivi
Interfaccia grafica per il download fatture e corrispettivi dal portale AdE.
Richiede: Python 3 + tkinter (incluso nella distribuzione standard)
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from tkinter import font as tkfont
import subprocess
import threading
import webbrowser
import os
import json
import sys

import fec_deps

__version__ = "0.03 alpha"

APP_NAME = "FeC-Plus"
REPO_URL = "https://github.com/denvermotel/FeC-Plus"
LICENSE_URL = "https://raw.githubusercontent.com/denvermotel/FeC-Plus/refs/heads/master/LICENSE"
DOCS_URL = "https://denvermotel.github.io/FeC-Plus/guida.html"
HOME_URL = "https://denvermotel.github.io/FeC-Plus/"

# Percorsi compatibili con l'eseguibile PyInstaller: i dati persistenti
# (config, credenziali, Download) stanno ACCANTO all'exe; gli asset di sola
# lettura vengono dal bundle (sys._MEIPASS). In esecuzione da sorgente: come prima.
if getattr(sys, "frozen", False):
    SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.executable))
    ASSETS_DIR = os.path.join(getattr(sys, "_MEIPASS", SCRIPT_DIR), "assets")
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    ASSETS_DIR = os.path.join(SCRIPT_DIR, "assets")
APP_ICON = os.path.join(ASSETS_DIR, "AppIcon1024.png")
DEFAULT_DEST_DIR = os.path.join(SCRIPT_DIR, "Download")


def _python_interprete() -> "str | None":
    """
    Interprete Python da usare per «Installa dipendenze» (pip / playwright install).

    Da sorgente: è lo stesso Python che esegue la GUI (venv), cioè `sys.executable`.
    Da app pacchettizzata (PyInstaller, `dist/FeC-Plus.exe`): `sys.executable` è
    l'ESEGUIBILE dell'app, NON un interprete Python - lanciarlo con «-m pip» non
    installa nulla (rilancia solo la GUI). In quel caso serve un Python di sistema:
    si cerca «py» (launcher Windows), «python», «python3». None se non ce n'è.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable
    import shutil
    for cand in ("py", "python", "python3"):
        trovato = shutil.which(cand)
        if trovato:
            return trovato
    return None


PYTHON = _python_interprete()

# Modalità SVILUPPO: stessa codebase, due interfacce scelte dal launcher.
#   - pubblica (default): solo gli strumenti d'uso (download, ecc.).
#   - dev: + scheda Test Login, cattura HAR, selettore backend/headless.
# Attivata da `--dev` sulla riga di comando o da FEC_DEV=1 nell'ambiente.
DEV_MODE = ("--dev" in sys.argv) or (
    os.environ.get("FEC_DEV", "").strip().lower() not in ("", "0", "false", "no")
)

# Selettore date da calendario: opzionale, fallback a Entry testuale se assente.
try:
    from tkcalendar import DateEntry
    _HAS_TKCAL = True
except Exception:
    DateEntry = None
    _HAS_TKCAL = False


def _periodi_generici():
    """Periodi generici SENZA anno (l'anno è in un campo a parte).
    Ritorna lista di (etichetta, mese_inizio, mese_fine)."""
    mesi = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
            "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]
    out = [(f"{q}º trimestre", (q - 1) * 3 + 1, (q - 1) * 3 + 3) for q in range(1, 5)]
    out += [(mesi[m - 1], m, m) for m in range(1, 13)]
    out.append(("Anno intero", 1, 12))
    return out

# Le 4 modalità di accesso utente-friendly (vedi ade_auth per il mapping tecnico verso
# i profili numerici del wizard, costanti PROFILO_*).
MODALITA_ACCESSO = ["Studio - Delega Cliente", "Studio - Cassetto proprio", "Azienda",
                    "Libero professionista / Me stesso"]

_MODALITA_PROFILO = {
    "Studio - Delega Cliente": 1,   # PROFILO_STUDIO_CLIENTE
    "Studio - Cassetto proprio": 2,  # PROFILO_STUDIO_CASSETTO
    "Azienda": 4,                    # PROFILO_AZIENDA
    "Libero professionista / Me stesso": 3,  # PROFILO_ME_STESSO
}


# Etichette del menù a tendina «Backend di login» (solo DEV_MODE, box credenziali).
_BACKEND_LABELS = {"browser": "Browser (Playwright)", "requests": "Solo requests"}
_BACKEND_DA_LABEL = {v: k for k, v in _BACKEND_LABELS.items()}


def _profilo_da_modalita(modalita: str) -> int:
    """Converte la modalità utente-friendly nel profilo numerico atteso da
    `ade_auth.Creds` (vedi le costanti `PROFILO_*` lì definite)."""
    return _MODALITA_PROFILO.get(modalita, 1)

# Classi di documento per le cartelle di download personalizzabili (Impostazioni).
# Ogni classe può avere una cartella propria (override di std_destdir) e l'opzione
# «senza sottocartella» (file diretti nella cartella, utile per i gestionali).
# Estensibile: per una nuova classe basta aggiungere una riga (chiave, etichetta) e
# mapparla nel relativo handler _run_*. Le 3 massive condividono la cartella
# `inviomassivo`, quindi sono un'unica classe «massive».
DOC_CLASSI = [
    ("emesse",             "Fatture emesse"),
    ("ricevute",           "Fatture ricevute"),
    ("trans_emesse",       "Transfrontaliere emesse"),
    ("trans_ricevute",     "Transfrontaliere ricevute"),
    ("messe_disposizione", "Messe a disposizione"),
    ("massive",            "Fatture massive"),
    ("corrispettivi",      "Corrispettivi"),
    ("bolli",              "Bolli virtuali"),
    ("utility",            "Utility (elenchi Excel)"),
    ("risultati_massive",         "Risultati Fatture Massive"),
    ("risultati_corrispettivi",   "Risultati Corrispettivi"),
]

# Mappa il «Tipo documento» della scheda Download Standard alla classe DOC_CLASSI,
# per mostrare la cartella di destinazione risolta dalle Impostazioni.
TIPO_STD_KEY = {
    "Fatture Emesse":            "emesse",
    "Fatture Ricevute":          "ricevute",
    "Transfrontaliere Emesse":   "trans_emesse",
    "Transfrontaliere Ricevute": "trans_ricevute",
    "Messe a Disposizione":      "messe_disposizione",
}


# ─────────────────────────────────────────────────────────────────────────────
class FecGui:

    def __init__(self, root: tk.Tk):
        self.root = root
        self._fix_macos_paste()
        self._fix_caret()
        _dev = "  ·  DEV" if DEV_MODE else ""
        self.root.title(f"{APP_NAME} - Fatture e Corrispettivi  ·  v{__version__}{_dev}")
        self._set_app_icon()
        self.root.geometry("880x1010")
        self.root.minsize(780, 680)
        self.root.columnconfigure(0, weight=1)
        # riga 0 = credenziali, riga 1 = PanedWindow verticale (notebook + console).
        # Il divisore tra le tab e la console «Output» è trascinabile dall'utente
        # (spesso, con molte tab in dev, la console finiva fuori schermo): la posizione
        # viene salvata/ripristinata dalle preferenze. Vedi _apply_sash / _persist_sash.
        self.root.rowconfigure(1, weight=1)

        self.cf_var       = tk.StringVar()
        self.pin_var      = tk.StringVar()
        self.pwd_var      = tk.StringVar()
        self.cfstudio_var = tk.StringVar()
        self.modalita     = tk.StringVar(value=MODALITA_ACCESSO[0])

        self.backend_var  = tk.StringVar(value="browser")  # browser | requests
        self.backend_label_var = tk.StringVar(value=_BACKEND_LABELS["browser"])  # combo DEV_MODE
        self.headless_var = tk.BooleanVar(value=True)  # browser nascosto di default
        self.salva_cred_var = tk.BooleanVar(value=True)  # «non salvare credenziali»
        # Sezione «Credenziali Entratel» comprimibile (risparmio spazio, in attesa del
        # redesign GUI): True = espansa (default). Persistita in fec_settings.json.
        self.cred_espanse_var = tk.BooleanVar(value=True)
        # Se True disabilita l'aggiornamento automatico dell'anagrafica deleghe da AdE
        # durante il download (nessun recupero né popup). Vedi tab Deleghe.
        self.deleghe_no_update_var = tk.BooleanVar(value=False)

        # Scheda Download Standard (creati qui per poterli popolare da _load_config)
        self.std_destdir = tk.StringVar(value=DEFAULT_DEST_DIR)
        self.std_escludi_scartate = tk.BooleanVar(value=True)
        self.std_estrai_p7m = tk.BooleanVar(value=False)
        # Tipo documento "Fatture Emesse"/"Fatture Ricevute": aggiunge in coda,
        # sullo stesso periodo, rispettivamente le transfrontaliere emesse e le
        # messe a disposizione (checkbox visibili solo col tipo pertinente).
        self.std_includi_trans = tk.BooleanVar(value=False)
        self.std_includi_disposizione = tk.BooleanVar(value=False)
        # Estrae automaticamente lo zip dei risultati delle Richieste Massive.
        self.estrai_zip_risultati_massivi = tk.BooleanVar(value=False)

        # Cartelle per tipo di documento (popolate da _load_config): per ogni classe
        # path (override), «personalizza» e «senza sottocartella». Vuoto ⇒ usa std_destdir.
        self.dirclassi = {
            key: {
                "path":         tk.StringVar(value=""),
                "personalizza": tk.BooleanVar(value=False),
                "senza_sotto":  tk.BooleanVar(value=False),
            }
            for key, _label in DOC_CLASSI
        }

        self.process: "subprocess.Popen | None" = None
        self.worker: "threading.Thread | None" = None
        self.control = None   # fec_download.Controllo dell'operazione in corso (pausa/annulla)
        self._tab_notes: dict = {}  # tab (ttk.Frame) -> lista di note mostrate dal pulsante "?"

        self._load_config()
        # GUI pubblica: nessun selettore backend, default fisso su "requests" (login
        # leggero senza browser). In dev resta scelto da config/selettore.
        if not DEV_MODE:
            self.backend_var.set("requests")
        self._build_ui()
        self._refresh_dep_banner()  # controllo dipendenze all'avvio (inline, non bloccante)
        try:  # pulizia best-effort delle richieste massive "eliminata" scadute (standby 30gg)
            import fec_richieste_massive
            fec_richieste_massive.purge_scadute()
        except Exception:
            pass

    def _set_app_icon(self):
        """Imposta l'icona della finestra (assets/AppIcon1024.png). Best-effort:
        ignora se il file manca o il Tk in uso non supporta PNG."""
        try:
            self._app_icon = tk.PhotoImage(file=APP_ICON)  # ref tenuta viva
            self.root.iconphoto(True, self._app_icon)
        except Exception:
            pass

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self):
        """Carica credenziali (cifrate) e preferenze dai due file gestiti da fec_store."""
        try:
            import fec_store
            cred = fec_store.load_credentials()
            cfg = fec_store.load_settings()
        except Exception:
            cred, cfg = {}, {}
        self.cf_var.set(cred.get("cf", ""))
        self.pin_var.set(cred.get("pin", ""))
        self.cfstudio_var.set(cred.get("cfstudio", ""))
        self.backend_var.set(cfg.get("login_backend", "browser"))
        self.backend_label_var.set(_BACKEND_LABELS.get(self.backend_var.get(),
                                                       _BACKEND_LABELS["browser"]))
        self.headless_var.set(bool(cfg.get("browser_headless", True)))
        self.modalita.set(cfg.get("modalita", self.modalita.get()))
        self.std_destdir.set(cfg.get("std_destdir", DEFAULT_DEST_DIR) or DEFAULT_DEST_DIR)
        self.salva_cred_var.set(bool(cfg.get("salva_credenziali", True)))
        self.cred_espanse_var.set(bool(cfg.get("cred_espanse", True)))
        self.deleghe_no_update_var.set(bool(cfg.get("deleghe_no_update", False)))
        self.std_escludi_scartate.set(bool(cfg.get("std_escludi_scartate_pa", True)))
        self.std_estrai_p7m.set(bool(cfg.get("std_estrai_p7m", False)))
        self.std_includi_trans.set(bool(cfg.get("std_includi_trans", False)))
        self.std_includi_disposizione.set(bool(cfg.get("std_includi_disposizione", False)))
        self.estrai_zip_risultati_massivi.set(bool(cfg.get("estrai_zip_risultati_massivi", False)))
        # Posizione del divisore console/tab (px dal bordo alto del PanedWindow), o None.
        val = cfg.get("console_sash", None)
        self.console_sash = int(val) if isinstance(val, (int, float)) and val > 0 else None

        cartelle = cfg.get("cartelle_documenti", {}) or {}
        for key, vars_ in self.dirclassi.items():
            c = cartelle.get(key, {}) if isinstance(cartelle.get(key), dict) else {}
            vars_["path"].set(str(c.get("path", "")))
            vars_["personalizza"].set(bool(c.get("personalizza", False)))
            vars_["senza_sotto"].set(bool(c.get("senza_sottocartella", False)))

    def _save_config(self):
        """Salva credenziali (cifrate, se consentito) e preferenze nei due file."""
        import fec_store
        salva = bool(self.salva_cred_var.get())
        if salva:
            fec_store.save_credentials({
                "cf":       self.cf_var.get().strip(),
                "pin":      self.pin_var.get().strip(),
                "cfstudio": self.cfstudio_var.get().strip(),
            })
        else:
            fec_store.clear_credentials()
        cartelle = {
            key: {
                "path":               vars_["path"].get().strip(),
                "personalizza":       bool(vars_["personalizza"].get()),
                "senza_sottocartella": bool(vars_["senza_sotto"].get()),
            }
            for key, vars_ in self.dirclassi.items()
        }
        fec_store.save_settings({
            "login_backend":    self.backend_var.get(),
            "browser_headless": bool(self.headless_var.get()),
            "modalita":         self.modalita.get(),
            "std_destdir":      self.std_destdir.get().strip(),
            "salva_credenziali": salva,
            "cartelle_documenti": cartelle,
            "deleghe_no_update": bool(self.deleghe_no_update_var.get()),
            "std_escludi_scartate_pa": bool(self.std_escludi_scartate.get()),
            "std_estrai_p7m": bool(self.std_estrai_p7m.get()),
            "std_includi_trans": bool(self.std_includi_trans.get()),
            "std_includi_disposizione": bool(self.std_includi_disposizione.get()),
            "cred_espanse": bool(self.cred_espanse_var.get()),
            "estrai_zip_risultati_massivi": bool(self.estrai_zip_risultati_massivi.get()),
        })
        self._update_dest_info()
        if salva:
            messagebox.showinfo(
                "Salvato",
                "CF, PIN e CF Studio salvati (cifrati in fec_credentials.dat).\n"
                "La password non viene mai salvata.\nPreferenze salvate in fec_settings.json.")
        else:
            messagebox.showinfo(
                "Salvato",
                "Preferenze salvate. Credenziali NON salvate su questo computer "
                "(file credenziali rimosso).")

    def _dest_classe(self, key: str) -> tuple[str, bool]:
        """Risolve (cartella_base, crea_sottocartella) per una classe di documento.

        Usa la cartella personalizzata della classe se «personalizza» è attivo e il
        path è valorizzato; altrimenti la cartella di default (`std_destdir`).
        """
        default = self.std_destdir.get().strip() or DEFAULT_DEST_DIR
        vars_ = self.dirclassi.get(key)
        if not vars_:
            return default, True
        path = vars_["path"].get().strip()
        base = path if (vars_["personalizza"].get() and path) else default
        return base, not bool(vars_["senza_sotto"].get())

    def _install_deps(self):
        """Pulsante «Installa dipendenze»: fa scegliere se installare tutto (incluso
        Playwright + Chromium) o solo il set leggero per il backend «requests»."""
        # App pacchettizzata (PyInstaller) senza un Python di sistema: pip/playwright
        # non sono installabili. Spieghiamo il perché invece di lanciare un comando muto.
        if PYTHON is None:
            messagebox.showwarning(
                "Installazione non disponibile",
                "Questa è la versione pacchettizzata (.exe) e non è stato trovato un "
                "interprete Python di sistema.\n\n"
                "Per installare Playwright/Chromium: installa Python 3 da python.org "
                "(spuntando «Add python.exe to PATH»), riavvia l'app e riprova. In "
                "alternativa usa la versione da sorgente.\n\n"
                "Nota: il backend leggero «requests» funziona comunque senza Playwright.")
            return
        win = tk.Toplevel(self.root)
        win.title("Installa dipendenze")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        frm = ttk.Frame(win, padding=(20, 16))
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Quali dipendenze vuoi installare?",
                  font=("", 12, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            frm, justify="left", wraplength=440,
            text="• «Installa tutto» include Playwright e il browser Chromium: necessario per il "
                 "backend browser e per l'accesso SPID/CIE.\n"
                 "• «Solo backend leggero» installa il minimo per l'accesso «requests» "
                 "(niente Chromium): più veloce, sufficiente per studio → cliente.",
        ).pack(anchor="w", pady=(0, 14))

        def avvia(include_playwright: bool):
            win.destroy()
            modo = ("tutto (incluso Playwright + Chromium)" if include_playwright
                    else "solo backend leggero «requests»")
            self._log(f"\nInstallazione dipendenze: {modo}…\n")
            self._run_sequence(
                fec_deps.install_commands(include_playwright, python=PYTHON),
                on_done=self._refresh_dep_banner,
            )

        ttk.Button(frm, text="Installa tutto (con Playwright)", width=30,
                   command=lambda: avvia(True)).pack(fill=tk.X, pady=2)
        ttk.Button(frm, text="Solo backend leggero (senza Playwright)", width=30,
                   command=lambda: avvia(False)).pack(fill=tk.X, pady=2)
        ttk.Button(frm, text="Annulla", width=12,
                   command=win.destroy).pack(anchor="e", pady=(12, 0))
        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 80
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _uninstall_deps(self):
        """Strumento DEV: disinstalla le dipendenze selezionate via `pip uninstall`.
        Utile per testare il banner/controllo dipendenze. Solo in DEV_MODE."""
        installate = fec_deps.installed_deps()
        win = tk.Toplevel(self.root)
        win.title("Disinstalla dipendenze (dev)")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        frm = ttk.Frame(win, padding=(20, 16))
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Disinstalla dipendenze (strumento di test)",
                  font=("", 12, "bold")).pack(anchor="w", pady=(0, 2))
        ttk.Label(
            frm, justify="left", wraplength=440, foreground="#b9770e",
            text="Seleziona i pacchetti da rimuovere con «pip uninstall». Serve per verificare "
                 "il controllo dipendenze all'avvio; reinstallali poi con «Installa dipendenze».",
        ).pack(anchor="w", pady=(0, 12))

        if not installate:
            ttk.Label(frm, text="Nessuna dipendenza nota risulta installata.").pack(anchor="w")
            ttk.Button(frm, text="Chiudi", width=12, command=win.destroy).pack(anchor="e", pady=(12, 0))
            return

        ruoli = {"core": "richiesta", "browser": "opzionale", "gui": "opzionale", "p7m": "opzionale"}
        sel = {}
        for dep in installate:
            var = tk.BooleanVar(value=False)
            sel[dep.pip] = var
            ttk.Checkbutton(
                frm, variable=var,
                text=f"{dep.pip}   ({ruoli.get(dep.role, dep.role)})",
            ).pack(anchor="w")

        def disinstalla():
            scelti = [pip for pip, var in sel.items() if var.get()]
            if not scelti:
                messagebox.showinfo("Nessuna selezione", "Seleziona almeno una dipendenza.", parent=win)
                return
            win.destroy()
            self._log(f"\nDisinstallazione dipendenze: {', '.join(scelti)}…\n")
            self._run_sequence(
                fec_deps.uninstall_command(scelti, python=PYTHON),
                on_done=self._refresh_dep_banner,
            )

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, pady=(14, 0))
        ttk.Button(btns, text="Disinstalla selezionate", width=24,
                   command=disinstalla).pack(side=tk.LEFT)
        ttk.Button(btns, text="Annulla", width=12, command=win.destroy).pack(side=tk.RIGHT)
        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 80
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _show_about(self):
        """Finestra 'Informazioni' con versione e link a repository e licenza."""
        win = tk.Toplevel(self.root)
        win.title(f"Informazioni - {APP_NAME}")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        frm = ttk.Frame(win, padding=(22, 18))
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text=APP_NAME, font=("", 15, "bold")).pack(anchor="w")
        ttk.Label(frm, text=f"Versione {__version__}", foreground="#666").pack(anchor="w", pady=(0, 10))
        ttk.Label(
            frm, justify="left", wraplength=420,
            text="FeC-Plus è uno strumento per automatizzare l'accesso e lo "
                 "scaricamento dei dati dal portale «Fatture e Corrispettivi» "
                 "dell'Agenzia delle Entrate.\n\n"
                 "Il software è fornito «così com'è», senza garanzie. L'utente è "
                 "l'unico responsabile dell'uso che ne viene fatto.",
        ).pack(anchor="w", pady=(0, 12))

        def _link(testo, url):
            lbl = ttk.Label(frm, text=testo, foreground="#1a6fd6", cursor="hand2")
            f = tkfont.Font(font=lbl.cget("font")); f.configure(underline=True)
            lbl.configure(font=f)
            lbl.pack(anchor="w", pady=2)
            lbl.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))

        _link("🏠  Homepage del progetto", HOME_URL)
        _link("📘  Documentazione", DOCS_URL)
        _link("🔗  Repository GitHub", REPO_URL)
        _link("📄  Licenza", LICENSE_URL)

        ttk.Button(frm, text="Chiudi", command=win.destroy, width=12).pack(anchor="e", pady=(16, 0))
        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        # centra rispetto alla finestra principale
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 80
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    # ── UI skeleton ───────────────────────────────────────────────────────────

    def _fix_macos_paste(self):
        """
        macOS/Tk: con Cmd+V il testo viene incollato DUE volte (su Aqua partono due
        percorsi di paste: il `<<Paste>>` virtuale E il binding di classe `<Command-v>`
        del paste integrato) → dato raddoppiato.

        Fix: intercettiamo ENTRAMBI gli eventi con un unico handler che (a) incolla una
        sola volta e (b) ha un debounce che ignora un secondo paste ravvicinato sullo
        stesso campo, qualunque percorso lo abbia generato; restituisce sempre "break"
        per fermare il paste di default. Solo su macOS; altrove comportamento standard.
        """
        if sys.platform != "darwin":
            return

        import time
        ultimo = {}   # path-widget -> istante ultimo paste (debounce anti-doppio)

        def _paste(event):
            w = event.widget
            key = str(w)
            now = time.monotonic()
            if now - ultimo.get(key, 0.0) < 0.15:
                return "break"                    # secondo paste ravvicinato = duplicato Aqua
            ultimo[key] = now
            try:                                  # sostituisci l'eventuale selezione
                w.delete("sel.first", "sel.last")
            except tk.TclError:
                pass
            try:
                w.insert("insert", w.clipboard_get())
            except tk.TclError:
                pass
            return "break"

        for cls in ("Entry", "TEntry", "Text"):
            for seq in ("<<Paste>>", "<Command-v>", "<Command-V>"):
                self.root.bind_class(cls, seq, _paste)

    def _fix_caret(self):
        """
        Rende visibile il caret (cursore di inserimento lampeggiante) nei campi: con il
        tema `clam` (usato come fallback su macOS/Linux, dato che il loop temi in main()
        sceglie clam quando i temi Windows non ci sono) l'`insertcolor` di default è VUOTO
        → il cursore risulta invisibile. Lo impostiamo a un colore scuro e leggermente più
        spesso, su tutte le classi di campo testuale.
        """
        style = ttk.Style(self.root)
        for cls in ("TEntry", "TCombobox", "DateEntry"):
            try:
                style.configure(cls, insertcolor="#1e1e1e", insertwidth=2)
            except tk.TclError:
                pass

    def _build_ui(self):
        self._build_credentials()
        # Contenitore verticale ridimensionabile: notebook (in alto) + console (in basso),
        # con divisore trascinabile dall'utente. Sostituisce le due righe fisse di grid.
        self.main_paned = ttk.PanedWindow(self.root, orient="vertical")
        self.main_paned.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        self._build_notebook()
        self._build_console()
        self.main_paned.bind("<ButtonRelease-1>", lambda _e: self._persist_sash())
        self.root.after(180, self._apply_sash)  # posiziona il divisore a layout pronto

    def _build_credentials(self):
        frame = ttk.LabelFrame(self.root, text=" Credenziali Entratel ", padding=(10, 6))
        frame.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        frame.columnconfigure(0, weight=1)

        # Barra comprimi/espandi (risparmio spazio): sempre visibile, comanda la
        # visibilità di _cred_content.
        bar = ttk.Frame(frame)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)
        self._cred_toggle_btn = ttk.Button(bar, command=self._toggle_credenziali, width=16)
        self._cred_toggle_btn.grid(row=0, column=1, sticky="e")

        self._cred_content = ttk.Frame(frame)
        self._cred_content.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        for i in range(9):
            self._cred_content.columnconfigure(i, weight=(1 if i % 2 == 1 else 0))

        fields = [
            ("Codice Fiscale:", self.cf_var,      False),
            ("PIN:",            self.pin_var,      False),
            ("Password:",       self.pwd_var,      True),
            ("CF Studio:",      self.cfstudio_var, False),
        ]
        for idx, (lbl, var, secret) in enumerate(fields):
            label = ttk.Label(self._cred_content, text=lbl)
            label.grid(row=0, column=idx * 2, sticky="w", padx=(4, 2))
            if lbl == "CF Studio:":
                self._cfstudio_label = label
            ttk.Entry(self._cred_content, textvariable=var, width=16,
                      show="●" if secret else "").grid(
                row=0, column=idx * 2 + 1, sticky="ew", padx=(0, 8))

        btn_frame = ttk.Frame(self._cred_content)
        btn_frame.grid(row=0, column=8, rowspan=4, padx=(6, 4))
        ttk.Button(btn_frame, text="Salva credenziali",   command=self._save_config,   width=18).pack(pady=(0, 2))
        ttk.Button(btn_frame, text="⚙  Impostazioni",      command=self._show_settings, width=18).pack(pady=(0, 2))
        ttk.Button(btn_frame, text="Installa dipendenze", command=self._install_deps,  width=18).pack(pady=(0, 2))
        if DEV_MODE:  # strumento diagnostico per testare il controllo dipendenze
            ttk.Button(btn_frame, text="Disinstalla dipendenze", command=self._uninstall_deps, width=18).pack(pady=(0, 2))
        ttk.Button(btn_frame, text="ℹ  Informazioni",     command=self._show_about,    width=18).pack()

        ttk.Label(self._cred_content, text="Modalità di accesso:").grid(
            row=1, column=0, sticky="w", padx=(4, 2), pady=(6, 0))
        ttk.Combobox(self._cred_content, textvariable=self.modalita, values=MODALITA_ACCESSO,
                     state="readonly", width=30).grid(
            row=1, column=1, columnspan=3, sticky="w", pady=(6, 0))
        self.modalita.trace_add("write", self._aggiorna_etichetta_cfstudio)
        self._aggiorna_etichetta_cfstudio()

        if DEV_MODE:  # backend di login: irrilevante per la GUI pubblica (forzata su requests)
            ttk.Label(self._cred_content, text="Backend di login:").grid(
                row=2, column=0, sticky="w", padx=(4, 2), pady=(6, 0))
            backend_frame = ttk.Frame(self._cred_content)
            backend_frame.grid(row=2, column=1, columnspan=3, sticky="w", pady=(6, 0))
            ttk.Combobox(backend_frame, textvariable=self.backend_label_var,
                        values=list(_BACKEND_LABELS.values()), state="readonly",
                        width=20).pack(side=tk.LEFT)
            ttk.Checkbutton(backend_frame, text="headless", variable=self.headless_var).pack(
                side=tk.LEFT, padx=(10, 0))
            self.backend_label_var.trace_add("write", self._aggiorna_backend_var)

        ttk.Checkbutton(
            self._cred_content, text="Non salvare le credenziali su questo computer",
            variable=self.salva_cred_var, onvalue=False, offvalue=True,
        ).grid(row=3, column=0, columnspan=8, sticky="w", padx=(4, 0), pady=(4, 0))

        # Banner dipendenze: avviso inline non bloccante, popolato da
        # _refresh_dep_banner(); resta nascosto (grid_remove) se non manca nulla.
        self.dep_banner = ttk.Label(self._cred_content, wraplength=720, justify="left")
        self.dep_banner.grid(row=4, column=0, columnspan=9, sticky="w", padx=(4, 0), pady=(6, 0))
        self.dep_banner.grid_remove()

        self._apply_cred_espanse()  # applica lo stato caricato da _load_config

    def _aggiorna_etichetta_cfstudio(self, *_):
        """Rietichetta il campo CF Studio come CF Azienda con la modalità Azienda."""
        self._cfstudio_label.configure(
            text="CF Azienda:" if self.modalita.get() == "Azienda" else "CF Studio:")

    def _aggiorna_backend_var(self, *_):
        """Sincronizza `backend_var` (valore tecnico) con la scelta nel combo DEV_MODE."""
        self.backend_var.set(_BACKEND_DA_LABEL.get(self.backend_label_var.get(), "browser"))

    def _apply_cred_espanse(self):
        """Mostra/nasconde il contenuto della sezione credenziali secondo
        `cred_espanse_var`, senza persistere (usato anche all'avvio)."""
        if bool(self.cred_espanse_var.get()):
            self._cred_content.grid()
            self._cred_toggle_btn.configure(text="▲  Comprimi")
        else:
            self._cred_content.grid_remove()
            self._cred_toggle_btn.configure(text="▼  Espandi")

    def _toggle_credenziali(self):
        """Comprimi/espandi la sezione credenziali (risparmio spazio) e ricorda la
        scelta (merge nelle preferenze, senza toccare le credenziali salvate)."""
        self.cred_espanse_var.set(not bool(self.cred_espanse_var.get()))
        self._apply_cred_espanse()
        try:
            import fec_store
            cfg = fec_store.load_settings()
            cfg["cred_espanse"] = bool(self.cred_espanse_var.get())
            fec_store.save_settings(cfg)
        except Exception:
            pass

    def _refresh_dep_banner(self):
        """Controllo dipendenze all'avvio: mostra inline le dipendenze mancanti.

        Convenzione UI avvisi: avviso inline, mai messagebox. Le mancanze «core»
        sono gravi (rosse), Playwright e tkcalendar sono opzionali (note arancio/grigio).
        """
        missing = fec_deps.find_missing()
        righe = []
        colore = "#777777"
        if missing["core"]:
            colore = "#c0392b"
            righe.append("⚠ Dipendenze richieste mancanti: "
                         + ", ".join(missing["core"])
                         + "  → usa «Installa dipendenze».")
        if missing["browser"]:
            if not missing["core"]:
                colore = "#b9770e"
            righe.append("• Playwright assente: disponibile solo il backend leggero «requests» "
                         "(niente backend browser / SPID-CIE).")
        if missing["gui"]:
            righe.append("• tkcalendar assente: il calendario è in modalità testo.")

        if righe:
            self.dep_banner.configure(text="\n".join(righe), foreground=colore)
            self.dep_banner.grid()
        else:
            self.dep_banner.grid_remove()

    def _show_settings(self):
        """Form preferenze: cartella download, profilo di default, salvataggio credenziali."""
        win = tk.Toplevel(self.root)
        win.title("Impostazioni - preferenze")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        frm = ttk.Frame(win, padding=(18, 14))
        frm.pack(fill=tk.BOTH, expand=True)

        r = 0
        ttk.Label(frm, text="Preferenze", font=("", 13, "bold")).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(0, 10))

        r += 1
        ttk.Label(frm, text="Cartella download di default:").grid(row=r, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Entry(frm, textvariable=self.std_destdir, width=40).grid(row=r, column=1, sticky="we")
        ttk.Button(frm, text="Sfoglia…", width=10, command=self._std_pick_destdir).grid(row=r, column=2, padx=(6, 0))

        r += 1
        self._build_cartelle_classi(frm, r)

        r += 1
        ttk.Checkbutton(frm, text="Non salvare le credenziali su questo computer",
                        variable=self.salva_cred_var, onvalue=False, offvalue=True).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(8, 0))

        r += 1
        ttk.Checkbutton(frm, text="Estrai automaticamente lo zip dei risultati delle "
                                  "Richieste Massive",
                        variable=self.estrai_zip_risultati_massivi).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(4, 0))

        r += 1
        ttk.Checkbutton(frm, text="Download Standard: includi fatture transfrontaliere "
                                  "(default con tipo «Fatture Emesse»)",
                        variable=self.std_includi_trans).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(4, 0))

        r += 1
        ttk.Checkbutton(frm, text="Download Standard: includi fatture Messe a Disposizione "
                                  "(default con tipo «Fatture Ricevute»)",
                        variable=self.std_includi_disposizione).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(4, 0))

        if DEV_MODE:
            r += 1
            ttk.Label(frm, text=f"(dev) backend: {self.backend_var.get()} · "
                               f"headless: {'on' if self.headless_var.get() else 'off'}",
                      foreground="#888").grid(row=r, column=0, columnspan=3, sticky="w", pady=(8, 0))

        r += 1
        ttk.Label(frm, text="Le credenziali sono cifrate (cifratura leggera/portabile); "
                            "la password Entratel non viene mai salvata.",
                  foreground="#777", wraplength=440).grid(row=r, column=0, columnspan=3, sticky="w", pady=(10, 0))

        r += 1
        bar = ttk.Frame(frm)
        bar.grid(row=r, column=0, columnspan=3, sticky="e", pady=(16, 0))
        ttk.Button(bar, text="Salva", width=12,
                   command=lambda: (self._save_config(), win.destroy())).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(bar, text="Chiudi", width=12, command=win.destroy).pack(side=tk.RIGHT)

        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 80
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _build_cartelle_classi(self, frm: ttk.Widget, row: int):
        """Sezione «Cartelle per tipo di documento»: per ogni classe un override di
        cartella («personalizza» + path + Sfoglia) e l'opzione «senza sottocartella»."""
        box = ttk.LabelFrame(frm, text=" Cartelle per tipo di documento ", padding=(10, 6))
        box.grid(row=row, column=0, columnspan=3, sticky="we", pady=(8, 4))
        box.columnconfigure(2, weight=1)

        ttk.Label(box, text="Spunta «personalizza» per assegnare una cartella diversa "
                            "dalla default; «senza sottocartella» salva i file direttamente "
                            "nella cartella (utile per i gestionali).",
                  foreground="#777", wraplength=520).grid(
            row=0, column=0, columnspan=5, sticky="w", pady=(0, 6))

        for i, (key, label) in enumerate(DOC_CLASSI, start=1):
            v = self.dirclassi[key]
            entry = ttk.Entry(box, textvariable=v["path"], width=34)
            btn = ttk.Button(box, text="Sfoglia…", width=10,
                             command=lambda k=key: self._pick_classe_dir(k))

            def _toggle(k=key, e=entry, b=btn):
                on = bool(self.dirclassi[k]["personalizza"].get())
                if on and not self.dirclassi[k]["path"].get().strip():
                    self.dirclassi[k]["path"].set(
                        self.std_destdir.get().strip() or DEFAULT_DEST_DIR)
                st = "normal" if on else "disabled"
                e.configure(state=st)
                b.configure(state=st)

            ttk.Checkbutton(box, text="personalizza", variable=v["personalizza"],
                            command=_toggle).grid(row=i, column=0, sticky="w", padx=(0, 6), pady=1)
            ttk.Label(box, text=label, width=20).grid(row=i, column=1, sticky="w", padx=(0, 6))
            entry.grid(row=i, column=2, sticky="we", padx=(0, 4))
            btn.grid(row=i, column=3, padx=(0, 8))
            ttk.Checkbutton(box, text="senza sottocartella",
                            variable=v["senza_sotto"]).grid(row=i, column=4, sticky="w")
            _toggle()  # stato iniziale entry/btn coerente con «personalizza»

    def _pick_classe_dir(self, key: str):
        v = self.dirclassi[key]
        scelta = filedialog.askdirectory(
            title="Cartella per questo tipo di documento",
            initialdir=v["path"].get().strip()
                       or self.std_destdir.get().strip() or DEFAULT_DEST_DIR)
        if scelta:
            v["path"].set(scelta)

    def _build_notebook(self):
        nb = ttk.Notebook(self.main_paned)
        self.main_paned.add(nb, weight=3)

        if DEV_MODE:
            self._tab_test_login(nb)
        self._tab_standard(nb)
        self._tab_richiesta_massiva(nb)
        self._tab_bolli(nb)
        self._tab_utility(nb)
        # Anagrafica deleghe: ultima tab.
        self._tab_deleghe(nb)

    def _build_console(self):
        frame = ttk.LabelFrame(self.main_paned, text=" Output ", padding=(6, 4))
        self.main_paned.add(frame, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        # La console vive nel PanedWindow: la sua altezza è data dal divisore trascinabile
        # (posizione iniziale/ripristino gestiti da _apply_sash).

        self.console = scrolledtext.ScrolledText(
            frame, height=12, state="disabled",
            font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="white", relief="flat",
        )
        self.console.grid(row=0, column=0, sticky="nsew")

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=1, column=0, sticky="e", pady=(4, 0))
        ttk.Button(btn_row, text="Pulisci",    command=self._clear_console, width=10).pack(side=tk.RIGHT, padx=3)
        ttk.Button(btn_row, text="Interrompi", command=self._stop_process,  width=10).pack(side=tk.RIGHT, padx=3)
        self.pausa_btn = ttk.Button(btn_row, text="⏸ Pausa", command=self._toggle_pausa, width=10)
        self.pausa_btn.pack(side=tk.RIGHT, padx=3)

    # ── Divisore console/tab ridimensionabile ─────────────────────────────────

    def _apply_sash(self):
        """Posiziona il divisore all'avvio: valore salvato o, in mancanza, ~58%
        dell'altezza (console ben visibile). Best-effort; riprova se il layout non
        è ancora dimensionato."""
        try:
            self.main_paned.update_idletasks()
            h = self.main_paned.winfo_height()
            if h <= 1:
                self.root.after(150, self._apply_sash)
                return
            pos = self.console_sash if (self.console_sash and 0 < self.console_sash < h) \
                else int(h * 0.58)
            self.main_paned.sashpos(0, pos)
        except Exception:
            pass

    def _persist_sash(self):
        """Salva la posizione del divisore nelle preferenze, senza toccare le
        credenziali (merge sul file settings esistente)."""
        try:
            pos = int(self.main_paned.sashpos(0))
        except Exception:
            return
        if pos <= 0:
            return
        self.console_sash = pos
        try:
            import fec_store
            cfg = fec_store.load_settings()
            cfg["console_sash"] = pos
            fec_store.save_settings(cfg)
        except Exception:
            pass

    # ── Console helpers ───────────────────────────────────────────────────────

    def _log(self, text: str):
        self.console.configure(state="normal")
        self.console.insert(tk.END, text)
        self.console.see(tk.END)
        self.console.configure(state="disabled")

    def _clear_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", tk.END)
        self.console.configure(state="disabled")

    def _stop_process(self):
        agito = False
        # Download/operazione in-process: annullamento cooperativo (effettivo al
        # prossimo file, o quando la richiesta HTTP in corso ritorna/va in timeout).
        if self.control is not None and self.worker and self.worker.is_alive():
            self.control.annulla()
            agito = True
        # Subprocess (installazione dipendenze pip/playwright).
        if self.process and self.process.poll() is None:
            self.process.terminate()
            agito = True
        if agito:
            self._log("\n[INTERRUZIONE richiesta dall'utente - termino appena possibile...]\n")

    def _toggle_pausa(self):
        """Mette in pausa / riprende lo scaricamento dei file (tra un file e l'altro)."""
        if self.control is None or not (self.worker and self.worker.is_alive()):
            return
        if self.control.in_pausa():
            self.control.riprendi()
            self.pausa_btn.configure(text="⏸ Pausa")
            self._log("\n[Ripreso]\n")
        else:
            self.control.pausa()
            self.pausa_btn.configure(text="▶ Riprendi")
            self._log("\n[In pausa - riprendo al prossimo file]\n")

    def _reset_pausa_btn(self):
        self.pausa_btn.configure(text="⏸ Pausa")

    # ── Process runner ────────────────────────────────────────────────────────

    def _run_sequence(self, commands: list, on_done=None):
        """Esegue più comandi in sequenza nello stesso thread, fermandosi al primo errore.
        Usato solo dall'installazione dipendenze (pip / playwright). `on_done`, se passato,
        viene richiamato nel thread Tk al termine (anche in caso di errore)."""
        if self.process and self.process.poll() is None:
            messagebox.showwarning("In esecuzione", "Un processo è già in esecuzione.")
            return

        def _finish():
            if on_done is not None:
                self.root.after(0, on_done)

        def _target():
            for args in commands:
                self.root.after(0, self._log, f"\n▶  {' '.join(str(a) for a in args)}\n")
                try:
                    self.process = subprocess.Popen(
                        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace", cwd=SCRIPT_DIR,
                    )
                    if self.process.stdout is not None:
                        for line in self.process.stdout:
                            self.root.after(0, self._log, line)
                    self.process.wait()
                    if self.process.returncode != 0:
                        self.root.after(0, self._log,
                                        f"\n[Interrotto - codice {self.process.returncode}]\n")
                        _finish()
                        return
                except Exception as exc:
                    self.root.after(0, self._log, f"\n[ERRORE] {exc}\n")
                    _finish()
                    return
            self.root.after(0, self._log, "\n[Completato]\n")
            _finish()

        threading.Thread(target=_target, daemon=True).start()

    def _run_inprocess(self, fn):
        """Esegue una funzione fn(log) in un thread, instradando il log nella console."""
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("In esecuzione", "Un'operazione è già in corso.")
            return

        def log(text: str):
            self.root.after(0, self._log, text if text.endswith("\n") else text + "\n")

        def _target():
            try:
                fn(log)
            except Exception as exc:
                log(f"\n❌ {exc}")
            finally:
                self.root.after(0, self._on_worker_done)

        self.worker = threading.Thread(target=_target, daemon=True)
        self.worker.start()

    def _on_worker_done(self):
        """Ripristina lo stato dei controlli al termine dell'operazione in-process."""
        self.control = None
        self._reset_pausa_btn()

    def _esegui_in_process(self, cfcl, piva, profilo: int, descrizione, operazione):
        """
        Autentica UNA volta in-process (backend/headless dalla scheda Test Login)
        e poi esegue `operazione(res, log, fec_queue)` sull'AuthResult.
        `operazione` deve chiamare `fec_queue.esegui_richiesta(...)`, che orchestra
        lo spezzettamento dei periodi lunghi sopra fec_download. `profilo` è già il
        valore numerico risolto (vedi `_profilo_da_modalita`), non la stringa combo.
        Tutto gira in un worker thread, con log instradato nella console.
        """
        cf, pin, pwd, cfst = self._get_creds()
        backend  = self.backend_var.get()
        headless = bool(self.headless_var.get())

        # Controllo pausa/annulla per QUESTA operazione (creato sul thread Tk così i
        # pulsanti Pausa/Interrompi lo vedono subito).
        import fec_download
        self.control = fec_download.Controllo()
        self._reset_pausa_btn()
        control = self.control

        def task(log):
            from ade_auth import autentica, Creds, AuthError
            import fec_download
            import fec_queue

            log(f"\n{'─' * 60}\n▶  {descrizione} (in-process, backend: {backend})\n{'─' * 60}")
            creds = Creds(nomeutente=cf, pin=pin, password=pwd, cfstudio=cfst,
                          cf_cliente=cfcl, piva=piva, profilo=profilo)
            try:
                # Se la P.IVA non è indicata e il CF ne ha più d'una, il popup di
                # scelta viene mostrato (solo backend requests; browser: ignorato).
                res = autentica(creds, backend=backend, headless=headless, log=log,
                                scegli_piva=self._chiedi_piva_thread)
            except AuthError as exc:
                log(f"\n❌ Login fallito allo step «{exc.step}»: {exc.dettaglio}")
                return
            msg_piva = f", P.IVA {res.piva}" if res.piva else ""
            log(f"\n✅ Login OK - backend {res.backend}{msg_piva}. Avvio operazione...")

            # Arricchimento anagrafica deleghe da AdE (salvo spunta «non aggiornare»).
            if cfcl and not self.deleghe_no_update_var.get():
                try:
                    import fec_anagrafica
                    dati = fec_anagrafica.recupera(res, log=log)
                    self._applica_aggiornamento_delega(cfcl, dati, log)
                except Exception as exc:  # noqa: BLE001 - non deve bloccare il download
                    log(f"⚠️  Aggiornamento anagrafica non riuscito: {exc}")

            try:
                operazione(res, log, fec_queue, control)
            except fec_download.DownloadAnnullato as exc:
                log(f"\n⏹  {exc}")
                return
            except fec_download.DownloadError as exc:
                log(f"\n❌ Operazione non riuscita: {exc}")
                return
            log("\n[Completato]")

        self._run_inprocess(task)

    # ── Generic widget helpers ────────────────────────────────────────────────

    @staticmethod
    def _lf(parent) -> ttk.Frame:
        f = ttk.Frame(parent, padding=(14, 10))
        f.pack(fill=tk.BOTH, expand=True)
        return f

    @staticmethod
    def _row(frame, row: int, label: str, var: tk.StringVar, width: int = 22, show: str = "") -> ttk.Entry:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
        entry = ttk.Entry(frame, textvariable=var, width=width, show=show)
        entry.grid(row=row, column=1, sticky="w")
        return entry

    @staticmethod
    def _combo(frame, row: int, label: str, var: tk.StringVar, values: list) -> ttk.Combobox:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
        cb = ttk.Combobox(frame, textvariable=var, values=values, state="readonly", width=34)
        cb.grid(row=row, column=1, sticky="w")
        return cb

    @staticmethod
    def _run_btn(frame, row: int, label: str, cmd, width: int = 18) -> ttk.Button:
        btn = ttk.Button(frame, text=f"▶  {label}", command=cmd, width=width)
        btn.grid(row=row, column=0, columnspan=2, pady=12)
        return btn

    def _note(self, frame, row: int, text: str):
        """Registra `text` come nota informativa della tab a cui appartiene `frame`
        (risalendo con `frame.master`), da mostrare tramite il pulsante "?" della tab
        invece che come testo sempre visibile nel layout. `row` non è più usato per il
        posizionamento ma resta nella firma per non toccare tutte le chiamate esistenti."""
        self._tab_notes.setdefault(frame.master, []).append(text)

    def _add_help_button(self, tab, corner: str = "ne"):
        """Aggiunge il pulsante "?" a un angolo di `tab` (in alto a destra di default,
        `corner="se"` per il basso a destra), che apre un popup con le note registrate
        per quella tab (vedi `_note`). Va chiamato come ultima riga di ogni metodo
        `_tab_xxx` dopo aver costruito tutti i controlli."""
        if corner == "se":
            opts = dict(relx=1.0, rely=1.0, x=-4, y=-4, anchor="se")
        else:
            opts = dict(relx=1.0, x=-4, y=4, anchor="ne")
        ttk.Button(tab, text="?", width=3,
                  command=lambda: self._mostra_note_tab(tab)).place(**opts)

    def _mostra_note_tab(self, tab):
        note = self._tab_notes.get(tab, [])
        win = tk.Toplevel(self.root)
        win.title("Informazioni")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=(18, 14))
        frm.pack(fill=tk.BOTH, expand=True)
        if not note:
            ttk.Label(frm, text="Nessuna informazione per questa scheda.").pack(anchor="w")
        for i, testo in enumerate(note):
            ttk.Label(frm, text=testo, foreground="#555555", wraplength=460,
                     justify="left").pack(anchor="w", pady=(0 if i == 0 else 10, 0))
        ttk.Button(frm, text="Chiudi", command=win.destroy).pack(anchor="e", pady=(14, 0))

        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 80
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    # ── Selettore date: calendario + periodi predefiniti ─────────────────

    @staticmethod
    def _date_widget(frame, var: tk.StringVar, strf: str, on_user_change=None):
        """
        Widget data: DateEntry (calendario) se tkcalendar è disponibile, altrimenti Entry
        testuale. La `var` (StringVar) viene mantenuta nel formato richiesto da `strf`
        (es. '%d%m%Y' o '%Y-%m-%d'), così i runner la usano senza conversioni.
        `on_user_change` (se passato) viene invocato SOLO quando l'utente modifica la data
        a mano (calendario/tastiera), NON quando la data è impostata da codice (`set_date`).
        """
        if DateEntry is not None:
            from datetime import date
            w = DateEntry(frame, width=14, locale="it_IT", date_pattern="dd/mm/yyyy",
                          showweeknumbers=False, maxdate=date.today())  # niente date future

            def _sync(_e=None):
                try:
                    var.set(w.get_date().strftime(strf))
                except Exception:
                    pass

            def _on_event(_e=None):
                _sync()
                if on_user_change:
                    on_user_change()

            w.bind("<<DateEntrySelected>>", _on_event)
            w.bind("<FocusOut>", _on_event)
            _sync()  # allinea subito la var alla data mostrata (oggi), senza on_user_change
            return w

        e = ttk.Entry(frame, textvariable=var, width=14)
        if on_user_change:
            e.bind("<KeyRelease>", lambda _e: on_user_change())
        return e

    @staticmethod
    def _set_date(widget, var: tk.StringVar, d, strf: str):
        """Imposta una data (oggetto date) sul widget e sulla var nel formato `strf`."""
        if _HAS_TKCAL and hasattr(widget, "set_date"):
            try:
                widget.set_date(d)
            except Exception:
                pass
        var.set(d.strftime(strf))

    def _build_date_range(self, frame, row: int, dal_var: tk.StringVar,
                          al_var: tk.StringVar, strf: str,
                          period_var: "tk.StringVar | None" = None) -> int:
        """
        Riga «Periodo:» = dropdown periodi GENERICI (trimestri/mesi/anno) + casella ANNO
        (4 cifre) che insieme precompilano le date. Sotto, i due selettori data
        (inizio/fine): se l'utente li modifica a mano, il periodo si azzera.
        Ritorna il numero di riga successivo.

        `period_var`: StringVar opzionale del chiamante per osservare il periodo
        selezionato (es. mostrare opzioni extra solo con «Anno intero»); si azzera
        quando l'utente modifica le date a mano.
        """
        import calendar
        from datetime import date

        oggi = date.today()
        periodi = _periodi_generici()
        mapping = {lbl: (m0, m1) for lbl, m0, m1 in periodi}
        if period_var is None:
            period_var = tk.StringVar()
        anno_var = tk.StringVar(value=str(oggi.year))

        # Anno PRIMA del periodo: si sceglie l'anno, poi il periodo dalla tendina.
        ttk.Label(frame, text="Anno / periodo:").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
        pframe = ttk.Frame(frame)
        pframe.grid(row=row, column=1, sticky="w")
        vcmd = (frame.register(lambda P: P == "" or (P.isdigit() and len(P) <= 4)), "%P")
        anno_entry = ttk.Spinbox(pframe, textvariable=anno_var, width=6,
                                 from_=2000, to=2100, validate="key",
                                 validatecommand=vcmd, command=lambda: _apply())
        anno_entry.pack(side=tk.LEFT)
        cb = ttk.Combobox(pframe, textvariable=period_var, state="readonly",
                          width=16, values=[p[0] for p in periodi])
        cb.pack(side=tk.LEFT, padx=(8, 0))
        warn_lbl = ttk.Label(pframe, text="", foreground="#c0392b")
        warn_lbl.pack(side=tk.LEFT, padx=(10, 0))

        def _periodo_futuro(label: str) -> bool:
            """True se il periodo, nell'anno scelto, inizia dopo oggi (non valido)."""
            anno = anno_var.get()
            if not (anno.isdigit() and len(anno) == 4):
                return False
            return date(int(anno), mapping[label][0], 1) > oggi

        def _style_popdown(*_):
            """Mostra in grigio chiaro i periodi non validi (futuri) nella tendina."""
            try:
                popdown = cb.tk.eval(f"ttk::combobox::PopdownWindow {cb}")
                lb = popdown + ".f.l"
                for i, (lbl, _m0, _m1) in enumerate(periodi):
                    fg = "#b0b0b0" if _periodo_futuro(lbl) else "black"
                    cb.tk.call(lb, "itemconfigure", i, "-foreground", fg)
            except tk.TclError:
                pass

        cb.configure(postcommand=_style_popdown)

        # selettori data; modificandoli a mano si azzera il periodo selezionato
        r_dal = row + 1
        ttk.Label(frame, text="Data inizio:").grid(row=r_dal, column=0, sticky="w", pady=4, padx=(0, 8))
        dal_w = self._date_widget(frame, dal_var, strf, on_user_change=lambda: period_var.set(""))
        dal_w.grid(row=r_dal, column=1, sticky="w")

        r_al = row + 2
        ttk.Label(frame, text="Data fine:").grid(row=r_al, column=0, sticky="w", pady=4, padx=(0, 8))
        al_w = self._date_widget(frame, al_var, strf, on_user_change=lambda: period_var.set(""))
        al_w.grid(row=r_al, column=1, sticky="w")

        if not _HAS_TKCAL:
            fmt = "ggmmaaaa" if strf == "%d%m%Y" else "aaaa-mm-gg"
            self._note(frame, r_al + 1, f"(Installa «tkcalendar» per il calendario; "
                                        f"formato manuale: {fmt}.)")

        def _apply(_e=None):
            sel = period_var.get()
            anno = anno_var.get()
            if sel not in mapping or not (anno.isdigit() and len(anno) == 4):
                return
            a = int(anno)
            m0, m1 = mapping[sel]
            dal_d = date(a, m0, 1)
            al_d = date(a, m1, calendar.monthrange(a, m1)[1])
            # L'AdE non ammette date future: se l'intero periodo è nel futuro non
            # precompilo nulla e avviso; altrimenti taglio la data fine a oggi.
            if dal_d > oggi:
                warn_lbl.configure(text="⚠ Periodo nel futuro: non selezionabile")
                return
            warn_lbl.configure(text="")
            if al_d > oggi:
                al_d = oggi
            # set_date() è programmatico → NON fa scattare on_user_change (periodo resta)
            self._set_date(dal_w, dal_var, dal_d, strf)
            self._set_date(al_w, al_var, al_d, strf)

        cb.bind("<<ComboboxSelected>>", _apply)
        anno_entry.bind("<KeyRelease>", _apply)

        # Default: trimestre in corso dell'anno corrente (inizio trimestre → oggi).
        period_var.set(f"{(oggi.month - 1) // 3 + 1}º trimestre")
        _apply()

        return row + (4 if not _HAS_TKCAL else 3)

    def _get_creds(self):
        return (
            self.cf_var.get().strip(),
            self.pin_var.get().strip(),
            self.pwd_var.get().strip(),
            self.cfstudio_var.get().strip(),
        )

    def _validate(self, **named_values) -> bool:
        missing = [lbl for lbl, val in named_values.items() if not str(val).strip()]
        if missing:
            messagebox.showerror(
                "Campi obbligatori mancanti",
                "Compila i seguenti campi:\n• " + "\n• ".join(missing),
            )
            return False
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 0 - Test Login (smoke-test del login AdE, in-process)
    # ─────────────────────────────────────────────────────────────────────────

    def _tab_test_login(self, nb: ttk.Notebook):
        tab = ttk.Frame(nb)
        nb.add(tab, text="  Test Login  ")
        f = self._lf(tab)

        self.tl_cfcl    = tk.StringVar()
        self.tl_piva    = tk.StringVar()

        r = 0
        ttk.Label(
            f,
            text="Verifica che l'app si avvii e superi il login del portale AdE "
                 "(credenziali Entratel in alto).",
            foreground="#555", wraplength=560,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(0, 8))

        r += 1; self._row(f, r, "CF Cliente:", self.tl_cfcl)
        r += 1; self._row(f, r, "P.IVA Cliente:", self.tl_piva)
        r += 1; self._note(f, r, "La modalità di accesso (Studio, Azienda, Libero professionista/"
                                 "Me stesso) si sceglie in alto nel riquadro «Credenziali Entratel» "
                                 "e vale per tutta l'app, non solo per questa scheda. Per «Studio» "
                                 "o «Azienda» compila anche il campo sotto le credenziali (l'etichetta "
                                 "diventa «CF Studio» o «CF Azienda» a seconda della modalità scelta). "
                                 "Col backend Browser puoi completare a mano l'eventuale scelta "
                                 "utenza nella finestra Chromium.")
        r += 1; self._run_btn(f, r, "Test Login", self._run_test_login)
        r += 1
        bar_cattura = ttk.Frame(f)
        bar_cattura.grid(row=r, column=0, columnspan=2, pady=(0, 4))
        ttk.Button(bar_cattura, text="🎥  Cattura login (HAR)", command=self._run_capture_login,
                   width=24).pack(side=tk.LEFT)
        ttk.Button(bar_cattura, text="🎥  Cattura HAR generico", command=self._run_capture_generico,
                   width=24).pack(side=tk.LEFT, padx=(8, 0))
        r += 1; self._note(f, r, "«Cattura login» registra solo il login e chiude il browser non "
                                 "appena completato: utile per diagnosticare il backend «Solo "
                                 "requests» quando smette di funzionare. «Cattura HAR generico» "
                                 "invece lascia il browser aperto dopo il login: naviga tu dove "
                                 "serve e chiudi il browser per salvare la registrazione. Entrambi "
                                 "salvano in «_materiale/»; i file contengono credenziali in "
                                 "chiaro, non condividerli.")

        # Strumenti investigativi sul portale Deleghe (diverso dal portale Fatture &
        # Corrispettivi): stesso schema di cattura HAR usato nella tab Utility.
        r += 1
        ttk.Separator(f, orient="horizontal").grid(row=r, column=0, columnspan=2,
                                                   sticky="ew", pady=(10, 2))
        r += 1
        ttk.Button(f, text="🎥  Cattura HAR Deleghe", command=self._run_capture_deleghe,
                   width=24).grid(row=r, column=0, columnspan=2, pady=(2, 4))
        r += 1
        ttk.Button(f, text="💾  Salva log console", command=self._salva_log_console,
                   width=24).grid(row=r, column=0, columnspan=2, pady=(0, 4))
        r += 1; self._note(f, r, "Strumento investigativo per il portale «Deleghe» "
                                 "(portale.agenziaentrate.gov.it, diverso da Fatture & "
                                 "Corrispettivi). Apre il browser visibile: effettua tu il login e "
                                 "naviga fino a «Deleghe -> Elenco deleganti», poi «Esporta "
                                 "elenco». Chiudi il browser per salvare la cattura in "
                                 "«_materiale/».")

        self._add_help_button(tab)

    def _run_capture_login(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl    = self.tl_cfcl.get().strip()
        piva    = self.tl_piva.get().strip()
        profilo = _profilo_da_modalita(self.modalita.get())

        if not self._validate(**{"Nome utente/CF": cf, "PIN": pin, "Password": pwd}):
            return

        capture_dir = os.path.join(SCRIPT_DIR, "_materiale")

        def task(log):
            from ade_auth import autentica, Creds, AuthError
            log(f"\n{'─' * 60}\n🎥  Cattura login (backend browser, finestra visibile)\n{'─' * 60}")
            creds = Creds(nomeutente=cf, pin=pin, password=pwd, cfstudio=cfst,
                          cf_cliente=cfcl, piva=piva, profilo=profilo)
            try:
                res = autentica(creds, backend="browser", headless=False, log=log,
                                capture_dir=capture_dir)
            except AuthError as exc:
                log(f"\n❌ Login fallito allo step «{exc.step}»: {exc.dettaglio}")
                log("ℹ️  La cattura parziale potrebbe comunque essere stata salvata in «_materiale/».")
                return
            log(f"\n✅ Login OK - cattura completata (vedi i percorsi HAR/LOG qui sopra).")
            for n in res.note:
                log(f"   ℹ️  {n}")

        self._run_inprocess(task)

    def _run_capture_generico(self):
        """Cattura HAR a navigazione libera, riusabile per qualsiasi investigazione
        (non solo Deleghe/Corrispettivi, che hanno il proprio bottone dedicato): login
        precompilato, poi l'utente naviga liberamente ovunque serva e chiude il browser
        per salvare la cattura."""
        cf, pin, pwd, cfst = self._get_creds()
        if not self._validate(**{"Nome utente/CF": cf, "PIN": pin, "Password": pwd}):
            return

        capture_dir = os.path.join(SCRIPT_DIR, "_materiale")

        def task(log):
            from ade_auth import cattura_har_navigazione, AuthError
            log(f"\n{'─' * 60}\n🎥  Cattura HAR generico (navigazione libera)\n{'─' * 60}")
            try:
                cattura_har_navigazione(
                    cf, pin, pwd, capture_dir=capture_dir, prefisso="capture_generico",
                    hint="Naviga liberamente fino alla pagina/funzione da investigare, poi "
                         "chiudi il browser per salvare la cattura.",
                    log=log)
            except AuthError as exc:
                log(f"\n❌ Cattura fallita allo step «{exc.step}»: {exc.dettaglio}")
                log("ℹ️  Una cattura parziale potrebbe comunque essere in «_materiale/».")
            except Exception as exc:
                log(f"\n❌ Cattura fallita: {exc}")
                log("ℹ️  Una cattura parziale potrebbe comunque essere in «_materiale/».")

        self._run_inprocess(task)

    def _run_capture_deleghe(self):
        """Strumento investigativo: cattura HAR a navigazione libera sul portale
        Deleghe (login precompilato, poi l'utente naviga fino a «Esporta elenco»)."""
        cf, pin, pwd, cfst = self._get_creds()
        if not self._validate(**{"Nome utente/CF": cf, "PIN": pin, "Password": pwd}):
            return

        capture_dir = os.path.join(SCRIPT_DIR, "_materiale")

        def task(log):
            from ade_auth import cattura_har_navigazione, AuthError
            import fec_deleghe
            log(f"\n{'─' * 60}\n🎥  Cattura HAR Deleghe (navigazione libera)\n{'─' * 60}")
            try:
                cattura_har_navigazione(
                    cf, pin, pwd, capture_dir=capture_dir, prefisso="capture_deleghe",
                    hint=f"Vai su {fec_deleghe.URL_RICERCA_DELEGANTI} e clicca "
                         "«Esporta elenco».",
                    log=log)
            except AuthError as exc:
                log(f"\n❌ Cattura fallita allo step «{exc.step}»: {exc.dettaglio}")
                log("ℹ️  Una cattura parziale potrebbe comunque essere in «_materiale/».")
            except Exception as exc:
                log(f"\n❌ Cattura fallita: {exc}")
                log("ℹ️  Una cattura parziale potrebbe comunque essere in «_materiale/».")

        self._run_inprocess(task)

    def _run_test_login(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl    = self.tl_cfcl.get().strip()
        piva    = self.tl_piva.get().strip()
        profilo = _profilo_da_modalita(self.modalita.get())
        backend = self.backend_var.get()
        headless = bool(self.headless_var.get())

        if not self._validate(**{"Nome utente/CF": cf, "PIN": pin, "Password": pwd}):
            return

        def task(log):
            from ade_auth import autentica, Creds, AuthError
            log(f"\n{'─' * 60}\n▶  Test Login (backend: {backend})\n{'─' * 60}")
            creds = Creds(nomeutente=cf, pin=pin, password=pwd, cfstudio=cfst,
                          cf_cliente=cfcl, piva=piva, profilo=profilo)
            try:
                # Multi-P.IVA: se non indichi una P.IVA e il login è headless, compare
                # il popup di scelta (col browser visibile la scegli nella tendina).
                res = autentica(creds, backend=backend, headless=headless, log=log,
                                scegli_piva=self._chiedi_piva_thread)
            except AuthError as exc:
                log(f"\n❌ Login fallito allo step «{exc.step}»: {exc.dettaglio}")
                return
            msg_piva = f", P.IVA attivata {res.piva}" if res.piva else ""
            log(f"\n✅ Login OK - backend {res.backend}{msg_piva}, token ottenuti "
                f"(x-b2bcookie/{len(res.xb2bcookie)} char, x-token/{len(res.xtoken)} char).")
            # Conferma collegamento: GET autenticata innocua (endpoint verificato 200).
            from ade_auth import IVASERVIZI
            try:
                r = res.session.get(
                    f"{IVASERVIZI}/ser/api/fatture/v1/ul/me/adesione/stato",
                    headers=res.headers, verify=False, timeout=30)
                esito = "confermato" if r.status_code == 200 else f"risposta HTTP {r.status_code}"
                log(f"✅ Collegamento al servizio {esito} (HTTP {r.status_code}).")
            except Exception as exc:
                log(f"⚠️  Token ottenuti ma GET di verifica fallita: {exc}")
            for n in res.note:
                log(f"   ℹ️  {n}")

        self._run_inprocess(task)

    # ── Scelta P.IVA (popup) - condivisa da Test Login, Download Standard e wizard ──

    def _chiedi_piva_thread(self, disponibili: list) -> str:
        """
        Callback `scegli_piva` per ade_auth: viene invocata DAL worker thread durante il
        login, ma Tk non è thread-safe → il dialog di scelta va costruito sul thread
        principale. Si pianifica il dialog con `after(0, …)` e si attende la risposta con
        un Event. Ritorna la P.IVA scelta (o '' se annullato → ade_auth userà la prima).
        """
        import threading
        evt = threading.Event()
        box = {"piva": ""}

        def _ask():
            try:
                box["piva"] = self._dialog_scelta_piva(disponibili)
            finally:
                evt.set()

        self.root.after(0, _ask)
        evt.wait()
        return box["piva"]

    def _dialog_scelta_piva(self, disponibili: list) -> str:
        """Dialog modale di scelta P.IVA (una radio per P.IVA del CF). Solo thread Tk."""
        win = tk.Toplevel(self.root)
        win.title("Scelta partita IVA")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=(20, 16))
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Il codice fiscale ha più partite IVA associate: "
                             "scegli quella da usare.",
                  wraplength=440, justify="left").pack(anchor="w", pady=(0, 10))

        prima = str((disponibili[0] or {}).get("piva", "")).strip() if disponibili else ""
        scelta = tk.StringVar(value=prima)
        for p in disponibili:
            piva = str((p or {}).get("piva", "")).strip()
            denom = str((p or {}).get("denominazione", "")).strip()
            ttk.Radiobutton(frm, variable=scelta, value=piva,
                            text=f"{piva}   {denom}").pack(anchor="w")

        out = {"piva": prima}

        def conferma():
            out["piva"] = scelta.get()
            win.destroy()

        ttk.Button(frm, text="Conferma", command=conferma, width=14).pack(anchor="e", pady=(12, 0))
        win.bind("<Return>", lambda _e: conferma())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 120
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.wait_window()
        return out["piva"]

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 1 - Download Standard
    # ─────────────────────────────────────────────────────────────────────────

    # ── Scheda «Deleghe» - anagrafica locale ───────────────────────────

    # Etichette delle colonne mostrate nel Treeview (ordine = fec_deleghe.FIELDS).
    _DELEGHE_COLS = (
        ("denominazione", "Denominazione", 200),
        ("codice_fiscale", "Codice fiscale", 130),
        ("partita_iva", "Partita IVA", 110),
        ("data_fine_delega", "Fine delega", 90),
        ("conservazione", "Conserv.", 70),
        ("codice_destinatario", "Cod. dest.", 80),
    )

    def _tab_deleghe(self, nb: ttk.Notebook):
        import fec_deleghe
        self._deleghe = fec_deleghe
        self.deleghe_rows = fec_deleghe.load_deleghe()

        tab = ttk.Frame(nb)
        nb.add(tab, text="  Deleghe  ")
        f = self._lf(tab)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)

        # ── Tabella ──
        tree_box = ttk.Frame(f)
        tree_box.grid(row=0, column=0, sticky="nsew")
        tree_box.columnconfigure(0, weight=1)
        tree_box.rowconfigure(0, weight=1)

        cols = [c[0] for c in self._DELEGHE_COLS]
        self.deleghe_tree = ttk.Treeview(tree_box, columns=cols, show="headings", height=12)
        for key, label, width in self._DELEGHE_COLS:
            self.deleghe_tree.heading(key, text=label,
                                      command=lambda k=key: self._deleghe_sort(k))
            anchor = "center" if key in ("data_fine_delega", "conservazione") else "w"
            self.deleghe_tree.column(key, width=width, anchor=anchor)
        self.deleghe_tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(tree_box, orient="vertical", command=self.deleghe_tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.deleghe_tree.configure(yscrollcommand=vsb.set)
        self.deleghe_tree.bind("<<TreeviewSelect>>", self._deleghe_on_select)

        # ── Form ──
        form = ttk.LabelFrame(f, text=" Riga ", padding=(12, 8))
        form.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.dlg_denom = tk.StringVar()
        self.dlg_cf    = tk.StringVar()
        self.dlg_piva  = tk.StringVar()
        self.dlg_fine  = tk.StringVar()
        self.dlg_dest  = tk.StringVar()
        self.dlg_cons  = tk.BooleanVar(value=False)
        r = 0
        self._row(form, r, "Denominazione:", self.dlg_denom, width=34)
        r += 1; self._row(form, r, "Codice fiscale:", self.dlg_cf)
        r += 1; self._row(form, r, "Partita IVA:", self.dlg_piva)
        r += 1; self._row(form, r, "Data fine delega:", self.dlg_fine)
        r += 1; self._row(form, r, "Codice destinatario:", self.dlg_dest)
        r += 1
        ttk.Label(form, text="Conservazione:").grid(row=r, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Checkbutton(form, variable=self.dlg_cons).grid(row=r, column=1, sticky="w")

        # ── Bottoni ──
        bar = ttk.Frame(f)
        bar.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(bar, text="Aggiungi / Salva", command=self._deleghe_save).pack(side=tk.LEFT)
        ttk.Button(bar, text="Pulisci form", command=self._deleghe_clear_form).pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="Elimina", command=self._deleghe_delete).pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="↻ Aggiorna da AdE",
                   command=self._deleghe_aggiorna_da_ade).pack(side=tk.LEFT, padx=(18, 6))
        ttk.Button(bar, text="↻↻ Aggiorna tutte",
                   command=self._deleghe_aggiorna_tutte).pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="▶ Usa per download", command=self._deleghe_use).pack(side=tk.LEFT, padx=6)

        bar2 = ttk.Frame(f)
        bar2.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(bar2, text="Importa da CSV AdE…", command=self._deleghe_import_ade).pack(side=tk.LEFT)
        ttk.Button(bar2, text="Importa CSV app…", command=self._deleghe_import_app).pack(side=tk.LEFT, padx=6)
        ttk.Button(bar2, text="Esporta CSV app…", command=self._deleghe_export_app).pack(side=tk.LEFT, padx=6)

        ttk.Checkbutton(
            f, text="Non aggiornare l'anagrafica dai dati AdE durante il download",
            variable=self.deleghe_no_update_var, command=self._persist_deleghe_flag,
        ).grid(row=4, column=0, sticky="w", pady=(10, 0))

        self._note(f, 5, "«Aggiorna da AdE» fa login sul CF selezionato (o del form) e ricava da "
                         "AdE denominazione, P.IVA, conservazione e codice destinatario, "
                         "proponendo i campi variati; «Aggiorna tutte» lo fa su tutte le deleghe con "
                         "un solo accesso. Lo stesso avviene in automatico al download, salvo la "
                         "spunta qui sopra. «Importa da CSV AdE…» (l'esportazione «Elenco "
                         "deleganti» del portale) riempie solo CF e data fine delega, senza "
                         "toccare gli altri campi: la conservazione si legge solo dal portale coi "
                         "tasti «Aggiorna…». «Importa/Esporta CSV app…» invece è un formato con "
                         "tutti i campi, comodo per un backup completo o per trasferire l'elenco "
                         "su un'altra installazione. «Usa per download» precompila la scheda "
                         "Download Standard col CF/P.IVA selezionati.")
        self._deleghe_refresh()
        self._add_help_button(tab, corner="se")

    def _no_update_check(self, frame, row: int) -> int:
        """Checkbox condivisa «non aggiornare l'anagrafica da AdE» (stessa variabile in
        tutte le schede: modificarla in una si riflette ovunque). Ritorna la riga dopo."""
        ttk.Checkbutton(
            frame, text="Non aggiornare l'anagrafica deleghe dai dati AdE",
            variable=self.deleghe_no_update_var, command=self._persist_deleghe_flag,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        return row + 1

    def _persist_deleghe_flag(self):
        """Salva la spunta «non aggiornare» nelle preferenze (merge, senza credenziali)."""
        try:
            import fec_store
            cfg = fec_store.load_settings()
            cfg["deleghe_no_update"] = bool(self.deleghe_no_update_var.get())
            fec_store.save_settings(cfg)
        except Exception:
            pass

    def _deleghe_aggiorna_da_ade(self):
        """Login sul CF selezionato (o del form) e aggiorna l'anagrafica dai dati AdE."""
        cf, pin, pwd, cfst = self._get_creds()
        i = self._deleghe_selected_index()
        cfcl = (self.deleghe_rows[i].get("codice_fiscale", "") if i is not None
                else self.dlg_cf.get().strip())
        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF della delega": cfcl}):
            return
        profilo = _profilo_da_modalita(self.modalita.get())

        def task(log):
            from ade_auth import autentica, Creds, AuthError
            import fec_anagrafica
            log(f"\n{'─' * 60}\n↻  Aggiorna anagrafica da AdE - CF {cfcl}\n{'─' * 60}")
            creds = Creds(nomeutente=cf, pin=pin, password=pwd, cfstudio=cfst,
                          cf_cliente=cfcl, piva="", profilo=profilo)
            try:
                res = autentica(creds, backend="requests", log=log,
                                scegli_piva=self._chiedi_piva_thread)
            except AuthError as exc:
                log(f"\n❌ Login fallito allo step «{exc.step}»: {exc.dettaglio}")
                return
            dati = fec_anagrafica.recupera(res, log=log)
            self._applica_aggiornamento_delega(cfcl, dati, log)
            log("\n[Completato]")

        self._run_inprocess(task)

    def _deleghe_reload(self):
        """Ricarica l'anagrafica da disco e aggiorna la tabella (thread Tk)."""
        self.deleghe_rows = self._deleghe.load_deleghe()
        self._deleghe_refresh()

    def _deleghe_aggiorna_tutte(self):
        """
        Aggiorna l'anagrafica di TUTTE le deleghe con un solo accesso: login una volta,
        poi cambia utenza di lavoro per ogni CF (ade_auth.seleziona_utenza) e applica in
        automatico i campi variati (senza popup per singolo cliente).
        """
        cf, pin, pwd, cfst = self._get_creds()
        if not self.deleghe_rows:
            messagebox.showinfo("Deleghe", "Nessuna delega in anagrafica.")
            return
        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst}):
            return
        n = len(self.deleghe_rows)
        if not messagebox.askyesno(
                "Aggiorna tutte",
                f"Aggiornare l'anagrafica di tutte le {n} deleghe da AdE?\n\n"
                "I campi variati vengono applicati automaticamente (nessun popup per "
                "singolo cliente). L'operazione richiede un solo accesso ma può durare "
                "qualche minuto; puoi interromperla con «Interrompi»."):
            return
        profilo = _profilo_da_modalita(self.modalita.get())
        righe = list(self.deleghe_rows)  # snapshot (stessi oggetti riga)

        import fec_download
        self.control = fec_download.Controllo()
        self._reset_pausa_btn()
        control = self.control

        def task(log):
            from ade_auth import autentica, seleziona_utenza, Creds, AuthError
            import fec_anagrafica
            import fec_download
            log(f"\n{'─' * 60}\n↻↻  Aggiorna TUTTE le anagrafiche ({len(righe)} deleghe)\n{'─' * 60}")
            quiet = lambda _m: None  # noqa: E731 - silenzia il log interno del login
            auth = None
            aggiornate = 0
            falliti = []
            interrotto = False
            for i, row in enumerate(righe, 1):
                try:
                    control.check()   # pausa/annullamento cooperativo tra un cliente e l'altro
                except fec_download.DownloadAnnullato:
                    interrotto = True
                    log("\n⏹  Interrotto: salvo le deleghe già aggiornate.")
                    break
                cfcl = str(row.get("codice_fiscale", "")).strip()
                if not cfcl:
                    continue
                # P.IVA salvata (se presente) → evita la scelta su CF multi-P.IVA.
                creds = Creds(nomeutente=cf, pin=pin, password=pwd, cfstudio=cfst,
                              cf_cliente=cfcl, piva=str(row.get("partita_iva", "")).strip(),
                              profilo=profilo)
                log(f"\n[{i}/{len(righe)}] CF {cfcl}…")
                try:
                    if auth is None:
                        auth = autentica(creds, backend="requests", log=quiet)
                    else:
                        auth = seleziona_utenza(auth, creds, log=quiet)
                except AuthError as exc:
                    log(f"   ❌ accesso/utenza: {exc.dettaglio}")
                    falliti.append(cfcl)
                    continue
                try:
                    dati = fec_anagrafica.recupera(auth)
                except Exception as exc:  # noqa: BLE001
                    log(f"   ⚠️  recupero dati fallito: {exc}")
                    falliti.append(cfcl)
                    continue
                diffs = fec_anagrafica.differenze(row, dati)
                if not diffs:
                    log("   = già allineata")
                    continue
                for k in diffs:
                    row[k] = dati[k]
                self.deleghe_rows[self.deleghe_rows.index(row)] = self._deleghe._norm_row(row)
                aggiornate += 1
                log("   ✓ aggiornati: "
                    + ", ".join(str(fec_anagrafica.ETICHETTE.get(k, k)) for k in diffs))

            # Salva sempre ciò che è stato aggiornato, anche se interrotto a metà.
            if aggiornate:
                self._deleghe.save_deleghe(self.deleghe_rows)
                self.root.after(0, self._deleghe_reload)
            stato = "Interrotto" if interrotto else "Completato"
            log(f"\n[{stato}] {aggiornate} aggiornate, {len(falliti)} non riuscite"
                + (f" ({', '.join(falliti)})" if falliti else "."))

        self._run_inprocess(task)

    def _applica_aggiornamento_delega(self, cf: str, dati: dict, log):
        """
        Confronta i dati AdE con l'anagrafica salvata per `cf` e, se ci sono differenze,
        mostra il popup di scelta e applica i campi selezionati. Invocato dal worker
        thread: il popup e la modifica della tabella sono marshallati sul thread Tk.
        """
        import fec_anagrafica
        cf_up = (cf or "").strip().upper()
        if not cf_up:
            return
        saved = next((r for r in self.deleghe_rows
                      if r.get("codice_fiscale", "").upper() == cf_up), {})
        diffs = fec_anagrafica.differenze(saved, dati)
        if not diffs:
            log("Anagrafica delega già allineata ai dati AdE (nessuna modifica).")
            return
        applicati = self._chiedi_aggiornamento_thread(cf_up, dati, diffs)
        if applicati:
            log(f"Anagrafica delega aggiornata: {', '.join(applicati)}.")
        else:
            log("Aggiornamento anagrafica non applicato.")

    def _chiedi_aggiornamento_thread(self, cf: str, dati: dict, diffs: dict) -> list:
        """Mostra sul thread Tk il popup di aggiornamento e attende l'esito (Event)."""
        import threading
        evt = threading.Event()
        box = {"applicati": []}

        def _ask():
            try:
                box["applicati"] = self._dialog_e_applica_aggiornamento(cf, dati, diffs)
            finally:
                evt.set()

        self.root.after(0, _ask)
        evt.wait()
        return box["applicati"]

    def _dialog_e_applica_aggiornamento(self, cf: str, dati: dict, diffs: dict) -> list:
        """Popup (thread Tk): checkbox per campo variato; salva i selezionati. Ritorna
        le etichette dei campi effettivamente aggiornati."""
        import fec_anagrafica
        win = tk.Toplevel(self.root)
        win.title("Aggiorna anagrafica delega")
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=(20, 16))
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text=f"I dati AdE differiscono dall'anagrafica per il CF {cf}. "
                            "Seleziona i campi da aggiornare:",
                  wraplength=470, justify="left").pack(anchor="w", pady=(0, 10))

        def _fmt(v):
            if isinstance(v, bool):
                return "Sì" if v else "No"
            return str(v) if str(v).strip() else "(vuoto)"

        vars_: dict = {}
        for k, (old, new) in diffs.items():
            var = tk.BooleanVar(value=True)
            vars_[k] = var
            lbl = fec_anagrafica.ETICHETTE.get(k, k)
            ttk.Checkbutton(frm, variable=var,
                            text=f"{lbl}:   {_fmt(old)}  →  {_fmt(new)}").pack(anchor="w")

        applicati: list = []

        def salva():
            scelti = [k for k, v in vars_.items() if v.get()]
            if scelti:
                self._salva_campi_delega(cf, dati, scelti)
                applicati.extend(fec_anagrafica.ETICHETTE.get(k, k) for k in scelti)
            win.destroy()

        barra = ttk.Frame(frm)
        barra.pack(anchor="e", pady=(14, 0))
        ttk.Button(barra, text="Annulla", command=win.destroy).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(barra, text="Salva selezionati", command=salva).pack(side=tk.RIGHT)
        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 100
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.wait_window()
        return applicati

    def _salva_campi_delega(self, cf: str, dati: dict, campi: list):
        """Applica i `campi` scelti alla riga del CF (creandola se assente) e salva."""
        cf_up = cf.upper()
        row = next((r for r in self.deleghe_rows
                    if r.get("codice_fiscale", "").upper() == cf_up), None)
        if row is None:
            row = self._deleghe._norm_row({"codice_fiscale": cf_up})
            self.deleghe_rows.append(row)
        for k in campi:
            row[k] = dati.get(k)
        idx = self.deleghe_rows.index(row)
        self.deleghe_rows[idx] = self._deleghe._norm_row(row)
        self._deleghe.save_deleghe(self.deleghe_rows)
        self.deleghe_rows = self._deleghe.load_deleghe()
        self._deleghe_refresh()

    def _deleghe_sort(self, col: str):
        """
        Ordina la tabella deleghe per la colonna cliccata, alternando crescente/
        decrescente a ogni click sulla stessa intestazione. Ordina per data reale la
        colonna «fine delega» e per valore booleano «conservazione»; le altre per testo
        (case-insensitive). I vuoti vanno in fondo.
        """
        from datetime import datetime
        reverse = (getattr(self, "_deleghe_sort_col", None) == col
                   and not getattr(self, "_deleghe_sort_rev", False))
        self._deleghe_sort_col = col
        self._deleghe_sort_rev = reverse

        def chiave(row):
            v = row.get(col, "")
            if col == "conservazione":
                return (bool(v),)
            if col == "data_fine_delega":
                d = self._deleghe._parse_data(str(v or ""))
                return (d is None, d or datetime.min)
            s = str(v or "")
            return (s == "", s.lower())

        self.deleghe_rows.sort(key=chiave, reverse=reverse)
        for k, label, _w in self._DELEGHE_COLS:
            freccia = (" ▼" if reverse else " ▲") if k == col else ""
            self.deleghe_tree.heading(k, text=label + freccia)
        self._deleghe_refresh()

    def _deleghe_refresh(self):
        """Svuota e ripopola il Treeview da self.deleghe_rows."""
        self.deleghe_tree.delete(*self.deleghe_tree.get_children())
        for i, row in enumerate(self.deleghe_rows):
            vals = [row.get(k, "") for k in (c[0] for c in self._DELEGHE_COLS)]
            vals[4] = "Sì" if row.get("conservazione") else "No"  # colonna conservazione
            self.deleghe_tree.insert("", "end", iid=str(i), values=vals)

    def _deleghe_selected_index(self):
        sel = self.deleghe_tree.selection()
        return int(sel[0]) if sel else None

    def _deleghe_on_select(self, _=None):
        i = self._deleghe_selected_index()
        if i is None:
            return
        row = self.deleghe_rows[i]
        self.dlg_denom.set(row.get("denominazione", ""))
        self.dlg_cf.set(row.get("codice_fiscale", ""))
        self.dlg_piva.set(row.get("partita_iva", ""))
        self.dlg_fine.set(row.get("data_fine_delega", ""))
        self.dlg_dest.set(row.get("codice_destinatario", ""))
        self.dlg_cons.set(bool(row.get("conservazione")))

    def _deleghe_clear_form(self):
        for v in (self.dlg_denom, self.dlg_cf, self.dlg_piva, self.dlg_fine, self.dlg_dest):
            v.set("")
        self.dlg_cons.set(False)
        if self.deleghe_tree.selection():
            self.deleghe_tree.selection_remove(self.deleghe_tree.selection())

    def _deleghe_save(self):
        cf = self.dlg_cf.get().strip()
        if not cf:
            messagebox.showwarning("Deleghe", "Il codice fiscale è obbligatorio.")
            return
        nuova = {
            "denominazione": self.dlg_denom.get(),
            "codice_fiscale": cf,
            "partita_iva": self.dlg_piva.get(),
            "data_fine_delega": self.dlg_fine.get(),
            "conservazione": self.dlg_cons.get(),
            "codice_destinatario": self.dlg_dest.get(),
        }
        # Salvataggio manuale: sovrascrive sempre i campi col valore del form (anche vuoti)
        # se la riga esiste, così l'utente può correggere/cancellare un valore.
        cf_up = cf.upper()
        esistente = next((r for r in self.deleghe_rows
                          if r.get("codice_fiscale", "").upper() == cf_up), None)
        if esistente:
            esistente.update(self._deleghe._norm_row(nuova))
        else:
            self.deleghe_rows.append(self._deleghe._norm_row(nuova))
        self._deleghe.save_deleghe(self.deleghe_rows)
        self.deleghe_rows = self._deleghe.load_deleghe()
        self._deleghe_refresh()

    def _deleghe_delete(self):
        i = self._deleghe_selected_index()
        if i is None:
            messagebox.showinfo("Deleghe", "Seleziona una riga da eliminare.")
            return
        row = self.deleghe_rows[i]
        if not messagebox.askyesno("Deleghe", f"Eliminare la delega di "
                                   f"«{row.get('denominazione') or row.get('codice_fiscale')}»?"):
            return
        del self.deleghe_rows[i]
        self._deleghe.save_deleghe(self.deleghe_rows)
        self._deleghe_refresh()
        self._deleghe_clear_form()

    def _deleghe_use(self):
        i = self._deleghe_selected_index()
        if i is None:
            messagebox.showinfo("Deleghe", "Seleziona un cliente da usare per il download.")
            return
        row = self.deleghe_rows[i]
        self.std_cf_cl.set(row.get("codice_fiscale", ""))
        self.std_piva.set(row.get("partita_iva", ""))
        if hasattr(self, "_std_tab"):
            nb = self._std_tab.master  # il notebook a cui è stata aggiunta la scheda
            nb.select(self._std_tab)

    def _deleghe_conferma_import(self, nuove: list[dict]) -> bool:
        """
        Conferma preventiva prima di un import CSV deleghe: mostra quante righe
        verranno aggiunte e quante «aggiornate» (di queste ultime viene toccata
        SOLO la scadenza, vedi `fec_deleghe.upsert`), poi chiede conferma.
        Ritorna True se l'utente conferma (o se non c'è nulla da importare).
        """
        if not nuove:
            return True
        esistenti = {r.get("codice_fiscale", "").upper() for r in self.deleghe_rows}
        agg = sum(1 for n in nuove
                 if str(n.get("codice_fiscale", "")).strip().upper() not in esistenti)
        upd = len(nuove) - agg
        return messagebox.askyesno(
            "Conferma import",
            f"Verranno aggiunte {agg} nuove deleghe e aggiornata la sola scadenza "
            f"di {upd} deleghe già presenti.\nNessun altro campo verrà modificato.\n\n"
            "Procedere?")

    def _deleghe_import_ade(self):
        path = filedialog.askopenfilename(
            title="Seleziona il CSV «Elenco deleganti» esportato dall'AdE",
            initialdir=os.path.join(SCRIPT_DIR, "_materiale"),
            filetypes=[("CSV", "*.csv"), ("Tutti i file", "*.*")])
        if not path:
            return
        try:
            nuove = self._deleghe.import_csv_ade(path)
        except Exception as e:  # noqa: BLE001 - errore mostrato all'utente
            messagebox.showerror("Import AdE", f"Impossibile leggere il file:\n{e}")
            return
        if not self._deleghe_conferma_import(nuove):
            return
        self.deleghe_rows, agg, upd = self._deleghe.merge_many(self.deleghe_rows, nuove)
        self._deleghe.save_deleghe(self.deleghe_rows)
        self.deleghe_rows = self._deleghe.load_deleghe()
        self._deleghe_refresh()
        messagebox.showinfo("Import AdE", f"Deleghe Fatture & Corrispettivi importate.\n"
                                          f"Nuove: {agg}   Aggiornate: {upd}")

    def _deleghe_import_app(self):
        path = filedialog.askopenfilename(
            title="Importa CSV deleghe (formato app)",
            filetypes=[("CSV", "*.csv"), ("Tutti i file", "*.*")])
        if not path:
            return
        try:
            nuove = self._deleghe.import_csv_app(path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Import CSV", f"Impossibile leggere il file:\n{e}")
            return
        if not self._deleghe_conferma_import(nuove):
            return
        self.deleghe_rows, agg, upd = self._deleghe.merge_many(self.deleghe_rows, nuove)
        self._deleghe.save_deleghe(self.deleghe_rows)
        self.deleghe_rows = self._deleghe.load_deleghe()
        self._deleghe_refresh()
        messagebox.showinfo("Import CSV", f"Righe importate.\nNuove: {agg}   Aggiornate: {upd}")

    def _deleghe_export_app(self):
        path = filedialog.asksaveasfilename(
            title="Esporta CSV deleghe (formato app)",
            defaultextension=".csv", initialfile="deleghe.csv",
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            self._deleghe.export_csv_app(self.deleghe_rows, path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Export CSV", f"Impossibile salvare il file:\n{e}")
            return
        messagebox.showinfo("Export CSV", f"Esportate {len(self.deleghe_rows)} righe in:\n{path}")

    def _tab_standard(self, nb: ttk.Notebook):
        tab = ttk.Frame(nb)
        nb.add(tab, text="  Download Standard  ")
        self._std_tab = tab  # riferimento per «Usa per download» dalla scheda Deleghe
        f = self._lf(tab)

        self.std_tipo    = tk.StringVar(value="Fatture Emesse")
        self.std_cf_cl   = tk.StringVar()
        self.std_piva    = tk.StringVar()
        self.std_dal     = tk.StringVar()
        self.std_al      = tk.StringVar()
        self.std_tipdata = tk.StringVar(value="1")
        # self.modalita / self.std_destdir creati in __init__ (popolati da config)

        r = 0
        ttk.Label(f, text="Tipo documento:").grid(row=r, column=0, sticky="w", pady=4, padx=(0, 8))
        tipo_row = ttk.Frame(f)
        tipo_row.grid(row=r, column=1, columnspan=2, sticky="w")
        cb = ttk.Combobox(tipo_row, textvariable=self.std_tipo, state="readonly", width=34, values=[
            "Fatture Emesse",
            "Fatture Ricevute",
            "Transfrontaliere Emesse",
            "Transfrontaliere Ricevute",
            "Messe a Disposizione",
        ])
        cb.pack(side=tk.LEFT)
        cb.bind("<<ComboboxSelected>>", self._std_tipo_changed)

        self._chk_tipo_frame = ttk.Frame(tipo_row)
        self._chk_tipo_frame.pack(side=tk.LEFT, padx=(14, 0))
        self._chk_includi_trans = ttk.Checkbutton(
            self._chk_tipo_frame, text="Includi fatture transfrontaliere (stesso periodo)",
            variable=self.std_includi_trans)
        self._chk_includi_disposizione = ttk.Checkbutton(
            self._chk_tipo_frame, text="Includi fatture Messe a Disposizione (stesso periodo)",
            variable=self.std_includi_disposizione)

        r += 1; self._row(f, r, "CF Cliente:", self.std_cf_cl)
        r += 1; self._row(f, r, "P.IVA (opzionale):", self.std_piva)

        r += 1; r = self._build_date_range(f, r, self.std_dal, self.std_al, "%d%m%Y") - 1

        r += 1
        self.std_dest_info = tk.StringVar()
        ttk.Label(f, text="Salvataggio in:").grid(row=r, column=0, sticky="nw", pady=4, padx=(0, 8))
        ttk.Label(f, textvariable=self.std_dest_info, foreground="#555",
                  wraplength=560, justify="left").grid(row=r, column=1, sticky="w", pady=4)

        r += 1
        self._tipdata_lbl = ttk.Label(f, text="Cerca per:")
        self._tipdata_lbl.grid(row=r, column=0, sticky="w", pady=4, padx=(0, 8))
        self._tipdata_frame = ttk.Frame(f)
        self._tipdata_frame.grid(row=r, column=1, sticky="w")
        ttk.Radiobutton(self._tipdata_frame, text="Data Ricezione", variable=self.std_tipdata, value="1").pack(side=tk.LEFT)
        ttk.Radiobutton(self._tipdata_frame, text="Data Emissione", variable=self.std_tipdata, value="2").pack(side=tk.LEFT, padx=14)

        r += 1
        ttk.Checkbutton(f, text="Non scaricare fatture RIFIUTATE DA P.A.",
                        variable=self.std_escludi_scartate).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))

        r += 1
        ttk.Checkbutton(f, text="Estrai file p7m (fatture firmate digitalmente)",
                        variable=self.std_estrai_p7m).grid(
            row=r, column=0, columnspan=2, sticky="w")

        self._std_tipo_changed()

        r += 1; self._note(f, r, "Download in-process con un solo login (backend/headless dalla "
                                 "scheda Test Login). «Cerca per» vale solo per le Fatture "
                                 "Ricevute. Le checkbox «Includi...» (visibili solo col tipo "
                                 "documento pertinente) accodano, sullo stesso periodo, un secondo "
                                 "download di transfrontaliere o messe a disposizione nella "
                                 "rispettiva cartella (personalizzabile in ⚙ Impostazioni). "
                                 "«Non scaricare fatture rifiutate da P.A.» salta le fatture "
                                 "scartate senza salvarne il file; «Estrai file p7m» sostituisce la "
                                 "busta firmata con l'XML estratto (mai entrambi i formati "
                                 "insieme). I periodi superiori a 3 mesi vengono spezzati e "
                                 "scaricati automaticamente a blocchi.")

        r += 1; r = self._no_update_check(f, r)
        self._run_btn(f, r, "Avvia Download", self._run_standard)
        self._add_help_button(tab)

    def _std_pick_destdir(self):
        scelta = filedialog.askdirectory(
            title="Cartella di destinazione dei download",
            initialdir=self.std_destdir.get().strip() or DEFAULT_DEST_DIR)
        if scelta:
            self.std_destdir.set(scelta)

    def _std_tipo_changed(self, _=None):
        tipo = self.std_tipo.get()
        visible = tipo == "Fatture Ricevute"
        fg    = "black" if visible else "#aaaaaa"
        state = "normal" if visible else "disabled"
        self._tipdata_lbl.configure(foreground=fg)
        for w in self._tipdata_frame.winfo_children():
            w.configure(state=state)  # type: ignore[call-arg]  # i figli (radio/combo) supportano -state

        if tipo == "Fatture Emesse":
            self._chk_includi_trans.pack(anchor="w")
        else:
            self._chk_includi_trans.pack_forget()

        if tipo == "Fatture Ricevute":
            self._chk_includi_disposizione.pack(anchor="w")
        else:
            self._chk_includi_disposizione.pack_forget()

        self._update_dest_info()

    def _update_dest_info(self):
        """Aggiorna l'etichetta «Salvataggio in:» con la cartella risolta dalle
        Impostazioni per il tipo documento selezionato (sola lettura)."""
        if not hasattr(self, "std_dest_info"):
            return
        key = TIPO_STD_KEY.get(self.std_tipo.get(), "emesse")
        base, sotto = self._dest_classe(key)
        suffisso = ("in una sottocartella per tipo e codice fiscale"
                    if sotto else "direttamente nella cartella (senza sottocartella)")
        self.std_dest_info.set(f"{base}\n→ i file saranno salvati {suffisso}.  "
                               "Modificabile in ⚙ Impostazioni.")

    def _run_standard(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl = self.std_cf_cl.get().strip()
        piva = self.std_piva.get().strip()
        dal  = self.std_dal.get().strip()
        al   = self.std_al.get().strip()
        tipo = self.std_tipo.get()
        tipdata = int(self.std_tipdata.get())

        # P.IVA NON obbligatoria: la consultazione usa solo il CF; se il CF ha più P.IVA
        # e il campo è vuoto, in fase di login compare il popup di scelta. Se indicata,
        # si usa quella.
        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF Cliente": cfcl},
                              **{"Data inizio": dal}, **{"Data fine": al}):
            return

        # Cartella e «sottocartella» risolte per la classe di documento (Impostazioni).
        d_em,  s_em  = self._dest_classe("emesse")
        d_ri,  s_ri  = self._dest_classe("ricevute")
        d_te,  s_te  = self._dest_classe("trans_emesse")
        d_tr,  s_tr  = self._dest_classe("trans_ricevute")
        d_md,  s_md  = self._dest_classe("messe_disposizione")

        # Tutte le tipologie girano in-process (un solo login), via fec_queue che
        # spezza i periodi > 3 mesi e unisce i risultati.
        escludi_scartate = bool(self.std_escludi_scartate.get())
        estrai_p7m = bool(self.std_estrai_p7m.get())
        includi_trans = bool(self.std_includi_trans.get())
        includi_disposizione = bool(self.std_includi_disposizione.get())

        def _op_emesse(res, log, fq, ctrl):
            fq.esegui_richiesta(res, "emesse", dal=dal, al=al, cf_cliente=cfcl,
                                dest_dir=d_em, sottocartella=s_em, control=ctrl, log=log,
                                escludi_scartate_pa=escludi_scartate, estrai_p7m=estrai_p7m)
            if includi_trans:
                log("\n↪  Aggiungo in coda: Transfrontaliere Emesse (stesso periodo)...")
                fq.esegui_richiesta(res, "trans_emesse", dal=dal, al=al, cf_cliente=cfcl,
                                    dest_dir=d_te, sottocartella=s_te, control=ctrl, log=log,
                                    escludi_scartate_pa=escludi_scartate, estrai_p7m=estrai_p7m)

        def _op_ricevute(res, log, fq, ctrl):
            fq.esegui_richiesta(res, "ricevute", dal=dal, al=al, cf_cliente=cfcl,
                                tipo_data=tipdata, dest_dir=d_ri, sottocartella=s_ri,
                                control=ctrl, log=log,
                                escludi_scartate_pa=escludi_scartate, estrai_p7m=estrai_p7m)
            if includi_disposizione:
                log("\n↪  Aggiungo in coda: Messe a Disposizione (stesso periodo)...")
                fq.esegui_richiesta(res, "messe_disposizione", dal=dal, al=al, cf_cliente=cfcl,
                                    dest_dir=d_md, sottocartella=s_md, control=ctrl, log=log,
                                    escludi_scartate_pa=escludi_scartate, estrai_p7m=estrai_p7m)

        OPS = {
            "Fatture Emesse": _op_emesse,
            "Fatture Ricevute": _op_ricevute,
            "Transfrontaliere Emesse": lambda res, log, fq, ctrl:
                fq.esegui_richiesta(res, "trans_emesse", dal=dal, al=al, cf_cliente=cfcl,
                                    dest_dir=d_te, sottocartella=s_te, control=ctrl, log=log,
                                    escludi_scartate_pa=escludi_scartate, estrai_p7m=estrai_p7m),
            "Transfrontaliere Ricevute": lambda res, log, fq, ctrl:
                fq.esegui_richiesta(res, "trans_ricevute", dal=dal, al=al, cf_cliente=cfcl,
                                    dest_dir=d_tr, sottocartella=s_tr, control=ctrl, log=log,
                                    escludi_scartate_pa=escludi_scartate, estrai_p7m=estrai_p7m),
            "Messe a Disposizione": lambda res, log, fq, ctrl:
                fq.esegui_richiesta(res, "messe_disposizione", dal=dal, al=al, cf_cliente=cfcl,
                                    dest_dir=d_md, sottocartella=s_md, control=ctrl, log=log,
                                    escludi_scartate_pa=escludi_scartate, estrai_p7m=estrai_p7m),
        }
        self._esegui_in_process(cfcl, piva, _profilo_da_modalita(self.modalita.get()), tipo, OPS[tipo])

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 2 - Richieste Massive
    # ─────────────────────────────────────────────────────────────────────────

    def _tab_richiesta_massiva(self, nb: ttk.Notebook):
        """
        Tab unica GUI per «Fatture Massive» + «Corrispettivi»: entrambe caricano un
        XML sulla stessa pagina del portale (/cons/mass-services/) per una richiesta
        di download massivo, differiscono solo nel tipo di richiesta selezionato.
        Nel core restano funzioni separate (fec_download/fec_queue) per
        retrocompatibilità; qui si accorpano solo UI e handler.
        """
        tab = ttk.Frame(nb)
        nb.add(tab, text="  Richieste Massive  ")
        f = self._lf(tab)

        self.mass_tipo    = tk.StringVar(value="Ft. Emesse")
        self.mass_cfcl    = tk.StringVar()
        self.mass_piva    = tk.StringVar()
        self.mass_dal     = tk.StringVar()
        self.mass_al      = tk.StringVar()

        r = 0
        self._combo(f, r, "Tipo richiesta:", self.mass_tipo, [
            "Ft. Emesse",
            "Ft. Ricevute per Data Emissione",
            "Ft. Ricevute per Data Ricezione",
            "Ft. Messe a Disposizione",
            "Corrispettivi",
        ])
        r += 1; self._row(f, r, "CF Cliente:", self.mass_cfcl)
        r += 1; self._row(f, r, "P.IVA Cliente (opzionale):", self.mass_piva)
        r += 1; r = self._build_date_range(f, r, self.mass_dal, self.mass_al, "%Y-%m-%d") - 1
        r += 1; self._note(f, r, "Genera e carica un file XML su /cons/mass-services/ dell'AdE "
                                 "(date nel formato AAAA-MM-GG). Comprende anche il tipo «Messe a "
                                 "Disposizione», oltre a emesse/ricevute e corrispettivi. I periodi "
                                 "superiori a 3 mesi vengono spezzati e inviati automaticamente in "
                                 "più richieste.")
        r += 1; r = self._no_update_check(f, r)
        self._run_btn(f, r, "Avvia Richiesta Massiva", self._run_richiesta_massiva, width=30)
        r += 1
        self._run_btn(f, r, "Controlla risultati disponibili", self._run_controlla_risultati_massivi,
                     width=30)
        r += 1; self._note(f, r, "Elenca i risultati disponibili sul portale per le richieste "
                                 "inviate in precedenza (anche da un'altra sessione o installazione, "
                                 "o fatte direttamente sul portale), per scegliere quali scaricare. "
                                 "Il tipo esatto (Emesse/Ricevute/Corrispettivi) è riconosciuto solo "
                                 "per le richieste inviate da questa installazione. Dopo lo scarico "
                                 "si può estrarre lo zip subito o più tardi, ed eliminare la "
                                 "richiesta dall'elenco: resta comunque recuperabile per un periodo "
                                 "di sicurezza prima di sparire per davvero.")
        r += 1
        self._run_btn(f, r, "Visualizza tutte le richieste effettuate", self._run_tutte_richieste_salvate,
                     width=40)
        r += 1; self._note(f, r, "Come sopra, ma per TUTTI i clienti già presenti in archivio: un "
                                 "solo accesso, poi cambio utenza per ciascun cliente in sequenza. "
                                 "Non serve compilare CF/P.IVA qui sopra.")

        self._add_help_button(tab)

    # Tipo richiesta -> (classe cartella DOC_CLASSI, chiave fec_queue.esegui_richiesta)
    _RICHIESTA_MASSIVA_OPS = {
        "Ft. Emesse":                       ("massive",       "massive_emesse"),
        "Ft. Ricevute per Data Emissione":  ("massive",       "massive_ricevute_emissione"),
        "Ft. Ricevute per Data Ricezione":  ("massive",       "massive_ricevute_ricezione"),
        "Ft. Messe a Disposizione":         ("massive",       "massive_disposizione"),
        "Corrispettivi":                   ("corrispettivi", "corrispettivi"),
    }

    def _run_richiesta_massiva(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl = self.mass_cfcl.get().strip()
        piva = self.mass_piva.get().strip()
        dal  = self.mass_dal.get().strip()
        al   = self.mass_al.get().strip()
        tipo = self.mass_tipo.get()

        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF Cliente": cfcl},
                              **{"Data inizio": dal}, **{"Data fine": al}):
            return

        classe, chiave_richiesta = self._RICHIESTA_MASSIVA_OPS[tipo]
        destdir, sotto = self._dest_classe(classe)

        def op(res, log, fq, ctrl):
            # P.IVA non obbligatoria: se vuota, si deduce dall'utenza di lavoro
            # attiva (res.piva, già risolta al login) o, in subordine, dalla
            # P.IVA salvata in anagrafica deleghe per lo stesso CF cliente.
            piva_eff = piva
            if not piva_eff:
                piva_eff = (getattr(res, "piva", "") or "").strip()
                if piva_eff:
                    log(f"P.IVA non indicata: uso quella dell'utenza attiva ({piva_eff}).")
            if not piva_eff and cfcl:
                import fec_deleghe
                for row in fec_deleghe.load_deleghe():
                    if str(row.get("codice_fiscale", "")).strip().upper() == cfcl.upper():
                        piva_eff = str(row.get("partita_iva", "")).strip()
                        if piva_eff:
                            log(f"P.IVA non indicata: uso quella salvata in anagrafica deleghe ({piva_eff}).")
                        break
            if not piva_eff:
                raise fq.DownloadError(
                    "P.IVA non indicata e non deducibile (non presente nell'utenza attiva "
                    "né in anagrafica deleghe): indicala manualmente.")
            codici = fq.esegui_richiesta(res, chiave_richiesta, dal=dal, al=al, cf_cliente=cfcl,
                                         piva=piva_eff, dest_dir=destdir, sottocartella=sotto,
                                         control=ctrl, log=log)
            self._registra_richieste_massive(codici, chiave_richiesta, cfcl, piva_eff, dal, al, log)

        self._esegui_in_process(cfcl, piva, _profilo_da_modalita(self.modalita.get()),
            f"Richiesta Massiva {tipo}", op)

    @staticmethod
    def _registra_richieste_massive(codici, tipo_richiesta, cfcl, piva, dal, al, log):
        """Ricorda in fec_richieste_massive.json l'idRichiesta di ogni blocco inviato:
        serve a etichettare correttamente il tipo esatto quando in seguito si
        controllano i risultati disponibili sul portale (che distingue solo fatture/
        corrispettivi, non il sottotipo). Non blocca l'operazione se il parsing fallisce."""
        import fec_richieste_massive
        for codice in codici or []:
            try:
                id_richiesta = json.loads(codice).get("idRichiesta", "")
            except (ValueError, AttributeError):
                id_richiesta = ""
            if not id_richiesta:
                log(f"⚠️  Impossibile ricordare la richiesta (idRichiesta non trovato in: {codice!r}).")
                continue
            fec_richieste_massive.registra_invio(id_richiesta, tipo_richiesta, cfcl, piva, dal, al)

    # Tipo esatto locale -> etichetta leggibile per il popup dei risultati disponibili.
    _TIPO_LOCALE_LABEL = {
        "massive_emesse":                  "Fatture Emesse",
        "massive_ricevute_emissione":       "Fatture Ricevute (per emissione)",
        "massive_ricevute_ricezione":       "Fatture Ricevute (per ricezione)",
        "massive_disposizione":            "Fatture Messe a Disposizione",
        "corrispettivi":                   "Corrispettivi",
    }

    def _risolvi_denominazione(self, res, log, cf_cliente: str) -> str:
        """Denominazione del CF cliente: prima dall'anagrafica deleghe locale (nessuna
        rete), altrimenti dall'AdE (stesso modulo `fec_anagrafica.recupera` già usato
        dalla tab Deleghe per «aggiorna dati da AdE») - vale solo per l'utenza attiva
        di `res`, quindi va richiamata una volta per gruppo/CF, non per riga."""
        if not cf_cliente:
            return ""
        import fec_deleghe
        for row in fec_deleghe.load_deleghe():
            if row.get("codice_fiscale", "").strip().upper() == cf_cliente.upper():
                denom = str(row.get("denominazione", "")).strip()
                if denom:
                    return denom
        try:
            import fec_anagrafica
            dati = fec_anagrafica.recupera(res, log=log)
            return str(dati.get("denominazione", "")).strip()
        except Exception:  # noqa: BLE001 - la denominazione è solo informativa
            return ""

    def _costruisci_righe_risultati(self, res, log, cf_default: str = "", piva_default: str = ""):
        """Interroga `fec_download.elenco_risposte_massive` sull'utenza attiva di `res`
        e incrocia ogni voce con `fec_richieste_massive.json` (per `idRichiesta`) per
        etichettare il tipo esatto - il portale distingue solo fatture/corrispettivi
        (campo `tipoRichiesta`), non il sottotipo esatto. `cf_default`/`piva_default`
        (l'utenza attiva con cui si è interrogato il portale) coprono le voci senza
        corrispondenza locale, così restano comunque scaricabili.

        Ogni voce vista viene ricordata/aggiornata in `fec_richieste_massive.json` via
        `registra_scoperta`, anche quelle non inviate da questa applicazione, così che
        una volta scaricata (`segna_scaricata`) non ricompaia più (vedi il filtro sotto):
        senza questo, una richiesta fatta a mano sul portale ricomparirebbe ad ogni
        controllo come "tipo non riconosciuto", scaricata o no.

        Le richieste già `scaricata`/`eliminata` localmente vengono OMESSE dal risultato,
        per non riproporle una volta gestite.
        """
        import fec_download
        import fec_richieste_massive
        risposte = fec_download.elenco_risposte_massive(res, log=log)
        locali = {r["id_richiesta"]: r for r in fec_richieste_massive.load_richieste(includi_eliminate=True)}

        denom_cache: dict[str, str] = {}

        def _denom_per(cf: str) -> str:
            if not cf:
                return ""
            if cf not in denom_cache:
                denom_cache[cf] = self._risolvi_denominazione(res, log, cf)
            return denom_cache[cf]

        righe = []
        for voce in risposte:
            idr = str(voce.get("idRichiesta", "")).strip()
            ricordata = locali.get(idr)
            if ricordata and ricordata["stato"] in ("scaricata", "eliminata"):
                continue  # già gestita: non va ripresentata una volta scaricata o eliminata

            tipo_ade = str(voce.get("tipoRichiesta", "")).strip()  # "FATT" | "CORR"
            cf_cliente = (ricordata.get("cf_cliente", "") if ricordata else "") or cf_default
            piva = (ricordata.get("piva", "") if ricordata else "") or piva_default
            denominazione = (ricordata.get("denominazione", "") if ricordata else "") or _denom_per(cf_cliente)
            fec_richieste_massive.registra_scoperta(idr, cf_cliente, piva, denominazione)

            if ricordata and ricordata.get("tipo_richiesta"):
                etichetta = self._TIPO_LOCALE_LABEL.get(
                    ricordata["tipo_richiesta"],
                    str(voce.get("descrizioneTipoRichiesta", "") or tipo_ade))
            else:
                etichetta = "Fatture - tipo non riconosciuto" if tipo_ade == "FATT" else \
                    str(voce.get("descrizioneTipoRichiesta", "") or "Corrispettivi")
            righe.append({
                "id_richiesta": idr,
                "etichetta": etichetta,
                "tipo_ade": tipo_ade,
                "stato": str(voce.get("stato", "")),
                "pronta": str(voce.get("stato", "")) == "Elaborata",
                "data_inserimento": str(voce.get("dataInserimento", "")),
                "cf_cliente": cf_cliente,
                "piva": piva,
                "denominazione": denominazione,
                # Periodo noto solo per le richieste inviate da questa applicazione
                # (il portale AdE non lo restituisce mai): vuoto per quelle "scoperte".
                "dal": ricordata.get("dal", "") if ricordata else "",
                "al": ricordata.get("al", "") if ricordata else "",
            })
        return righe

    def _run_controlla_risultati_massivi(self):
        """Elenca i risultati disponibili sul portale per il CF/P.IVA indicati nella
        tab (utenza corrente)."""
        cf, pin, pwd, cfst = self._get_creds()
        cfcl = self.mass_cfcl.get().strip()
        piva = self.mass_piva.get().strip()

        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst}):
            return

        def op(res, log, fq, ctrl):
            righe = self._costruisci_righe_risultati(res, log, cf_default=cfcl, piva_default=piva)
            log(f"\n{len(righe)} risultati trovati sul portale.")
            self.root.after(0, self._mostra_popup_risultati_massivi, righe)

        self._esegui_in_process(cfcl, piva, _profilo_da_modalita(self.modalita.get()),
            "Controlla risultati Richieste Massive", op)

    def _run_tutte_richieste_salvate(self):
        """Elenca i risultati per TUTTE le richieste ricordate in
        `fec_richieste_massive.json`, di qualunque CF cliente: un solo accesso, poi
        cambio utenza (`ade_auth.seleziona_utenza`) per ciascun CF distinto, stesso
        schema di `_deleghe_aggiorna_tutte`. Utile per non dover riaprire la tab per
        ogni cliente e per vedere in un colpo solo cosa manca ancora da scaricare."""
        cf, pin, pwd, cfst = self._get_creds()
        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst}):
            return

        import fec_richieste_massive
        locali = fec_richieste_massive.load_richieste(includi_eliminate=False)
        gruppi = sorted({(r.get("cf_cliente", "").strip(), r.get("piva", "").strip())
                         for r in locali if r.get("cf_cliente", "").strip()})
        if not gruppi:
            messagebox.showinfo("Richieste Massive",
                                "Nessuna richiesta salvata (fec_richieste_massive.json) con "
                                "un CF Cliente registrato.")
            return

        profilo = _profilo_da_modalita(self.modalita.get())
        backend = self.backend_var.get()
        headless = bool(self.headless_var.get())

        def task(log):
            from ade_auth import autentica, seleziona_utenza, Creds, AuthError
            log(f"\n{'─' * 60}\n▶  Tutte le richieste salvate ({len(gruppi)} clienti)\n{'─' * 60}")
            auth = None
            righe_totali = []
            for cfcl, piva in gruppi:
                creds = Creds(nomeutente=cf, pin=pin, password=pwd, cfstudio=cfst,
                              cf_cliente=cfcl, piva=piva, profilo=profilo)
                try:
                    if auth is None:
                        auth = autentica(creds, backend=backend, headless=headless, log=log,
                                         scegli_piva=self._chiedi_piva_thread)
                    else:
                        auth = seleziona_utenza(auth, creds, log=log,
                                               scegli_piva=self._chiedi_piva_thread)
                except AuthError as exc:
                    log(f"❌ Accesso/utenza {cfcl}: {exc.dettaglio}")
                    continue
                try:
                    righe = self._costruisci_righe_risultati(auth, log, cf_default=cfcl,
                                                             piva_default=piva)
                except Exception as exc:  # noqa: BLE001 - un cliente non deve bloccare gli altri
                    log(f"⚠️  Elenco risultati non ottenuto per {cfcl}: {exc}")
                    continue
                righe_totali.extend(righe)
            log(f"\n{len(righe_totali)} risultati totali trovati.")
            self.root.after(0, self._mostra_popup_risultati_massivi, righe_totali)

        self._run_inprocess(task)

    def _mostra_popup_risultati_massivi(self, righe: list):
        """Popup (solo thread Tk, pianificato con `after` dal worker) con una checkbox
        per risultato: l'utente sceglie cosa scaricare. Le richieste non ancora
        «Elaborata» sono mostrate ma non selezionabili (nessun file da scaricare)."""
        win = tk.Toplevel(self.root)
        win.title("Risultati Richieste Massive disponibili")
        win.transient(self.root)
        win.grab_set()

        frm = ttk.Frame(win, padding=(18, 14))
        frm.pack(fill=tk.BOTH, expand=True)

        if not righe:
            ttk.Label(frm, text="Nessuna richiesta trovata sul portale.").pack(anchor="w")
            ttk.Button(frm, text="Chiudi", command=win.destroy).pack(anchor="e", pady=(12, 0))
            return

        ttk.Label(frm, text="Seleziona i risultati da scaricare:",
                  font=("", 10, "bold")).pack(anchor="w", pady=(0, 8))

        vars_sel = {}
        for r in righe:
            v = tk.BooleanVar(value=r["pronta"])
            vars_sel[r["id_richiesta"]] = v
            riga = ttk.Frame(frm)
            riga.pack(fill=tk.X, pady=2)
            cb = ttk.Checkbutton(riga, variable=v)
            cb.pack(side=tk.LEFT)
            if not r["pronta"]:
                cb.state(["disabled"])
            soggetto_parti = []
            if r.get("denominazione"):
                soggetto_parti.append(r["denominazione"])
            if r.get("cf_cliente"):
                soggetto_parti.append(f"CF {r['cf_cliente']}")
            soggetto_txt = "  ·  ".join(soggetto_parti)
            soggetto_txt = f"{soggetto_txt}  ·  " if soggetto_txt else ""
            testo = (f"{soggetto_txt}{r['etichetta']}  ·  {r['stato']}  ·  "
                    f"inviata {r['data_inserimento']}  ·  id {r['id_richiesta']}")
            ttk.Label(riga, text=testo, foreground=("black" if r["pronta"] else "#999")).pack(
                side=tk.LEFT, padx=(6, 0))

        bar = ttk.Frame(frm)
        bar.pack(fill=tk.X, pady=(14, 0))
        ttk.Button(bar, text="Chiudi", command=win.destroy).pack(side=tk.RIGHT)

        def _scarica():
            selezionate = [r for r in righe if r["pronta"] and vars_sel[r["id_richiesta"]].get()]
            if not selezionate:
                messagebox.showinfo("Risultati Richieste Massive", "Nessun risultato selezionato.")
                return
            win.destroy()
            self._scarica_risultati_selezionati(selezionate)

        ttk.Button(bar, text="Scarica selezionati", command=_scarica).pack(side=tk.RIGHT, padx=(0, 8))

        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 80
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _scarica_risultati_selezionati(self, selezionate: list):
        """Scarica in-process i risultati scelti nel popup, raggruppati per (CF
        cliente, P.IVA): un accesso per gruppo, cambio utenza per i successivi (stesso
        schema di `_run_tutte_richieste_salvate`, copre anche il caso a un solo
        cliente). Cartella per classe (fatture -> `risultati_massive`, corrispettivi ->
        `risultati_corrispettivi`); a fine di ognuna aggiorna lo stato locale e, se il
        file scaricato è ancora uno zip (impostazione «estrai automaticamente»
        disattivata), propone in un popup finale l'estrazione e l'eliminazione
        (soft-delete) della richiesta."""
        cf, pin, pwd, cfst = self._get_creds()
        profilo = _profilo_da_modalita(self.modalita.get())
        backend = self.backend_var.get()
        headless = bool(self.headless_var.get())
        estrai_zip = bool(self.estrai_zip_risultati_massivi.get())

        gruppi = {}
        for r in selezionate:
            gruppi.setdefault((r["cf_cliente"], r["piva"]), []).append(r)

        def task(log):
            from ade_auth import autentica, seleziona_utenza, Creds, AuthError
            import fec_download
            import fec_richieste_massive
            log(f"\n{'─' * 60}\n▶  Scarico risultati Richieste Massive selezionati\n{'─' * 60}")
            auth = None
            risultati = []
            for (cfcl, piva), righe_gruppo in gruppi.items():
                creds = Creds(nomeutente=cf, pin=pin, password=pwd, cfstudio=cfst,
                              cf_cliente=cfcl, piva=piva, profilo=profilo)
                try:
                    if auth is None:
                        auth = autentica(creds, backend=backend, headless=headless, log=log,
                                         scegli_piva=self._chiedi_piva_thread)
                    else:
                        auth = seleziona_utenza(auth, creds, log=log,
                                               scegli_piva=self._chiedi_piva_thread)
                except AuthError as exc:
                    log(f"❌ Accesso/utenza {cfcl}: {exc.dettaglio}")
                    continue
                for r in righe_gruppo:
                    classe = "risultati_massive" if r["tipo_ade"] == "FATT" else "risultati_corrispettivi"
                    destdir, sotto = self._dest_classe(classe)
                    log(f"\n[{r['etichetta']}] id {r['id_richiesta']}...")
                    try:
                        salvati = fec_download.scarica_risposta_massiva(
                            auth, r["id_richiesta"], cf_cliente=cfcl, tipo_label=r["etichetta"],
                            dal=r.get("dal", ""), al=r.get("al", ""),
                            dest_dir=destdir, sottocartella=sotto, estrai_zip=estrai_zip, log=log)
                    except fec_download.DownloadError as exc:
                        log(f"   ❌ {exc}")
                        continue
                    fec_richieste_massive.segna_scaricata(r["id_richiesta"])
                    log(f"   ✅ {len(salvati)} file salvati.")
                    risultati.append({"id_richiesta": r["id_richiesta"], "etichetta": r["etichetta"],
                                      "salvati": salvati})
            log("\n[Completato]")
            self.root.after(0, self._mostra_popup_dopo_download, risultati)

        self._run_inprocess(task)

    def _mostra_popup_dopo_download(self, risultati: list):
        """Dopo il download: per ogni richiesta scaricata propone, in un unico popup,
        se estrarre ora lo zip (solo se non già estratto, cioè se l'impostazione
        «estrai automaticamente» era disattivata) e/o «eliminare» la richiesta
        dall'elenco. L'eliminazione è un soft-delete (vedi
        `fec_richieste_massive.segna_eliminata`): resta nel file per
        `fec_richieste_massive.GIORNI_STANDBY_ELIMINAZIONE` giorni prima della
        rimozione definitiva, così l'utente ha ancora un promemoria/riprova entro
        quella finestra se cambia idea."""
        if not risultati:
            return
        import fec_richieste_massive

        win = tk.Toplevel(self.root)
        win.title("Download completato")
        win.transient(self.root)
        win.grab_set()

        frm = ttk.Frame(win, padding=(18, 14))
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text=f"{len(risultati)} richieste scaricate - azioni facoltative:",
                  font=("", 10, "bold"), wraplength=480).pack(anchor="w", pady=(0, 8))

        estrai_vars, elimina_vars = {}, {}
        for r in risultati:
            zip_paths = [p for p in r["salvati"] if p.lower().endswith(".zip")]
            riga = ttk.Frame(frm)
            riga.pack(fill=tk.X, pady=3)
            ttk.Label(riga, text=r["etichetta"], width=34).pack(side=tk.LEFT)

            v_estrai = tk.BooleanVar(value=False)
            estrai_vars[r["id_richiesta"]] = v_estrai
            cb_estrai = ttk.Checkbutton(riga, text="Estrai zip ora", variable=v_estrai)
            cb_estrai.pack(side=tk.LEFT, padx=(0, 12))
            if not zip_paths:
                cb_estrai.state(["disabled"])

            v_elimina = tk.BooleanVar(value=False)
            elimina_vars[r["id_richiesta"]] = v_elimina
            ttk.Checkbutton(riga, text="Elimina richiesta dall'elenco",
                            variable=v_elimina).pack(side=tk.LEFT)

        ttk.Label(frm, text="«Elimina» non cancella subito: la richiesta resta nascosta ma "
                            f"recuperabile per {fec_richieste_massive.GIORNI_STANDBY_ELIMINAZIONE} "
                            "giorni prima di essere rimossa definitivamente.",
                  foreground="#777", wraplength=480).pack(anchor="w", pady=(6, 0))

        bar = ttk.Frame(frm)
        bar.pack(fill=tk.X, pady=(14, 0))
        ttk.Button(bar, text="Chiudi", command=win.destroy).pack(side=tk.RIGHT)

        def _applica():
            import fec_download

            def task(log):
                for r in risultati:
                    idr = r["id_richiesta"]
                    if estrai_vars[idr].get():
                        for p in r["salvati"]:
                            if p.lower().endswith(".zip"):
                                fec_download.estrai_zip_risultato(p, log=log)
                    if elimina_vars[idr].get():
                        fec_richieste_massive.segna_eliminata(idr)
                        log(f"Richiesta {idr} eliminata (nascosta, in standby "
                            f"{fec_richieste_massive.GIORNI_STANDBY_ELIMINAZIONE} giorni).")

            self._run_inprocess(task)
            win.destroy()

        ttk.Button(bar, text="Applica", command=_applica).pack(side=tk.RIGHT, padx=(0, 8))

        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 80
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 3 - Bolli Virtuali
    # ─────────────────────────────────────────────────────────────────────────

    def _tab_bolli(self, nb: ttk.Notebook):
        tab = ttk.Frame(nb)
        nb.add(tab, text="  Bolli Virtuali  ")
        f = self._lf(tab)

        self.bolli_cfcl = tk.StringVar()
        self.bolli_piva = tk.StringVar()
        self.bolli_trim = tk.StringVar(value="1")
        self.bolli_anno = tk.StringVar()

        r = 0
        self._row(f, r, "CF Cliente:", self.bolli_cfcl)
        r += 1; self._row(f, r, "P.IVA (opzionale):", self.bolli_piva)
        r += 1; self._combo(f, r, "Trimestre:", self.bolli_trim,
                            ["1", "2", "3", "4", "Tutto l'anno"])
        r += 1
        ttk.Label(f, text="Anno (YYYY):").grid(row=r, column=0, sticky="w", pady=4, padx=(0, 8))
        vcmd_bolli = (f.register(lambda P: P == "" or (P.isdigit() and len(P) <= 4)), "%P")
        ttk.Spinbox(f, textvariable=self.bolli_anno, width=8, from_=2000, to=2100,
                    validate="key", validatecommand=vcmd_bolli).grid(
            row=r, column=1, sticky="w")
        r += 1; self._note(f, r, "Genera un riepilogo CSV (elenco A/B, importo calcolato, "
                                 "scadenza, stato pagamento e versamenti) per il trimestre scelto o "
                                 "per l'intero anno. Il modello F24 non è generabile da questa "
                                 "procedura del portale AdE: va completato direttamente lì.")
        r += 1; r = self._no_update_check(f, r)
        self._run_btn(f, r, "Genera Riepilogo Bolli", self._run_bolli, width=26)
        self._add_help_button(tab)

    def _run_bolli(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl = self.bolli_cfcl.get().strip()
        piva = self.bolli_piva.get().strip()
        trim_ui = self.bolli_trim.get().strip()
        trim = "" if trim_ui == "Tutto l'anno" else trim_ui
        anno = self.bolli_anno.get().strip()
        destdir, sotto = self._dest_classe("bolli")

        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF Cliente": cfcl},
                              Trimestre=trim_ui, Anno=anno):
            return

        op = lambda res, log, fq, ctrl: fq.esegui_richiesta(
            res, "bolli", cf_cliente=cfcl, piva=piva, trimestre=trim, anno=anno,
            dest_dir=destdir, sottocartella=sotto, control=ctrl, log=log)
        self._esegui_in_process(cfcl, piva, _profilo_da_modalita(self.modalita.get()),
            f"Bolli {trim_ui}/{anno}", op)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB Utility - elenchi Excel di riepilogo (dev-only)
    # ─────────────────────────────────────────────────────────────────────────

    # Etichetta del combo «Tipo elenco» -> chiave fec_utility.TIPI_ELENCO.
    # "Corrispettivi" è un caso speciale (non in TIPI_ELENCO): dispatch nel runner unico.
    _UTILITY_TIPI = {
        "Fatture Emesse":                    "emesse",
        "Fatture Ricevute (per ricezione)":  "ricevute_ricezione",
        "Fatture Ricevute (per emissione)":  "ricevute_emissione",
        "Transfrontaliere Emesse":           "trans_emesse",
        "Transfrontaliere Ricevute":         "trans_ricevute",
        "Corrispettivi":                     "corrispettivi",
    }

    def _tab_utility(self, nb: ttk.Notebook):
        tab = ttk.Frame(nb)
        nb.add(tab, text="  Utility  ")
        f = self._lf(tab)

        self.util_cfcl = tk.StringVar()
        self.util_piva = tk.StringVar()
        self.util_tipo = tk.StringVar(value="Fatture Emesse")
        self.util_dal = tk.StringVar()
        self.util_al = tk.StringVar()
        self.util_period = tk.StringVar()             # periodo scelto nella tendina
        self.util_granularita = tk.StringVar(value="unico")

        r = 0
        self._combo(f, r, "Tipo elenco:", self.util_tipo,
                    list(self._UTILITY_TIPI))
        r += 1; self._row(f, r, "CF Cliente:", self.util_cfcl)
        r += 1
        self._util_piva_lbl = ttk.Label(f, text="P.IVA (opzionale):")
        self._util_piva_lbl.grid(row=r, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Entry(f, textvariable=self.util_piva, width=22).grid(row=r, column=1, sticky="w")
        r += 1; r = self._build_date_range(f, r, self.util_dal, self.util_al,
                                           "%d%m%Y", period_var=self.util_period) - 1

        # «File Excel»: compare SOLO con «Anno intero» - un file unico, uno per
        # trimestre o uno per mese (nomi file distinti per sotto-periodo).
        r += 1
        self._util_gran_lbl = ttk.Label(f, text="File Excel:")
        self._util_gran_lbl.grid(row=r, column=0, sticky="w", pady=4, padx=(0, 8))
        gframe = ttk.Frame(f)
        gframe.grid(row=r, column=1, sticky="w")
        self._util_gran_frame = gframe
        ttk.Radiobutton(gframe, text="Unico", variable=self.util_granularita,
                        value="unico").pack(side=tk.LEFT)
        ttk.Radiobutton(gframe, text="Uno per trimestre", variable=self.util_granularita,
                        value="trimestre").pack(side=tk.LEFT, padx=14)
        ttk.Radiobutton(gframe, text="Uno per mese", variable=self.util_granularita,
                        value="mese").pack(side=tk.LEFT)

        def _toggle_gran(*_):
            if self.util_period.get() == "Anno intero":
                self._util_gran_lbl.grid()
                self._util_gran_frame.grid()
            else:
                self._util_gran_lbl.grid_remove()
                self._util_gran_frame.grid_remove()

        self.util_period.trace_add("write", _toggle_gran)
        _toggle_gran()

        def _toggle_piva_label(*_):
            corr = self.util_tipo.get() == "Corrispettivi"
            self._util_piva_lbl.configure(
                text="P.IVA (se vuota, quella attiva):" if corr else "P.IVA (opzionale):")

        self.util_tipo.trace_add("write", _toggle_piva_label)
        _toggle_piva_label()

        r += 1; self._note(f, r, "Genera un file Excel (.xlsx) di riepilogo con colonne per "
                                 "aliquota IVA/natura (richiede il pacchetto opzionale "
                                 "«openpyxl»). Fatture: una riga per fattura, con una chiamata di "
                                 "dettaglio per ciascuna (su periodi ampi può richiedere qualche "
                                 "minuto). Corrispettivi: un file per matricola dispositivo; se la "
                                 "P.IVA non è indicata usa quella dell'utenza di lavoro attiva. "
                                 "Con «Anno intero» si può scegliere se avere un file unico oppure "
                                 "uno per trimestre o per mese.")
        r += 1; r = self._no_update_check(f, r)
        self._run_btn(f, r, "Scarica Elenco Excel", self._run_utility, width=26)

        # Strumenti di debug (dump/HAR/log in «_materiale/», fuori da Git): solo DEV_MODE,
        # non servono all'uso normale dell'app e non vanno nella GUI pubblica.
        if DEV_MODE:
            r += 1
            ttk.Separator(f, orient="horizontal").grid(row=r, column=0, columnspan=2,
                                                       sticky="ew", pady=(10, 2))
            r += 1
            ttk.Label(f, text="Debug (file salvati in «_materiale/»):").grid(
                row=r, column=0, columnspan=2, sticky="w", pady=(2, 2))
            r += 1
            bar = ttk.Frame(f)
            bar.grid(row=r, column=0, columnspan=2, sticky="w")
            ttk.Button(bar, text="🔍 Dump JSON fatture", width=22,
                      command=self._run_utility_dump).pack(side=tk.LEFT)
            ttk.Button(bar, text="🎥 Cattura HAR fatture/corrisp.", width=28,
                      command=self._run_utility_har).pack(side=tk.LEFT, padx=8)
            ttk.Button(bar, text="💾 Salva log console", width=20,
                      command=self._salva_log_console).pack(side=tk.LEFT)
            r += 1; self._note(f, r, "Dump = lista JSON del periodo + dettaglio della 1ª fattura "
                                     "(per confermare i nomi campo). Cattura HAR = browser visibile "
                                     "con registrazione: naviga tu (login, Fatture, Corrispettivi...) "
                                     "e CHIUDI il browser per salvare. ⚠️ I file contengono "
                                     "credenziali/dati reali: non condividerli.")

        self._add_help_button(tab)

    def _run_utility(self):
        """Dispatch unico del pulsante «Scarica Elenco Excel» in base al «Tipo elenco»."""
        cf, pin, pwd, cfst = self._get_creds()
        cfcl = self.util_cfcl.get().strip()
        piva = self.util_piva.get().strip()
        dal = self.util_dal.get().strip()
        al = self.util_al.get().strip()
        tipo_ui = self.util_tipo.get()
        destdir, sotto = self._dest_classe("utility")
        corrispettivi = tipo_ui == "Corrispettivi"

        campi = dict(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                    **{"CF Cliente": cfcl},
                    **{"Data inizio": dal}, **{"Data fine": al})
        # P.IVA non obbligatoria in GUI: se vuota, i corrispettivi la ricavano da
        # sé (P.IVA dell'utenza di lavoro attiva, `res.piva`, come già fa
        # l'anagrafica deleghe con «aggiorna dati da AdE»).
        if not self._validate(**campi):
            return
        mancanti = fec_deps.find_missing().get("excel", [])
        if mancanti:
            messagebox.showerror(
                "Dipendenza mancante",
                "L'export Excel richiede il pacchetto «openpyxl», non installato.\n\n"
                f"Installa con:  {fec_deps.pip_install_hint(mancanti)}")
            return

        gran = self._util_gran()

        def op(res, log, fq, ctrl):
            import fec_utility
            piva_eff = piva
            if corrispettivi and not piva_eff:
                piva_eff = (getattr(res, "piva", "") or "").strip()
                if piva_eff:
                    log(f"P.IVA non indicata: uso quella dell'utenza attiva ({piva_eff}).")
            for sd, sa in self._util_sotto_periodi(dal, al, gran, log):
                try:
                    if corrispettivi:
                        fec_utility.elenco_corrispettivi_excel(
                            res, cfcl, piva_eff, sd, sa,
                            dest_dir=destdir, sottocartella=sotto, control=ctrl, log=log)
                    else:
                        tipo = self._UTILITY_TIPI.get(tipo_ui, "emesse")
                        fec_utility.elenco_fatture_excel(
                            res, cfcl, piva, tipo, sd, sa,
                            dest_dir=destdir, sottocartella=sotto, control=ctrl, log=log)
                except fec_utility.NessunDato as exc:
                    log(f"   (periodo saltato: {exc})")

        self._esegui_in_process(cfcl, piva, _profilo_da_modalita(self.modalita.get()),
            f"Elenco Excel {tipo_ui}", op)

    def _util_gran(self) -> str:
        """Granularità file Excel: vale solo se il periodo scelto è «Anno intero»
        (negli altri casi l'opzione è nascosta e si genera il file unico)."""
        if self.util_period.get() == "Anno intero":
            return self.util_granularita.get() or "unico"
        return "unico"

    @staticmethod
    def _util_sotto_periodi(dal: str, al: str, gran: str, log) -> list:
        """Sotto-periodi (fec_utility.spezza_granularita) con log del piano file."""
        import fec_utility
        periodi = fec_utility.spezza_granularita(dal, al, gran)
        if len(periodi) > 1:
            log(f"Genererò {len(periodi)} file "
                f"(uno per {'trimestre' if gran == 'trimestre' else 'mese'}).")
        return periodi

    def _run_utility_dump(self):
        """Debug: salva in _materiale/ la lista JSON del periodo e il dettaglio
        della prima fattura (per confermare i nomi campo del parser)."""
        cf, pin, pwd, cfst = self._get_creds()
        cfcl = self.util_cfcl.get().strip()
        piva = self.util_piva.get().strip()
        dal = self.util_dal.get().strip()
        al = self.util_al.get().strip()
        tipo = self._UTILITY_TIPI.get(self.util_tipo.get(), "emesse")

        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF Cliente": cfcl},
                              **{"Data inizio": dal}, **{"Data fine": al}):
            return
        materiale = os.path.join(SCRIPT_DIR, "_materiale")

        def op(res, log, fq, ctrl):
            import fec_utility
            fec_utility.dump_json_esempio(res, tipo, dal, al,
                                          dest_dir=materiale, log=log)
            log("⚠️  I dump contengono dati reali: restano in «_materiale/» (fuori da Git).")

        self._esegui_in_process(cfcl, piva, _profilo_da_modalita(self.modalita.get()),
            f"Dump JSON {tipo}", op)

    def _run_utility_har(self):
        """Debug: browser visibile con registrazione HAR a navigazione libera
        (per scoprire gli endpoint dei corrispettivi / verificare le fatture)."""
        cf, pin, pwd, cfst = self._get_creds()
        if not self._validate(**{"Nome utente/CF": cf, "PIN": pin, "Password": pwd}):
            return
        materiale = os.path.join(SCRIPT_DIR, "_materiale")

        def task(log):
            import fec_utility
            log(f"\n{'─' * 60}\n🎥  Cattura HAR fatture/corrispettivi "
                f"(browser visibile, navigazione libera)\n{'─' * 60}")
            try:
                fec_utility.cattura_har_debug(cf, pin, pwd,
                                              capture_dir=materiale, log=log)
            except Exception as exc:
                log(f"\n❌ Cattura fallita: {exc}")
                log("ℹ️  Una cattura parziale potrebbe comunque essere in «_materiale/».")

        self._run_inprocess(task)

    def _salva_log_console(self):
        """Debug: salva il contenuto attuale della console in _materiale/."""
        from datetime import datetime
        materiale = os.path.join(SCRIPT_DIR, "_materiale")
        os.makedirs(materiale, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        percorso = os.path.join(materiale, f"console_{ts}.log")
        try:
            testo = self.console.get("1.0", "end-1c")
            with open(percorso, "w", encoding="utf-8") as fh:
                fh.write(testo)
        except Exception as exc:
            messagebox.showerror("Salvataggio log fallito", str(exc))
            return
        self._log(f"\n💾 Log console salvato in {percorso}")


# ─────────────────────────────────────────────────────────────────────────────
def main():
    root = tk.Tk()

    style = ttk.Style()
    for theme in ("vista", "winnative", "xpnative", "clam"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break

    FecGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
