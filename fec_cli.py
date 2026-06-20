#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FeC-Plus — v0.02 alpha
"""
fec_cli.py — Interfaccia a riga di comando per FeC-Plus, SENZA GUI.

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

__version__ = "0.02 alpha"

import argparse
import os
import sys

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
        description="FeC-Plus — download da «Fatture e Corrispettivi» AdE, da riga di comando.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--version", action="version", version=f"FeC-Plus {__version__}")

    # ── Argomenti di ACCESSO (comuni a tutti i comandi, prima del COMANDO) ──
    acc = parser.add_argument_group("accesso")
    acc.add_argument("--cf", required=True,
                     help="CF Fisconline o nome utente Entratel (IDToken1)")
    acc.add_argument("--pin", required=True, help="PIN (IDToken3)")
    pwd = parser.add_mutually_exclusive_group(required=True)
    pwd.add_argument("--password", help="Password (IDToken2)")
    pwd.add_argument("--password-env", metavar="VAR",
                     help="Nome della variabile d'ambiente da cui leggere la password")
    acc.add_argument("--cfstudio", default="",
                     help="CF dello studio incaricante (profili 1/2)")
    acc.add_argument("--cf-cliente", default="", help="CF del cliente delegante")
    acc.add_argument("--piva", default="", help="P.IVA dell'utenza di lavoro (massive/bolli)")
    acc.add_argument("--profilo", type=int, choices=(1, 2, 3), default=1,
                     help="1=studio→cliente, 2=cassetto studio, 3=me stesso")
    acc.add_argument("--backend", choices=("requests", "browser"), default="requests",
                     help="Backend di login")
    acc.add_argument("--no-headless", dest="headless", action="store_false", default=True,
                     help="Mostra la finestra del browser (solo backend browser)")
    acc.add_argument("--dest", default=None,
                     help="Cartella di destinazione dei download (default: ./Download)")
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

    _add_date_range(sub.add_parser("massive-emesse",
                                   help="Richiesta massiva fatture emesse"), "aaaa-mm-gg")
    _add_date_range(sub.add_parser("massive-ricevute-emissione",
                                   help="Richiesta massiva ricevute (data emissione)"), "aaaa-mm-gg")
    _add_date_range(sub.add_parser("massive-ricevute-ricezione",
                                   help="Richiesta massiva ricevute (data ricezione)"), "aaaa-mm-gg")
    _add_date_range(sub.add_parser("corrispettivi",
                                   help="Richiesta massiva corrispettivi"), "aaaa-mm-gg")

    spb = sub.add_parser("bolli", help="Bolli virtuali → PDF F24")
    spb.add_argument("--trimestre", required=True, choices=("1", "2", "3", "4"))
    spb.add_argument("--anno", required=True, help="Anno (aaaa)")

    return parser


def _dispatch(args, auth, fd):
    """Chiama la funzione di fec_download corrispondente al comando."""
    c = args.comando
    dest, cfcl, piva = args.dest, args.cf_cliente, args.piva
    if c == "emesse":
        return fd.scarica_emesse(auth, args.dal, args.al, cfcl, dest_dir=dest)
    if c == "ricevute":
        return fd.scarica_ricevute(auth, args.dal, args.al, cfcl,
                                   tipo_data=args.tipo_data, dest_dir=dest)
    if c == "transfrontaliere-emesse":
        return fd.scarica_transfrontaliere_emesse(auth, args.dal, args.al, cfcl, dest_dir=dest)
    if c == "transfrontaliere-ricevute":
        return fd.scarica_transfrontaliere_ricevute(auth, args.dal, args.al, cfcl, dest_dir=dest)
    if c == "messe-a-disposizione":
        return fd.scarica_messe_a_disposizione(auth, args.dal, args.al, cfcl, dest_dir=dest)
    if c == "massive-emesse":
        return fd.richiesta_massiva_emesse(auth, args.dal, args.al, cfcl, piva, dest_dir=dest)
    if c == "massive-ricevute-emissione":
        return fd.richiesta_massiva_ricevute_emissione(auth, args.dal, args.al, cfcl, piva, dest_dir=dest)
    if c == "massive-ricevute-ricezione":
        return fd.richiesta_massiva_ricevute_ricezione(auth, args.dal, args.al, cfcl, piva, dest_dir=dest)
    if c == "corrispettivi":
        return fd.richiesta_corrispettivi(auth, args.dal, args.al, cfcl, piva, dest_dir=dest)
    if c == "bolli":
        return fd.scarica_bolli(auth, cfcl, piva, args.trimestre, args.anno, dest_dir=dest)
    raise SystemExit(f"Comando sconosciuto: {c}")


def _risolvi_password(args) -> str:
    if args.password is not None:
        return args.password
    val = os.environ.get(args.password_env or "", "")
    if not val:
        raise SystemExit(f"Variabile d'ambiente «{args.password_env}» vuota o assente.")
    return val


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    password = _risolvi_password(args)

    if args.dry_run:
        print(f"[dry-run] comando: {args.comando}")
        print(f"  accesso : cf={args.cf} profilo={args.profilo} "
              f"backend={args.backend} headless={args.headless}")
        print(f"  soggetti: cf_cliente={args.cf_cliente!r} piva={args.piva!r} "
              f"cfstudio={args.cfstudio!r}")
        for k in ("dal", "al", "tipo_data", "trimestre", "anno", "dest"):
            if hasattr(args, k):
                print(f"  {k} = {getattr(args, k)!r}")
        print("  (login e download NON eseguiti)")
        return 0

    from ade_auth import autentica, Creds, AuthError
    import fec_download as fd

    creds = Creds(nomeutente=args.cf, pin=args.pin, password=password,
                  cfstudio=args.cfstudio, cf_cliente=args.cf_cliente,
                  piva=args.piva, profilo=args.profilo)
    try:
        auth = autentica(creds, backend=args.backend, headless=args.headless)
    except AuthError as exc:
        print(f"\n❌ Login fallito allo step «{exc.step}»: {exc.dettaglio}", file=sys.stderr)
        return 2

    print(f"\n✅ Login OK — backend {auth.backend}. Avvio «{args.comando}»…\n")
    try:
        _dispatch(args, auth, fd)
    except fd.DownloadError as exc:
        print(f"\n❌ Operazione non riuscita: {exc}", file=sys.stderr)
        return 1
    print("\n[Completato]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
