#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FactuPOS · Opciones de Energía
-------------------------------
Herramienta propia de FactuPOS OS para configurar el ahorro de energía de
la terminal POS sin tocar archivos a mano: apagado de pantalla, suspensión
automática del equipo y comportamiento del botón de encendido.

Archivos que administra:
  ~/.config/factupos-energia.conf                       (config de pantalla, por usuario)
  ~/.config/autostart/factupos-energia-apply.desktop     (reaplica la pantalla al iniciar sesión)
  systemd sleep.target / suspend.target                  (mask/unmask = suspensión automática)
  /etc/systemd/logind.conf.d/50-factupos-energia.conf    (botón de encendido)

Uso:
  factupos-energia                            ventana gráfica
  factupos-energia --status                   muestra el estado (no requiere root)
  factupos-energia --apply                    reaplica la pantalla desde el .conf (autostart)
  factupos-energia --set-sleep on|off         permite/bloquea la suspensión automática (root)
  factupos-energia --set-powerkey ACCION      poweroff|suspend|ignore para el botón (root)
"""

import os
import sys
import subprocess
import configparser

VERSION = "1.0.1"                                 # fuente única de versión

# ----------------------------------------------------------------------
# Rutas
# ----------------------------------------------------------------------

CONFIG_DIR = os.path.expanduser("~/.config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "factupos-energia.conf")

AUTOSTART_DIR = os.path.join(CONFIG_DIR, "autostart")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, "factupos-energia-apply.desktop")

LOGIND_DIR = "/etc/systemd/logind.conf.d"
LOGIND_CONF = os.path.join(LOGIND_DIR, "50-factupos-energia.conf")

SLEEP_TARGETS = ["sleep.target", "suspend.target"]

PANTALLA_OPCIONES = [0, 5, 10, 15, 30, 60]         # minutos; 0 = Nunca
PANTALLA_DEFECTO = 10                              # si no hay .conf todavía

POWERKEY_OPCIONES = ["poweroff", "suspend", "ignore"]
POWERKEY_ETIQUETAS = {
    "poweroff": "Apagar",
    "suspend": "Suspender",
    "ignore": "No hacer nada",
}
POWERKEY_DEFECTO = "poweroff"                      # comportamiento estándar del sistema


def etiqueta_pantalla(minutos):
    return "Nunca" if minutos <= 0 else "%d minutos" % minutos


# ----------------------------------------------------------------------
# Pantalla (xset) — no requiere root, se guarda por usuario
# ----------------------------------------------------------------------

def leer_config_pantalla():
    """Minutos configurados para apagar la pantalla (0 = Nunca)."""
    if not os.path.exists(CONFIG_FILE):
        return PANTALLA_DEFECTO
    cfg = configparser.ConfigParser()
    try:
        cfg.read(CONFIG_FILE)
        return cfg.getint("energia", "pantalla_min", fallback=PANTALLA_DEFECTO)
    except Exception:
        return PANTALLA_DEFECTO


def guardar_config_pantalla(minutos):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_FILE):
        try:
            cfg.read(CONFIG_FILE)
        except Exception:
            pass
    if not cfg.has_section("energia"):
        cfg.add_section("energia")
    cfg.set("energia", "pantalla_min", str(minutos))
    with open(CONFIG_FILE, "w") as f:
        cfg.write(f)


def aplicar_pantalla(minutos):
    """Aplica en vivo el apagado de pantalla vía xset. Falla con gracia
    si no hay servidor gráfico disponible (p.ej. corriendo por SSH)."""
    try:
        subprocess.call(["xset", "s", "off"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if minutos <= 0:
            subprocess.call(["xset", "-dpms"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            segundos = str(minutos * 60)
            subprocess.call(["xset", "dpms", "0", "0", segundos],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def asegurar_autostart():
    """Escribe el .desktop en autostart para reaplicar la pantalla al
    iniciar sesión (xset no persiste solo, hay que repetirlo cada login)."""
    os.makedirs(AUTOSTART_DIR, exist_ok=True)
    with open(AUTOSTART_FILE, "w") as f:
        f.write(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=FactuPOS - Aplicar energia\n"
            "Comment=Reaplica el apagado de pantalla configurado en FactuPOS Energia\n"
            "Exec=factupos-energia --apply\n"
            "Terminal=false\n"
            "NoDisplay=true\n"
            "X-GNOME-Autostart-enabled=true\n"
        )


# ----------------------------------------------------------------------
# Suspensión automática del equipo (systemd mask/unmask) — requiere root
# ----------------------------------------------------------------------

def sleep_permitido():
    """True si la suspensión automática está permitida (no enmascarada)."""
    try:
        r = subprocess.run(["systemctl", "is-enabled"] + SLEEP_TARGETS,
                            capture_output=True, text=True, timeout=5)
        salida = (r.stdout or "").strip().splitlines()
        return not any(s.strip() == "masked" for s in salida)
    except Exception:
        return True  # si no se puede determinar, no asumimos bloqueo


def set_sleep(permitir):
    if permitir:
        subprocess.call(["systemctl", "unmask"] + SLEEP_TARGETS)
    else:
        subprocess.call(["systemctl", "mask"] + SLEEP_TARGETS)


# ----------------------------------------------------------------------
# Botón de encendido (logind.conf.d) — requiere root, rige tras reiniciar
# ----------------------------------------------------------------------

def powerkey_actual():
    try:
        with open(LOGIND_CONF) as f:
            for line in f:
                line = line.strip()
                if line.startswith("HandlePowerKey="):
                    v = line.split("=", 1)[1].strip()
                    if v:
                        return v
    except FileNotFoundError:
        pass
    return None  # sin archivo = usa el valor por defecto del sistema


def set_powerkey(accion):
    if accion not in POWERKEY_OPCIONES:
        raise SystemExit("acción inválida: %s" % accion)
    os.makedirs(LOGIND_DIR, exist_ok=True)
    with open(LOGIND_CONF, "w") as f:
        f.write("# Generado por factupos-energia v%s — NO editar a mano\n"
                 "[Login]\n"
                 "HandlePowerKey=%s\n" % (VERSION, accion))


# ----------------------------------------------------------------------
# Relanzarse a sí mismo con pkexec para la parte que necesita root
# ----------------------------------------------------------------------

def _reejecutar_root(args):
    yo = os.path.abspath(__file__)
    return subprocess.call(["pkexec", "python3", yo] + args)


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main_cli(argv):
    if argv[0] == "--status":
        minutos = leer_config_pantalla()
        pk = powerkey_actual() or POWERKEY_DEFECTO
        print("Apagar pantalla tras: %s" % etiqueta_pantalla(minutos))
        print("Suspensión automática: %s" %
              ("permitida" if sleep_permitido() else "no permitida"))
        print("Botón de encendido: %s" % POWERKEY_ETIQUETAS.get(pk, pk))
        return 0

    if argv[0] == "--apply":
        minutos = leer_config_pantalla()
        aplicar_pantalla(minutos)
        print("pantalla aplicada:", etiqueta_pantalla(minutos))
        return 0

    if argv[0] == "--set-sleep" and len(argv) > 1:
        val = argv[1]
        if val not in ("on", "off"):
            print("uso: --set-sleep on|off")
            return 1
        if os.geteuid() != 0:
            return _reejecutar_root(argv)
        set_sleep(val == "on")
        print("suspensión automática:", "permitida" if val == "on" else "no permitida")
        return 0

    if argv[0] == "--set-powerkey" and len(argv) > 1:
        accion = argv[1]
        if accion not in POWERKEY_OPCIONES:
            print("uso: --set-powerkey poweroff|suspend|ignore")
            return 1
        if os.geteuid() != 0:
            return _reejecutar_root(argv)
        set_powerkey(accion)
        print("botón de encendido:", POWERKEY_ETIQUETAS[accion], "(rige tras reiniciar)")
        return 0

    print(__doc__)
    return 1


# ----------------------------------------------------------------------
# GUI (GTK3, mismo look claro/navy que las demás ventanas del panel)
# ----------------------------------------------------------------------

CSS = """
.fpe-win { background: #ffffff; }
.fpe-title { color: #14233f; font-weight: bold; font-size: 15px; }
.fpe-seccion { color: #14233f; font-weight: bold; font-size: 12px; }
.fpe-text { color: #14233f; }
.fpe-nota { color: #5a6b8c; font-size: 11px; }
.fpe-estado { color: #2d5aa6; font-weight: bold; }
.fpe-aplicar {
    background: #2d5aa6; color: #ffffff; font-weight: bold;
    border-radius: 6px; padding: 6px 18px;
}
.fpe-aplicar:hover { background: #244a8a; }

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
    from gi.repository import Gtk, Gdk

    prov = Gtk.CssProvider()
    prov.load_from_data(CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), prov,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    win = Gtk.Window(title="Opciones de Energía")
    win.set_default_size(460, 420)
    hb = Gtk.HeaderBar()
    hb.set_show_close_button(True)
    hb.set_decoration_layout(":close")
    hb.props.title = "Opciones de Energía"
    hb.get_style_context().add_class("fp-titlebar")
    win.set_titlebar(hb)
    win.set_position(Gtk.WindowPosition.CENTER)
    win.set_resizable(False)
    win.get_style_context().add_class("fpe-win")
    win.connect("destroy", Gtk.main_quit)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=18)
    win.add(box)

    tit = Gtk.Label(label="Opciones de Energía", xalign=0)
    tit.get_style_context().add_class("fpe-title")
    box.pack_start(tit, False, False, 0)

    sub = Gtk.Label(xalign=0, wrap=True,
                     label="Configuración de ahorro de energía para la terminal POS.")
    sub.get_style_context().add_class("fpe-text")
    box.pack_start(sub, False, False, 0)

    # ---------------- a) Apagado de pantalla ----------------
    lbl_a = Gtk.Label(label="Apagar la pantalla tras", xalign=0)
    lbl_a.get_style_context().add_class("fpe-seccion")
    box.pack_start(lbl_a, False, False, 0)

    fila_pantalla = Gtk.Box(spacing=10)
    lbl_p = Gtk.Label(label="Tiempo de inactividad", xalign=0)
    lbl_p.get_style_context().add_class("fpe-text")
    combo_pantalla = Gtk.ComboBoxText()
    for m in PANTALLA_OPCIONES:
        combo_pantalla.append_text(etiqueta_pantalla(m))
    fila_pantalla.pack_start(lbl_p, True, True, 0)
    fila_pantalla.pack_end(combo_pantalla, False, False, 0)
    box.pack_start(fila_pantalla, False, False, 0)

    box.pack_start(Gtk.Separator(), False, False, 4)

    # ---------------- b) Suspensión automática ----------------
    lbl_b = Gtk.Label(label="Suspensión automática del equipo", xalign=0)
    lbl_b.get_style_context().add_class("fpe-seccion")
    box.pack_start(lbl_b, False, False, 0)

    fila_susp = Gtk.Box(spacing=10)
    lbl_s = Gtk.Label(label="Permitir que el equipo se suspenda solo", xalign=0)
    lbl_s.get_style_context().add_class("fpe-text")
    sw_susp = Gtk.Switch()
    fila_susp.pack_start(lbl_s, True, True, 0)
    fila_susp.pack_end(sw_susp, False, False, 0)
    box.pack_start(fila_susp, False, False, 0)

    nota_susp = Gtk.Label(xalign=0, wrap=True,
                           label="Recomendado NO permitir en terminales POS.")
    nota_susp.get_style_context().add_class("fpe-nota")
    box.pack_start(nota_susp, False, False, 0)

    box.pack_start(Gtk.Separator(), False, False, 4)

    # ---------------- c) Botón de encendido ----------------
    lbl_c = Gtk.Label(label="Al presionar el botón de encendido", xalign=0)
    lbl_c.get_style_context().add_class("fpe-seccion")
    box.pack_start(lbl_c, False, False, 0)

    fila_pk = Gtk.Box(spacing=10)
    lbl_k = Gtk.Label(label="Acción", xalign=0)
    lbl_k.get_style_context().add_class("fpe-text")
    combo_pk = Gtk.ComboBoxText()
    for accion in POWERKEY_OPCIONES:
        combo_pk.append_text(POWERKEY_ETIQUETAS[accion])
    fila_pk.pack_start(lbl_k, True, True, 0)
    fila_pk.pack_end(combo_pk, False, False, 0)
    box.pack_start(fila_pk, False, False, 0)

    nota_pk = Gtk.Label(xalign=0, wrap=True,
                         label="Este cambio rige tras reiniciar el equipo.")
    nota_pk.get_style_context().add_class("fpe-nota")
    box.pack_start(nota_pk, False, False, 0)

    # ---------------- estado + aplicar ----------------
    lbl_est = Gtk.Label(xalign=0, wrap=True)
    lbl_est.get_style_context().add_class("fpe-estado")
    box.pack_start(lbl_est, False, False, 0)

    btn = Gtk.Button(label="Aplicar")
    btn.get_style_context().add_class("fpe-aplicar")
    box.pack_end(btn, False, False, 0)

    def refrescar():
        minutos = leer_config_pantalla()
        if minutos in PANTALLA_OPCIONES:
            combo_pantalla.set_active(PANTALLA_OPCIONES.index(minutos))
        else:
            combo_pantalla.set_active(PANTALLA_OPCIONES.index(PANTALLA_DEFECTO))

        sw_susp.set_active(sleep_permitido())

        pk = powerkey_actual() or POWERKEY_DEFECTO
        if pk in POWERKEY_OPCIONES:
            combo_pk.set_active(POWERKEY_OPCIONES.index(pk))
        else:
            combo_pk.set_active(POWERKEY_OPCIONES.index(POWERKEY_DEFECTO))

        lbl_est.set_text(
            "Estado: pantalla %s · suspensión %s · botón %s" % (
                etiqueta_pantalla(minutos),
                "permitida" if sleep_permitido() else "no permitida",
                POWERKEY_ETIQUETAS.get(pk, pk)))

    def aplicar(_b):
        idx = combo_pantalla.get_active()
        minutos = PANTALLA_OPCIONES[idx] if idx >= 0 else PANTALLA_DEFECTO
        permitir_susp = sw_susp.get_active()
        idx_pk = combo_pk.get_active()
        accion_pk = POWERKEY_OPCIONES[idx_pk] if idx_pk >= 0 else POWERKEY_DEFECTO

        # a) pantalla — sin root
        guardar_config_pantalla(minutos)
        aplicar_pantalla(minutos)
        asegurar_autostart()

        errores = []

        # b) suspensión — root solo si cambió
        if sleep_permitido() != permitir_susp:
            rc = _reejecutar_root(["--set-sleep", "on" if permitir_susp else "off"])
            if rc != 0:
                errores.append("suspensión")

        # c) botón de encendido — root solo si cambió
        pk_actual = powerkey_actual() or POWERKEY_DEFECTO
        if pk_actual != accion_pk:
            rc = _reejecutar_root(["--set-powerkey", accion_pk])
            if rc != 0:
                errores.append("botón de encendido")

        refrescar()
        if errores:
            lbl_est.set_text(lbl_est.get_text() +
                              "  ⚠ no se aplicó: " + ", ".join(errores))
        else:
            lbl_est.set_text(lbl_est.get_text() + "  ✓ aplicado")

    btn.connect("clicked", aplicar)
    refrescar()
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main_cli(sys.argv[1:]))
    main_gui()
