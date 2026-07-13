#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus — v0.03 dev
"""
FEC GUI — Fatture Elettroniche e Corrispettivi
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

__version__ = "0.03 dev"

APP_NAME = "FeC-Plus"
REPO_URL = "https://github.com/denvermotel/FeC-Plus"
LICENSE_URL = "https://raw.githubusercontent.com/denvermotel/FeC-Plus/refs/heads/master/LICENSE"
DOCS_URL = "https://denvermotel.github.io/FeC-Plus/guida.html"
HOME_URL = "https://denvermotel.github.io/FeC-Plus/"

# Percorsi compatibili con l'eseguibile PyInstaller (G.9): i dati persistenti
# (config, credenziali, Download) stanno ACCANTO all'exe; gli asset di sola
# lettura vengono dal bundle (sys._MEIPASS). In esecuzione da sorgente: come prima.
if getattr(sys, "frozen", False):
    SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.executable))
    ASSETS_DIR = os.path.join(getattr(sys, "_MEIPASS", SCRIPT_DIR), "assets")
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    ASSETS_DIR = os.path.join(SCRIPT_DIR, "assets")
APP_ICON = os.path.join(ASSETS_DIR, "AppIcon1024.png")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "fec_gui_config.json")
DEFAULT_DEST_DIR = os.path.join(SCRIPT_DIR, "Download")


def _python_interprete() -> "str | None":
    """
    Interprete Python da usare per «Installa dipendenze» (pip / playwright install).

    Da sorgente: è lo stesso Python che esegue la GUI (venv) → `sys.executable`.
    Da app pacchettizzata (PyInstaller, `dist/FeC-Plus.exe`): `sys.executable` è
    l'ESEGUIBILE dell'app, NON un interprete Python — lanciarlo con «-m pip» non
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

# Modalità SVILUPPO (G.1): stessa codebase, due interfacce scelte dal launcher.
#   - pubblica (default): solo gli strumenti d'uso (download, ecc.).
#   - dev: + scheda Test Login, cattura HAR, selettore backend/headless.
# Attivata da `--dev` sulla riga di comando o da FEC_DEV=1 nell'ambiente.
DEV_MODE = ("--dev" in sys.argv) or (
    os.environ.get("FEC_DEV", "").strip().lower() not in ("", "0", "false", "no")
)

# Selettore date da calendario (G.2): opzionale, fallback a Entry testuale se assente.
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

# Profili dell'utenza di lavoro (vedi ade_auth: 1=Studio→cliente, 2=cassetto, 3=Me stesso)
PROFILI = [
    "1 – Studio → cliente (delegato singolo soggetto)",
    "2 – Studio → cassetto studio (incaricato)",
    "3 – Me stesso",
]

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
        self.root.title(f"{APP_NAME} – Fatture e Corrispettivi  ·  v{__version__}{_dev}")
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

        self.backend_var  = tk.StringVar(value="browser")  # browser | requests
        self.headless_var = tk.BooleanVar(value=True)  # browser nascosto di default
        self.salva_cred_var = tk.BooleanVar(value=True)  # «non salvare credenziali» (G.3)
        # Se True disabilita l'aggiornamento automatico dell'anagrafica deleghe da AdE
        # durante il download (nessun recupero né popup). Vedi tab Deleghe.
        self.deleghe_no_update_var = tk.BooleanVar(value=False)

        # Scheda Download Standard (creati qui per poterli popolare da _load_config)
        self.std_profilo = tk.StringVar(value=PROFILI[0])
        self.std_destdir = tk.StringVar(value=DEFAULT_DEST_DIR)
        self.std_escludi_scartate = tk.BooleanVar(value=True)
        self.std_estrai_p7m = tk.BooleanVar(value=False)

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

        self._load_config()
        # GUI pubblica: nessun selettore backend → default fisso su «requests» (login
        # leggero senza browser, verificato per studio→cliente). In dev resta scelto
        # da config/selettore. Vedi C.1/G.1.
        if not DEV_MODE:
            self.backend_var.set("requests")
        self._build_ui()
        self._refresh_dep_banner()  # G.8: controllo dipendenze all'avvio (inline, non bloccante)

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
        """Carica credenziali (cifrate) e preferenze dai due file gestiti da fec_store (C.3)."""
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
        self.headless_var.set(bool(cfg.get("browser_headless", True)))
        self.std_profilo.set(cfg.get("std_profilo", self.std_profilo.get()))
        self.std_destdir.set(cfg.get("std_destdir", DEFAULT_DEST_DIR) or DEFAULT_DEST_DIR)
        self.salva_cred_var.set(bool(cfg.get("salva_credenziali", True)))
        self.deleghe_no_update_var.set(bool(cfg.get("deleghe_no_update", False)))
        self.std_escludi_scartate.set(bool(cfg.get("std_escludi_scartate_pa", True)))
        self.std_estrai_p7m.set(bool(cfg.get("std_estrai_p7m", False)))
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
        """Salva credenziali (cifrate, se consentito) e preferenze nei due file (C.3)."""
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
            "std_profilo":      self.std_profilo.get(),
            "std_destdir":      self.std_destdir.get().strip(),
            "salva_credenziali": salva,
            "cartelle_documenti": cartelle,
            "deleghe_no_update": bool(self.deleghe_no_update_var.get()),
            "std_escludi_scartate_pa": bool(self.std_escludi_scartate.get()),
            "std_estrai_p7m": bool(self.std_estrai_p7m.get()),
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
        """Pulsante «Installa dipendenze» (G.8): fa scegliere se installare tutto (incluso
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
        """Strumento DEV (G.8): disinstalla le dipendenze selezionate via `pip uninstall`.
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
        win.title(f"Informazioni — {APP_NAME}")
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
        for i in range(9):
            frame.columnconfigure(i, weight=(1 if i % 2 == 1 else 0))

        fields = [
            ("Codice Fiscale:", self.cf_var,      False),
            ("PIN:",            self.pin_var,      False),
            ("Password:",       self.pwd_var,      True),
            ("CF Studio:",      self.cfstudio_var, False),
        ]
        for idx, (lbl, var, secret) in enumerate(fields):
            ttk.Label(frame, text=lbl).grid(row=0, column=idx * 2,     sticky="w", padx=(4, 2))
            ttk.Entry(frame, textvariable=var, width=16,
                      show="●" if secret else "").grid(
                row=0, column=idx * 2 + 1, sticky="ew", padx=(0, 8))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=0, column=8, rowspan=2, padx=(6, 4))
        ttk.Button(btn_frame, text="Salva credenziali",   command=self._save_config,   width=18).pack(pady=(0, 2))
        ttk.Button(btn_frame, text="⚙  Impostazioni",      command=self._show_settings, width=18).pack(pady=(0, 2))
        ttk.Button(btn_frame, text="Installa dipendenze", command=self._install_deps,  width=18).pack(pady=(0, 2))
        if DEV_MODE:  # strumento diagnostico per testare il controllo dipendenze (G.8)
            ttk.Button(btn_frame, text="Disinstalla dipendenze", command=self._uninstall_deps, width=18).pack(pady=(0, 2))
        ttk.Button(btn_frame, text="ℹ  Informazioni",     command=self._show_about,    width=18).pack()

        ttk.Checkbutton(
            frame, text="Non salvare le credenziali su questo computer",
            variable=self.salva_cred_var, onvalue=False, offvalue=True,
        ).grid(row=1, column=0, columnspan=8, sticky="w", padx=(4, 0), pady=(4, 0))

        # Banner dipendenze (G.8): avviso inline non bloccante, popolato da
        # _refresh_dep_banner(); resta nascosto (grid_remove) se non manca nulla.
        self.dep_banner = ttk.Label(frame, wraplength=720, justify="left")
        self.dep_banner.grid(row=2, column=0, columnspan=9, sticky="w", padx=(4, 0), pady=(6, 0))
        self.dep_banner.grid_remove()

    def _refresh_dep_banner(self):
        """Controllo dipendenze all'avvio (G.8): mostra inline le dipendenze mancanti.

        Convenzione UI avvisi (G.2): avviso inline, mai messagebox. Le mancanze «core»
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
        """Form preferenze (G.3): cartella download, profilo di default, salvataggio credenziali."""
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
        ttk.Label(frm, text="Profilo di default:").grid(row=r, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Combobox(frm, textvariable=self.std_profilo, values=PROFILI, state="readonly",
                     width=38).grid(row=r, column=1, columnspan=2, sticky="we")

        r += 1
        ttk.Checkbutton(frm, text="Non salvare le credenziali su questo computer",
                        variable=self.salva_cred_var, onvalue=False, offvalue=True).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(8, 0))

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
        # Anagrafica deleghe (C.6.1): feature indipendente dall'AdE, sempre visibile.
        self._tab_deleghe(nb)
        # Tab ancora non testate/funzionanti: visibili solo in modalità sviluppo
        # (avvia_fec_dev.bat). Nella GUI pubblica si mostra solo «Download Standard».
        if DEV_MODE:
            self._tab_richiesta_massiva(nb)
            self._tab_bolli(nb)
            self._tab_utility(nb)

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
            self._log("\n[INTERRUZIONE richiesta dall'utente — termino appena possibile…]\n")

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
            self._log("\n[In pausa — riprendo al prossimo file]\n")

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
                                        f"\n[Interrotto – codice {self.process.returncode}]\n")
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

    def _esegui_in_process(self, cfcl, piva, profilo_str, descrizione, operazione):
        """
        Autentica UNA volta in-process (backend/headless dalla scheda Test Login)
        e poi esegue `operazione(res, log, fec_queue)` sull'AuthResult.
        `operazione` deve chiamare `fec_queue.esegui_richiesta(...)`, che orchestra
        lo spezzettamento periodi (C.5) sopra fec_download.
        Tutto gira in un worker thread, con log instradato nella console.
        """
        cf, pin, pwd, cfst = self._get_creds()
        profilo  = int(profilo_str.split(" ", 1)[0])
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
            log(f"\n✅ Login OK — backend {res.backend}{msg_piva}. Avvio operazione…")

            # Arricchimento anagrafica deleghe da AdE (salvo spunta «non aggiornare»).
            if cfcl and not self.deleghe_no_update_var.get():
                try:
                    import fec_anagrafica
                    dati = fec_anagrafica.recupera(res, log=log)
                    self._applica_aggiornamento_delega(cfcl, dati, log)
                except Exception as exc:  # noqa: BLE001 — non deve bloccare il download
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
    def _run_btn(frame, row: int, label: str, cmd) -> ttk.Button:
        btn = ttk.Button(frame, text=f"▶  {label}", command=cmd, width=18)
        btn.grid(row=row, column=0, columnspan=2, pady=12)
        return btn

    @staticmethod
    def _note(frame, row: int, text: str):
        ttk.Label(frame, text=text, foreground="#777777", wraplength=520).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(2, 0))

    def _build_access_controls(self, frame, row: int) -> int:
        """
        Riga di controlli ACCESSO condivisi (backend login + headless), inserita in ogni
        scheda. Tutti i widget sono legati alle stesse variabili `self.backend_var` /
        `self.headless_var`, quindi modificarli in una scheda si riflette in tutte.
        Ritorna il numero di riga successivo.

        Solo in DEV_MODE: nella GUI pubblica i controlli non vengono mostrati e si usano
        i valori di default (backend browser, headless ON). Ritorna `row` invariato.
        """
        if not DEV_MODE:
            return row
        ttk.Label(frame, text="Accesso:").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
        bframe = ttk.Frame(frame)
        bframe.grid(row=row, column=1, sticky="w")
        ttk.Radiobutton(bframe, text="Browser (Playwright)", variable=self.backend_var,
                        value="browser").pack(side=tk.LEFT)
        ttk.Radiobutton(bframe, text="Solo requests", variable=self.backend_var,
                        value="requests").pack(side=tk.LEFT, padx=14)
        ttk.Checkbutton(bframe, text="headless", variable=self.headless_var).pack(side=tk.LEFT)
        row += 1
        self._note(frame, row, "headless = browser nascosto (ignorato col backend «Solo requests»).")
        return row + 1

    # ── Selettore date (G.2): calendario + periodi predefiniti ─────────────────

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
                          al_var: tk.StringVar, strf: str) -> int:
        """
        Riga «Periodo:» = dropdown periodi GENERICI (trimestri/mesi/anno) + casella ANNO
        (4 cifre) che insieme precompilano le date. Sotto, i due selettori data
        (inizio/fine): se l'utente li modifica a mano, il periodo si azzera.
        Ritorna il numero di riga successivo.
        """
        import calendar
        from datetime import date

        oggi = date.today()
        periodi = _periodi_generici()
        mapping = {lbl: (m0, m1) for lbl, m0, m1 in periodi}
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
    # TAB 0 – Test Login  (smoke-test del nuovo login AdE, in-process)
    # ─────────────────────────────────────────────────────────────────────────

    def _tab_test_login(self, nb: ttk.Notebook):
        tab = ttk.Frame(nb)
        nb.add(tab, text="  Test Login  ")
        f = self._lf(tab)

        self.tl_cfcl    = tk.StringVar()
        self.tl_piva    = tk.StringVar()
        self.tl_profilo = tk.StringVar(value=PROFILI[0])

        r = 0
        ttk.Label(
            f,
            text="Verifica che l'app si avvii e superi il login del portale AdE "
                 "(credenziali Entratel in alto).",
            foreground="#555", wraplength=560,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(0, 8))

        r += 1
        r = self._build_access_controls(f, r)
        self._combo(f, r, "Profilo:", self.tl_profilo, PROFILI)
        r += 1; self._row(f, r, "CF Cliente:", self.tl_cfcl)
        r += 1; self._row(f, r, "P.IVA Cliente:", self.tl_piva)
        r += 1; self._note(f, r, "Studio associato: in alto metti le credenziali Fisconline del "
                                 "titolare e in «CF Studio» il CF dello studio incaricante "
                                 "(es. 12345678901). Col backend Browser puoi completare a mano "
                                 "l'eventuale scelta utenza nella finestra Chromium.")
        r += 1; self._run_btn(f, r, "Test Login", self._run_test_login)
        r += 1
        ttk.Button(f, text="🎥  Cattura login (HAR)", command=self._run_capture_login,
                   width=24).grid(row=r, column=0, columnspan=2, pady=(0, 4))
        r += 1; self._note(f, r, "Cattura il traffico di rete del login reale in «_materiale/» "
                                 "(HAR + log) per sviluppare il backend «Solo requests» (C.1). "
                                 "Forza il browser visibile; il file contiene credenziali in "
                                 "chiaro, non condividerlo.")

    def _run_capture_login(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl    = self.tl_cfcl.get().strip()
        piva    = self.tl_piva.get().strip()
        profilo = int(self.tl_profilo.get().split(" ", 1)[0])

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
            log(f"\n✅ Login OK — cattura completata (vedi i percorsi HAR/LOG qui sopra).")
            for n in res.note:
                log(f"   ℹ️  {n}")

        self._run_inprocess(task)

    def _run_test_login(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl    = self.tl_cfcl.get().strip()
        piva    = self.tl_piva.get().strip()
        profilo = int(self.tl_profilo.get().split(" ", 1)[0])
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
            log(f"\n✅ Login OK — backend {res.backend}{msg_piva}, token ottenuti "
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

    # ── Scelta P.IVA (popup) — condivisa da Test Login, Download Standard e wizard ──

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
    # TAB 1 – Download Standard
    # ─────────────────────────────────────────────────────────────────────────

    # ── Scheda «Deleghe» — anagrafica locale (C.6.1) ───────────────────────────

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

        self._note(f, 5, "«Aggiorna da AdE»: fa login sul CF selezionato (o del form) e ricava da "
                         "AdE denominazione, P.IVA, conservazione e codice destinatario, "
                         "proponendo i campi variati; «Aggiorna tutte» lo fa su tutte le deleghe con "
                         "un solo accesso. Lo stesso avviene in automatico al download, salvo la "
                         "spunta qui sopra. L'import dal CSV AdE «Elenco deleganti» riempie solo CF "
                         "e data fine delega: la conservazione si legge solo dal portale (i tasti "
                         "«Aggiorna…»). «Usa per download» precompila la scheda Download Standard.")
        self._deleghe_refresh()

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
        profilo = int(self.std_profilo.get().split(" ", 1)[0])

        def task(log):
            from ade_auth import autentica, Creds, AuthError
            import fec_anagrafica
            log(f"\n{'─' * 60}\n↻  Aggiorna anagrafica da AdE — CF {cfcl}\n{'─' * 60}")
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
        profilo = int(self.std_profilo.get().split(" ", 1)[0])
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
            quiet = lambda _m: None  # noqa: E731 — silenzia il log interno del login
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

    def _deleghe_import_ade(self):
        path = filedialog.askopenfilename(
            title="Seleziona il CSV «Elenco deleganti» esportato dall'AdE",
            initialdir=os.path.join(SCRIPT_DIR, "_materiale"),
            filetypes=[("CSV", "*.csv"), ("Tutti i file", "*.*")])
        if not path:
            return
        try:
            nuove = self._deleghe.import_csv_ade(path)
        except Exception as e:  # noqa: BLE001 — errore mostrato all'utente
            messagebox.showerror("Import AdE", f"Impossibile leggere il file:\n{e}")
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
        # self.std_profilo / self.std_destdir creati in __init__ (popolati da config)

        r = 0
        cb = self._combo(f, r, "Tipo documento:", self.std_tipo, [
            "Fatture Emesse",
            "Fatture Ricevute",
            "Transfrontaliere Emesse",
            "Transfrontaliere Ricevute",
            "Messe a Disposizione",
        ])
        cb.bind("<<ComboboxSelected>>", self._std_tipo_changed)

        r += 1; self._combo(f, r, "Profilo:", self.std_profilo, PROFILI)
        r = self._build_access_controls(f, r + 1) - 1

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

        r += 1; self._note(f, r, "Download in-process con un solo login "
                                 "(backend/headless dalla scheda Test Login). "
                                 "«Cerca per» vale solo per le Fatture Ricevute.")

        r += 1; r = self._no_update_check(f, r)
        self._run_btn(f, r, "Avvia Download", self._run_standard)

    def _std_pick_destdir(self):
        scelta = filedialog.askdirectory(
            title="Cartella di destinazione dei download",
            initialdir=self.std_destdir.get().strip() or DEFAULT_DEST_DIR)
        if scelta:
            self.std_destdir.set(scelta)

    def _std_tipo_changed(self, _=None):
        visible = self.std_tipo.get() == "Fatture Ricevute"
        fg    = "black" if visible else "#aaaaaa"
        state = "normal" if visible else "disabled"
        self._tipdata_lbl.configure(foreground=fg)
        for w in self._tipdata_frame.winfo_children():
            w.configure(state=state)  # type: ignore[call-arg]  # i figli (radio/combo) supportano -state
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
        # spezza i periodi > 3 mesi (C.5) e unisce i risultati.
        escludi_scartate = bool(self.std_escludi_scartate.get())
        estrai_p7m = bool(self.std_estrai_p7m.get())

        OPS = {
            "Fatture Emesse": lambda res, log, fq, ctrl:
                fq.esegui_richiesta(res, "emesse", dal=dal, al=al, cf_cliente=cfcl,
                                    dest_dir=d_em, sottocartella=s_em, control=ctrl, log=log,
                                    escludi_scartate_pa=escludi_scartate, estrai_p7m=estrai_p7m),
            "Fatture Ricevute": lambda res, log, fq, ctrl:
                fq.esegui_richiesta(res, "ricevute", dal=dal, al=al, cf_cliente=cfcl,
                                    tipo_data=tipdata, dest_dir=d_ri, sottocartella=s_ri,
                                    control=ctrl, log=log,
                                    escludi_scartate_pa=escludi_scartate, estrai_p7m=estrai_p7m),
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
        self._esegui_in_process(cfcl, piva, self.std_profilo.get(), tipo, OPS[tipo])

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 2 – Richieste Massive
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

        self.mass_tipo    = tk.StringVar(value="Emesse")
        self.mass_profilo = tk.StringVar(value=PROFILI[0])
        self.mass_cfcl    = tk.StringVar()
        self.mass_piva    = tk.StringVar()
        self.mass_dal     = tk.StringVar()
        self.mass_al      = tk.StringVar()

        r = 0
        self._combo(f, r, "Tipo richiesta:", self.mass_tipo, [
            "Emesse",
            "Ricevute per Data Emissione",
            "Ricevute per Data Ricezione",
            "Corrispettivi",
        ])
        r += 1; self._combo(f, r, "Profilo:", self.mass_profilo, PROFILI)
        r = self._build_access_controls(f, r + 1) - 1
        r += 1; self._row(f, r, "CF Cliente:", self.mass_cfcl)
        r += 1; self._row(f, r, "P.IVA Cliente:", self.mass_piva)
        r += 1; r = self._build_date_range(f, r, self.mass_dal, self.mass_al, "%Y-%m-%d") - 1
        r += 1; self._note(f, r, "Genera e carica un file XML su /cons/mass-services/ dell'AdE.  Date nel formato AAAA-MM-GG.")
        r += 1; r = self._no_update_check(f, r)
        self._run_btn(f, r, "Avvia Richiesta Massiva", self._run_richiesta_massiva)

    # Tipo richiesta -> (classe cartella DOC_CLASSI, chiave fec_queue.esegui_richiesta)
    _RICHIESTA_MASSIVA_OPS = {
        "Emesse":                       ("massive",       "massive_emesse"),
        "Ricevute per Data Emissione":  ("massive",       "massive_ricevute_emissione"),
        "Ricevute per Data Ricezione":  ("massive",       "massive_ricevute_ricezione"),
        "Corrispettivi":                ("corrispettivi", "corrispettivi"),
    }

    def _run_richiesta_massiva(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl = self.mass_cfcl.get().strip()
        piva = self.mass_piva.get().strip()
        dal  = self.mass_dal.get().strip()
        al   = self.mass_al.get().strip()
        tipo = self.mass_tipo.get()

        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF Cliente": cfcl}, **{"P.IVA Cliente": piva},
                              **{"Data inizio": dal}, **{"Data fine": al}):
            return

        classe, chiave_richiesta = self._RICHIESTA_MASSIVA_OPS[tipo]
        destdir, sotto = self._dest_classe(classe)
        op = lambda res, log, fq, ctrl: fq.esegui_richiesta(
            res, chiave_richiesta, dal=dal, al=al, cf_cliente=cfcl, piva=piva,
            dest_dir=destdir, sottocartella=sotto, control=ctrl, log=log)
        self._esegui_in_process(cfcl, piva, self.mass_profilo.get(),
                                f"Richiesta Massiva {tipo}", op)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 3 – Bolli Virtuali
    # ─────────────────────────────────────────────────────────────────────────

    def _tab_bolli(self, nb: ttk.Notebook):
        tab = ttk.Frame(nb)
        nb.add(tab, text="  Bolli Virtuali  ")
        f = self._lf(tab)

        self.bolli_profilo = tk.StringVar(value=PROFILI[0])
        self.bolli_cfcl = tk.StringVar()
        self.bolli_piva = tk.StringVar()
        self.bolli_trim = tk.StringVar(value="1")
        self.bolli_anno = tk.StringVar()

        r = 0
        self._combo(f, r, "Profilo:", self.bolli_profilo, PROFILI)
        r = self._build_access_controls(f, r + 1) - 1
        r += 1; self._row(f, r, "CF Cliente:", self.bolli_cfcl)
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
                                 "scadenza, stato pagamento, versamenti F24) per il trimestre o "
                                 "l'intero anno selezionato. La generazione del modello F24 non è disponibile "
                                 "da questa procedura: va completata sul portale AdE.")
        r += 1; r = self._no_update_check(f, r)
        self._run_btn(f, r, "Genera Riepilogo Bolli", self._run_bolli)

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
        self._esegui_in_process(cfcl, piva, self.bolli_profilo.get(),
                                f"Bolli {trim_ui}/{anno}", op)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB Utility (C.9/G.6) – elenchi Excel di riepilogo (dev-only)
    # ─────────────────────────────────────────────────────────────────────────

    # Etichetta del combo «Tipo elenco» → chiave fec_utility.TIPI_ELENCO.
    _UTILITY_TIPI = {
        "Fatture Emesse":                    "emesse",
        "Fatture Ricevute (per ricezione)":  "ricevute_ricezione",
        "Fatture Ricevute (per emissione)":  "ricevute_emissione",
        "Transfrontaliere Emesse":           "trans_emesse",
        "Transfrontaliere Ricevute":         "trans_ricevute",
    }

    def _tab_utility(self, nb: ttk.Notebook):
        tab = ttk.Frame(nb)
        nb.add(tab, text="  Utility  ")
        f = self._lf(tab)

        self.util_profilo = tk.StringVar(value=PROFILI[0])
        self.util_cfcl = tk.StringVar()
        self.util_piva = tk.StringVar()
        self.util_tipo = tk.StringVar(value="Fatture Emesse")
        self.util_dal = tk.StringVar()
        self.util_al = tk.StringVar()

        r = 0
        self._combo(f, r, "Tipo elenco:", self.util_tipo,
                    list(self._UTILITY_TIPI))
        r += 1; self._combo(f, r, "Profilo:", self.util_profilo, PROFILI)
        r = self._build_access_controls(f, r + 1) - 1
        r += 1; self._row(f, r, "CF Cliente:", self.util_cfcl)
        r += 1; self._row(f, r, "P.IVA (opzionale):", self.util_piva)
        r += 1; r = self._build_date_range(f, r, self.util_dal, self.util_al,
                                           "%d%m%Y") - 1
        r += 1; self._note(f, r, "Genera un file Excel (.xlsx) di riepilogo con una riga "
                                 "per fattura e colonne per aliquota IVA / natura "
                                 "(richiede il pacchetto opzionale «openpyxl»). "
                                 "Una chiamata di dettaglio per fattura: su periodi ampi "
                                 "richiede qualche minuto.")
        r += 1; r = self._no_update_check(f, r)
        self._run_btn(f, r, "Fatture → Excel", self._run_utility_excel)
        r += 1
        ttk.Button(f, text="Corrispettivi → Excel", state="disabled").grid(
            row=r, column=1, sticky="w", pady=(2, 0))
        r += 1; self._note(f, r, "«Corrispettivi → Excel» è in sviluppo: gli endpoint di "
                                 "consultazione corrispettivi non sono ancora noti "
                                 "(richiede una cattura HAR sul portale).")

    def _run_utility_excel(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl = self.util_cfcl.get().strip()
        piva = self.util_piva.get().strip()
        dal = self.util_dal.get().strip()
        al = self.util_al.get().strip()
        tipo_ui = self.util_tipo.get()
        tipo = self._UTILITY_TIPI.get(tipo_ui, "emesse")
        destdir, sotto = self._dest_classe("utility")

        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF Cliente": cfcl},
                              **{"Data inizio": dal}, **{"Data fine": al}):
            return
        mancanti = fec_deps.find_missing().get("excel", [])
        if mancanti:
            messagebox.showerror(
                "Dipendenza mancante",
                "L'export Excel richiede il pacchetto «openpyxl», non installato.\n\n"
                f"Installa con:  {fec_deps.pip_install_hint(mancanti)}")
            return

        def op(res, log, fq, ctrl):
            import fec_utility
            fec_utility.elenco_fatture_excel(
                res, cfcl, piva, tipo, dal, al,
                dest_dir=destdir, sottocartella=sotto, control=ctrl, log=log)

        self._esegui_in_process(cfcl, piva, self.util_profilo.get(),
                                f"Elenco Excel {tipo_ui}", op)


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
