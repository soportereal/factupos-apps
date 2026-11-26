#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FactuPOS · Inicio de sesión automático
--------------------------------------
Herramienta propia de FactuPOS OS para activar/desactivar el auto-login
de LightDM sin tocar archivos a mano.

Escribe /etc/lightdm/lightdm.conf.d/70-factupos-autologin.conf

Uso:
  factupos-autologin                  ventana gráfica
  factupos-autologin --status         muestra el estado (no requiere root)
  factupos-autologin --enable USER    activa auto-login para USER (root)
  factupos-autologin --disable        desactiva auto-login (root)
"""

import os
import sys
import pwd
import subprocess

VERSION = "1.1.1"                                 # fuente única de versión

CONF_DIR = "/etc/lightdm/lightdm.conf.d"
CONF = os.path.join(CONF_DIR, "70-factupos-autologin.conf")


# ----------------------------------------------------------------------
# Lógica (sirve igual para CLI y GUI)
# ----------------------------------------------------------------------

def usuarios_reales():
    """Usuarios humanos del sistema (uid 1000-59999 con shell de login)."""
    us = []
    for p in pwd.getpwall():
        if 1000 <= p.pw_uid < 60000 and not p.pw_shell.endswith(("nologin", "false")):
            us.append(p.pw_name)
    return sorted(us)


def estado_actual():
    """Devuelve el usuario con auto-login activo, o None."""
    try:
        with open(CONF) as f:
            for line in f:
                line = line.strip()
                if line.startswith("autologin-user="):
                    v = line.split("=", 1)[1].strip()
                    if v:
                        return v
    except FileNotFoundError:
        pass
    return None


def activar(user):
    if user not in usuarios_reales():
        raise SystemExit(f"usuario desconocido: {user}")
    os.makedirs(CONF_DIR, exist_ok=True)
    with open(CONF, "w") as f:
        f.write("# Generado por factupos-autologin v%s — NO editar a mano\n"
                "[Seat:*]\n"
                "autologin-user=%s\n"
                "autologin-user-timeout=0\n" % (VERSION, user))


def desactivar():
    try:
        os.remove(CONF)
    except FileNotFoundError:
        pass


def _reejecutar_root(args):
    """Se relanza a sí mismo con pkexec para la parte que necesita root."""
    yo = os.path.abspath(__file__)
    return subprocess.call(["pkexec", "python3", yo] + args)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main_cli(argv):
    if argv[0] == "--status":
        u = estado_actual()
        print(u if u else "desactivado")
        return 0
    if argv[0] == "--enable" and len(argv) > 1:
        if os.geteuid() != 0:
            return _reejecutar_root(argv)
        activar(argv[1])
        print("auto-login activado para", argv[1])
        return 0
    if argv[0] == "--disable":
        if os.geteuid() != 0:
            return _reejecutar_root(argv)
        desactivar()
        print("auto-login desactivado")
        return 0
    print(__doc__)
    return 1


# ----------------------------------------------------------------------
# GUI (GTK3, mismo look claro/navy que las ventanas del panel)
# ----------------------------------------------------------------------

CSS = """
.fpa-win { background: #ffffff; }
.fpa-title { color: #14233f; font-weight: bold; font-size: 15px; }
.fpa-text { color: #14233f; }
.fpa-estado { color: #2d5aa6; font-weight: bold; }
.fpa-aplicar {
    background: #2d5aa6; color: #ffffff; font-weight: bold;
    border-radius: 6px; padding: 6px 18px;
}
.fpa-aplicar:hover { background: #244a8a; }

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

/* ===== PIEL NAVY (#2698, 13-oct-2026) — mismo lenguaje que el kiosko y la barra 1.6.x.
   Va AL FINAL del CSS: con igual especificidad, la ultima regla gana. Copiada dentro de
   cada app a proposito (cada una es independiente, no comparte archivos). ===== */
.fpa-win { background: #0b1533; color: #e2e8f0; }
.fpa-win scrolledwindow, .fpa-win viewport { background: #0b1533; }
.fpa-header { background: linear-gradient(135deg, #1e1b4b, #1e3a8a); border-bottom: 2px solid #7c3aed; }
.fpa-header-title, .fpa-title { color: #ffffff; }
.fpa-header-resumen { color: #a5b4fc; }
.fpa-text, .fpa-nombre, .fpa-seccion { color: #e2e8f0; }
.fpa-seccion-titulo { background: #14224d; color: #a5b4fc; }
.fpa-nota { color: #b4c2e0; }
.fpa-estado { color: #38bdf8; }
.fpa-error { color: #fb7185; }
.fpa-tarjeta {
    background: linear-gradient(to bottom, #182a5c, #14224d);
    border: 1px solid rgba(255,255,255,0.10); border-top-color: rgba(255,255,255,0.20);
    border-bottom-color: rgba(0,0,0,0.55); border-radius: 14px;
    box-shadow: 0 3px 6px rgba(0,0,0,0.45);
}
.fpa-aplicar {
    background: linear-gradient(135deg, #7c3aed, #2563eb); color: #ffffff; font-weight: bold;
    border: 1px solid rgba(255,255,255,0.35); border-radius: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.4);
}
.fpa-aplicar:hover { background: linear-gradient(135deg, #8b5cf6, #3b82f6); }
.fpa-aplicar label { color: #ffffff; }
.fpa-elegir, .fpa-identificar {
    background: rgba(255,255,255,0.08); color: #e2e8f0;
    border: 1px solid rgba(255,255,255,0.25); border-radius: 12px;
}
.fpa-elegir:hover, .fpa-identificar:hover { background: rgba(255,255,255,0.16); }
.fpa-elegir label, .fpa-identificar label { color: #e2e8f0; }
.fpa-miniatura { border: 2px solid rgba(255,255,255,0.10); border-radius: 10px; }
.fpa-miniatura-sel { border: 3px solid #38bdf8; border-radius: 10px; }
.fpa-win entry { background: #14224d; color: #ffffff; border: 1px solid #4f63a8; border-radius: 12px; }
.fpa-win entry:focus { border-color: #38bdf8; }
.fpa-win combobox button { background: #14224d; color: #ffffff; border: 1px solid #4f63a8; border-radius: 10px; }
.fpa-win combobox button label, .fpa-win combobox arrow { color: #ffffff; }
.fpa-win switch { background: #334155; border: 1px solid rgba(255,255,255,0.25); border-radius: 14px; }
.fpa-win switch:checked { background: #16a34a; }
.fpa-win switch slider { background: #ffffff; border-radius: 12px; }
.fpa-win checkbutton label { color: #e2e8f0; }
.fpa-win checkbutton check { background: #14224d; border: 1px solid #7184ad; }
.fpa-win checkbutton check:checked { background: #7c3aed; border-color: #a78bfa; color: #ffffff; }
.fpa-win treeview { background-color: #0f1a3a; color: #e2e8f0; }
.fpa-win treeview:selected { background-color: #7c3aed; color: #ffffff; }
.fpa-win treeview header button { background: #14224d; color: #a5b4fc; font-weight: bold;
    border: none; border-bottom: 1px solid rgba(255,255,255,0.12); }
.fpa-win separator { background: rgba(255,255,255,0.12); }
.fp-titlebar { background: linear-gradient(to right, #0b1533, #14224d 55%, #1e1b4b); }
"""


def main_gui():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk

    prov = Gtk.CssProvider()
    prov.load_from_data(CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), prov,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    win = Gtk.Window(title="Inicio de sesión automático")
    win.set_default_size(420, 230)
    hb = Gtk.HeaderBar()
    hb.set_show_close_button(True)
    hb.set_decoration_layout(":close")
    hb.props.title = "Inicio de sesión automático"
    hb.get_style_context().add_class("fp-titlebar")
    win.set_titlebar(hb)
    win.set_position(Gtk.WindowPosition.CENTER)
    win.set_resizable(False)
    win.get_style_context().add_class("fpa-win")
    win.connect("destroy", Gtk.main_quit)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                  margin=18)
    win.add(box)

    tit = Gtk.Label(label="Inicio de sesión automático", xalign=0)
    tit.get_style_context().add_class("fpa-title")
    box.pack_start(tit, False, False, 0)

    sub = Gtk.Label(xalign=0, wrap=True,
                    label="El equipo entrará directo al escritorio sin pedir "
                          "contraseña al encender. Pensado para terminales POS.")
    sub.get_style_context().add_class("fpa-text")
    box.pack_start(sub, False, False, 0)

    # fila switch
    fila_sw = Gtk.Box(spacing=10)
    lbl_sw = Gtk.Label(label="Activar auto-login", xalign=0)
    lbl_sw.get_style_context().add_class("fpa-text")
    sw = Gtk.Switch()
    fila_sw.pack_start(lbl_sw, True, True, 0)
    fila_sw.pack_end(sw, False, False, 0)
    box.pack_start(fila_sw, False, False, 0)

    # fila usuario
    fila_u = Gtk.Box(spacing=10)
    lbl_u = Gtk.Label(label="Usuario", xalign=0)
    lbl_u.get_style_context().add_class("fpa-text")
    combo = Gtk.ComboBoxText()
    for u in usuarios_reales():
        combo.append_text(u)
    fila_u.pack_start(lbl_u, True, True, 0)
    fila_u.pack_end(combo, False, False, 0)
    box.pack_start(fila_u, False, False, 0)

    # estado + aplicar
    lbl_est = Gtk.Label(xalign=0)
    lbl_est.get_style_context().add_class("fpa-estado")
    box.pack_start(lbl_est, False, False, 0)

    btn = Gtk.Button(label="Aplicar")
    btn.get_style_context().add_class("fpa-aplicar")
    box.pack_end(btn, False, False, 0)

    def refrescar():
        actual = estado_actual()
        us = usuarios_reales()
        if actual:
            sw.set_active(True)
            if actual in us:
                combo.set_active(us.index(actual))
            lbl_est.set_text("Estado: ACTIVO para «%s»" % actual)
        else:
            sw.set_active(False)
            # preseleccionar el usuario de la sesión
            yo = pwd.getpwuid(os.getuid()).pw_name
            if yo in us:
                combo.set_active(us.index(yo))
            lbl_est.set_text("Estado: desactivado")

    def aplicar(_b):
        if sw.get_active():
            u = combo.get_active_text()
            if not u:
                lbl_est.set_text("Elegí un usuario")
                return
            rc = _reejecutar_root(["--enable", u]) if os.geteuid() else (activar(u) or 0)
        else:
            rc = _reejecutar_root(["--disable"]) if os.geteuid() else (desactivar() or 0)
        if rc == 0:
            refrescar()
            lbl_est.set_text(lbl_est.get_text() + "  ✓ aplicado (rige al reiniciar)")
        else:
            lbl_est.set_text("No se aplicó (autorización cancelada)")

    btn.connect("clicked", aplicar)
    refrescar()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main_cli(sys.argv[1:]))
    main_gui()
