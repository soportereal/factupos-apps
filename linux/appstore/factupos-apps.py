#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FactuPOS · Apps
---------------
Tienda de aplicaciones de FactuPOS OS: lista las apps disponibles en el
repositorio APT propio (https://soportereal.com/apt) y permite instalar,
actualizar o quitar cada una con un clic.

No reinventa nada: por debajo es apt. La lista sale del índice Packages
que ya bajó `apt update` (solo los paquetes del repo FactuPOS).
"""

import os
import sys
import glob
import subprocess
import threading

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

VERSION = "1.2.7"                                 # fuente única de versión

REPO_HOST = "soportereal.com"                     # identifica los índices del repo
LISTS_GLOB = "/var/lib/apt/lists/*%s*_Packages" % REPO_HOST.replace(".", "*")

# Nombres amigables (lo demás sale del propio .deb)
NOMBRES = {
    "factupos-panel":               "Barra de Tareas",
    "factupos-print":               "Impresión (Print)",
    "factupos-print-bridge":        "Puente de Impresión (Bridge)",
    "factupos-printer-inst":        "Instalador de Impresoras",
    "factupos-actualizador":        "Actualizador",
    "factupos-autologin":           "Inicio de Sesión Automático",
    "factupos-dataequipo":          "Datos del Equipo",
    "factupos-recortes":            "Recortes",
    "factupos-ia":                  "Asistente IA",
    "factupos-fingerprint":         "Huella Digital",
    "factupos-fingerprint-kiosko":  "Huella - Kiosko",
    "factupos-fingerprint-servicio":"Huella - Servicio",
    # La tienda tambien se lista a si misma: asi se puede actualizar sola, sin
    # tener que abrir una terminal. Antes salia como "factupos-apps" al final de
    # la lista (sin nombre amigable no se entendia que era ella misma).
    "factupos-apps":                "Tienda de Aplicaciones",
    "rustdesk":                     "Soporte Remoto FactuPOS",
    "telegram-desktop-bin":         "Telegram",
    "winbox":                       "Winbox (MikroTik)",
}


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
.fap-win { background: #eef2f8; }

/* Header navy con degradado (mismo lenguaje visual del panel) */
.fap-header { background: linear-gradient(135deg, #0e1b33, #1b3563); }
.fap-header .fap-tit { color: #ffffff; font-weight: bold; font-size: 19px; }
.fap-header .fap-sub { color: #6aa6ff; font-weight: normal; font-size: 11px; }
/* Version en grande a la derecha, como la del cliente FactuPOS Print. La app
   NO mostraba su version en ningun lado: para saber si una PC tenia la nueva
   habia que ir a la terminal y correr dpkg. */
.fap-header .fap-ver { color: #ffffff; font-weight: bold; font-size: 20px; }
.fap-refresh {
    background: rgba(255,255,255,0.08);
    color: #cfe0ff; font-weight: bold; font-size: 12px;
    border: 1px solid #2d5aa6; border-radius: 6px; padding: 6px 14px;
}
.fap-refresh:hover { background: #2d5aa6; color: #ffffff; }

/* Buscador integrado a la franja navy */
.fap-searchzone { background: #1b3563; }
.fap-search {
    background: #ffffff; color: #14233f;
    border: none; border-radius: 8px; padding: 8px 12px; font-size: 13px;
}

/* Tarjetas */
.fap-card {
    background: #ffffff; border-radius: 10px;
    border: 1px solid #dbe3ef; border-left: 4px solid #2d5aa6;
}
.fap-card-inst { border-left: 4px solid #1e7e34; }
.fap-nombre { color: #0e1b33; font-weight: bold; font-size: 13px; }
.fap-desc { color: #5b6b85; font-size: 11px; }
.fap-ver { color: #8494ad; font-size: 10px; }

/* Botones de acción */
.fap-btn-inst {
    background: linear-gradient(135deg, #2d5aa6, #244a8a);
    color: #ffffff; font-weight: bold;
    border-radius: 6px; padding: 5px 16px;
}
.fap-btn-inst:hover { background: #6aa6ff; }
.fap-btn-act {
    background: linear-gradient(135deg, #1e7e34, #17632a);
    color: #ffffff; font-weight: bold;
    border-radius: 6px; padding: 5px 16px;
}
.fap-btn-act:hover { background: #28a745; }
.fap-btn-quitar { color: #b04343; font-size: 11px; padding: 4px 8px; }
.fap-btn-quitar:hover { color: #d32f2f; }
.fap-ok { color: #1e7e34; font-weight: bold; }

/* Pie de estado navy */
.fap-status { background: #0e1b33; }
.fap-status label { color: #9fb6dd; font-size: 11px; }

/* Barra de titulo propia: navy flat, letra blanca, minimalista */
.fp-titlebar {
    background: #0e1b33;
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
        ancho, alto = 620, 620
        try:
            monitor = Gdk.Display.get_default().get_primary_monitor()
            if monitor is None:                     # sin monitor primario
                monitor = Gdk.Display.get_default().get_monitor(0)
            if monitor is not None:
                area = monitor.get_workarea()
                alto = max(self.ALTO_MINIMO, int(area.height * self.PROPORCION_ALTO))
                # El ancho no crece igual: es una lista de tarjetas, estirada a
                # lo ancho se ve peor. Solo se limita si la pantalla es angosta.
                ancho = min(ancho, max(420, area.width - 80))
        except Exception:
            pass
        return ancho, alto

    def __init__(self):
        super().__init__(title="FactuPOS Apps")
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

        raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(raiz)

        # ---- header navy (título + botón)
        head = Gtk.Box(spacing=8)
        head.get_style_context().add_class("fap-header")
        head.set_border_width(14)
        tit_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        # Marca de prueba pedida por el dueño para verificar la cadena completa
        # de publicacion: .deb al pool -> publicar.py -> deploy -> la tienda
        # ofrece la version nueva -> se instala -> se VE este texto en pantalla.
        # Si aparece, la cadena funciona de punta a punta. Quitar despues.
        tit = Gtk.Label(label="Factupos-Apps 24/04/2026", xalign=0)
        tit.get_style_context().add_class("fap-tit")
        self.lbl_sub = Gtk.Label(label="Aplicaciones del repositorio FactuPOS", xalign=0)
        self.lbl_sub.get_style_context().add_class("fap-sub")
        tit_box.pack_start(tit, False, False, 0)
        tit_box.pack_start(self.lbl_sub, False, False, 0)
        head.pack_start(tit_box, True, True, 0)

        lbl_ver = Gtk.Label(label="v%s" % VERSION, xalign=1)
        lbl_ver.get_style_context().add_class("fap-ver")
        lbl_ver.set_valign(Gtk.Align.CENTER)
        lbl_ver.set_margin_end(12)

        self.btn_refresh = Gtk.Button(label="⟳  Actualizar lista")
        self.btn_refresh.get_style_context().add_class("fap-refresh")
        self.btn_refresh.set_valign(Gtk.Align.CENTER)
        self.btn_refresh.connect("clicked", self._refrescar_indice)
        head.pack_end(self.btn_refresh, False, False, 0)
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

        # ---- lista con scroll
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.lista = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.lista.set_border_width(12)
        sc.add(self.lista)
        raiz.pack_start(sc, True, True, 0)

        # ---- pie de estado (franja navy)
        pie = Gtk.Box()
        pie.get_style_context().add_class("fap-status")
        pie.set_border_width(8)
        self.lbl_estado = Gtk.Label(label="", xalign=0)
        self.lbl_estado.set_margin_start(6)
        pie.pack_start(self.lbl_estado, True, True, 0)
        raiz.pack_start(pie, False, False, 0)

        self._cargar()

    # ------------------------------------------------------------------
    def _cargar(self):
        for w in self.lista.get_children():
            self.lista.remove(w)
        pkgs = paquetes_repo()
        self.lbl_sub.set_text("%d aplicaciones disponibles" % len(pkgs))

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

        visibles = [pkgs[n] for n in
                    sorted(pkgs, key=lambda p: NOMBRES.get(p, "zz" + p))
                    if coincide(pkgs[n])]
        if not pkgs:
            aviso = Gtk.Label(label="No hay índice del repositorio.\n"
                                    "Presioná «Actualizar lista».")
            self.lista.pack_start(aviso, True, True, 20)
        elif not visibles:
            aviso = Gtk.Label(label="Sin resultados para «%s»" % filtro)
            self.lista.pack_start(aviso, True, True, 20)
        for p in visibles:
            self.lista.pack_start(self._fila(p), False, False, 0)
        self.lista.show_all()

    def _fila(self, p):
        pkg = p["Package"]
        disp = p.get("Version", "?")
        inst = version_instalada(pkg)

        card = Gtk.Box(spacing=10)
        card.get_style_context().add_class("fap-card")
        if inst is not None:
            card.get_style_context().add_class("fap-card-inst")
        card.set_border_width(10)

        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        nom = Gtk.Label(xalign=0, label=NOMBRES.get(pkg, pkg))
        nom.get_style_context().add_class("fap-nombre")
        desc = Gtk.Label(xalign=0, wrap=True,
                         label=p.get("Description", "").split("\n")[0][:110])
        desc.get_style_context().add_class("fap-desc")
        ver = Gtk.Label(xalign=0)
        ver.get_style_context().add_class("fap-ver")
        ver.set_text("%s · disponible %s%s" %
                     (pkg, disp, (" · instalada " + inst) if inst else ""))
        for w in (nom, desc, ver):
            txt.pack_start(w, False, False, 0)
        card.pack_start(txt, True, True, 0)

        if inst is None:
            b = Gtk.Button(label="Instalar")
            b.get_style_context().add_class("fap-btn-inst")
            b.connect("clicked", self._accion, pkg, "install")
            card.pack_end(b, False, False, 0)
        elif _vercmp(inst, disp) < 0:
            b = Gtk.Button(label="Actualizar")
            b.get_style_context().add_class("fap-btn-act")
            b.connect("clicked", self._accion, pkg, "install")
            card.pack_end(b, False, False, 0)
            q = Gtk.Button(label="Quitar")
            q.get_style_context().add_class("fap-btn-quitar")
            q.set_relief(Gtk.ReliefStyle.NONE)
            q.connect("clicked", self._accion, pkg, "remove")
            card.pack_end(q, False, False, 0)
        else:
            ok = Gtk.Label(label="Instalada ✓")
            ok.get_style_context().add_class("fap-ok")
            card.pack_end(ok, False, False, 0)
            q = Gtk.Button(label="Quitar")
            q.get_style_context().add_class("fap-btn-quitar")
            q.set_relief(Gtk.ReliefStyle.NONE)
            q.connect("clicked", self._accion, pkg, "remove")
            card.pack_end(q, False, False, 0)
        return card

    # ------------------------------------------------------------------
    # Apps que NO se pueden quitar desde aca. La tienda no se puede desinstalar
    # a si misma (te quedas sin forma de reinstalar nada salvo por terminal), y
    # sin el Actualizador la maquina deja de recibir versiones nuevas en
    # silencio. Se quitan por terminal si de verdad hace falta.
    INTOCABLES = {
        "factupos-apps": "la Tienda de Aplicaciones",
        "factupos-actualizador": "el Actualizador",
    }

    def _accion(self, _b, pkg, verbo):
        if self._ocupado:
            return
        if verbo == "remove":
            if pkg in self.INTOCABLES:
                self._avisar("No se puede quitar %s desde aquí" % self.INTOCABLES[pkg],
                             "Si la quita, se queda sin forma de instalar o "
                             "actualizar las demás aplicaciones.")
                return
            # Antes bastaba UN clic para desinstalar: no preguntaba nada, iba
            # directo a `apt-get remove -y`. La unica barrera era la contrasena
            # de pkexec, que el usuario teclea por costumbre sin leer.
            if not self._confirmar("¿Quitar %s?" % NOMBRES.get(pkg, pkg),
                                   "Se va a desinstalar de este equipo.\n"
                                   "Después la puede volver a instalar desde aquí."):
                return
        self._ocupado = True
        self.lbl_estado.set_text(("Instalando" if verbo == "install"
                                  else "Quitando") + " %s…" % pkg)

        def trabajo():
            env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
            rc = subprocess.call(
                ["pkexec", "apt-get", "-o", "DPkg::Lock::Timeout=180", verbo, "-y", pkg], env=env)
            GLib.idle_add(self._fin, pkg, verbo, rc)

        threading.Thread(target=trabajo, daemon=True).start()

    def _refrescar_indice(self, _b):
        if self._ocupado:
            return
        self._ocupado = True
        self.lbl_estado.set_text("Actualizando índice del repositorio…")

        def trabajo():
            rc = subprocess.call(["pkexec", "apt-get", "-o", "DPkg::Lock::Timeout=180", "update"])
            GLib.idle_add(self._fin, "índice", "update", rc)

        threading.Thread(target=trabajo, daemon=True).start()

    def _fin(self, pkg, verbo, rc):
        self._ocupado = False
        self.lbl_estado.set_text(
            ("Listo: %s" % pkg) if rc == 0
            else "No se completó (%s) — autorización cancelada o error" % pkg)
        self._cargar()

        # Si la tienda se actualizo A SI MISMA, la ventana abierta sigue
        # corriendo el codigo VIEJO: apt reemplazo el archivo en disco, pero
        # Python ya lo tenia cargado en memoria. Sin avisar, el usuario
        # actualiza, no ve ningun cambio y cree que no funciono. Se le ofrece
        # reabrirla, que es lo unico que hace falta.
        if rc == 0 and verbo == "install" and pkg == "factupos-apps":
            self._ofrecer_reinicio()

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
            text="La Tienda de Aplicaciones se actualizó")
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
    prov.load_from_data(CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), prov,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    TiendaApps().show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
