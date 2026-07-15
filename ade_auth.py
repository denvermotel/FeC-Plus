# FeC-Plus - v0.03 alpha
"""
ade_auth.py - Autenticazione al portale AdE "Fatture e Corrispettivi".

L'Agenzia delle Entrate ha sostituito il vecchio login Liferay
(ivaservizi.../portale/home, campi _58_login/_58_pin) con il portale
SAM/IAM ForgeRock:

    https://iampe.agenziaentrate.gov.it/sam/UI/Login?realm=/agenziaentrate&goto=...

Campi credenziali Entratel/Fisconline (tab "Fisconline/Entratel", #tab-4):
    IDToken1 = Nome utente Entratel (T...) / Codice fiscale Fisconline   (#username-fo-ent)
    IDToken2 = Password                                                  (#password-fo-ent-1)
    IDToken3 = PIN                                                        (#pin-fo-ent)

Dopo il login si passa dal wizard di scelta utenza di lavoro:
    https://ivaservizi.agenziaentrate.gov.it/instr/InstradamentofcWeb/wizard
  radio `tipoincaricante` (vedi `_PROFILO_TIPOINCARICANTE`):
    incaricoDelega        -> Studio, delega diretta di un cliente (profilo 1, default)
    incaricoDiretto       -> Studio, cassetto proprio o "Me stesso" (profili 2/3)
    incaricoIntermediario -> Azienda, legale rappresentante/incaricato (profilo 4,
                              ipotesi non ancora verificata dal vivo)
  select `incaricante`, input `cfDelegante` (CF cliente/azienda), bottone "Procedi".

Espone una sola API:

    autentica(creds, backend="browser") -> AuthResult

con due backend:
  - "browser"  : Playwright Chromium (affidabile, gestisce la SPA/JS; default).
  - "requests" : login via API JSON /api/login/telematico + scelta utenza via API
                 REST di instradamento (leggero, senza browser).

In caso di problema solleva AuthError(step, dettaglio).
"""

from __future__ import annotations

__version__ = "0.03 alpha"

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning
from urllib3.util.retry import Retry

urllib3.disable_warnings(InsecureRequestWarning)


def _nuova_sessione() -> requests.Session:
    """
    Sessione `requests` con retry automatico sugli errori di connessione.

    L'AdE, su sessioni lunghe (es. download annuale spezzato in più blocchi),
    talvolta chiude lato server una connessione keep-alive riutilizzata
    ('RemoteDisconnected'); senza un adapter di retry questo fa fallire la
    richiesta anche se un secondo tentativo andrebbe a buon fine.
    """
    s = requests.Session()
    retry = Retry(
        total=3, connect=3, read=3, backoff_factor=1,
        status_forcelist=(502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Costanti
# ─────────────────────────────────────────────────────────────────────────────

IVASERVIZI = "https://ivaservizi.agenziaentrate.gov.it"
IAMPE = "https://iampe.agenziaentrate.gov.it"

# URL della pagina di login SAM con redirect verso Fatture & Corrispettivi (FATBTB).
_GOTO = "https://portale.agenziaentrate.gov.it:443/PortaleWeb/home?to=FATBTB"
SAM_LOGIN_URL = (
    f"{IAMPE}/sam/UI/Login?realm=/agenziaentrate&goto={quote(_GOTO, safe='')}"
)

# Entry point del servizio di consultazione (innesca il wizard di instradamento).
CONS_WEB = f"{IVASERVIZI}/cons/cons-web/"
WIZARD_URL = f"{IVASERVIZI}/instr/InstradamentofcWeb/wizard"

# Login "telematico" dell'AdE: una POST JSON {username,password,pin} che imposta i
# cookie SSO (SIAMPE…). Sostituisce il vecchio form ForgeRock /sam/UI/Login.
LOGIN_API = f"{IAMPE}/api/login/telematico"

# Portale: la GET a initPortale (anche se risponde 501) "scambia" i cookie SAM con i
# cookie SSO del portale (LtpaToken2, cookieutentee0194, AE, portaleCookie, domain
# .agenziaentrate.gov.it) → SENZA questi l'app di instradamento risponde 403.
PORTALE = "https://portale.agenziaentrate.gov.it"
PORTALE_HOME = f"{PORTALE}/PortaleWeb/home?to=FATBTB"
PORTALE_INIT = f"{PORTALE}/portale-rest/rs/initPortale"

# App di instradamento (scelta utenza di lavoro): home SPA + API REST.
INSTR_HOME = f"{IVASERVIZI}/instr/InstradamentofcWeb/home"
INSTR_REST = f"{IVASERVIZI}/instr/instradamento-fatture-rest/rs"

# x-appl: identificativo applicativo SOGEI richiesto dalle API di instradamento;
# viene restituito da initLight nell'header omonimo. Valore di fallback osservato
# in cattura (può cambiare a un redeploy dell'AdE → rieseguire la cattura HAR).
X_APPL_DEFAULT = "18a9b6e6f69bb94b5e12f67cb2d54c4f791f5b12"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ─────────────────────────────────────────────────────────────────────────────
# Profili dell'utenza di lavoro (nuovo wizard "Configura l'utenza di lavoro").
#
# Flusso reale (login Fisconline di un titolare dello studio):
#   1) si sceglie il "soggetto che ti ha incaricato" (select #incaricante):
#      il proprio CF (Me stesso) oppure lo studio associato, il cui valore usa il
#      suffisso "-000" (es. "12345678901-000", -000 = sede).
#   2) si sceglie "per chi operare" (radio name=tipoincaricante):
#      incaricoDiretto       -> "Incaricato"  (cassetto dello studio stesso)
#      incaricoDelega        -> "Delegato per singolo soggetto" (un cliente)  [default]
#      incaricoDelegaMassivo -> delega massiva
#      incaricoIntermediario -> intermediario
#   3) per la delega si inserisce il CF del cliente (#cfDelegante).
#   4) "Procedi" -> pagina "Riepilogo e conferma" -> "Conferma".
PROFILO_STUDIO_CLIENTE = 1   # studio -> cliente (delegato per singolo soggetto)
PROFILO_STUDIO_CASSETTO = 2  # studio -> cassetto dello studio (incaricato)
PROFILO_ME_STESSO = 3        # opero sul mio CF (o libero professionista)
PROFILO_AZIENDA = 4          # azienda: uso lo stesso meccanismo del cassetto studio
                             # (incaricato/incaricoDiretto), con l'incarico cercato
                             # per il CF dell'azienda invece che per il CF studio
                             # (confermato con una cattura HAR dal vivo)

_PROFILO_TIPOINCARICANTE = {
    PROFILO_STUDIO_CLIENTE: "incaricoDelega",
    PROFILO_STUDIO_CASSETTO: "incaricoDiretto",
    PROFILO_ME_STESSO: "incaricoDiretto",
    PROFILO_AZIENDA: "incaricoDiretto",
}


def unix_time() -> str:
    """Timestamp Unix in millisecondi (stringa), usato come cache-buster."""
    return str(int(datetime.now(tz=timezone.utc).timestamp() * 1000))


def _accesso_completato(url: str) -> bool:
    """
    True se l'URL indica che l'accesso è andato a buon fine e l'utenza di lavoro
    è stata selezionata. Stati validi (post-login/post-wizard):
      - app di consultazione F&C:           .../cons/cons-web/...
      - dashboard post-wizard instradamento: .../instr/InstradamentofcWeb/home
    NB: la pagina del wizard (.../InstradamentofcWeb/wizard) NON è uno stato finale.
    """
    if "ivaservizi.agenziaentrate.gov.it" not in url:
        return False
    if "/cons/cons-web" in url:
        return True
    if "InstradamentofcWeb/home" in url:
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Tipi
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Creds:
    """Credenziali Entratel/Fisconline + dati dell'utenza di lavoro da selezionare."""
    nomeutente: str          # IDToken1 (Nome utente Entratel T... o CF Fisconline)
    pin: str                 # IDToken3
    password: str            # IDToken2
    cfstudio: str = ""       # CF/P.IVA dello studio (incaricante), per profili 2/3
    cf_cliente: str = ""     # CF del cliente delegante (profilo 1) o dell'azienda (profilo 4)
    piva: str = ""           # P.IVA dell'utenza di lavoro da attivare
    profilo: int = 1         # 1=Studio->cliente  2=Studio->cassetto  3=Me stesso  4=Azienda


@dataclass
class AuthResult:
    """Esito dell'autenticazione: sessione requests pronta per le chiamate API."""
    session: requests.Session
    headers: dict
    xb2bcookie: str
    xtoken: str
    utenza: str = ""
    backend: str = ""
    note: list = field(default_factory=list)
    piva: str = ""                                  # P.IVA dell'utenza di lavoro attiva
    piva_disponibili: list = field(default_factory=list)  # elenco P.IVA del CF (PIva[])
    denominazione: str = ""                         # denominazione dell'utenza di lavoro
    conservazione: bool = False                     # adesione conservazione dati fattura


class AuthError(RuntimeError):
    """Errore di autenticazione con indicazione dello step fallito."""

    def __init__(self, step: str, dettaglio: str = ""):
        self.step = step
        self.dettaglio = dettaglio
        super().__init__(f"[{step}] {dettaglio}".strip())


# ─────────────────────────────────────────────────────────────────────────────
# Header / token comuni ai due backend
# ─────────────────────────────────────────────────────────────────────────────

_SECURITY_HEADERS = {
    "x-xss-protection": "1; mode=block",
    "strict-transport-security": "max-age=16070400; includeSubDomains",
    "x-content-type-options": "nosniff",
    "x-frame-options": "deny",
}


def _ottieni_token(s: requests.Session) -> tuple[str, str]:
    """Aderisce al servizio e recupera gli header x-b2bcookie / x-token."""
    s.get(f"{IVASERVIZI}/ser/api/fatture/v1/ul/me/adesione/stato/", verify=False)
    r = s.get(
        f"{IVASERVIZI}/cons/cons-services/sc/tokenB2BCookie/get?v={unix_time()}",
        headers=_SECURITY_HEADERS,
        verify=False,
    )
    xb2bcookie = r.headers.get("x-b2bcookie", "")
    xtoken = r.headers.get("x-token", "")
    if not xb2bcookie or not xtoken:
        raise AuthError(
            "token",
            "x-b2bcookie/x-token non ottenuti: la sessione non risulta autenticata "
            "oppure l'utenza di lavoro non è stata selezionata.",
        )
    return xb2bcookie, xtoken


def _build_headers(xb2bcookie: str, xtoken: str) -> dict:
    """Header completi per le chiamate API /cons/cons-services/rs/..."""
    return {
        "Host": "ivaservizi.agenziaentrate.gov.it",
        "Referer": f"{IVASERVIZI}/cons/cons-web/?v={unix_time()}",
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "DNT": "1",
        **_SECURITY_HEADERS,
        "x-b2bcookie": xb2bcookie,
        "x-token": xtoken,
        "User-Agent": _UA,
    }


def _accetta_disclaimer(s: requests.Session, headers: dict) -> None:
    """Accetta le condizioni d'uso del servizio di consultazione (best-effort)."""
    try:
        s.get(
            f"{IVASERVIZI}/cons/cons-services/rs/disclaimer/accetta?v={unix_time()}",
            headers=_SECURITY_HEADERS,
            verify=False,
        )
    except requests.RequestException:
        pass


def _finalizza(s: requests.Session, backend: str, utenza: str,
               note: list | None = None, piva: str = "",
               piva_disponibili: list | None = None,
               denominazione: str = "", conservazione: bool = False) -> AuthResult:
    """Step finale comune: token B2B, header, disclaimer."""
    xb2bcookie, xtoken = _ottieni_token(s)
    headers = _build_headers(xb2bcookie, xtoken)
    s.headers.update(headers)
    _accetta_disclaimer(s, headers)
    return AuthResult(
        session=s, headers=headers, xb2bcookie=xb2bcookie, xtoken=xtoken,
        utenza=utenza or "", backend=backend, note=note or [],
        piva=piva or "", piva_disponibili=piva_disponibili or [],
        denominazione=denominazione or "", conservazione=bool(conservazione),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Backend BROWSER (Playwright)
# ─────────────────────────────────────────────────────────────────────────────

def _autentica_browser(creds: Creds, headless: bool = False,
                        timeout_ms: int = 180_000,
                        log=print, capture_dir: str | None = None,
                        scegli_piva=None) -> AuthResult:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout  # type: ignore
    except ImportError:
        raise AuthError(
            "dipendenze",
            "Playwright non installato. Premi 'Installa dipendenze' nella GUI "
            "oppure esegui:  pip install playwright  &&  playwright install chromium",
        )

    note: list[str] = []
    har_path = log_path = None
    if capture_dir:
        har_path, log_path = _capture_paths(capture_dir)
        log(f"Cattura traffico ATTIVA → {har_path}")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=headless)
        except Exception as exc:
            raise AuthError(
                "browser",
                f"Impossibile avviare Chromium ({exc}). Esegui: playwright install chromium",
            )
        ctx_kwargs = dict(user_agent=_UA, ignore_https_errors=True)
        if har_path:
            ctx_kwargs.update(record_har_path=har_path, record_har_mode="full",
                              record_har_content="embed")
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        page.set_default_timeout(30_000)
        if log_path:
            _attach_network_log(page, log_path, log)
            note.append(f"Cattura traffico salvata in {har_path}")

        try:
            # 1) Pagina di login SAM
            log("Apro la pagina di login dell'Agenzia delle Entrate...")
            page.goto(SAM_LOGIN_URL, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass

            # 2) Tab Fisconline/Entratel: dal vivo è attiva SPID di default e i campi
            #    Entratel sono nascosti finché non si seleziona la scheda.
            _seleziona_tab_entratel(page, log)

            log("Inserisco le credenziali Entratel...")
            page.fill("#username-fo-ent", creds.nomeutente)
            page.fill("#password-fo-ent-1", creds.password)
            page.fill("#pin-fo-ent", creds.pin)

            log("Invio il login...")
            page.locator('#tab-4 button[type="submit"]').first.click()

            # 3) Attendo di lasciare il dominio di login (iampe)
            try:
                page.wait_for_url(lambda u: "iampe.agenziaentrate.gov.it" not in u,
                                  timeout=60_000)
            except PWTimeout:
                err = _estrai_errore_login(page)
                raise AuthError("login", err or "Login non completato (credenziali errate?)")

            # 4) Wizard scelta utenza di lavoro (best-effort; NON forzo navigazioni:
            #    forzare /cons/cons-web prima della conferma fa rimbalzare al login).
            log("Configuro l'utenza di lavoro...")
            piva_scelta, piva_disponibili = _wizard_browser(
                page, creds, log, headless=headless, scegli_piva=scegli_piva)

            # 5) Attendo l'arrivo naturale su Fatture & Corrispettivi (anche se
            #    completi a mano la scelta utenza nella finestra del browser).
            log("Attendo l'accesso a Fatture e Corrispettivi...")
            _attendi_app_cons(page, timeout_ms, log, note)

            s = _session_da_browser(context)
        finally:
            # context.close() prima di browser.close() per flushare l'HAR su disco.
            try:
                context.close()
            except Exception:
                pass
            browser.close()

    if har_path:
        log(f"\n📦 Cattura login salvata:\n   HAR: {har_path}\n   LOG: {log_path}")
    piva_finale = piva_scelta or creds.piva
    # denominazione ricavabile dall'opzione P.IVA scelta nella tendina (PIva[]);
    # conservazione non è disponibile per questa via (la ricava fec_anagrafica).
    denom = ""
    for p in piva_disponibili:
        if str((p or {}).get("piva", "")).strip() == piva_finale:
            denom = str((p or {}).get("denominazione", "") or "").strip()
            break
    return _finalizza(s, "browser", piva_finale, note, piva=piva_finale,
                      piva_disponibili=piva_disponibili, denominazione=denom)


def _seleziona_tab_entratel(page, log) -> None:
    """
    Seleziona la scheda 'Fisconline/Entratel' (default della pagina è SPID).
    La pagina è una SPA: le tab compaiono dopo il load e un eventuale banner cookie
    può intercettare i click. Si usano attese + chiusura banner + click multipli
    (normale, force, dispatch JS).
    """
    from playwright.sync_api import TimeoutError as PWTimeout  # type: ignore

    _chiudi_banner(page)

    def _tab_locator():
        for getter in (
            lambda: page.get_by_role("tab", name=re.compile("Entratel", re.I)),
            lambda: page.get_by_role("link", name=re.compile("Entratel", re.I)),
            lambda: page.locator(
                'a[href="#tab-4"], [aria-controls="tab-4"], [data-bs-target="#tab-4"]'),
            lambda: page.get_by_text(re.compile(r"Fisconline\s*/?\s*Entratel", re.I)),
        ):
            try:
                loc = getter()
                if loc.count():
                    return loc.first
            except Exception:
                continue
        return None

    for attempt in range(6):
        # già visibile? fatto.
        try:
            if page.locator("#username-fo-ent").first.is_visible():
                return
        except Exception:
            pass

        tab = _tab_locator()
        if tab is not None:
            tab_loc = tab  # binding non-None: le lambda lo catturano senza il tipo Optional
            for clicker in (
                lambda: tab_loc.click(timeout=3000),
                lambda: tab_loc.click(timeout=3000, force=True),
                lambda: tab_loc.dispatch_event("click"),
            ):
                try:
                    tab.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass
                try:
                    clicker()
                    break
                except Exception:
                    continue

        try:
            page.wait_for_selector("#username-fo-ent", state="visible", timeout=4000)
            return
        except PWTimeout:
            _chiudi_banner(page)
            page.wait_for_timeout(700)

    _dump_html(page, "_debug_login.html")
    raise AuthError(
        "login",
        "Impossibile selezionare la scheda Fisconline/Entratel "
        "(salvato _debug_login.html per individuare il selettore corretto).",
    )


def _chiudi_banner(page) -> None:
    """Chiude eventuali banner cookie/consenso che intercettano i click."""
    for name in ("Accetta tutti", "Accetta", "Accetto", "Acconsento", "OK",
                 "Ho capito", "Chiudi", "Continua"):
        try:
            btn = page.get_by_role("button", name=re.compile(name, re.I))
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=1500)
                return
        except Exception:
            continue


def _attendi_app_cons(page, timeout_ms: int, log, note: list) -> None:
    """
    Polla finché si approda all'app Fatture & Corrispettivi (/cons/cons-web),
    senza forzare navigazioni. Funziona anche se l'utente completa il wizard a mano.
    """
    import time
    deadline = time.time() + timeout_ms / 1000
    avvisato = False
    last_logged = ""
    next_url_log = 0.0
    while time.time() < deadline:
        try:
            url = page.url
        except Exception:
            url = ""
        if _accesso_completato(url):
            log("Accesso a Fatture e Corrispettivi rilevato.")
            page.wait_for_timeout(1500)
            return
        if not avvisato:
            log("Se i passaggi non procedono da soli, completa la scelta utenza "
                "nella finestra del browser (NON chiuderla).")
            avvisato = True
            note.append("Wizard completato (eventualmente) a mano nel browser.")
        # log periodico dell'URL corrente (diagnostica)
        now = time.time()
        if now >= next_url_log and url and url != last_logged:
            log(f"   …pagina attuale: {url}")
            last_logged = url
            next_url_log = now + 8
        page.wait_for_timeout(1000)
    try:
        note.append(f"Timeout: ultima pagina {page.url}")
    except Exception:
        note.append("Timeout in attesa di /cons/cons-web.")


def _estrai_errore_login(page) -> str:
    for sel in (".alert-danger", ".text-danger", "#errorMessage", ".message-error"):
        try:
            loc = page.locator(sel)
            if loc.count():
                txt = loc.first.inner_text().strip()
                if txt:
                    return txt
        except Exception:
            continue
    return ""


_RE_PIVA = re.compile(r"\d{11}")


def _trova_select_piva(page):
    """
    Trova nel DOM la tendina (native `<select>`) di scelta P.IVA dello step corrente.
    La distingue da `#incaricante`: è un select VISIBILE, diverso da #incaricante, con
    opzioni che contengono una P.IVA (11 cifre) o con id/name che cita "piva".
    Ritorna `(locator_select, opzioni)` con opzioni = [(value, testo), ...], o (None, []).
    """
    try:
        selects = page.locator("select")
        n = selects.count()
    except Exception:
        return None, []
    for i in range(n):
        s = selects.nth(i)
        try:
            if not s.is_visible():
                continue
        except Exception:
            continue
        sid = (s.get_attribute("id") or "")
        sname = (s.get_attribute("name") or "")
        if sid == "incaricante":
            continue
        opzioni: list[tuple[str, str]] = []
        try:
            opts = s.locator("option")
            for j in range(opts.count()):
                o = opts.nth(j)
                testo = (o.inner_text() or "").strip()
                val = (o.get_attribute("value") or "").strip()
                opzioni.append((val, testo))
        except Exception:
            continue
        blob = " ".join(f"{v} {t}" for v, t in opzioni)
        if _RE_PIVA.search(blob) or "piva" in sid.lower() or "piva" in sname.lower():
            return s, opzioni
    return None, []


def _piva_da_opzioni(opzioni: list) -> list:
    """Estrae [{piva, denominazione, _value, _label}] dalle opzioni della tendina,
    scartando i placeholder ("Seleziona…") privi di P.IVA."""
    out = []
    for val, testo in opzioni:
        m = _RE_PIVA.search(val) or _RE_PIVA.search(testo)
        if not m:
            continue
        piva = m.group(0)
        denom = _RE_PIVA.sub("", testo).strip(" -–—\t·|")
        out.append({"piva": piva, "denominazione": denom, "_value": val, "_label": testo})
    return out


def _seleziona_opzione_piva(select_loc, opzioni: list, target: str) -> bool:
    """Seleziona nella tendina l'opzione corrispondente a `target` (P.IVA): prima per
    value, poi per etichetta. Ritorna True se selezionata."""
    for val, testo in opzioni:
        if target and (target in val or target in testo):
            for tentativo in (lambda: select_loc.select_option(value=val),
                              lambda: select_loc.select_option(label=testo)):
                try:
                    tentativo()
                    return True
                except Exception:
                    continue
    return False


def _gestisci_piva_browser(page, creds: Creds, headless: bool, scegli_piva, log,
                           stato: dict) -> str:
    """
    Gestisce lo step con la tendina di scelta P.IVA nel wizard browser (multi-P.IVA).

    Legge le P.IVA dalla tendina e decide quale attivare:
      - P.IVA indicata dall'utente (`creds.piva`) → selezionata direttamente;
      - una sola P.IVA → automatica;
      - più P.IVA senza indicazione: se headless si chiede con `scegli_piva` (popup),
        altrimenti (finestra visibile) si lascia scegliere a mano nel browser.
    Ritorna: "none" (nessuna tendina qui), "selected" (scelta fatta, si può avanzare),
    "manual" (scelta lasciata all'utente nel browser: non avanzare in automatico).
    Aggiorna `stato['disponibili']` e `stato['scelta']`.
    """
    select_loc, opzioni = _trova_select_piva(page)
    if select_loc is None:
        return "none"
    disponibili = _piva_da_opzioni(opzioni)
    lista = [d["piva"] for d in disponibili]
    if not lista:
        return "none"
    stato["disponibili"] = disponibili
    log(f"Menù P.IVA rilevato: {lista}")

    target = ""
    if creds.piva:
        target = creds.piva
        if target not in lista:
            log(f"⚠️  La P.IVA indicata {target} non è tra quelle del menù {lista}; "
                "la seleziono comunque se presente.")
    elif len(lista) == 1:
        target = lista[0]
    elif headless:
        # Finestra non visibile: l'utente non può usare la tendina → popup.
        if scegli_piva is not None:
            try:
                target = (scegli_piva(list(disponibili)) or "").strip()
            except Exception as exc:
                log(f"⚠️  Selettore P.IVA fallito ({exc}).")
        if not target:
            target = lista[0]
            log(f"⚠️  Nessuna P.IVA scelta: uso la prima ({target}).")
    else:
        # Finestra visibile: lascia scegliere a mano nella tendina del browser.
        log("ℹ️  Più P.IVA: seleziona quella desiderata nel menù a tendina del browser.")
        return "manual"

    if _seleziona_opzione_piva(select_loc, opzioni, target):
        stato["scelta"] = target
        log(f"P.IVA selezionata nel menù: {target}")
        return "selected"
    log(f"⚠️  Non sono riuscito a selezionare {target} nella tendina.")
    return "selected" if headless else "manual"


def _wizard_browser(page, creds: Creds, log, headless: bool = False,
                    scegli_piva=None) -> tuple[str, list]:
    """
    Wizard "Configura l'utenza di lavoro": è MULTI-STEP (form separati, ognuno con il
    suo 'Procedi'). Procede a ciclo gestendo, su ciascuna schermata:
      - select #incaricante (studio): il VALORE è un JSON, si seleziona per ETICHETTA
        (es. "12345678901-000");
      - scelta "per chi operare" (Incaricato / Delegato per singolo soggetto);
      - input #cfDelegante (CF del cliente);
      - tendina di scelta P.IVA quando il CF ne ha più d'una (vedi _gestisci_piva_browser);
      - bottoni Procedi / Conferma.
    Se incontra uno step che non sa gestire, si ferma e lascia completare a mano.

    Ritorna `(piva_scelta, piva_disponibili)`: la P.IVA attivata (letta/selezionata dalla
    tendina) e l'elenco delle P.IVA del CF. In scelta manuale, `piva_scelta` resta "".
    """
    stato: dict = {"scelta": "", "disponibili": []}

    def _esito():
        return stato["scelta"], stato["disponibili"]

    # La pagina è una SPA: il markup di TUTTI gli step è sempre nel DOM (Conferma
    # compresa), mostrato/nascosto via CSS. Quindi si agisce SOLO su ciò che è VISIBILE
    # e si avanza cliccando il bottone primario visibile (Procedi o, al riepilogo, Conferma).
    has_primary = ("() => [...document.querySelectorAll('button')].some("
                   "b => b.offsetParent && /Procedi|Conferma/i.test(b.textContent))")

    for step in range(1, 12):
        try:
            url = page.url
        except Exception:
            url = ""
        if _accesso_completato(url):
            return _esito()  # accesso completato (F&C o dashboard post-wizard)

        try:
            page.wait_for_function(has_primary, timeout=15_000)
        except Exception:
            return _esito()  # nessun wizard (utenza unica) o già oltre

        conferma = _btn_visibile(page, "Conferma")
        procedi = _btn_visibile(page, "Procedi")

        # Riepilogo finale: c'è solo Conferma (niente Procedi visibile).
        if conferma is not None and procedi is None:
            try:
                conferma.click()
                log("Riepilogo confermato.")
            except Exception:
                log("⚠️  Bottone 'Conferma' non cliccabile: confermalo nel browser.")
                return _esito()
        else:
            sel = page.locator("#incaricante")
            incaricante_vis = sel.count() and sel.first.is_visible()
            if incaricante_vis:
                # form-step-2: studio/azienda + "per chi operare" + CF cliente.
                # Per il profilo Azienda l'incarico va cercato per il CF dell'azienda
                # (cf_cliente), non per il CF studio: è l'azienda stessa ad aver dato
                # l'incarico all'utente collegato.
                cf_incarico = (creds.cf_cliente if creds.profilo == PROFILO_AZIENDA
                              else creds.cfstudio)
                _select_incaricante(page, cf_incarico, log)
                try:
                    page.wait_for_selector('input[name="tipoincaricante"]', timeout=4000)
                except Exception:
                    pass
                _scegli_per_chi_operare(page, creds.profilo)
                if creds.profilo == PROFILO_STUDIO_CLIENTE and creds.cf_cliente:
                    try:
                        page.wait_for_selector("#cfDelegante", state="visible", timeout=4000)
                    except Exception:
                        pass
                    try:
                        page.locator("#cfDelegante").first.fill(creds.cf_cliente)
                    except Exception:
                        pass
                # la tendina P.IVA può popolarsi nello stesso form dopo il CF delegante
                if _gestisci_piva_browser(page, creds, headless, scegli_piva, log, stato) \
                        == "manual":
                    return _esito()
            else:
                # step "tipo utenza" OPPURE step con la tendina di scelta P.IVA.
                esito_piva = _gestisci_piva_browser(page, creds, headless, scegli_piva,
                                                    log, stato)
                if esito_piva == "manual":
                    return _esito()
                if esito_piva == "none":
                    _scegli_tipoutenza(page, creds.profilo)

            if not _click_btn(page, ("Procedi", "Avanti", "Prosegui")):
                if conferma is not None:
                    try:
                        conferma.click()
                    except Exception:
                        log("⚠️  Impossibile avanzare: completa lo step nel browser.")
                        return _esito()
                else:
                    _dump_html(page, f"_debug_wizard_step{step}.html")
                    log("⚠️  Nessun bottone per avanzare: completa lo step nel browser "
                        "(salvato _debug_wizard_step%d.html)." % step)
                    return _esito()

        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(800)

        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:
            page.wait_for_timeout(1500)

    return _esito()


def _select_incaricante(page, cfstudio: str, log) -> bool:
    """
    Seleziona lo studio nel select #incaricante. Il VALORE dell'option è un JSON
    ({"incaricante":{"cf":"...","sede":"000"}}), quindi si abbina per CF cercando
    nell'etichetta o nel value e si seleziona per ETICHETTA esatta.
    """
    sel = page.locator("#incaricante")
    if not sel.count():
        return False
    # già selezionato?
    try:
        cur = sel.first.input_value()
        if cfstudio in cur:
            return True
    except Exception:
        pass
    try:
        options = sel.locator("option")
        for i in range(options.count()):
            opt = options.nth(i)
            label = (opt.inner_text() or "").strip()
            value = opt.get_attribute("value") or ""
            if label and (cfstudio in label or cfstudio in value):
                sel.first.select_option(label=label)
                return True
    except Exception:
        pass
    for kw in (f"{cfstudio}-000", cfstudio):
        try:
            sel.first.select_option(label=kw)
            return True
        except Exception:
            continue
    log(f"⚠️  Studio '{cfstudio}' non trovato nel menù; selezionalo a mano nel browser.")
    return False


def _scegli_per_chi_operare(page, profilo: int) -> bool:
    """
    Seleziona la modalità operativa (radio name=tipoincaricante). I radio sono
    Bootstrap "form-check" visivamente nascosti, quindi serve check(force=True);
    in fallback si clicca la label testuale.
    """
    tipo = _PROFILO_TIPOINCARICANTE.get(profilo, "incaricoDelega")
    r = page.locator(f'input[name="tipoincaricante"][value="{tipo}"]')
    if r.count():
        # già selezionato?
        try:
            if r.first.is_checked():
                return True
        except Exception:
            pass
        for action in (lambda: r.first.check(force=True),
                       lambda: r.first.click(force=True)):
            try:
                action()
                return True
            except Exception:
                continue
    testo = {
        PROFILO_STUDIO_CLIENTE: r"delegato per singolo soggetto",
        PROFILO_STUDIO_CASSETTO: r"^\s*incaricato\s*$",
        PROFILO_AZIENDA: r"^\s*incaricato\s*$",
        PROFILO_ME_STESSO: r"me stesso",
    }.get(profilo)
    if testo:
        try:
            loc = page.get_by_text(re.compile(testo, re.I))
            if loc.count():
                loc.first.click()
                return True
        except Exception:
            pass
    return False


def _scegli_tipoutenza(page, profilo: int) -> bool:
    """Step 1: 'Me stesso' / 'Incaricato' (radio Bootstrap nascosti -> force)."""
    val = "meStesso" if profilo == PROFILO_ME_STESSO else "incaricato"
    r = page.locator(f'input[name="tipoutenza"][value="{val}"]')
    if r.count():
        try:
            if r.first.is_checked():
                return True
        except Exception:
            pass
        for action in (lambda: r.first.check(force=True),
                       lambda: r.first.click(force=True)):
            try:
                action()
                return True
            except Exception:
                continue
    return False


def _btn_visibile(page, pattern: str):
    """Primo <button> VISIBILE e abilitato il cui testo combacia con pattern, o None."""
    try:
        btns = page.get_by_role("button", name=re.compile(pattern, re.I))
        for i in range(btns.count()):
            b = btns.nth(i)
            try:
                if b.is_visible() and b.is_enabled():
                    return b
            except Exception:
                continue
    except Exception:
        pass
    return None


def _click_btn(page, labels: tuple) -> bool:
    """Clicca il primo bottone VISIBILE che combacia con una delle etichette."""
    for label in labels:
        b = _btn_visibile(page, label)
        if b is not None:
            try:
                b.click()
                return True
            except Exception:
                continue
    return False


def _dump_html(page, filename: str) -> None:
    try:
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page.content())
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Cattura traffico login (per ricostruire il flusso del backend requests)
# ─────────────────────────────────────────────────────────────────────────────

def _capture_paths(capture_dir: str) -> tuple[str, str]:
    """Crea `capture_dir` e ritorna i percorsi (HAR, LOG) con timestamp."""
    import os
    os.makedirs(capture_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(capture_dir, f"capture_login_{ts}")
    return base + ".har", base + ".log"


def _attach_network_log(page, log_path: str, log) -> None:
    """
    Registra richieste/risposte rilevanti del login (ForgeRock SAM, wizard di
    instradamento, token B2B) su `log_path` (con i body POST, per ricostruire i
    payload ForgeRock) e una riga sintetica in console. Solo per il backend browser.

    ⚠️ Il file contiene credenziali in chiaro: resta in `_materiale/` (fuori da Git).
    """
    interessanti = ("iampe.agenziaentrate.gov.it", "InstradamentofcWeb",
                    "tokenB2BCookie", "/sam/")

    def _rilevante(url: str) -> bool:
        return any(k in url for k in interessanti)

    def _scrivi(riga: str) -> None:
        try:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(riga + "\n")
        except Exception:
            pass

    def on_request(req):
        try:
            if not _rilevante(req.url):
                return
            riga = f"→ {req.method} {req.url}"
            try:
                post = req.post_data
            except Exception:
                post = None
            if post:
                riga += f"\n    body: {post}"
            _scrivi(riga)
            log(f"   ↪ {req.method} {req.url[:110]}")
        except Exception:
            pass

    def on_response(resp):
        try:
            if not _rilevante(resp.url):
                return
            ct = resp.headers.get("content-type", "")
            _scrivi(f"← {resp.status} {resp.url}  [{ct}]")
        except Exception:
            pass

    page.on("request", on_request)
    page.on("response", on_response)
    _scrivi(f"# Cattura login AdE - {datetime.now().isoformat()}")


def cattura_har_navigazione(nomeutente: str, pin: str, password: str,
                            capture_dir: str = "_materiale",
                            prefisso: str = "capture_debug", hint: str = "",
                            log=print) -> tuple[str, str]:
    """
    Cattura HAR a navigazione libera (strumento investigativo generico, usato
    per scoprire endpoint AdE non ancora noti).

    Apre Chromium VISIBILE con registrazione HAR attiva, precompila (best-effort)
    il login Entratel e poi lascia la navigazione ALL'UTENTE: completare il login,
    l'eventuale scelta utenza e visitare le pagine da tracciare. La cattura termina
    **chiudendo il browser**. Ritorna (har_path, log_path).

    `prefisso` distingue i file per scenario d'uso (es. "capture_deleghe"); `hint`,
    se dato, è scritto come riga guida in testa al file di log (es. l'URL da
    raggiungere per l'investigazione in corso).

    Differenza dalla «🎥 Cattura login» di Test Login (`_attach_network_log` sopra):
    là il browser si chiude da solo a login completato e il log filtra solo il
    traffico di autenticazione; qui si registra TUTTO il traffico
    `agenziaentrate.gov.it` finché il browser resta aperto. ⚠️ HAR e log contengono
    credenziali/dati reali: restano in `_materiale/` (fuori da Git), non condividerli.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise AuthError("dipendenze",
                        "La cattura HAR richiede Playwright: pip install playwright "
                        "e poi «playwright install chromium».")
    import os

    os.makedirs(capture_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(capture_dir, f"{prefisso}_{ts}")
    har_path, log_path = base + ".har", base + ".log"

    def _scrivi(riga: str) -> None:
        try:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(riga + "\n")
        except Exception:
            pass

    def _rilevante(url: str) -> bool:
        # Tutto il traffico AdE, esclusi gli asset statici che affollerebbero il log
        # (nell'HAR c'è comunque tutto).
        if "agenziaentrate.gov.it" not in url:
            return False
        return not url.lower().split("?")[0].endswith(
            (".js", ".css", ".png", ".gif", ".jpg", ".svg", ".woff", ".woff2", ".ico"))

    def _attach_log_completo(page) -> None:
        def on_request(req):
            try:
                if not _rilevante(req.url):
                    return
                riga = f"→ {req.method} {req.url}"
                try:
                    post = req.post_data
                except Exception:
                    post = None
                if post:
                    riga += f"\n    body: {post}"
                _scrivi(riga)
            except Exception:
                pass

        def on_response(resp):
            try:
                if _rilevante(resp.url):
                    ct = resp.headers.get("content-type", "")
                    _scrivi(f"← {resp.status} {resp.url}  [{ct}]")
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", on_response)

    _scrivi(f"# Cattura navigazione AdE - {datetime.now().isoformat()}")
    if hint:
        _scrivi(f"# {hint}")
    log(f"Cattura traffico ATTIVA → {har_path}")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=False)
        except Exception as exc:
            raise AuthError("browser", f"Impossibile avviare Chromium ({exc}). "
                            "Esegui: playwright install chromium")
        context = browser.new_context(user_agent=_UA, ignore_https_errors=True,
                                      record_har_path=har_path, record_har_mode="full",
                                      record_har_content="embed")
        try:
            page = context.new_page()
            page.set_default_timeout(30_000)
            _attach_log_completo(page)
            context.on("page", _attach_log_completo)   # anche pagine/tab aperte dopo

            log("Apro la pagina di login (compilazione campi best-effort)...")
            page.goto(SAM_LOGIN_URL, wait_until="domcontentloaded")
            try:
                _seleziona_tab_entratel(page, log)
                page.fill("#username-fo-ent", nomeutente)
                page.fill("#password-fo-ent-1", password)
                page.fill("#pin-fo-ent", pin)
                log("Credenziali precompilate: premi tu il pulsante di accesso.")
            except Exception:
                log("⚠️  Precompilazione non riuscita: inserisci le credenziali a mano.")

            if hint:
                log(f"👉 {hint}")
            log("Naviga liberamente. CHIUDI IL BROWSER per terminare e salvare la cattura.")
            try:
                while context.pages:
                    context.pages[0].wait_for_timeout(500)
            except Exception:
                pass                        # browser chiuso dall'utente
        finally:
            # context.close() prima di browser.close() per flushare l'HAR su disco.
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass

    log(f"\n📦 Cattura salvata:\n   HAR: {har_path}\n   LOG: {log_path}")
    log("⚠️  I file contengono credenziali/dati reali: non condividerli.")
    return har_path, log_path


def _session_da_browser(context) -> requests.Session:
    """Costruisce una requests.Session con i cookie del browser."""
    s = _nuova_sessione()
    s.headers.update({"User-Agent": _UA, "Connection": "keep-alive"})
    for c in context.cookies():
        s.cookies.set(c["name"], c["value"],
                      domain=c.get("domain", "").lstrip("."),
                      path=c.get("path", "/"))
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Backend REQUESTS (ForgeRock, best-effort)
# ─────────────────────────────────────────────────────────────────────────────

def _autentica_requests(creds: Creds, log=print, scegli_piva=None) -> AuthResult:
    """
    Login "solo requests" ricostruito dal traffico reale del portale:
      1) POST {IAMPE}/api/login/telematico con JSON {username,password,pin} → cookie SSO.
      2) bootstrap della sessione di instradamento (portale → InstradamentofcWeb/home).
      3) wizard scelta utenza via API REST (initLight/wizardTemplate/procediWizard/
         setUserChoice), che attiva l'utenza di lavoro.
      4) token B2B/header (comune al backend browser).
    """
    s = _nuova_sessione()
    s.headers.update({"User-Agent": _UA, "Connection": "keep-alive"})

    # 1) Login via API JSON dell'AdE (sostituisce il vecchio form ForgeRock).
    log("Carico la pagina di login...")
    try:
        s.get(SAM_LOGIN_URL, verify=False, timeout=30)  # warm-up: cookie iniziali
    except requests.RequestException:
        pass

    log("Invio le credenziali al login telematico AdE...")
    login_headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": IAMPE,
        "Referer": SAM_LOGIN_URL,
        "User-Agent": _UA,
    }
    payload = {"username": creds.nomeutente, "password": creds.password, "pin": creds.pin}
    try:
        r = s.post(LOGIN_API, data=json.dumps(payload), headers=login_headers,
                   verify=False, timeout=30)
    except requests.RequestException as exc:
        raise AuthError("login-post", f"Login telematico non raggiungibile: {exc}")

    if r.status_code != 200 or "SIAMPE" not in s.cookies.get_dict():
        msg = ""
        try:
            j = r.json()
            msg = j.get("error") or j.get("message") or ""
        except ValueError:
            msg = (r.text or "").strip()[:200]
        raise AuthError(
            "login",
            msg or f"Login rifiutato (HTTP {r.status_code}): credenziali, PIN o "
                   "nome utente non validi.",
        )
    log("Login riuscito (cookie SSO ottenuti).")

    # 2) Bootstrap: lo scambio cookie SAM→portale (initPortale, anche se 501) minta i
    #    cookie SSO del portale (LtpaToken2…) necessari ad autorizzare l'instradamento.
    log("Inizializzo la sessione del portale...")
    for url in (PORTALE_HOME, f"{PORTALE_INIT}?v={unix_time()}&to=FATBTB", INSTR_HOME):
        try:
            s.get(url, verify=False, timeout=30)
        except requests.RequestException:
            pass
    if "LtpaToken2" not in s.cookies.get_dict():
        log("   ⚠️  LtpaToken2 non ottenuto dal portale: l'instradamento potrebbe dare 403.")

    # 3) Wizard scelta utenza di lavoro via API REST. Ritorna la P.IVA attivata
    #    (ricavata automaticamente dal CF) e l'elenco delle P.IVA del soggetto.
    log("Configuro l'utenza di lavoro...")
    piva_scelta, piva_disponibili, denom, cons = _wizard_requests(
        s, creds, log, scegli_piva=scegli_piva)

    # 4) Ingresso nell'app di consultazione: /dp/PI2FC imposta il cookie FATSC (sessione
    #    cons) che, insieme al B2BCookie ottenuto da setUserChoice, autorizza il token B2B.
    log("Apro l'app di consultazione...")
    for url in (f"{IVASERVIZI}/dp/PI2FC", CONS_WEB):
        try:
            s.get(url, headers={"User-Agent": _UA}, verify=False, timeout=30)
        except requests.RequestException:
            pass
    if "FATSC" not in s.cookies.get_dict():
        log("   ⚠️  FATSC non ottenuto: il token B2B potrebbe fallire.")

    # 5) Token + header
    log("Ottengo i token di servizio...")
    piva_finale = piva_scelta or creds.piva
    return _finalizza(s, "requests", piva_finale, piva=piva_finale,
                      piva_disponibili=piva_disponibili,
                      denominazione=denom, conservazione=cons)


def _instr_headers(x_appl: str) -> dict:
    """Header per le API di instradamento (scelta utenza)."""
    return {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": IVASERVIZI,
        "Referer": WIZARD_URL,
        "User-Agent": _UA,
        "x-appl": x_appl,
    }


def _incarichi(template: dict) -> list:
    """Estrae richiestaIncarichi.incarichi[] dal template (lista, eventualmente vuota)."""
    return (((template or {}).get("richiestaIncarichi") or {}).get("incarichi")) or []


def _dump_debug(filename: str, text: str) -> None:
    """Scrive `text` in un file di debug accanto al modulo (best-effort)."""
    try:
        import os
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text or "")
    except Exception:
        pass


def _trova_incarico(template: dict, cfstudio: str) -> dict | None:
    """
    Individua, fra gli incarichi restituiti da wizardTemplate, quello dello studio
    indicato (match su incaricante.cf). Ritorna l'oggetto incarico, o None.
    """
    incarichi = _incarichi(template)
    if not incarichi:
        return None
    if cfstudio:
        for inc in incarichi:
            if (inc.get("incaricante") or {}).get("cf") == cfstudio:
                return inc
    return incarichi[0] if len(incarichi) == 1 else None


def _elenco_piva(disponibili: list) -> list[str]:
    """Estrae le sole stringhe P.IVA (non vuote) dall'array PIva[] del wizard."""
    return [str((p or {}).get("piva", "")).strip()
            for p in (disponibili or []) if (p or {}).get("piva")]


def _risolvi_piva(disponibili: list, piva_preferita: str, scegli_piva, log) -> str:
    """
    Ricava la P.IVA dell'utenza di lavoro dall'elenco `PIva[]` restituito dal wizard.

    Regola richiesta:
      - se l'utente ha INDICATO una P.IVA (`piva_preferita`) → si usa quella (ci si
        fida dell'input; se non è tra quelle del CF si avvisa ma la si usa comunque);
      - altrimenti, se il CF ha UNA sola P.IVA → scelta automatica;
      - altrimenti (PIÙ P.IVA e nessuna indicata) → si chiede all'utente con
        `scegli_piva(disponibili)` (finestra popup in GUI). Senza callback / senza
        risposta valida si usa la prima e si annota un avviso.
    Ritorna la P.IVA scelta (stringa), o `piva_preferita` se l'elenco è vuoto
    (es. profilo «Me stesso», dove il wizard non restituisce PIva[]).
    """
    lista = _elenco_piva(disponibili)
    if piva_preferita:
        if lista and piva_preferita not in lista:
            log(f"⚠️  P.IVA indicata {piva_preferita} non tra quelle del CF {lista}: "
                "la uso comunque come richiesto.")
        return piva_preferita
    if len(lista) == 1:
        log(f"P.IVA rilevata automaticamente dal CF: {lista[0]}")
        return lista[0]
    if len(lista) > 1:
        if scegli_piva is not None:
            try:
                scelta = (scegli_piva(list(disponibili)) or "").strip()
            except Exception as exc:
                log(f"⚠️  Selettore P.IVA fallito ({exc}); uso la prima.")
                scelta = ""
            if scelta and scelta in lista:
                log(f"P.IVA selezionata: {scelta}")
                return scelta
        log(f"⚠️  Il CF ha più P.IVA {lista}: uso la prima ({lista[0]}). "
            "Indica la P.IVA desiderata per sceglierne un'altra.")
        return lista[0]
    return piva_preferita


def _wizard_requests(s: requests.Session, creds: Creds, log=print,
                     scegli_piva=None) -> tuple[str, list, str, bool]:
    """
    Replica via API REST la scelta dell'utenza di lavoro fatta dal wizard SPA:
      GET  initLight        → header x-appl da riusare
      GET  wizardTemplate   → elenco incarichi disponibili
      POST procediWizard    → tipoutenza, poi delega/incarico (risposta: PIva[])
      POST setUserChoice    → conferma; attiva l'utenza (200 = ok).
    Il campo `incaricante` è l'oggetto incarico serializzato in JSON (come fa la SPA).

    Ritorna `(piva_scelta, piva_disponibili, denominazione, conservazione)`: la P.IVA
    attivata (ricavata dal CF, via `scegli_piva` se il CF ne ha più d'una), l'elenco
    grezzo `PIva[]`, e denominazione/conservazione lette dalla risposta di setUserChoice.
    """
    x_appl = X_APPL_DEFAULT

    # init: aggiorna x-appl dall'header di risposta
    try:
        r = s.get(f"{INSTR_REST}/initLight?v={unix_time()}",
                  headers=_instr_headers(x_appl), verify=False, timeout=30)
        nuovo = r.headers.get("x-appl")
        if nuovo:
            x_appl = nuovo
        log(f"   initLight HTTP {r.status_code}, x-appl {'da risposta' if nuovo else 'fallback'}")
    except requests.RequestException as exc:
        log(f"   ⚠️  initLight non raggiungibile: {exc}")

    # template con gli incarichi disponibili
    template = {}
    try:
        r = s.get(f"{INSTR_REST}/wizardTemplate?v={unix_time()}",
                  headers=_instr_headers(x_appl), verify=False, timeout=30)
        log(f"   wizardTemplate HTTP {r.status_code}")
        try:
            template = r.json()
        except ValueError:
            _dump_debug("_debug_wizardTemplate_raw.txt", r.text)
            log(f"   ⚠️  wizardTemplate non JSON (HTTP {r.status_code}, "
                "salvato _debug_wizardTemplate_raw.txt)")
    except requests.RequestException as exc:
        log(f"   ⚠️  wizardTemplate non raggiungibile: {exc}")

    tipoutenza = "soloPerMe" if creds.profilo == PROFILO_ME_STESSO else "incaricato"
    tipoincaricante = _PROFILO_TIPOINCARICANTE.get(creds.profilo, "incaricoDelega")

    # step 1: scelta del tipo di utenza. La risposta contiene anch'essa gli incarichi:
    # la usiamo come fonte di fallback se wizardTemplate non li avesse restituiti.
    try:
        r = s.post(f"{INSTR_REST}/procediWizard?v={unix_time()}",
                   headers=_instr_headers(x_appl),
                   data=json.dumps({"tipoutenza": tipoutenza}), verify=False, timeout=30)
        log(f"   procediWizard(tipoutenza) HTTP {r.status_code}")
        if not _incarichi(template):
            try:
                template = r.json()
            except ValueError:
                pass
    except requests.RequestException as exc:
        log(f"   ⚠️  procediWizard non raggiungibile: {exc}")

    # Me stesso: nessun incarico, si conferma direttamente il proprio CF.
    if creds.profilo == PROFILO_ME_STESSO:
        resp = _setuserchoice(s, x_appl, {"tipoutenza": "soloPerMe", "cf": creds.nomeutente}, log)
        denom, cons = _anagrafica_da_utente(resp)
        return creds.piva, [], denom, cons

    # Studio/Azienda: serve l'oggetto incarico corrispondente al CF di chi ha dato
    # l'incarico. Per l'Azienda l'incaricante è l'azienda stessa (cf_cliente), non
    # lo studio: stesso meccanismo del cassetto studio, solo con un altro CF.
    cf_incarico = creds.cf_cliente if creds.profilo == PROFILO_AZIENDA else creds.cfstudio
    incarico = _trova_incarico(template, cf_incarico)
    if incarico is None:
        disponibili = [(i.get("incaricante") or {}).get("cf", "?") for i in _incarichi(template)]
        _dump_debug("_debug_wizardTemplate.txt", json.dumps(template, indent=2, ensure_ascii=False))
        soggetto = "l'azienda" if creds.profilo == PROFILO_AZIENDA else "lo studio"
        raise AuthError(
            "utenza",
            f"Incarico per {soggetto} «{cf_incarico}» non trovato. "
            + (f"Incarichi disponibili (CF incaricante): {disponibili}. "
               if disponibili else
               "Nessun incarico restituito dal portale (template vuoto: possibile "
               "x-appl scaduto o sessione non valida; salvato _debug_wizardTemplate.txt). ")
            + "Verifica il CF indicato o completa col backend browser.",
        )
    incaricante_str = json.dumps(incarico, separators=(",", ":"), ensure_ascii=False)
    cf_lavoro = (creds.cf_cliente if creds.profilo in (PROFILO_STUDIO_CLIENTE, PROFILO_AZIENDA)
                else creds.cfstudio)

    base = {
        "tipoutenza": tipoutenza,
        "incaricante": incaricante_str,
        "tipoincaricante": tipoincaricante,
        "cfDelegante": cf_lavoro,
    }

    # step 2: procedi con delega/incarico. La risposta contiene `PIva[]`, l'elenco
    # delle P.IVA del soggetto: una sola → scelta automatica, più d'una → menù/scelta.
    piva_disponibili: list = []
    try:
        r = s.post(f"{INSTR_REST}/procediWizard?v={unix_time()}",
                   headers=_instr_headers(x_appl),
                   data=json.dumps({**base, "pIva": None}), verify=False, timeout=30)
        try:
            piva_disponibili = (r.json() or {}).get("PIva") or []
        except ValueError:
            log("   ⚠️  procediWizard(delega) non JSON: P.IVA non ricavata dal CF.")
    except requests.RequestException:
        pass

    piva_scelta = _risolvi_piva(piva_disponibili, creds.piva, scegli_piva, log)

    # Il campo `pIva` serve SOLO a disambiguare quando il CF ha più P.IVA: nel caso a
    # P.IVA unica il setUserChoice verificato in cattura NON lo include, quindi lo
    # omettiamo per non alterare il flusso funzionante. Con più P.IVA rifacciamo prima
    # un procediWizard con la P.IVA scelta (come la SPA alla conferma della tendina).
    multi = len(_elenco_piva(piva_disponibili)) > 1
    if multi and piva_scelta:
        try:
            s.post(f"{INSTR_REST}/procediWizard?v={unix_time()}",
                   headers=_instr_headers(x_appl),
                   data=json.dumps({**base, "pIva": piva_scelta}), verify=False, timeout=30)
        except requests.RequestException:
            pass

    # step 3: conferma definitiva della scelta (attiva l'utenza di lavoro).
    conferma = {**base, "cf": cf_lavoro}
    if multi and piva_scelta:
        conferma["pIva"] = piva_scelta
    resp = _setuserchoice(s, x_appl, conferma, log)

    denom, cons = _anagrafica_da_utente(resp)
    if not denom:  # fallback: denominazione dell'opzione P.IVA scelta (da PIva[])
        for p in piva_disponibili:
            if str((p or {}).get("piva", "")).strip() == piva_scelta:
                denom = str((p or {}).get("denominazione", "") or "").strip()
                break
    return piva_scelta, piva_disponibili, denom, cons


def _setuserchoice(s: requests.Session, x_appl: str, body: dict, log) -> dict:
    """POST setUserChoice; solleva AuthError se la scelta utenza non è accettata.
    Ritorna il JSON di risposta (contiene `utenteDiLavoro.partitaIva` con denominazione
    e opzioni di adesione), o {} se non JSON."""
    try:
        r = s.post(f"{INSTR_REST}/setUserChoice?v={unix_time()}",
                   headers=_instr_headers(x_appl), data=json.dumps(body),
                   verify=False, timeout=30)
    except requests.RequestException as exc:
        raise AuthError("utenza", f"Conferma utenza fallita: {exc}")
    if r.status_code != 200:
        msg = ""
        try:
            msg = r.json().get("error") or r.json().get("message") or ""
        except ValueError:
            msg = (r.text or "").strip()[:200]
        raise AuthError(
            "utenza",
            msg or f"Scelta utenza di lavoro non accettata (HTTP {r.status_code}).",
        )
    log("Utenza di lavoro attivata.")
    try:
        return r.json() or {}
    except ValueError:
        return {}


def _anagrafica_da_utente(resp: dict) -> tuple[str, bool]:
    """
    Estrae (denominazione, conservazione) dalla risposta di setUserChoice:
      denominazione = utenteDiLavoro.partitaIva.denominazione;
      conservazione = utenteDiLavoro.partitaIva.opzioni.datiFattura.attiva
                      (adesione alla conservazione dati fattura).
    """
    pi = (((resp or {}).get("utenteDiLavoro") or {}).get("partitaIva")) or {}
    denom = str(pi.get("denominazione", "") or "").strip()
    cons = bool((((pi.get("opzioni") or {}).get("datiFattura")) or {}).get("attiva", False))
    return denom, cons


# ─────────────────────────────────────────────────────────────────────────────
# API pubblica
# ─────────────────────────────────────────────────────────────────────────────

def autentica(creds: Creds, backend: str = "browser",
              headless: bool = False, log=print,
              capture_dir: str | None = None, scegli_piva=None) -> AuthResult:
    """
    Esegue l'autenticazione completa al portale AdE e restituisce un AuthResult
    con sessione e header pronti per le chiamate /cons/cons-services/rs/...

    backend:
      "browser"  -> Playwright (default, affidabile; headless opzionale)
      "requests" -> sole richieste HTTP (leggero ma fragile)

    capture_dir: se valorizzato (solo backend browser), registra il traffico di rete
      del login/wizard in `<capture_dir>/capture_login_<ts>.har` (HAR completo) e in un
      `.log` leggibile, per ricostruire il flusso ForgeRock nel backend requests.

    scegli_piva: callback opzionale `(disponibili: list[dict]) -> str` (entrambi i
      backend) invocata quando il CF ha più P.IVA e nessuna è stata indicata; deve
      restituire la P.IVA scelta. Nel backend browser è usata SOLO se headless (a
      finestra visibile la scelta si fa a mano nella tendina). Se una P.IVA è indicata
      viene selezionata direttamente; con una sola P.IVA la scelta è automatica.

    Solleva AuthError(step, dettaglio) in caso di fallimento.
    """
    if backend == "requests":
        return _autentica_requests(creds, log=log, scegli_piva=scegli_piva)
    if backend == "browser":
        return _autentica_browser(creds, headless=headless, log=log,
                                  capture_dir=capture_dir, scegli_piva=scegli_piva)
    raise AuthError("config", f"Backend sconosciuto: {backend!r} (usa 'browser' o 'requests').")


def seleziona_utenza(auth: AuthResult, creds: Creds, log=print,
                     scegli_piva=None) -> AuthResult:
    """
    Cambia utenza di lavoro RIUSANDO la sessione già autenticata di `auth` (come il
    «Cambia Utenza» del portale), senza rifare il login telematico. Riesegue il wizard
    REST di instradamento per il nuovo `creds.cf_cliente` e rifà i token B2B.

    Utile per operazioni massive su più deleghe con un solo accesso (aggiornamento
    anagrafica di tutti i clienti). Ritorna un nuovo AuthResult per la nuova utenza.
    Solleva AuthError se la scelta utenza non riesce.
    """
    s = auth.session
    piva_scelta, piva_disponibili, denom, cons = _wizard_requests(
        s, creds, log, scegli_piva=scegli_piva)
    # Rientro nell'app di consultazione (best-effort) e nuovi token per la nuova utenza.
    for url in (f"{IVASERVIZI}/dp/PI2FC", CONS_WEB):
        try:
            s.get(url, headers={"User-Agent": _UA}, verify=False, timeout=30)
        except requests.RequestException:
            pass
    piva_finale = piva_scelta or creds.piva
    return _finalizza(s, auth.backend or "requests", piva_finale, note=list(auth.note),
                      piva=piva_finale, piva_disponibili=piva_disponibili,
                      denominazione=denom, conservazione=cons)
