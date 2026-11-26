#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Helper privilegiado de factupos-printer-inst.
# Se ejecuta como root via pkexec. Hace SOLO lo que necesita root:
# crear la cola RAW en CUPS, detectar dispositivos USB, desinstalar una cola y
# dejar una como predeterminada (#2831), y crear/quitar impresoras virtuales en un puerto
# COM (#3420: vport.py + factupos-vport@<n>.service), e impresoras PDF (#3494: cups-pdf).
# Mantenerlo minimo y auditado: la regla polkit permite correrlo sin clave.

import os
import re
import sys
import json
import time
import argparse
import pwd
import subprocess

LPADMIN = "/usr/sbin/lpadmin"
LPINFO = "/usr/sbin/lpinfo"
CUPSENABLE = "/usr/sbin/cupsenable"
CUPSACCEPT = "/usr/sbin/cupsaccept"
LPSTAT = "/usr/bin/lpstat"
SYSTEMCTL = "/usr/bin/systemctl"
# cups-browsed CREA SOLO una cola por cada impresora que otro equipo comparte en la red
# (device-uri implicitclass://). Borrarla con lpadmin no alcanza: a los segundos vuelve
# (visto en la .18 el 16-oct-2026, #2831). Para que no vuelva se le pone un filtro.
BROWSED_CONF = "/etc/cups/cups-browsed.conf"
MARCA_FILTRO = "# factupos-printer-inst: oculta"


def run(cmd):
    # 🪤 LC_ALL=C: en un equipo en espanol lpstat dice «dispositivo para», no «device for»,
    # y vport-add creia que la impresora no estaba instalada (#3420, misma trampa que #2698).
    p = subprocess.run(cmd, capture_output=True, text=True,
                       env=dict(os.environ, LANG="C", LC_ALL="C"))
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def cmd_apply(args):
    # Cola RAW (la TM-U220 y demas POS imprimen ESC/POS crudo).
    # 1.4.4: «factupos-termica» = el driver propio (PDF/navegador -> tiquete ESC/POS).
    if args.model == "factupos-termica":
        if not os.path.isfile(TERMICA_PPD):
            print("APPLY_ERR falta el driver FactuPOS termica (%s)" % TERMICA_PPD)
            return 1
        modelo = ["-P", TERMICA_PPD]
    else:
        modelo = ["-m", args.model]
    rc, out = run([LPADMIN, "-p", args.name, "-E", "-v", args.uri] + modelo
                  + ["-o", "printer-is-shared=false"])
    if rc != 0:
        print("APPLY_ERR\n" + out)
        return 1
    run([CUPSENABLE, args.name])
    run([CUPSACCEPT, args.name])
    if args.default:
        run([LPADMIN, "-d", args.name])
    print("APPLY_OK %s" % args.name)
    return 0


# Nombre de cola CUPS: sin espacios, '/', '#' ni comillas (lo mismo que acepta lpadmin).
NOMBRE_OK = re.compile(r"^[^\s/#\\'\"]{1,127}$")


def _nombre_valido(name):
    if not NOMBRE_OK.match(name or ""):
        print("NAME_ERR nombre de impresora invalido")
        return False
    return True


def _es_automatica(name):
    """True si la cola la creo cups-browsed (impresora compartida por otro equipo)."""
    _rc, out = run([LPSTAT, "-v", name])
    return "implicitclass://" in out


def _linea_filtro(name):
    return "BrowseFilter NOT EXACT name %s %s" % (name, MARCA_FILTRO)


def _leer_conf():
    try:
        with open(BROWSED_CONF, encoding="utf-8") as f:
            return f.read().splitlines()
    except FileNotFoundError:
        return []


def _escribir_conf(lineas):
    tmp = BROWSED_CONF + ".fp-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, BROWSED_CONF)
    run([SYSTEMCTL, "restart", "cups-browsed"])


def _ocultar(name):
    lineas = _leer_conf()
    if _linea_filtro(name) not in lineas:
        _escribir_conf(lineas + [_linea_filtro(name)])


def cmd_remove(args):
    # #2831: desinstalar una impresora del equipo (borra la cola de CUPS). Si es una de
    # las que cups-browsed crea solo, primero se le pone el filtro para que no vuelva.
    if not _nombre_valido(args.name):
        return 1
    if _es_automatica(args.name):
        _ocultar(args.name)
        rc, out = run([LPADMIN, "-x", args.name])
        _rc2, sigue = run([LPSTAT, "-v", args.name])
        if "implicitclass://" in sigue:
            print("REMOVE_ERR\n" + out + sigue)
            return 1
        print("REMOVE_OK %s oculta" % args.name)
        return 0
    rc, out = run([LPADMIN, "-x", args.name])
    if rc != 0:
        print("REMOVE_ERR\n" + out)
        return 1
    print("REMOVE_OK %s" % args.name)
    return 0


def cmd_default(args):
    # #2831: dejar una impresora como predeterminada del equipo.
    if not _nombre_valido(args.name):
        return 1
    rc, out = run([LPADMIN, "-d", args.name])
    if rc != 0:
        print("DEFAULT_ERR\n" + out)
        return 1
    print("DEFAULT_OK %s" % args.name)
    return 0


def cmd_hidden(_args):
    # #2831: impresoras de la red que se ocultaron (para poder volver a mostrarlas).
    for l in _leer_conf():
        if l.endswith(MARCA_FILTRO) and l.startswith("BrowseFilter NOT EXACT name "):
            print("HIDDEN " + l[len("BrowseFilter NOT EXACT name "):-len(MARCA_FILTRO)].strip())
    return 0


def cmd_unhide(args):
    # #2831: quita el filtro; cups-browsed la vuelve a crear sola en unos segundos.
    if not _nombre_valido(args.name):
        return 1
    lineas = _leer_conf()
    nuevas = [l for l in lineas if l != _linea_filtro(args.name)]
    if nuevas != lineas:
        _escribir_conf(nuevas)
    print("UNHIDE_OK %s" % args.name)
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


# ---------- impresora virtual en un puerto COM (#3420) ----------
VPORT_DIR = "/etc/factupos-printer-inst/vport"
VPORT_UNIT = "factupos-vport@%d.service"
COM_MAX = 32
NOMBRE_VIRTUAL_MALO = re.compile(r"[\x00-\x1f\x7f]")
# 1.4.1: la impresora de CUPS con el nombre de la virtual (para que el NAVEGADOR la vea)
# apunta al servicio por un socket local: CUPS no puede abrir el COM (AppArmor).
PUERTO_BASE = 19100


def _uri_virtual(com):
    return "socket://127.0.0.1:%d" % (PUERTO_BASE + com)


def _es_uri_virtual(uri):
    return uri.startswith("socket://127.0.0.1:%d" % (PUERTO_BASE // 100)) and \
        uri[len("socket://127.0.0.1:"):].isdigit()


def _uri_de(cola):
    _rc, out = run([LPSTAT, "-v", cola])
    for l in out.splitlines():
        if l.startswith("device for ") and ":" in l[11:]:
            return l[11:].split(":", 1)[1].strip()
    return ""


def _cola_de_nombre(nombre):
    return re.sub(r"[\s/#\\'\"]+", "_", nombre).strip("_")[:127] or "Impresora_virtual"


# fp-helper: vport-termica  (la pantalla busca esta marca para saber si el helper esta al dia)
PPD_DIR = "/etc/cups/ppd"
# 1.4.4: driver propio para termicas (filtro /usr/lib/cups/filter/rastertofactupos).
TERMICA_PPD = "/usr/share/ppd/factupos/factupos-termica.ppd"


def _instalar_cola_virtual(nombre, com, destino=""):
    """Crea (o deja al dia) la cola de CUPS de la virtual. Devuelve (cola, error).
    1.4.3: lleva el MISMO controlador (PPD) que la impresora real. Sin controlador (raw) Chrome
    deja gris el boton Imprimir (no tiene tamanos de papel que mostrar), y con el de la real el
    trabajo sale ya preparado para ella: vport.py lo pasa con -o raw."""
    cola = _cola_de_nombre(nombre)
    uri = _uri_virtual(com)
    actual = _uri_de(cola)
    if actual and actual != uri:
        return cola, "ya hay otra impresora llamada '%s'" % cola
    # El driver de la real; si la real es RAW (la de FactuPOS Print), el driver FactuPOS
    # termica: el navegador manda PDF y una termica RAW no lo sabe leer (1.4.4).
    ppd = os.path.join(PPD_DIR, destino + ".ppd") if destino else ""
    if ppd and os.path.isfile(ppd):
        modelo = ["-P", ppd]
    elif os.path.isfile(TERMICA_PPD):
        modelo = ["-P", TERMICA_PPD]
    else:
        modelo = ["-m", "raw"]
    rc, out = run([LPADMIN, "-p", cola, "-E", "-v", uri] + modelo + ["-D", nombre,
                   "-L", "Impresora virtual COM%d" % com, "-o", "printer-is-shared=false"])
    if rc != 0:
        return cola, out
    run([CUPSENABLE, cola])
    run([CUPSACCEPT, cola])
    return cola, ""


def _usuario_pkexec():
    """Quién tocó el botón (pkexec deja PKEXEC_UID). 1.4.6 (#3494): si la virtual imprime en
    una impresora PDF, el archivo va a SU carpeta PDF (vport.py corre como root)."""
    try:
        return pwd.getpwuid(int(os.environ["PKEXEC_UID"])).pw_name
    except Exception:
        return ""


def _com_valido(com):
    if not (1 <= com <= COM_MAX):
        print("VPORT_ERR el puerto tiene que ser COM1 a COM%d" % COM_MAX)
        return False
    return True


def cmd_vport_add(args):
    # Nombre libre (lo que el usuario quiera), un COM y una impresora YA instalada.
    nombre = (args.nombre or "").strip()
    if not nombre or len(nombre) > 60 or NOMBRE_VIRTUAL_MALO.search(nombre):
        print("VPORT_ERR nombre invalido")
        return 1
    if not _com_valido(args.com) or not _nombre_valido(args.cola):
        return 1
    destino = _uri_de(args.cola)
    if not destino:
        print("VPORT_ERR la impresora '%s' no esta instalada" % args.cola)
        return 1
    if _es_uri_virtual(destino):
        print("VPORT_ERR '%s' es otra impresora virtual: elija una impresora real" % args.cola)
        return 1
    cola_v = _cola_de_nombre(nombre)
    uri_v = _uri_de(cola_v)
    if uri_v and uri_v != _uri_virtual(args.com):
        print("VPORT_ERR ya hay otra impresora llamada '%s'" % cola_v)
        return 1
    os.makedirs(VPORT_DIR, mode=0o755, exist_ok=True)
    ruta = os.path.join(VPORT_DIR, "COM%d.json" % args.com)
    tmp = ruta + ".fp-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"nombre": nombre, "cola": args.cola, "com": args.com, "cups": cola_v,
                   "usuario": _usuario_pkexec()}, f, ensure_ascii=False)
    os.chmod(tmp, 0o644)
    os.replace(tmp, ruta)
    unit = VPORT_UNIT % args.com
    run([SYSTEMCTL, "enable", unit])
    rc, out = run([SYSTEMCTL, "restart", unit])
    dev = "/dev/ttyCOM%d" % args.com
    for _ in range(40):                    # el servicio crea el puerto en ~0,2 s
        if os.path.exists(dev):
            break
        time.sleep(0.1)
    else:
        print("VPORT_ERR el servicio no creo %s\n%s" % (dev, out))
        return 1
    cola_v, err = _instalar_cola_virtual(nombre, args.com, args.cola)
    if err:
        print("VPORT_ERR no se pudo instalar '%s' en el sistema de impresion\n%s" % (cola_v, err))
        return 1
    print("VPORT_OK COM%d %s %s" % (args.com, dev, cola_v))
    return 0


def cmd_vport_sync(_args):
    # 1.4.1: las virtuales creadas con la 1.4.0 no tenian cola de CUPS (el navegador no las
    # veia). Lo corre el postinst del paquete; tambien sirve para reparar.
    for ruta in sorted(os.listdir(VPORT_DIR) if os.path.isdir(VPORT_DIR) else []):
        if not (ruta.startswith("COM") and ruta.endswith(".json")):
            continue
        try:
            with open(os.path.join(VPORT_DIR, ruta), encoding="utf-8") as f:
                c = json.load(f)
            com = int(c["com"])
        except Exception:
            continue
        cola_v, err = _instalar_cola_virtual(c.get("nombre") or "COM%d" % com, com,
                                             c.get("cola", ""))
        usuario = c.get("usuario") or _usuario_pkexec()
        if not err and (c.get("cups") != cola_v or c.get("usuario", "") != usuario):
            c["cups"] = cola_v
            c["usuario"] = usuario
            tmp = os.path.join(VPORT_DIR, ruta + ".fp-tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False)
            os.chmod(tmp, 0o644)
            os.replace(tmp, os.path.join(VPORT_DIR, ruta))
        print(("VPORT_SYNC_OK COM%d %s" % (com, cola_v)) if not err
              else ("VPORT_SYNC_ERR COM%d %s" % (com, err.strip())))
    return 0


def cmd_vport_remove(args):
    if not _com_valido(args.com):
        return 1
    unit = VPORT_UNIT % args.com
    ruta = os.path.join(VPORT_DIR, "COM%d.json" % args.com)
    try:
        with open(ruta, encoding="utf-8") as f:
            cola_v = json.load(f).get("cups", "")
    except Exception:
        cola_v = ""
    # Se borra la cola de CUPS solo si de verdad es la de este COM.
    if cola_v and _uri_de(cola_v) == _uri_virtual(args.com):
        run([LPADMIN, "-x", cola_v])
    run([SYSTEMCTL, "disable", "--now", unit])
    try:
        os.unlink(ruta)
    except FileNotFoundError:
        pass
    if os.path.exists("/dev/ttyCOM%d" % args.com):
        print("VPORT_ERR el puerto COM%d sigue existiendo" % args.com)
        return 1
    print("VPORT_REMOVE_OK COM%d" % args.com)
    return 0


# ---------- impresora PDF (#3494) ----------
# fp-helper: pdf  (la pantalla busca add_parser("pdf-add") para saber si el helper la conoce)
# Usa cups-pdf (paquete printer-driver-cups-pdf): guarda cada trabajo como PDF en la
# carpeta PDF del usuario que imprime (~/PDF, /etc/cups/cups-pdf.conf «Out ${HOME}/PDF»).
PDF_PKG = "printer-driver-cups-pdf"
PDF_BACKEND = "/usr/lib/cups/backend/cups-pdf"
PDF_PPDS = ("/usr/share/ppd/cups-pdf/CUPS-PDF_opt.ppd", "/usr/share/ppd/cups-pdf/CUPS-PDF_noopt.ppd")
APT_GET = "/usr/bin/apt-get"


def _colas_pdf():
    """Nombres de las colas que hoy imprimen a cups-pdf:/."""
    _rc, out = run([LPSTAT, "-v"])
    res = set()
    for l in out.splitlines():
        if l.startswith("device for ") and ":" in l[11:]:
            n, u = l[11:].split(":", 1)
            if u.strip().startswith("cups-pdf:"):
                res.add(n.strip())
    return res


def _apt_instalar_pdf():
    env = dict(os.environ, LANG="C", LC_ALL="C", DEBIAN_FRONTEND="noninteractive")
    cmd = [APT_GET, "install", "-y", "--no-install-recommends", PDF_PKG]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if p.returncode != 0:      # lista de paquetes vieja: se actualiza y se reintenta una vez
        subprocess.run([APT_GET, "update"], capture_output=True, text=True, env=env)
        p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def cmd_pdf_add(args):
    if not _nombre_valido(args.name):
        return 1
    actual = _uri_de(args.name)
    if actual and not actual.startswith("cups-pdf:"):
        print("PDF_ERR ya hay otra impresora llamada '%s'" % args.name)
        return 1
    if not os.path.exists(PDF_BACKEND):
        # El postinst de printer-driver-cups-pdf crea SOLO una cola «PDF» (y la deja
        # predeterminada si no hay otra): esa no la pidio nadie y se borra.
        antes = _colas_pdf()
        rc, out = _apt_instalar_pdf()
        if rc != 0 or not os.path.exists(PDF_BACKEND):
            print("PDF_ERR no se pudo instalar el componente PDF (%s)\n%s" % (PDF_PKG, out[-1500:]))
            return 1
        for cola in _colas_pdf() - antes:
            if cola != args.name:
                run([LPADMIN, "-x", cola])
    ppd = next((p for p in PDF_PPDS if os.path.isfile(p)), "")
    modelo = ["-P", ppd] if ppd else ["-m", "lsb/usr/cups-pdf/CUPS-PDF_opt.ppd"]
    rc, papel = run(["paperconf"])
    papel = papel.strip().capitalize() if rc == 0 and papel.strip() else "Letter"
    rc, out = run([LPADMIN, "-p", args.name, "-E", "-v", "cups-pdf:/"] + modelo
                  + ["-D", "Impresora PDF", "-L", "Guarda en la carpeta PDF del usuario",
                     "-o", "printer-is-shared=false", "-o", "PageSize=%s" % papel])
    if rc != 0:
        print("PDF_ERR\n" + out)
        return 1
    run([CUPSENABLE, args.name])
    run([CUPSACCEPT, args.name])
    if args.default:
        run([LPADMIN, "-d", args.name])
    if not _uri_de(args.name).startswith("cups-pdf:"):
        print("PDF_ERR la impresora no quedo instalada")
        return 1
    print("PDF_OK %s" % args.name)
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

    r = sub.add_parser("remove")
    r.add_argument("--name", required=True)
    r.set_defaults(func=cmd_remove)

    df = sub.add_parser("default")
    df.add_argument("--name", required=True)
    df.set_defaults(func=cmd_default)

    h = sub.add_parser("hidden")
    h.set_defaults(func=cmd_hidden)

    u = sub.add_parser("unhide")
    u.add_argument("--name", required=True)
    u.set_defaults(func=cmd_unhide)

    va = sub.add_parser("vport-add")
    va.add_argument("--nombre", required=True)
    va.add_argument("--cola", required=True)
    va.add_argument("--com", required=True, type=int)
    va.set_defaults(func=cmd_vport_add)

    vs = sub.add_parser("vport-sync")
    vs.set_defaults(func=cmd_vport_sync)

    vr = sub.add_parser("vport-remove")
    vr.add_argument("--com", required=True, type=int)
    vr.set_defaults(func=cmd_vport_remove)

    pa = sub.add_parser("pdf-add")
    pa.add_argument("--name", required=True)
    pa.add_argument("--default", action="store_true")
    pa.set_defaults(func=cmd_pdf_add)

    d = sub.add_parser("detect-usb")
    d.set_defaults(func=cmd_detect_usb)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
