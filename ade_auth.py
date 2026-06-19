"""
ade_auth.py — Autenticazione al portale AdE "Fatture e Corrispettivi" (nuovo login).

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
  radio `tipoincaricante`:
    incaricoDiretto       -> "Me stesso"            (profilo 2)
    incaricoDelega        -> "Delega diretta"       (profilo 1, default)
    incaricoIntermediario -> "Studio / intermediario" (profilo 3)
  select `incaricante`, input `cfDelegante` (CF cliente), bottone "Procedi".

Espone una sola API:

    autentica(creds, backend="browser") -> AuthResult

con due backend:
  - "browser"  : Playwright Chromium (affidabile, gestisce la SPA/JS; default).
  - "requests" : flusso ForgeRock via sole richieste HTTP (leggero ma fragile).

In caso di problema solleva AuthError(step, dettaglio).
"""

from __future__ import annotations

__version__ = "0.01 alpha"

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


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
PROFILO_ME_STESSO = 3        # opero sul mio CF

_PROFILO_TIPOINCARICANTE = {
    PROFILO_STUDIO_CLIENTE: "incaricoDelega",
    PROFILO_STUDIO_CASSETTO: "incaricoDiretto",
    PROFILO_ME_STESSO: "incaricoDiretto",
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
    cf_cliente: str = ""     # CF del cliente delegante (profili 1/3)
    piva: str = ""           # P.IVA dell'utenza di lavoro da attivare
    profilo: int = 1         # 1=Delega diretta  2=Me stesso  3=Studio associato


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
               note: list | None = None) -> AuthResult:
    """Step finale comune: token B2B, header, disclaimer."""
    xb2bcookie, xtoken = _ottieni_token(s)
    headers = _build_headers(xb2bcookie, xtoken)
    s.headers.update(headers)
    _accetta_disclaimer(s, headers)
    return AuthResult(
        session=s, headers=headers, xb2bcookie=xb2bcookie, xtoken=xtoken,
        utenza=utenza or "", backend=backend, note=note or [],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Backend BROWSER (Playwright)
# ─────────────────────────────────────────────────────────────────────────────

def _autentica_browser(creds: Creds, headless: bool = False,
                        timeout_ms: int = 180_000,
                        log=print) -> AuthResult:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        raise AuthError(
            "dipendenze",
            "Playwright non installato. Premi 'Installa dipendenze' nella GUI "
            "oppure esegui:  pip install playwright  &&  playwright install chromium",
        )

    note: list[str] = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=headless)
        except Exception as exc:
            raise AuthError(
                "browser",
                f"Impossibile avviare Chromium ({exc}). Esegui: playwright install chromium",
            )
        context = browser.new_context(user_agent=_UA, ignore_https_errors=True)
        page = context.new_page()
        page.set_default_timeout(30_000)

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
            _wizard_browser(page, creds, log)

            # 5) Attendo l'arrivo naturale su Fatture & Corrispettivi (anche se
            #    completi a mano la scelta utenza nella finestra del browser).
            log("Attendo l'accesso a Fatture e Corrispettivi...")
            _attendi_app_cons(page, timeout_ms, log, note)

            s = _session_da_browser(context)
        finally:
            browser.close()

    return _finalizza(s, "browser", creds.piva, note)


def _seleziona_tab_entratel(page, log) -> None:
    """
    Seleziona la scheda 'Fisconline/Entratel' (default della pagina è SPID).
    La pagina è una SPA: le tab compaiono dopo il load e un eventuale banner cookie
    può intercettare i click. Si usano attese + chiusura banner + click multipli
    (normale, force, dispatch JS).
    """
    from playwright.sync_api import TimeoutError as PWTimeout

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
            for clicker in (
                lambda: tab.click(timeout=3000),
                lambda: tab.click(timeout=3000, force=True),
                lambda: tab.dispatch_event("click"),
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


def _wizard_browser(page, creds: Creds, log) -> None:
    """
    Wizard "Configura l'utenza di lavoro" — è MULTI-STEP (form separati, ognuno con il
    suo 'Procedi'). Procede a ciclo gestendo, su ciascuna schermata:
      - select #incaricante (studio): il VALORE è un JSON, si seleziona per ETICHETTA
        (es. "12345678901-000");
      - scelta "per chi operare" (Incaricato / Delegato per singolo soggetto);
      - input #cfDelegante (CF del cliente);
      - bottoni Procedi / Conferma.
    Salva il DOM di ogni step in _debug_wizard_stepN.html per rifinire i selettori.
    Se incontra uno step che non sa gestire, si ferma e lascia completare a mano.
    """
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
            return  # accesso completato (F&C o dashboard post-wizard)

        try:
            page.wait_for_function(has_primary, timeout=15_000)
        except Exception:
            return  # nessun wizard (utenza unica) o già oltre

        conferma = _btn_visibile(page, "Conferma")
        procedi = _btn_visibile(page, "Procedi")

        # Riepilogo finale: c'è solo Conferma (niente Procedi visibile).
        if conferma is not None and procedi is None:
            try:
                conferma.click()
                log("Riepilogo confermato.")
            except Exception:
                log("⚠️  Bottone 'Conferma' non cliccabile: confermalo nel browser.")
                return
        else:
            sel = page.locator("#incaricante")
            incaricante_vis = sel.count() and sel.first.is_visible()
            if incaricante_vis:
                # form-step-2: studio + "per chi operare" + CF cliente.
                _select_incaricante(page, creds.cfstudio, log)
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
            else:
                # form-step-1: tipo utenza "Me stesso" / "Incaricato".
                _scegli_tipoutenza(page, creds.profilo)

            if not _click_btn(page, ("Procedi", "Avanti", "Prosegui")):
                if conferma is not None:
                    try:
                        conferma.click()
                    except Exception:
                        log("⚠️  Impossibile avanzare: completa lo step nel browser.")
                        return
                else:
                    _dump_html(page, f"_debug_wizard_step{step}.html")
                    log("⚠️  Nessun bottone per avanzare: completa lo step nel browser "
                        "(salvato _debug_wizard_step%d.html)." % step)
                    return

        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(800)

        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:
            page.wait_for_timeout(1500)


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


def _session_da_browser(context) -> requests.Session:
    """Costruisce una requests.Session con i cookie del browser."""
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Connection": "keep-alive"})
    for c in context.cookies():
        s.cookies.set(c["name"], c["value"],
                      domain=c.get("domain", "").lstrip("."),
                      path=c.get("path", "/"))
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Backend REQUESTS (ForgeRock, best-effort)
# ─────────────────────────────────────────────────────────────────────────────

def _autentica_requests(creds: Creds, log=print) -> AuthResult:
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Connection": "keep-alive"})

    # 1) GET pagina di login per leggere i campi nascosti ForgeRock correnti
    log("Carico la pagina di login SAM...")
    try:
        r = s.get(SAM_LOGIN_URL, verify=False, timeout=30)
    except requests.RequestException as exc:
        raise AuthError("login-get", f"Pagina di login non raggiungibile: {exc}")

    hidden = dict(re.findall(
        r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', r.text))
    for k in ("goto", "gotoOnFail", "SunQueryParamsString", "encoded",
              "gx_charset", "newpost"):
        hidden.setdefault(k, "")

    payload = {
        **hidden,
        "IDToken1": creds.nomeutente,
        "IDToken2": creds.password,
        "IDToken3": creds.pin,
    }

    # 2) POST credenziali sul punto di autenticazione ForgeRock
    log("Invio le credenziali Entratel...")
    try:
        r = s.post(SAM_LOGIN_URL, data=payload, verify=False, timeout=30,
                   allow_redirects=True)
    except requests.RequestException as exc:
        raise AuthError("login-post", f"Invio credenziali fallito: {exc}")

    if "iampe.agenziaentrate.gov.it" in r.url:
        msg = ""
        m = re.search(r'class="[^"]*alert-danger[^"]*"[^>]*>(.*?)<', r.text, re.S)
        if m:
            msg = re.sub(r"\s+", " ", m.group(1)).strip()
        raise AuthError(
            "login",
            msg or "Credenziali rifiutate dal SAM, oppure il flusso richiede "
                   "passaggi JS non riproducibili via requests: usa il backend 'browser'.",
        )

    # 3) Wizard scelta utenza di lavoro (InstradamentofcWeb)
    log("Seleziono l'utenza di lavoro...")
    _wizard_requests(s, creds)

    # 4) Token + header
    log("Ottengo i token di servizio...")
    return _finalizza(s, "requests", creds.piva)


def _wizard_requests(s: requests.Session, creds: Creds) -> None:
    """Invio best-effort dei parametri del wizard di instradamento."""
    tipo = _PROFILO_TIPOINCARICANTE.get(creds.profilo, "incaricoDelega")
    incaricante = f"{creds.cfstudio}-000" if creds.cfstudio else ""
    try:
        s.get(WIZARD_URL, verify=False, timeout=30)
    except requests.RequestException:
        return
    data = {
        "tipoincaricante": tipo,
        "incaricante": incaricante,
        "cfDelegante": creds.cf_cliente if creds.profilo == PROFILO_STUDIO_CLIENTE else "",
        "sceltapiva": creds.piva,
    }
    try:
        s.post(WIZARD_URL, data={k: v for k, v in data.items() if v},
               verify=False, timeout=30)
    except requests.RequestException:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# API pubblica
# ─────────────────────────────────────────────────────────────────────────────

def autentica(creds: Creds, backend: str = "browser",
              headless: bool = False, log=print) -> AuthResult:
    """
    Esegue l'autenticazione completa al portale AdE e restituisce un AuthResult
    con sessione e header pronti per le chiamate /cons/cons-services/rs/...

    backend:
      "browser"  -> Playwright (default, affidabile; headless opzionale)
      "requests" -> sole richieste HTTP (leggero ma fragile)

    Solleva AuthError(step, dettaglio) in caso di fallimento.
    """
    if backend == "requests":
        return _autentica_requests(creds, log=log)
    if backend == "browser":
        return _autentica_browser(creds, headless=headless, log=log)
    raise AuthError("config", f"Backend sconosciuto: {backend!r} (usa 'browser' o 'requests').")
