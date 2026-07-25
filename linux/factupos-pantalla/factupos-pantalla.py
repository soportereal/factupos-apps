#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FactuPOS · Monitores
---------------------
Herramienta propia de FactuPOS OS para acomodar monitores (resolución,
monitor principal y posición relativa) usando xrandr, sin necesidad de
permisos de root.

Uso:
  factupos-pantalla        ventana gráfica
"""

import os
import re
import subprocess

VERSION = "1.0.1"                                 # fuente única de versión


# ----------------------------------------------------------------------
# Lógica: leer y aplicar con xrandr
# ----------------------------------------------------------------------

RE_SALIDA = re.compile(
    r'^(?P<nombre>\S+)\s+(?P<estado>connected|disconnected)'
    r'(?P<primario>\s+primary)?'
    r'(?:\s+(?P<ancho>\d+)x(?P<alto>\d+)\+(?P<x>\d+)\+(?P<y>\d+))?'
)
RE_MODO = re.compile(r'^\s+(?P<res>\d+x\d+)(?P<resto>.*)$')


def leer_monitores():
    """Corre `xrandr --query` y arma la lista de monitores CONECTADOS.

    Devuelve (monitores, error). Cada monitor es un dict:
    nombre, primario, ancho, alto, x, y, modos (lista de resoluciones
    únicas, en el orden que las reporta xrandr) y modo_actual.
    """
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    try:
        salida = subprocess.check_output(
            ["xrandr", "--query"], env=env,
            stderr=subprocess.STDOUT, text=True)
    except Exception as e:
        return [], str(e)

    monitores = []
    actual = None

    for linea in salida.splitlines():
        m = RE_SALIDA.match(linea)
        if m:
            if m.group('estado') != 'connected':
                actual = None
                continue
            actual = {
                'nombre': m.group('nombre'),
                'primario': bool(m.group('primario')),
                'ancho': int(m.group('ancho')) if m.group('ancho') else 0,
                'alto': int(m.group('alto')) if m.group('alto') else 0,
                'x': int(m.group('x')) if m.group('x') else 0,
                'y': int(m.group('y')) if m.group('y') else 0,
                'modos': [],
                'modo_actual': None,
            }
            monitores.append(actual)
            continue
        if actual is not None:
            mm = RE_MODO.match(linea)
            if mm:
                res = mm.group('res')
                resto = mm.group('resto')
                if res not in actual['modos']:
                    actual['modos'].append(res)
                if '*' in resto and actual['modo_actual'] is None:
                    actual['modo_actual'] = res

    return monitores, None


def posicion_actual(monitor, otro):
    """Adivina la relación entre 'monitor' y 'otro' según su geometría
    actual, para preseleccionar algo razonable en el combo."""
    if monitor['x'] == otro['x'] and monitor['y'] == otro['y']:
        return 'same'
    if monitor['x'] >= otro['x'] + otro['ancho']:
        return 'right'
    if monitor['x'] + monitor['ancho'] <= otro['x']:
        return 'left'
    return None


def aplicar_xrandr(cambios):
    """cambios: lista de dicts {nombre, resolucion, primario, posicion}
    donde posicion es None o (tipo, otro_nombre) con tipo en
    right/left/same. Corre UN solo xrandr atómico. Devuelve (ok, mensaje)."""
    args = ["xrandr"]
    flag_por_tipo = {
        'right': '--right-of',
        'left': '--left-of',
        'same': '--same-as',
    }
    for c in cambios:
        if not c['resolucion']:
            continue
        args += ["--output", c['nombre'], "--mode", c['resolucion']]
        if c['primario']:
            args += ["--primary"]
        if c['posicion']:
            tipo, otro = c['posicion']
            args += [flag_por_tipo[tipo], otro]

    try:
        subprocess.run(args, check=True, capture_output=True, text=True)
        return True, "Cambios aplicados correctamente."
    except subprocess.CalledProcessError as e:
        detalle = (e.stderr or e.stdout or str(e)).strip()
        return False, "Error de xrandr: %s" % detalle
    except Exception as e:
        return False, "No se pudo ejecutar xrandr: %s" % e


# ----------------------------------------------------------------------
# GUI (GTK3, mismo look claro/navy que las ventanas del panel)
# ----------------------------------------------------------------------

CSS = """
.fpp-win { background: #ffffff; }
.fpp-title { color: #14233f; font-weight: bold; font-size: 15px; }
.fpp-text { color: #14233f; }
.fpp-estado { color: #2d5aa6; font-weight: bold; }
.fpp-error { color: #b3261e; font-weight: bold; }
.fpp-tarjeta {
    background: #f4f6fb; border: 1px solid #d7deec; border-radius: 8px;
    padding: 10px;
}
.fpp-nombre { color: #14233f; font-weight: bold; font-size: 13px; }
.fpp-aplicar {
    background: #2d5aa6; color: #ffffff; font-weight: bold;
    border-radius: 6px; padding: 6px 18px;
}
.fpp-aplicar:hover { background: #244a8a; }
.fpp-identificar {
    background: #ffffff; color: #2d5aa6; font-weight: bold;
    border-radius: 6px; padding: 6px 18px; border: 1px solid #2d5aa6;
}
.fpp-identificar:hover { background: #eef3fb; }
.fpp-ident-win { background-color: #2d5aa6; }
.fpp-ident-label { color: #ffffff; font-weight: bold; font-size: 72px; }

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
    from gi.repository import Gtk, Gdk, GLib

    prov = Gtk.CssProvider()
    prov.load_from_data(CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), prov,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    win = Gtk.Window(title="Monitores")
    win.set_default_size(460, 520)
    hb = Gtk.HeaderBar()
    hb.set_show_close_button(True)
    hb.set_decoration_layout(":close")
    hb.props.title = "Monitores"
    hb.get_style_context().add_class("fp-titlebar")
    win.set_titlebar(hb)
    win.set_position(Gtk.WindowPosition.CENTER)
    win.set_resizable(False)
    win.get_style_context().add_class("fpp-win")
    win.connect("destroy", Gtk.main_quit)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                   margin=18)
    win.add(box)

    tit = Gtk.Label(label="Monitores", xalign=0)
    tit.get_style_context().add_class("fpp-title")
    box.pack_start(tit, False, False, 0)

    sub = Gtk.Label(xalign=0, wrap=True,
                     label="Configurá resolución, monitor principal y "
                           "posición de cada pantalla conectada.")
    sub.get_style_context().add_class("fpp-text")
    box.pack_start(sub, False, False, 0)

    # área con scroll para las tarjetas de monitores
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_height(340)
    box.pack_start(scroll, True, True, 0)

    caja_tarjetas = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    scroll.add(caja_tarjetas)

    lbl_est = Gtk.Label(xalign=0, wrap=True)
    lbl_est.get_style_context().add_class("fpp-estado")
    box.pack_start(lbl_est, False, False, 0)

    fila_botones = Gtk.Box(spacing=10)
    box.pack_start(fila_botones, False, False, 0)

    btn_identificar = Gtk.Button(label="Identificar")
    btn_identificar.get_style_context().add_class("fpp-identificar")
    fila_botones.pack_start(btn_identificar, False, False, 0)

    btn_aplicar = Gtk.Button(label="Aplicar")
    btn_aplicar.get_style_context().add_class("fpp-aplicar")
    fila_botones.pack_end(btn_aplicar, False, False, 0)

    # estado mutable de la sesión
    estado = {'monitores': [], 'controles': {}}

    def limpiar_tarjetas():
        for hijo in caja_tarjetas.get_children():
            caja_tarjetas.remove(hijo)

    def construir_tarjetas():
        limpiar_tarjetas()
        monitores, error = leer_monitores()
        estado['monitores'] = monitores
        estado['controles'] = {}

        if error:
            lbl_est.get_style_context().add_class("fpp-error")
            lbl_est.set_text("No se pudo leer xrandr: %s" % error)
            caja_tarjetas.show_all()
            return
        if not monitores:
            lbl_est.get_style_context().remove_class("fpp-error")
            lbl_est.set_text("No se detectaron monitores conectados.")
            caja_tarjetas.show_all()
            return

        checks_principal = []  # (checkbutton, handler_id)

        def on_principal_toggled(cb):
            if not cb.get_active():
                return
            for otro_cb, hid in checks_principal:
                if otro_cb is not cb:
                    otro_cb.handler_block(hid)
                    otro_cb.set_active(False)
                    otro_cb.handler_unblock(hid)

        for mon in monitores:
            nombre = mon['nombre']

            marco = Gtk.Frame()
            marco.set_shadow_type(Gtk.ShadowType.NONE)
            marco.get_style_context().add_class("fpp-tarjeta")
            caja_tarjetas.pack_start(marco, False, False, 0)

            interior = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                spacing=8)
            marco.add(interior)

            lbl_nombre = Gtk.Label(xalign=0)
            lbl_nombre.get_style_context().add_class("fpp-nombre")
            estado_txt = mon['modo_actual'] or "sin modo activo"
            lbl_nombre.set_text("%s  (%s)" % (nombre, estado_txt))
            interior.pack_start(lbl_nombre, False, False, 0)

            # combo resolución
            fila_res = Gtk.Box(spacing=10)
            l1 = Gtk.Label(label="Resolución", xalign=0)
            l1.get_style_context().add_class("fpp-text")
            combo_res = Gtk.ComboBoxText()
            for r in mon['modos']:
                combo_res.append_text(r)
            if mon['modo_actual'] in mon['modos']:
                combo_res.set_active(mon['modos'].index(mon['modo_actual']))
            elif mon['modos']:
                combo_res.set_active(0)
            fila_res.pack_start(l1, True, True, 0)
            fila_res.pack_end(combo_res, False, False, 0)
            interior.pack_start(fila_res, False, False, 0)

            # checkbox principal
            check_principal = Gtk.CheckButton(label="Monitor principal")
            check_principal.get_style_context().add_class("fpp-text")
            check_principal.set_active(mon['primario'])
            hid = check_principal.connect(
                "toggled", lambda cb: on_principal_toggled(cb))
            checks_principal.append((check_principal, hid))
            interior.pack_start(check_principal, False, False, 0)

            # combo posición (solo si hay 2+ monitores)
            combo_pos = None
            if len(monitores) >= 2:
                fila_pos = Gtk.Box(spacing=10)
                l2 = Gtk.Label(label="Posición", xalign=0)
                l2.get_style_context().add_class("fpp-text")
                combo_pos = Gtk.ComboBoxText()
                combo_pos.append("keep", "(mantener posición actual)")
                sugerida = "keep"
                for otro in monitores:
                    if otro is mon:
                        continue
                    combo_pos.append(
                        "right:%s" % otro['nombre'],
                        "A la derecha de %s" % otro['nombre'])
                    combo_pos.append(
                        "left:%s" % otro['nombre'],
                        "A la izquierda de %s" % otro['nombre'])
                    combo_pos.append(
                        "same:%s" % otro['nombre'],
                        "Duplicar %s" % otro['nombre'])
                    if sugerida == "keep":
                        rel = posicion_actual(mon, otro)
                        if rel:
                            sugerida = "%s:%s" % (rel, otro['nombre'])
                combo_pos.set_active_id(sugerida)
                fila_pos.pack_start(l2, True, True, 0)
                fila_pos.pack_end(combo_pos, False, False, 0)
                interior.pack_start(fila_pos, False, False, 0)

            estado['controles'][nombre] = {
                'combo_res': combo_res,
                'check_principal': check_principal,
                'combo_pos': combo_pos,
            }

        caja_tarjetas.show_all()

    def on_aplicar(_b):
        cambios = []
        for nombre, ctrl in estado['controles'].items():
            posicion = None
            if ctrl['combo_pos'] is not None:
                pid = ctrl['combo_pos'].get_active_id()
                if pid and pid != "keep":
                    tipo, otro = pid.split(":", 1)
                    posicion = (tipo, otro)
            cambios.append({
                'nombre': nombre,
                'resolucion': ctrl['combo_res'].get_active_text(),
                'primario': ctrl['check_principal'].get_active(),
                'posicion': posicion,
            })

        lbl_est.get_style_context().remove_class("fpp-error")
        lbl_est.set_text("Aplicando…")
        while Gtk.events_pending():
            Gtk.main_iteration()

        ok, mensaje = aplicar_xrandr(cambios)
        if not ok:
            lbl_est.get_style_context().add_class("fpp-error")
        lbl_est.set_text(mensaje)
        construir_tarjetas()

    def on_identificar(_b):
        monitores = estado['monitores']
        ventanas = []
        for i, mon in enumerate(monitores):
            if mon['ancho'] <= 0 or mon['alto'] <= 0:
                continue
            vi = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
            vi.set_decorated(False)
            vi.set_skip_taskbar_hint(True)
            vi.set_skip_pager_hint(True)
            vi.get_style_context().add_class("fpp-ident-win")
            vi.move(mon['x'], mon['y'])
            vi.resize(mon['ancho'], mon['alto'])

            centro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                              halign=Gtk.Align.CENTER,
                              valign=Gtk.Align.CENTER)
            lbl = Gtk.Label(label="%d\n%s" % (i + 1, mon['nombre']))
            lbl.set_justify(Gtk.Justification.CENTER)
            lbl.get_style_context().add_class("fpp-ident-label")
            centro.pack_start(lbl, True, True, 0)
            vi.add(centro)

            vi.show_all()
            vi.set_keep_above(True)
            ventanas.append(vi)

        def cerrar_todas():
            for vi in ventanas:
                vi.destroy()
            return False

        if ventanas:
            GLib.timeout_add(2000, cerrar_todas)

    btn_aplicar.connect("clicked", on_aplicar)
    btn_identificar.connect("clicked", on_identificar)

    construir_tarjetas()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main_gui()
