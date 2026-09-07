#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus - v0.04 dev
"""
fec_cli.py - Interfaccia a riga di comando per FeC-Plus, SENZA GUI.

Wrapper: esegue il login al portale «Fatture e Corrispettivi» dell'AdE (via ade_auth) e
scarica fatture/corrispettivi/bolli usando le funzioni di fec_download. La logica di
download resta in fec_download.py (libreria pura), l'autenticazione in ade_auth.py: qui si
fa solo il parsing degli argomenti e il «dispatch».

Sintassi:
    python fec_cli.py [ARGOMENTI DI ACCESSO] COMANDO [ARGOMENTI DEL COMANDO]

⚠️ SICUREZZA: le credenziali passano sulla riga di comando (visibili nella cronologia della
shell e nell'elenco dei processi). Per la password preferire «--password-env NOME_VAR», che
la legge da una variabile d'ambiente.

Esempi:
    python fec_cli.py --cf RSSMRA80A01H501U --pin 1234 --password segreta \\
        --cfstudio 01234567890 --cf-cliente 09876543210 \\
        emesse --dal 01012026 --al 31012026

    set FEC_PWD=segreta   &&   python fec_cli.py --cf ... --pin ... --password-env FEC_PWD \\
        --cf-cliente 09876543210 --piva 09876543210 \\
        corrispettivi --dal 2026-01-01 --al 2026-03-31
"""

from __future__ import annotations

__version__ = "0.04 dev"

import argparse
import os
import sys

import fec_deps

# Output UTF-8 anche su console Windows (cp1252) per evitare UnicodeEncodeError sui
# caratteri non-ASCII di help e log (« » → ✅ ❌ …).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _add_date_range(sp: argparse.ArgumentParser, fmt: str) -> None:
    sp.add_argument("--dal", required=True, help=f"Data inizio ({fmt})")
    sp.add_argument("--al", required=True, help=f"Data fine ({fmt})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fec_cli.py",
        description="FeC-Plus - download da «Fatture e Corrispettivi» AdE, da riga di comando.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--version", action="version", version=f"FeC-Plus {__version__}")

    # ── Argomenti di ACCESSO (comuni a tutti i comandi, prima del COMANDO) ──
    acc = parser.add_argument_group("accesso")
    # Non obbligatori a livello di parser: con «--backend sso» non servono affatto
    # (ci si autentica nel browser). La verifica è in `_verifica_accesso`, che dà un
    # errore mirato invece del messaggio generico di argparse.
    acc.add_argument("--cf",
                     help="CF Fisconline o nome utente Entratel (IDToken1). "
                          "Obbligatorio salvo «--backend sso»")
    acc.add_argument("--pin", help="PIN (IDToken3). Obbligatorio salvo «--backend sso»")
    pwd = parser.add_mutually_exclusive_group()
    pwd.add_argument("--password", help="Password (IDToken2)")
    pwd.add_argument("--password-env", metavar="VAR",
                     help="Nome della variabile d'ambiente da cui leggere la password")
    acc.add_argument("--cfstudio", default="",
                     help="CF dello studio incaricante (profili 1/2)")
    acc.add_argument("--cf-cliente", default="",
                     help="CF del cliente delegante, o dell'azienda per --profilo 4")
    acc.add_argument("--piva", default="", help="P.IVA dell'utenza di lavoro (massive/bolli)")
    acc.add_argument("--profilo", type=int, choices=(1, 2, 3, 4, 5), default=1,
                     help="1=studio→cliente, 2=cassetto studio, 3=me stesso/libero "
                          "professionista, 4=azienda, 5=delega diretta (soggetto in "
                          "--cf-cliente)")
    acc.add_argument("--backend", choices=("requests", "browser", "sso"), default="requests",
                     help="Backend di login. «sso» = SPID/CIE/CNS: apre il browser e "
                          "aspetti di autenticarti a mano (ignora --pin/--password)")
    acc.add_argument("--no-headless", dest="headless", action="store_false", default=True,
                     help="Mostra la finestra del browser (solo backend browser)")
    acc.add_argument("--dest", default=None,
                     help="Cartella di destinazione dei download (default: ./Download)")
    acc.add_argument("--includi-scartate-pa", dest="escludi_scartate_pa",
                     action="store_false", default=True,
                     help="Include anche le fatture rifiutate dalla P.A. (default: escluse)")
    acc.add_argument("--estrai-p7m", action="store_true", default=False,
                     help="Estrae l'XML dai file firmati .p7m al posto dell'originale "
                          "(richiede il pacchetto asn1crypto)")
    acc.add_argument("--csv-ade", action="store_true", default=False,
                     help="Genera anche il CSV dell'elenco nel formato «Esporta la "
                          "tabella» del portale AdE (solo per i comandi di download)")
    acc.add_argument("--dry-run", action="store_true",
                     help="Mostra cosa verrebbe eseguito, senza fare login né download")

    # ── COMANDI ──
    sub = parser.add_subparsers(dest="comando", required=True, metavar="COMANDO")

    _add_date_range(sub.add_parser("emesse", help="Fatture emesse"), "ggmmaaaa")

    sp = sub.add_parser("ricevute", help="Fatture ricevute")
    _add_date_range(sp, "ggmmaaaa")
    sp.add_argument("--tipo-data", type=int, choices=(1, 2), default=1,
                    help="1=ricerca per data ricezione (default), 2=per data emissione")

    _add_date_range(sub.add_parser("transfrontaliere-emesse",
                                   help="Transfrontaliere emesse"), "ggmmaaaa")
    _add_date_range(sub.add_parser("transfrontaliere-ricevute",
                                   help="Transfrontaliere ricevute"), "ggmmaaaa")
    _add_date_range(sub.add_parser("messe-a-disposizione",
                                   help="Fatture messe a disposizione"), "ggmmaaaa")

    spc = sub.add_parser("csv-fatture",
                         help="Solo il CSV formato AdE dell'elenco fatture "
                              "(nessun file fattura scaricato)")
    _add_date_range(spc, "ggmmaaaa")
    spc.add_argument("--tipo", default="emesse",
                     choices=("emesse", "ricevute_ricezione", "ricevute_emissione",
                              "trans_emesse", "trans_ricevute"),
                     help="Tipo di elenco da esportare")

    _add_date_range(sub.add_parser("massive-emesse",
                                   help="Richiesta massiva fatture emesse"), "aaaa-mm-gg")
    _add_date_range(sub.add_parser("massive-ricevute-emissione",
                                   help="Richiesta massiva ricevute (data emissione)"), "aaaa-mm-gg")
    _add_date_range(sub.add_parser("massive-ricevute-ricezione",
                                   help="Richiesta massiva ricevute (data ricezione)"), "aaaa-mm-gg")
    _add_date_range(sub.add_parser("massive-disposizione",
                                   help="Richiesta massiva fatture messe a disposizione"), "aaaa-mm-gg")
    _add_date_range(sub.add_parser("corrispettivi",
                                   help="Richiesta massiva corrispettivi"), "aaaa-mm-gg")

    spb = sub.add_parser("bolli", help="Bolli virtuali → riepilogo CSV (elenco A/B, importo, stato pagamento)")
    spb.add_argument("--trimestre", required=True, choices=("1", "2", "3", "4", "tutti"),
                     help="Trimestre singolo, o 'tutti' per l'intero anno")
    spb.add_argument("--anno", required=True, help="Anno (aaaa)")

    return parser


# Mappatura comando CLI → tipo di richiesta (chiavi del registro fec_queue.TIPI).
_CMD_TIPO = {
    "emesse": "emesse",
    "ricevute": "ricevute",
    "transfrontaliere-emesse": "trans_emesse",
    "transfrontaliere-ricevute": "trans_ricevute",
    "messe-a-disposizione": "messe_disposizione",
    "massive-emesse": "massive_emesse",
    "massive-ricevute-emissione": "massive_ricevute_emissione",
    "massive-ricevute-ricezione": "massive_ricevute_ricezione",
    "massive-disposizione": "massive_disposizione",
    "corrispettivi": "corrispettivi",
    "bolli": "bolli",
}


def _dispatch(args, auth, fq):
    """Instrada il comando a fec_queue.esegui_richiesta (spezzettamento periodi)."""
    # Export CSV AdE autonomo: non passa da fec_queue (nessun download di file),
    # ma da fec_utility, che interroga solo le liste.
    if args.comando == "csv-fatture":
        import fec_utility
        return fec_utility.elenco_fatture_csv_ade(
            auth, args.cf_cliente, args.piva, args.tipo, args.dal, args.al,
            dest_dir=args.dest)

    tipo = _CMD_TIPO.get(args.comando)
    if tipo is None:
        raise SystemExit(f"Comando sconosciuto: {args.comando}")
    spec = fq.TIPI[tipo]
    kw = {"cf_cliente": args.cf_cliente, "dest_dir": args.dest}
    if tipo == "ricevute":
        kw["tipo_data"] = args.tipo_data
    if spec.kind == "download":
        kw["escludi_scartate_pa"] = args.escludi_scartate_pa
        kw["estrai_p7m"] = args.estrai_p7m
        kw["csv_ade"] = args.csv_ade
    if spec.kind == "invio":
        kw["piva"] = args.piva
    if tipo == "bolli":
        kw.update(piva=args.piva, trimestre=args.trimestre, anno=args.anno)
    return fq.esegui_richiesta(auth, tipo, dal=getattr(args, "dal", None),
                               al=getattr(args, "al", None), **kw)


def _verifica_accesso(args) -> None:
    """Con i backend a credenziali (requests/browser) CF, PIN e password sono
    obbligatori; con «sso» non servono e vanno anzi ignorati."""
    if args.backend == "sso":
        return
    mancanti = [nome for nome, valore in (("--cf", args.cf), ("--pin", args.pin))
                if not valore]
    if args.password is None and not args.password_env:
        mancanti.append("--password (oppure --password-env)")
    if mancanti:
        raise SystemExit(
            "Argomenti obbligatori mancanti: " + ", ".join(mancanti)
            + f".\n   Con «--backend {args.backend}» servono le credenziali Entratel; "
              "per accedere con SPID/CIE usa «--backend sso».")


def _risolvi_password(args) -> str:
    if args.backend == "sso":
        return ""      # l'accesso avviene nel browser: nessuna password da passare
    if args.password is not None:
        return args.password
    val = os.environ.get(args.password_env or "", "")
    if not val:
        raise SystemExit(f"Variabile d'ambiente «{args.password_env}» vuota o assente.")
    return val


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    _verifica_accesso(args)
    password = _risolvi_password(args)

    if args.dry_run:
        print(f"[dry-run] comando: {args.comando}")
        print(f"  accesso : cf={args.cf or '-'} profilo={args.profilo} "
              f"backend={args.backend} headless={args.headless}")
        print(f"  soggetti: cf_cliente={args.cf_cliente!r} piva={args.piva!r} "
              f"cfstudio={args.cfstudio!r}")
        for k in ("dal", "al", "tipo", "tipo_data", "trimestre", "anno", "dest",
                  "escludi_scartate_pa", "estrai_p7m", "csv_ade"):
            if hasattr(args, k):
                print(f"  {k} = {getattr(args, k)!r}")
        print("  (login e download NON eseguiti)")
        return 0

    # Controllo dipendenze all'avvio.
    missing = fec_deps.find_missing()
    if missing["core"]:
        print("❌ Dipendenze richieste mancanti: " + ", ".join(missing["core"]),
              file=sys.stderr)
        print("   Installa con:  " + fec_deps.pip_install_hint(missing["core"]),
              file=sys.stderr)
        return 3
    if args.backend in ("browser", "sso") and "playwright" in missing["browser"]:
        quale = ("L'accesso con SPID/CIE" if args.backend == "sso"
                 else "Il backend «browser»")
        print(f"❌ {quale} richiede Playwright, che non è installato.", file=sys.stderr)
        print("   Usa «--backend requests» (credenziali Entratel) oppure installa Playwright:",
              file=sys.stderr)
        print("   " + fec_deps.pip_install_hint(["playwright"])
              + " && python -m playwright install chromium", file=sys.stderr)
        return 3
    if args.estrai_p7m and missing["p7m"]:
        print("❌ «--estrai-p7m» richiesto ma «asn1crypto» non è installato.", file=sys.stderr)
        print("   Installa con:  " + fec_deps.pip_install_hint(missing["p7m"]),
              file=sys.stderr)
        return 3

    from ade_auth import autentica, Creds, AuthError
    import fec_queue as fq

    creds = Creds(nomeutente=args.cf, pin=args.pin, password=password,
                  cfstudio=args.cfstudio, cf_cliente=args.cf_cliente,
                  piva=args.piva, profilo=args.profilo)
    try:
        auth = autentica(creds, backend=args.backend, headless=args.headless)
    except AuthError as exc:
        print(f"\n❌ Login fallito allo step «{exc.step}»: {exc.dettaglio}", file=sys.stderr)
        return 2

    print(f"\n✅ Login OK - backend {auth.backend}. Avvio «{args.comando}»...\n")
    try:
        _dispatch(args, auth, fq)
    except fq.DownloadError as exc:
        print(f"\n❌ Operazione non riuscita: {exc}", file=sys.stderr)
        return 1
    print("\n[Completato]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
