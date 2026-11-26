#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FactuPOS · Fondo de Escritorio
--------------------------------------
Herramienta propia de FactuPOS OS para cambiar el fondo de escritorio
eligiendo entre las imágenes de /usr/share/backgrounds o una imagen propia.

Detecta el entorno de escritorio en uso (XFCE / Cinnamon) y aplica el
fondo con la herramienta nativa correspondiente; si no reconoce el
entorno, intenta con `feh --bg-fill` como respaldo.

Uso:
  factupos-fondo                  ventana gráfica
"""

import os
import sys
import glob
import subprocess

VERSION = "1.0.1"                                 # fuente única de versión

CARPETA_FONDOS = "/usr/share/backgrounds"
EXTENSIONES = ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG")
MAX_MINIATURAS = 60
ANCHO_MINIATURA = 160
ALTO_MINIATURA = 100


# ----------------------------------------------------------------------
# Lógica (búsqueda de imágenes y aplicación del fondo)
# ----------------------------------------------------------------------

def listar_fondos():
    """Busca imágenes de fondo en CARPETA_FONDOS de forma recursiva."""
    encontradas = []
    if os.path.isdir(CARPETA_FONDOS):
        for raiz, _dirs, _archivos in os.walk(CARPETA_FONDOS):
            for patron in EXTENSIONES:
                encontradas.extend(glob.glob(os.path.join(raiz, patron)))
    encontradas = sorted(set(encontradas))
    return encontradas[:MAX_MINIATURAS]


def _escritorio_actual():
    """Adivina el entorno de escritorio en uso (env var + procesos)."""
    xdg = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
    if "xfce" in xdg:
        return "xfce"
    if "x-cinnamon" in xdg or "cinnamon" in xdg:
        return "cinnamon"

    # respaldo: revisar procesos corriendo
    try:
        procesos = subprocess.check_output(["ps", "-e", "-o", "comm="],
                                            text=True)
    except Exception:
        procesos = ""
    if "xfdesktop" in procesos:
        return "xfce"
    if "cinnamon" in procesos:
        return "cinnamon"
    return None


def _aplicar_xfce(ruta):
    """Setea la imagen en TODAS las propiedades .../last-image de xfdesktop
    (una por monitor/workspace); si no existen aún, las crea."""
    canal = "xfce4-desktop"
    try:
        salida = subprocess.check_output(
            ["xfconf-query", "-c", canal, "-l"], text=True)
    except Exception as e:
        return False, "xfconf-query no disponible: %s" % e

    props = [p.strip() for p in salida.splitlines()
             if p.strip().endswith("last-image")]

    if not props:
        # no hay propiedades todavía: crear una genérica para el monitor
        # principal (patrón típico de xfdesktop)
        props = ["/backdrop/screen0/monitor0/workspace0/last-image"]

    ok_total = True
    detalles = []
    for prop in props:
        rc = subprocess.call(
            ["xfconf-query", "-c", canal, "-p", prop,
             "-n", "-t", "string", "-s", ruta])
        if rc != 0:
            # ya existía -> solo actualizar (sin -n)
            rc = subprocess.call(
                ["xfconf-query", "-c", canal, "-p", prop, "-s", ruta])
        detalles.append((prop, rc))
        ok_total = ok_total and (rc == 0)

    if ok_total:
        return True, "xfce (%d propiedad%s)" % (
            len(props), "es" if len(props) != 1 else "")
    return False, "fallo en xfconf-query: %s" % detalles


def _aplicar_cinnamon(ruta):
    uri = "file://%s" % ruta
    rc = subprocess.call(
        ["gsettings", "set", "org.cinnamon.desktop.background",
         "picture-uri", uri])
    if rc == 0:
        return True, "cinnamon"
    return False, "fallo en gsettings (rc=%d)" % rc


def _aplicar_feh(ruta):
    if subprocess.call(["which", "feh"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL) != 0:
        return False, "feh no está instalado"
    rc = subprocess.call(["feh", "--bg-fill", ruta])
    if rc == 0:
        return True, "feh"
    return False, "fallo en feh (rc=%d)" % rc


def aplicar_fondo(ruta):
    """Aplica `ruta` como fondo de escritorio. Devuelve (ok, mensaje)."""
    if not os.path.isfile(ruta):
        return False, "el archivo no existe"

    escritorio = _escritorio_actual()

    if escritorio == "xfce":
        ok, msg = _aplicar_xfce(ruta)
        if ok:
            return True, "aplicado con xfconf-query (%s)" % msg
        # si falla, intentar feh como respaldo
        ok2, msg2 = _aplicar_feh(ruta)
        if ok2:
            return True, "aplicado con feh (xfconf falló: %s)" % msg
        return False, "%s / %s" % (msg, msg2)

    if escritorio == "cinnamon":
        ok, msg = _aplicar_cinnamon(ruta)
        if ok:
            return True, "aplicado con gsettings (%s)" % msg
        ok2, msg2 = _aplicar_feh(ruta)
        if ok2:
            return True, "aplicado con feh (gsettings falló: %s)" % msg
        return False, "%s / %s" % (msg, msg2)

    # entorno desconocido: probar todo en orden
    ok, msg = _aplicar_xfce(ruta)
    if ok:
        return True, "aplicado con xfconf-query (%s)" % msg
    ok, msg = _aplicar_cinnamon(ruta)
    if ok:
        return True, "aplicado con gsettings (%s)" % msg
    ok, msg = _aplicar_feh(ruta)
    if ok:
        return True, "aplicado con feh (%s)" % msg
    return False, "no se encontró una herramienta de escritorio compatible"


# ----------------------------------------------------------------------
# GUI (GTK3, mismo look claro/navy que las ventanas del panel)
# ----------------------------------------------------------------------

CSS = """
.fpf-win { background: #ffffff; }
.fpf-title { color: #14233f; font-weight: bold; font-size: 15px; }
.fpf-text { color: #14233f; }
.fpf-estado { color: #2d5aa6; font-weight: bold; }
.fpf-aplicar {
    background: #2d5aa6; color: #ffffff; font-weight: bold;
    border-radius: 6px; padding: 6px 18px;
}
.fpf-aplicar:hover { background: #244a8a; }
.fpf-elegir {
    background: #eef2f9; color: #14233f;
    border-radius: 6px; padding: 6px 14px;
    border: 1px solid #c7d2e6;
}
.fpf-elegir:hover { background: #dde6f5; }
.fpf-miniatura {
    border: 3px solid transparent;
    border-radius: 4px;
    padding: 4px;
}
.fpf-miniatura-sel {
    border: 3px solid #2d5aa6;
    border-radius: 4px;
    padding: 4px;
    background: #eef2f9;
}

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


def main_gui():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gtk, Gdk, GdkPixbuf, GLib

    prov = Gtk.CssProvider()
    prov.load_from_data(CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), prov,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    win = Gtk.Window(title="Fondo de Escritorio")
    win.set_default_size(640, 520)
    hb = Gtk.HeaderBar()
    hb.set_show_close_button(True)
    hb.set_decoration_layout(":close")
    hb.props.title = "Fondo de Escritorio"
    hb.get_style_context().add_class("fp-titlebar")
    win.set_titlebar(hb)
    win.set_position(Gtk.WindowPosition.CENTER)
    win.get_style_context().add_class("fpf-win")
    win.connect("destroy", Gtk.main_quit)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                  margin=18)
    win.add(box)

    tit = Gtk.Label(label="Fondo de Escritorio", xalign=0)
    tit.get_style_context().add_class("fpf-title")
    box.pack_start(tit, False, False, 0)

    sub = Gtk.Label(xalign=0, wrap=True,
                    label="Elegí una imagen de la lista o cargá una propia "
                          "y aplicala como fondo del escritorio.")
    sub.get_style_context().add_class("fpf-text")
    box.pack_start(sub, False, False, 0)

    # ------------------------------------------------------------
    # grilla de miniaturas dentro de un scroll
    # ------------------------------------------------------------
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_vexpand(True)
    box.pack_start(scroll, True, True, 0)

    flow = Gtk.FlowBox()
    flow.set_valign(Gtk.Align.START)
    flow.set_max_children_per_line(4)
    flow.set_selection_mode(Gtk.SelectionMode.NONE)
    flow.set_row_spacing(6)
    flow.set_column_spacing(6)
    scroll.add(flow)

    estado = {"seleccionada": None, "hijos": []}

    def marcar_seleccion(hijo_elegido):
        for hijo, ruta in estado["hijos"]:
            ctx = hijo.get_style_context()
            if hijo is hijo_elegido:
                ctx.remove_class("fpf-miniatura")
                ctx.add_class("fpf-miniatura-sel")
            else:
                ctx.remove_class("fpf-miniatura-sel")
                ctx.add_class("fpf-miniatura")

    def agregar_miniatura(ruta):
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                ruta, ANCHO_MINIATURA, ALTO_MINIATURA, True)
        except Exception:
            return
        img = Gtk.Image.new_from_pixbuf(pixbuf)
        evbox = Gtk.EventBox()
        evbox.add(img)
        evbox.get_style_context().add_class("fpf-miniatura")
        evbox.set_tooltip_text(os.path.basename(ruta))

        def on_click(_w, _e, r=ruta, eb=evbox):
            estado["seleccionada"] = r
            marcar_seleccion(eb)
            lbl_est.set_text("Seleccionado: %s" % os.path.basename(r))

        evbox.connect("button-press-event", on_click)
        flow.add(evbox)
        flow.show_all()
        estado["hijos"].append((evbox, ruta))

    def cargar_miniaturas_diferido():
        rutas = listar_fondos()
        pendientes = list(rutas)

        def paso():
            if not pendientes:
                if not estado["hijos"]:
                    lbl_est.set_text(
                        "No se encontraron imágenes en %s" % CARPETA_FONDOS)
                return False
            ruta = pendientes.pop(0)
            agregar_miniatura(ruta)
            return True  # seguir en el próximo ciclo idle

        GLib.idle_add(paso)

    # ------------------------------------------------------------
    # elegir imagen propia
    # ------------------------------------------------------------
    def on_elegir(_b):
        dialogo = Gtk.FileChooserDialog(
            title="Elegir imagen", parent=win,
            action=Gtk.FileChooserAction.OPEN)
        dialogo.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN, Gtk.ResponseType.OK)

        filtro = Gtk.FileFilter()
        filtro.set_name("Imágenes")
        filtro.add_mime_type("image/png")
        filtro.add_mime_type("image/jpeg")
        filtro.add_pattern("*.png")
        filtro.add_pattern("*.jpg")
        filtro.add_pattern("*.jpeg")
        dialogo.add_filter(filtro)

        if dialogo.run() == Gtk.ResponseType.OK:
            ruta = dialogo.get_filename()
            estado["seleccionada"] = ruta
            marcar_seleccion(None)
            lbl_est.set_text("Seleccionado: %s" % os.path.basename(ruta))
        dialogo.destroy()

    # ------------------------------------------------------------
    # fila inferior: elegir / estado / aplicar
    # ------------------------------------------------------------
    lbl_est = Gtk.Label(xalign=0, wrap=True)
    lbl_est.get_style_context().add_class("fpf-estado")
    lbl_est.set_text("Ningún fondo seleccionado")
    box.pack_start(lbl_est, False, False, 0)

    fila_botones = Gtk.Box(spacing=10)
    box.pack_start(fila_botones, False, False, 0)

    btn_elegir = Gtk.Button(label="Elegir imagen…")
    btn_elegir.get_style_context().add_class("fpf-elegir")
    btn_elegir.connect("clicked", on_elegir)
    fila_botones.pack_start(btn_elegir, False, False, 0)

    btn_aplicar = Gtk.Button(label="Aplicar")
    btn_aplicar.get_style_context().add_class("fpf-aplicar")
    fila_botones.pack_end(btn_aplicar, False, False, 0)

    def on_aplicar(_b):
        ruta = estado["seleccionada"]
        if not ruta:
            lbl_est.set_text("Elegí una imagen primero")
            return
        ok, msg = aplicar_fondo(ruta)
        if ok:
            lbl_est.set_text("✓ Fondo aplicado (%s)" % msg)
        else:
            lbl_est.set_text("No se pudo aplicar el fondo: %s" % msg)

    btn_aplicar.connect("clicked", on_aplicar)

    win.show_all()
    GLib.idle_add(cargar_miniaturas_diferido)
    Gtk.main()


def main_cli(argv):
    print(__doc__)
    return 1


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main_cli(sys.argv[1:]))
    main_gui()
