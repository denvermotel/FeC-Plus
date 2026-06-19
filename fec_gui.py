#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

__version__ = "0.01 alpha"

APP_NAME = "FeC-Plus"
REPO_URL = "https://github.com/denvermotel/FeC-Plus"
LICENSE_URL = "https://github.com/denvermotel/FeC-Plus?tab=License-1-ov-file"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "fec_gui_config.json")
DEFAULT_DEST_DIR = os.path.join(SCRIPT_DIR, "Download")
PYTHON = sys.executable

# Profili dell'utenza di lavoro (vedi ade_auth: 1=Studio→cliente, 2=cassetto, 3=Me stesso)
PROFILI = [
    "1 – Studio → cliente (delegato singolo soggetto)",
    "2 – Studio → cassetto studio (incaricato)",
    "3 – Me stesso",
]


# ─────────────────────────────────────────────────────────────────────────────
class FecGui:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} – Fatture e Corrispettivi  ·  v{__version__}")
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
        self.headless_var = tk.BooleanVar(value=False)

        # Scheda Download Standard (creati qui per poterli popolare da _load_config)
        self.std_profilo = tk.StringVar(value=PROFILI[0])
        self.std_destdir = tk.StringVar(value=DEFAULT_DEST_DIR)

        self.process: "subprocess.Popen | None" = None
        self.worker: "threading.Thread | None" = None

        self._load_config()
        self._build_ui()

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            self.cf_var.set(cfg.get("cf", ""))
            self.pin_var.set(cfg.get("pin", ""))
            self.cfstudio_var.set(cfg.get("cfstudio", ""))
            self.backend_var.set(cfg.get("login_backend", "browser"))
            self.headless_var.set(bool(cfg.get("browser_headless", False)))
            self.std_profilo.set(cfg.get("std_profilo", self.std_profilo.get()))
            self.std_destdir.set(cfg.get("std_destdir", DEFAULT_DEST_DIR) or DEFAULT_DEST_DIR)
        except Exception:
            pass

    def _save_config(self):
        cfg = {
            "cf":              self.cf_var.get().strip(),
            "pin":             self.pin_var.get().strip(),
            "cfstudio":        self.cfstudio_var.get().strip(),
            "login_backend":   self.backend_var.get(),
            "browser_headless": bool(self.headless_var.get()),
            "std_profilo":     self.std_profilo.get(),
            "std_destdir":     self.std_destdir.get().strip(),
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
        messagebox.showinfo("Salvato", "CF, PIN e CF Studio salvati.\nLa password non viene salvata per sicurezza.")

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
        btn_frame.grid(row=0, column=8, padx=(6, 4))
        ttk.Button(btn_frame, text="Salva credenziali",   command=self._save_config,   width=18).pack(pady=(0, 2))
        ttk.Button(btn_frame, text="Installa dipendenze", command=self._install_deps,  width=18).pack(pady=(0, 2))
        ttk.Button(btn_frame, text="ℹ  Informazioni",     command=self._show_about,    width=18).pack()

    def _build_notebook(self):
        nb = ttk.Notebook(self.root)
        nb.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)

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
        ttk.Label(f, text="Backend login:").grid(row=r, column=0, sticky="w", pady=4, padx=(0, 8))
        bframe = ttk.Frame(f)
        bframe.grid(row=r, column=1, sticky="w")
        ttk.Radiobutton(bframe, text="Browser (Playwright)", variable=self.backend_var,
                        value="browser").pack(side=tk.LEFT)
        ttk.Radiobutton(bframe, text="Solo requests", variable=self.backend_var,
                        value="requests").pack(side=tk.LEFT, padx=14)
        ttk.Checkbutton(bframe, text="headless", variable=self.headless_var).pack(side=tk.LEFT)

        r += 1; self._combo(f, r, "Profilo:", self.tl_profilo, PROFILI)
        r += 1; self._row(f, r, "CF Cliente:", self.tl_cfcl)
        r += 1; self._row(f, r, "P.IVA Cliente:", self.tl_piva)
        r += 1; self._note(f, r, "Studio associato: in alto metti le credenziali Fisconline del "
                                 "titolare e in «CF Studio» il CF dello studio incaricante "
                                 "(es. 12345678901). Col backend Browser puoi completare a mano "
                                 "l'eventuale scelta utenza nella finestra Chromium.")
        r += 1; self._run_btn(f, r, "Test Login", self._run_test_login)

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
            # Conferma collegamento: GET autenticata innocua
            from ade_auth import IVASERVIZI, unix_time
            try:
                r = res.session.get(
                    f"{IVASERVIZI}/cons/cons-services/rs/fe/adesione/stato/?v={unix_time()}",
                    headers=res.headers, verify=False, timeout=30)
                log(f"✅ Collegamento al servizio confermato (HTTP {r.status_code}).")
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

        r += 1; self._row(f, r, "CF Cliente:", self.std_cf_cl)
        r += 1; self._row(f, r, "P.IVA Cliente:", self.std_piva)
        r += 1; self._row(f, r, "Data inizio  (ddmmyyyy):", self.std_dal, 14)
        r += 1; self._row(f, r, "Data fine    (ddmmyyyy):", self.std_al,  14)

        r += 1
        ttk.Label(f, text="Cartella destinazione:").grid(row=r, column=0, sticky="w", pady=4, padx=(0, 8))
        destframe = ttk.Frame(f)
        destframe.grid(row=r, column=1, sticky="w")
        ttk.Entry(destframe, textvariable=self.std_destdir, width=40).pack(side=tk.LEFT)
        ttk.Button(destframe, text="Sfoglia…", command=self._std_pick_destdir, width=10).pack(side=tk.LEFT, padx=(6, 0))

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

    def _run_standard(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl = self.std_cf_cl.get().strip()
        piva = self.std_piva.get().strip()
        dal  = self.std_dal.get().strip()
        al   = self.std_al.get().strip()
        tipo = self.std_tipo.get()
        destdir = self.std_destdir.get().strip() or DEFAULT_DEST_DIR
        tipdata = int(self.std_tipdata.get())

        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF Cliente": cfcl}, **{"P.IVA Cliente": piva},
                              **{"Data inizio": dal}, **{"Data fine": al}):
            return

        # Tutte le tipologie ora girano in-process (un solo login, niente subprocess).
        OPS = {
            "Fatture Emesse": lambda res, log, fd:
                fd.scarica_emesse(res, dal, al, cfcl, dest_dir=destdir, log=log),
            "Fatture Ricevute": lambda res, log, fd:
                fd.scarica_ricevute(res, dal, al, cfcl, tipo_data=tipdata,
                                    dest_dir=destdir, log=log),
            "Transfrontaliere Emesse": lambda res, log, fd:
                fd.scarica_transfrontaliere_emesse(res, dal, al, cfcl,
                                                   dest_dir=destdir, log=log),
            "Transfrontaliere Ricevute": lambda res, log, fd:
                fd.scarica_transfrontaliere_ricevute(res, dal, al, cfcl,
                                                     dest_dir=destdir, log=log),
            "Messe a Disposizione": lambda res, log, fd:
                fd.scarica_messe_a_disposizione(res, dal, al, cfcl,
                                                dest_dir=destdir, log=log),
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
        r += 1; self._row(f, r, "CF Cliente:", self.mass_cfcl)
        r += 1; self._row(f, r, "P.IVA Cliente:", self.mass_piva)
        r += 1; self._row(f, r, "Data inizio  (YYYY-MM-DD):", self.mass_dal, 14)
        r += 1; self._row(f, r, "Data fine    (YYYY-MM-DD):", self.mass_al,  14)
        r += 1; self._note(f, r, "Genera e carica un file XML su /cons/mass-services/ dell'AdE.  Date nel formato AAAA-MM-GG.")
        r += 1; self._run_btn(f, r, "Avvia Richiesta Massiva", self._run_massive)

    def _run_massive(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl = self.mass_cfcl.get().strip()
        piva = self.mass_piva.get().strip()
        dal  = self.mass_dal.get().strip()
        al   = self.mass_al.get().strip()
        tipo = self.mass_tipo.get()
        destdir = self.std_destdir.get().strip() or DEFAULT_DEST_DIR

        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF Cliente": cfcl}, **{"P.IVA Cliente": piva},
                              **{"Data inizio": dal}, **{"Data fine": al}):
            return

        OPS = {
            "Emesse": lambda res, log, fd:
                fd.richiesta_massiva_emesse(res, dal, al, cfcl, piva,
                                            dest_dir=destdir, log=log),
            "Ricevute per Data Emissione": lambda res, log, fd:
                fd.richiesta_massiva_ricevute_emissione(res, dal, al, cfcl, piva,
                                                        dest_dir=destdir, log=log),
            "Ricevute per Data Ricezione": lambda res, log, fd:
                fd.richiesta_massiva_ricevute_ricezione(res, dal, al, cfcl, piva,
                                                        dest_dir=destdir, log=log),
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
        destdir = self.std_destdir.get().strip() or DEFAULT_DEST_DIR

        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF Cliente": cfcl}, **{"P.IVA Cliente": piva},
                              Trimestre=trim, Anno=anno):
            return

        op = lambda res, log, fd: fd.scarica_bolli(res, cfcl, piva, trim, anno,
                                                   dest_dir=destdir, log=log)
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
        r += 1; self._row(f, r, "CF Cliente:", self.corr_cfcl)
        r += 1; self._row(f, r, "P.IVA Cliente:", self.corr_piva)
        r += 1; self._row(f, r, "Data inizio  (YYYY-MM-DD):", self.corr_dal, 14)
        r += 1; self._row(f, r, "Data fine    (YYYY-MM-DD):", self.corr_al,  14)
        r += 1; self._note(f, r, "Genera XML e carica su /cons/mass-services/.  Date nel formato AAAA-MM-GG.")
        r += 1; self._run_btn(f, r, "Avvia Corrispettivi", self._run_corrispettivi)

    def _run_corrispettivi(self):
        cf, pin, pwd, cfst = self._get_creds()
        cfcl = self.corr_cfcl.get().strip()
        piva = self.corr_piva.get().strip()
        dal  = self.corr_dal.get().strip()
        al   = self.corr_al.get().strip()
        destdir = self.std_destdir.get().strip() or DEFAULT_DEST_DIR

        if not self._validate(CF=cf, PIN=pin, Password=pwd, **{"CF Studio": cfst},
                              **{"CF Cliente": cfcl}, **{"P.IVA Cliente": piva},
                              **{"Data inizio": dal}, **{"Data fine": al}):
            return

        op = lambda res, log, fd: fd.richiesta_corrispettivi(res, dal, al, cfcl, piva,
                                                             dest_dir=destdir, log=log)
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
