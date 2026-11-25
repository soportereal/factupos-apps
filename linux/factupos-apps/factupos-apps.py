#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FactuPOS · Apps
---------------
Tienda de aplicaciones de FactuPOS OS: lista las apps disponibles en el
repositorio APT propio (https://soportereal.com/apt) y permite instalar,
actualizar o quitar cada una con un clic.

1.4.2: el mismo ícono que FactuPOS Apps de Windows.

1.4.1 (#3957): sale «FactuSuper (caja)» con su nombre y la app se llama a sí misma «FactuPOS Apps».

1.4.0 (#3037): la Tienda hace TODO lo que antes hacía la ventana «FactuPOS Update» de la
barra (que se quitó). A la izquierda, dos grupos de color como los submenús de FactuPOS:
«FactuPOS» (las apps propias) y «Otras apps» (Telegram, Winbox… y los navegadores Chrome y
Brave: instalar, actualizar, quitar y elegir el predeterminado). Arriba, «Instalar y
actualizar todo». Lo que se quita a propósito ya no vuelve solo (op.sh lo anota).

No reinventa nada: por debajo es apt. La lista sale del índice Packages
que ya bajó `apt update` (solo los paquetes del repo FactuPOS).
"""

import os
import sys
import glob
import shutil
import subprocess
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

VERSION = "1.4.2"                                 # fuente única de versión

REPO_HOST = "soportereal.com"                     # identifica los índices del repo
LISTS_GLOB = "/var/lib/apt/lists/*%s*_Packages" % REPO_HOST.replace(".", "*")

# Nombres amigables (lo demás sale del propio .deb)
NOMBRES = {
    "factupos-panel":               "Barra de Tareas",
    "factupos-print":               "Impresión (Print)",
    "factupos-print-bridge":        "Puente de Impresión (Bridge)",
    "factupos-printer-inst":        "Gestión de Impresoras",   # #2831, antes «Instalador de Impresoras»
    "factupos-actualizador":        "Actualizador",
    "factupos-autologin":           "Inicio de Sesión Automático",
    "factupos-dataequipo":          "Datos del Equipo",
    "factupos-recortes":            "Recortes",
    "factupos-ia":                  "Asistente IA",
    # #2698 — Una sola app de huella (ventana + servicio). Los nombres viejos quedan
    # por si en alguna PC sigue instalado un paquete suelto.
    "factupos-huella":              "Huella Digital (marcaje)",
    "factupos-fingerprint":         "Huella Digital (viejo)",
    "factupos-fingerprint-kiosko":  "Huella - Kiosko (suelto)",
    "factupos-fingerprint-servicio":"Huella - Servicio (suelto)",
    # La tienda tambien se lista a si misma: asi se puede actualizar sola, sin
    # tener que abrir una terminal. Antes salia como "factupos-apps" al final de
    # la lista (sin nombre amigable no se entendia que era ella misma).
    "factupos-apps":                "FactuPOS Apps",
    "factupos-factusuper":          "FactuSuper (caja)",   # #3957
    "rustdesk":                     "Soporte Remoto FactuPOS",
    "telegram-desktop-bin":         "Telegram",
    "winbox":                       "Winbox (MikroTik)",
    "factupos-navegadores":         "Navegadores y WhatsApp",
    "google-chrome-stable":         "Google Chrome",
    "brave-browser":                "Brave",
}

# Navegadores (#3037): no están en el repo FactuPOS; su repositorio y su llave los mantiene la
# app «Navegadores y WhatsApp». Se muestran en «Otras apps».
NAVEGADORES = {
    "google-chrome-stable": {"desc": "Navegador de Google. Lo usan WhatsApp y FactuPOS.",
                             "desktop": "google-chrome.desktop"},
    "brave-browser":        {"desc": "Navegador Brave: rápido y con bloqueo de publicidad.",
                             "desktop": "brave-browser.desktop"},
}
NAV_SCRIPT = "/usr/lib/factupos-navegadores/navegadores.sh"
QUITADAS = "/var/lib/factupos-apps/quitadas.txt"            # las escribe op.sh (root)
SEG_ESTADO = "/var/lib/factupos-actualizador/seguridad.txt"  # parches de seguridad (#2942)

# Grupos de la izquierda, como los submenús de FactuPOS (pastilla de color por grupo, misma
# paleta que PALETA_GRUPOS de modules/mainmenu/modal.js): (clave, nombre, ícono, color)
GRUPOS = [
    ("factupos", "FactuPOS",   "system-software-install", "#3b82f6"),
    ("otras",    "Otras apps", "applications-internet",   "#f59e0b"),
]


def grupo_de(pkg):
    return "factupos" if pkg.startswith("factupos-") or pkg == "rustdesk" else "otras"


# ----------------------------------------------------------------------
# Datos: paquetes del repo + estado local
# ----------------------------------------------------------------------

def paquetes_repo():
    """Parsea los índices Packages del repo FactuPOS ya bajados por apt."""
    pkgs = {}
    for idx in glob.glob(LISTS_GLOB):
        try:
            with open(idx, encoding="utf-8", errors="replace") as f:
                cur = {}
                for line in f:
                    line = line.rstrip("\n")
                    if not line:
                        if cur.get("Package"):
                            pkgs[cur["Package"]] = cur
                        cur = {}
                    elif line[0] not in " \t" and ":" in line:
                        k, v = line.split(":", 1)
                        cur[k] = v.strip()
                if cur.get("Package"):
                    pkgs[cur["Package"]] = cur
        except OSError:
            pass
    return pkgs


def version_instalada(pkg):
    try:
        out = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version}\t${Status}", pkg],
            capture_output=True, text=True)
        if out.returncode == 0 and "install ok installed" in out.stdout:
            return out.stdout.split("\t")[0]
    except OSError:
        pass
    return None


def candidato(pkg):
    """Versión que ofrece apt para un navegador ('' si su repositorio no está)."""
    try:
        out = subprocess.run(["apt-cache", "policy", pkg], capture_output=True, text=True,
                             timeout=15, env=dict(os.environ, LC_ALL="C")).stdout
        for ln in out.splitlines():
            if ln.strip().startswith("Candidate:"):
                v = ln.split(":", 1)[1].strip()
                return "" if v == "(none)" else v
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def quitadas():
    try:
        with open(QUITADAS, encoding="utf-8") as f:
            return {ln.strip() for ln in f if ln.strip()}
    except OSError:
        return set()


def navegador_predeterminado():
    """El .desktop del navegador que abre los enlaces (de ESTE usuario)."""
    try:
        if shutil.which("xdg-settings"):
            r = subprocess.run(["xdg-settings", "get", "default-web-browser"],
                               capture_output=True, text=True, timeout=10)
            if r.stdout.strip():
                return r.stdout.strip()
        r = subprocess.run(["xdg-mime", "query", "default", "x-scheme-handler/https"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def poner_predeterminado(desktop):
    try:
        if shutil.which("xdg-settings") and subprocess.run(
                ["xdg-settings", "set", "default-web-browser", desktop], timeout=15).returncode == 0:
            return True
        return subprocess.run(["xdg-mime", "default", desktop, "x-scheme-handler/http",
                               "x-scheme-handler/https", "text/html"], timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def seguridad_texto():
    est = {}
    try:
        with open(SEG_ESTADO, encoding="utf-8") as f:
            for ln in f:
                k, _, v = ln.partition("=")
                est[k.strip()] = v.strip()
    except OSError:
        pass
    if not est.get("revisado"):
        return "Seguridad del sistema: todavía no se revisó en este equipo"
    if est.get("reinicio_pendiente") == "si":
        return "Seguridad del sistema: revisada %s · falta reiniciar para terminar" % est["revisado"]
    return "Seguridad del sistema: ✓ revisada %s" % est["revisado"]


def _mezcla(c1, c2, p):
    """#rrggbb con p (0-1) de c1 y el resto de c2 (GTK3 no tiene color-mix)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x * p + y * (1 - p)) for x, y in zip(a, b))


def _css_grupos():
    """Pastilla por grupo: teñida de su color; la elegida RELLENA con letra blanca e ícono en
    círculo blanco (igual que .ms-tab de los submenús de FactuPOS, sobre el navy de la Tienda)."""
    out = []
    for g, _n, _i, c in GRUPOS:
        out.append("""
.fap-tab-%(g)s { background: %(bg)s; border: 1px solid %(bd)s; }
.fap-tab-%(g)s:hover { background: %(hv)s; }
.fap-tab-%(g)s.fap-tab-activa { background: %(ac)s; border-color: %(ac)s; }
.fap-tab-%(g)s .fap-tab-ico { background: %(c)s; }
.fap-tab-%(g)s.fap-tab-activa .fap-tab-ico { background: rgba(255,255,255,0.22); }
.fap-tab-%(g)s .fap-tab-count { color: %(ac)s; }
.fap-tit-%(g)s { color: %(tx)s; }
.fap-linea-%(g)s { background: %(ln)s; }
.fap-card-%(g)s { border-left: 5px solid %(c)s; }
""" % {"g": g, "c": c, "bg": _mezcla(c, "#0b1533", .15), "bd": _mezcla(c, "#0b1533", .45),
       "hv": _mezcla(c, "#0b1533", .28), "ac": _mezcla(c, "#0f2438", .82),
       "tx": _mezcla(c, "#ffffff", .75), "ln": _mezcla(c, "#0b1533", .45)})
    return "".join(out)


def _vercmp(a, b):
    """-1/0/1 comparando versiones debian (usa dpkg)."""
    for op, r in (("lt", -1), ("gt", 1)):
        if subprocess.run(["dpkg", "--compare-versions", a, op, b]).returncode == 0:
            return r
    return 0


# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------

CSS = """
/* Diseno navy 1.3.0 (#2698): el mismo lenguaje que el kiosko de marcaje y la barra
   1.6.x — fondo navy, tarjetas redondeadas con relieve, acentos violeta/azul/cian/verde. */
.fap-win { background: #0b1533; }

.fap-header { background: linear-gradient(135deg, #1e1b4b, #1e3a8a);
              border-bottom: 2px solid #7c3aed; }
.fap-header .fap-tit { color: #ffffff; font-weight: bold; font-size: 19px; }
.fap-header .fap-sub { color: #a5b4fc; font-weight: normal; font-size: 11px; }
/* Version en grande a la derecha (para saber de un vistazo que tienda tiene la PC). */
.fap-header .fap-ver { color: #ffffff; font-weight: bold; font-size: 20px; }
.fap-refresh {
    background: rgba(255,255,255,0.10);
    color: #ffffff; font-weight: bold; font-size: 12px;
    border: 1px solid rgba(255,255,255,0.35); border-radius: 12px; padding: 6px 16px;
}
.fap-refresh:hover { background: linear-gradient(135deg, #7c3aed, #2563eb); }

.fap-searchzone { background: #14224d; }
.fap-search {
    background: #0b1533; color: #ffffff;
    border: 1px solid #4f63a8; border-radius: 12px; padding: 8px 12px; font-size: 13px;
}
.fap-search:focus { border-color: #38bdf8; }

/* Tarjetas con relieve: luz arriba, sombra abajo, acento a la izquierda */
.fap-card {
    background: linear-gradient(to bottom, #182a5c, #14224d);
    border-radius: 14px;
    border: 1px solid rgba(255,255,255,0.10); border-top-color: rgba(255,255,255,0.20);
    border-bottom-color: rgba(0,0,0,0.55);
    border-left: 5px solid #7c3aed;
    box-shadow: 0 3px 6px rgba(0,0,0,0.45);
}
.fap-nombre { color: #ffffff; font-weight: bold; font-size: 13px; }
.fap-desc { color: #b4c2e0; font-size: 11px; }
.fap-ver { color: #7184ad; font-size: 10px; }

.fap-btn-inst {
    background: linear-gradient(135deg, #7c3aed, #2563eb);
    color: #ffffff; font-weight: bold; border: 1px solid rgba(255,255,255,0.35);
    border-radius: 12px; padding: 5px 18px;
}
.fap-btn-inst:hover { background: linear-gradient(135deg, #8b5cf6, #3b82f6); }
.fap-btn-act {
    background: linear-gradient(135deg, #16a34a, #0891b2);
    color: #ffffff; font-weight: bold; border: 1px solid rgba(255,255,255,0.35);
    border-radius: 12px; padding: 5px 18px;
}
.fap-btn-act:hover { background: linear-gradient(135deg, #22c55e, #06b6d4); }
.fap-btn-quitar { color: #fb7185; font-size: 11px; padding: 4px 10px; border-radius: 10px;
                  background: transparent; border: 1px solid transparent; }
.fap-btn-quitar:hover { color: #ffffff; background: #e11d48; }
.fap-btn-quitar:disabled { color: #6b7280; }
.fap-btn-sec { color: #c7d2fe; font-size: 11px; padding: 4px 10px; border-radius: 10px;
               background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.25); }
.fap-btn-sec:hover { color: #ffffff; background: #2563eb; }
.fap-btn-inst:disabled, .fap-btn-act:disabled { background: #4b5563; color: #9ca3af;
                                                border: 1px solid #6b7280; }
.fap-pred { color: #fde047; font-size: 11px; font-weight: bold; }

/* Columna izquierda de grupos (#3037), como los submenús de FactuPOS */
.fap-rail { background: #0f1a3a; border-right: 1px solid rgba(255,255,255,0.10); }
.fap-tab { border-radius: 99px; padding: 10px 14px; color: #e2e8f0; font-weight: bold;
           font-size: 13px; box-shadow: none; }
.fap-tab-activa { color: #ffffff; }
.fap-tab-ico { border-radius: 99px; min-width: 38px; min-height: 38px; }
.fap-tab-count { background: #ffffff; border-radius: 99px; padding: 1px 7px;
                 font-size: 11px; font-weight: bold; }
.fap-tab-activa .fap-tab-count { background: rgba(255,255,255,0.25); color: #ffffff; }
.fap-panel-tit { font-weight: bold; font-size: 15px; }
.fap-panel-tit-n { color: #7184ad; font-size: 11px; }
.fap-linea { min-height: 2px; border-radius: 2px; }
.fap-ok { color: #4ade80; font-weight: bold; }

.fap-status { background: #0f1a3a; border-top: 1px solid rgba(255,255,255,0.10); }
.fap-status label { color: #b4c2e0; font-size: 11px; }

/* Barra de titulo propia: navy flat, letra blanca, minimalista */
.fp-titlebar {
    background: linear-gradient(to right, #0b1533, #14224d 55%, #1e1b4b);
    color: #ffffff;
    border: none;
    box-shadow: none;
    min-height: 38px;
    padding: 0 4px;
}
.fp-titlebar .title { color: #ffffff; font-weight: bold; font-size: 13px; }
.fp-titlebar button {
    background: transparent; color: #ffffff;
    border: none; box-shadow: none; min-width: 26px; min-height: 26px;
}
.fp-titlebar button:hover { background: rgba(255,255,255,0.18); border-radius: 6px; }
"""


class TiendaApps(Gtk.Window):

    # Alto = 80% del monitor. Antes era fijo en 620 px y en pantallas grandes se
    # veia chiquita, con la lista de 20 apps mostrando apenas 6 y obligando a
    # rodar todo el tiempo. Se calcula sobre el AREA UTIL (get_workarea), no
    # sobre el alto crudo: asi descuenta la barra de tareas y la ventana no
    # queda con el pie tapado.
    PROPORCION_ALTO = 0.80
    ALTO_MINIMO = 480          # por si el escritorio reporta cualquier cosa

    def _tamano_ventana(self):
        ancho, alto = 900, 620
        try:
            monitor = Gdk.Display.get_default().get_primary_monitor()
            if monitor is None:                     # sin monitor primario
                monitor = Gdk.Display.get_default().get_monitor(0)
            if monitor is not None:
                area = monitor.get_workarea()
                alto = max(self.ALTO_MINIMO, int(area.height * self.PROPORCION_ALTO))
                # El ancho no crece igual: es una lista de tarjetas, estirada a
                # lo ancho se ve peor. Solo se limita si la pantalla es angosta.
                ancho = min(ancho, max(620, area.width - 80))
        except Exception:
            pass
        return ancho, alto

    def __init__(self):
        super().__init__(title="FactuPOS Apps")
        self.set_icon_name("factupos-apps")   # 1.4.2: mismo ícono que la de Windows
        self.set_default_size(*self._tamano_ventana())
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.set_decoration_layout(":close")
        hb.props.title = "FactuPOS Apps"
        hb.get_style_context().add_class("fp-titlebar")
        self.set_titlebar(hb)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.get_style_context().add_class("fap-win")
        self.connect("destroy", Gtk.main_quit)
        self._ocupado = False
        self._grupo = GRUPOS[0][0]

        raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(raiz)

        # ---- header navy (título + botones)
        head = Gtk.Box(spacing=8)
        head.get_style_context().add_class("fap-header")
        head.set_border_width(14)
        tit_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        tit = Gtk.Label(label="FactuPOS Apps", xalign=0)
        tit.get_style_context().add_class("fap-tit")
        self.lbl_sub = Gtk.Label(label="Instalar, actualizar y quitar aplicaciones", xalign=0)
        self.lbl_sub.get_style_context().add_class("fap-sub")
        tit_box.pack_start(tit, False, False, 0)
        tit_box.pack_start(self.lbl_sub, False, False, 0)
        head.pack_start(tit_box, True, True, 0)

        lbl_ver = Gtk.Label(label="v%s" % VERSION, xalign=1)
        lbl_ver.get_style_context().add_class("fap-ver")
        lbl_ver.set_valign(Gtk.Align.CENTER)
        lbl_ver.set_margin_end(12)

        # «Instalar y actualizar todo» (antes en la ventana FactuPOS Update de la barra, #3037):
        # instala las apps obligatorias que falten, actualiza todo lo instalado, los navegadores
        # y dispara los parches de seguridad.
        self.btn_todo = Gtk.Button(label="Instalar y actualizar todo")
        self.btn_todo.get_style_context().add_class("fap-btn-inst")
        self.btn_todo.set_valign(Gtk.Align.CENTER)
        self.btn_todo.connect("clicked", self._todo)
        self.btn_refresh = Gtk.Button(label="⟳  Actualizar lista")
        self.btn_refresh.get_style_context().add_class("fap-refresh")
        self.btn_refresh.set_valign(Gtk.Align.CENTER)
        self.btn_refresh.connect("clicked", self._refrescar_indice)
        head.pack_end(self.btn_refresh, False, False, 0)
        head.pack_end(self.btn_todo, False, False, 0)
        head.pack_end(lbl_ver, False, False, 0)

        # header + buscador comparten la franja navy
        zona = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        zona.get_style_context().add_class("fap-searchzone")
        zona.pack_start(head, False, False, 0)

        self.buscador = Gtk.SearchEntry()
        self.buscador.get_style_context().add_class("fap-search")
        self.buscador.set_placeholder_text("Buscar aplicación…")
        self.buscador.set_margin_start(14)
        self.buscador.set_margin_end(14)
        self.buscador.set_margin_bottom(14)
        self.buscador.connect("search-changed", lambda _e: self._cargar())
        zona.pack_start(self.buscador, False, False, 0)
        raiz.pack_start(zona, False, False, 0)

        cuerpo = Gtk.Box()
        raiz.pack_start(cuerpo, True, True, 0)

        # ---- columna izquierda: un botón-pastilla por grupo, con su color y su conteo
        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        rail.get_style_context().add_class("fap-rail")
        rail.set_border_width(10)
        rail.set_size_request(210, -1)
        self._tabs, self._tab_count = {}, {}
        for g, nombre, icono, _c in GRUPOS:
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            for cls in ("fap-tab", "fap-tab-" + g):
                b.get_style_context().add_class(cls)
            fila = Gtk.Box(spacing=10)
            ico = Gtk.Box()
            ico.get_style_context().add_class("fap-tab-ico")
            ico.set_valign(Gtk.Align.CENTER)
            img = Gtk.Image.new_from_icon_name(icono, Gtk.IconSize.LARGE_TOOLBAR)
            img.set_margin_start(7)
            img.set_margin_end(7)
            img.set_margin_top(7)
            img.set_margin_bottom(7)
            ico.pack_start(img, False, False, 0)
            fila.pack_start(ico, False, False, 0)
            fila.pack_start(Gtk.Label(label=nombre, xalign=0), True, True, 0)
            cnt = Gtk.Label(label="0")
            cnt.get_style_context().add_class("fap-tab-count")
            cnt.set_valign(Gtk.Align.CENTER)
            fila.pack_end(cnt, False, False, 0)
            b.add(fila)
            b.connect("clicked", self._elegir_grupo, g)
            rail.pack_start(b, False, False, 0)
            self._tabs[g], self._tab_count[g] = b, cnt
        cuerpo.pack_start(rail, False, False, 0)

        # ---- derecha: rótulo del grupo («FactuPOS · 17 apps») + sus tarjetas
        der = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tit_g = Gtk.Box(spacing=8)
        tit_g.set_margin_start(14)
        tit_g.set_margin_end(14)
        tit_g.set_margin_top(12)
        self.lbl_grupo = Gtk.Label(xalign=0)
        self.lbl_grupo.get_style_context().add_class("fap-panel-tit")
        self.lbl_grupo_n = Gtk.Label(xalign=0)
        self.lbl_grupo_n.get_style_context().add_class("fap-panel-tit-n")
        self.linea_grupo = Gtk.Box()
        self.linea_grupo.get_style_context().add_class("fap-linea")
        self.linea_grupo.set_valign(Gtk.Align.CENTER)
        tit_g.pack_start(self.lbl_grupo, False, False, 0)
        tit_g.pack_start(self.lbl_grupo_n, False, False, 0)
        tit_g.pack_start(self.linea_grupo, True, True, 0)
        der.pack_start(tit_g, False, False, 0)

        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.lista = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.lista.set_border_width(12)
        sc.add(self.lista)
        der.pack_start(sc, True, True, 0)
        cuerpo.pack_start(der, True, True, 0)

        # ---- pie de estado (franja navy): lo último que se hizo + la seguridad del sistema
        pie = Gtk.Box()
        pie.get_style_context().add_class("fap-status")
        pie.set_border_width(8)
        self.lbl_estado = Gtk.Label(label="", xalign=0)
        self.lbl_estado.set_margin_start(6)
        self.lbl_estado.set_line_wrap(True)
        pie.pack_start(self.lbl_estado, True, True, 0)
        self.lbl_seg = Gtk.Label(label="", xalign=1)
        self.lbl_seg.set_margin_end(6)
        pie.pack_end(self.lbl_seg, False, False, 0)
        raiz.pack_start(pie, False, False, 0)

        self._cargar()

    # ------------------------------------------------------------------
    def _elegir_grupo(self, _b, g):
        self._grupo = g
        self._cargar()

    def _apps(self):
        """Todas las apps de la Tienda: las del repo FactuPOS + los navegadores."""
        pkgs = paquetes_repo()
        for pkg, nav in NAVEGADORES.items():
            pkgs[pkg] = {"Package": pkg, "Description": nav["desc"], "navegador": True}
        return pkgs

    def _cargar(self):
        for w in self.lista.get_children():
            self.lista.remove(w)
        pkgs = self._apps()
        self._quitadas = quitadas()
        self._pred = navegador_predeterminado()
        self.lbl_seg.set_text(seguridad_texto())

        filtro = (self.buscador.get_text() or "").strip().lower()

        def coincide(p):
            if not filtro:
                return True
            texto = " ".join((
                p.get("Package", ""),
                NOMBRES.get(p.get("Package", ""), ""),
                p.get("Description", ""),
            )).lower()
            return filtro in texto

        orden = sorted(pkgs, key=lambda p: NOMBRES.get(p, "zz" + p))
        por_grupo = {g[0]: [pkgs[n] for n in orden if grupo_de(n) == g[0] and coincide(pkgs[n])]
                     for g in GRUPOS}
        for g, nombre, _i, _c in GRUPOS:
            self._tab_count[g].set_text(str(len(por_grupo[g])))
            ctx = self._tabs[g].get_style_context()
            (ctx.add_class if g == self._grupo else ctx.remove_class)("fap-tab-activa")

        g = self._grupo
        nombre = dict((x[0], x[1]) for x in GRUPOS)[g]
        visibles = por_grupo[g]
        self.lbl_grupo.set_text(nombre)
        n = len(visibles)
        self.lbl_grupo_n.set_text("· %d %s" % (n, "app" if n == 1 else "apps"))
        for x in GRUPOS:
            for w, pre in ((self.lbl_grupo, "fap-tit-"), (self.linea_grupo, "fap-linea-")):
                (w.get_style_context().add_class if x[0] == g
                 else w.get_style_context().remove_class)(pre + x[0])

        if not paquetes_repo() and g == "factupos":
            aviso = Gtk.Label(label="No hay índice del repositorio.\n"
                                    "Presioná «Actualizar lista».")
            self.lista.pack_start(aviso, True, True, 20)
        elif not visibles:
            aviso = Gtk.Label(label="Sin resultados para «%s»" % filtro)
            self.lista.pack_start(aviso, True, True, 20)
        for p in visibles:
            self.lista.pack_start(self._fila(p), False, False, 0)
        self.lista.show_all()

    def _boton(self, texto, clase, cb, *args, tip=None, activo=True):
        b = Gtk.Button(label=texto)
        b.get_style_context().add_class(clase)
        if clase in ("fap-btn-quitar", "fap-btn-sec"):
            b.set_relief(Gtk.ReliefStyle.NONE)
        b.set_valign(Gtk.Align.CENTER)
        b.connect("clicked", cb, *args)
        b.set_sensitive(activo)
        if tip:
            b.set_tooltip_text(tip)
        return b

    def _fila(self, p):
        pkg = p["Package"]
        nav = bool(p.get("navegador"))
        inst = version_instalada(pkg)
        disp = candidato(pkg) if nav else p.get("Version", "?")

        card = Gtk.Box(spacing=10)
        card.get_style_context().add_class("fap-card")
        card.get_style_context().add_class("fap-card-" + grupo_de(pkg))
        card.set_border_width(10)

        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        txt.set_margin_start(10)            # aire entre el acento de color y el texto (1.3.0)
        txt.set_margin_top(4)
        txt.set_margin_bottom(4)
        nom = Gtk.Label(xalign=0, label=NOMBRES.get(pkg, pkg))
        nom.get_style_context().add_class("fap-nombre")
        desc = Gtk.Label(xalign=0, wrap=True,
                         label=p.get("Description", "").split("\n")[0][:110])
        desc.get_style_context().add_class("fap-desc")
        ver = Gtk.Label(xalign=0, wrap=True)
        ver.get_style_context().add_class("fap-ver")
        partes = [pkg]
        if disp:
            partes.append("disponible " + disp)
        if inst:
            partes.append("instalada " + inst)
        elif pkg in self._quitadas:
            partes.append("quitada en este equipo: no se reinstala sola")
        ver.set_text(" · ".join(partes))
        for w in (nom, desc, ver):
            txt.pack_start(w, False, False, 0)
        card.pack_start(txt, True, True, 0)

        # Navegadores sin la app que mantiene su repositorio: botón GRIS, no oculto
        sin_nav = nav and not os.path.exists(NAV_SCRIPT)
        tip_nav = "Necesita la app «Navegadores y WhatsApp» (grupo FactuPOS)" if sin_nav else None

        if inst is None:
            card.pack_end(self._boton("Instalar", "fap-btn-inst", self._accion, pkg, "instalar",
                                      tip=tip_nav, activo=not sin_nav), False, False, 0)
            return card
        if disp and _vercmp(inst, disp) < 0:
            card.pack_end(self._boton("Actualizar", "fap-btn-act", self._accion, pkg, "instalar",
                                      tip=tip_nav, activo=not sin_nav), False, False, 0)
        else:
            ok = Gtk.Label(label="Instalada ✓")
            ok.get_style_context().add_class("fap-ok")
            card.pack_end(ok, False, False, 0)
        if pkg in self.INTOCABLES:
            card.pack_end(self._boton("Quitar", "fap-btn-quitar", self._accion, pkg, "quitar",
                                      tip="No se puede quitar %s: %s" % self.INTOCABLES[pkg],
                                      activo=False), False, False, 0)
        else:
            card.pack_end(self._boton("Quitar", "fap-btn-quitar", self._accion, pkg, "quitar"),
                          False, False, 0)
        if nav:
            desktop = NAVEGADORES[pkg]["desktop"]
            if self._pred == desktop:
                pr = Gtk.Label(label="Predeterminado ★")
                pr.get_style_context().add_class("fap-pred")
                pr.set_tooltip_text("Los enlaces se abren con este navegador")
                card.pack_end(pr, False, False, 0)
            else:
                card.pack_end(self._boton("Usar como predeterminado", "fap-btn-sec",
                                          self._predeterminado, pkg,
                                          tip="Que los enlaces se abran con este navegador"),
                              False, False, 0)
        return card

    # ------------------------------------------------------------------
    # Apps que NO se pueden quitar desde aca (el botón sale gris). Sin la tienda te quedas sin
    # forma de reinstalar nada; sin el Actualizador la maquina deja de recibir versiones
    # nuevas en silencio; sin la barra el equipo se queda sin escritorio. La barrera de
    # verdad está en op.sh (root): esto es para avisar.
    INTOCABLES = {
        "factupos-apps": ("FactuPOS Apps",
                          "se quedaría sin forma de instalar o actualizar las demás"),
        "factupos-actualizador": ("el Actualizador",
                                  "el equipo dejaría de recibir versiones nuevas"),
        "factupos-panel": ("la Barra de Tareas", "el equipo se quedaría sin escritorio"),
    }

    def _op(self, instancia):
        """Arranca factupos-apps-op@<instancia> (root, sin clave por la regla polkit 51) y
        espera que termine. Devuelve (ok, detalle)."""
        unidad = "factupos-apps-op@%s.service" % instancia
        r = subprocess.run(["systemctl", "--no-ask-password", "start", unidad],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode != 0 and "authentication" in (r.stderr or "").lower() and shutil.which("pkexec"):
            r = subprocess.run(["pkexec", "systemctl", "start", unidad],
                               capture_output=True, text=True, timeout=1800)
        detalle = ""
        if r.returncode != 0:
            try:   # la última línea del script dice por qué (si el usuario puede leer el registro)
                j = subprocess.run(["journalctl", "-u", unidad, "-n", "20", "-o", "cat",
                                    "--no-pager"], capture_output=True, text=True, timeout=10).stdout
                lineas = [ln for ln in j.splitlines() if ln.startswith("factupos-apps:")]
                detalle = lineas[-1].split(":", 1)[1].strip() if lineas else ""
            except (OSError, subprocess.SubprocessError):
                pass
        return r.returncode == 0, detalle

    def _trabajar(self, texto, instancia, al_terminar):
        self._ocupado = True
        for b in (self.btn_todo, self.btn_refresh):
            b.set_sensitive(False)
        self.lbl_estado.set_text(texto)

        def trabajo():
            ok, det = self._op(instancia)
            GLib.idle_add(al_terminar, ok, det)

        threading.Thread(target=trabajo, daemon=True).start()

    def _liberar(self, msg):
        self._ocupado = False
        for b in (self.btn_todo, self.btn_refresh):
            b.set_sensitive(True)
        self.lbl_estado.set_text(msg)
        self._cargar()

    def _accion(self, _b, pkg, verbo):
        if self._ocupado:
            return
        nombre = NOMBRES.get(pkg, pkg)
        if verbo == "quitar":
            if pkg in self.INTOCABLES:
                return
            extra = ""
            if pkg == "google-chrome-stable":
                extra = "WhatsApp usará Brave (si está instalado).\n"
            if not self._confirmar("¿Quitar %s?" % nombre,
                                   "Se va a desinstalar de este equipo y no se vuelve a "
                                   "instalar sola.\n%sDespués la puede volver a instalar "
                                   "desde aquí." % extra):
                return
        texto = ("Quitando" if verbo == "quitar" else "Instalando / actualizando") + \
                " %s… puede tardar unos minutos." % nombre

        def fin(ok, det):
            if ok:
                msg = "Listo: %s %s." % (nombre, "quitada" if verbo == "quitar" else "al día")
            else:
                msg = "No se completó (%s)%s" % (nombre, (": " + det) if det else
                                                 " — sin internet o autorización cancelada")
            self._liberar(msg)
            # Si la tienda se actualizo A SI MISMA, la ventana abierta sigue corriendo el
            # codigo VIEJO (Python ya lo tenia cargado): se le ofrece reabrirla.
            if ok and verbo == "instalar" and pkg == "factupos-apps":
                self._ofrecer_reinicio()
            return False

        self._trabajar(texto, "%s-%s" % (verbo, pkg), fin)

    def _todo(self, _b):
        if self._ocupado:
            return
        antes = {p: version_instalada(p) for p in self._apps()}

        def fin(ok, det):
            hecho = []
            for p, v in antes.items():
                ahora = version_instalada(p)
                if ahora and ahora != v:
                    hecho.append(("se instaló %s" if v is None else "%s " + ahora) % NOMBRES.get(p, p))
            if not ok:
                msg = "No se pudo terminar%s" % ((": " + det) if det else " (sin internet o autorización cancelada).")
            elif hecho:
                msg = ("Listo: " + ", ".join(hecho) + ". Los parches de seguridad siguen por detrás. "
                       "Si un programa estaba abierto, ciérrelo y vuelva a abrirlo.")
            else:
                msg = "Listo: todo estaba al día. Los parches de seguridad siguen por detrás."
            self._liberar(msg)
            return False

        self._trabajar("Instalando lo que falta y actualizando lo instalado… puede tardar unos "
                       "minutos. Puede seguir trabajando.", "todo", fin)

    def _predeterminado(self, _b, pkg):
        ok = poner_predeterminado(NAVEGADORES[pkg]["desktop"])
        self.lbl_estado.set_text(("Listo: los enlaces se abren con %s." if ok else
                                  "No se pudo poner %s como predeterminado.") % NOMBRES[pkg])
        self._cargar()

    def _refrescar_indice(self, _b):
        if self._ocupado:
            return
        self._ocupado = True
        self.lbl_estado.set_text("Actualizando índice del repositorio…")

        def trabajo():
            rc = subprocess.call(["pkexec", "apt-get", "-o", "DPkg::Lock::Timeout=180", "update"])
            GLib.idle_add(self._liberar, "Listo: lista al día." if rc == 0 else
                          "No se completó — autorización cancelada o sin internet")

        threading.Thread(target=trabajo, daemon=True).start()

    def _confirmar(self, titulo, detalle):
        d = Gtk.MessageDialog(transient_for=self, modal=True,
                              message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.NONE, text=titulo)
        d.format_secondary_text(detalle)
        d.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        d.add_button("Quitar", Gtk.ResponseType.OK)
        r = d.run()
        d.destroy()
        return r == Gtk.ResponseType.OK

    def _avisar(self, titulo, detalle):
        d = Gtk.MessageDialog(transient_for=self, modal=True,
                              message_type=Gtk.MessageType.WARNING,
                              buttons=Gtk.ButtonsType.OK, text=titulo)
        d.format_secondary_text(detalle)
        d.run()
        d.destroy()

    def _ofrecer_reinicio(self):
        d = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            text="FactuPOS Apps se actualizó")
        d.format_secondary_text(
            "Para ver la versión nueva hay que volver a abrirla.\n"
            "¿La reabro ahora?")
        d.add_button("Ahora no", Gtk.ResponseType.CANCEL)
        d.add_button("Reabrir", Gtk.ResponseType.OK)
        r = d.run()
        d.destroy()
        if r == Gtk.ResponseType.OK:
            try:
                # Desacoplado: se lanza la nueva y esta se cierra. Sin
                # start_new_session la hija moriria junto con la madre.
                subprocess.Popen(["factupos-apps"], start_new_session=True)
            except OSError:
                subprocess.Popen([sys.executable, os.path.abspath(__file__)],
                                 start_new_session=True)
            Gtk.main_quit()
        return False


def main():
    prov = Gtk.CssProvider()
    prov.load_from_data((CSS + _css_grupos()).encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), prov,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    TiendaApps().show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
