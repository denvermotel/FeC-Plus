#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus — v0.02 alpha
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

__version__ = "0.02 alpha"

APP_NAME = "FeC-Plus"
REPO_URL = "https://github.com/denvermotel/FeC-Plus"
LICENSE_URL = "https://github.com/denvermotel/FeC-Plus?tab=MIT-1-ov-file"
DOCS_URL = "https://denvermotel.github.io/FeC-Plus/guida.html"
HOME_URL = "https://denvermotel.github.io/FeC-Plus/"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(SCRIPT_DIR, "assets")
APP_ICON = os.path.join(ASSETS_DIR, "AppIcon1024.png")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "fec_gui_config.json")
DEFAULT_DEST_DIR = os.path.join(SCRIPT_DIR, "Download")
PYTHON = sys.executable

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
        _dev = "  ·  DEV" if DEV_MODE else ""
        self.root.title(f"{APP_NAME} – Fatture e Corrispettivi  ·  v{__version__}{_dev}")
        self._set_app_icon()
        self.root.geometry("880x760")
        self.root.minsize(780, 600)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=0)
        self.root.rowconfigure(2, weight=1)

        self.cf_var       = tk.StringVar()
        self.pin_var      = tk.StringVar()
        self.pwd_var      = tk.StringVar()
        self.cfstudio_var = tk.StringVar()

        self.backend_var  = tk.StringVar(value="browser")  # browser | requests
        self.headless_var = tk.BooleanVar(value=True)  # browser nascosto di default
        self.salva_cred_var = tk.BooleanVar(value=True)  # «non salvare credenziali» (G.3)

        # Scheda Download Standard (creati qui per poterli popolare da _load_config)
        self.std_profilo = tk.StringVar(value=PROFILI[0])
        self.std_destdir = tk.StringVar(value=DEFAULT_DEST_DIR)

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

        self._load_config()
        # GUI pubblica: nessun selettore backend → default fisso su «requests» (login
        # leggero senza browser, verificato per studio→cliente). In dev resta scelto
        # da config/selettore. Vedi C.1/G.1.
        if not DEV_MODE:
            self.backend_var.set("requests")
        self._build_ui()

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
        packages = ["requests", "python-dateutil", "playwright"]
        self._log("\nInstallazione dipendenze + browser Chromium per Playwright...\n")
        self._run_sequence([
            [PYTHON, "-m", "pip", "install", "--upgrade"] + packages,
            [PYTHON, "-m", "playwright", "install", "chromium"],
        ])

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

    def _build_ui(self):
        self._build_credentials()
        self._build_notebook()
        self._build_console()

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
            kw = {"show": "●"} if secret else {}
            ttk.Entry(frame, textvariable=var, width=16, **kw).grid(
                row=0, column=idx * 2 + 1, sticky="ew", padx=(0, 8))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=0, column=8, rowspan=2, padx=(6, 4))
        ttk.Button(btn_frame, text="Salva credenziali",   command=self._save_config,   width=18).pack(pady=(0, 2))
        ttk.Button(btn_frame, text="⚙  Impostazioni",      command=self._show_settings, width=18).pack(pady=(0, 2))
        ttk.Button(btn_frame, text="Installa dipendenze", command=self._install_deps,  width=18).pack(pady=(0, 2))
        ttk.Button(btn_frame, text="ℹ  Informazioni",     command=self._show_about,    width=18).pack()

        ttk.Checkbutton(
            frame, text="Non salvare le credenziali su questo computer",
            variable=self.salva_cred_var, onvalue=False, offvalue=True,
        ).grid(row=1, column=0, columnspan=8, sticky="w", padx=(4, 0), pady=(4, 0))

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
        nb = ttk.Notebook(self.root)
        nb.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)

        if DEV_MODE:
            self._tab_test_login(nb)
        self._tab_standard(nb)
        self._tab_massive(nb)
        self._tab_bolli(nb)
        self._tab_corrispettivi(nb)

    def _build_console(self):
        frame = ttk.LabelFrame(self.root, text=" Output ", padding=(6, 4))
        frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(4, 10))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

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
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self._log("\n[INTERROTTO dall'utente]\n")

    # ── Process runner ────────────────────────────────────────────────────────

    def _run_sequence(self, commands: list):
        """Esegue più comandi in sequenza nello stesso thread, fermandosi al primo errore.
        Usato solo dall'installazione dipendenze (pip / playwright)."""
        if self.process and self.process.poll() is None:
            messagebox.showwarning("In esecuzione", "Un processo è già in esecuzione.")
            return

        def _target():
            for args in commands:
                self.root.after(0, self._log, f"\n▶  {' '.join(str(a) for a in args)}\n")
                try:
                    self.process = subprocess.Popen(
                        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace", cwd=SCRIPT_DIR,
                    )
                    for line in self.process.stdout:
                        self.root.after(0, self._log, line)
                    self.process.wait()
                    if self.process.returncode != 0:
                        self.root.after(0, self._log,
                                        f"\n[Interrotto – codice {self.process.returncode}]\n")
                        return
                except Exception as exc:
                    self.root.after(0, self._log, f"\n[ERRORE] {exc}\n")
                    return
            self.root.after(0, self._log, "\n[Completato]\n")

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

        self.worker = threading.Thread(target=_target, daemon=True)
        self.worker.start()

    def _esegui_in_process(self, cfcl, piva, profilo_str, descrizione, operazione):
        """
        Autentica UNA volta in-process (backend/headless dalla scheda Test Login)
        e poi esegue `operazione(res, log, fec_download)` sull'AuthResult.
        `operazione` deve chiamare la funzione opportuna di fec_download.
        Tutto gira in un worker thread, con log instradato nella console.
        """
        cf, pin, pwd, cfst = self._get_creds()
        profilo  = int(profilo_str.split(" ", 1)[0])
        backend  = self.backend_var.get()
        headless = bool(self.headless_var.get())

        def task(log):
            from ade_auth import autentica, Creds, AuthError
            import fec_download

            log(f"\n{'─' * 60}\n▶  {descrizione} (in-process, backend: {backend})\n{'─' * 60}")
            creds = Creds(nomeutente=cf, pin=pin, password=pwd, cfstudio=cfst,
                          cf_cliente=cfcl, piva=piva, profilo=profilo)
            try:
                res = autentica(creds, backend=backend, headless=headless, log=log)
            except AuthError as exc:
                log(f"\n❌ Login fallito allo step «{exc.step}»: {exc.dettaglio}")
                return
            log(f"\n✅ Login OK — backend {res.backend}. Avvio operazione…")
            try:
                operazione(res, log, fec_download)
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
        kw = {"show": show} if show else {}
        entry = ttk.Entry(frame, textvariable=var, width=width, **kw)
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
        if _HAS_TKCAL:
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
        anno_entry = ttk.Entry(pframe, textvariable=anno_var, width=6,
                               validate="key", validatecommand=vcmd)
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
                res = autentica(creds, backend=backend, headless=headless, log=log)
            except AuthError as exc:
                log(f"\n❌ Login fallito allo step «{exc.step}»: {exc.dettaglio}")
                return
            log(f"\n✅ Login OK — backend {res.backend}, token ottenuti "
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

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 1 – Download Standard
    # ─────────────────────────────────────────────────────────────────────────

    def _tab_standard(self, nb: ttk.Notebook):
        tab = ttk.Frame(nb)
        nb.add(tab, text="  Download Standard  ")
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
        r += 1; self._row(f, r, "P.IVA Cliente:", self.std_piva)
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

        self._std_tipo_changed()

        r += 1; self._note(f, r, "Download in-process con un solo login "
                                 "(backend/headless dalla scheda Test Login). "
                                 "«Cerca per» vale solo per le Fatture Ricevute.")

        r += 1; self._run_btn(f, r, "Avvia Download", self._run_standard)

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
            w.configure(state=state)
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

        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF Cliente": cfcl}, **{"P.IVA Cliente": piva},
                              **{"Data inizio": dal}, **{"Data fine": al}):
            return

        # Cartella e «sottocartella» risolte per la classe di documento (Impostazioni).
        d_em,  s_em  = self._dest_classe("emesse")
        d_ri,  s_ri  = self._dest_classe("ricevute")
        d_te,  s_te  = self._dest_classe("trans_emesse")
        d_tr,  s_tr  = self._dest_classe("trans_ricevute")
        d_md,  s_md  = self._dest_classe("messe_disposizione")

        # Tutte le tipologie ora girano in-process (un solo login, niente subprocess).
        OPS = {
            "Fatture Emesse": lambda res, log, fd:
                fd.scarica_emesse(res, dal, al, cfcl, dest_dir=d_em,
                                  sottocartella=s_em, log=log),
            "Fatture Ricevute": lambda res, log, fd:
                fd.scarica_ricevute(res, dal, al, cfcl, tipo_data=tipdata,
                                    dest_dir=d_ri, sottocartella=s_ri, log=log),
            "Transfrontaliere Emesse": lambda res, log, fd:
                fd.scarica_transfrontaliere_emesse(res, dal, al, cfcl,
                                                   dest_dir=d_te, sottocartella=s_te, log=log),
            "Transfrontaliere Ricevute": lambda res, log, fd:
                fd.scarica_transfrontaliere_ricevute(res, dal, al, cfcl,
                                                     dest_dir=d_tr, sottocartella=s_tr, log=log),
            "Messe a Disposizione": lambda res, log, fd:
                fd.scarica_messe_a_disposizione(res, dal, al, cfcl,
                                                dest_dir=d_md, sottocartella=s_md, log=log),
        }
        self._esegui_in_process(cfcl, piva, self.std_profilo.get(), tipo, OPS[tipo])

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 2 – Fatture Massive
    # ─────────────────────────────────────────────────────────────────────────

    def _tab_massive(self, nb: ttk.Notebook):
        tab = ttk.Frame(nb)
        nb.add(tab, text="  Fatture Massive  ")
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
        ])
        r += 1; self._combo(f, r, "Profilo:", self.mass_profilo, PROFILI)
        r = self._build_access_controls(f, r + 1) - 1
        r += 1; self._row(f, r, "CF Cliente:", self.mass_cfcl)
        r += 1; self._row(f, r, "P.IVA Cliente:", self.mass_piva)
        r += 1; r = self._build_date_range(f, r, self.mass_dal, self.mass_al, "%Y-%m-%d") - 1
        r += 1; self._note(f, r, "Genera e carica un file XML su /cons/mass-services/ dell'AdE.  Date nel formato AAAA-MM-GG.")
        r += 1; self._run_btn(f, r, "Avvia Richiesta Massiva", self._run_massive)

    def _run_massive(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl = self.mass_cfcl.get().strip()
        piva = self.mass_piva.get().strip()
        dal  = self.mass_dal.get().strip()
        al   = self.mass_al.get().strip()
        tipo = self.mass_tipo.get()
        destdir, sotto = self._dest_classe("massive")

        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF Cliente": cfcl}, **{"P.IVA Cliente": piva},
                              **{"Data inizio": dal}, **{"Data fine": al}):
            return

        OPS = {
            "Emesse": lambda res, log, fd:
                fd.richiesta_massiva_emesse(res, dal, al, cfcl, piva,
                                            dest_dir=destdir, sottocartella=sotto, log=log),
            "Ricevute per Data Emissione": lambda res, log, fd:
                fd.richiesta_massiva_ricevute_emissione(res, dal, al, cfcl, piva,
                                                        dest_dir=destdir, sottocartella=sotto, log=log),
            "Ricevute per Data Ricezione": lambda res, log, fd:
                fd.richiesta_massiva_ricevute_ricezione(res, dal, al, cfcl, piva,
                                                        dest_dir=destdir, sottocartella=sotto, log=log),
        }
        self._esegui_in_process(cfcl, piva, self.mass_profilo.get(),
                                f"Massive {tipo}", OPS[tipo])

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
        r += 1; self._row(f, r, "P.IVA Cliente:", self.bolli_piva)
        r += 1; self._combo(f, r, "Trimestre:", self.bolli_trim, ["1", "2", "3", "4"])
        r += 1; self._row(f, r, "Anno (YYYY):", self.bolli_anno, 8)
        r += 1; self._note(f, r, "Scarica i dati bolli virtuali e genera PDF F24 per il trimestre/anno selezionato.")
        r += 1; self._run_btn(f, r, "Avvia Download Bolli", self._run_bolli)

    def _run_bolli(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl = self.bolli_cfcl.get().strip()
        piva = self.bolli_piva.get().strip()
        trim = self.bolli_trim.get().strip()
        anno = self.bolli_anno.get().strip()
        destdir, sotto = self._dest_classe("bolli")

        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF Cliente": cfcl}, **{"P.IVA Cliente": piva},
                              Trimestre=trim, Anno=anno):
            return

        op = lambda res, log, fd: fd.scarica_bolli(res, cfcl, piva, trim, anno,
                                                   dest_dir=destdir, sottocartella=sotto, log=log)
        self._esegui_in_process(cfcl, piva, self.bolli_profilo.get(),
                                f"Bolli {trim}/{anno}", op)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 4 – Corrispettivi
    # ─────────────────────────────────────────────────────────────────────────

    def _tab_corrispettivi(self, nb: ttk.Notebook):
        tab = ttk.Frame(nb)
        nb.add(tab, text="  Corrispettivi  ")
        f = self._lf(tab)

        self.corr_profilo = tk.StringVar(value=PROFILI[0])
        self.corr_cfcl = tk.StringVar()
        self.corr_piva = tk.StringVar()
        self.corr_dal  = tk.StringVar()
        self.corr_al   = tk.StringVar()

        r = 0
        self._combo(f, r, "Profilo:", self.corr_profilo, PROFILI)
        r = self._build_access_controls(f, r + 1) - 1
        r += 1; self._row(f, r, "CF Cliente:", self.corr_cfcl)
        r += 1; self._row(f, r, "P.IVA Cliente:", self.corr_piva)
        r += 1; r = self._build_date_range(f, r, self.corr_dal, self.corr_al, "%Y-%m-%d") - 1
        r += 1; self._note(f, r, "Genera XML e carica su /cons/mass-services/.  Date nel formato AAAA-MM-GG.")
        r += 1; self._run_btn(f, r, "Avvia Corrispettivi", self._run_corrispettivi)

    def _run_corrispettivi(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl = self.corr_cfcl.get().strip()
        piva = self.corr_piva.get().strip()
        dal  = self.corr_dal.get().strip()
        al   = self.corr_al.get().strip()
        destdir, sotto = self._dest_classe("corrispettivi")

        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF Cliente": cfcl}, **{"P.IVA Cliente": piva},
                              **{"Data inizio": dal}, **{"Data fine": al}):
            return

        op = lambda res, log, fd: fd.richiesta_corrispettivi(res, dal, al, cfcl, piva,
                                                             dest_dir=destdir, sottocartella=sotto, log=log)
        self._esegui_in_process(cfcl, piva, self.corr_profilo.get(),
                                "Corrispettivi", op)


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
