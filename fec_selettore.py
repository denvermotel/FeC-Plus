# FeC-Plus - v0.04 dev
"""fec_selettore.py - Selettore dei soggetti (deleghe) con ricerca per nominativo e scelta multipla.

Derivato da `risc_selettore.SelettoreSoggetto` (A-Risc) e da `cassetto_selettore` (Cassetto-Plus),
che scelgono un solo soggetto. Un campo di ricerca con tendina a comparsa: con le frecce e Invio,
o con un clic, una riga viene aggiunta all'elenco dei soggetti scelti. Un C.F./P.IVA valido
scritto a mano che non è tra le deleghe viene proposto come ultima riga. Con un solo soggetto
scelto compare il campo P.IVA, opzionale (serve ai C.F. con più partite IVA); con più soggetti
si usa la P.IVA di ciascuna delega.
"""
from __future__ import annotations

__version__ = "0.04 dev"

import re
import tkinter as tk
from tkinter import messagebox, ttk
from typing import NamedTuple


class Soggetto(NamedTuple):
    nome: str
    cf: str
    piva: str = ""


def _cf(row: dict) -> str:
    return ((row.get("codice_fiscale") or row.get("partita_iva") or "").strip().upper())


def opzioni_soggetti(rows: list[dict]) -> list[tuple[str, str]]:
    """(testo dell'elenco, C.F.) in ordine alfabetico, per le deleghe con un identificativo. Gli
    omonimi compaiono come «Nome - C.F.» per non collassare in un solo elemento."""
    ordinate = sorted((r for r in rows if _cf(r)),
                      key=lambda r: (not (r.get("denominazione") or "").strip(),
                                     (r.get("denominazione") or "").strip().casefold(), _cf(r)))
    voci = [((r.get("denominazione") or "").strip() or _cf(r), _cf(r)) for r in ordinate]
    conta: dict[str, int] = {}
    for nome, _ in voci:
        conta[nome.casefold()] = conta.get(nome.casefold(), 0) + 1
    return [(f"{nome} - {cf}" if conta[nome.casefold()] > 1 else nome, cf) for nome, cf in voci]


def piva_per_cf(rows: list[dict]) -> dict[str, str]:
    """P.IVA salvata in delega per ogni C.F. (vuota se la delega non ne ha)."""
    return {_cf(r): (r.get("partita_iva") or "").strip() for r in rows if _cf(r)}


def filtra_opzioni(opzioni: list[tuple[str, str]], testo: str) -> list[tuple[str, str]]:
    """Le opzioni il cui testo o C.F. contiene `testo`, senza badare alle maiuscole."""
    q = (testo or "").strip().casefold()
    if not q:
        return list(opzioni)
    return [o for o in opzioni if q in o[0].casefold() or q in o[1].casefold()]


def normalizza_cf(testo: str) -> str:
    """Maiuscolo e senza spazi; valido se C.F. (16 alfanumerici) o P.IVA (11 cifre), altrimenti
    ValueError con un messaggio pronto per l'utente."""
    cf = "".join((testo or "").split()).upper()
    if re.fullmatch(r"[A-Z0-9]{16}", cf) or re.fullmatch(r"\d{11}", cf):
        return cf
    raise ValueError("Inserisci un codice fiscale di 16 caratteri alfanumerici "
                     "oppure una partita IVA di 11 cifre.")


_TASTI_NAVIGAZIONE = ("Up", "Down", "Left", "Right", "Tab", "Escape", "Shift_L", "Shift_R",
                      "Control_L", "Control_R")

_RIGHE_MAX = 8          # righe della tendina
_SCELTI_MAX = 6         # righe visibili dell'elenco dei soggetti scelti
_COL_ACCENTO = "#2f6fdf"
_COL_TENUE = "#6b7280"
_COL_BORDO = "#c5cad1"
_COL_EVIDENZIATO = "#dbe8fb"
_COL_ALTERNATO = "#f5f7fa"


class SelettoreSoggetti(ttk.Frame):
    """Ricerca dei soggetti con tendina a comparsa e scelta multipla. `rows` sono le righe di
    `fec_deleghe.load_deleghe()`; `info_var` riceve «N deleghe».

    `scelti` è l'elenco dei `Soggetto` scelti. `soggetti()` li restituisce pronti per l'uso,
    oppure None dopo aver mostrato l'avviso se non ce n'è nessuno."""

    def __init__(self, master, rows=(), info_var=None):
        super().__init__(master)
        self.nome_var = tk.StringVar()                       # testo della ricerca
        self.piva_var = tk.StringVar()                       # P.IVA, solo con un soggetto
        self.etichetta_piva_var = tk.StringVar(value="P.IVA (opzionale):")
        self.info_var = info_var if info_var is not None else tk.StringVar()
        self.contatore_var = tk.StringVar()                  # nella tendina
        self.contatore_scelti_var = tk.StringVar()
        self.scelti: list[Soggetto] = []
        self._opzioni: list[tuple[str, str]] = []
        self._pive: dict[str, str] = {}
        self._visibili: list[tuple[str, str, bool]] = []     # (testo, C.F., inserito a mano)
        self._evid = -1
        self._aperta = False
        self.columnconfigure(0, weight=1)
        self._stili()
        self._costruisci_ricerca()
        self._costruisci_elenco()
        self._costruisci_piva()
        self._costruisci_tendina()
        self.aggiorna(rows)

    # -- costruzione

    def _stili(self) -> None:
        from tkinter import font as tkfont
        self._font = tkfont.nametofont("TkDefaultFont")
        st = ttk.Style(self)
        st.configure("Selettore.Treeview", rowheight=26, borderwidth=0, relief="flat")
        st.layout("Selettore.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.map("Selettore.Treeview", background=[("selected", _COL_EVIDENZIATO)],
               foreground=[("selected", "black")])

    def _costruisci_ricerca(self) -> None:
        self.riga_ricerca = ttk.Frame(self)
        self.riga_ricerca.grid(row=0, column=0, sticky="ew")
        self.riga_ricerca.columnconfigure(1, weight=1)
        ttk.Label(self.riga_ricerca, text="🔍").grid(row=0, column=0, padx=(2, 6))
        self.entry_nome = ttk.Entry(self.riga_ricerca, textvariable=self.nome_var,
                                    font=self._font)
        self.entry_nome.grid(row=0, column=1, sticky="ew", ipady=3)
        self._segnaposto = tk.Label(self.entry_nome, text="Cerca per nome o C.F.",
                                    fg=_COL_TENUE, bg="white", font=self._font, cursor="xterm")
        self._segnaposto.bind("<Button-1>", lambda _e: self.entry_nome.focus_set())
        self.pulsante_cancella = tk.Label(self.riga_ricerca, text="✕", fg=_COL_TENUE,
                                          cursor="hand2", padx=6)
        self.pulsante_cancella.bind("<Button-1>", lambda _e: self._svuota_ricerca())
        self.pulsante_cancella.grid(row=0, column=2)
        self.pulsante_tutte = ttk.Button(self.riga_ricerca, text="Aggiungi tutte",
                                         command=self.aggiungi_tutte)
        self.pulsante_tutte.grid(row=0, column=3, padx=(8, 0))
        self.pulsante_svuota = ttk.Button(self.riga_ricerca, text="Svuota", command=self.svuota)
        self.pulsante_svuota.grid(row=0, column=4, padx=(4, 0))
        ttk.Label(self.riga_ricerca, textvariable=self.info_var, foreground=_COL_TENUE).grid(
            row=0, column=5, padx=(8, 0))
        e = self.entry_nome
        e.bind("<KeyRelease>", self._filtra)
        e.bind("<Down>", self._giu)
        e.bind("<Up>", self._su)
        e.bind("<Return>", self._invio)
        e.bind("<Escape>", self._esc)
        e.bind("<FocusOut>", lambda _e: self.after(200, self._chiudi_se_fuori))
        self.nome_var.trace_add("write", lambda *_: self._aggiorna_segnaposto())
        self._aggiorna_segnaposto()

    def _costruisci_elenco(self) -> None:
        self.riquadro = tk.Frame(self, bg="white", highlightthickness=1,
                                 highlightbackground=_COL_BORDO)
        self.riquadro.columnconfigure(0, weight=1)
        self.lista = ttk.Treeview(self.riquadro, columns=("nome", "cf"), show="",
                                  style="Selettore.Treeview", selectmode="extended")
        self.lista.column("nome", anchor="w", stretch=True)
        self.lista.column("cf", anchor="e", width=130, stretch=False)
        self.lista.tag_configure("pari", background="white")
        self.lista.tag_configure("dispari", background=_COL_ALTERNATO)
        self.lista.grid(row=0, column=0, sticky="nsew", padx=1, pady=(1, 0))
        self._barra_scelti = ttk.Scrollbar(self.riquadro, orient="vertical",
                                           command=self.lista.yview)
        self.lista.configure(yscrollcommand=self._barra_scelti.set)
        tk.Label(self.riquadro, textvariable=self.contatore_scelti_var, bg="white",
                 fg=_COL_TENUE, anchor="w", padx=8, pady=3).grid(
            row=1, column=0, columnspan=2, sticky="ew")
        self.lista.bind("<Double-1>", self._doppio_clic)
        self.lista.bind("<Delete>", lambda _e: self.rimuovi_selezionati())

    def _costruisci_piva(self) -> None:
        self.riga_piva = ttk.Frame(self)
        ttk.Label(self.riga_piva, textvariable=self.etichetta_piva_var).grid(
            row=0, column=0, sticky="w", pady=4, padx=(0, 8))
        self.entry_piva = ttk.Entry(self.riga_piva, textvariable=self.piva_var, width=22)
        self.entry_piva.grid(row=0, column=1, sticky="w")

    def _costruisci_tendina(self) -> None:
        self.tendina = tk.Toplevel(self)
        self.tendina.withdraw()
        self.tendina.overrideredirect(True)
        cornice = tk.Frame(self.tendina, bg="white", highlightthickness=1,
                           highlightbackground=_COL_BORDO)
        cornice.pack(fill=tk.BOTH, expand=True)
        cornice.columnconfigure(0, weight=1)
        self.albero = ttk.Treeview(cornice, columns=("nome", "cf"), show="",
                                   style="Selettore.Treeview", selectmode="browse")
        self.albero.column("nome", anchor="w", stretch=True)
        self.albero.column("cf", anchor="e", width=130, stretch=False)
        self.albero.tag_configure("pari", background="white")
        self.albero.tag_configure("dispari", background=_COL_ALTERNATO)
        self.albero.tag_configure("mano", foreground=_COL_ACCENTO)
        self.albero.grid(row=0, column=0, sticky="nsew", padx=1, pady=(1, 0))
        self._barra = ttk.Scrollbar(cornice, orient="vertical", command=self.albero.yview)
        self.albero.configure(yscrollcommand=self._barra.set)
        tk.Label(cornice, textvariable=self.contatore_var, bg="white", fg=_COL_TENUE,
                 anchor="e", padx=8, pady=3).grid(row=1, column=0, columnspan=2, sticky="ew")
        self.albero.bind("<Motion>", self._al_passaggio)
        self.albero.bind("<ButtonRelease-1>", self._clic)
        finestra = self.winfo_toplevel()
        finestra.bind("<Configure>", self._finestra_mossa, add="+")
        finestra.bind("<Unmap>", lambda _e: self._chiudi(), add="+")

    # -- dati

    def aggiorna(self, rows) -> None:
        """Sostituisce l'elenco delle deleghe (dopo una modifica nella tab Deleghe). I soggetti
        già scelti restano."""
        rows = list(rows)
        self._opzioni = opzioni_soggetti(rows)
        self._pive = piva_per_cf(rows)
        n = len(self._opzioni)
        self.info_var.set(f"{n} deleghe" if n else "nessuna delega")
        if self._aperta:
            self._filtra()

    def voci(self) -> list[str]:
        """Testi attualmente mostrati nella tendina."""
        return [t for t, _, _ in self._visibili]

    def aperta(self) -> bool:
        return self._aperta

    def piva_visibile(self) -> bool:
        return bool(self.riga_piva.winfo_manager())

    def aggiungi(self, nome: str, cf: str, piva: str | None = None) -> bool:
        """Aggiunge un soggetto; False se il C.F. è già tra i scelti."""
        cf = (cf or "").strip().upper()
        if not cf or any(s.cf == cf for s in self.scelti):
            return False
        if piva is None:
            piva = self._pive.get(cf, "")
        self.scelti.append(Soggetto(nome or cf, cf, piva))
        self._ridisegna()
        return True

    def imposta(self, nome: str, cf: str, piva: str | None = None) -> None:
        """Sostituisce la scelta con un solo soggetto (menu «Usa in...» della tab Deleghe)."""
        self._chiudi()
        self.scelti = []
        self.aggiungi(nome, cf, piva)
        self._ridisegna()

    def aggiungi_tutte(self) -> None:
        for nome, cf in self._opzioni:
            self.aggiungi(nome, cf)

    def svuota(self) -> None:
        self.scelti = []
        self._ridisegna()

    def rimuovi(self, indice: int) -> None:
        if 0 <= indice < len(self.scelti):
            del self.scelti[indice]
            self._ridisegna()

    def rimuovi_selezionati(self) -> None:
        togliere = {int(i) for i in self.lista.selection()}
        self.scelti = [s for i, s in enumerate(self.scelti) if i not in togliere]
        self._ridisegna()

    def soggetti(self, obbligatorio: bool = True):
        """Soggetti scelti, oppure None dopo aver mostrato l'avviso. Senza scelte, il testo
        scritto nella ricerca vale se corrisponde a una sola delega o è un C.F./P.IVA valido.
        Con un solo soggetto vale la P.IVA del campo, altrimenti quella di ciascuna delega.
        Con `obbligatorio=False` e nulla di scelto né scritto torna un soggetto vuoto
        (l'utenza di accesso, senza cliente), senza avviso."""
        if not self.scelti:
            testo = self.nome_var.get().strip()
            if not testo and not obbligatorio:
                return [Soggetto("", "", "")]
            if not testo:
                messagebox.showwarning("Soggetto non scelto",
                                       "Cerca un nominativo e sceglilo dall'elenco, oppure "
                                       "inserisci un C.F./P.IVA.")
                return None
            esatti = [o for o in self._opzioni if o[0].casefold() == testo.casefold()]
            trovati = esatti or filtra_opzioni(self._opzioni, testo)
            if len(trovati) == 1:
                nome, cf = trovati[0]
            else:
                try:
                    cf = normalizza_cf(testo)
                except ValueError:
                    messagebox.showerror("Errore", "Nominativo non riconosciuto: scegli un nome "
                                                   "dall'elenco delle deleghe, oppure inserisci "
                                                   "un C.F./P.IVA valido.")
                    return None
                nome = next((t for t, c in self._opzioni if c == cf), cf)
            self.aggiungi(nome, cf)
            self.nome_var.set("")
        if len(self.scelti) == 1:
            return [self.scelti[0]._replace(piva=self.piva_var.get().strip())]
        return list(self.scelti)

    # -- interni

    def _ridisegna(self) -> None:
        self.lista.delete(*self.lista.get_children())
        for i, s in enumerate(self.scelti):
            self.lista.insert("", tk.END, iid=str(i), values=(s.nome, s.cf),
                              tags=("dispari" if i % 2 else "pari",))
        n = len(self.scelti)
        self.lista.configure(height=max(1, min(n, _SCELTI_MAX)))
        if n > _SCELTI_MAX:
            self._barra_scelti.grid(row=0, column=1, sticky="ns", pady=(1, 0))
        else:
            self._barra_scelti.grid_forget()
        if n:
            self.riquadro.grid(row=1, column=0, sticky="ew", pady=(6, 0))
            self.contatore_scelti_var.set(
                f"{n} soggett{'o' if n == 1 else 'i'}  ·  doppio clic o Canc per toglierne uno")
        else:
            self.riquadro.grid_remove()
        if n == 1:
            self.piva_var.set(self.scelti[0].piva)
            self.riga_piva.grid(row=2, column=0, sticky="w", pady=(4, 0))
        else:
            self.riga_piva.grid_remove()

    def _doppio_clic(self, event) -> None:
        riga = self.lista.identify_row(event.y)
        if riga:
            self.rimuovi(int(riga))

    def _aggiorna_segnaposto(self) -> None:
        if self.nome_var.get():
            self._segnaposto.place_forget()
        else:
            self._segnaposto.place(x=4, rely=0.5, anchor="w")

    def _svuota_ricerca(self) -> None:
        self.nome_var.set("")
        self._chiudi()
        self.entry_nome.focus_set()

    def _filtra(self, event=None) -> None:
        if event is not None and event.keysym in _TASTI_NAVIGAZIONE + ("Return",):
            return
        testo = self.nome_var.get()
        if not testo.strip():
            self._visibili = []
            self._chiudi()
            return
        gia = {s.cf for s in self.scelti}
        trovate = [o for o in filtra_opzioni(self._opzioni, testo) if o[1] not in gia]
        self._visibili = [(t, c, False) for t, c in trovate]
        try:
            cf = normalizza_cf(testo)
        except ValueError:
            cf = ""
        if cf and cf not in gia and all(c != cf for _, c in self._opzioni):
            self._visibili.append((f"Usa {cf} (non tra le deleghe)", cf, True))
        self.contatore_var.set(f"{len(trovate)} di {len(self._opzioni)} deleghe" if trovate
                               else "Nessuna delega trovata")
        self._popola()
        self._apri()

    def _popola(self) -> None:
        self.albero.delete(*self.albero.get_children())
        for i, (testo, cf, mano) in enumerate(self._visibili):
            tag = "mano" if mano else ("dispari" if i % 2 else "pari")
            self.albero.insert("", tk.END, iid=str(i), values=(testo, "" if mano else cf),
                               tags=(tag,))
        n = len(self._visibili)
        self.albero.configure(height=max(1, min(n, _RIGHE_MAX)))
        if n > _RIGHE_MAX:
            self._barra.grid(row=0, column=1, sticky="ns", pady=(1, 0))
        else:
            self._barra.grid_forget()
        self._evid = -1
        if n == 1:
            self._evidenzia(0)

    def _evidenzia(self, i: int) -> None:
        self._evid = i
        if 0 <= i < len(self._visibili):
            self.albero.selection_set(str(i))
            self.albero.see(str(i))
        else:
            self.albero.selection_remove(*self.albero.selection())

    def _apri(self) -> None:
        self.update_idletasks()
        x = self.riga_ricerca.winfo_rootx()
        y = self.entry_nome.winfo_rooty() + self.entry_nome.winfo_height() + 2
        larghezza = max(self.riga_ricerca.winfo_width(), 320)
        self.tendina.update_idletasks()
        altezza = self.tendina.winfo_reqheight()
        self.tendina.geometry(f"{larghezza}x{altezza}+{x}+{y}")
        if not self._aperta:
            self.tendina.deiconify()
            self.tendina.lift()
        self._aperta = True

    def _chiudi(self) -> None:
        if self._aperta:
            self.tendina.withdraw()
        self._aperta = False

    def _chiudi_se_fuori(self) -> None:
        try:
            dove = self.focus_get()
        except (KeyError, tk.TclError):
            dove = None
        if dove is not self.entry_nome:
            self._chiudi()

    def _finestra_mossa(self, event) -> None:
        # Il binding resta sulla finestra: se il selettore è già stato distrutto (per esempio
        # a fine test), winfo_toplevel() non trova più il widget.
        try:
            if not self.winfo_exists() or not self._aperta:
                return
            se_stesso = event.widget is self.winfo_toplevel()
        except tk.TclError:
            return
        if se_stesso:
            self._chiudi()

    def _scegli_indice(self, i: int) -> None:
        if 0 <= i < len(self._visibili):
            testo, cf, mano = self._visibili[i]
            self.aggiungi(cf if mano else testo, cf)
            self.nome_var.set("")
            self._chiudi()
            self.entry_nome.focus_set()

    # -- eventi

    def _giu(self, _event=None):
        if not self._aperta and self.nome_var.get().strip():
            self._filtra()
        if self._visibili:
            self._evidenzia(min(self._evid + 1, len(self._visibili) - 1))
        return "break"

    def _su(self, _event=None):
        if self._visibili and self._evid > 0:
            self._evidenzia(self._evid - 1)
        return "break"

    def _invio(self, _event=None):
        if self._evid >= 0:
            self._scegli_indice(self._evid)
        elif len(self._visibili) == 1:
            self._scegli_indice(0)
        return "break"

    def _esc(self, _event=None):
        self._chiudi()
        return "break"

    def _al_passaggio(self, event) -> None:
        riga = self.albero.identify_row(event.y)
        if riga and int(riga) != self._evid:
            self._evidenzia(int(riga))

    def _clic(self, event) -> None:
        riga = self.albero.identify_row(event.y)
        if riga:
            self._scegli_indice(int(riga))
