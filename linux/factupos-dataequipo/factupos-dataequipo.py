#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FactuPOS DataEquipo - Información del equipo organizada por pestañas.
# Tema navy FactuPOS (azul navy / negro / grises-blancos). Python3 + GTK3.
import os
import re
import sys
import json
import shutil
import socket
import subprocess
import threading
import urllib.request

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib, Pango  # noqa: E402

VERSION = "1.0.3"                                 # fuente única de versión
OS_VERSION_FILE = "/etc/factupos-os-version"

# Auto-actualización (mismo esquema que factupos-panel).
UPDATE_BASE = "https://soportereal.com/software/factupos-app/linux"
UPDATE_MANIFEST = UPDATE_BASE + "/Factupos-DataEquipo_version.json"
UPDATE_PY_LOCAL = os.path.expanduser(
    "~/.local/share/factupos-dataequipo/factupos-dataequipo.py")
UPDATE_INTERVAL = 6 * 3600                        # re-chequeo cada 6 horas


def _vtuple(v):
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except Exception:
        return (0,)

# ---- paleta navy FactuPOS ----
CSS = b"""
/* Tema CLARO moderno y FLAT con acentos NAVY: fondo claro + texto oscuro;
   header/titulos/botones navy. Letra grande, contrastes AA verificados. */
.fp-win { background-color: #eef2f8; }
.fp-header { background-color: #16305c; }
.fp-header label { color: #ffffff; }
.fp-title { font-size: 1.7em; font-weight: bold; }
.fp-sub { color: #cdddf2; font-size: 1.05em; }
notebook { background-color: #eef2f8; }
notebook header { background-color: #e3e9f2; }
notebook header tabs tab { background-color: transparent; color: #5a6b86; padding: 10px 18px;
                           font-size: 1.12em; border: none; border-bottom: 2px solid transparent; margin: 0 2px; }
notebook header tabs tab:checked { color: #16305c; border-bottom: 2px solid #285296; }
notebook header tabs tab:hover { color: #1f2d44; }
.fp-card { background-color: #ffffff; border: 1px solid #d3dce8; border-radius: 10px;
           padding: 9px 6px; margin: 7px 9px; }
.fp-cardtitle { color: #1d4ed8; font-weight: bold; font-size: 1.22em; padding: 5px 10px 3px 10px; }
.fp-key { color: #54627c; font-size: 1.12em; padding: 6px 10px; }
.fp-val { color: #1e293b; font-size: 1.12em; padding: 6px 10px; }
.fp-val-strong { color: #15803d; font-weight: bold; font-size: 1.12em; }
.fp-val-warn { color: #b45309; font-weight: bold; font-size: 1.12em; }
.fp-val-bad  { color: #dc2626; font-weight: bold; font-size: 1.12em; }
.fp-foot { background-color: #e3e9f2; }
.fp-btn { background-image: none; background-color: #285296; color: #ffffff;
          border: none; padding: 9px 18px; border-radius: 8px; font-weight: bold; font-size: 1.08em; }
.fp-btn:hover { background-color: #34619f; }
progressbar trough { background-color: #d6deea; min-height: 12px; border-radius: 6px; }
progressbar progress { background-color: #2563eb; border-radius: 6px; }
levelbar block.filled { background-color: #2563eb; }
levelbar block.empty { background-color: #d6deea; }
"""


def sh(cmd, timeout=4):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=timeout).stdout.strip()
    except Exception:
        return ""


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return default


def os_version():
    v = read(OS_VERSION_FILE)
    if v:
        return v
    for ln in read("/etc/os-release").splitlines():
        if ln.startswith("VERSION_ID="):
            return ln.split("=", 1)[1].strip().strip('"')
    return "—"


def human(n):
    try:
        n = float(n)
    except Exception:
        return str(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return "%.1f %s" % (n, u)
        n /= 1024
    return "%.1f PB" % n


# ----------------- recolectores de datos -----------------
def cpu_usage():
    def snap():
        p = read("/proc/stat").splitlines()[0].split()[1:]
        v = list(map(int, p))
        idle = v[3] + v[4]
        return sum(v), idle
    t1, i1 = snap()
    import time as _t
    _t.sleep(0.25)
    t2, i2 = snap()
    dt, di = t2 - t1, i2 - i1
    return 0.0 if dt == 0 else max(0.0, min(100.0, 100.0 * (dt - di) / dt))


def mem_info():
    d = {}
    for ln in read("/proc/meminfo").splitlines():
        k, _, v = ln.partition(":")
        d[k] = int(v.strip().split()[0]) * 1024
    total = d.get("MemTotal", 0)
    avail = d.get("MemAvailable", 0)
    used = total - avail
    swt = d.get("SwapTotal", 0)
    swf = d.get("SwapFree", 0)
    return total, used, avail, swt, swt - swf


def uptime_str():
    try:
        s = float(read("/proc/uptime").split()[0])
    except Exception:
        return "—"
    d, s = divmod(int(s), 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    out = []
    if d:
        out.append("%dd" % d)
    out.append("%dh" % h)
    out.append("%dm" % m)
    return " ".join(out)


class DataEquipo(Gtk.Window):
    def __init__(self):
        super().__init__(title="FactuPOS · DataEquipo")
        self.set_default_size(820, 640)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.get_style_context().add_class("fp-win")
        self._live = {}            # nombre -> Gtk.Label (valores en vivo)
        self._apply_css()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)

        # encabezado
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        head.get_style_context().add_class("fp-header")
        head.set_border_width(12)
        ic = Gtk.Image.new_from_icon_name("computer", Gtk.IconSize.DND)
        head.pack_start(ic, False, False, 4)
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        t = Gtk.Label(label="FactuPOS · DataEquipo", xalign=0)
        t.get_style_context().add_class("fp-title")
        s = Gtk.Label(label="Información del equipo  ·  v%s  ·  FactuPOS OS %s" % (VERSION, os_version()), xalign=0)
        s.get_style_context().add_class("fp-sub")
        tb.pack_start(t, False, False, 0)
        tb.pack_start(s, False, False, 0)
        head.pack_start(tb, True, True, 0)
        root.pack_start(head, False, False, 0)

        # pestañas
        self.nb = Gtk.Notebook()
        root.pack_start(self.nb, True, True, 0)
        self._build_tabs()

        # pie con botones
        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        foot.get_style_context().add_class("fp-foot")
        foot.set_border_width(8)
        b_ref = Gtk.Button(label="🔄  Actualizar")
        b_ref.get_style_context().add_class("fp-btn")
        b_ref.connect("clicked", lambda *_: self._refresh_all())
        b_cp = Gtk.Button(label="📋  Copiar resumen")
        b_cp.get_style_context().add_class("fp-btn")
        b_cp.connect("clicked", self._copy_summary)
        b_upd = Gtk.Button(label="⬆️  Verificar versión")
        b_upd.get_style_context().add_class("fp-btn")
        b_upd.set_tooltip_text("Buscar e instalar la última versión (v%s)" % VERSION)
        b_upd.connect("clicked", self._check_update_manual)
        foot.pack_start(b_ref, False, False, 0)
        foot.pack_start(b_cp, False, False, 0)
        foot.pack_start(b_upd, False, False, 0)
        root.pack_end(foot, False, False, 0)

        GLib.timeout_add_seconds(2, self._tick)
        # Auto-update: chequeo al arrancar (20s) y luego cada UPDATE_INTERVAL.
        GLib.timeout_add_seconds(20, lambda: (self._check_update_loop(), False)[1])
        GLib.timeout_add_seconds(UPDATE_INTERVAL, self._check_update_loop)

    # ---------- auto-actualización (botón + chequeo periódico) ----------
    def _notify(self, msg):
        if shutil.which("notify-send"):
            try:
                subprocess.Popen(["notify-send", "-i", "computer",
                                  "FactuPOS DataEquipo", msg],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        sys.stderr.write(msg + "\n")

    def _check_update_loop(self):
        threading.Thread(target=self._check_update_once, daemon=True).start()
        return True   # repetir cada UPDATE_INTERVAL

    def _check_update_manual(self, *_):
        self._notify("Buscando actualizaciones…")
        threading.Thread(
            target=lambda: self._check_update_once(notify_uptodate=True),
            daemon=True).start()

    def _check_update_once(self, notify_uptodate=False):
        try:
            req = urllib.request.Request(UPDATE_MANIFEST,
                                         headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=8) as r:
                man = json.loads(r.read().decode("utf-8"))
        except Exception:
            if notify_uptodate:
                self._notify("No se pudo verificar (sin conexión).")
            return False
        newv = str(man.get("version", "")).strip()
        if not newv or _vtuple(newv) <= _vtuple(VERSION):
            if notify_uptodate:
                self._notify("Ya estás en la última versión (v%s)." % VERSION)
            return False
        pyurl = man.get("py") or (UPDATE_BASE + "/factupos-dataequipo.py")
        try:
            with urllib.request.urlopen(pyurl, timeout=25) as r:
                data = r.read()
        except Exception:
            return False
        if b"DataEquipo" not in data or b"def main(" not in data:
            return False
        try:
            os.makedirs(os.path.dirname(UPDATE_PY_LOCAL), exist_ok=True)
            tmp = UPDATE_PY_LOCAL + ".new"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, UPDATE_PY_LOCAL)
        except Exception:
            return False
        self._notify("Actualizado a la versión %s, reiniciando…" % newv)
        GLib.timeout_add_seconds(1, self._restart_self)
        return False

    def _restart_self(self):
        try:
            py = UPDATE_PY_LOCAL if os.path.exists(UPDATE_PY_LOCAL) else os.path.abspath(__file__)
            os.execv(sys.executable, [sys.executable, py] + sys.argv[1:])
        except Exception:
            pass
        return False

    def _apply_css(self):
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    # ---- helpers de UI ----
    def _page(self):
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_border_width(6)
        sc.add(box)
        return sc, box

    def _card(self, parent, title, rows, live_keys=None):
        live_keys = live_keys or {}
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.get_style_context().add_class("fp-card")
        lt = Gtk.Label(label=title, xalign=0)
        lt.get_style_context().add_class("fp-cardtitle")
        card.pack_start(lt, False, False, 0)
        grid = Gtk.Grid()
        grid.set_column_spacing(8)
        grid.set_row_spacing(0)
        card.pack_start(grid, False, False, 0)
        for i, (k, v, *cls) in enumerate(rows):
            lk = Gtk.Label(label=k, xalign=0)
            lk.get_style_context().add_class("fp-key")
            lk.set_size_request(180, -1)
            lv = Gtk.Label(label=v, xalign=0)
            lv.set_line_wrap(True)
            lv.set_selectable(True)
            lv.get_style_context().add_class(cls[0] if cls else "fp-val")
            grid.attach(lk, 0, i, 1, 1)
            grid.attach(lv, 1, i, 1, 1)
            if k in live_keys:
                self._live[live_keys[k]] = lv
        parent.pack_start(card, False, False, 0)

    # ---- construcción de pestañas ----
    def _build_tabs(self):
        self._pages = {}
        for name, icon in (("Resumen", "📋"), ("Hardware", "🖥️"), ("Discos", "💾"),
                           ("Red", "📶"), ("Impresoras", "🖨️"),
                           ("FactuPOS", "🧩"), ("Soporte", "🆘")):
            sc, box = self._page()
            self.nb.append_page(sc, Gtk.Label(label="%s  %s" % (icon, name)))
            self._pages[name] = box
        # Abrir la ventana YA y llenar la info despues (juntar discos/red/hardware
        # tarda; no bloquear el arranque).
        lbl = Gtk.Label(label="Cargando información…")
        lbl.get_style_context().add_class("fp-key")
        self._pages["Resumen"].pack_start(lbl, False, False, 14)
        GLib.timeout_add(80, self._first_fill)

    def _first_fill(self):
        self._live = {}
        self._fill_resumen()        # lo mas rapido primero
        self.show_all()
        GLib.timeout_add(30, self._rest_fill)
        return False

    def _rest_fill(self):
        self._fill_hardware()
        self._fill_discos()
        self._fill_red()
        self._fill_impresoras()
        self._fill_factupos()
        self._fill_soporte()
        self.show_all()
        return False

    def _clear(self, box):
        for c in box.get_children():
            box.remove(c)

    def _refresh_all(self):
        self._live = {}
        self._fill_resumen()
        self._fill_hardware()
        self._fill_discos()
        self._fill_red()
        self._fill_impresoras()
        self._fill_factupos()
        self._fill_soporte()
        self.show_all()

    def _fill_resumen(self):
        b = self._pages["Resumen"]
        self._clear(b)
        self._card(b, "Equipo", [
            ("Nombre del equipo", socket.gethostname()),
            ("FactuPOS OS", os_version(), "fp-val-strong"),
            ("Fabricante", read("/sys/class/dmi/id/sys_vendor", "—")),
            ("Modelo", read("/sys/class/dmi/id/product_name", "—")),
            ("Número de serie", read("/sys/class/dmi/id/product_serial", "—")),
            ("Usuario", os.environ.get("USER", sh("whoami"))),
        ])
        self._card(b, "Estado", [
            ("Encendido desde", uptime_str()),
            ("Kernel", os.uname().release),
            ("Fecha / hora", sh("date '+%d/%m/%Y %H:%M'")),
            ("Zona horaria", sh("timedatectl show -p Timezone --value") or "—"),
        ], live_keys={"Encendido desde": "uptime", "Fecha / hora": "fecha"})

    def _fill_hardware(self):
        b = self._pages["Hardware"]
        self._clear(b)
        cpu = "—"
        ncpu = 0
        for ln in read("/proc/cpuinfo").splitlines():
            if ln.startswith("model name"):
                cpu = ln.split(":", 1)[1].strip()
            if ln.startswith("processor"):
                ncpu += 1
        self._card(b, "Procesador", [
            ("Modelo", cpu),
            ("Núcleos", str(ncpu)),
            ("Uso actual", "…", "fp-val-strong"),
            ("Carga (1/5/15m)", read("/proc/loadavg").split()[0:3] and
             " · ".join(read("/proc/loadavg").split()[0:3])),
        ], live_keys={"Uso actual": "cpu"})
        tot, used, avail, swt, swu = mem_info()
        self._card(b, "Memoria RAM", [
            ("Total", human(tot)),
            ("Usada", "…", "fp-val-strong"),
            ("Disponible", human(avail)),
            ("Swap", "%s de %s" % (human(swu), human(swt)) if swt else "—"),
        ], live_keys={"Usada": "ram"})
        gpu = sh("lspci 2>/dev/null | grep -iE 'vga|3d|display' | sed 's/.*: //'")
        self._card(b, "Gráficos / BIOS", [
            ("GPU", gpu or "—"),
            ("BIOS / UEFI", "%s  (%s)" % (read("/sys/class/dmi/id/bios_version", "—"),
                                          read("/sys/class/dmi/id/bios_date", ""))),
            ("Placa madre", read("/sys/class/dmi/id/board_name", "—")),
        ])

    def _fill_discos(self):
        b = self._pages["Discos"]
        self._clear(b)
        disks = sh("lsblk -dn -o NAME,SIZE,MODEL 2>/dev/null | grep -vE '^loop|^sr'")
        rows = []
        for ln in disks.splitlines():
            parts = ln.split(None, 2)
            if len(parts) >= 2:
                rows.append((parts[0], "%s  %s" % (parts[1], parts[2] if len(parts) > 2 else "")))
        self._card(b, "Discos físicos", rows or [("—", "sin datos")])
        # uso de particiones montadas
        out = sh("df -h --output=target,size,used,avail,pcent -x tmpfs -x devtmpfs 2>/dev/null | tail -n +2")
        for ln in out.splitlines():
            p = ln.split()
            if len(p) >= 5 and (p[0] == "/" or p[0].startswith("/mnt") or p[0].startswith("/media")):
                try:
                    pct = int(p[4].rstrip("%"))
                except Exception:
                    pct = 0
                cls = "fp-val-bad" if pct >= 90 else ("fp-val-warn" if pct >= 75 else "fp-val-strong")
                self._card(b, "Almacenamiento  %s" % p[0], [
                    ("Tamaño", p[1]),
                    ("Usado", "%s  (%s)" % (p[2], p[4]), cls),
                    ("Libre", p[3]),
                ])

    def _fill_red(self):
        b = self._pages["Red"]
        self._clear(b)
        # interfaces con IP
        for ln in sh("ip -o -4 addr show scope global 2>/dev/null").splitlines():
            m = re.search(r"\d+:\s+(\S+)\s+inet\s+(\S+)", ln)
            if m:
                ifc, ip = m.group(1), m.group(2)
                mac = read("/sys/class/net/%s/address" % ifc, "—")
                tipo = "WiFi" if ifc.startswith(("wl", "wlan", "wlp")) else "Cable"
                self._card(b, "%s  (%s)" % (ifc, tipo), [
                    ("Dirección IP", ip, "fp-val-strong"),
                    ("MAC", mac),
                ])
        # WiFi
        ssid = sh("nmcli -t -f active,ssid,signal dev wifi 2>/dev/null | grep '^sí\\|^yes' | head -1")
        if ssid:
            p = ssid.split(":")
            self._card(b, "WiFi conectado", [
                ("Red (SSID)", p[1] if len(p) > 1 else "—", "fp-val-strong"),
                ("Señal", (p[2] + " %") if len(p) > 2 else "—"),
            ])
        gw = sh("ip route 2>/dev/null | awk '/default/{print $3; exit}'")
        dns = sh("grep -m3 nameserver /etc/resolv.conf 2>/dev/null | awk '{print $2}' | paste -sd ' '")
        self._card(b, "Conexión", [
            ("Puerta de enlace", gw or "—"),
            ("DNS", dns or "—"),
            ("Internet", "Comprobando…", "fp-val"),
            ("IP pública", "Comprobando…"),
        ], live_keys={"Internet": "inet", "IP pública": "pubip"})
        threading.Thread(target=self._check_net, daemon=True).start()

    def _check_net(self):
        ok = sh("ping -c1 -W2 1.1.1.1 >/dev/null 2>&1 && echo ok", timeout=5)
        pub = sh("curl -s --max-time 5 https://api.ipify.org 2>/dev/null", timeout=7)
        def upd():
            if "inet" in self._live:
                if ok == "ok":
                    self._live["inet"].set_text("✓ Conectado")
                    self._live["inet"].get_style_context().add_class("fp-val-strong")
                else:
                    self._live["inet"].set_text("✗ Sin internet")
                    self._live["inet"].get_style_context().add_class("fp-val-bad")
            if "pubip" in self._live:
                self._live["pubip"].set_text(pub or "—")
            return False
        GLib.idle_add(upd)

    def _fill_impresoras(self):
        b = self._pages["Impresoras"]
        self._clear(b)
        default = sh("lpstat -d 2>/dev/null | sed 's/.*: //')")
        printers = sh("lpstat -p 2>/dev/null")
        rows = []
        for ln in printers.splitlines():
            m = re.match(r"impresora\s+(\S+)|printer\s+(\S+)", ln, re.I)
            if m:
                nm = m.group(1) or m.group(2)
                estado = "inactiva" if "desactiv" in ln or "disabled" in ln else "lista"
                rows.append((nm, estado + (" · predeterminada" if nm == default else "")))
        self._card(b, "Impresoras (CUPS)", rows or [("—", "ninguna instalada")])
        serial = sh("ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null | paste -sd ' '")
        self._card(b, "Puertos de tickets", [
            ("Puertos serie/USB", serial or "ninguno detectado"),
        ])

    def _fill_factupos(self):
        b = self._pages["FactuPOS"]
        self._clear(b)
        rows = []
        for pkg, nombre in (("factupos-panel", "Barra de tareas"),
                            ("factupos-printer-inst", "Instalador de impresoras"),
                            ("factupos-dataequipo", "DataEquipo")):
            v = sh("dpkg-query -Wf '${Version}' %s 2>/dev/null" % pkg)
            rows.append((nombre, ("v" + v) if v else "no instalado",
                         "fp-val-strong" if v else "fp-val-warn"))
        self._card(b, "Aplicaciones FactuPOS", rows)
        prnt = sh("ls /opt/factupos* /usr/bin/factupos-print* 2>/dev/null | head -1")
        self._card(b, "Servicios", [
            ("FactuPOS Print", "instalado" if prnt else "—"),
            ("Tema arranque (Plymouth)", sh("plymouth-set-default-theme 2>/dev/null") or "—"),
        ])

    def _fill_soporte(self):
        b = self._pages["Soporte"]
        self._clear(b)
        anydesk = sh("anydesk --get-id 2>/dev/null") or sh(
            "awk -F= '/^ad.anynet.id/{print $2}' /etc/anydesk/system.conf 2>/dev/null")
        rust = sh("rustdesk --get-id 2>/dev/null")
        self._card(b, "Acceso remoto", [
            ("AnyDesk ID", anydesk or "—", "fp-val-strong"),
            ("RustDesk ID", rust or "—", "fp-val-strong"),
        ])
        self._card(b, "Acceso / red", [
            ("Usuario SSH", os.environ.get("USER", "factupos")),
            ("IP local", sh("hostname -I 2>/dev/null | awk '{print $1}'") or "—"),
            ("Nombre del equipo", socket.gethostname()),
        ])
        self._card(b, "Soporte", [
            ("Web", "soportereal.com"),
            ("Sistema", "FactuPOS OS %s" % os_version()),
        ])

    # ---- refresco en vivo ----
    def _tick(self):
        if "cpu" in self._live:
            threading.Thread(target=self._upd_cpu, daemon=True).start()
        if "ram" in self._live:
            _, used, _, _, _ = mem_info()
            tot = mem_info()[0]
            pct = 100 * used / tot if tot else 0
            self._live["ram"].set_text("%s  (%.0f%%)" % (human(used), pct))
        if "uptime" in self._live:
            self._live["uptime"].set_text(uptime_str())
        if "fecha" in self._live:
            self._live["fecha"].set_text(sh("date '+%d/%m/%Y %H:%M'"))
        return True

    def _upd_cpu(self):
        u = cpu_usage()
        GLib.idle_add(lambda: self._live["cpu"].set_text("%.0f %%" % u) if "cpu" in self._live else None)

    def _copy_summary(self, *_):
        tot, used, _, _, _ = mem_info()
        txt = (
            "=== FactuPOS DataEquipo ===\n"
            "Equipo: %s\nFactuPOS OS: %s\nModelo: %s %s\nSerie: %s\n"
            "Kernel: %s\nEncendido: %s\nCPU: %s\nRAM: %s de %s\nIP: %s\n"
            "AnyDesk: %s\nRustDesk: %s\n" % (
                socket.gethostname(), os_version(),
                read("/sys/class/dmi/id/sys_vendor", ""), read("/sys/class/dmi/id/product_name", ""),
                read("/sys/class/dmi/id/product_serial", "—"),
                os.uname().release, uptime_str(),
                next((l for l in read("/proc/cpuinfo").splitlines() if l.startswith("model name")),
                     "model name: —").split(":", 1)[1].strip(),
                human(used), human(tot),
                sh("hostname -I 2>/dev/null | awk '{print $1}'"),
                sh("anydesk --get-id 2>/dev/null") or "—",
                sh("rustdesk --get-id 2>/dev/null") or "—"))
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        cb.set_text(txt, -1)
        d = Gtk.MessageDialog(transient_for=self, modal=True,
                              message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.OK,
                              text="Resumen copiado al portapapeles")
        d.run()
        d.destroy()


def main():
    win = DataEquipo()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
