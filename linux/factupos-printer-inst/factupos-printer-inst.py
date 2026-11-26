#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FactuPOS · Gestión de Impresoras  (factupos-printer-inst)
# (hasta 1.2.0 se llamo «Instalador de Impresoras»: ese texto tiene que seguir en este
#  archivo porque las versiones viejas lo buscan para aceptar la actualizacion)
# Asistente grafico para instalar impresoras USB / Serial (tickets Epson TM, etc.)
# como cola RAW en CUPS. No requiere pycups: usa lpadmin/lpinfo via un helper con pkexec.
# 1.4.6 (#3494): impresora virtual con destino PDF: lo que llega al COM (ESC/POS) sale como PDF
#        de texto en la carpeta PDF del usuario que creó la virtual (vport.py + helper).
# 1.4.5 (#3494): botón «+ Impresora PDF» (cups-pdf): guarda lo que se imprime como PDF en la
#        carpeta PDF del usuario. El componente se instala solo la primera vez.
# 1.4.4 (#3420): driver propio «FactuPOS térmica» (filtro CUPS rastertofactupos): el navegador
#        imprime en una térmica. La virtual lo usa si la real es RAW, y el asistente puede
#        instalar una térmica con ese driver (otro nombre, misma impresora) además de la RAW.
# 1.4.3 (#3420): la impresora del sistema de la virtual lleva el controlador de la real (en
#        Chrome el botón Imprimir salía gris con la cola raw). «Actualizar ahora» también si el
#        helper es anterior a esto.
# 1.4.2 (#3420): botón «Actualizar ahora» cuando falta el paquete nuevo (pantalla al día y
#        paquete atrasado): actualiza por FactuPOS Apps (sin clave) y corre vport-sync.
# 1.4.1 (#3420): cada impresora virtual queda TAMBIEN como impresora del sistema con su nombre
#        (socket://127.0.0.1:1910n -> vport.py): el navegador la ve. Las de la 1.4.0 se agregan solas.
# 1.4.0 (#3420): IMPRESORAS VIRTUALES — un nombre libre + un puerto COM virtual (/dev/ttyCOMn,
#        y COMn en Wine) mapeado a una impresora ya instalada. Servicio vport.py por COM.
# 1.3.2 (#2831): el revisor del paquete ve la version nueva tambien en PCs en espanol.
# 1.3.1 (#2831): las impresoras que cups-browsed agrega solas (compartidas por otro equipo,
#        implicitclass://) ya no vuelven al desinstalarlas: se ocultan, y se pueden volver a mostrar.
# 1.3.0 (#2831): impresoras de RED — busca en la red impresoras (9100/IPP/LPD) y equipos
#        que comparten impresoras (CUPS de Linux y Windows/SMB) y las instala en este equipo.
# 1.2.1 (#2831): se llama «Gestion de Impresoras»; con helper viejo pide la clave (pkexec lpadmin).
# 1.2.0 (#2831): pantalla «Impresoras de este equipo» (desinstalar, predeterminada,
# prueba) y asistente de instalacion con pasos, tarjetas y detalle tecnico plegado.
# FactuPOS / Soporte Real - https://soportereal.com

import os
import sys
import re
import json
import glob
import shutil
import threading
import subprocess
import socket
import tempfile
import concurrent.futures
import urllib.parse
import urllib.request

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango  # noqa: E402

try:
    import serial  # pyserial
    HAVE_SERIAL = True
except Exception:
    HAVE_SERIAL = False

VERSION = "1.4.6"                                # fuente única de versión

# Auto-actualización (mismo esquema que factupos-panel): lee el manifest publicado,
# y si hay versión nueva baja el .py a una carpeta del usuario (sin root) y reinicia.
UPDATE_BASE = "https://soportereal.com/software/factupos-app/linux"
UPDATE_MANIFEST = UPDATE_BASE + "/Factupos-Printer-Inst_version.json"
UPDATE_PY_LOCAL = os.path.expanduser(
    "~/.local/share/factupos-printer-inst/factupos-printer-inst.py")
UPDATE_INTERVAL = 3600                           # re-chequeo cada hora (#2698)


def _vtuple(v):
    """'1.2.10' -> (1,2,10) para comparar versiones."""
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except Exception:
        return (0,)

# El helper privilegiado: instalado en /usr/lib/..., o junto al script en desarrollo.
_HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = "/usr/lib/factupos-printer-inst/helper.py"
if not os.path.exists(HELPER):
    HELPER = os.path.join(_HERE, "helper.py")

BAUDS = ["9600", "19200", "38400", "115200", "4800", "2400"]
# flujo de datos serie. dtrdsr = por defecto en Epson TM-U220.
FLOWS = ["dtrdsr", "none", "rtscts", "xonxoff"]
LPADMIN = "/usr/sbin/lpadmin"

# Nombre de cola CUPS: sin espacios, '/', '#' ni comillas (igual que el helper).
NOMBRE_MALO = re.compile(r"[\s/#\\'\"]+")

CSS = b"""
/* Diseno NAVY (#2698) + tarjetas y pasos (#2831). El proveedor es de ESTA app (su
   propio proceso): los selectores genericos (window, button...) no tocan a ninguna otra. */
window, dialog, messagedialog { background-color: #0b1533; color: #e2e8f0; }
messagedialog .dialog-action-area button { margin: 6px; }
label { color: #e2e8f0; }
.fp-title { font-size: 18px; font-weight: bold; color: #ffffff; }
.fp-sub   { color: #a5b4fc; }
.fp-muted { color: #94a3b8; }
.fp-step  { color: #38bdf8; font-weight: bold; font-size: 15px; }
.fp-log   { font-family: monospace; font-size: 11px; }
.fp-ver   { background-color: rgba(124,58,237,0.35); color: #e9d5ff; border-radius: 10px;
            padding: 2px 10px; font-size: 11px; }
.fp-paso      { color: #64748b; padding: 4px 12px; border-radius: 12px;
                background-color: rgba(255,255,255,0.04); }
.fp-paso-on   { color: #ffffff; font-weight: bold;
                background-image: linear-gradient(135deg, #7c3aed, #2563eb); }
.fp-paso-ok   { color: #86efac; background-color: rgba(34,197,94,0.14); }
.fp-card { background-color: #12204a; border: 1px solid rgba(255,255,255,0.10);
           border-radius: 14px; padding: 12px 14px; }
.fp-card-t { font-weight: bold; color: #ffffff; font-size: 14px; }
.fp-badge { background-color: rgba(34,197,94,0.20); color: #86efac; border-radius: 9px;
            padding: 1px 8px; font-size: 11px; font-weight: bold; }
.fp-badge-off { background-color: rgba(244,63,94,0.20); color: #fda4af; border-radius: 9px;
                padding: 1px 8px; font-size: 11px; font-weight: bold; }
.fp-ok   { color: #86efac; font-weight: bold; }
.fp-err  { color: #fda4af; font-weight: bold; }
.fp-warn { color: #fcd34d; }
.fp-vacio { color: #94a3b8; font-size: 14px; }
textview, textview text { background-color: #0f1a3a; color: #e2e8f0; }
button { background-image: none; background-color: rgba(255,255,255,0.08); color: #e2e8f0;
         border: 1px solid rgba(255,255,255,0.25); border-radius: 12px; padding: 6px 14px; box-shadow: none; }
button:hover { background-color: rgba(255,255,255,0.16); }
button label { color: #e2e8f0; }
button:disabled label { color: #64748b; }
button.suggested-action { background-image: linear-gradient(135deg, #7c3aed, #2563eb);
                          border-color: rgba(255,255,255,0.35); }
button.suggested-action label { color: #ffffff; font-weight: bold; }
button.suggested-action:disabled { background-image: none; background-color: #2a2f4a; }
button.fp-peligro { background-color: rgba(244,63,94,0.16); border-color: rgba(244,63,94,0.55); }
button.fp-peligro:hover { background-color: rgba(244,63,94,0.32); }
button.fp-peligro label { color: #fecdd3; }
button.fp-opcion { background-color: #12204a; border: 2px solid rgba(255,255,255,0.10);
                   border-radius: 14px; padding: 12px 14px; }
button.fp-opcion:hover { border-color: rgba(167,139,250,0.6); }
button.fp-opcion:checked { background-color: #1b2a5c; border-color: #a78bfa; }
list, list row { background-color: transparent; }
list row { border-radius: 14px; margin: 3px 0; }
list row:selected { background-color: rgba(124,58,237,0.25); }
radiobutton label, checkbutton label { color: #e2e8f0; }
radiobutton radio, checkbutton check { background-image: none; background-color: #14224d; border: 1px solid #7184ad; }
radiobutton radio:checked, checkbutton check:checked { background-color: #7c3aed; border-color: #a78bfa; color: #ffffff; }
entry { background-color: #14224d; color: #ffffff; border: 1px solid #4f63a8; border-radius: 10px; padding: 6px 10px; }
combobox button { background-color: #14224d; }
expander title label { color: #94a3b8; }
scrolledwindow, viewport { background-color: #0b1533; }
"""


def sh(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                           env=dict(os.environ, LANG="C", LC_ALL="C"))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


def nombre_limpio(txt):
    """Lo que el usuario escribe -> nombre de cola valido para CUPS."""
    return NOMBRE_MALO.sub("_", (txt or "").strip()).strip("_")[:127]


def helper_viejo(out):
    """El helper.py vive en /usr/lib (root) y el auto-update solo cambia este .py:
    un helper anterior a 1.2.0 no conoce 'remove'/'default' (argparse lo rechaza)."""
    return "invalid choice" in out or "usage: factupos-printer-inst-helper" in out


HELPER_MARCA = "fp-helper: vport-termica"  # helper.py 1.4.4 (driver FactuPOS térmica, #3420)


def helper_al_dia():
    try:
        with open(HELPER, encoding="utf-8", errors="replace") as f:
            return HELPER_MARCA in f.read()
    except Exception:
        return False


def helper_sabe(accion):
    """True si el helper instalado conoce esa accion (se lee el archivo, no hace falta root)."""
    try:
        with open(HELPER, encoding="utf-8", errors="replace") as f:
            return ('add_parser("%s")' % accion) in f.read()
    except Exception:
        return False


def ocultar_clave(uri):
    """smb://usuario:clave@equipo/... -> smb://***@equipo/... (nada de claves en pantalla)."""
    return re.sub(r"//[^@/]*@", "//***@", uri)


def describir_uri(uri):
    """URI de CUPS -> (tipo, detalle) en palabras del usuario."""
    if uri.startswith("smb://"):
        resto = uri[6:].split("@", 1)[-1]
        host, _, share = resto.partition("/")
        return "Windows", "%s · %s" % (urllib.parse.unquote(share) or "?", host)
    if uri.startswith("serial:"):
        port = uri[7:].split("?")[0]
        baud = ""
        if "baud=" in uri:
            baud = uri.split("baud=")[1].split("+")[0].split("&")[0]
        return "Serial", port + ((" · %s baud" % baud) if baud else "")
    if uri.startswith("usb://"):
        modelo = urllib.parse.unquote(uri[6:].split("?")[0]).replace("/", " ")
        return "USB", modelo
    if uri.startswith(("socket://", "lpd://", "ipp://", "ipps://", "http://", "https://")):
        host = uri.split("://", 1)[1].split("/")[0]
        return "Red", host
    if uri.startswith("dnssd://"):
        return "Red", urllib.parse.unquote(uri[8:].split("/")[0].split("._")[0])
    if uri.startswith("cups-pdf:"):
        return "PDF", "guarda los archivos en la carpeta «PDF» del usuario"
    if uri.startswith(("file:", "parallel:")):
        return "Directo", uri.split(":", 1)[1]
    return "Otra", uri


def listar_impresoras():
    """Impresoras instaladas en CUPS (no necesita root)."""
    _rc, outv = sh(["lpstat", "-v"])
    _rc, outp = sh(["lpstat", "-p"])
    _rc, outd = sh(["lpstat", "-d"])
    default = ""
    if ":" in outd and "no system default" not in outd:
        default = outd.split(":", 1)[1].strip()
    estados = {}
    for line in outp.splitlines():
        if line.startswith("printer "):
            partes = line.split()
            if len(partes) > 1:
                estados[partes[1]] = "disabled" not in line
    impresoras = []
    for line in outv.splitlines():
        if not line.startswith("device for ") or ":" not in line[11:]:
            continue
        nombre, uri = line[11:].split(":", 1)
        nombre, uri = nombre.strip(), uri.strip()
        tipo, det = describir_uri(uri)
        auto = uri.startswith("implicitclass://")
        if es_uri_virtual(uri):
            continue                      # se muestra en «Impresoras virtuales» (#3420)
        if auto:
            tipo, det = "Red (la comparte otro equipo)", origen_automatica(nombre)
        impresoras.append({"nombre": nombre, "uri": uri, "tipo": tipo, "detalle": det,
                           "default": nombre == default, "auto": auto,
                           "lista": estados.get(nombre, True)})
    impresoras.sort(key=lambda p: (not p["default"], p["nombre"].lower()))
    return impresoras


BROWSED_CONF = "/etc/cups/cups-browsed.conf"
MARCA_FILTRO = "# factupos-printer-inst: oculta"     # la misma que escribe helper.py


def origen_automatica(nombre):
    """De qué equipo viene una cola que creó cups-browsed: su device-uri real es
    ipps://Canon%20G1110%20%40%20svr-stg1._ipps._tcp.local/cups -> 'Canon G1110 @ svr-stg1'."""
    _rc, out = sh(["lpoptions", "-p", nombre])
    m = re.search(r"device-uri=(\S+)", out)
    if not m:
        return "agregada sola por el equipo"
    serv = urllib.parse.unquote(m.group(1).split("://", 1)[-1].split("/")[0])
    return serv.split("._")[0]


def impresoras_ocultas():
    """Las de la red que se ocultaron con esta app (el archivo es legible sin root)."""
    pref = "BrowseFilter NOT EXACT name "
    try:
        with open(BROWSED_CONF, encoding="utf-8", errors="replace") as f:
            return [l[len(pref):-len(MARCA_FILTRO)].strip() for l in f.read().splitlines()
                    if l.startswith(pref) and l.endswith(MARCA_FILTRO)]
    except Exception:
        return []


def es_raw(nombre):
    _rc, out = sh(["lpoptions", "-p", nombre])
    return "Local Raw Printer" in out or "printer-make-and-model" not in out


def imprimir_prueba(nombre):
    """Manda una pagina de prueba por la cola (no por el puerto): prueba la cola real."""
    raw = es_raw(nombre)
    texto = ("FactuPOS - Soporte Real\n--- PRUEBA DE IMPRESORA ---\n"
             "Impresora: %s\nSi lee esto, la impresora quedo bien.\n\n\n\n\n" % nombre)
    datos = (("\x1b@" + texto) if raw else texto).encode("latin-1", "replace")
    fd, ruta = tempfile.mkstemp(prefix="fp-prueba-", suffix=".txt")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(datos)
        cmd = ["lp", "-d", nombre] + (["-o", "raw"] if raw else []) + [ruta]
        return sh(cmd)
    finally:
        try:
            os.unlink(ruta)
        except Exception:
            pass


# ---------- impresora PDF (1.4.5, #3494) ----------
CARPETA_PDF = os.path.expanduser("~/PDF")     # «Out ${HOME}/PDF» de /etc/cups/cups-pdf.conf


def abrir_carpeta_pdf():
    os.makedirs(CARPETA_PDF, exist_ok=True)
    subprocess.Popen(["xdg-open", CARPETA_PDF], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


# ---------- impresoras virtuales en un puerto COM (1.4.0, #3420) ----------
VPORT_DIR = "/etc/factupos-printer-inst/vport"
COM_MAX = 32
DEV_COM = "/dev/ttyCOM%d"                    # el puerto que crea vport.py (helper.py)
WINE_DOS = os.path.expanduser("~/.wine/dosdevices")


def es_uri_virtual(uri):
    """La impresora del sistema de una virtual: socket://127.0.0.1:1910n (ver helper.py)."""
    pref = "socket://127.0.0.1:191"
    return uri.startswith(pref) and uri[len("socket://127.0.0.1:"):].isdigit()


def colas_virtuales():
    """{cola: uri} de las impresoras del sistema que son de una virtual (no necesita root)."""
    _rc, out = sh(["lpstat", "-v"])
    res = {}
    for line in out.splitlines():
        if line.startswith("device for ") and ":" in line[11:]:
            n, u = line[11:].split(":", 1)
            if es_uri_virtual(u.strip()):
                res[n.strip()] = u.strip()
    return res


PKG = "factupos-printer-inst"
# FactuPOS Apps instala/actualiza SIN clave (polkit 51, op.sh hace apt update + install).
TIENDA_UNIT = "factupos-apps-op@instalar-%s.service" % PKG
REVISOR_UNIT = "%s-autoupdate.service" % PKG      # el revisor propio del paquete (pide clave)


def version_paquete():
    _rc, out = sh(["dpkg-query", "-Wf", "${Version}", PKG])
    return out.strip() if _rc == 0 else ""


def unidad_existe(unit):
    plantilla = unit.split("@")[0] + "@.service" if "@" in unit else unit
    return any(os.path.exists(os.path.join(d, plantilla))
               for d in ("/lib/systemd/system", "/usr/lib/systemd/system", "/etc/systemd/system"))


def actualizar_paquete(log):
    """Pone al día el paquete (helper, vport.py). Devuelve la versión que quedó."""
    antes = version_paquete()
    if unidad_existe(TIENDA_UNIT):
        cmd = ["systemctl", "start", TIENDA_UNIT]
    else:
        cmd = ["pkexec", "systemctl", "start", REVISOR_UNIT]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900,
                           env=dict(os.environ, LANG="C", LC_ALL="C"))
        log("%s: rc=%s %s" % (" ".join(cmd), p.returncode, (p.stdout + p.stderr).strip()))
    except Exception as e:
        log("%s: %s" % (" ".join(cmd), e))
    despues = version_paquete()
    log("Paquete %s: %s -> %s" % (PKG, antes or "?", despues or "?"))
    return despues


def listar_virtuales():
    """Impresoras virtuales del equipo (la configuración es legible sin root)."""
    vs = []
    en_cups = colas_virtuales()
    for ruta in sorted(glob.glob(os.path.join(VPORT_DIR, "COM*.json"))):
        try:
            with open(ruta, encoding="utf-8") as f:
                c = json.load(f)
            com = int(c["com"])
        except Exception:
            continue
        dev = DEV_COM % com
        vs.append({"nombre": c.get("nombre") or "COM%d" % com, "cola": c.get("cola", ""),
                   "com": com, "dev": dev, "activa": os.path.exists(dev),
                   # por el PUERTO, no por lo anotado en el .json: así la ve aunque el .json
                   # no se haya actualizado (cada virtual escucha en 19100+n)
                   "cups": next((q for q, u in sorted(en_cups.items())
                                 if u == "socket://127.0.0.1:%d" % (19100 + com)), ""),
                   "wine": os.path.realpath(os.path.join(WINE_DOS, "com%d" % com))
                   == os.path.realpath(dev) if os.path.isdir(WINE_DOS) else False})
    vs.sort(key=lambda v: v["com"])
    return vs


def wine_enlazar(com, quitar=False):
    """Programas de Windows (Wine): COMn de Wine = el enlace ~/.wine/dosdevices/comN."""
    if not os.path.isdir(WINE_DOS):
        return False
    enlace = os.path.join(WINE_DOS, "com%d" % com)
    try:
        if os.path.islink(enlace) or os.path.exists(enlace):
            os.unlink(enlace)
        if not quitar:
            os.symlink(DEV_COM % com, enlace)
        return True
    except Exception:
        return False


def prueba_virtual(dev, nombre):
    """Escribe en el COM como lo haría un programa: prueba la cadena completa."""
    texto = ("\x1b@FactuPOS - Soporte Real\n--- PRUEBA DE IMPRESORA VIRTUAL ---\n"
             "Impresora: %s\nPuerto: %s\nSi lee esto, el puerto quedo bien.\n\n\n\n\n"
             % (nombre, dev.replace("/dev/tty", "")))
    fd = os.open(dev, os.O_WRONLY | os.O_NOCTTY)
    try:
        os.write(fd, texto.encode("latin-1", "replace"))
    finally:
        os.close(fd)


# ---------- impresoras de red (1.3.0, #2831) ----------
PUERTOS_RED = (9100, 631, 515, 445)        # RAW/JetDirect · IPP/CUPS · LPD · Windows (SMB)
SMB_BACKEND = "/usr/lib/cups/backend/smb"


def mis_redes():
    """(IPs propias, hosts a revisar): la /24 de cada placa con IPv4 (no loopback)."""
    _rc, out = sh(["ip", "-4", "-o", "addr", "show", "scope", "global"])
    propias, hosts = set(), []
    for m in re.finditer(r"inet (\d+\.\d+\.\d+)\.(\d+)/(\d+)", out):
        base = m.group(1)
        propias.add("%s.%s" % (base, m.group(2)))
        for i in range(1, 255):
            ip = "%s.%d" % (base, i)
            if ip not in hosts:
                hosts.append(ip)
    return propias, [h for h in hosts if h not in propias]


def puerto_abierto(ip, puerto, espera=0.6):
    try:
        with socket.create_connection((ip, puerto), timeout=espera):
            return True
    except Exception:
        return False


def nombre_equipo(ip):
    try:
        return socket.gethostbyaddr(ip)[0].split(".")[0]
    except Exception:
        return ""


def colas_cups_compartidas(ip):
    """Impresoras que un equipo Linux/Mac comparte por CUPS (su pagina /printers/).
    Ojo: CUPS escribe los enlaces en MAYUSCULAS (<A HREF=...>): el patron va con re.I."""
    try:
        with urllib.request.urlopen("http://%s:631/printers/" % ip, timeout=3) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception:
        return None                     # no es un CUPS (o no comparte): es una impresora IPP
    return sorted(set(urllib.parse.unquote(n)
                      for n in re.findall(r'href="/printers/([^"/?#]+)"', html, re.I)))


def impresoras_windows(ip):
    """Impresoras compartidas por un equipo Windows (smbclient anonimo). None = no se pudo
    listar (sin smbclient o pide usuario): se ofrece igual y se escribe el nombre a mano."""
    if not shutil.which("smbclient"):
        return None
    rc, out = sh(["timeout", "8", "smbclient", "-L", "//" + ip, "-N", "-g"])
    if rc != 0:
        return None
    return [l.split("|")[1] for l in out.splitlines()
            if l.startswith("Printer|") and len(l.split("|")) > 1]


def buscar_en_red(avance=None):
    """Recorre la red local y devuelve una lista de hallazgos:
    {uri, titulo, sub, nombre, tipo: 'raw'|'ipp'|'cups'|'lpd'|'smb', pide_share}"""
    _propias, hosts = mis_redes()
    abiertos = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=128) as ex:
        futs = {ex.submit(puerto_abierto, ip, pt): (ip, pt)
                for ip in hosts for pt in PUERTOS_RED}
        hechos = 0
        for f in concurrent.futures.as_completed(futs):
            hechos += 1
            if avance and hechos % 200 == 0:
                avance(hechos, len(futs))
            if f.result():
                ip, pt = futs[f]
                abiertos.setdefault(ip, set()).add(pt)

    def clasificar(ip):
        pts = abiertos[ip]
        equipo = nombre_equipo(ip)
        quien = ("%s (%s)" % (equipo, ip)) if equipo else ip
        res = []
        if 631 in pts:
            colas = colas_cups_compartidas(ip)
            if colas:
                for c in colas:
                    res.append({"uri": "ipp://%s:631/printers/%s" % (ip, urllib.parse.quote(c)),
                                "titulo": "%s · compartida por %s" % (c, quien),
                                "sub": "Equipo con impresora compartida (Linux / FactuPOS OS)",
                                "nombre": c, "tipo": "cups"})
            elif colas is None:
                res.append({"uri": "ipp://%s/ipp/print" % ip,
                            "titulo": "Impresora de red %s" % quien,
                            "sub": "IPP (puerto 631)", "nombre": equipo or "Red_" + ip,
                            "tipo": "ipp"})
        if 9100 in pts and not any(r["tipo"] == "ipp" for r in res):
            res.append({"uri": "socket://%s:9100" % ip,
                        "titulo": "Impresora de red %s" % quien,
                        "sub": "Directa por IP, puerto 9100 (tiquetes y la mayoría de impresoras)",
                        "nombre": equipo or "Red_" + ip, "tipo": "raw"})
        if 515 in pts and not res:
            res.append({"uri": "lpd://%s/" % ip, "titulo": "Impresora de red %s" % quien,
                        "sub": "LPD (puerto 515)", "nombre": equipo or "Red_" + ip,
                        "tipo": "lpd"})
        if 445 in pts and 631 not in pts:
            comp = impresoras_windows(ip)
            if comp:
                for c in comp:
                    res.append({"uri": "smb://%s/%s" % (ip, urllib.parse.quote(c)),
                                "titulo": "%s · compartida por %s" % (c, quien),
                                "sub": "Equipo Windows con impresora compartida",
                                "nombre": c, "tipo": "smb"})
            elif comp is None:
                res.append({"uri": "smb://%s/" % ip, "pide_share": True,
                            "titulo": "Equipo Windows %s" % quien,
                            "sub": "Puede compartir impresoras: en el paso siguiente se escribe "
                                   "el nombre de la impresora compartida",
                            "nombre": equipo or "Windows_" + ip, "tipo": "smb"})
        return res

    hallazgos = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        for res in ex.map(clasificar, sorted(abiertos, key=lambda i: tuple(map(int, i.split("."))))):
            hallazgos.extend(res)
    return hallazgos


def enviar_socket(ip, puerto, datos, espera=5):
    """Prueba directa a una impresora de red RAW (9100), sin pasar por CUPS."""
    with socket.create_connection((ip, int(puerto)), timeout=espera) as s:
        s.sendall(datos)


def _label(txt, clase=None, wrap=False, xalign=0):
    lab = Gtk.Label(label=txt, xalign=xalign)
    if wrap:
        lab.set_line_wrap(True)
    if clase:
        lab.get_style_context().add_class(clase)
    return lab


class Wizard(Gtk.Window):
    PASOS = [("type", "1 · Conexión"), ("device", "2 · Dispositivo"),
             ("config", "3 · Configurar"), ("install", "4 · Instalar")]

    def __init__(self):
        super().__init__(title="FactuPOS · Gestión de Impresoras")
        self.set_default_size(860, 580)   # 1.4.5: cabe «+ Impresora PDF»
        self.set_position(Gtk.WindowPosition.CENTER)

        self.conn_type = "serial"
        self._found = []
        self._impresoras = []
        self._virtuales = []
        self._instalada = ""

        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        head = Gtk.Box(spacing=10)
        head.set_border_width(14)
        tit = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        tit.pack_start(_label("FactuPOS · Gestión de Impresoras", "fp-title"), False, False, 0)
        tit.pack_start(_label("Instale, pruebe y desinstale las impresoras de este equipo",
                              "fp-sub"), False, False, 0)
        head.pack_start(tit, True, True, 0)
        ver = _label("v" + VERSION, "fp-ver")
        ver.set_valign(Gtk.Align.START)
        head.pack_end(ver, False, False, 0)
        root.pack_start(head, False, False, 0)
        root.pack_start(Gtk.Separator(), False, False, 0)

        # Indicador de pasos (solo en el asistente).
        self.pasos_box = Gtk.Box(spacing=6)
        self.pasos_box.set_border_width(10)
        self.pasos_box.set_halign(Gtk.Align.CENTER)
        self.pasos_lbl = {}
        for clave, txt in self.PASOS:
            lab = _label(txt, "fp-paso")
            self.pasos_lbl[clave] = lab
            self.pasos_box.pack_start(lab, False, False, 0)
        self.pasos_box.set_no_show_all(True)
        root.pack_start(self.pasos_box, False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_border_width(16)
        root.pack_start(self.stack, True, True, 0)

        self._page_home()
        self._page_type()
        self._page_device()
        self._page_config()
        self._page_install()
        self._page_done()

        # Detalle tecnico: plegado; el usuario no lo necesita para trabajar.
        self.logbuf = Gtk.TextBuffer()
        logview = Gtk.TextView(buffer=self.logbuf)
        logview.set_editable(False)
        logview.set_cursor_visible(False)
        logview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        logview.get_style_context().add_class("fp-log")
        logsc = Gtk.ScrolledWindow()
        logsc.set_min_content_height(90)
        logsc.add(logview)
        self.expander = Gtk.Expander(label="Detalle técnico")
        self.expander.add(logsc)
        self.expander.set_border_width(6)
        root.pack_start(Gtk.Separator(), False, False, 0)
        root.pack_start(self.expander, False, False, 0)

        nav = Gtk.Box(spacing=8)
        nav.set_border_width(12)
        btn_close = Gtk.Button(label="Cerrar")
        btn_close.connect("clicked", lambda *_: self.destroy())
        btn_upd = Gtk.Button(label="Verificar versión")
        btn_upd.set_tooltip_text("Buscar e instalar la última versión (v%s)" % VERSION)
        btn_upd.connect("clicked", self._check_update_manual)
        nav.pack_start(btn_close, False, False, 0)
        nav.pack_start(btn_upd, False, False, 0)

        self.btn_nueva = Gtk.Button(label="+  Instalar impresora")
        self.btn_nueva.get_style_context().add_class("suggested-action")
        self.btn_nueva.connect("clicked", self.on_nueva)
        self.btn_virtual = Gtk.Button(label="+  Impresora virtual")
        self.btn_virtual.set_tooltip_text("Crear una impresora con el nombre que quiera, en un "
                                          "puerto COM, que imprime en una de las ya instaladas")
        self.btn_virtual.connect("clicked", self.on_virtual_nueva)
        self.btn_pdf = Gtk.Button(label="+  Impresora PDF")
        self.btn_pdf.set_tooltip_text("Crear una impresora que guarda lo que se imprime como "
                                      "archivo PDF en la carpeta «PDF»")
        self.btn_pdf.connect("clicked", self.on_pdf_nueva)
        self.btn_refrescar = Gtk.Button(label="Actualizar lista")
        self.btn_refrescar.connect("clicked", lambda *_: self.refrescar_lista())
        self.btn_next = Gtk.Button(label="Siguiente")
        self.btn_next.get_style_context().add_class("suggested-action")
        self.btn_next.connect("clicked", self.on_next)
        self.btn_back = Gtk.Button(label="Atrás")
        self.btn_back.connect("clicked", self.on_back)
        self.btn_cancel = Gtk.Button(label="Cancelar")
        self.btn_cancel.connect("clicked", lambda *_: self.ir_inicio())
        for btn in (self.btn_nueva, self.btn_next):
            nav.pack_end(btn, False, False, 0)
        nav.pack_end(self.btn_virtual, False, False, 0)
        nav.pack_end(self.btn_pdf, False, False, 0)
        nav.pack_end(self.btn_refrescar, False, False, 0)
        nav.pack_end(self.btn_back, False, False, 0)
        nav.pack_end(self.btn_cancel, False, False, 0)
        for btn in (self.btn_nueva, self.btn_virtual, self.btn_pdf, self.btn_refrescar, self.btn_next,
                    self.btn_back, self.btn_cancel):
            btn.set_no_show_all(True)
        root.pack_start(nav, False, False, 0)

        self.pages = ["type", "device", "config", "install", "done"]
        self.idx = -1          # -1 = pantalla de inicio (lista de impresoras)
        self._show()
        self.refrescar_lista()

    # ---------- paginas ----------
    def _page_home(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(_label("Impresoras de este equipo", "fp-step"), False, False, 0)
        self.lista = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.add(self.lista)
        box.pack_start(sc, True, True, 0)
        self.lbl_home = _label("", "fp-muted", wrap=True)
        box.pack_start(self.lbl_home, False, False, 0)
        self.stack.add_named(box, "home")

    def _opcion(self, grupo, titulo, desc):
        rb = Gtk.RadioButton.new_from_widget(grupo)
        rb.set_mode(False)       # se ve como tarjeta, no como circulito
        rb.get_style_context().add_class("fp-opcion")
        cont = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        cont.pack_start(_label(titulo, "fp-card-t"), False, False, 0)
        cont.pack_start(_label(desc, "fp-muted", wrap=True), False, False, 0)
        rb.add(cont)
        return rb

    def _page_type(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(_label("¿Cómo está conectada la impresora?", "fp-step"), False, False, 0)
        self.rb_usb = self._opcion(
            None, "USB directo",
            "La impresora se conecta con un cable USB normal. Es lo más común en "
            "impresoras de tiquetes nuevas (Epson TM-T20, TM-T88, Xprinter…).")
        self.rb_serial = self._opcion(
            self.rb_usb, "Serial (adaptador USB → Serial)",
            "La impresora tiene un puerto serial (DB9/DB25) y se conecta con un adaptador. "
            "Ejemplo: Epson TM-U220 de tiquetes.")
        self.rb_red = self._opcion(
            self.rb_usb, "Red (cable o WiFi)",
            "Busca en la red las impresoras con IP y los equipos que comparten una impresora "
            "(otra caja, una PC con Windows o Linux) y la instala en este equipo.")
        self.rb_serial.set_active(True)
        box.pack_start(self.rb_serial, False, False, 0)
        box.pack_start(self.rb_usb, False, False, 0)
        box.pack_start(self.rb_red, False, False, 0)
        box.pack_start(_label("Antes de seguir: encienda la impresora y conecte el cable.",
                              "fp-sub"), False, False, 6)
        self.stack.add_named(box, "type")

    def _page_device(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(_label("Elija el dispositivo", "fp-step"), False, False, 0)
        self.dev_list = Gtk.ListBox()
        self.dev_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.set_min_content_height(150)
        sc.add(self.dev_list)
        box.pack_start(sc, True, True, 0)
        fila = Gtk.Box(spacing=8)
        b = Gtk.Button(label="Volver a detectar")
        b.connect("clicked", lambda *_: self.detect_devices())
        fila.pack_start(b, False, False, 0)
        self.lbl_dev_hint = _label("", "fp-sub", wrap=True)
        fila.pack_start(self.lbl_dev_hint, True, True, 0)
        box.pack_start(fila, False, False, 0)
        # Red: agregar a mano una IP que la busqueda no encontro (otra subred, VPN...).
        self.manual_box = Gtk.Box(spacing=8)
        self.manual_box.pack_start(_label("¿No aparece? IP de la impresora:"), False, False, 0)
        self.ent_ip = Gtk.Entry()
        self.ent_ip.set_placeholder_text("192.168.1.50")
        self.ent_ip.set_width_chars(16)
        self.manual_box.pack_start(self.ent_ip, False, False, 0)
        b_ip = Gtk.Button(label="Agregar")
        b_ip.connect("clicked", self.on_ip_manual)
        self.manual_box.pack_start(b_ip, False, False, 0)
        self.manual_box.set_no_show_all(True)
        box.pack_start(self.manual_box, False, False, 0)
        self.stack.add_named(box, "device")

    def _page_config(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(_label("Póngale nombre y pruébela", "fp-step"), False, False, 0)

        row = Gtk.Box(spacing=8)
        row.pack_start(_label("Nombre:"), False, False, 0)
        self.ent_name = Gtk.Entry()
        self.ent_name.set_text("TM-U220")
        self.ent_name.connect("changed", self._on_nombre)
        row.pack_start(self.ent_name, True, True, 0)
        box.pack_start(row, False, False, 0)
        self.lbl_nombre = _label("", "fp-muted", wrap=True)
        box.pack_start(self.lbl_nombre, False, False, 0)

        self.serial_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("fp-card")
        card.pack_start(_label("Velocidad del puerto serial", "fp-card-t"), False, False, 0)
        card.pack_start(_label(
            "Toque «Probar todas las velocidades» y mire la impresora: la velocidad correcta "
            "imprime texto legible; si salen garabatos, esa NO es. Después elíjala aquí.",
            "fp-muted", wrap=True), False, False, 0)
        rowb = Gtk.Box(spacing=8)
        rowb.pack_start(_label("Velocidad (baud):"), False, False, 0)
        self.combo_baud = Gtk.ComboBoxText()
        for b in BAUDS:
            self.combo_baud.append_text(b)
        self.combo_baud.set_active(0)
        rowb.pack_start(self.combo_baud, False, False, 0)
        card.pack_start(rowb, False, False, 0)

        rowt = Gtk.Box(spacing=8)
        self.btn_sweep = Gtk.Button(label="Probar todas las velocidades")
        self.btn_sweep.connect("clicked", self.on_sweep)
        self.btn_test = Gtk.Button(label="Imprimir prueba")
        self.btn_test.connect("clicked", self.on_test)
        rowt.pack_start(self.btn_sweep, False, False, 0)
        rowt.pack_start(self.btn_test, False, False, 0)
        card.pack_start(rowt, False, False, 0)
        self.lbl_prueba = _label("", "fp-muted", wrap=True)
        card.pack_start(self.lbl_prueba, False, False, 0)

        avz = Gtk.Expander(label="Opciones avanzadas")
        rowf = Gtk.Box(spacing=8)
        rowf.set_border_width(6)
        rowf.pack_start(_label("Control de flujo:"), False, False, 0)
        self.combo_flow = Gtk.ComboBoxText()
        for f in FLOWS:
            self.combo_flow.append_text(f)
        self.combo_flow.set_active(0)  # dtrdsr
        rowf.pack_start(self.combo_flow, False, False, 0)
        rowf.pack_start(_label("(dtrdsr es el de fábrica de la TM-U220)", "fp-muted"),
                        False, False, 0)
        avz.add(rowf)
        card.pack_start(avz, False, False, 0)
        self.serial_box.pack_start(card, False, False, 0)
        box.pack_start(self.serial_box, False, False, 0)

        # 1.4.4 (#3420): USB y serial — RAW (FactuPOS Print) o driver FactuPOS térmica.
        self.driver_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        cardd = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        cardd.get_style_context().add_class("fp-card")
        cardd.pack_start(_label("¿Desde dónde va a imprimir?", "fp-card-t"), False, False, 0)
        self.rb_drv_raw = Gtk.RadioButton.new_with_label_from_widget(
            None, "FactuPOS Print (tiquetes y facturas de FactuPOS, cola RAW)")
        self.rb_drv_term = Gtk.RadioButton.new_with_label_from_widget(
            self.rb_drv_raw, "El navegador y cualquier programa (driver FactuPOS térmica 80/58 mm)")
        cardd.pack_start(self.rb_drv_raw, False, False, 0)
        cardd.pack_start(self.rb_drv_term, False, False, 0)
        cardd.pack_start(_label("¿Las dos? Instálela dos veces con distinto nombre: una de cada "
                                "tipo. Es la misma impresora.", "fp-muted", wrap=True),
                         False, False, 0)
        self.driver_box.pack_start(cardd, False, False, 0)
        self.driver_box.set_no_show_all(True)
        box.pack_start(self.driver_box, False, False, 0)

        # Red (1.3.0): tipo de cola, recurso de Windows y prueba directa.
        self.red_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        cardr = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        cardr.get_style_context().add_class("fp-card")
        cardr.pack_start(_label("¿Qué imprime?", "fp-card-t"), False, False, 0)
        self.rb_red_raw = Gtk.RadioButton.new_with_label_from_widget(
            None, "Tiquetes / facturas de FactuPOS (impresora de tiquetes, cola RAW)")
        self.rb_red_hoja = Gtk.RadioButton.new_with_label_from_widget(
            self.rb_red_raw, "Hojas (carta / oficio) desde cualquier programa (controlador automático)")
        self.rb_red_term = Gtk.RadioButton.new_with_label_from_widget(
            self.rb_red_raw, "Tiquetes desde el navegador y cualquier programa (driver FactuPOS térmica)")
        cardr.pack_start(self.rb_red_raw, False, False, 0)
        cardr.pack_start(self.rb_red_hoja, False, False, 0)
        cardr.pack_start(self.rb_red_term, False, False, 0)
        self.smb_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.smb_box.pack_start(_label("Impresora compartida por Windows", "fp-card-t"),
                                False, False, 4)
        self.lbl_smb = _label("", "fp-muted", wrap=True)
        self.smb_box.pack_start(self.lbl_smb, False, False, 0)
        rs = Gtk.Box(spacing=8)
        rs.pack_start(_label("Nombre compartido:"), False, False, 0)
        self.ent_share = Gtk.Entry()
        self.ent_share.set_placeholder_text("ej. EPSON-CAJA1")
        rs.pack_start(self.ent_share, True, True, 0)
        self.smb_box.pack_start(rs, False, False, 0)
        ru = Gtk.Box(spacing=8)
        ru.pack_start(_label("Usuario de Windows:"), False, False, 0)
        self.ent_smb_user = Gtk.Entry()
        self.ent_smb_user.set_placeholder_text("si la pide")
        ru.pack_start(self.ent_smb_user, True, True, 0)
        ru.pack_start(_label("Clave:"), False, False, 0)
        self.ent_smb_pass = Gtk.Entry()
        self.ent_smb_pass.set_visibility(False)
        ru.pack_start(self.ent_smb_pass, True, True, 0)
        self.smb_box.pack_start(ru, False, False, 0)
        self.smb_box.set_no_show_all(True)
        cardr.pack_start(self.smb_box, False, False, 0)
        rp = Gtk.Box(spacing=8)
        self.btn_test_red = Gtk.Button(label="Imprimir prueba")
        self.btn_test_red.connect("clicked", self.on_test_red)
        rp.pack_start(self.btn_test_red, False, False, 0)
        self.lbl_prueba_red = _label("", "fp-muted", wrap=True)
        rp.pack_start(self.lbl_prueba_red, True, True, 0)
        cardr.pack_start(rp, False, False, 0)
        self.red_box.pack_start(cardr, False, False, 0)
        self.red_box.set_no_show_all(True)
        box.pack_start(self.red_box, False, False, 0)
        self.stack.add_named(box, "config")

    def _page_install(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.pack_start(_label("Revise y presione Instalar", "fp-step"), False, False, 0)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.get_style_context().add_class("fp-card")
        self.lbl_summary = _label("", wrap=True)
        card.pack_start(self.lbl_summary, False, False, 0)
        box.pack_start(card, False, False, 0)
        self.chk_default = Gtk.CheckButton(label="Dejarla como impresora predeterminada del equipo")
        self.chk_default.set_active(True)
        box.pack_start(self.chk_default, False, False, 0)
        self.lbl_reemplazo = _label("", "fp-warn", wrap=True)
        box.pack_start(self.lbl_reemplazo, False, False, 0)
        box.pack_start(_label(
            "Puede pedir la contraseña UNA vez (es normal, como el control de Windows).",
            "fp-muted", wrap=True), False, False, 0)
        self.stack.add_named(box, "install")

    def _page_done(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.lbl_done = _label("¡Listo!", "fp-title")
        box.pack_start(self.lbl_done, False, False, 0)
        self.lbl_done2 = _label("", wrap=True)
        box.pack_start(self.lbl_done2, False, False, 0)
        self.btn_prueba_fin = Gtk.Button(label="Imprimir página de prueba")
        self.btn_prueba_fin.set_halign(Gtk.Align.START)
        self.btn_prueba_fin.connect("clicked",
                                    lambda *_: self.on_prueba_cola(self._instalada,
                                                                   self.lbl_prueba_fin))
        box.pack_start(self.btn_prueba_fin, False, False, 0)
        self.lbl_prueba_fin = _label("", "fp-muted", wrap=True)
        box.pack_start(self.lbl_prueba_fin, False, False, 0)
        self.stack.add_named(box, "done")

    # ---------- logica ----------
    def log(self, msg):
        GLib.idle_add(lambda: self.logbuf.insert(self.logbuf.get_end_iter(), msg + "\n"))

    # ---------- auto-actualización (botón + chequeo periódico) ----------
    def _check_update_loop(self):
        threading.Thread(target=self._check_update_once, daemon=True).start()
        return True   # repetir cada UPDATE_INTERVAL

    def _check_update_manual(self, *_):
        """Disparado por el botón: chequea y avisa el resultado."""
        self.log("Buscando actualizaciones…")
        threading.Thread(
            target=lambda: self._check_update_once(notify_uptodate=True),
            daemon=True).start()

    def _check_update_once(self, notify_uptodate=False):
        """Lee el manifest; si hay versión nueva, baja el .py y reinicia."""
        try:
            req = urllib.request.Request(UPDATE_MANIFEST,
                                         headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=8) as r:
                man = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if notify_uptodate:
                self.log("No se pudo verificar (sin conexión): %s" % e)
            return False
        newv = str(man.get("version", "")).strip()
        if not newv or _vtuple(newv) <= _vtuple(VERSION):
            if notify_uptodate:
                self.log("Ya estás en la última versión (v%s)." % VERSION)
            return False
        pyurl = man.get("py") or (UPDATE_BASE + "/factupos-printer-inst.py")
        self.log("⬇️ Descargando v%s…" % newv)
        try:
            with urllib.request.urlopen(pyurl, timeout=25) as r:
                data = r.read()
        except Exception as e:
            self.log("Descarga falló: %s" % e)
            return False
        if (b"Instalador de Impresoras" not in data and b"Impresoras" not in data) \
                or b"def main(" not in data:
            self.log("Contenido inválido, se descarta.")
            return False
        try:
            os.makedirs(os.path.dirname(UPDATE_PY_LOCAL), exist_ok=True)
            tmp = UPDATE_PY_LOCAL + ".new"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, UPDATE_PY_LOCAL)
        except Exception as e:
            self.log("No se pudo guardar la actualización: %s" % e)
            return False
        self.log("Actualizado a v%s, reiniciando…" % newv)
        GLib.timeout_add_seconds(1, self._restart_self)
        return False

    def _restart_self(self):
        try:
            py = UPDATE_PY_LOCAL if os.path.exists(UPDATE_PY_LOCAL) else os.path.abspath(__file__)
            os.execv(sys.executable, [sys.executable, py] + sys.argv[1:])
        except Exception as e:
            self.log("No se pudo reiniciar: %s" % e)
        return False

    # ---------- inicio: impresoras de este equipo (#2831) ----------
    def refrescar_lista(self):
        def run():
            imps = listar_impresoras()
            GLib.idle_add(self._pintar_lista, imps, impresoras_ocultas(), listar_virtuales())
        threading.Thread(target=run, daemon=True).start()

    def _pintar_lista(self, imps, ocultas=(), virtuales=()):
        self._impresoras = imps
        self._virtuales = list(virtuales)
        for hijo in self.lista.get_children():
            self.lista.remove(hijo)
        if not imps:
            vacio = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            vacio.set_valign(Gtk.Align.CENTER)
            vacio.pack_start(_label("Este equipo no tiene impresoras instaladas.", "fp-vacio",
                                    xalign=0.5), False, False, 20)
            vacio.pack_start(_label("Toque «+ Instalar impresora» para agregar una.",
                                    "fp-muted", xalign=0.5), False, False, 0)
            self.lista.pack_start(vacio, False, False, 0)
            self.lbl_home.set_text("")
        for p in imps:
            self.lista.pack_start(self._tarjeta(p), False, False, 0)
        if imps:
            self.lbl_home.set_text(
                "%d impresora%s instalada%s." % (len(imps), "" if len(imps) == 1 else "s",
                                                 "" if len(imps) == 1 else "s"))
        if getattr(self, "_aviso_home", ""):
            self.lbl_home.set_text(self._aviso_home)
            self._aviso_home = ""
        if ocultas:
            caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            caja.pack_start(_label("Impresoras de la red ocultas", "fp-sub"), False, False, 8)
            for n in ocultas:
                fila = Gtk.Box(spacing=8)
                fila.pack_start(_label(n, "fp-muted"), True, True, 0)
                res = _label("", "fp-muted")
                res.set_no_show_all(True)
                fila.pack_start(res, False, False, 0)
                b = Gtk.Button(label="Volver a mostrar")
                b.set_tooltip_text("Que este equipo la vuelva a agregar sola desde la red")
                b.connect("clicked", lambda _b, n=n, r=res: self.on_mostrar(n, r))
                fila.pack_start(b, False, False, 0)
                caja.pack_start(fila, False, False, 0)
            self.lista.pack_start(caja, False, False, 0)
        if virtuales:
            self.lista.pack_start(_label("Impresoras virtuales (puerto COM)", "fp-step"),
                                  False, False, 8)
            nombres = {p["nombre"] for p in imps}
            for v in virtuales:
                self.lista.pack_start(self._tarjeta_virtual(v, v["cola"] in nombres),
                                      False, False, 0)
        self.lista.show_all()
        return False

    def _tarjeta(self, p):
        card = Gtk.Box(spacing=12)
        card.get_style_context().add_class("fp-card")
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        fila = Gtk.Box(spacing=8)
        fila.pack_start(_label(p["nombre"], "fp-card-t"), False, False, 0)
        if p["default"]:
            fila.pack_start(_label("Predeterminada", "fp-badge"), False, False, 0)
        if not p["lista"]:
            fila.pack_start(_label("Detenida", "fp-badge-off"), False, False, 0)
        if p.get("auto"):
            aut = _label("De la red", "fp-badge")
            aut.set_tooltip_text("Este equipo la agregó solo porque otro equipo la comparte")
            fila.pack_start(aut, False, False, 0)
        info.pack_start(fila, False, False, 0)
        det = _label("%s · %s" % (p["tipo"], p["detalle"]), "fp-muted")
        det.set_ellipsize(Pango.EllipsizeMode.END)
        det.set_tooltip_text(ocultar_clave(p["uri"]))
        info.pack_start(det, False, False, 0)
        res = _label("", "fp-muted", wrap=True)
        res.set_no_show_all(True)
        info.pack_start(res, False, False, 0)
        card.pack_start(info, True, True, 0)

        botones = Gtk.Box(spacing=6)
        botones.set_valign(Gtk.Align.CENTER)
        b_prueba = Gtk.Button(label="Prueba")
        b_prueba.set_tooltip_text("Imprimir una página de prueba")
        b_prueba.connect("clicked", lambda *_: self.on_prueba_cola(p["nombre"], res))
        botones.pack_start(b_prueba, False, False, 0)
        if p["uri"].startswith("cups-pdf:"):
            b_carp = Gtk.Button(label="Abrir carpeta")
            b_carp.set_tooltip_text("Abrir la carpeta donde quedan los PDF (%s)" % CARPETA_PDF)
            b_carp.connect("clicked", lambda *_: abrir_carpeta_pdf())
            botones.pack_start(b_carp, False, False, 0)
        b_def = Gtk.Button(label="Predeterminada")
        b_def.set_tooltip_text("Dejarla como impresora predeterminada del equipo")
        b_def.set_sensitive(not p["default"])
        b_def.connect("clicked", lambda *_: self.on_predeterminada(p["nombre"], res))
        botones.pack_start(b_def, False, False, 0)
        b_quitar = Gtk.Button(label="Desinstalar")
        b_quitar.get_style_context().add_class("fp-peligro")
        b_quitar.connect("clicked", lambda *_: self.on_desinstalar(p["nombre"], res,
                                                                   p.get("auto", False)))
        botones.pack_start(b_quitar, False, False, 0)
        card.pack_end(botones, False, False, 0)
        return card

    # ---------- impresoras virtuales (#3420) ----------
    def _tarjeta_virtual(self, v, cola_ok):
        card = Gtk.Box(spacing=12)
        card.get_style_context().add_class("fp-card")
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        fila = Gtk.Box(spacing=8)
        fila.pack_start(_label(v["nombre"], "fp-card-t"), False, False, 0)
        fila.pack_start(_label("COM%d" % v["com"], "fp-badge"), False, False, 0)
        if not v["activa"]:
            fila.pack_start(_label("Detenida", "fp-badge-off"), False, False, 0)
        if not cola_ok:
            fila.pack_start(_label("Impresora no instalada", "fp-badge-off"), False, False, 0)
        if v["cups"] and not helper_al_dia():
            vieja = _label("Falta actualizar", "fp-badge-off")
            vieja.set_tooltip_text("En el navegador el botón Imprimir puede salir gris: toque "
                                   "«Actualizar ahora»")
            fila.pack_start(vieja, False, False, 0)
        if not v["cups"]:
            sin = _label("El navegador no la ve", "fp-badge-off")
            sin.set_tooltip_text("Falta instalarla en el sistema: se arregla sola al actualizarse "
                                 "el equipo, o quítela y vuelva a crearla")
            fila.pack_start(sin, False, False, 0)
        info.pack_start(fila, False, False, 0)
        det = _label("Virtual · imprime en «%s» · puerto %s%s%s"
                     % (v["cola"], v["dev"],
                        " · en el navegador: «%s»" % v["cups"] if v["cups"] else "",
                        " · también COM%d en Wine" % v["com"] if v["wine"] else ""), "fp-muted")
        det.set_ellipsize(Pango.EllipsizeMode.END)
        info.pack_start(det, False, False, 0)
        res = _label("", "fp-muted", wrap=True)
        res.set_no_show_all(True)
        info.pack_start(res, False, False, 0)
        card.pack_start(info, True, True, 0)
        botones = Gtk.Box(spacing=6)
        botones.set_valign(Gtk.Align.CENTER)
        if not v["cups"] or not helper_al_dia():
            b_act = Gtk.Button(label="Actualizar ahora")
            b_act.get_style_context().add_class("suggested-action")
            b_act.set_tooltip_text("Instalar la versión nueva del componente y dejarla visible "
                                   "en el navegador")
            b_act.connect("clicked", lambda *_: self.on_actualizar_ahora(res))
            botones.pack_start(b_act, False, False, 0)
        b_prueba = Gtk.Button(label="Prueba")
        b_prueba.set_tooltip_text("Escribir una prueba en el COM%d, como lo haría un programa"
                                  % v["com"])
        b_prueba.set_sensitive(v["activa"])
        b_prueba.connect("clicked", lambda *_: self.on_prueba_virtual(v, res))
        botones.pack_start(b_prueba, False, False, 0)
        b_quitar = Gtk.Button(label="Quitar")
        b_quitar.get_style_context().add_class("fp-peligro")
        b_quitar.connect("clicked", lambda *_: self.on_virtual_quitar(v, res))
        botones.pack_start(b_quitar, False, False, 0)
        card.pack_end(botones, False, False, 0)
        return card

    def on_prueba_virtual(self, v, lab):
        self._mostrar(lab, "Enviando la prueba por el COM%d…" % v["com"], "fp-muted")

        def run():
            try:
                prueba_virtual(v["dev"], v["nombre"])
                self.log("Prueba por COM%d (%s) -> '%s'" % (v["com"], v["dev"], v["cola"]))
                GLib.idle_add(self._mostrar, lab, "Prueba enviada por el COM%d. Revise «%s»."
                              % (v["com"], v["cola"]), "fp-ok")
            except Exception as e:
                self.log("Prueba por COM%d falló: %s" % (v["com"], e))
                GLib.idle_add(self._mostrar, lab,
                              "No se pudo escribir en el COM%d (vea el Detalle técnico)."
                              % v["com"], "fp-err")
        threading.Thread(target=run, daemon=True).start()

    def _falta_componente(self, para="Las impresoras virtuales", pdf=False):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.INFO,
                                buttons=Gtk.ButtonsType.NONE,
                                text="Falta actualizar un componente del equipo")
        dlg.format_secondary_text(
            "%s necesita%s la versión nueva del paquete. Se actualiza sola en menos de una "
            "hora, o puede actualizarlo ahora." % (para, "n" if para.endswith("s") else ""))
        dlg.add_button("Después", Gtk.ResponseType.CANCEL)
        b = dlg.add_button("Actualizar ahora", Gtk.ResponseType.OK)
        b.get_style_context().add_class("suggested-action")
        resp = dlg.run()
        dlg.destroy()
        if resp == Gtk.ResponseType.OK:
            self.on_actualizar_ahora(self.lbl_home, pdf=pdf)

    def on_actualizar_ahora(self, lab, pdf=False):
        """#3420: pantalla al día y paquete atrasado -> se actualiza el paquete desde acá
        (en una PC fuera de la red no hay otra forma rápida) y se instalan las virtuales
        en el sistema (vport-sync; el postinst ya lo hace, esto también repara)."""
        self._mostrar(lab, "Actualizando el componente… puede tardar un par de minutos.",
                      "fp-muted")

        def run():
            if not helper_al_dia() or (pdf and not helper_sabe("pdf-add")):
                actualizar_paquete(self.log)
            if pdf:
                self._aviso_home = ("Listo: ya puede crear la impresora PDF."
                                    if helper_sabe("pdf-add") else
                                    "No se pudo actualizar el componente (vea el Detalle "
                                    "técnico). Se va a actualizar solo en menos de una hora.")
                GLib.idle_add(self.refrescar_lista)
                return
            if not helper_sabe("vport-sync"):
                self._aviso_home = ("No se pudo actualizar el componente (vea el Detalle "
                                    "técnico). Se va a actualizar solo en menos de una hora.")
                GLib.idle_add(self.refrescar_lista)
                return
            rc, out = sh(["pkexec", HELPER, "vport-sync"])
            self.log("vport-sync: %s" % out.strip())
            faltan = [v["nombre"] for v in listar_virtuales() if not v["cups"]]
            self._aviso_home = ("Listo: las impresoras virtuales ya aparecen en el navegador."
                                if not faltan else
                                "Todavía no se pudo instalar en el sistema: %s (vea el Detalle "
                                "técnico)." % ", ".join(faltan))
            GLib.idle_add(self.refrescar_lista)
        threading.Thread(target=run, daemon=True).start()

    # ---------- impresora PDF (#3494) ----------
    def on_pdf_nueva(self, *_):
        if not helper_sabe("pdf-add"):
            self._falta_componente("La impresora PDF", pdf=True)
            return
        usados = {p["nombre"] for p in self._impresoras}
        sugerido = "PDF"
        n = 1
        while sugerido in usados:
            n += 1
            sugerido = "PDF_%d" % n
        dlg = Gtk.Dialog(title="Nueva impresora PDF", transient_for=self, modal=True)
        dlg.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        b_ok = dlg.add_button("Crear", Gtk.ResponseType.OK)
        b_ok.get_style_context().add_class("suggested-action")
        caja = dlg.get_content_area()
        caja.set_spacing(8)
        caja.set_border_width(16)
        caja.pack_start(_label("Nueva impresora PDF", "fp-step"), False, False, 0)
        caja.pack_start(_label("Lo que se imprima en ella no sale en papel: queda guardado como "
                               "archivo PDF en la carpeta «PDF» de su usuario (%s)."
                               % CARPETA_PDF, "fp-muted", wrap=True), False, False, 0)
        fila = Gtk.Box(spacing=10)
        fila.pack_start(_label("Nombre"), False, False, 0)
        ent = Gtk.Entry()
        ent.set_text(sugerido)
        ent.set_max_length(60)
        ent.set_activates_default(True)
        fila.pack_start(ent, True, True, 0)
        caja.pack_start(fila, False, False, 4)
        chk_def = Gtk.CheckButton(label="Dejarla como impresora predeterminada del equipo")
        caja.pack_start(chk_def, False, False, 0)
        caja.pack_start(_label("La primera vez puede tardar un minuto: se instala el componente "
                               "PDF del sistema.", "fp-muted", wrap=True), False, False, 0)
        aviso = _label("", "fp-err", wrap=True)
        caja.pack_start(aviso, False, False, 0)
        dlg.set_default_response(Gtk.ResponseType.OK)
        dlg.show_all()
        while True:
            resp = dlg.run()
            if resp != Gtk.ResponseType.OK:
                dlg.destroy()
                return
            nombre = nombre_limpio(ent.get_text())
            if not nombre:
                aviso.set_text("Escriba un nombre para la impresora.")
            elif nombre in usados:
                aviso.set_text("Ya hay una impresora llamada «%s»: use otro nombre." % nombre)
            else:
                break
        predet = chk_def.get_active()
        dlg.destroy()
        self.lbl_home.set_text("Creando la impresora PDF «%s»…" % nombre)
        self.btn_pdf.set_sensitive(False)

        def run():
            cmd = ["pkexec", HELPER, "pdf-add", "--name", nombre]
            if predet:
                cmd.append("--default")
            try:     # sin el tope de 90 s de sh(): la primera vez instala el componente
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                                   env=dict(os.environ, LANG="C", LC_ALL="C"))
                rc, out = p.returncode, (p.stdout or "") + (p.stderr or "")
            except Exception as e:
                rc, out = 1, str(e)
            self.log("pdf-add '%s': %s" % (nombre, out.strip()[-1500:]))
            # Se comprueba con CUPS, no con lo que dijo el comando.
            ok = rc == 0 and any(p["nombre"] == nombre and p["uri"].startswith("cups-pdf:")
                                 for p in listar_impresoras())
            self._aviso_home = ("Lista: «%s». Lo que imprima ahí queda como PDF en %s."
                                % (nombre, CARPETA_PDF) if ok else
                                "No se pudo crear la impresora PDF (vea el Detalle técnico).")
            GLib.idle_add(self.btn_pdf.set_sensitive, True)
            GLib.idle_add(self.refrescar_lista)
        threading.Thread(target=run, daemon=True).start()

    def on_virtual_nueva(self, *_):
        if not helper_sabe("vport-add"):
            self._falta_componente()
            return
        colas = [p["nombre"] for p in self._impresoras]
        if not colas:
            dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                    message_type=Gtk.MessageType.INFO,
                                    buttons=Gtk.ButtonsType.OK,
                                    text="Primero instale una impresora")
            dlg.format_secondary_text("La impresora virtual imprime en una que ya esté "
                                      "instalada en este equipo.")
            dlg.run()
            dlg.destroy()
            return
        usados = {v["com"] for v in self._virtuales}
        libres = [n for n in range(1, COM_MAX + 1) if n not in usados]
        if not libres:
            return
        dlg = Gtk.Dialog(title="Nueva impresora virtual", transient_for=self, modal=True)
        dlg.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        b_ok = dlg.add_button("Crear", Gtk.ResponseType.OK)
        b_ok.get_style_context().add_class("suggested-action")
        caja = dlg.get_content_area()
        caja.set_spacing(8)
        caja.set_border_width(16)
        caja.pack_start(_label("Nueva impresora virtual", "fp-step"), False, False, 0)
        caja.pack_start(_label("Los programas imprimen en el puerto COM que elija, como si "
                               "hubiera una impresora serial conectada, y sale por la "
                               "impresora real.", "fp-muted", wrap=True), False, False, 0)
        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        ent = Gtk.Entry()
        ent.set_placeholder_text("Ejemplo: Tiquetes Caja 1")
        ent.set_max_length(60)
        cb_com = Gtk.ComboBoxText()
        for n in libres:
            cb_com.append(str(n), "COM%d" % n)
        cb_com.set_active(0)
        cb_cola = Gtk.ComboBoxText()
        for c in colas:
            cb_cola.append(c, c)
        cb_cola.set_active(0)
        for i, (t, w) in enumerate((("Nombre", ent), ("Puerto", cb_com),
                                     ("Imprime en", cb_cola))):
            grid.attach(_label(t), 0, i, 1, 1)
            w.set_hexpand(True)
            grid.attach(w, 1, i, 1, 1)
        caja.pack_start(grid, False, False, 4)
        chk_wine = Gtk.CheckButton(label="Que también lo vean los programas de Windows (Wine)")
        chk_wine.set_active(True)
        if os.path.isdir(WINE_DOS):
            caja.pack_start(chk_wine, False, False, 0)
        aviso = _label("", "fp-err", wrap=True)
        caja.pack_start(aviso, False, False, 0)
        dlg.show_all()
        while True:
            resp = dlg.run()
            if resp != Gtk.ResponseType.OK:
                dlg.destroy()
                return
            nombre = ent.get_text().strip()
            if nombre:
                break
            aviso.set_text("Escriba un nombre para la impresora virtual.")
        com = int(cb_com.get_active_id())
        cola = cb_cola.get_active_id()
        wine = chk_wine.get_active() and os.path.isdir(WINE_DOS)
        dlg.destroy()
        self.lbl_home.set_text("Creando «%s» en el COM%d…" % (nombre, com))

        def run():
            rc, out = sh(["pkexec", HELPER, "vport-add", "--nombre", nombre,
                          "--cola", cola, "--com", str(com)])
            self.log("vport-add COM%d '%s' -> '%s': %s" % (com, nombre, cola, out.strip()))
            # Se comprueba con el equipo: el puerto tiene que existir de verdad.
            ok = rc == 0 and "VPORT_OK" in out and os.path.exists(DEV_COM % com)
            if ok and wine:
                self.log("Wine COM%d: %s" % (com, "enlazado" if wine_enlazar(com)
                                              else "no se pudo enlazar"))
            if ok:
                m = re.search(r"VPORT_OK COM\d+ \S+ (\S+)", out)
                self._aviso_home = ("Lista: «%s» en el COM%d. En el navegador y los demás "
                                    "programas aparece como «%s»." % (nombre, com, m.group(1))
                                    if m else "Lista: «%s» en el COM%d." % (nombre, com))
            if not ok:
                # Se deja para _pintar_lista: si se pone aca, el contador de la lista lo tapa.
                self._aviso_home = "No se pudo crear la impresora virtual (vea el Detalle técnico)."
            GLib.idle_add(self.refrescar_lista)
        threading.Thread(target=run, daemon=True).start()

    def on_virtual_quitar(self, v, lab):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.NONE,
                                text="¿Quitar la impresora virtual «%s» (COM%d)?"
                                % (v["nombre"], v["com"]))
        dlg.format_secondary_text("Los programas que imprimen en el COM%d dejan de imprimir. "
                                  "La impresora «%s» no se toca." % (v["com"], v["cola"]))
        dlg.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        b = dlg.add_button("Sí, quitar", Gtk.ResponseType.OK)
        b.get_style_context().add_class("fp-peligro")
        resp = dlg.run()
        dlg.destroy()
        if resp != Gtk.ResponseType.OK:
            return
        if not helper_sabe("vport-remove"):
            self._falta_componente()
            return
        self._mostrar(lab, "Quitando…", "fp-muted")

        def run():
            rc, out = sh(["pkexec", HELPER, "vport-remove", "--com", str(v["com"])])
            self.log("vport-remove COM%d: %s" % (v["com"], out.strip()))
            if rc == 0 and "VPORT_REMOVE_OK" in out and not os.path.exists(v["dev"]):
                if v["wine"]:
                    wine_enlazar(v["com"], quitar=True)
                GLib.idle_add(self.refrescar_lista)
            else:
                GLib.idle_add(self._mostrar, lab, "No se pudo quitar (vea el Detalle técnico).",
                              "fp-err")
        threading.Thread(target=run, daemon=True).start()

    def _mostrar(self, lab, txt, clase):
        ctx = lab.get_style_context()
        for c in ("fp-ok", "fp-err", "fp-muted"):
            ctx.remove_class(c)
        ctx.add_class(clase)
        lab.set_text(txt)
        lab.show()
        return False

    def on_prueba_cola(self, nombre, lab):
        if not nombre:
            return
        self._mostrar(lab, "Enviando la prueba…", "fp-muted")
        es_pdf = any(p["nombre"] == nombre and p["uri"].startswith("cups-pdf:")
                     for p in self._impresoras)

        def run():
            rc, out = imprimir_prueba(nombre)
            self.log("Prueba por la cola '%s': %s" % (nombre, out.strip()))
            if rc == 0:
                GLib.idle_add(self._mostrar, lab,
                              "Prueba enviada: el PDF queda en %s (toque «Abrir carpeta»)."
                              % CARPETA_PDF if es_pdf else
                              "Prueba enviada. Revise la impresora.", "fp-ok")
            else:
                GLib.idle_add(self._mostrar, lab,
                              "No se pudo enviar la prueba (vea el Detalle técnico).", "fp-err")
        threading.Thread(target=run, daemon=True).start()

    def _privilegiado(self, accion, nombre, marca):
        """Corre una accion del helper. El auto-update solo cambia este .py: si el helper
        instalado (root, viene con el .deb) es anterior a 1.2.0 no conoce 'remove'/'default'.
        Entonces: lpadmin directo (sirve si el usuario esta en el grupo lpadmin) y, si CUPS
        dice Forbidden, pkexec lpadmin (pide la clave UNA vez). Visto en campo el 16-oct."""
        flag = "-x" if accion == "remove" else "-d"
        if helper_sabe(accion):
            rc, out = sh(["pkexec", HELPER, accion, "--name", nombre])
            self.log("%s '%s': %s" % (accion, nombre, out.strip()))
            if rc == 0 and marca in out:
                return True
            if not helper_viejo(out):
                return False
        rc, out = sh([LPADMIN, flag, nombre])
        self.log("lpadmin %s '%s' (helper anterior a 1.2.0): rc=%s %s"
                 % (flag, nombre, rc, out.strip()))
        if rc == 0:
            return True
        rc, out = sh(["pkexec", LPADMIN, flag, nombre])
        self.log("pkexec lpadmin %s '%s' (con clave): rc=%s %s"
                 % (flag, nombre, rc, out.strip()))
        return rc == 0

    def on_predeterminada(self, nombre, lab):
        self._mostrar(lab, "Cambiando la predeterminada…", "fp-muted")

        def run():
            self._privilegiado("default", nombre, "DEFAULT_OK")
            # Se comprueba con CUPS, no con lo que dijo el comando.
            ok = any(p["nombre"] == nombre and p["default"] for p in listar_impresoras())
            if ok:
                GLib.idle_add(self.refrescar_lista)
            else:
                GLib.idle_add(self._mostrar, lab,
                              "No se pudo cambiar (vea el Detalle técnico).", "fp-err")
        threading.Thread(target=run, daemon=True).start()

    def on_desinstalar(self, nombre, lab, auto=False):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.NONE,
                                text="¿Desinstalar «%s» de este equipo?" % nombre)
        if auto:
            dlg.format_secondary_text(
                "Esta impresora la agregó el equipo solo, porque otro equipo la comparte en la "
                "red. Se quita y no vuelve a aparecer. Si un día la necesita, abajo de la lista "
                "queda en «Impresoras de la red ocultas» con el botón «Volver a mostrar».")
        else:
            dlg.format_secondary_text(
                "Se quita de la lista de impresoras. Si FactuPOS u otro programa imprime en "
                "ella, deja de imprimir ahí hasta que la vuelva a instalar.")
        dlg.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        b = dlg.add_button("Sí, desinstalar", Gtk.ResponseType.OK)
        b.get_style_context().add_class("fp-peligro")
        resp = dlg.run()
        dlg.destroy()
        if resp != Gtk.ResponseType.OK:
            return
        self._mostrar(lab, "Desinstalando…", "fp-muted")

        def run():
            self._privilegiado("remove", nombre, "REMOVE_OK")
            if auto:
                # cups-browsed la recrea a los segundos si no quedo oculta: se espera y se
                # vuelve a mirar (en la .18 «desinstalaba» bien y volvia al recargar).
                import time
                time.sleep(8)
            # Se comprueba con CUPS: quedo desinstalada solo si ya no esta en la lista.
            sigue = any(p["nombre"] == nombre for p in listar_impresoras())
            if sigue and auto and not helper_sabe("unhide"):
                GLib.idle_add(self._mostrar, lab,
                              "Volvió a aparecer: falta actualizar un componente del equipo "
                              "(se actualiza solo en menos de una hora). Pruebe de nuevo después.",
                              "fp-err")
            elif sigue:
                GLib.idle_add(self._mostrar, lab,
                              "No se pudo desinstalar (vea el Detalle técnico).", "fp-err")
            else:
                self.log("'%s' desinstalada." % nombre)
                GLib.idle_add(self.refrescar_lista)
        threading.Thread(target=run, daemon=True).start()

    def on_mostrar(self, nombre, lab):
        self._mostrar(lab, "Un momento…", "fp-muted")

        def run():
            rc, out = sh(["pkexec", HELPER, "unhide", "--name", nombre])
            self.log("unhide '%s': %s" % (nombre, out.strip()))
            if rc == 0 and "UNHIDE_OK" in out:
                GLib.idle_add(self._mostrar, lab, "Listo, aparece en unos segundos.", "fp-ok")
                import time
                time.sleep(8)
                GLib.idle_add(self.refrescar_lista)
            else:
                GLib.idle_add(self._mostrar, lab, "No se pudo (vea el Detalle técnico).", "fp-err")
        threading.Thread(target=run, daemon=True).start()

    def on_nueva(self, *_):
        self.idx = 0
        self._instalada = ""
        self._show()

    def ir_inicio(self):
        self.idx = -1
        self._show()
        self.refrescar_lista()

    # ---------- asistente ----------
    def _fila_dev(self, dev, titulo, sub, info=None):
        row = Gtk.ListBoxRow()
        row.dev = dev
        row.info = info or {}
        cont = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        cont.get_style_context().add_class("fp-card")
        cont.pack_start(_label(titulo, "fp-card-t"), False, False, 0)
        if sub:
            cont.pack_start(_label(sub, "fp-muted"), False, False, 0)
        row.add(cont)
        return row

    def detect_devices(self):
        self.conn_type = ("serial" if self.rb_serial.get_active() else
                          ("red" if self.rb_red.get_active() else "usb"))
        self.manual_box.set_visible(self.conn_type == "red")
        for c in self.manual_box.get_children():
            c.show()
        for hijo in self.dev_list.get_children():
            self.dev_list.remove(hijo)
        self._found = []
        if self.conn_type == "serial":
            ports = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
            descs = {}
            if HAVE_SERIAL:
                try:
                    from serial.tools import list_ports
                    for p in list_ports.comports():
                        descs[p.device] = p.description
                except Exception:
                    pass
            self._pintar_devs([(p, p, descs.get(p, ""), None) for p in ports],
                              "Adaptadores serial detectados: %d",
                              "No se detectó ningún adaptador. Conecte el cable USB → Serial "
                              "y toque «Volver a detectar».")
        elif self.conn_type == "red":
            self.lbl_dev_hint.set_text("Buscando impresoras y equipos en la red… "
                                       "(tarda unos segundos)")

            def run_red():
                self.log("Buscando en la red (puertos %s)..." % ", ".join(map(str, PUERTOS_RED)))
                try:
                    hall = buscar_en_red(lambda h, t: GLib.idle_add(
                        self.lbl_dev_hint.set_text,
                        "Buscando en la red… %d%%" % (100 * h // max(t, 1))))
                except Exception as e:
                    self.log("Error buscando en la red: %s" % e)
                    hall = []
                for h in hall:
                    self.log("  %s -> %s" % (h["titulo"], h["uri"]))
                GLib.idle_add(self._pintar_devs,
                              [(h["uri"], h["titulo"], h["sub"], h) for h in hall],
                              "Encontrados en la red: %d",
                              "No se encontró ninguna impresora ni equipo que comparta una. "
                              "Revise que estén encendidos y en la misma red, o escriba la IP abajo.")
            threading.Thread(target=run_red, daemon=True).start()
        else:
            self.lbl_dev_hint.set_text("Buscando impresoras USB…")

            def run():
                self.log("Detectando impresoras USB (puede pedir contraseña)...")
                _rc, out = sh(["pkexec", HELPER, "detect-usb"])
                devs = []
                for line in out.splitlines():
                    line = line.strip()
                    if line.startswith("usb://"):
                        _t, modelo = describir_uri(line)
                        devs.append((line, modelo, line, None))
                GLib.idle_add(self._pintar_devs, devs, "Impresoras USB detectadas: %d",
                              "No se detectó ninguna impresora USB. Revise que esté encendida "
                              "y conectada, y toque «Volver a detectar».")
            threading.Thread(target=run, daemon=True).start()

    def _pintar_devs(self, devs, txt_ok, txt_nada):
        for dev, titulo, sub, info in devs:
            self.dev_list.add(self._fila_dev(dev, titulo, sub, info))
        self._found = [d[0] for d in devs]
        self.lbl_dev_hint.set_text((txt_ok % len(devs)) if devs else txt_nada)
        self.dev_list.show_all()
        primera = self.dev_list.get_row_at_index(0)
        if primera is not None:
            self.dev_list.select_row(primera)
        if self.conn_type == "usb" and devs:
            # Nombre sugerido: el modelo (EPSON TM-T20 -> EPSON_TM-T20).
            self.ent_name.set_text(nombre_limpio(devs[0][1]) or "Impresora")
        return False

    def _current_info(self):
        row = self.dev_list.get_selected_row()
        return getattr(row, "info", {}) if row is not None else {}

    def on_ip_manual(self, *_):
        ip = self.ent_ip.get_text().strip()
        if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
            self.lbl_dev_hint.set_text("Escriba una IP válida, por ejemplo 192.168.1.50")
            return
        self.lbl_dev_hint.set_text("Revisando %s…" % ip)

        def run():
            abiertos = [pt for pt in PUERTOS_RED if puerto_abierto(ip, pt, 2)]
            self.log("IP manual %s: puertos abiertos %s" % (ip, abiertos))
            if 9100 in abiertos:
                h = {"uri": "socket://%s:9100" % ip, "titulo": "Impresora de red %s" % ip,
                     "sub": "Agregada a mano · puerto 9100", "nombre": "Red_" + ip, "tipo": "raw"}
            elif 631 in abiertos:
                h = {"uri": "ipp://%s/ipp/print" % ip, "titulo": "Impresora de red %s" % ip,
                     "sub": "Agregada a mano · IPP", "nombre": "Red_" + ip, "tipo": "ipp"}
            else:
                # Igual se ofrece por 9100: puede estar apagada ahora.
                h = {"uri": "socket://%s:9100" % ip, "titulo": "Impresora de red %s" % ip,
                     "sub": "Agregada a mano · no respondió ahora (¿apagada?)",
                     "nombre": "Red_" + ip, "tipo": "raw"}
            GLib.idle_add(self._agregar_manual, h)
        threading.Thread(target=run, daemon=True).start()

    def _agregar_manual(self, h):
        row = self._fila_dev(h["uri"], h["titulo"], h["sub"], h)
        self.dev_list.insert(row, 0)
        self.dev_list.show_all()
        self.dev_list.select_row(row)
        self.lbl_dev_hint.set_text("Agregada: %s" % h["uri"])
        return False

    def _preparar_red(self):
        """Al entrar a Configurar con una impresora de red elegida."""
        h = self._current_info()
        nueva = h.get("uri") != getattr(self, "_red_elegida", None)
        self._red_elegida = h.get("uri")
        if nueva:     # al volver con «Atrás» no se pisa lo que el usuario cambio
            self.ent_name.set_text(nombre_limpio(h.get("nombre", "")) or "Impresora_red")
            # Lo compartido por otra caja FactuPOS y lo directo por 9100 suele ser de tiquetes.
            if h.get("tipo") in ("ipp",):
                self.rb_red_hoja.set_active(True)
            else:
                self.rb_red_raw.set_active(True)
        es_smb = h.get("tipo") == "smb"
        self.smb_box.set_visible(es_smb)
        if es_smb:
            for c in self.smb_box.get_children():
                c.show_all()
            if nueva:
                self.ent_share.set_text("" if h.get("pide_share") else
                                        urllib.parse.unquote(h["uri"].rstrip("/").rsplit("/", 1)[1]))
            falta = "" if os.path.exists(SMB_BACKEND) else (
                "⚠ A este equipo le falta el componente para impresoras de Windows "
                "(paquete smbclient). Pídalo a soporte antes de instalar.")
            self.lbl_smb.set_text(
                ("Escriba el nombre con que Windows comparte la impresora. " if h.get("pide_share")
                 else "") + "Si Windows pide usuario y clave, escríbalos. " + falta)
        self.btn_test_red.set_visible(h.get("uri", "").startswith("socket://"))
        self.lbl_prueba_red.set_text("" if h.get("uri", "").startswith("socket://") else
                                     "La prueba se imprime al terminar de instalar.")

    def on_test_red(self, *_):
        uri = self._current_device()
        if not uri.startswith("socket://"):
            return
        hostport = uri[9:].split("/")[0]
        ip, _, pt = hostport.partition(":")
        datos = ("\x1b@FactuPOS - Soporte Real\n--- PRUEBA DE RED ---\n%s\nOK!\n\n\n\n\n"
                 % hostport).encode("latin-1", "replace")
        self._mostrar(self.lbl_prueba_red, "Enviando…", "fp-muted")

        def run():
            try:
                enviar_socket(ip, pt or 9100, datos)
                self.log("Prueba directa enviada a %s" % hostport)
                GLib.idle_add(self._mostrar, self.lbl_prueba_red,
                              "Prueba enviada. Revise la impresora.", "fp-ok")
            except Exception as e:
                self.log("Prueba directa a %s: %s" % (hostport, e))
                GLib.idle_add(self._mostrar, self.lbl_prueba_red,
                              "No respondió (%s)." % e, "fp-err")
        threading.Thread(target=run, daemon=True).start()

    def _current_device(self):
        row = self.dev_list.get_selected_row()
        return getattr(row, "dev", "") if row is not None else ""

    def _on_nombre(self, *_):
        limpio = nombre_limpio(self.ent_name.get_text())
        txt = self.ent_name.get_text().strip()
        if not limpio:
            self.lbl_nombre.set_text("Escriba un nombre para la impresora.")
        elif limpio != txt:
            self.lbl_nombre.set_text("Va a quedar como: %s  (sin espacios ni / # comillas)"
                                     % limpio)
        else:
            self.lbl_nombre.set_text("")

    def on_sweep(self, *_):
        port = self._current_device()
        if not port:
            self.log("Primero elegí un puerto en el paso anterior.")
            return
        self.btn_sweep.set_sensitive(False)
        self._mostrar(self.lbl_prueba, "Probando velocidades, mire la impresora…", "fp-muted")
        self.log("Probando velocidades en %s ..." % port)

        def run():
            import time
            for b in BAUDS:
                ok = self._serial_write(port, b,
                                        "\n==== VELOCIDAD %s ====\nFactuPOS prueba\n\n\n" % b)
                self.log(("  enviado a %s baud" % b) if ok else ("  ERROR a %s baud" % b))
                time.sleep(2)
            self.log("Barrido terminado. Elegi la velocidad que salio legible.")
            GLib.idle_add(self._mostrar, self.lbl_prueba,
                          "Listo. Elija arriba la velocidad que salió legible.", "fp-ok")
            GLib.idle_add(self.btn_sweep.set_sensitive, True)
        threading.Thread(target=run, daemon=True).start()

    def on_test(self, *_):
        port = self._current_device()
        b = self.combo_baud.get_active_text() or "9600"
        # ESC @ (init) + texto + avances de linea
        data = "\x1b@FactuPOS - Soporte Real\n--- PRUEBA TM-U220 ---\n%s @ %s baud\nOK!\n\n\n\n" % (port, b)
        ok = self._serial_write(port, b, data)
        self.log("Prueba enviada a %s @ %s baud" % (port, b) if ok else "ERROR enviando prueba")
        if ok:
            self._mostrar(self.lbl_prueba, "Prueba enviada a %s baud." % b, "fp-ok")
        else:
            self._mostrar(self.lbl_prueba, "No se pudo enviar (vea el Detalle técnico).", "fp-err")

    def _serial_write(self, port, baud, text):
        if not HAVE_SERIAL:
            self.log("pyserial no disponible.")
            return False
        flow = self.combo_flow.get_active_text() or "dtrdsr"
        try:
            ser = serial.Serial(
                port=port, baudrate=int(baud), bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, timeout=2,
                rtscts=(flow == "rtscts"), dsrdtr=(flow == "dtrdsr"),
                xonxoff=(flow == "xonxoff"))
            ser.write(text.encode("latin-1", "replace"))
            ser.flush()
            ser.close()
            return True
        except Exception as e:
            self.log("  (%s) %s" % (port, e))
            return False

    def _uri(self):
        port = self._current_device()
        if self.conn_type == "serial":
            b = self.combo_baud.get_active_text() or "9600"
            flow = self.combo_flow.get_active_text() or "dtrdsr"
            return "serial:%s?baud=%s+bits=8+parity=none+flow=%s" % (port, b, flow)
        if self.conn_type == "red" and port.startswith("smb://"):
            host = port[6:].split("/")[0]
            share = self.ent_share.get_text().strip()
            user = self.ent_smb_user.get_text().strip()
            clave = self.ent_smb_pass.get_text()
            cred = ""
            if user:
                cred = urllib.parse.quote(user, safe="") + (
                    ":" + urllib.parse.quote(clave, safe="") if clave else "") + "@"
            return "smb://%s%s/%s" % (cred, host, urllib.parse.quote(share, safe=""))
        return port

    def _modelo(self):
        if self.conn_type == "red" and self.rb_red_hoja.get_active():
            return "everywhere"
        if (self.conn_type == "red" and self.rb_red_term.get_active()) or \
                (self.conn_type != "red" and self.rb_drv_term.get_active()):
            return "factupos-termica"
        return "raw"

    def do_install(self):
        name = nombre_limpio(self.ent_name.get_text()) or "Impresora"
        uri = self._uri()
        # La clave de Windows no va al Detalle tecnico.
        self.log("Instalando '%s' -> %s" % (name, ocultar_clave(uri)))
        cmd = ["pkexec", HELPER, "apply", "--name", name, "--uri", uri, "--model", self._modelo()]
        if not self.chk_default.get_active():
            cmd.append("--no-default")
        rc, out = sh(cmd)
        self.log(out.strip())
        ok = rc == 0 and "APPLY_OK" in out
        self._instalada = name if ok else ""
        ctx = self.lbl_done.get_style_context()
        if ok:
            self.lbl_done.set_text("¡Listo! Impresora instalada.")
            ctx.remove_class("fp-err")
            self.lbl_done2.set_text(
                "«%s» quedó instalada%s.\nImprima una página de prueba para confirmar que "
                "sale bien." % (name, " y como predeterminada"
                                if self.chk_default.get_active() else ""))
            self.btn_prueba_fin.show()
        else:
            self.lbl_done.set_text("No se pudo instalar")
            ctx.add_class("fp-err")
            ayuda = ""
            if self._modelo() == "everywhere":
                ayuda = ("Esta impresora no aceptó el controlador automático: vuelva atrás y "
                         "elija «Tiquetes / facturas» (cola RAW).\n\n")
            self.lbl_done2.set_text(ayuda + "Toque «Atrás» para revisar los datos y vuelva a "
                                    "intentar.\n\nDetalle:\n" + out.strip()[:600])
            self.btn_prueba_fin.hide()
            self.expander.set_expanded(True)
        self.lbl_prueba_fin.set_text("")

    # ---------- navegacion ----------
    def _show(self):
        en_inicio = self.idx < 0
        name = "home" if en_inicio else self.pages[self.idx]
        self.stack.set_visible_child_name(name)

        self.btn_nueva.set_visible(en_inicio)
        self.btn_virtual.set_visible(en_inicio)
        self.btn_pdf.set_visible(en_inicio)
        self.btn_refrescar.set_visible(en_inicio)
        self.btn_next.set_visible(not en_inicio)
        self.btn_back.set_visible(not en_inicio and name != "type")
        self.btn_cancel.set_visible(not en_inicio and name != "done")
        self.btn_next.set_label("Instalar" if name == "install"
                                else ("Finalizar" if name == "done" else "Siguiente"))

        self.pasos_box.set_visible(not en_inicio)
        if not en_inicio:
            orden = [c for c, _t in self.PASOS]
            actual = orden.index(name) if name in orden else len(orden)
            for i, clave in enumerate(orden):
                ctx = self.pasos_lbl[clave].get_style_context()
                ctx.remove_class("fp-paso-on")
                ctx.remove_class("fp-paso-ok")
                if i == actual:
                    ctx.add_class("fp-paso-on")
                elif i < actual:
                    ctx.add_class("fp-paso-ok")
            for lab in self.pasos_lbl.values():
                lab.show()

        if name == "device":
            tipo = ("serial" if self.rb_serial.get_active() else
                    ("red" if self.rb_red.get_active() else "usb"))
            # La busqueda en red tarda: al volver con «Atrás» no se repite.
            if not (tipo == "red" and self.conn_type == "red" and self._found):
                self.detect_devices()
        if name == "config":
            self.serial_box.set_visible(self.conn_type == "serial")
            self.red_box.set_visible(self.conn_type == "red")
            self.driver_box.set_visible(self.conn_type != "red")
            if self.conn_type != "red":
                for c in self.driver_box.get_children():
                    c.show_all()
            # el driver propio viene en el paquete 1.4.4: con helper viejo no se ofrece
            al_dia = helper_al_dia()
            for rb in (self.rb_drv_term, self.rb_red_term):
                rb.set_sensitive(al_dia)
                rb.set_tooltip_text(None if al_dia else "Falta actualizar el componente: toque "
                                    "«Actualizar ahora» en la lista de impresoras")
                if not al_dia and rb.get_active():
                    (self.rb_drv_raw if rb is self.rb_drv_term else self.rb_red_raw).set_active(True)
            if self.conn_type == "red":
                for c in self.red_box.get_children():
                    c.show_all()
                self._preparar_red()
            self.lbl_prueba.set_text("")
            self._on_nombre()
        if name == "install":
            port = self._current_device()
            if self.conn_type == "serial":
                b = self.combo_baud.get_active_text() or "9600"
                flow = self.combo_flow.get_active_text() or "dtrdsr"
                det = "Serial · %s · %s baud (8N1, flujo %s)" % (port, b, flow)
            elif self.conn_type == "red":
                det = "Red · %s" % self._current_info().get("titulo", port)
            else:
                det = "USB · %s" % describir_uri(port)[1]
            cola = {"everywhere": "Controlador automático (hojas)",
                    "factupos-termica": "Driver FactuPOS térmica (navegador y cualquier programa)"
                    }.get(self._modelo(), "RAW (tiquetes ESC/POS, FactuPOS Print)")
            nombre = nombre_limpio(self.ent_name.get_text()) or "Impresora"
            self.lbl_summary.set_markup(
                "<b>Nombre:</b>  %s\n<b>Conexión:</b>  %s\n<b>Tipo de cola:</b>  %s"
                % (GLib.markup_escape_text(nombre), GLib.markup_escape_text(det),
                   GLib.markup_escape_text(cola)))
            existe = any(p["nombre"] == nombre for p in self._impresoras)
            self.lbl_reemplazo.set_text(
                "Ya hay una impresora llamada «%s»: se va a reemplazar con estos datos." % nombre
                if existe else "")
            self.chk_default.set_active(True)

    def on_back(self, *_):
        if self.idx > 0:
            self.idx -= 1
            self._show()

    def on_next(self, *_):
        name = self.pages[self.idx]
        if name == "device" and not self._current_device():
            self.lbl_dev_hint.set_text("Elija un dispositivo de la lista (o conecte el cable "
                                       "y toque «Volver a detectar»).")
            return
        if name == "config" and not nombre_limpio(self.ent_name.get_text()):
            self._on_nombre()
            return
        if (name == "config" and self.conn_type == "red"
                and self._current_device().startswith("smb://")
                and not self.ent_share.get_text().strip()):
            self.lbl_smb.set_text("Escriba el nombre con que Windows comparte la impresora.")
            return
        if name == "install":
            self.do_install()
            self.idx += 1
            self._show()
            return
        if name == "done":
            self.ir_inicio()
            return
        self.idx += 1
        self._show()


def main():
    w = Wizard()
    w.connect("destroy", Gtk.main_quit)
    w.show_all()
    # Auto-update: un chequeo al arrancar (a los 20s) y luego cada UPDATE_INTERVAL.
    GLib.timeout_add_seconds(20, lambda: (w._check_update_loop(), False)[1])
    GLib.timeout_add_seconds(UPDATE_INTERVAL, w._check_update_loop)
    Gtk.main()


if __name__ == "__main__":
    main()
