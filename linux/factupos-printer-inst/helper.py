#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Helper privilegiado de factupos-printer-inst.
# Se ejecuta como root via pkexec. Hace SOLO lo que necesita root:
# crear la cola RAW en CUPS y detectar dispositivos USB.
# Mantenerlo minimo y auditado: la regla polkit permite correrlo sin clave.

import sys
import argparse
import subprocess

LPADMIN = "/usr/sbin/lpadmin"
LPINFO = "/usr/sbin/lpinfo"
CUPSENABLE = "/usr/sbin/cupsenable"
CUPSACCEPT = "/usr/sbin/cupsaccept"


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def cmd_apply(args):
    # Cola RAW (la TM-U220 y demas POS imprimen ESC/POS crudo).
    rc, out = run([LPADMIN, "-p", args.name, "-E", "-v", args.uri,
                   "-m", args.model, "-o", "printer-is-shared=false"])
    if rc != 0:
        print("APPLY_ERR\n" + out)
        return 1
    run([CUPSENABLE, args.name])
    run([CUPSACCEPT, args.name])
    if args.default:
        run([LPADMIN, "-d", args.name])
    print("APPLY_OK %s" % args.name)
    return 0


def cmd_detect_usb(_args):
    rc, out = run([LPINFO, "-v"])
    if rc != 0:
        print(out)
        return 1
    for line in out.splitlines():
        for tok in line.split():
            if tok.startswith("usb://"):
                print(tok)
    return 0


def main():
    ap = argparse.ArgumentParser(prog="factupos-printer-inst-helper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("apply")
    a.add_argument("--name", required=True)
    a.add_argument("--uri", required=True)
    a.add_argument("--model", default="raw")
    a.add_argument("--no-default", dest="default", action="store_false")
    a.set_defaults(default=True, func=cmd_apply)

    d = sub.add_parser("detect-usb")
    d.set_defaults(func=cmd_detect_usb)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
