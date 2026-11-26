#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FactuPOS Panel — barra de tareas con comportamiento tipo Windows para FactuPOS OS.

Componentes (de izquierda a derecha):
  [Inicio]  ...botones de programas abiertos (Wnck)...  [Red/WiFi] [Reloj/Fecha] [Mostrar escritorio]

Comportamiento "tipo Windows":
  - Botón Inicio -> menú Programas / Utilidades (+ apagar/reiniciar/cerrar sesión).
  - Programas abiertos visibles como botones (clic = enfocar/minimizar,
    clic derecho = Minimizar/Maximizar/Cerrar) vía Wnck.Tasklist.
  - Clic derecho en zona vacía de la barra -> Administrador de tareas /
    Mostrar el escritorio / Configuración.
  - Ctrl+Shift+Esc -> Administrador de tareas (atajo igual que Windows).
  - Tecla Súper (⊞) -> abre Inicio (best-effort; en Cinnamon la tecla la
    suele tener el menú nativo y la grab puede fallar -> se ignora).

Uso:
  factupos-panel [--edge bottom|top] [--height N]

Solo X11 (LMDE 7 / Cinnamon usa X11).
"""
import os
import re
import sys
import json
import shlex
import shutil
import argparse
import datetime
import subprocess
import urllib.request
import getpass
import socket
import threading
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkX11", "3.0")
gi.require_version("Wnck", "3.0")
from gi.repository import Gtk, Gdk, GdkX11, GdkPixbuf, GLib, Gio, Wnck, Pango  # noqa: E402

# Iconos propios de red y sonido (1.6.6, #2698) dibujados con cairo. 🪤 El auto-update baja
# SOLO el .py (no instala dependencias): si a la PC le falta python3-gi-cairo, la barra NO se
# cae — sigue con los iconos del tema de siempre.
try:
    import cairo  # noqa: E402
    gi.require_foreign("cairo")
    HAY_CAIRO = True
except Exception:
    HAY_CAIRO = False

_ICONO_COLORES = {
    "lan":  ("#22c55e", "#15803d"),   # cable conectado: verde
    "wifi": ("#38bdf8", "#0284c7"),   # WiFi conectado: celeste
    "off":  ("#fb7185", "#e11d48"),   # sin red: rosa
    "vol":  ("#a78bfa", "#7c3aed"),   # sonido: violeta
    "mute": ("#64748b", "#334155"),   # silenciado: gris
    "bt":   ("#60a5fa", "#2563eb"),   # Bluetooth encendido: azul (1.7.0, #2942)
    "btoff": ("#64748b", "#334155"),  # Bluetooth apagado: gris
}


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (1, 3, 5))


def icono_estado(clase, nivel=3, tam=26):
    """Icono redondo de la bandeja: circulo con degradado del color del estado + dibujo
    blanco (LAN, ondas WiFi, X, parlante con ondas segun el volumen). None si no hay cairo."""
    if not HAY_CAIRO:
        return None
    try:
        sf = cairo.ImageSurface(cairo.FORMAT_ARGB32, tam, tam)
        cr = cairo.Context(sf)
        c1, c2 = _ICONO_COLORES.get(clase, _ICONO_COLORES["off"])
        r = tam / 2.0
        g = cairo.LinearGradient(0, 0, tam, tam)
        g.add_color_stop_rgb(0, *_rgb(c1))
        g.add_color_stop_rgb(1, *_rgb(c2))
        cr.arc(r, r, r - 1, 0, 6.2832)
        cr.set_source(g)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.55)
        cr.set_line_width(1.2)
        cr.stroke()
        cr.set_source_rgb(1, 1, 1)
        k = tam / 26.0
        cr.set_line_width(1.8 * k)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        if clase == "lan":                       # red cableada: un nodo arriba y dos abajo
            cr.rectangle(10.5 * k, 6 * k, 5 * k, 4.5 * k); cr.fill()
            cr.rectangle(5.5 * k, 15.5 * k, 5 * k, 4.5 * k); cr.fill()
            cr.rectangle(15.5 * k, 15.5 * k, 5 * k, 4.5 * k); cr.fill()
            cr.move_to(13 * k, 10.5 * k); cr.line_to(13 * k, 13 * k)
            cr.move_to(8 * k, 15.5 * k); cr.line_to(8 * k, 13 * k); cr.line_to(18 * k, 13 * k); cr.line_to(18 * k, 15.5 * k)
            cr.stroke()
        elif clase == "wifi":                    # tres arcos + punto
            for rad in (4.0, 7.5, 11.0):
                cr.arc(13 * k, 18.5 * k, rad * k, 3.93, 5.50); cr.stroke()
            cr.arc(13 * k, 18.5 * k, 1.6 * k, 0, 6.2832); cr.fill()
        elif clase in ("bt", "btoff"):           # runa de Bluetooth
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.move_to(8.5 * k, 9 * k); cr.line_to(17 * k, 17 * k); cr.line_to(13 * k, 21 * k)
            cr.line_to(13 * k, 5 * k); cr.line_to(17 * k, 9 * k); cr.line_to(8.5 * k, 17 * k)
            cr.stroke()
        elif clase == "off":                     # X
            cr.set_line_width(2.4 * k)
            cr.move_to(8.5 * k, 8.5 * k); cr.line_to(17.5 * k, 17.5 * k)
            cr.move_to(17.5 * k, 8.5 * k); cr.line_to(8.5 * k, 17.5 * k)
            cr.stroke()
        else:                                    # parlante (vol / mute)
            cr.move_to(6 * k, 10.5 * k); cr.line_to(9.5 * k, 10.5 * k); cr.line_to(13.5 * k, 6.5 * k)
            cr.line_to(13.5 * k, 19.5 * k); cr.line_to(9.5 * k, 15.5 * k); cr.line_to(6 * k, 15.5 * k)
            cr.close_path(); cr.fill()
            if clase == "mute":
                cr.set_source_rgb(*_rgb("#fb7185"))
                cr.set_line_width(2.2 * k)
                cr.move_to(16 * k, 10 * k); cr.line_to(21 * k, 16 * k)
                cr.move_to(21 * k, 10 * k); cr.line_to(16 * k, 16 * k)
                cr.stroke()
            else:
                for i, rad in enumerate((3.5, 6.5, 9.5)):
                    if i < nivel:
                        cr.arc(13.5 * k, 13 * k, rad * k, -0.8, 0.8); cr.stroke()
        # 🪤 Gdk.pixbuf_get_from_surface() devolvía None con pycairo (medido): se pasa por PNG
        #    en memoria, que funciona en cualquier PC.
        import io
        buf = io.BytesIO()
        sf.write_to_png(buf)
        ld = GdkPixbuf.PixbufLoader.new_with_type("png")
        ld.write(buf.getvalue())
        ld.close()
        return ld.get_pixbuf()
    except Exception:
        return None

# Xlib es opcional: si no está, el panel funciona pero no reserva espacio
# (strut) ni captura el atajo global Ctrl+Shift+Esc.
try:
    from Xlib import X, XK, Xatom
    from Xlib.display import Display as XDisplay
    from Xlib.protocol import event as Xevent
    HAVE_XLIB = True
except Exception:
    HAVE_XLIB = False

APP_ID = "com.soportereal.factupos.panel"
VERSION = "1.8.3"                              # fuente única de versión
RECORTE_CIERRE_MS = 2500     # #3398: el menú se cierra cuando Recortes ya congeló la pantalla
ASSETS = "/usr/share/factupos-os"               # íconos de marca del FactuPOS OS
START_ICON = os.path.join(ASSETS, "start-icon.png")
CONFIG_MENU = "/etc/factupos-panel/menu.json"   # menú Inicio personalizable
STATE_FILE = os.path.expanduser(                 # estado por USUARIO (sin root):
    "~/.config/factupos-panel/estado.json")      # hoy solo "locked" (barra bloqueada)
OS_VERSION_FILE = "/etc/factupos-os-version"     # versión de la distro (1 línea, ej: 5.1)
OS_VERSION_DEFAULT = ""                          # respaldo si no hay archivo ni os-release

# Auto-actualización: archivo de versiones publicado en la misma carpeta de
# descargas. El panel lo lee, y si hay versión nueva baja el .py a una carpeta
# del usuario (sin root) y se reinicia solo.
UPDATE_BASE = "https://soportereal.com/software/factupos-app/linux"
UPDATE_MANIFEST = UPDATE_BASE + "/Factupos-Panel_version.json"
UPDATE_PY_LOCAL = os.path.expanduser("~/.local/share/factupos-panel/factupos-panel.py")
SOPORTE_ICONO = "factupos-soporte"     # diadema amarilla de Soporte Remoto (#2942), viene en el .deb
REBOOT_FLAG = "/run/reboot-required"                           # parches que piden reinicio (#2942)
APPS_BASE = "/etc/factupos-actualizador/apps-base.txt"          # apps obligatorias
APPS_QUITADAS = "/var/lib/factupos-apps/quitadas.txt"           # quitadas a propósito en la Tienda (#3037)
APPS_REPO_INDEX = "https://soportereal.com/apt/Packages"   # 1.7.0: repo de TODAS las apps
UPDATE_INTERVAL = 3600                           # re-chequeo cada hora (#2698: igual que las demás apps)

DEFAULT_HEIGHT = 44
HOVER_POLL_MS = 120                              # cada cuánto se mira el puntero
                                                 # para abrir submenús al pasar el mouse
START_CLOSE_DELAY = 0                            # seg que el menú Inicio sigue visible
                                                 # tras un clic afuera antes de esconderse.
                                                 # 0 = al instante, como el calendario, el
                                                 # volumen y la red de esta misma barra


def _vtuple(v):
    """'1.2.10' -> (1,2,10) para comparar versiones."""
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except Exception:
        return (0,)

# Administradores de tareas a probar, en orden (el primero que exista).
# El propio de FactuPOS va primero.
TASK_MANAGERS = [
    "factupos-tareas",
    "gnome-system-monitor", "mate-system-monitor", "xfce4-taskmanager",
    "plasma-systemmonitor", "ksysguard", "lxtask",
]


def icono_tema(*nombres):
    """Primer ícono que EXISTA en el tema (los nombres varían por tema/distro).
    Evita items sin ícono cuando el nombre no está (ej. internet-chat en XFCE)."""
    try:
        t = Gtk.IconTheme.get_default()
        for n in nombres:
            if t.has_icon(n):
                return n
    except Exception:
        pass
    return nombres[-1]


def brand_icon():
    """Logo FactuPOS (hexágono): el del propio .deb del panel, o el de la
    distro; si no hay ninguno, cae al ícono de tema."""
    for p in ("/usr/lib/factupos-panel/factupos.png",
              "/usr/share/factupos-os/factupos.png"):
        if os.path.exists(p):
            return p
    return "start-here"

# Menú Inicio por defecto (si no hay /etc/factupos-panel/menu.json).
# Cada item: (etiqueta, comando, icono). Solo se muestran los comandos cuyo
# binario exista (los lanzadores .desktop / urls se muestran siempre).
DEFAULT_MENU = {
    "Programas": [
        ["FactuPOS", "xdg-open https://factupos.com", "applications-internet"],
        ["Google Chrome", "google-chrome-stable", "google-chrome"],
        ["Firefox", "firefox", "firefox"],
        ["LibreOffice Calc", "libreoffice --calc", "libreoffice-calc"],
        ["LibreOffice Writer", "libreoffice --writer", "libreoffice-writer"],
        ["Archivos", "nemo", "system-file-manager"],
    ],
    "Utilidades": [
        ["Impresoras", "system-config-printer", "printer"],
        ["Gestión de Impresoras", "factupos-printer-inst", "printer"],   # #2831 (antes «Instalador de Impresoras»)
        ["Configurar red / WiFi", "nm-connection-editor", "network-wireless"],
        ["Soporte Remoto", "rustdesk", "factupos-soporte"],
        ["Panel de Control", "cinnamon-settings", "preferences-system"],
        ["Administrador de tareas", "@taskmgr", "utilities-system-monitor"],
        ["Terminal", "x-terminal-emulator", "utilities-terminal"],
    ],
}

CSS = b"""
/* Paleta navy moderna FactuPOS - rediseno 1.6.0 (#2698, mismo lenguaje que el kiosko
   1.8.12): fondo con degradado + linea violeta arriba, todo redondeado, acentos vivos
   (violeta #7c3aed, azul #2563eb, cian #38bdf8). Solo la BARRA: las ventanitas (red,
   sonido, calendario, menu Inicio) se redisenan en sus propias versiones. */
.fp-panel {
    background-image: linear-gradient(to right, #0b1533, #14224d 55%, #1e1b4b);
    border-top: 2px solid #7c3aed;
}
.fp-start {
    background-image: linear-gradient(135deg, #7c3aed, #2563eb);
    color: #ffffff; font-weight: bold; padding: 0 16px; margin: 5px 6px 5px 6px;
    border: 1px solid rgba(255,255,255,0.35); border-radius: 12px;
}
.fp-start:hover { background-image: linear-gradient(135deg, #8b5cf6, #3b82f6);
                  border-color: rgba(255,255,255,0.6); }
.fp-start label { color: #ffffff; }
.fp-clock { color: #e2e8f0; padding: 0 12px; margin: 5px 2px; border-radius: 10px;
            border: 1px solid transparent; background-image: none; background-color: transparent; }
.fp-clock:hover { background-color: rgba(255,255,255,0.10); border-color: rgba(255,255,255,0.18); }
.fp-clock label { color: #e2e8f0; }
.fp-net { color: #e2e8f0; padding: 0 9px; margin: 5px 1px; border-radius: 10px;
          border: 1px solid transparent; background-image: none; background-color: transparent; }
.fp-net:hover { background-color: rgba(255,255,255,0.10); border-color: rgba(255,255,255,0.18); }
.fp-showdesk { background-image: none; background-color: transparent; border: none;
               border-left: 1px solid rgba(255,255,255,0.15); min-width: 8px; }
.fp-showdesk:hover { background-color: rgba(56,189,248,0.30); }

/* Accesos rapidos anclados (entre Inicio y las ventanas abiertas) */
.fp-pin { color: #e2e8f0; padding: 0 7px; margin: 6px 1px; border-radius: 10px;
          border: 1px solid transparent; background-image: none;
          background-color: transparent; min-width: 0; }
.fp-pin:hover { background-color: rgba(124,58,237,0.35); border-color: rgba(167,139,250,0.6); }
.fp-pin:disabled { opacity: 0.45; }
.fp-pinsep { background-color: rgba(255,255,255,0.15); min-width: 1px; min-height: 1px; margin: 10px 5px; }

/* Barra de tareas: ventanas abiertas como PASTILLAS; la activa con borde y rayita cian */
.fp-task { color: #dbe4f3; padding: 0 12px; margin: 5px 2px; border-radius: 10px;
           background-image: none; background-color: rgba(255,255,255,0.05);
           border: 1px solid rgba(255,255,255,0.08); }
.fp-task:hover { background-color: rgba(255,255,255,0.12); border-color: rgba(255,255,255,0.22); }
.fp-task label { color: #dbe4f3; }
.fp-task-active { background-color: rgba(56,189,248,0.18); border-color: #38bdf8;
                  box-shadow: inset 0 -3px 0 0 #38bdf8; }
.fp-task-active label { color: #ffffff; font-weight: bold; }

/* Ventanitas con el diseno navy 1.6.x (#2698): se encienden de a una agregando la clase
   fp-navy a la ventana (1.6.1 red, 1.6.2 sonido, 1.6.3 calendario, 1.6.4 menu Inicio).
   Va ANTES que .fp-startmenu en el texto: por eso cada regla lleva .fp-startmenu.fp-navy
   (dos clases), que gana sobre el esquema claro (una clase) sin importar el orden. */
.fp-startmenu.fp-navy { background-color: #0f1a3a; border: 1px solid #4c3fa8; }
.fp-startmenu.fp-navy label { color: #e2e8f0; }
.fp-startmenu.fp-navy .fp-menu-right { background-image: linear-gradient(135deg, #1e1b4b, #1e3a8a);
                          background-color: transparent; border-bottom: 2px solid #7c3aed; }
.fp-startmenu.fp-navy .fp-menu-right label { color: #ffffff; }
.fp-startmenu.fp-navy .fp-menu-header { color: #a5b4fc; }
.fp-startmenu.fp-navy separator { background-color: rgba(255,255,255,0.12); }
.fp-startmenu.fp-navy button { background-image: none; background-color: rgba(255,255,255,0.06);
                  color: #e2e8f0; border: 1px solid rgba(255,255,255,0.18); border-radius: 10px;
                  box-shadow: none; text-shadow: none; padding: 6px 12px; }
.fp-startmenu.fp-navy button:hover { background-color: rgba(255,255,255,0.14); border-color: rgba(255,255,255,0.35); }
.fp-startmenu.fp-navy button label { color: #e2e8f0; }
.fp-startmenu.fp-navy button.fp-item { background-color: transparent; border: 1px solid transparent;
                          border-radius: 8px; padding: 6px 10px; margin: 1px 0; }
.fp-startmenu.fp-navy button.fp-item:hover { background-color: rgba(124,58,237,0.30); border-color: rgba(167,139,250,0.5); }
.fp-startmenu.fp-navy button.fp-pri { background-image: linear-gradient(135deg, #7c3aed, #2563eb);
                         border-color: rgba(255,255,255,0.35); }
.fp-startmenu.fp-navy button.fp-pri:hover { background-image: linear-gradient(135deg, #8b5cf6, #3b82f6); }
.fp-startmenu.fp-navy button.fp-pri label { color: #ffffff; font-weight: bold; }
.fp-startmenu.fp-navy button.fp-cerrar { background-color: transparent; border: 1px solid transparent;
                            border-radius: 8px; padding: 2px 8px; }
.fp-startmenu.fp-navy button.fp-cerrar:hover { background-color: #e11d48; }
.fp-startmenu.fp-navy entry { background-image: none; background-color: #14224d; color: #ffffff;
                 border: 1px solid #4f63a8; border-radius: 8px; padding: 4px 8px; }
.fp-startmenu.fp-navy entry:focus { border-color: #38bdf8; }
.fp-startmenu.fp-navy .fp-card { background-color: rgba(56,189,248,0.10); border: 1px solid rgba(56,189,248,0.45);
                    border-radius: 12px; padding: 8px 12px; }
.fp-startmenu.fp-navy switch { background-image: none; background-color: #334155; border-radius: 14px;
                  border: 1px solid rgba(255,255,255,0.25); }
.fp-startmenu.fp-navy switch:checked { background-color: #16a34a; }
.fp-startmenu.fp-navy switch slider { background-image: none; background-color: #ffffff; border-radius: 12px; }
.fp-startmenu.fp-navy scrollbar slider { background-color: rgba(255,255,255,0.30); }

.fp-startmenu.fp-navy viewport, .fp-startmenu.fp-navy scrolledwindow { background-color: transparent; }
.fp-startmenu.fp-navy image { color: #e2e8f0; -gtk-icon-style: symbolic; }
.fp-startmenu.fp-navy radiobutton label { color: #e2e8f0; }
.fp-startmenu.fp-navy radiobutton radio { background-image: none; background-color: #14224d;
                                          border: 1px solid #7184ad; }
.fp-startmenu.fp-navy radiobutton radio:checked { background-color: #7c3aed; border-color: #a78bfa; color: #ffffff; }
.fp-startmenu.fp-navy radiobutton:disabled label { color: #64748b; }
/* 1.6.2 sonido: barras de volumen y selector de tarjeta */
.fp-startmenu.fp-navy scale trough { background-image: none; background-color: #1e293b;
                                     border: none; border-radius: 6px; min-width: 8px; min-height: 8px; }
.fp-startmenu.fp-navy scale highlight { background-image: linear-gradient(to top, #38bdf8, #7c3aed);
                                        border: none; border-radius: 6px; }
.fp-startmenu.fp-navy scale slider { background-image: none; background-color: #ffffff;
                                     border: 2px solid #38bdf8; border-radius: 12px;
                                     min-width: 18px; min-height: 18px; }
.fp-startmenu.fp-navy scale value { color: #e2e8f0; }
.fp-startmenu.fp-navy combobox button { background-image: none; background-color: #14224d;
                                        border: 1px solid #4f63a8; border-radius: 8px; }
.fp-startmenu.fp-navy combobox button label, .fp-startmenu.fp-navy combobox arrow { color: #ffffff; }
/* 1.6.3 reloj y calendario */
.fp-startmenu.fp-navy calendar { background-image: none; background-color: #14224d; color: #e2e8f0;
                                 border: 1px solid #4f63a8; border-radius: 10px; padding: 4px; }
.fp-startmenu.fp-navy calendar:selected { background-color: #7c3aed; color: #ffffff; border-radius: 8px; }
.fp-startmenu.fp-navy calendar.header, .fp-startmenu.fp-navy calendar.button {
    background-image: none; background-color: transparent; color: #ffffff; border: none; }
.fp-startmenu.fp-navy calendar:indeterminate { color: #475569; }
.fp-startmenu.fp-navy calendar.highlight { color: #a5b4fc; }
/* 1.6.8 menu Inicio CLARO (pedido del duenio #2698: "que no se vea tanta sombra, tema blanco,
   grises y azules"): fondo blanco, separadores grises, acentos azules, opciones planas. */
.fp-startmenu.fp-claro { background-color: #ffffff; border: 1px solid #cbd5e1; }
.fp-startmenu.fp-claro label { color: #1f2937; }
.fp-startmenu.fp-claro .fp-banner { background-image: linear-gradient(to top, #1e3a8a, #2563eb);
                                    border-right: none; }
.fp-startmenu.fp-claro .fp-banner label { color: #ffffff; }
.fp-startmenu.fp-claro separator { background-color: #e5e7eb; }
.fp-startmenu.fp-claro button.fp-mitem { background-image: none; background-color: transparent;
    border: 1px solid transparent; border-radius: 8px; padding: 5px 12px; margin: 1px 4px; box-shadow: none; }
.fp-startmenu.fp-claro button.fp-mitem:hover { background-color: #e8f0fe; border-color: #bfd3f5; }
.fp-startmenu.fp-claro button.fp-mitem:hover label { color: #1e40af; }
.fp-startmenu.fp-claro .fp-mitem label { color: #1f2937; }
.fp-startmenu.fp-claro image { color: #2563eb; -gtk-icon-style: symbolic; }
.fp-startmenu.fp-claro entry { background-image: none; background-color: #f3f4f6; color: #111827;
                               border: 1px solid #d1d5db; border-radius: 10px; padding: 4px 8px; }
.fp-startmenu.fp-claro entry:focus { border-color: #2563eb; background-color: #ffffff; }
.fp-startmenu.fp-claro .fp-menu-header { color: #2563eb; }
.fp-startmenu.fp-claro .fp-menu-foot, .fp-startmenu.fp-claro .fp-menu-right { background-color: #f8fafc; }
.fp-startmenu.fp-navy .fp-reloj { background-image: linear-gradient(135deg, #1e1b4b, #1e3a8a);
                                  border-bottom: 2px solid #7c3aed; border-radius: 10px; padding: 8px; }
.fp-startmenu.fp-navy button:disabled label { color: #64748b; }

/* Popups (menu, red, calendario, volumen, equipo): esquema claro de alto contraste */
.fp-startmenu { background-color: #eef2f8; border: 1px solid #2d5aa6; }
.fp-startmenu label { color: #14233f; }
.fp-startmenu separator { background-color: #c9d6ea; min-width: 1px; min-height: 1px; }
.fp-startmenu button { background-image: none; background-color: #e8eff9; color: #14233f;
                       border: 1px solid #b9cae6; box-shadow: none; text-shadow: none; }
.fp-startmenu button:hover { background-color: #d2e1f7; }
.fp-startmenu button:disabled { color: #8a97ad; }
.fp-startmenu entry { background-image: none; background-color: #ffffff; color: #14233f; border: 1px solid #b9cae6; }
.fp-startmenu combobox, .fp-startmenu combobox button { background-color: #ffffff; color: #14233f; }
.fp-startmenu calendar { background-color: #ffffff; color: #14233f; border: 1px solid #c9d6ea; }
.fp-startmenu calendar:selected { background-color: #2d5aa6; color: #ffffff; }
.fp-startmenu calendar.header, .fp-startmenu calendar.button { background-color: #eef3fb; color: #14233f; }
.fp-startmenu scale trough { background-color: #cdddf2; }
.fp-startmenu scale highlight, .fp-startmenu scale progress { background-color: #2d5aa6; }
.fp-startmenu scale slider { background-color: #ffffff; border: 1px solid #2d5aa6; }
.fp-banner { background: linear-gradient(to top, #0a1730, #1f3f78); border-right: 1px solid #2d5aa6; }
.fp-banner label { color: #ffffff; }
/* items del menu principal: planos, compactos, sin radius ni sombra */
.fp-startmenu button.fp-mitem { background-color: transparent; border: none;
    padding: 4px 12px; margin: 0; border-radius: 0; box-shadow: none; }
.fp-startmenu button.fp-mitem:hover { background-color: #d6e4fb; }
.fp-mitem label { font-size: 1em; color: #14233f; }
.fp-startmenu button.fp-item { background-color: transparent; border: none; padding: 3px 10px; margin: 0; border-radius: 0; }
.fp-startmenu button.fp-item:hover { background-color: #d6e4fb; }
.fp-menu-header { color: #1f4f9c; font-weight: bold; padding: 4px 10px 1px 10px; }
.fp-menu-right, .fp-menu-foot { background-color: #eef3fb; }
/* submenus (flyouts) y menus de clic derecho: CLAROS y planos desde 1.6.8 (#2698) */
.fp-flyout, .fp-flyout-plano { background-color: #ffffff; border: 1px solid #cbd5e1; }
.fp-flyout menuitem, .fp-flyout-plano menuitem { background-image: none; background-color: transparent;
    border: 1px solid transparent; border-radius: 6px; margin: 1px 3px; padding: 5px 12px;
    color: #1f2937; box-shadow: none; }
.fp-flyout menuitem:hover, .fp-flyout-plano menuitem:hover { background-color: #e8f0fe; border-color: #bfd3f5; }
.fp-flyout menuitem:hover label, .fp-flyout-plano menuitem:hover label { color: #1e40af; }
.fp-flyout menuitem:disabled label, .fp-flyout-plano menuitem:disabled label { color: #9ca3af; }
.fp-flyout label, .fp-flyout-plano label { color: #1f2937; }
.fp-flyout arrow, .fp-flyout-plano arrow { color: #6b7280; }
.fp-flyout separator, .fp-flyout-plano separator { background-color: #e5e7eb; }
.fp-flyout image, .fp-flyout-plano image { color: #2563eb; }
"""

# Categorías freedesktop -> nombre en español, en orden de aparición.
CATEGORIES = [
    ("Office", "Oficina"),
    ("Network", "Internet"),
    ("Graphics", "Gráficos"),
    ("AudioVideo", "Sonido y Video"),
    ("Development", "Programación"),
    ("Game", "Juegos"),
    ("Education", "Educación"),
    ("Science", "Ciencia"),
    ("System", "Herramientas del sistema"),
    ("Settings", "Configuración"),
    ("Utility", "Accesorios"),
]

# División curada Utilidades vs Herramientas (por nombre de ejecutable).
# Herramientas = apps del sistema / administración.
FORCE_TOOLS = {
    "gnome-terminal", "x-terminal-emulator", "xterm", "mate-terminal", "xfce4-terminal",
    "qterminal", "konsole", "tilix",
    "gnome-system-monitor", "mate-system-monitor", "xfce4-taskmanager", "ksysguard",
    "plasma-systemmonitor", "htop", "btop",
    "gparted", "gnome-disks", "gnome-disk-utility", "baobab", "gnome-logs",
    "synaptic", "mintupdate", "mintinstall", "mintdrivers", "mintsources",
    "software-properties-gtk", "timeshift", "timeshift-gtk", "hardinfo", "cpu-x",
    "system-config-printer", "gnome-system-log", "users-admin",
}
# Utilidades = accesorios de usuario.
FORCE_UTILS = {
    "gnome-calculator", "galculator", "kcalc", "mate-calc",
    "xed", "gedit", "gnome-text-editor", "org.gnome.TextEditor", "mousepad", "kate", "pluma",
    "file-roller", "xarchiver", "ark", "engrampa",
    "gnome-screenshot", "flameshot", "mate-screenshot", "ksnip",
    "gnome-characters", "gucharmap", "kcharselect",
    "xreader", "evince", "atril", "okular", "sticky", "gnote", "xpad",
    "gnome-font-viewer", "gnome-clocks", "deja-dup",
}

# Icono por título de sección/categoría del menú Inicio.
SECTION_ICONS = {
    "Programas": "applications-other",
    "Utilidades": "applications-utilities",
    "Oficina": "applications-office",
    "Internet": "applications-internet",
    "Gráficos": "applications-graphics",
    "Sonido y Video": "applications-multimedia",
    "Programación": "applications-development",
    "Juegos": "applications-games",
    "Educación": "applications-science",
    "Ciencia": "applications-science",
    "Herramientas del sistema": "applications-system",
    "Configuración": "preferences-system",
    "Accesorios": "applications-accessories",
    "Otros": "applications-other",
}


def icono_soporte(tam=None):
    """Ícono de diadema de Soporte Remoto FactuPOS (#2942). Sin tam: el NOMBRE de tema para
    menús (o el de antes si la PC todavía no recibió el .deb con el ícono). Con tam: pixbuf."""
    base = "/usr/share/icons/hicolor/%dx%d/apps/" + SOPORTE_ICONO + ".png"
    if tam is None:
        return SOPORTE_ICONO if os.path.exists(base % (48, 48)) else "preferences-desktop-remote-desktop"
    for t in (16, 22, 24, 32, 48, 64, 128, 256):
        if t >= tam and os.path.exists(base % (t, t)):
            try:
                return GdkPixbuf.Pixbuf.new_from_file_at_size(base % (t, t), tam, tam)
            except Exception:
                return None
    return None


def es_soporte(*textos):
    """True si la ventana / ícono de bandeja es el de RustDesk (Soporte Remoto FactuPOS)."""
    return any(t and "rustdesk" in str(t).lower() for t in textos)


def _deb_lt(a, b):
    """True si la versión Debian a < b (dpkg sabe comparar 1.10 vs 1.9, epochs, etc.)."""
    if not a or not b:
        return False
    try:
        return subprocess.run(["dpkg", "--compare-versions", a, "lt", b],
                              timeout=5).returncode == 0
    except Exception:
        return False


def _nombre_app(pkg):
    """factupos-printer-inst -> Impresoras, factupos-tareas -> Tareas (para los avisos)."""
    lindos = {"factupos-ia": "IA", "factupos-dataequipo": "Datos del Equipo",
              "factupos-printer-inst": "Impresoras", "factupos-apps": "Tienda",
              "factupos-navegadores": "Navegadores y WhatsApp", "rustdesk": "Soporte Remoto"}
    if pkg in lindos:
        return lindos[pkg]
    n = pkg[len("factupos-"):] if pkg.startswith("factupos-") else pkg
    return "-".join(x.capitalize() for x in n.split("-"))


def detached_run(cmd):
    """Lanza un comando desligado del panel (no muere si cerramos el panel)."""
    if not cmd:
        return
    if cmd.startswith("@taskmgr"):
        tm = task_manager_cmd()
        if not tm:
            _error_dialog("No se encontró un Administrador de tareas.\n"
                          "Instalá 'gnome-system-monitor'.")
            return
        cmd = tm
    try:
        if "||" in cmd or "&&" in cmd:
            # cadena con respaldos (ej. apagar: comando del escritorio y si
            # falla, systemctl) -> necesita shell
            subprocess.Popen(["sh", "-c", cmd], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(shlex.split(cmd), start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        _error_dialog("No se pudo abrir:\n%s\n\n%s" % (cmd, e))


def task_manager_cmd():
    for t in TASK_MANAGERS:
        if shutil.which(t):
            return t
    return None


def cmd_available(cmd):
    """True si el binario del comando existe (o si es una url/xdg-open)."""
    if not cmd or cmd.startswith("@"):
        return True
    parts = shlex.split(cmd)
    if not parts:
        return False
    if parts[0] in ("xdg-open", "x-terminal-emulator"):
        return True
    return shutil.which(parts[0]) is not None


def _error_dialog(msg):
    d = Gtk.MessageDialog(transient_for=None, modal=True,
                          message_type=Gtk.MessageType.ERROR,
                          buttons=Gtk.ButtonsType.OK, text="FactuPOS Panel")
    d.format_secondary_text(msg)
    d.run()
    d.destroy()


def load_menu():
    if os.path.exists(CONFIG_MENU):
        try:
            with open(CONFIG_MENU, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_MENU


def load_state():
    """Estado del panel guardado por usuario (no requiere root)."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_state(**cambios):
    """Guarda solo las claves indicadas, respetando el resto del archivo."""
    d = load_state()
    d.update(cambios)
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except Exception as e:
        sys.stderr.write("estado: %s\n" % e)


# ── #3654: la barra se asegura SOLA de quedar en el inicio de sesión ──────────
# El .deb la pone en /etc/xdg/autostart (vale para todos), pero cada usuario la
# puede apagar sin root desde «Aplicaciones al inicio» (Cinnamon/XFCE/MATE): eso
# deja una copia en ~/.config/autostart con Hidden=true o
# X-GNOME-Autostart-enabled=false, y la barra no vuelve a salir al encender.
# Un POS no puede quedar sin barra: al abrir (y si alguien la vuelve a apagar
# mientras corre) se quita esa copia o se reescribe encendida.
AUTOARRANQUE_SISTEMA = "/etc/xdg/autostart/factupos-panel.desktop"
AUTOARRANQUE_USUARIO = os.path.expanduser("~/.config/autostart/factupos-panel.desktop")
AUTOARRANQUE_KEEPALIVE = "/usr/lib/factupos-panel/keepalive.sh"


def _leer_desktop(ruta):
    """Claves de la sección [Desktop Entry] de un .desktop ({} si no se puede leer)."""
    claves, seccion = {}, None
    try:
        with open(ruta, encoding="utf-8", errors="replace") as fh:
            for linea in fh:
                linea = linea.strip()
                if not linea or linea.startswith("#"):
                    continue
                if linea.startswith("[") and linea.endswith("]"):
                    seccion = linea[1:-1]
                    continue
                if seccion == "Desktop Entry" and "=" in linea:
                    k, v = linea.split("=", 1)
                    claves[k.strip()] = v.strip()
    except Exception:
        return {}
    return claves


def _escritorios_actuales():
    return [d.strip().lower() for d in
            (os.environ.get("XDG_CURRENT_DESKTOP", "") or "").split(":") if d.strip()]


AUTOARRANQUE_ESCRITORIOS = "XFCE;Cinnamon;X-Cinnamon;MATE;LXDE;LXQt;"   # = el .desktop del .deb


def autoarranque_escritorio_permitido(claves):
    """¿Este escritorio es uno donde la barra DEBE arrancar? El OnlyShowIn del
    .deb deja afuera a GNOME a propósito (la barra tumba GNOME Shell en Zorin):
    eso NO se repara nunca."""
    actuales = _escritorios_actuales()
    if not actuales:
        return True
    lista = lambda k, defecto="": [d.strip().lower() for d in
                                   claves.get(k, defecto).split(";") if d.strip()]
    if any(d in lista("NotShowIn") for d in actuales):
        return False
    solo = lista("OnlyShowIn", AUTOARRANQUE_ESCRITORIOS if not claves else "")
    return not solo or any(d in solo for d in actuales)


def autoarranque_motivo_apagado(claves):
    """Por qué ESTE .desktop no arrancaría la barra al iniciar sesión (None = arranca)."""
    if not claves:
        return "archivo ilegible o vacío"
    if claves.get("Hidden", "").lower() == "true":
        return "Hidden=true"
    for k, v in claves.items():
        if k.startswith("X-") and k.endswith("-Autostart-enabled") and v.lower() == "false":
            return "%s=false" % k
    exe = claves.get("Exec", "")
    if "factupos-panel" not in exe and "keepalive" not in exe:
        return "Exec no es la barra (%s)" % (exe or "vacío")
    if not autoarranque_escritorio_permitido(claves):
        return "excluye este escritorio"
    return None


def _autoarranque_contenido():
    exe = (AUTOARRANQUE_KEEPALIVE if os.path.exists(AUTOARRANQUE_KEEPALIVE)
           else "factupos-panel --monitor all")
    return ("[Desktop Entry]\nType=Application\nName=FactuPOS Panel\n"
            "Comment=Barra de tareas de FactuPOS OS\nIcon=start-here\n"
            "Exec=%s\nTerminal=false\nOnlyShowIn=%s\nStartupNotify=false\n"
            "X-GNOME-Autostart-enabled=true\n"
            "# FactuPOS (#3654): la barra se vuelve a poner sola en el inicio de sesión\n"
            % (exe, AUTOARRANQUE_ESCRITORIOS))


def asegurar_autoarranque():
    """Deja la barra en el inicio de sesión de ESTE usuario. Devuelve qué hizo
    (None si ya estaba bien). Sin root: solo toca ~/.config/autostart."""
    try:
        sis = _leer_desktop(AUTOARRANQUE_SISTEMA) if os.path.exists(AUTOARRANQUE_SISTEMA) else {}
        if not autoarranque_escritorio_permitido(sis):
            return None      # escritorio excluido a propósito (GNOME): no se toca
        sistema_ok = (os.path.exists(AUTOARRANQUE_SISTEMA)
                      and autoarranque_motivo_apagado(_leer_desktop(AUTOARRANQUE_SISTEMA)) is None)
        if os.path.exists(AUTOARRANQUE_USUARIO):
            motivo = autoarranque_motivo_apagado(_leer_desktop(AUTOARRANQUE_USUARIO))
            if motivo is None:
                return None
            if sistema_ok:
                # La copia del usuario es la que la apaga: sin ella manda la del sistema.
                os.remove(AUTOARRANQUE_USUARIO)
                hecho = "quitada la copia del usuario que la apagaba (%s)" % motivo
            else:
                with open(AUTOARRANQUE_USUARIO, "w", encoding="utf-8") as fh:
                    fh.write(_autoarranque_contenido())
                hecho = "reescrita la copia del usuario (%s)" % motivo
        elif sistema_ok:
            return None
        else:
            # Falta (o no sirve) la del sistema y el usuario no tiene la suya.
            os.makedirs(os.path.dirname(AUTOARRANQUE_USUARIO), exist_ok=True)
            with open(AUTOARRANQUE_USUARIO, "w", encoding="utf-8") as fh:
                fh.write(_autoarranque_contenido())
            hecho = "creada la copia del usuario (la del sistema falta o está apagada)"
        sys.stderr.write("autoarranque: %s\n" % hecho)
        return hecho
    except Exception as e:
        sys.stderr.write("autoarranque: no se pudo asegurar: %s\n" % e)
        return None


_AUTOARRANQUE_MONITOR = None
_AUTOARRANQUE_PENDIENTE = None


def vigilar_autoarranque():
    """Asegura el autoarranque ya y lo vuelve a asegurar si alguien toca
    ~/.config/autostart mientras la barra está abierta."""
    global _AUTOARRANQUE_MONITOR
    asegurar_autoarranque()
    try:
        carpeta = os.path.dirname(AUTOARRANQUE_USUARIO)
        os.makedirs(carpeta, exist_ok=True)
        mon = Gio.File.new_for_path(carpeta).monitor_directory(Gio.FileMonitorFlags.NONE, None)

        def _cambio(_m, f, _o, _ev):
            global _AUTOARRANQUE_PENDIENTE
            if f is None or f.get_basename() != os.path.basename(AUTOARRANQUE_USUARIO):
                return
            if _AUTOARRANQUE_PENDIENTE:          # debounce: el editor escribe en ráfaga
                GLib.source_remove(_AUTOARRANQUE_PENDIENTE)

            def _ahora():
                global _AUTOARRANQUE_PENDIENTE
                _AUTOARRANQUE_PENDIENTE = None
                asegurar_autoarranque()
                return False
            _AUTOARRANQUE_PENDIENTE = GLib.timeout_add(1000, _ahora)
        mon.connect("changed", _cambio)
        _AUTOARRANQUE_MONITOR = mon             # que no lo recoja el recolector
    except Exception as e:
        sys.stderr.write("autoarranque: no se pudo vigilar: %s\n" % e)
    return False


def load_pins():
    """Accesos rápidos anclados a la barra, en el orden en que se muestran.

    Cada uno es un dict: {"label": str, "desktop": "x.desktop" | "cmd": "...",
    "icon": nombre-de-icono-o-ruta}. Se guardan por USUARIO en STATE_FILE, así
    que no hace falta root y cada quien arma su barra."""
    pins = load_state().get("anclados", [])
    if not isinstance(pins, list):
        return []
    limpios = []
    for p in pins:
        if not isinstance(p, dict):
            continue
        if not (p.get("desktop") or p.get("cmd")):
            continue
        limpios.append(p)
    return limpios


def save_pins(pins):
    save_state(anclados=pins)


def pin_key(p):
    """Identidad de un acceso (para no anclar dos veces lo mismo)."""
    return (p.get("desktop") or "").strip().lower() or (p.get("cmd") or "").strip()


def refrescar_anclados():
    """Con --monitor all hay una barra por pantalla: todas muestran lo mismo."""
    for p in PANELES:
        try:
            p._rebuild_pins()
        except Exception as e:
            sys.stderr.write("anclados: %s\n" % e)


def pin_desde_appinfo(ai):
    """Convierte una app instalada (.desktop) en un acceso anclable."""
    try:
        did = ai.get_id() or ""
    except Exception:
        did = ""
    label = ai.get_display_name() or ai.get_name() or did or "Programa"
    p = {"label": label}
    if did:
        p["desktop"] = did
    ex = ai.get_executable() or ""
    if ex:
        p["cmd"] = ex.split()[0] if not did else ex.split()[0]
    return p


LANZADORES_DIR = os.path.expanduser("~/.local/share/factupos-panel/lanzadores")


def _slug(t):
    t = re.sub(r"[^a-z0-9]+", "-", (t or "").lower()).strip("-")
    return t or "programa"


def lanzador_de(p):
    """#3398: el archivo .desktop de un acceso del menú, para arrastrarlo al
    escritorio o copiarlo ahí. Si la app tiene .desktop instalado se usa ESE
    (el escritorio lo copia y queda como lanzador de verdad); si es un comando
    suelto del menú, se arma uno propio en LANZADORES_DIR. None si no se puede."""
    did = (p.get("desktop") or "").strip()
    if did:
        try:
            ai = Gio.DesktopAppInfo.new(did)
            fn = ai.get_filename() if ai is not None else None
            if fn and os.path.isfile(fn):
                return fn
        except Exception:
            pass
    cmd = (p.get("cmd") or "").strip()
    if not cmd or cmd.startswith("@"):
        return None
    label = (p.get("label") or cmd).replace("\n", " ").strip()
    try:
        os.makedirs(LANZADORES_DIR, exist_ok=True)
        ruta = os.path.join(LANZADORES_DIR, "factupos-acceso-%s.desktop" % _slug(label))
        lineas = ["[Desktop Entry]", "Type=Application", "Name=%s" % label,
                  "Exec=%s" % cmd, "Icon=%s" % (p.get("icon") or "application-x-executable"),
                  "Terminal=false", ""]
        with open(ruta, "w") as fh:
            fh.write("\n".join(lineas))
        os.chmod(ruta, 0o755)
        return ruta
    except Exception as e:
        sys.stderr.write("lanzador: %s\n" % e)
        return None


def escritorio_dir():
    """La carpeta del escritorio del usuario (Escritorio / Desktop)."""
    home = os.path.expanduser("~")
    d = None
    try:
        d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DESKTOP)
    except Exception:
        d = None
    if not d or os.path.realpath(d) == os.path.realpath(home):
        for n in ("Escritorio", "Desktop"):
            if os.path.isdir(os.path.join(home, n)):
                return os.path.join(home, n)
        d = os.path.join(home, "Escritorio")
    return d


def confiar_lanzador(ruta):
    """El escritorio (nemo) solo abre un .desktop si es ejecutable y confiable;
    si no, muestra un aviso de «lanzador no confiable» al darle doble clic."""
    try:
        os.chmod(ruta, 0o755)
    except Exception:
        pass
    if shutil.which("gio"):
        try:
            subprocess.run(["gio", "set", ruta, "metadata::trusted", "true"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception:
            pass


def crear_acceso_escritorio(p):
    """#3398: copia el lanzador de la app al escritorio. Devuelve (ok, mensaje)."""
    nombre = p.get("label") or "el programa"
    src = lanzador_de(p)
    if not src:
        return False, "No se pudo crear el acceso directo de %s." % nombre
    dest_dir = escritorio_dir()
    try:
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(src))
        if os.path.exists(dest):
            return True, "%s ya tiene acceso directo en el escritorio." % nombre
        shutil.copyfile(src, dest)
        confiar_lanzador(dest)
        return True, "Listo: acceso directo de %s en el escritorio." % nombre
    except Exception as e:
        return False, "No se pudo crear el acceso directo de %s:\n%s" % (nombre, e)


def es_tecla_recorte(event):
    """Las teclas de la herramienta de Recortes (las mismas que deja factupos-recortes
    en Cinnamon): Impr Pant con o sin Shift/Ctrl/Alt (Alt+Impr llega como Sys_Req)
    y Win+Shift+S."""
    kv = event.keyval
    if kv in (Gdk.KEY_Print, Gdk.KEY_Sys_Req):
        return True
    st = event.state
    win_ = st & (Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.MOD4_MASK)
    return bool(kv in (Gdk.KEY_s, Gdk.KEY_S) and win_ and st & Gdk.ModifierType.SHIFT_MASK)


def app_de_ejecutable(base):
    """La app instalada (.desktop) cuyo programa es `base` (ej. brave-browser), o None.
    🪤 El .desktop de Brave dice `Exec=/usr/bin/brave-browser-stable`: no alcanza con
    comparar el nombre, se compara también adónde apunta de verdad el programa."""
    try:
        ai = Gio.DesktopAppInfo.new(base + ".desktop")
        if ai is not None:
            return ai
    except Exception:
        pass
    real = os.path.realpath(shutil.which(base) or base)
    try:
        for ai in Gio.AppInfo.get_all():
            if not isinstance(ai, Gio.DesktopAppInfo):
                continue
            ex = (ai.get_executable() or "").split()
            if not ex:
                continue
            if os.path.basename(ex[0]) == base or \
                    os.path.realpath(shutil.which(ex[0]) or ex[0]) == real:
                return ai
    except Exception:
        pass
    return None


def os_version():
    """Versión de FactuPOS OS: SOLO el archivo /etc/factupos-os-version.

    NO se cae a VERSION_ID de /etc/os-release: eso devuelve la versión de la
    base (en LMDE 7 daba "7") y el banner la mostraba como si fuera la versión
    de FactuPOS OS. Si la distro no declara la suya, no se muestra nada."""
    try:
        if os.path.exists(OS_VERSION_FILE):
            with open(OS_VERSION_FILE) as f:
                v = f.read().strip()
                if v:
                    return v
    except Exception:
        pass
    return OS_VERSION_DEFAULT


PANELES = []      # todas las barras vivas (con --monitor all hay una por pantalla)
MONITOR_ALL = False   # se arrancó con --monitor all (una barra por pantalla)
PANEL_ARGS = {}       # edge/height, para crear barras de monitores que aparezcan después
_RESYNC_TIMER = None  # id del timer que agrupa (debounce) los avisos de X


def resync_monitors(*_a):
    """Vuelve a acomodar TODAS las barras cuando cambia la disposición de pantallas.

    Se llama por señal de X (monitors-changed / size-changed / monitor-added) y
    también a los pocos segundos de arrancar: en el login el escritorio suele
    aplicar la disposición real de los monitores DESPUÉS de que el panel ya se
    dibujó, y la barra quedaba con el tamaño equivocado hasta reiniciarla.
    """
    disp = Gdk.Display.get_default()
    if disp is None:
        return False
    n = disp.get_n_monitors()
    for p in list(PANELES):
        try:
            idx = p.monitor_index
            if idx is not None and idx >= n:
                p.hide()          # ese monitor ya no está (NO destruir: destroy cierra el panel)
                continue
            if not p.get_visible():
                p.show_all()      # volvió a conectarse
            p.resync_geometry()
        except Exception as e:
            sys.stderr.write("resync monitor: %s\n" % e)
    # Con --monitor all: si aparecieron pantallas nuevas, darles su barra.
    if MONITOR_ALL:
        ocupados = set(p.monitor_index for p in PANELES)
        for i in range(n):
            if i not in ocupados:
                try:
                    nuevo = Panel(monitor=i, primary=False, **PANEL_ARGS)
                    nuevo.show_all()
                except Exception as e:
                    sys.stderr.write("panel monitor %d: %s\n" % (i, e))
    return False          # no repetir si vino de un timeout


def _resync_fire():
    global _RESYNC_TIMER
    _RESYNC_TIMER = None
    resync_monitors()
    return False


def schedule_resync(*_a):
    """Agrupa los avisos de X (llegan varios seguidos) en una sola re-acomodada."""
    global _RESYNC_TIMER
    if _RESYNC_TIMER is not None:
        try:
            GLib.source_remove(_RESYNC_TIMER)
        except Exception:
            pass
    _RESYNC_TIMER = GLib.timeout_add(400, _resync_fire)


class Panel(Gtk.Window):
    def __init__(self, edge="bottom", height=DEFAULT_HEIGHT, monitor=None, primary=True):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.edge = edge
        self.vertical = edge in ("left", "right")
        self.height = height            # grosor de la barra (alto si horizontal, ancho si vertical)
        self.monitor_index = monitor   # None = monitor primario
        self.primary = primary          # solo el panel primario maneja atajos y auto-update
        self._xhotkey = None
        self._ctxmenu = None       # menú de clic derecho abierto (ver _popup_ctx)
        self._pinwin = None        # ventana "Accesos rápidos de la barra"
        # Barra bloqueada: no se puede mover de monitor ni cambiar de borde.
        # Se recuerda por usuario en STATE_FILE.
        self.locked = bool(load_state().get("locked", False))
        PANELES.append(self)

        self.set_title("FactuPOS Panel")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_keep_above(True)
        self.stick()
        self.get_style_context().add_class("fp-panel")

        self._apply_css()
        self._geometry()
        self._build_ui()

        self.connect("destroy", Gtk.main_quit)
        self.connect("realize", self._on_realize)
        self.connect("button-press-event", self._on_panel_click)
        self.connect("size-allocate", self._fit_start_icon)

    # ---------- estilo / geometría ----------
    def _apply_css(self):
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), prov,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _monitor_geo(self):
        disp = Gdk.Display.get_default()
        n = disp.get_n_monitors()
        mon = None
        if self.monitor_index is not None and 0 <= self.monitor_index < n:
            mon = disp.get_monitor(self.monitor_index)
        if mon is None and hasattr(disp, "get_primary_monitor"):
            mon = disp.get_primary_monitor()
        if mon is None:
            mon = disp.get_monitor(0)
        return mon.get_geometry()

    def _geometry(self):
        geo = self._monitor_geo()
        self._geo = geo
        if self.vertical:
            self.set_size_request(self.height, geo.height)
            self.resize(self.height, geo.height)
            x = geo.x if self.edge == "left" else geo.x + geo.width - self.height
            self.move(x, geo.y)
        else:
            self.set_size_request(geo.width, self.height)
            self.resize(geo.width, self.height)
            self.move(geo.x, geo.y if self.edge == "top"
                      else geo.y + geo.height - self.height)

    def resync_geometry(self):
        """Re-acomoda la barra si cambió la geometría de SU monitor o si la
        VENTANA no está donde debe.

        Al iniciar la sesión la barra puede nacer ANTES de que X/Cinnamon
        apliquen la disposición final de las pantallas. Falla de dos modos:
        1) la geometría del monitor cambia después (se detectaba desde 1.5.54);
        2) X/el WM CORREN la ventana al reacomodar los monitores sin que la
           geometría del monitor cambie para Gdk — la barra queda "a media
           pantalla", la comparación de geometrías decía "todo igual" y no se
           enderezaba (visto en la máquina del dueño el 1-ago con 1.5.54).
        Por eso también se compara dónde quedó la ventana contra dónde debería
        (posición + largo; el grosor no, para no pelear con el WM si el
        contenido pide más alto). No hace nada si todo coincide (barato).
        """
        geo = self._monitor_geo()
        old = getattr(self, "_geo", None)
        cambio = old is None or (old.x, old.y, old.width, old.height) != \
            (geo.x, geo.y, geo.width, geo.height)
        if not cambio and self.get_window() is not None:
            if self.vertical:
                esperado = (geo.x if self.edge == "left"
                            else geo.x + geo.width - self.height,
                            geo.y, geo.height)
                px, py = self.get_position()
                real = (px, py, self.get_size()[1])
            else:
                esperado = (geo.x,
                            geo.y if self.edge == "top"
                            else geo.y + geo.height - self.height,
                            geo.width)
                px, py = self.get_position()
                real = (px, py, self.get_size()[0])
            cambio = real != esperado
        if not cambio:
            return False
        self._geometry()
        if HAVE_XLIB and self.get_window() is not None:
            try:
                self._reserve_strut()
            except Exception as e:
                sys.stderr.write("strut: %s\n" % e)
        return True

    def _primary_index(self):
        disp = Gdk.Display.get_default()
        prim = disp.get_primary_monitor() if hasattr(disp, "get_primary_monitor") else None
        for i in range(disp.get_n_monitors()):
            if prim is not None and disp.get_monitor(i) == prim:
                return i
        return 0

    def move_to_monitor(self, index):
        """Mueve la barra a otro monitor (en caliente) y re-reserva el espacio."""
        if self.locked:
            return
        self.monitor_index = index
        self._geometry()
        if HAVE_XLIB and self.get_window() is not None:
            try:
                self._reserve_strut()
            except Exception as e:
                sys.stderr.write("strut: %s\n" % e)

    def _set_edge(self, edge):
        """Cambia el borde/orientación de la barra en caliente (reconstruye)."""
        if self.locked:
            return
        self.edge = edge
        self.vertical = edge in ("left", "right")
        child = self.get_child()
        if child is not None:
            child.destroy()
        self._geometry()
        self._build_ui()
        self.show_all()
        if HAVE_XLIB and self.get_window() is not None:
            try:
                self._reserve_strut()
            except Exception as e:
                sys.stderr.write("strut: %s\n" % e)
            # La barra se reconstruyó: re-anunciar la bandeja para que las apps
            # (AnyDesk, RustDesk...) vuelvan a colocar su icono.
            if self.primary and getattr(self, "_traywin", None) is not None:
                try:
                    self._traywin.change_property(
                        self._traydisp.intern_atom("_NET_SYSTEM_TRAY_ORIENTATION"),
                        Xatom.CARDINAL, 32, [1 if self.vertical else 0])
                    self._tray_announce()
                except Exception as e:
                    sys.stderr.write("tray re-announce: %s\n" % e)

    def _start_icon(self):
        """Crea el Gtk.Image del botón Inicio. Se reescala solo al alto real
        de la barra en _fit_start_icon() (conectado a size-allocate)."""
        self._start_src = None
        if os.path.exists(START_ICON):
            try:
                self._start_src = GdkPixbuf.Pixbuf.new_from_file(START_ICON)
            except Exception:
                self._start_src = None
        img = Gtk.Image()
        if self._start_src is None:
            img.set_from_icon_name("start-here", Gtk.IconSize.LARGE_TOOLBAR)
        return img

    def _fit_start_icon(self, _widget, alloc):
        """Ajusta el logo de Inicio al alto real de la barra (con un margen)."""
        if self._start_src is None:
            return
        target = max(16, alloc.height - 12)
        cur = self.start_img.get_pixbuf()
        if cur is not None and cur.get_height() == target:
            return   # ya está al tamaño correcto (evita bucle de size-allocate)
        sw, sh = self._start_src.get_width(), self._start_src.get_height()
        w = max(1, int(sw * target / sh))
        scaled = self._start_src.scale_simple(w, target, GdkPixbuf.InterpType.BILINEAR)
        self.start_img.set_from_pixbuf(scaled)

    # ---------- barra de tareas propia (ventanas abiertas) ----------
    # Wnck.Tasklist (el widget de la librería) es INTERMITENTE en este entorno
    # (a veces nace vacío, a veces se borra). Implementamos la barra a mano con
    # un botón por ventana, manejado por las señales de Wnck.Screen.
    def _make_tasklist(self):
        box = Gtk.Box(orientation=(Gtk.Orientation.VERTICAL if self.vertical
                                   else Gtk.Orientation.HORIZONTAL), spacing=2)
        self._taskbox = box
        self._task_btns = {}            # xid -> Gtk.Button
        self._task_orden = []           # 1.6.6: orden elegido arrastrando (xids)
        scr = self.wnck_screen
        scr.connect("window-opened", lambda _s, w: self._task_add(w))
        scr.connect("window-closed", lambda _s, w: self._task_remove(w))
        scr.connect("active-window-changed", lambda *_: self._task_highlight())
        scr.connect("active-workspace-changed", lambda *_: self._task_reload())
        for w in scr.get_windows():
            self._task_add(w)
        return box

    def _task_visible(self, w):
        try:
            if w.is_skip_tasklist():
                return False
            if w.is_pinned() or w.is_sticky():
                return True
            ws = w.get_workspace()
            cur = self.wnck_screen.get_active_workspace()
            if ws is None or cur is None:
                return True
            return ws.get_number() == cur.get_number()
        except Exception:
            return True

    def _task_add(self, w):
        try:
            xid = w.get_xid()
            if xid in self._task_btns or not self._task_visible(w):
                return
            btn = Gtk.Button()
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.get_style_context().add_class("fp-task")
            hb = Gtk.Box(spacing=6)
            img = Gtk.Image()
            pb = self._icono_ventana(w)
            if pb is not None:
                img.set_from_pixbuf(pb)
            hb.pack_start(img, False, False, 0)
            lbl = Gtk.Label(label=(w.get_name() or "")[:42])
            lbl.set_xalign(0)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_max_width_chars(24)
            hb.pack_start(lbl, True, True, 0)
            btn.add(hb)
            btn.set_tooltip_text(w.get_name() or "")
            btn.connect("clicked", lambda _b, win=w: self._task_click(win))
            # Clic derecho: agregar ese programa a la barra + minimizar/cerrar
            btn.connect("button-press-event", self._task_menu, w)
            try:
                w.connect("name-changed", lambda win, b=btn, l=lbl:
                          (l.set_text((win.get_name() or "")[:42]),
                           b.set_tooltip_text(win.get_name() or "")))
                w.connect("state-changed", lambda *_a: self._task_highlight())
                w.connect("icon-changed", lambda win, i=img:
                          i.set_from_pixbuf(self._icono_ventana(win)))
            except Exception:
                pass
            # 1.6.6 (#2698): se pueden ARRASTRAR para cambiarlas de lugar. El arrastre solo
            # empieza si se mueve el mouse con el botón apretado: el clic normal no cambia.
            try:
                btn.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [], Gdk.DragAction.MOVE)
                btn.drag_source_add_text_targets()
                btn.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.MOVE)
                btn.drag_dest_add_text_targets()
                btn.connect("drag-begin", lambda _b, ctx, win=w: self._task_drag_icono(ctx, win))
                btn.connect("drag-data-get", lambda _b, _c, data, _i, _t, x=xid: data.set_text(str(x), -1))
                btn.connect("drag-data-received", self._task_drop, xid)
            except Exception as e:
                sys.stderr.write("task dnd: %s\n" % e)
            self._taskbox.pack_start(btn, False, False, 0)
            btn.show_all()
            self._task_btns[xid] = btn
            self._task_aplicar_orden()
            self._task_highlight()
        except Exception as e:
            sys.stderr.write("task add: %s\n" % e)

    def _icono_ventana(self, w):
        """Ícono de una ventana abierta. RustDesk lleva la diadema de Soporte Remoto
        FactuPOS (#2942) en vez de su logo; el resto, el que trae la ventana."""
        try:
            if es_soporte(w.get_class_group_name(), w.get_class_instance_name()):
                pb = icono_soporte(16)
                if pb is not None:
                    return pb
        except Exception:
            pass
        return w.get_mini_icon() or w.get_icon()

    def _task_drag_icono(self, ctx, w):
        try:
            pb = self._icono_ventana(w)
            if pb is not None:
                Gtk.drag_set_icon_pixbuf(ctx, pb, pb.get_width() // 2, pb.get_height() // 2)
        except Exception:
            pass

    def _task_drop(self, dest_btn, ctx, x, y, data, _info, t, dest_xid):
        """Soltaron una ventana sobre otra: se ubica antes o después según el lado."""
        try:
            src_xid = int(data.get_text() or 0)
        except Exception:
            return
        src_btn = self._task_btns.get(src_xid)
        if src_btn is None or src_xid == dest_xid:
            return
        hijos = self._taskbox.get_children()
        hijos.remove(src_btn)
        pos = hijos.index(dest_btn)
        a = dest_btn.get_allocation()
        medio = (a.height if self.vertical else a.width) / 2.0
        if (y if self.vertical else x) > medio:
            pos += 1
        self._taskbox.reorder_child(src_btn, pos)
        inv = {b: k for k, b in self._task_btns.items()}
        self._task_orden = [inv[b] for b in self._taskbox.get_children() if b in inv]

    def _task_aplicar_orden(self):
        """Respeta el orden elegido a mano; las ventanas nuevas quedan al final."""
        if not self._task_orden:
            return
        rank = {x: i for i, x in enumerate(self._task_orden)}
        inv = {b: k for k, b in self._task_btns.items()}
        hijos = [b for b in self._taskbox.get_children() if b in inv]
        hijos.sort(key=lambda b: rank.get(inv[b], 10 ** 6))
        for i, b in enumerate(hijos):
            self._taskbox.reorder_child(b, i)

    def _task_remove(self, w):
        try:
            xid = w.get_xid()
            b = self._task_btns.pop(xid, None)
            if b is not None:
                b.destroy()
            if xid in self._task_orden:
                self._task_orden.remove(xid)
        except Exception:
            pass

    def _task_reload(self):
        for b in list(self._task_btns.values()):
            b.destroy()
        self._task_btns = {}
        for w in self.wnck_screen.get_windows():
            self._task_add(w)
        return False

    def _task_highlight(self):
        try:
            act = self.wnck_screen.get_active_window()
            axid = act.get_xid() if act is not None else None
            for xid, b in self._task_btns.items():
                ctx = b.get_style_context()
                if xid == axid:
                    ctx.add_class("fp-task-active")
                else:
                    ctx.remove_class("fp-task-active")
        except Exception:
            pass

    def _task_click(self, w):
        try:
            t = Gtk.get_current_event_time()
            if w.is_active() and not w.is_minimized():
                w.minimize()
            else:
                if w.is_minimized():
                    w.unminimize(t)
                w.activate(t)
        except Exception:
            pass

    def _show_windows_menu(self, btn):
        """Menú con las ventanas abiertas (consultado en el momento del clic, así
        siempre está al día). Clic en una = restaurar/enfocar."""
        menu = Gtk.Menu()
        menu.get_style_context().add_class("fp-flyout")
        try:
            self.wnck_screen.force_update()
        except Exception:
            pass
        wins = [w for w in self.wnck_screen.get_windows() if not w.is_skip_tasklist()]
        if not wins:
            mi = Gtk.MenuItem(label="(no hay ventanas abiertas)")
            mi.set_sensitive(False)
            menu.append(mi)
        else:
            for w in wins:
                mi = Gtk.MenuItem()
                hb = Gtk.Box(spacing=8)
                pb = self._icono_ventana(w)
                if pb is not None:
                    hb.pack_start(Gtk.Image.new_from_pixbuf(pb), False, False, 0)
                mark = "○ " if w.is_minimized() else "● "
                lbl = Gtk.Label(label=(mark + (w.get_name() or ""))[:60])
                lbl.set_xalign(0)
                hb.pack_start(lbl, True, True, 0)
                mi.add(hb)
                mi.connect("activate", lambda _m, win=w: self._task_click(win))
                menu.append(mi)
        menu.show_all()
        try:
            menu.popup_at_widget(btn, Gdk.Gravity.NORTH_WEST,
                                 Gdk.Gravity.SOUTH_WEST, None)
        except Exception:
            menu.popup(None, None, None, None, 1, Gtk.get_current_event_time())

    def _resync_tasklist(self):
        """Catch-up NO destructivo: agrega las ventanas que existan pero aún no
        tengan botón (por si la pantalla no estaba poblada al arrancar) y quita
        las que ya no existen. NO usa force_update() (deja get_windows()
        momentáneamente vacío y borraría los botones buenos)."""
        try:
            wins = self.wnck_screen.get_windows()
            for w in wins:
                if w.get_xid() not in self._task_btns:
                    self._task_add(w)
            live = set(w.get_xid() for w in wins)
            for xid in list(self._task_btns):
                if xid not in live:
                    b = self._task_btns.pop(xid)
                    b.destroy()
        except Exception as e:
            sys.stderr.write("task resync: %s\n" % e)
        return False

    # ---------- accesos rápidos anclados a la barra ----------
    # Franja de íconos entre "Ventanas abiertas" y la lista de programas
    # abiertos: un clic = abrir el programa (esté abierto o no).
    def _make_pinbox(self):
        box = Gtk.Box(orientation=(Gtk.Orientation.VERTICAL if self.vertical
                                   else Gtk.Orientation.HORIZONTAL), spacing=0)
        self._pinbox = box
        self._rebuild_pins()
        return box

    def _rebuild_pins(self):
        """Vuelve a dibujar la franja de accesos desde el estado guardado."""
        box = getattr(self, "_pinbox", None)
        if box is None:
            return
        for hijo in box.get_children():
            hijo.destroy()
        pins = load_pins()
        for i, p in enumerate(pins):
            box.pack_start(self._pin_button(i, p), False, False, 0)
        if pins:
            sep = Gtk.Separator(orientation=(Gtk.Orientation.HORIZONTAL if self.vertical
                                             else Gtk.Orientation.VERTICAL))
            sep.get_style_context().add_class("fp-pinsep")
            box.pack_start(sep, False, False, 0)
        box.show_all()

    def _pin_appinfo(self, p):
        """El .desktop del acceso, si el programa sigue instalado."""
        d = p.get("desktop")
        if not d:
            return None
        try:
            return Gio.DesktopAppInfo.new(d)
        except Exception:
            return None

    def _pin_instalado(self, p):
        if p.get("desktop"):
            return self._pin_appinfo(p) is not None
        return cmd_available(p.get("cmd") or "")

    def _pin_image(self, p, px=24):
        # Soporte Remoto (RustDesk): la diadema SIEMPRE, aunque el acceso se haya anclado
        # antes con el logo viejo guardado en estado.json (#2942, 1.7.6).
        if es_soporte(p.get("desktop"), p.get("cmd")):
            pb = icono_soporte(px)
            if pb is not None:
                img = Gtk.Image.new_from_pixbuf(pb)
                img.set_pixel_size(px)
                return img
        ai = self._pin_appinfo(p)
        img = None
        if ai is not None:
            try:
                gi = ai.get_icon()
                if gi is not None:
                    img = Gtk.Image.new_from_gicon(gi, Gtk.IconSize.LARGE_TOOLBAR)
            except Exception:
                img = None
        if img is None:
            ic = p.get("icon") or ""
            if ic.startswith("/") and os.path.exists(ic):
                try:
                    img = Gtk.Image.new_from_pixbuf(
                        GdkPixbuf.Pixbuf.new_from_file_at_size(ic, px, px))
                except Exception:
                    img = None
            if img is None:
                img = Gtk.Image.new_from_icon_name(ic or "application-x-executable",
                                                   Gtk.IconSize.LARGE_TOOLBAR)
        img.set_pixel_size(px)
        return img

    def _pin_button(self, idx, p):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.get_style_context().add_class("fp-pin")
        b.add(self._pin_image(p, max(16, self.height - 20)))
        label = p.get("label") or p.get("cmd") or "Programa"
        if self._pin_instalado(p):
            b.set_tooltip_text(label)
            b.connect("clicked", lambda _w, pin=p: self._pin_launch(pin))
        else:
            # No se oculta: el usuario debe ver que el acceso sigue ahí y por
            # qué no funciona (clic derecho para quitarlo).
            b.set_sensitive(False)
            b.set_tooltip_text("%s ya no está instalado en este equipo\n"
                               "(clic derecho sobre el ícono para quitarlo)" % label)
        b.connect("button-press-event", self._pin_click, idx)
        return b

    def _pin_launch(self, p):
        ai = self._pin_appinfo(p)
        if ai is not None:
            self._launch_appinfo(ai)
            return
        detached_run(p.get("cmd") or "")

    def _pin_click(self, widget, event, idx):
        """Clic derecho sobre un acceso: abrir, moverlo o quitarlo."""
        if event.button != 3:
            return False
        pins = load_pins()
        if idx >= len(pins):
            return False
        p = pins[idx]
        label = p.get("label") or "este acceso"
        menu = Gtk.Menu()

        mi = Gtk.MenuItem(label="Abrir %s" % label)
        mi.set_sensitive(self._pin_instalado(p))
        mi.connect("activate", lambda *_: self._pin_launch(p))
        menu.append(mi)
        menu.append(Gtk.SeparatorMenuItem())

        izq = "arriba" if self.vertical else "la izquierda"
        der = "abajo" if self.vertical else "la derecha"
        mi = Gtk.MenuItem(label="Mover hacia %s" % izq)
        mi.set_sensitive(idx > 0 and not self.locked)
        mi.connect("activate", lambda *_: self._pin_move(idx, -1))
        menu.append(mi)

        mi = Gtk.MenuItem(label="Mover hacia %s" % der)
        mi.set_sensitive(idx < len(pins) - 1 and not self.locked)
        mi.connect("activate", lambda *_: self._pin_move(idx, +1))
        menu.append(mi)

        menu.append(Gtk.SeparatorMenuItem())
        mi = Gtk.MenuItem(label="Quitar de la barra")
        # Barra bloqueada: se ve en gris, no se esconde (igual que mover/posición).
        mi.set_sensitive(not self.locked)
        mi.connect("activate", lambda *_: self._pin_remove(idx))
        menu.append(mi)

        mi = Gtk.MenuItem(label="Agregar otro acceso a la barra…")
        mi.set_sensitive(not self.locked)
        mi.connect("activate", lambda *_: self.open_anclados())
        menu.append(mi)

        self._popup_ctx(menu, event)
        return True

    def _pin_add(self, p, avisar=True):
        """Ancla un acceso al final de la franja. False si ya estaba."""
        pins = load_pins()
        k = pin_key(p)
        if any(pin_key(x) == k for x in pins):
            if avisar:
                self._notify("«%s» ya estaba en la barra." % (p.get("label") or ""))
            return False
        pins.append(p)
        save_pins(pins)
        refrescar_anclados()
        if avisar:
            self._notify("«%s» quedó en la barra." % (p.get("label") or ""))
        return True

    def _pin_remove(self, idx):
        pins = load_pins()
        if 0 <= idx < len(pins):
            fuera = pins.pop(idx)
            save_pins(pins)
            refrescar_anclados()
            self._notify("«%s» se quitó de la barra." % (fuera.get("label") or ""))

    def _pin_move(self, idx, delta):
        pins = load_pins()
        j = idx + delta
        if 0 <= idx < len(pins) and 0 <= j < len(pins):
            pins[idx], pins[j] = pins[j], pins[idx]
            save_pins(pins)
            refrescar_anclados()

    def _pin_menu_desde_item(self, widget, event, p):
        """Clic derecho sobre una app del menú Inicio → agregarla a la barra."""
        if event.button != 3:
            return False
        menu = Gtk.Menu()
        mi = Gtk.MenuItem(label="Agregar a la barra")
        ya = any(pin_key(x) == pin_key(p) for x in load_pins())
        if ya:
            mi = Gtk.MenuItem(label="Ya está en la barra")
            mi.set_sensitive(False)
        elif self.locked:
            mi.set_sensitive(False)   # barra bloqueada: se ve, en gris
        else:
            mi.connect("activate", lambda *_: (self._close_start_menu(),
                                               self._pin_add(p)))
        menu.append(mi)
        me = Gtk.MenuItem(label="Crear acceso directo en el escritorio")
        me.connect("activate", lambda *_: (self._close_start_menu(),
                                           self._acceso_escritorio(p)))
        menu.append(me)
        self._popup_ctx(menu, event)
        return True

    def _pin_curado(self, label, cmd, icon=None):
        """#3398: items armados a mano (Navegadores, Mensajería, Programas, Utilidades,
        Configuración). Si hay una app instalada con ese mismo programa, se usa SU
        .desktop (el acceso del escritorio queda igual al del sistema); si no, el
        comando. Así también tienen clic derecho y se pueden arrastrar."""
        base = os.path.basename((cmd or "").split()[0]) if cmd else ""
        if base and not base.startswith("@") and len((cmd or "").split()) == 1:
            ai = app_de_ejecutable(base)
            if ai is not None:
                p = pin_desde_appinfo(ai)
                p["label"] = label
                if icon:
                    p["icon"] = icon
                return p
        return self._pin_desde_cmd(label, cmd, icon)

    def _pin_desde_cmd(self, label, cmd, icon=None):
        """Acceso anclable a partir de un comando del menú. Los tokens internos
        (@taskmgr, @apagar…) no se anclan: no son programas."""
        if not cmd or cmd.startswith("@"):
            return None
        p = {"label": label, "cmd": cmd}
        if icon:
            p["icon"] = icon
        return p

    def _popup_ctx(self, menu, event):
        """Abre un menú de clic derecho avisando que HAY uno abierto.

        🔑 Sin esto, si el clic derecho se hace sobre un item del menú Inicio,
        el submenú se desactiva → `_on_deact` → `_regrab_start` le devuelve el
        grab a la ventana del menú y este menú se cierra solo (es la misma
        trampa de grabs de la v1.5.44). Mientras `_ctxmenu` viva, `_regrab_start`
        y el hover de submenús no tocan nada."""
        self._ctxmenu = menu

        def _fin(m):
            if getattr(self, "_ctxmenu", None) is m:
                self._ctxmenu = None
                GLib.idle_add(self._regrab_start)
        menu.connect("deactivate", _fin)
        self._menu_escucha_recorte(menu)
        menu.show_all()
        try:
            menu.popup_at_pointer(event)
        except Exception:
            menu.popup(None, None, None, None, 3, Gtk.get_current_event_time())

    def _pin_conectar_item(self, mi, p):
        """Engancha el clic derecho 'Agregar a la barra' a un item de menú."""
        if p is None:
            return mi
        try:
            mi.connect("button-press-event", self._pin_menu_desde_item, p)
        except Exception:
            pass
        self._arrastre_conectar(mi, p)
        return mi

    # ---------- #3398: arrastrar una app del menú al escritorio ----------
    def _arrastre_conectar(self, w, p):
        """El item del menú se puede arrastrar: suelta un text/uri-list con su
        .desktop, que el escritorio copia como acceso directo (igual que el menú
        de Cinnamon). El clic normal sigue abriendo la app."""
        if p is None or (p.get("cmd") or "").startswith("@") and not p.get("desktop"):
            return
        try:
            w.drag_source_set(Gdk.ModifierType.BUTTON1_MASK,
                              [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
                              Gdk.DragAction.COPY)
            w.connect("drag-begin", self._arrastre_inicio, p)
            w.connect("drag-data-get", self._arrastre_datos, p)
            w.connect("drag-end", self._arrastre_fin)
        except Exception as e:
            sys.stderr.write("arrastre: %s\n" % e)

    def _arrastre_inicio(self, w, ctx, p):
        self._arrastrando = True
        try:
            ic = p.get("icon")
            if ic and ic.startswith("/") and os.path.exists(ic):
                Gtk.drag_set_icon_pixbuf(
                    ctx, GdkPixbuf.Pixbuf.new_from_file_at_size(ic, 32, 32), 0, 0)
                return
            gi = None
            if p.get("desktop"):
                ai = Gio.DesktopAppInfo.new(p["desktop"])
                gi = ai.get_icon() if ai is not None else None
            if gi is not None:
                Gtk.drag_set_icon_gicon(ctx, gi, 0, 0)
            else:
                Gtk.drag_set_icon_name(ctx, ic or "application-x-executable", 0, 0)
        except Exception:
            pass

    def _arrastre_datos(self, w, ctx, data, info, t, p):
        ruta = lanzador_de(p)
        if ruta:
            data.set_uris([GLib.filename_to_uri(ruta, None)])

    def _arrastre_fin(self, w, ctx):
        self._arrastrando = False
        GLib.idle_add(self._close_start_menu)

    def _acceso_escritorio(self, p):
        ok, msg = crear_acceso_escritorio(p)
        if not ok:
            _error_dialog(msg)
        else:
            self._notify(msg)

    # ---------- #3398: Recortes con un menú de la barra abierto ----------
    # Cada menú de la barra AGARRA teclado y mouse (seat.grab) para enterarse
    # del clic afuera. Mientras tanto X le manda TODAS las teclas a la barra:
    # el atajo Impr Pant de Cinnamon no se entera y la herramienta de Recortes
    # no podría usar el mouse. Por eso la barra misma atiende la tecla: suelta
    # el grab, abre Recortes con el menú TODAVÍA visible (sale en la captura)
    # y lo cierra un rato después, cuando la pantalla ya quedó congelada.
    def _tecla_recorte(self, event, cerrar):
        if not es_tecla_recorte(event):
            return False
        self._recorte_lanzar(cerrar)
        return True

    def _menu_escucha_recorte(self, menu):
        def _k(m, ev):
            return self._tecla_recorte(ev, lambda: (m.popdown(), self._close_start_menu()))
        try:
            menu.connect("key-press-event", _k)
        except Exception:
            pass

    def _recorte_lanzar(self, cerrar):
        if getattr(self, "_recortando", False):
            return
        cmd = ("factupos-recortes" if cmd_available("factupos-recortes")
               else "flameshot gui" if cmd_available("flameshot") else None)
        self._recortando = True
        try:
            Gdk.Display.get_default().get_default_seat().ungrab()
        except Exception:
            pass

        def _fin():
            self._recortando = False
            try:
                cerrar()
            except Exception:
                pass
            return False
        if cmd:
            detached_run(cmd)
            GLib.timeout_add(RECORTE_CIERRE_MS, _fin)
        else:
            _fin()

    def _pin_desde_ventana(self, w):
        """Intenta identificar el .desktop de una ventana abierta (para poder
        anclar 'el programa que está abierto', como en Windows). Devuelve None
        si no se puede: mejor no ofrecer la opción que anclar algo equivocado."""
        nombres = []
        try:
            grp = w.get_class_group()
            if grp is not None:
                for f in ("get_id", "get_res_class", "get_name"):
                    try:
                        v = getattr(grp, f)()
                        if v:
                            nombres.append(v)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            app = w.get_application()
            if app is not None and app.get_name():
                nombres.append(app.get_name())
        except Exception:
            pass
        cands = []
        for n in nombres:
            n = n.strip()
            if not n:
                continue
            cands += [n, n.lower(), n + ".desktop", n.lower() + ".desktop"]
        for c in cands:
            if not c.endswith(".desktop"):
                continue
            try:
                ai = Gio.DesktopAppInfo.new(c)
            except Exception:
                ai = None
            if ai is not None:
                return pin_desde_appinfo(ai)
        # Último intento: por nombre visible contra las apps instaladas.
        objetivo = set(n.strip().lower() for n in nombres if n)
        for ai in Gio.AppInfo.get_all():
            try:
                if not ai.should_show():
                    continue
                nm = (ai.get_display_name() or "").strip().lower()
                ex = (ai.get_executable() or "").split("/")[-1].strip().lower()
            except Exception:
                continue
            if nm in objetivo or (ex and ex in objetivo):
                return pin_desde_appinfo(ai)
        return None

    def _task_menu(self, widget, event, w):
        """Clic derecho sobre una ventana abierta de la barra de tareas."""
        if event.button != 3:
            return False
        menu = Gtk.Menu()
        p = self._pin_desde_ventana(w)
        if p is not None:
            ya = any(pin_key(x) == pin_key(p) for x in load_pins())
            mi = Gtk.MenuItem(label=("Ya está en la barra" if ya
                                     else "Agregar a la barra"))
            if ya or self.locked:
                mi.set_sensitive(False)
            else:
                mi.connect("activate", lambda *_: self._pin_add(p))
            menu.append(mi)
            menu.append(Gtk.SeparatorMenuItem())
        mi = Gtk.MenuItem(label="Minimizar" if not w.is_minimized() else "Restaurar")
        mi.connect("activate", lambda *_: self._task_click(w))
        menu.append(mi)
        mi = Gtk.MenuItem(label="Cerrar la ventana")
        mi.connect("activate", lambda *_: w.close(Gtk.get_current_event_time()))
        menu.append(mi)
        self._popup_ctx(menu, event)
        return True

    # ---------- ventana "Accesos rápidos de la barra" ----------
    def open_anclados(self, *_):
        """Ventana para armar la franja: buscar un programa, agregarlo,
        ordenarlo o quitarlo. Es el camino descubrible (el clic derecho en el
        menú Inicio hace lo mismo en un paso)."""
        if getattr(self, "_pinwin", None) is not None:
            self._close_pin_win()
            return
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_decorated(False)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        win.set_keep_above(True)
        win.set_resizable(False)
        win.set_size_request(720, -1)
        win.get_style_context().add_class("fp-startmenu")
        self._pinwin = win

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(14)
        win.add(box)

        head = Gtk.Box(spacing=10)
        head.pack_start(Gtk.Image.new_from_icon_name("bookmark-new",
                                                     Gtk.IconSize.DIALOG), False, False, 0)
        ht = Gtk.Label()
        ht.set_markup("<span size='large'><b>Accesos rápidos de la barra</b></span>\n"
                      "Elegí un programa de la izquierda y presioná «Agregar a la barra».")
        ht.set_xalign(0)
        head.pack_start(ht, True, True, 0)
        box.pack_start(head, False, False, 4)
        box.pack_start(Gtk.Separator(), False, False, 4)

        cols = Gtk.Box(spacing=12)
        box.pack_start(cols, True, True, 0)

        # --- Columna izquierda: programas instalados ---
        izq = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        cols.pack_start(izq, True, True, 0)
        izq.pack_start(self._section_label("Programas de este equipo"), False, False, 0)
        busc = Gtk.SearchEntry()
        busc.set_placeholder_text("Buscar un programa…")
        izq.pack_start(busc, False, False, 0)

        self._pin_lista = Gtk.ListBox()
        self._pin_lista.set_selection_mode(Gtk.SelectionMode.SINGLE)
        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc.set_size_request(-1, 280)
        sc.add(self._pin_lista)
        izq.pack_start(sc, True, True, 0)

        apps = []
        vistos = set()
        for ai in Gio.AppInfo.get_all():
            try:
                if not ai.should_show():
                    continue
                did = ai.get_id() or ""
            except Exception:
                continue
            if not did or did in vistos:
                continue
            vistos.add(did)
            apps.append(((ai.get_display_name() or ai.get_name() or did), ai))
        apps.sort(key=lambda x: x[0].lower())
        for nm, ai in apps:
            row = Gtk.ListBoxRow()
            row._pin = pin_desde_appinfo(ai)
            row._texto = nm.lower()
            hb = Gtk.Box(spacing=8)
            hb.set_border_width(4)
            try:
                im = Gtk.Image.new_from_gicon(ai.get_icon(), Gtk.IconSize.LARGE_TOOLBAR)
            except Exception:
                im = Gtk.Image.new_from_icon_name("application-x-executable",
                                                  Gtk.IconSize.LARGE_TOOLBAR)
            im.set_pixel_size(22)
            hb.pack_start(im, False, False, 0)
            l = Gtk.Label(label=nm)
            l.set_xalign(0)
            l.set_ellipsize(Pango.EllipsizeMode.END)
            hb.pack_start(l, True, True, 0)
            row.add(hb)
            self._pin_lista.add(row)

        def _filtra(row):
            t = busc.get_text().strip().lower()
            return (not t) or (t in getattr(row, "_texto", ""))
        self._pin_lista.set_filter_func(_filtra)
        busc.connect("search-changed", lambda *_: self._pin_lista.invalidate_filter())

        def _agregar(*_a):
            row = self._pin_lista.get_selected_row()
            if row is None:
                self._pin_aviso("Elegí primero un programa de la lista de la izquierda.")
                return
            p = dict(row._pin)
            nom = p.get("label") or "El programa"
            if self._pin_add(p, avisar=False):
                self._pin_refrescar_actuales(sel=len(load_pins()) - 1)
                self._pin_aviso("«%s» quedó al final de la barra." % nom)
            else:
                self._pin_aviso("«%s» ya estaba en la barra." % nom)
        self._pin_lista.connect("row-activated", lambda *_: _agregar())

        add_btn = Gtk.Button(label="Agregar a la barra  ▶")
        add_btn.connect("clicked", _agregar)
        izq.pack_start(add_btn, False, False, 0)

        # --- Columna derecha: lo que ya está en la barra ---
        der = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        cols.pack_start(der, True, True, 0)
        der.pack_start(self._section_label("Ahora en la barra (de izquierda a derecha)"),
                       False, False, 0)
        self._pin_actuales = Gtk.ListBox()
        self._pin_actuales.set_selection_mode(Gtk.SelectionMode.SINGLE)
        sc2 = Gtk.ScrolledWindow()
        sc2.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sc2.set_size_request(-1, 280)
        sc2.add(self._pin_actuales)
        der.pack_start(sc2, True, True, 0)

        acc = Gtk.Box(spacing=6)
        def _sel_idx():
            row = self._pin_actuales.get_selected_row()
            return None if row is None else row.get_index()

        def _mover(delta):
            i = _sel_idx()
            if i is None:
                self._pin_aviso("Elegí primero un acceso de la lista de la derecha.")
                return
            if not (0 <= i + delta < len(load_pins())):
                self._pin_aviso("Ese acceso ya está en la punta.")
                return
            self._pin_move(i, delta)
            self._pin_refrescar_actuales(sel=i + delta)
            self._pin_aviso("Listo, quedó en la posición %d." % (i + delta + 1))

        def _quitar(*_a):
            i = _sel_idx()
            if i is None:
                self._pin_aviso("Elegí primero un acceso de la lista de la derecha.")
                return
            pins = load_pins()
            nom = pins[i].get("label") if i < len(pins) else ""
            self._pin_remove(i)
            self._pin_refrescar_actuales(sel=min(i, len(load_pins()) - 1))
            self._pin_aviso("«%s» se quitó de la barra." % (nom or ""))

        b1 = Gtk.Button(label="◀ Mover")
        b1.set_tooltip_text("Mover el acceso hacia la izquierda de la barra")
        b1.connect("clicked", lambda *_: _mover(-1))
        acc.pack_start(b1, True, True, 0)
        b2 = Gtk.Button(label="Mover ▶")
        b2.set_tooltip_text("Mover el acceso hacia la derecha de la barra")
        b2.connect("clicked", lambda *_: _mover(+1))
        acc.pack_start(b2, True, True, 0)
        b3 = Gtk.Button(label="Quitar de la barra")
        b3.connect("clicked", _quitar)
        acc.pack_start(b3, True, True, 0)
        der.pack_start(acc, False, False, 0)

        self._pin_refrescar_actuales()

        box.pack_start(Gtk.Separator(), False, False, 6)
        pie = Gtk.Box(spacing=6)
        self._pin_msg = Gtk.Label()
        self._pin_msg.set_xalign(0)
        self._pin_msg.set_ellipsize(Pango.EllipsizeMode.END)
        self._pin_aviso("Los cambios se ven en la barra al instante.")
        pie.pack_start(self._pin_msg, True, True, 0)
        listo = Gtk.Button(label="Listo")
        listo.connect("clicked", lambda *_: self._close_pin_win())
        pie.pack_start(listo, False, False, 0)
        box.pack_start(pie, False, False, 0)

        win.show_all()
        geo = self._geo
        _m, nat = win.get_preferred_size()
        w, h = nat.width, nat.height
        win.move(max(geo.x, geo.x + (geo.width - w) // 2),
                 max(geo.y, geo.y + (geo.height - h) // 2))
        win.connect("button-press-event", self._pin_click_outside)
        win.connect("key-press-event", self._pin_key)
        win.connect("destroy", lambda *_: setattr(self, "_pinwin", None))
        GLib.idle_add(self._grab_pin_win, win)

    def _pin_aviso(self, texto):
        """Avisa DENTRO de la ventana (no depende de que haya notify-send)."""
        lbl = getattr(self, "_pin_msg", None)
        if lbl is not None:
            lbl.set_markup("<small>%s</small>" % GLib.markup_escape_text(texto))
        else:
            self._notify(texto)

    def _pin_refrescar_actuales(self, sel=None):
        lb = getattr(self, "_pin_actuales", None)
        if lb is None:
            return
        for hijo in lb.get_children():
            hijo.destroy()
        pins = load_pins()
        if not pins:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            l = Gtk.Label(label="(todavía no hay accesos en la barra)")
            l.set_xalign(0)
            l.set_margin_top(6)
            l.set_margin_bottom(6)
            l.set_margin_start(6)
            row.add(l)
            lb.add(row)
        for i, p in enumerate(pins):
            row = Gtk.ListBoxRow()
            hb = Gtk.Box(spacing=8)
            hb.set_border_width(4)
            im = self._pin_image(p, 22)
            hb.pack_start(im, False, False, 0)
            texto = p.get("label") or p.get("cmd") or "Programa"
            if not self._pin_instalado(p):
                texto += "  (ya no está instalado)"
            l = Gtk.Label(label="%d.  %s" % (i + 1, texto))
            l.set_xalign(0)
            l.set_ellipsize(Pango.EllipsizeMode.END)
            hb.pack_start(l, True, True, 0)
            row.add(hb)
            lb.add(row)
        lb.show_all()
        if sel is not None and pins:
            r = lb.get_row_at_index(max(0, min(sel, len(pins) - 1)))
            if r is not None:
                lb.select_row(r)

    def _grab_pin_win(self, win):
        gw = win.get_window()
        if gw is None:
            return False
        try:
            win.get_display().get_default_seat().grab(
                gw, Gdk.SeatCapabilities.ALL, True, None, None, None, None)
        except Exception:
            pass
        return False

    def _pin_click_outside(self, win, event):
        a = win.get_allocation()
        if event.x < 0 or event.y < 0 or event.x > a.width or event.y > a.height:
            self._close_pin_win()
            return True
        return False

    def _pin_key(self, win, event):
        if self._tecla_recorte(event, self._close_pin_win):
            return True
        if event.keyval == Gdk.KEY_Escape:
            self._close_pin_win()
            return True
        return False

    def _close_pin_win(self):
        win = getattr(self, "_pinwin", None)
        if win is None:
            return
        try:
            win.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        self._pinwin = None
        self._pin_actuales = None
        self._pin_msg = None
        win.destroy()

    # ---------- construcción de la barra ----------
    def _build_ui(self):
        orient = (Gtk.Orientation.VERTICAL if self.vertical
                  else Gtk.Orientation.HORIZONTAL)
        root = Gtk.Box(orientation=orient, spacing=0)
        self.add(root)

        # --- Botón Inicio ---
        self.start_btn = Gtk.Button()
        self.start_btn.get_style_context().add_class("fp-start")
        self.start_btn.set_relief(Gtk.ReliefStyle.NONE)
        hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hb.set_halign(Gtk.Align.CENTER)
        self.start_img = self._start_icon()
        hb.pack_start(self.start_img, False, False, 0)
        if not self.vertical:
            hb.pack_start(Gtk.Label(label="Inicio"), False, False, 0)
        self.start_btn.add(hb)
        self.start_btn.connect("clicked", self.toggle_start_menu)
        root.pack_start(self.start_btn, False, False, 0)

        # --- Botón "Ventanas abiertas" (después de Inicio) ---
        self.windows_btn = Gtk.Button()
        self.windows_btn.get_style_context().add_class("fp-net")
        self.windows_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.windows_btn.add(Gtk.Image.new_from_icon_name(
            "preferences-system-windows", Gtk.IconSize.LARGE_TOOLBAR))
        self.windows_btn.set_tooltip_text("Ventanas abiertas")
        self.windows_btn.connect("clicked", self._show_windows_menu)
        root.pack_start(self.windows_btn, False, False, 0)

        # --- Accesos rápidos anclados (franja de íconos, izq -> der) ---
        root.pack_start(self._make_pinbox(), False, False, 0)

        # --- Lista de programas abiertos (Wnck) ---
        self.wnck_screen = Wnck.Screen.get_default()
        self.wnck_screen.force_update()
        self.tasklist = self._make_tasklist()
        root.pack_start(self.tasklist, True, True, 4)
        # Catch-up no destructivo unas veces tras arrancar, por si la pantalla
        # todavía no estaba poblada (carrera con el WM). Ver _resync_tasklist().
        for _d in (2, 5, 10):
            GLib.timeout_add_seconds(_d, self._resync_tasklist)

        # --- Bandeja del sistema (XEmbed: AnyDesk, RustDesk, Telegram, etc.) ---
        self._tray_box = Gtk.Box(orientation=orient, spacing=2)
        root.pack_start(self._tray_box, False, False, 4)

        # --- Red / WiFi ---
        self.net_btn = Gtk.Button()
        self.net_btn.get_style_context().add_class("fp-net")
        self.net_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.net_img = Gtk.Image.new_from_icon_name(
            "network-offline-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        self.net_btn.add(self.net_img)
        self.net_btn.set_tooltip_text("Red / WiFi  (Conectar / Desconectar / Configurar)")
        self.net_btn.connect("button-press-event", self._net_btn_press)
        root.pack_start(self.net_btn, False, False, 0)

        # --- Bluetooth (1.7.0, #2942): propio, reemplaza el applet del sistema ---
        self.bt_btn = Gtk.Button()
        self.bt_btn.get_style_context().add_class("fp-net")
        self.bt_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.bt_img = Gtk.Image.new_from_icon_name("bluetooth-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        self.bt_btn.add(self.bt_img)
        self.bt_btn.set_tooltip_text("Bluetooth")
        self.bt_btn.connect("clicked", self.open_bluetooth)
        self.bt_btn.set_no_show_all(True)      # se muestra solo si la PC tiene Bluetooth
        root.pack_start(self.bt_btn, False, False, 0)

        # --- Volumen (campanita de audio) ---
        self.vol_btn = Gtk.Button()
        self.vol_btn.get_style_context().add_class("fp-net")
        self.vol_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.vol_img = Gtk.Image.new_from_icon_name(
            "audio-volume-medium-symbolic", Gtk.IconSize.LARGE_TOOLBAR)
        self.vol_btn.add(self.vol_img)
        self.vol_btn.set_tooltip_text("Volumen")
        self.vol_btn.connect("clicked", self.open_volume)
        root.pack_start(self.vol_btn, False, False, 0)

        # --- Reloj / Fecha ---
        self.clock_btn = Gtk.Button()
        self.clock_btn.get_style_context().add_class("fp-clock")
        self.clock_btn.set_relief(Gtk.ReliefStyle.NONE)
        self.clock_lbl = Gtk.Label()
        self.clock_lbl.set_justify(Gtk.Justification.CENTER)
        self.clock_btn.add(self.clock_lbl)
        self.clock_btn.connect("clicked", self.open_calendar)
        self.clock_btn.set_tooltip_text("Calendario, fecha/hora, zona horaria y teclado")
        root.pack_start(self.clock_btn, False, False, 0)

        # --- Mostrar escritorio (extremo derecho, como Windows) ---
        self.showdesk = Gtk.Button()
        self.showdesk.get_style_context().add_class("fp-showdesk")
        self.showdesk.set_relief(Gtk.ReliefStyle.NONE)
        self.showdesk.set_tooltip_text("Mostrar el escritorio")
        self.showdesk.connect("clicked", self.toggle_show_desktop)
        root.pack_start(self.showdesk, False, False, 0)

        self._tick()
        self._update_net()
        self._update_vol()
        self._update_bt()
        if not getattr(self, "_timers_started", False):
            self._timers_started = True
            GLib.timeout_add_seconds(1, self._tick)
            GLib.timeout_add_seconds(5, self._update_net)
            GLib.timeout_add_seconds(3, self._update_vol)
            GLib.timeout_add_seconds(5, self._update_bt)
            # Auto-actualización solo en el panel primario (evita reinicios múltiples).
            if self.primary:
                GLib.timeout_add_seconds(20, self._check_update_once)
                GLib.timeout_add_seconds(UPDATE_INTERVAL, self._check_update_loop)
                # 1.7.0 (#2942): también pone al día las DEMÁS apps FactuPOS
                GLib.timeout_add_seconds(90, self._check_apps_update_bg)
                GLib.timeout_add_seconds(900, self._aviso_reinicio)
                GLib.timeout_add_seconds(3, self._bt_ocultar_applet_sistema)

    # ---------- reloj ----------
    def _tick(self):
        now = datetime.datetime.now()
        hora = now.strftime("%H:%M")
        if self.vertical:
            fecha = now.strftime("%d/%m")
            sz = "x-small"
        else:
            fecha = now.strftime("%d/%m/%Y")
            sz = "small"
        self.clock_lbl.set_markup(
            "<b>%s</b>\n<span size='%s'>%s</span>" % (hora, sz, fecha))
        self.clock_btn.set_tooltip_text(now.strftime("%A %d de %B de %Y"))
        return True

    # ---------- red ----------
    def _update_net(self):
        icon, tip = self._net_state()
        ips = [ip for (_t, _n, ip, _s) in self._net_details() if ip]
        if ips:
            tip = tip + "\nIP: " + ", ".join(ips)
        clase = ("lan" if icon.startswith("network-wired") else
                 "wifi" if icon.startswith("network-wireless") else "off")
        pb = icono_estado(clase)
        if pb is not None:
            self.net_img.set_from_pixbuf(pb)
        else:
            self.net_img.set_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
        self.net_btn.set_tooltip_text(tip)
        return True

    def _net_btn_press(self, widget, event):
        """Clic IZQUIERDO -> abre directo la ventana de Red (1.6.7, pedido del dueño #2698).
        Clic DERECHO -> menú chico Conectar/Desconectar/Configurar."""
        if event.button == 1:
            self.open_network()
            return True
        if event.button == 3:
            menu = Gtk.Menu()
            menu.get_style_context().add_class("fp-flyout")
            for label, cmd in (("Conectar", "nmcli networking on"),
                               ("Desconectar", "nmcli networking off"),
                               (None, None),
                               ("Configurar…", "__net_config__")):
                if label is None:
                    menu.append(Gtk.SeparatorMenuItem())
                    continue
                mi = Gtk.MenuItem(label=label)
                if cmd == "__net_config__":
                    # abre la ventana propia de configuración de IP (la del clic izq.)
                    mi.connect("activate", lambda _w: self.open_network())
                else:
                    mi.connect("activate", lambda _w, c=cmd: detached_run(c))
                menu.append(mi)
            menu.show_all()
            menu.popup_at_widget(widget, Gdk.Gravity.NORTH, Gdk.Gravity.SOUTH, None)
            return True
        return False

    def _net_state(self):
        try:
            out = subprocess.run(
                ["nmcli", "-t", "-f", "TYPE,STATE", "device", "status"],
                capture_output=True, text=True, timeout=4).stdout
        except Exception:
            return "network-offline-symbolic", "Red: estado desconocido"
        wifi = eth = False
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) < 2:
                continue
            typ, state = parts[0], parts[1]
            if state != "connected":
                continue
            if typ == "wifi":
                wifi = True
            elif typ == "ethernet":
                eth = True
        if eth:
            return "network-wired-symbolic", "Red: cableada conectada"
        if wifi:
            return "network-wireless-signal-good-symbolic", "WiFi conectado"
        return "network-offline-symbolic", "Sin conexión de red"

    def _net_details(self):
        """Lista de conexiones activas: (tipo, nombre/SSID, ip, señal)."""
        rows = []
        try:
            out = subprocess.run(
                ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"],
                capture_output=True, text=True, timeout=4).stdout
        except Exception:
            return rows
        # señal del WiFi en uso
        signal = ""
        try:
            w = subprocess.run(["nmcli", "-t", "-f", "IN-USE,SIGNAL,SSID", "device", "wifi"],
                               capture_output=True, text=True, timeout=4).stdout
            for ln in w.splitlines():
                if ln.startswith("*"):
                    parts = ln.split(":")
                    if len(parts) >= 2:
                        signal = parts[1]
                    break
        except Exception:
            pass
        for line in out.splitlines():
            p = line.split(":")
            if len(p) < 4:
                continue
            dev, typ, state, conn = p[0], p[1], p[2], p[3]
            if typ in ("loopback", "") or state != "connected":
                continue
            ip = ""
            try:
                ipout = subprocess.run(["nmcli", "-g", "IP4.ADDRESS", "device", "show", dev],
                                       capture_output=True, text=True, timeout=4).stdout.strip()
                ip = ipout.split("\n")[0].split("/")[0] if ipout else ""
            except Exception:
                pass
            rows.append((typ, conn or dev, ip, signal if typ == "wifi" else ""))
        return rows

    def _open_net_config(self):
        for cmd in ("nm-connection-editor", "cinnamon-settings network",
                    "gnome-control-center wifi"):
            if cmd_available(cmd):
                detached_run(cmd)
                return
        _error_dialog("No se encontró un configurador de red.")

    def open_network(self, *_):
        if getattr(self, "_netwin", None) is not None:
            self._close_net_win()
            return
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_decorated(False)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        win.set_keep_above(True)
        win.set_resizable(False)
        win.set_size_request(400, 560)
        win.get_style_context().add_class("fp-startmenu")
        win.get_style_context().add_class("fp-navy")   # 1.6.1 (#2698)
        self._net_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        win.add(self._net_content)
        self._netwin = win
        self._wifi_networks = None
        self._net_revelar = []
        self._net_abiertas = set()      # 1.6.7: tarjetas desplegadas (se recuerdan al refrescar)
        self._build_net_ui()
        win.show_all()
        geo = self._geo
        w, h = win.get_size_request()
        if self.edge == "left":
            x, y = geo.x + self.height, geo.y + geo.height - h
        elif self.edge == "right":
            x, y = geo.x + geo.width - self.height - w, geo.y + geo.height - h
        elif self.edge == "top":
            x, y = geo.x + geo.width - w - 4, geo.y + self.height
        else:  # bottom
            x, y = geo.x + geo.width - w - 4, geo.y + geo.height - self.height - h
        win.move(max(geo.x, x), max(geo.y, y))
        win.connect("button-press-event", self._net_click_outside)
        win.connect("key-press-event", self._net_key)
        win.connect("destroy", lambda *_: setattr(self, "_netwin", None))
        GLib.idle_add(self._grab_net_win, win)
        self._wifi_rescan()

    def _section_label(self, text):
        l = Gtk.Label()
        l.set_markup("<small><b>%s</b></small>" % GLib.markup_escape_text(text))
        l.set_xalign(0)
        l.get_style_context().add_class("fp-menu-header")
        return l

    def _build_net_ui(self):
        """Ventana de Red 1.6.5 (#2698): una TARJETA por cada placa de red (cable o WiFi,
        aunque haya varias), cada una con IP Automática/Manual y DNS Automático/Manual
        por separado, + «Usar primero» para elegir cuál manda si hay varias conectadas."""
        box = self._net_content
        for c in box.get_children():
            box.remove(c)
        if hasattr(self, "_wifi_list"):      # la lista vieja se destruyó con la ventana anterior
            del self._wifi_list

        hdr = Gtk.Box(spacing=8)
        hdr.set_border_width(10)
        hdr.get_style_context().add_class("fp-menu-right")
        hdr.pack_start(Gtk.Image.new_from_icon_name("network-workgroup-symbolic",
                                                    Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        t = Gtk.Label()
        t.set_markup("<b><big>Red y WiFi</big></b>")
        t.set_xalign(0)
        hdr.pack_start(t, True, True, 0)
        hdr.pack_start(Gtk.Label(label="WiFi"), False, False, 0)
        self._wifi_switch = Gtk.Switch()
        self._wifi_switch.set_active(self._wifi_enabled())
        self._wifi_switch.set_tooltip_text("Encender / apagar el WiFi")
        self._wifi_switch.connect("notify::active", self._on_wifi_toggle)
        hdr.pack_start(self._wifi_switch, False, False, 0)
        close = Gtk.Button(label="✕")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text("Cerrar")
        close.get_style_context().add_class("fp-cerrar")
        close.connect("clicked", lambda *_: self._close_net_win())
        hdr.pack_end(close, False, False, 0)
        box.pack_start(hdr, False, False, 0)

        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.set_border_width(10)
        sc.add(content)
        box.pack_start(sc, True, True, 0)

        devs = self._net_devices()
        conectadas = [d for d in devs if d["state"] == "connected"]

        # --- tarjetas de red, separadas: primero las de cable (LAN), después las WiFi (1.6.7) ---
        if not devs:
            content.pack_start(Gtk.Label(label="No se encontró ninguna tarjeta de red"), False, False, 6)
        for tipo, titulo in (("ethernet", "Cable (LAN)"), ("wifi", "WiFi")):
            grupo = [d for d in devs if d["type"] == tipo]
            if not grupo:
                continue
            content.pack_start(self._section_label("%s  ·  %d tarjeta%s" % (
                titulo, len(grupo), "" if len(grupo) == 1 else "s")), False, False, 2)
            for d in grupo:
                content.pack_start(self._net_dev_card(d), False, False, 0)

        # --- redes WiFi ---
        if any(d["type"] == "wifi" for d in devs):
            content.pack_start(self._section_label("Redes WiFi disponibles"), False, False, 2)
            scl = Gtk.ScrolledWindow()
            scl.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scl.set_min_content_height(130)
            self._wifi_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            scl.add(self._wifi_list)
            content.pack_start(scl, False, False, 0)
            rb = Gtk.Button(label="Actualizar redes")
            rb.connect("clicked", lambda *_: self._wifi_rescan())
            content.pack_start(rb, False, False, 2)
            self._populate_wifi()

        # --- cuál usar primero ---
        if len(devs) > 1:
            content.pack_start(self._section_label("Usar primero"), False, False, 2)
            pr = Gtk.Box(spacing=6)
            combo = Gtk.ComboBoxText()
            actual = self._net_preferida(devs)
            for i, d in enumerate(devs):
                combo.append(d["dev"], self._net_dev_nombre(d))
                if d["dev"] == actual:
                    combo.set_active(i)
            pr.pack_start(combo, True, True, 0)
            ub = Gtk.Button(label="Aplicar")
            ub.get_style_context().add_class("fp-pri")
            ub.connect("clicked", lambda *_: self._net_set_preferida(combo.get_active_id(), devs))
            pr.pack_start(ub, False, False, 0)
            content.pack_start(pr, False, False, 0)
            h = Gtk.Label()
            h.set_markup("<small>Si hay varias conectadas, esta es la que sale a Internet.</small>")
            h.set_xalign(0)
            content.pack_start(h, False, False, 0)

        if not conectadas:
            st = Gtk.Label()
            st.set_markup("<i>Sin conexión de red</i>")
            content.pack_start(st, False, False, 4)
        box.show_all()
        for r in getattr(self, "_net_revelar", []):
            r()

    def _net_dev_nombre(self, d):
        tipo = "WiFi" if d["type"] == "wifi" else "Cable"
        return "%s · %s" % (tipo, d["dev"])

    def _net_devices(self):
        """Placas de red reales (cable y WiFi): [{dev, type, state, conn}]."""
        devs = []
        try:
            out = subprocess.run(
                ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"],
                capture_output=True, text=True, timeout=4).stdout
        except Exception:
            return devs
        for line in out.splitlines():
            p = line.split(":")
            if len(p) < 4 or p[1] not in ("ethernet", "wifi"):
                continue
            devs.append({"dev": p[0], "type": p[1], "state": p[2].split(" ")[0],
                         "conn": p[3] if p[3] not in ("", "--") else ""})
        return devs

    def _conn_settings(self, conn):
        """Cómo está configurada una conexión guardada (IP y DNS)."""
        r = {"manual": False, "dns_manual": False, "dns": "", "metric": ""}
        if not conn:
            return r
        try:
            out = subprocess.run(
                ["nmcli", "-t", "-f", "ipv4.method,ipv4.ignore-auto-dns,ipv4.dns,ipv4.route-metric",
                 "connection", "show", conn], capture_output=True, text=True, timeout=4).stdout
            for ln in out.splitlines():
                k, _, v = ln.partition(":")
                if k == "ipv4.method":
                    r["manual"] = v.strip() == "manual"
                elif k == "ipv4.ignore-auto-dns":
                    r["dns_manual"] = v.strip() == "yes"
                elif k == "ipv4.dns":
                    r["dns"] = ", ".join(x for x in v.replace(",", " ").split() if x)
                elif k == "ipv4.route-metric":
                    r["metric"] = v.strip()
        except Exception:
            pass
        if r["manual"]:
            r["dns_manual"] = True
        return r

    def _net_dev_card(self, d):
        """Tarjeta de UNA placa: estado + IP Automática/Manual + DNS Automático/Manual."""
        if not hasattr(self, "_net_revelar"):
            self._net_revelar = []
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.get_style_context().add_class("fp-card")
        cfg = self._ip_config(d["dev"]) if d["state"] == "connected" else \
            {"ip": "", "mask": "", "gw": "", "dns": ""}
        st = self._conn_settings(d["conn"])

        top = Gtk.Box(spacing=8)
        ico = "network-wireless-symbolic" if d["type"] == "wifi" else "network-wired-symbolic"
        top.pack_start(Gtk.Image.new_from_icon_name(ico, Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        tl = Gtk.Label()
        estado = ("conectada" if d["state"] == "connected" else
                  "sin cable" if d["state"] == "unavailable" else "desconectada")
        sub = ("%s · IP %s" % (GLib.markup_escape_text(d["conn"] or "sin perfil"), cfg["ip"] or "—")
               if d["state"] == "connected" else estado)
        tl.set_markup("<b>%s</b>\n<small>%s</small>"
                      % (GLib.markup_escape_text(self._net_dev_nombre(d)), sub))
        tl.set_xalign(0)
        top.pack_start(tl, True, True, 0)
        card.pack_start(top, False, False, 0)

        if d["type"] == "wifi" and not d["conn"]:
            n = Gtk.Label()
            n.set_markup("<small>Conectate a una red de la lista de abajo para poder configurarla.</small>")
            n.set_xalign(0)
            n.set_line_wrap(True)
            card.pack_start(n, False, False, 0)
            return card

        def fila(titulo, op_a, op_b, manual):
            fb = Gtk.Box(spacing=6)
            l = Gtk.Label(label=titulo)
            l.set_xalign(0)
            l.set_size_request(46, -1)
            fb.pack_start(l, False, False, 0)
            ra = Gtk.RadioButton.new_with_label(None, op_a)
            rb = Gtk.RadioButton.new_with_label_from_widget(ra, op_b)
            (rb if manual else ra).set_active(True)
            fb.pack_start(ra, False, False, 0)
            fb.pack_start(rb, False, False, 0)
            return fb, ra, rb

        fip, ip_auto, ip_man = fila("IP", "Automática (DHCP)", "Manual", st["manual"])
        card.pack_start(fip, False, False, 0)
        grid = Gtk.Grid()
        grid.set_row_spacing(4)
        grid.set_column_spacing(8)

        def campo(rowi, label, value):
            l = Gtk.Label(label=label)
            l.set_xalign(0)
            e = Gtk.Entry()
            e.set_text(value or "")
            e.set_hexpand(True)
            grid.attach(l, 0, rowi, 1, 1)
            grid.attach(e, 1, rowi, 1, 1)
            return e

        e_ip = campo(0, "IP", cfg["ip"])
        e_mask = campo(1, "Máscara", cfg["mask"] or "24")
        e_gw = campo(2, "Gateway", cfg["gw"])
        card.pack_start(grid, False, False, 0)

        fdns, dns_auto, dns_man = fila("DNS", "Automático", "Manual", st["dns_manual"])
        card.pack_start(fdns, False, False, 0)
        e_dns = Gtk.Entry()
        e_dns.set_text(st["dns"] or cfg["dns"])
        e_dns.set_placeholder_text("ej. 8.8.8.8, 1.1.1.1")
        card.pack_start(e_dns, False, False, 0)
        nota = Gtk.Label()
        nota.set_xalign(0)
        nota.set_line_wrap(True)
        card.pack_start(nota, False, False, 0)

        # 🪤 open_network() hace win.show_all() DESPUÉS de armar esto y volvía a mostrar los
        #    campos escondidos: estos tres los maneja SOLO revelar().
        for w in (grid, e_dns, nota):
            w.set_no_show_all(True)
        for w in grid.get_children():
            w.show()

        def revelar(*_):
            man = ip_man.get_active()
            grid.set_visible(man)
            if man and dns_auto.get_active():
                dns_man.set_active(True)        # IP manual => DNS manual (sin DHCP no hay DNS automático)
            dns_auto.set_sensitive(not man)
            e_dns.set_visible(dns_man.get_active())
            nota.set_markup("<small>Con IP manual el DNS también va manual.</small>" if man else "")
            nota.set_visible(man)
        for w in (ip_auto, ip_man, dns_auto, dns_man):
            w.connect("toggled", revelar)
        self._net_revelar.append(revelar)

        gb = Gtk.Button(label="Guardar %s" % self._net_dev_nombre(d))
        gb.get_style_context().add_class("fp-pri")
        gb.connect("clicked", lambda *_: self._apply_ip_dev(
            d, ip_man.get_active(), e_ip.get_text(), e_mask.get_text(), e_gw.get_text(),
            dns_man.get_active(), e_dns.get_text()))
        card.pack_start(gb, False, False, 2)

        # 1.6.7 (#2698): la tarjeta arranca CERRADA (nombre, estado e IP); un clic en ella
        # despliega la configuración y otro la cierra. Se recuerda cuáles quedaron abiertas.
        cuerpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for ch in card.get_children():
            if ch is not top:
                card.remove(ch)
                cuerpo.pack_start(ch, False, False, 0)
        cuerpo.set_no_show_all(True)
        card.remove(top)
        flecha = Gtk.Label(label="▾" if d["dev"] in self._net_abiertas else "▸")
        top.pack_end(flecha, False, False, 4)
        cab = Gtk.Button()
        cab.set_relief(Gtk.ReliefStyle.NONE)
        cab.get_style_context().add_class("fp-item")
        cab.set_tooltip_text("Clic para ver / ocultar la configuración")
        cab.add(top)
        card.pack_start(cab, False, False, 0)
        card.pack_start(cuerpo, False, False, 0)

        def abrir(mostrar):
            if mostrar:
                cuerpo.show()
                for ch in cuerpo.get_children():
                    ch.show_all()
                revelar()
                self._net_abiertas.add(d["dev"])
            else:
                cuerpo.hide()
                self._net_abiertas.discard(d["dev"])
            flecha.set_text("▾" if mostrar else "▸")

        cab.connect("clicked", lambda *_: abrir(not cuerpo.get_visible()))
        if d["dev"] in self._net_abiertas:
            self._net_revelar.append(lambda: abrir(True))
        return card

    # ----- WiFi (nmcli por dentro) -----
    def _wifi_dev(self):
        try:
            out = subprocess.run(["nmcli", "-t", "-f", "DEVICE,TYPE", "device", "status"],
                                 capture_output=True, text=True, timeout=4).stdout
            for ln in out.splitlines():
                p = ln.split(":")
                if len(p) >= 2 and p[1] == "wifi":
                    return p[0]
        except Exception:
            pass
        return None

    def _wifi_enabled(self):
        try:
            out = subprocess.run(["nmcli", "-t", "-f", "WIFI", "radio"],
                                 capture_output=True, text=True, timeout=4).stdout.strip()
            return out.lower() == "enabled"
        except Exception:
            return False

    def _on_wifi_toggle(self, sw, _p):
        on = sw.get_active()
        try:
            subprocess.Popen(["nmcli", "radio", "wifi", "on" if on else "off"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
        GLib.timeout_add_seconds(2, lambda: (self._wifi_rescan(), False)[1])

    def _wifi_rescan(self):
        if self._wifi_dev() is None:
            self._wifi_networks = []
            self._populate_wifi()
            return

        def work():
            try:
                subprocess.run(["nmcli", "device", "wifi", "rescan"],
                               capture_output=True, timeout=12)
            except Exception:
                pass
            try:
                out = subprocess.run(
                    ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
                    capture_output=True, text=True, timeout=10).stdout
            except Exception:
                out = ""
            nets, seen = [], set()
            for ln in out.splitlines():
                parts = ln.split(":")
                if len(parts) < 4:
                    continue
                inuse, ssid, signal = parts[0], parts[1], parts[2]
                sec = ":".join(parts[3:])
                if not ssid or ssid in seen:
                    continue
                seen.add(ssid)
                nets.append({"ssid": ssid, "signal": signal, "sec": sec,
                             "inuse": inuse.strip() == "*"})
            nets.sort(key=lambda n: (not n["inuse"], -int(n["signal"] or 0)))
            GLib.idle_add(self._set_networks, nets)
        threading.Thread(target=work, daemon=True).start()

    def _set_networks(self, nets):
        self._wifi_networks = nets
        self._populate_wifi()
        return False

    def _populate_wifi(self):
        if not hasattr(self, "_wifi_list"):
            return
        box = self._wifi_list
        for c in box.get_children():
            box.remove(c)
        nets = getattr(self, "_wifi_networks", None)
        if nets is None:
            box.pack_start(Gtk.Label(label="Buscando redes..."), False, False, 6)
        elif not nets:
            box.pack_start(Gtk.Label(label="No hay redes WiFi"), False, False, 6)
        else:
            for n in nets:
                box.pack_start(self._wifi_row(n), False, False, 0)
        box.show_all()

    def _wifi_row(self, n):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.get_style_context().add_class("fp-item")
        row = Gtk.Box(spacing=8)
        sig = int(n["signal"] or 0)
        ico = ("network-wireless-signal-excellent-symbolic" if sig >= 75 else
               "network-wireless-signal-good-symbolic" if sig >= 50 else
               "network-wireless-signal-ok-symbolic" if sig >= 25 else
               "network-wireless-signal-weak-symbolic")
        row.pack_start(Gtk.Image.new_from_icon_name(ico, Gtk.IconSize.MENU), False, False, 0)
        l = Gtk.Label(label=n["ssid"] + ("   ✓ conectado" if n["inuse"] else ""))
        l.set_xalign(0)
        row.pack_start(l, True, True, 0)
        if n["sec"].strip():
            row.pack_start(Gtk.Image.new_from_icon_name(
                "network-wireless-encrypted-symbolic", Gtk.IconSize.MENU), False, False, 0)
        b.add(row)
        b.connect("clicked", lambda *_: self._wifi_clicked(n))
        return b

    def _wifi_clicked(self, n):
        if n["inuse"]:
            return
        if n["sec"].strip():
            self._ask_wifi_password(n)
        else:
            self._do_wifi_connect(n["ssid"], None)

    def _ask_wifi_password(self, n):
        try:
            self._netwin.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        d = Gtk.Dialog(title="Conectar a %s" % n["ssid"],
                       transient_for=self._netwin, modal=True)
        d.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        d.add_button("Conectar", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        ca = d.get_content_area()
        ca.set_border_width(10)
        ca.set_spacing(6)
        ca.add(Gtk.Label(label="Contraseña de %s:" % n["ssid"]))
        e = Gtk.Entry()
        e.set_visibility(False)
        e.set_activates_default(True)
        ca.add(e)
        show = Gtk.CheckButton(label="Mostrar contraseña")
        show.connect("toggled", lambda c: e.set_visibility(c.get_active()))
        ca.add(show)
        d.show_all()
        resp = d.run()
        pwd = e.get_text()
        d.destroy()
        if resp == Gtk.ResponseType.OK and pwd:
            self._do_wifi_connect(n["ssid"], pwd)
        elif getattr(self, "_netwin", None) is not None:
            GLib.idle_add(self._grab_net_win, self._netwin)

    def _do_wifi_connect(self, ssid, pwd):
        self._notify("Conectando a %s..." % ssid)

        def work():
            cmd = ["nmcli", "device", "wifi", "connect", ssid]
            if pwd:
                cmd += ["password", pwd]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
                ok = r.returncode == 0
                msg = ("Conectado a %s" % ssid if ok
                       else (r.stderr.strip() or "No se pudo conectar"))
            except Exception as e:
                ok, msg = False, str(e)
            GLib.idle_add(self._after_netchange, ok, msg)
        threading.Thread(target=work, daemon=True).start()

    # ----- IP fija / DHCP -----
    def _ip_config(self, dev):
        res = {"ip": "", "mask": "", "gw": "", "dns": ""}
        if not dev:
            return res
        try:
            a = subprocess.run(["nmcli", "-g", "IP4.ADDRESS", "device", "show", dev],
                               capture_output=True, text=True, timeout=4).stdout.strip()
            first = a.split("\n")[0] if a else ""
            if "/" in first:
                res["ip"], res["mask"] = first.split("/")[0], first.split("/")[1]
            else:
                res["ip"] = first
            res["gw"] = subprocess.run(["nmcli", "-g", "IP4.GATEWAY", "device", "show", dev],
                                       capture_output=True, text=True, timeout=4).stdout.strip().split("\n")[0]
            dns = subprocess.run(["nmcli", "-g", "IP4.DNS", "device", "show", dev],
                                 capture_output=True, text=True, timeout=4).stdout.strip()
            res["dns"] = ", ".join([x for x in dns.split("\n") if x][:3])
        except Exception:
            pass
        return res

    def _mask_to_prefix(self, m):
        m = (m or "").strip()
        if not m:
            return 24
        if "." not in m:
            try:
                return int(m)
            except Exception:
                return 24
        try:
            return sum(bin(int(o)).count("1") for o in m.split("."))
        except Exception:
            return 24

    def _run_priv(self, args):
        """Corre nmcli; si falla por permisos, reintenta con pkexec (diálogo).
        LC_ALL=C para que el error sea SIEMPRE en inglés (en Debian puro el
        sistema en español decía "no autorizado" y no se detectaba)."""
        env = dict(os.environ, LC_ALL="C")
        try:
            r = subprocess.run(args, capture_output=True, text=True,
                               timeout=45, env=env)
            if r.returncode == 0:
                return True, (r.stdout or "").strip()
            err = (r.stderr or "").strip()
            if any(k in err.lower() for k in (
                    "not authorized", "permission", "insufficient",
                    "privilege", "autoriz", "permis", "insuficiente")):
                if shutil.which("pkexec"):
                    r2 = subprocess.run(["pkexec"] + args, capture_output=True,
                                        text=True, timeout=90, env=env)
                    return r2.returncode == 0, (r2.stderr or r2.stdout or "").strip()
            return False, err
        except Exception as e:
            return False, str(e)

    def _net_ungrab(self):
        try:
            self._netwin.get_display().get_default_seat().ungrab()
        except Exception:
            pass

    def _apply_ip_dev(self, d, manual, ip, mask, gw, dns_manual, dns):
        """Guarda IP (DHCP/manual) y DNS (automático/manual) de UNA placa (1.6.5)."""
        ip, gw = ip.strip(), gw.strip()
        prefix = self._mask_to_prefix(mask)
        dns = " ".join(dns.replace(",", " ").split())
        if manual and not ip:
            self._notify("Escribí la IP para %s" % self._net_dev_nombre(d))
            return
        if (manual or dns_manual) and not dns:
            self._notify("Escribí al menos un DNS (ej. 8.8.8.8)")
            return
        self._net_ungrab()
        self._notify("Guardando %s..." % self._net_dev_nombre(d))

        def work():
            conn = d["conn"]
            if not conn and d["type"] == "ethernet":
                # placa de cable sin perfil: se le crea uno atado a ESA placa
                conn = "Cable %s" % d["dev"]
                ok, msg = self._run_priv(["nmcli", "connection", "add", "type", "ethernet",
                                          "ifname", d["dev"], "con-name", conn])
                if not ok:
                    GLib.idle_add(self._after_netchange, False, msg)
                    return
            args = ["nmcli", "connection", "modify", conn]
            if manual:
                args += ["ipv4.method", "manual", "ipv4.addresses", "%s/%s" % (ip, prefix),
                         "ipv4.gateway", gw]
            else:
                args += ["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", ""]
            if dns_manual or manual:
                args += ["ipv4.dns", dns, "ipv4.ignore-auto-dns", "yes"]
            else:
                args += ["ipv4.dns", "", "ipv4.ignore-auto-dns", "no"]
            ok, msg = self._run_priv(args)
            if ok:
                ok, msg = self._run_priv(["nmcli", "connection", "up", conn, "ifname", d["dev"]])
                if ok:
                    msg = "%s guardada: IP %s · DNS %s" % (
                        self._net_dev_nombre(d), "manual %s/%s" % (ip, prefix) if manual else "automática",
                        "manual" if (dns_manual or manual) else "automático")
            GLib.idle_add(self._after_netchange, ok, msg)
        threading.Thread(target=work, daemon=True).start()

    def _net_preferida(self, devs):
        """La placa que hoy manda: la de menor métrica entre las conectadas."""
        mejor, mejor_m = "", None
        for d in devs:
            if d["state"] != "connected" or not d["conn"]:
                continue
            m = self._conn_settings(d["conn"])["metric"]
            try:
                m = int(m)
            except Exception:
                m = 100 if d["type"] == "ethernet" else 600   # lo que NetworkManager usa por defecto
            if m < 0:
                m = 100 if d["type"] == "ethernet" else 600
            if mejor_m is None or m < mejor_m:
                mejor, mejor_m = d["dev"], m
        return mejor

    def _net_set_preferida(self, dev, devs):
        """«Usar primero»: la elegida métrica 50, las demás 700 (cuanto más baja, más manda)."""
        if not dev:
            return
        self._net_ungrab()
        self._notify("Usando primero %s..." % dev)

        def work():
            ok_all, err = True, ""
            for d in devs:
                if not d["conn"]:
                    continue
                metric = "50" if d["dev"] == dev else "700"
                ok, msg = self._run_priv(["nmcli", "connection", "modify", d["conn"],
                                          "ipv4.route-metric", metric])
                if ok and d["state"] == "connected":
                    ok, msg = self._run_priv(["nmcli", "device", "reapply", d["dev"]])
                if not ok:
                    ok_all, err = False, msg
            GLib.idle_add(self._after_netchange, ok_all,
                          ("Ahora sale primero por %s" % dev) if ok_all else err)
        threading.Thread(target=work, daemon=True).start()

    def _after_netchange(self, ok, msg):
        self._notify(msg or ("Listo" if ok else "Error de red"))
        if getattr(self, "_netwin", None) is not None:
            self._net_revelar = []
            self._build_net_ui()
            GLib.idle_add(self._grab_net_win, self._netwin)
        self._update_net()
        return False

    # ----- ventana de red: grab / cierre -----
    def _grab_net_win(self, win):
        gw = win.get_window()
        if gw is None:
            return False
        try:
            win.get_display().get_default_seat().grab(
                gw, Gdk.SeatCapabilities.ALL, True, None, None, None, None)
        except Exception:
            pass
        return False

    def _net_click_outside(self, win, event):
        a = win.get_allocation()
        if event.x < 0 or event.y < 0 or event.x > a.width or event.y > a.height:
            self._close_net_win()
            return True
        return False

    def _net_key(self, win, event):
        if self._tecla_recorte(event, self._close_net_win):
            return True
        if event.keyval == Gdk.KEY_Escape:
            self._close_net_win()
            return True
        return False

    def _close_net_win(self):
        win = getattr(self, "_netwin", None)
        if win is None:
            return
        try:
            win.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        self._netwin = None
        win.destroy()

    # ---------- calendario + fecha/hora/zona/teclado ----------
    def open_calendar(self, *_):
        if getattr(self, "_calwin", None) is not None:
            self._close_cal_win()
            return
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_decorated(False)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        win.set_keep_above(True)
        win.set_resizable(False)
        win.get_style_context().add_class("fp-startmenu")
        win.get_style_context().add_class("fp-navy")   # 1.6.3 (#2698)
        self._calwin = win

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        win.add(box)

        # Hora grande + fecha en español sobre el degradado (1.6.3)
        reloj = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        reloj.get_style_context().add_class("fp-reloj")
        self._cal_time = Gtk.Label()
        reloj.pack_start(self._cal_time, False, False, 0)
        self._cal_fecha = Gtk.Label()
        reloj.pack_start(self._cal_fecha, False, False, 0)
        box.pack_start(reloj, False, False, 0)

        self._cal = Gtk.Calendar()
        box.pack_start(self._cal, False, False, 0)

        # Hora manual + aplicar
        hb = Gtk.Box(spacing=6)
        hb.pack_start(Gtk.Label(label="Hora:"), False, False, 0)
        self._cal_hh = Gtk.Entry()
        self._cal_hh.set_width_chars(6)
        self._cal_hh.set_max_length(5)
        hb.pack_start(self._cal_hh, False, False, 0)
        apb = Gtk.Button(label="Aplicar fecha y hora")
        apb.get_style_context().add_class("fp-pri")
        apb.connect("clicked", lambda *_: self._apply_datetime())
        hb.pack_start(apb, True, True, 0)
        box.pack_start(hb, False, False, 0)

        # Hora automática (NTP)
        nb = Gtk.Box(spacing=6)
        nb.pack_start(Gtk.Label(label="Hora automática (Internet)"), True, True, 0)
        self._ntp_sw = Gtk.Switch()
        self._ntp_sw.set_active(self._ntp_enabled())
        self._ntp_sw.connect("notify::active", self._on_ntp_toggle)
        nb.pack_start(self._ntp_sw, False, False, 0)
        box.pack_start(nb, False, False, 0)

        box.pack_start(self._section_label("Zona horaria"), False, False, 0)
        self._tz_combo = Gtk.ComboBoxText()
        tzs = self._tz_list()
        cur_tz = self._tz_current()
        for i, tz in enumerate(tzs):
            self._tz_combo.append_text(tz)
            if tz == cur_tz:
                self._tz_combo.set_active(i)
        self._tz_combo.connect("changed", self._on_tz_changed)
        box.pack_start(self._tz_combo, False, False, 0)

        box.pack_start(self._section_label("Distribución del teclado"), False, False, 0)
        self._kbd_combo = Gtk.ComboBoxText()
        cur_kbd = self._kbd_current()
        self._kbd_layouts = [("latam", "Español (Latinoamérica)"),
                             ("es", "Español (España)"),
                             ("us", "Inglés (EE.UU.)")]
        for i, (code, label) in enumerate(self._kbd_layouts):
            self._kbd_combo.append_text(label)
            if code == cur_kbd:
                self._kbd_combo.set_active(i)
        self._kbd_combo.connect("changed", self._on_kbd_changed)
        box.pack_start(self._kbd_combo, False, False, 0)

        cfg = Gtk.Button(label="Configuración completa")
        cfg.connect("clicked", lambda *_: (self._close_cal_win(),
                    detached_run("cinnamon-settings calendar" if cmd_available("cinnamon-settings")
                                 else "gnome-control-center datetime")))
        box.pack_start(cfg, False, False, 4)

        now = datetime.datetime.now()
        self._cal.select_month(now.month - 1, now.year)
        self._cal.select_day(now.day)
        self._cal_hh.set_text(now.strftime("%H:%M"))
        self._cal_tick()

        win.show_all()
        geo = self._geo
        _m, nat = win.get_preferred_size()
        w, h = nat.width, nat.height
        if self.vertical:
            x = (geo.x + self.height) if self.edge == "left" else (geo.x + geo.width - self.height - w)
            y = geo.y + geo.height - h
        else:
            x = geo.x + geo.width - w - 4
            y = geo.y + self.height if self.edge == "top" else geo.y + geo.height - self.height - h
        win.move(max(geo.x, x), max(geo.y, y))
        win.connect("button-press-event", self._cal_click_outside)
        win.connect("key-press-event", self._cal_key)
        win.connect("destroy", lambda *_: setattr(self, "_calwin", None))
        GLib.idle_add(self._grab_cal_win, win)
        GLib.timeout_add_seconds(1, self._cal_tick)

    def _cal_tick(self):
        if getattr(self, "_calwin", None) is None:
            return False
        now = datetime.datetime.now()
        self._cal_time.set_markup("<span size='xx-large'><b>%s</b></span>" % now.strftime("%H:%M:%S"))
        if getattr(self, "_cal_fecha", None) is not None:
            dias = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
            meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                     "agosto", "setiembre", "octubre", "noviembre", "diciembre")
            self._cal_fecha.set_text("%s %d de %s de %d" % (dias[now.weekday()], now.day,
                                                            meses[now.month - 1], now.year))
        return True

    # --- fecha/hora (timedatectl, root vía pkexec) ---
    def _ntp_enabled(self):
        try:
            out = subprocess.run(["timedatectl", "show", "-p", "NTP", "--value"],
                                 capture_output=True, text=True, timeout=4).stdout.strip()
            return out.lower() == "yes"
        except Exception:
            return False

    def _on_ntp_toggle(self, sw, _p):
        on = sw.get_active()
        try:
            self._calwin.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        self._notify("Hora automática " + ("activada" if on else "desactivada"))

        def work():
            ok, msg = self._run_priv(["timedatectl", "set-ntp", "true" if on else "false"])
            GLib.idle_add(self._after_cal, ok, msg)
        threading.Thread(target=work, daemon=True).start()

    def _apply_datetime(self):
        y, mo, d = self._cal.get_date()   # mo es 0-based
        hhmm = self._cal_hh.get_text().strip() or "00:00"
        try:
            hh, mm = hhmm.split(":")[:2]
            stamp = "%04d-%02d-%02d %02d:%02d:00" % (y, mo + 1, d, int(hh), int(mm))
        except Exception:
            self._notify("Hora inválida (usá HH:MM)")
            return
        try:
            self._calwin.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        self._notify("Aplicando %s..." % stamp)

        def work():
            self._run_priv(["timedatectl", "set-ntp", "false"])
            ok, msg = self._run_priv(["timedatectl", "set-time", stamp])
            if ok:
                msg = "Fecha y hora actualizada"
            GLib.idle_add(self._after_cal, ok, msg)
        threading.Thread(target=work, daemon=True).start()

    def _after_cal(self, ok, msg):
        self._notify(msg or ("Listo" if ok else "Error"))
        self._tick()
        if getattr(self, "_calwin", None) is not None:
            GLib.idle_add(self._grab_cal_win, self._calwin)
        return False

    # --- zona horaria ---
    def _tz_list(self):
        try:
            out = subprocess.run(["timedatectl", "list-timezones"],
                                 capture_output=True, text=True, timeout=6).stdout
            return [t for t in out.splitlines() if t]
        except Exception:
            return ["America/Costa_Rica", "UTC"]

    def _tz_current(self):
        try:
            return subprocess.run(["timedatectl", "show", "-p", "Timezone", "--value"],
                                  capture_output=True, text=True, timeout=4).stdout.strip()
        except Exception:
            return ""

    def _on_tz_changed(self, combo):
        tz = combo.get_active_text()
        if not tz:
            return
        try:
            self._calwin.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        self._notify("Zona horaria: %s" % tz)

        def work():
            ok, msg = self._run_priv(["timedatectl", "set-timezone", tz])
            if ok:
                msg = "Zona horaria: %s" % tz
            GLib.idle_add(self._after_cal, ok, msg)
        threading.Thread(target=work, daemon=True).start()

    # --- teclado (setxkbmap, sin root) ---
    def _kbd_current(self):
        try:
            out = subprocess.run(["setxkbmap", "-query"],
                                 capture_output=True, text=True, timeout=4).stdout
            for ln in out.splitlines():
                if ln.startswith("layout:"):
                    return ln.split(":", 1)[1].strip().split(",")[0]
        except Exception:
            pass
        return ""

    def _on_kbd_changed(self, combo):
        idx = combo.get_active()
        if idx < 0 or idx >= len(self._kbd_layouts):
            return
        code = self._kbd_layouts[idx][0]
        try:
            subprocess.Popen(["setxkbmap", code],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._notify("Teclado: %s" % self._kbd_layouts[idx][1])
        except Exception:
            pass

    def _grab_cal_win(self, win):
        gw = win.get_window()
        if gw is None:
            return False
        try:
            win.get_display().get_default_seat().grab(
                gw, Gdk.SeatCapabilities.ALL, True, None, None, None, None)
        except Exception:
            pass
        return False

    def _cal_click_outside(self, win, event):
        a = win.get_allocation()
        if event.x < 0 or event.y < 0 or event.x > a.width or event.y > a.height:
            self._close_cal_win()
            return True
        return False

    def _cal_key(self, win, event):
        if self._tecla_recorte(event, self._close_cal_win):
            return True
        if event.keyval == Gdk.KEY_Escape:
            self._close_cal_win()
            return True
        return False

    def _close_cal_win(self):
        win = getattr(self, "_calwin", None)
        if win is None:
            return
        try:
            win.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        self._calwin = None
        win.destroy()

    # ---------- volumen (salida + micrófono, vía pactl) ----------
    def _pa_get(self, kind):
        """kind='sink' (salida) o 'source' (micrófono) -> (porcentaje, muteado)."""
        dev = "@DEFAULT_SINK@" if kind == "sink" else "@DEFAULT_SOURCE@"
        pct, muted = 0, False
        try:
            m = subprocess.run(["pactl", "get-%s-mute" % kind, dev],
                               capture_output=True, text=True, timeout=3).stdout
            muted = "yes" in m.lower()
            v = subprocess.run(["pactl", "get-%s-volume" % kind, dev],
                               capture_output=True, text=True, timeout=3).stdout
            mm = re.search(r"(\d+)%", v)
            if mm:
                pct = int(mm.group(1))
        except Exception:
            pass
        return pct, muted

    def _pa_set(self, kind, pct):
        dev = "@DEFAULT_SINK@" if kind == "sink" else "@DEFAULT_SOURCE@"
        try:
            subprocess.Popen(["pactl", "set-%s-volume" % kind, dev, "%d%%" % pct],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _pa_mute(self, kind):
        dev = "@DEFAULT_SINK@" if kind == "sink" else "@DEFAULT_SOURCE@"
        try:
            subprocess.run(["pactl", "set-%s-mute" % kind, dev, "toggle"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        except Exception:
            pass

    def _vol_icon(self, pct, muted):
        if muted or pct == 0:
            return "audio-volume-muted-symbolic"
        if pct < 34:
            return "audio-volume-low-symbolic"
        if pct < 67:
            return "audio-volume-medium-symbolic"
        return "audio-volume-high-symbolic"

    def _update_vol(self):
        pct, muted = self._pa_get("sink")
        pb = icono_estado("mute" if (muted or pct == 0) else "vol",
                          1 if pct < 34 else 2 if pct < 67 else 3)
        if pb is not None:
            self.vol_img.set_from_pixbuf(pb)
        else:
            self.vol_img.set_from_icon_name(self._vol_icon(pct, muted), Gtk.IconSize.LARGE_TOOLBAR)
        self.vol_btn.set_tooltip_text(
            "Volumen: %d%%%s" % (pct, "  (silenciado)" if muted else ""))
        return True

    def open_volume(self, *_):
        if getattr(self, "_volwin", None) is not None:
            self._close_vol_win()
            return
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_decorated(False)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        win.set_keep_above(True)
        win.set_resizable(False)
        win.get_style_context().add_class("fp-startmenu")
        win.get_style_context().add_class("fp-navy")   # 1.6.2 (#2698)
        self._volwin = win

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(12)
        win.add(box)

        hdr = Gtk.Box(spacing=8)
        hdr.get_style_context().add_class("fp-menu-right")
        hdr.set_border_width(8)
        hdr.pack_start(Gtk.Image.new_from_icon_name("audio-volume-high-symbolic",
                                                    Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        ht = Gtk.Label()
        ht.set_markup("<b><big>Sonido</big></b>")
        ht.set_xalign(0)
        hdr.pack_start(ht, True, True, 0)
        closeb = Gtk.Button(label="✕")
        closeb.set_relief(Gtk.ReliefStyle.NONE)
        closeb.set_tooltip_text("Cerrar")
        closeb.get_style_context().add_class("fp-cerrar")
        closeb.connect("clicked", lambda *_: self._close_vol_win())
        hdr.pack_end(closeb, False, False, 0)
        box.pack_start(hdr, False, False, 0)
        box.pack_start(Gtk.Separator(), False, False, 2)

        cols = Gtk.Box(spacing=18)
        cols.set_halign(Gtk.Align.CENTER)
        cols.pack_start(self._vol_col("Salida", "sink"), False, False, 0)
        cols.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 0)
        cols.pack_start(self._vol_col("Micrófono", "source"), False, False, 0)
        box.pack_start(cols, True, True, 0)

        # Selector de tarjeta de salida (solo si hay mas de un dispositivo).
        sinks = self._pa_sinks()
        if len(sinks) > 1:
            box.pack_start(Gtk.Separator(), False, False, 2)
            box.pack_start(self._section_label("Tarjeta de salida"), False, False, 0)
            combo = Gtk.ComboBoxText()
            cur = self._pa_default_sink()
            active = 0
            for i, (nm, desc) in enumerate(sinks):
                combo.append(nm, desc)
                if nm == cur:
                    active = i
            combo.set_active(active)
            combo.connect("changed", self._on_sink_changed)
            box.pack_start(combo, False, False, 0)

        cfg = Gtk.Button(label="Configuración de sonido")
        cfg.connect("clicked", lambda *_: (self._close_vol_win(),
                    detached_run("cinnamon-settings sound" if cmd_available("cinnamon-settings")
                                 else "pavucontrol")))
        box.pack_start(cfg, False, False, 4)

        win.show_all()
        geo = self._geo
        _m, nat = win.get_preferred_size()
        w, h = nat.width, nat.height
        if self.vertical:
            x = (geo.x + self.height) if self.edge == "left" else (geo.x + geo.width - self.height - w)
            y = geo.y + geo.height - h
        else:
            x = geo.x + geo.width - w - 4
            y = geo.y + self.height if self.edge == "top" else geo.y + geo.height - self.height - h
        win.move(max(geo.x, x), max(geo.y, y))
        win.connect("button-press-event", self._vol_click_outside)
        win.connect("key-press-event", self._vol_key)
        win.connect("destroy", lambda *_: setattr(self, "_volwin", None))
        GLib.idle_add(self._grab_vol_win, win)

    def _vol_col(self, titulo, kind):
        """Columna de volumen VERTICAL (barra hacia arriba) + icono mute abajo."""
        pct, muted = self._pa_get(kind)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        col.set_halign(Gtk.Align.CENTER)
        col.pack_start(self._section_label(titulo), False, False, 0)
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0, 100, 1)
        sc.set_inverted(True)        # arriba = mas volumen
        sc.set_value(pct)
        sc.set_vexpand(True)
        sc.set_size_request(-1, 170)
        sc.set_draw_value(True)
        sc.set_value_pos(Gtk.PositionType.BOTTOM)
        sc.connect("value-changed", lambda s: self._pa_set(kind, int(s.get_value())))
        col.pack_start(sc, True, True, 0)
        mb = Gtk.Button()
        mb.set_relief(Gtk.ReliefStyle.NONE)
        mimg = Gtk.Image.new_from_icon_name(self._vol_icon(pct, muted), Gtk.IconSize.LARGE_TOOLBAR)
        mb.add(mimg)
        mb.set_tooltip_text("Silenciar / activar")
        mb.connect("clicked", lambda *_: (self._pa_mute(kind),
                   mimg.set_from_icon_name(self._vol_icon(int(sc.get_value()),
                                           self._pa_get(kind)[1]), Gtk.IconSize.LARGE_TOOLBAR),
                   self._update_vol()))
        col.pack_start(mb, False, False, 0)
        return col

    def _pa_sinks(self):
        """Lista [(name, descripcion)] de las salidas de sonido."""
        sinks = []
        try:
            out = subprocess.run(["pactl", "list", "sinks"],
                                 capture_output=True, text=True, timeout=4).stdout
            name = None
            for ln in out.splitlines():
                s = ln.strip()
                if s.startswith("Name:"):
                    name = s.split(":", 1)[1].strip()
                elif s.startswith("Description:") and name:
                    sinks.append((name, s.split(":", 1)[1].strip() or name))
                    name = None
        except Exception:
            pass
        return sinks

    def _pa_default_sink(self):
        try:
            return subprocess.run(["pactl", "get-default-sink"],
                                  capture_output=True, text=True, timeout=3).stdout.strip()
        except Exception:
            return ""

    def _on_sink_changed(self, combo):
        name = combo.get_active_id()
        if not name:
            return
        try:
            subprocess.run(["pactl", "set-default-sink", name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            # mover los streams que estan sonando al nuevo dispositivo
            out = subprocess.run(["pactl", "list", "short", "sink-inputs"],
                                 capture_output=True, text=True, timeout=3).stdout
            for ln in out.splitlines():
                sid = ln.split("\t")[0].strip() if ln.strip() else ""
                if sid:
                    subprocess.run(["pactl", "move-sink-input", sid, name],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        except Exception:
            pass
        self._update_vol()

    def _grab_vol_win(self, win):
        gw = win.get_window()
        if gw is None:
            return False
        try:
            win.get_display().get_default_seat().grab(
                gw, Gdk.SeatCapabilities.ALL, True, None, None, None, None)
        except Exception:
            pass
        return False

    def _vol_click_outside(self, win, event):
        a = win.get_allocation()
        if event.x < 0 or event.y < 0 or event.x > a.width or event.y > a.height:
            self._close_vol_win()
            return True
        return False

    def _vol_key(self, win, event):
        if self._tecla_recorte(event, self._close_vol_win):
            return True
        if event.keyval == Gdk.KEY_Escape:
            self._close_vol_win()
            return True
        return False

    def _close_vol_win(self):
        win = getattr(self, "_volwin", None)
        if win is None:
            return
        try:
            win.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        self._volwin = None
        win.destroy()

    # ---------- Bluetooth (1.7.0, #2942) ----------
    # Propio, como Sonido y Red: reemplaza el applet del sistema (blueman-applet) y llega
    # solo con el auto-update de la barra. Todo por `bluetoothctl` (paquete bluez), siempre
    # en un hilo: si bluetoothd no responde, la barra NO se traba.
    def _bt_hay_adaptador(self):
        try:
            return any(n.startswith("hci") for n in os.listdir("/sys/class/bluetooth"))
        except Exception:
            return False

    def _btctl(self, *args, timeout=6):
        if not shutil.which("bluetoothctl"):
            return ""
        try:
            # 🪤 LC_ALL=C: se parsea el texto (la misma trampa de «Candidato:» del #2831)
            return subprocess.run(["bluetoothctl"] + list(args), capture_output=True, text=True,
                                  timeout=timeout, stdin=subprocess.DEVNULL,
                                  env=dict(os.environ, LC_ALL="C")).stdout
        except Exception:
            return ""

    def _bt_lista(self, salida):
        """'Device AA:BB:.. Nombre' -> [(mac, nombre)]"""
        res = []
        for ln in salida.splitlines():
            m = re.match(r"\s*Device\s+([0-9A-F:]{17})\s*(.*)$", ln.strip(), re.I)
            if m:
                res.append((m.group(1).upper(), m.group(2).strip()))
        return res

    def _bt_info(self, mac):
        d = {"mac": mac, "name": mac, "paired": False, "connected": False,
             "icon": "", "battery": None}
        for ln in self._btctl("info", mac).splitlines():
            s = ln.strip()
            k, _, v = s.partition(":")
            v = v.strip()
            if k == "Alias" or (k == "Name" and d["name"] == mac):
                d["name"] = v or d["name"]
            elif k == "Paired":
                d["paired"] = v == "yes"
            elif k == "Connected":
                d["connected"] = v == "yes"
            elif k == "Icon":
                d["icon"] = v
            elif k == "Battery Percentage":
                m = re.search(r"\((\d+)\)", v)
                if m:
                    d["battery"] = int(m.group(1))
        return d

    def _bt_estado(self):
        """{'hay': adaptador, 'on': encendido, 'devs': [info de los vinculados]}"""
        if not self._bt_hay_adaptador() or not shutil.which("bluetoothctl"):
            return {"hay": False, "on": False, "devs": []}
        show = self._btctl("show")
        on = bool(re.search(r"^\s*Powered:\s*yes", show, re.M))
        pares = self._bt_lista(self._btctl("devices", "Paired"))
        if not pares:   # bluez viejo (< 5.65) no entiende «devices Paired»
            pares = self._bt_lista(self._btctl("paired-devices"))
        devs = [self._bt_info(mac) for mac, _n in pares]
        return {"hay": bool(show.strip()), "on": on, "devs": devs}

    def _update_bt(self):
        if not getattr(self, "_bt_leyendo", False):
            self._bt_leyendo = True

            def work():
                try:
                    est = self._bt_estado()
                finally:
                    self._bt_leyendo = False
                GLib.idle_add(self._bt_pintar, est)
            threading.Thread(target=work, daemon=True).start()
        return True

    def _bt_pintar(self, est):
        self._bt_ultimo = est
        if not est["hay"]:
            self.bt_btn.hide()       # PC sin Bluetooth: como Windows, no hay ícono
            return False
        con = [d["name"] for d in est["devs"] if d["connected"]]
        pb = icono_estado("bt" if est["on"] else "btoff")
        if pb is not None:
            self.bt_img.set_from_pixbuf(pb)
        else:
            self.bt_img.set_from_icon_name(
                "bluetooth-active-symbolic" if est["on"] else "bluetooth-disabled-symbolic",
                Gtk.IconSize.LARGE_TOOLBAR)
        if not est["on"]:
            tip = "Bluetooth: apagado"
        elif con:
            tip = "Bluetooth: conectado a " + ", ".join(con)
        else:
            tip = "Bluetooth: encendido, sin dispositivos conectados"
        self.bt_btn.set_tooltip_text(tip)
        self.bt_img.show()
        self.bt_btn.show()       # 🪤 show_all() no hace nada con set_no_show_all(True)
        if getattr(self, "_btwin", None) is not None and not getattr(self, "_bt_ocupado", False):
            if self._bt_firma(est) != getattr(self, "_bt_firma_ui", None):
                self._build_bt_ui(est)
        return False

    @staticmethod
    def _bt_firma(est):
        return (est["on"], tuple((d["mac"], d["connected"], d["battery"]) for d in est["devs"]))

    def _bt_ocultar_applet_sistema(self):
        """El ícono de Bluetooth del sistema (blueman-applet) sobra: la barra ya tiene el suyo.
        Se apaga SOLO para este usuario (autostart con Hidden=true, sin root) y se cierra."""
        if not shutil.which("bluetoothctl"):
            return False      # sin bluez nuestra ventana no sirve: se deja el del sistema
        try:
            dst = os.path.expanduser("~/.config/autostart")
            for f in os.listdir("/etc/xdg/autostart"):
                src = os.path.join("/etc/xdg/autostart", f)
                try:
                    txt = open(src, encoding="utf-8", errors="replace").read()
                except Exception:
                    continue
                if "blueman-applet" not in txt:
                    continue
                os.makedirs(dst, exist_ok=True)
                out = os.path.join(dst, f)
                if os.path.exists(out) and "Hidden=true" in open(out, encoding="utf-8",
                                                                 errors="replace").read():
                    continue
                with open(out, "w", encoding="utf-8") as fh:
                    fh.write("[Desktop Entry]\nType=Application\nName=Blueman Applet\n"
                             "Exec=blueman-applet\nHidden=true\n"
                             "# FactuPOS: la barra tiene su propio Bluetooth (#2942)\n")
            subprocess.run(["pkill", "-f", "bin/blueman-applet"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception as e:
            sys.stderr.write("bt: no se pudo ocultar blueman-applet: %s\n" % e)
        return False

    def open_bluetooth(self, *_):
        if getattr(self, "_btwin", None) is not None:
            self._close_bt_win()
            return
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_decorated(False)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        win.set_keep_above(True)
        win.set_resizable(False)
        win.set_size_request(380, 480)
        win.get_style_context().add_class("fp-startmenu")
        win.get_style_context().add_class("fp-navy")
        self._bt_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        win.add(self._bt_content)
        self._btwin = win
        self._bt_cerca = None          # None = no se buscó · [] = se buscó y no hay
        self._bt_msg = ""
        self._bt_confirmar = None      # mac que pidió «Quitar» (2do clic confirma)
        self._build_bt_ui(getattr(self, "_bt_ultimo", None) or self._bt_estado())
        win.show_all()
        geo = self._geo
        w, h = win.get_size_request()
        if self.edge == "left":
            x, y = geo.x + self.height, geo.y + geo.height - h
        elif self.edge == "right":
            x, y = geo.x + geo.width - self.height - w, geo.y + geo.height - h
        elif self.edge == "top":
            x, y = geo.x + geo.width - w - 4, geo.y + self.height
        else:  # bottom
            x, y = geo.x + geo.width - w - 4, geo.y + geo.height - self.height - h
        win.move(max(geo.x, x), max(geo.y, y))
        win.connect("button-press-event", self._bt_click_outside)
        win.connect("key-press-event", self._bt_key)
        win.connect("destroy", lambda *_: setattr(self, "_btwin", None))
        GLib.idle_add(self._grab_net_win, win)

    def _build_bt_ui(self, est):
        box = self._bt_content
        for c in box.get_children():
            box.remove(c)
        self._bt_firma_ui = self._bt_firma(est)

        hdr = Gtk.Box(spacing=8)
        hdr.set_border_width(10)
        hdr.get_style_context().add_class("fp-menu-right")
        pb = icono_estado("bt" if est["on"] else "btoff")
        hdr.pack_start(Gtk.Image.new_from_pixbuf(pb) if pb is not None else
                       Gtk.Image.new_from_icon_name("bluetooth-symbolic", Gtk.IconSize.LARGE_TOOLBAR),
                       False, False, 0)
        t = Gtk.Label()
        t.set_markup("<b><big>Bluetooth</big></b>")
        t.set_xalign(0)
        hdr.pack_start(t, True, True, 0)
        sw = Gtk.Switch()
        sw.set_active(est["on"])
        sw.set_sensitive(est["hay"])
        sw.set_valign(Gtk.Align.CENTER)
        sw.set_tooltip_text("Encender / apagar el Bluetooth")
        sw.connect("notify::active", self._bt_on_switch)
        hdr.pack_start(sw, False, False, 0)
        close = Gtk.Button(label="✕")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text("Cerrar")
        close.get_style_context().add_class("fp-cerrar")
        close.connect("clicked", lambda *_: self._close_bt_win())
        hdr.pack_end(close, False, False, 0)
        box.pack_start(hdr, False, False, 0)

        sc = Gtk.ScrolledWindow()
        sc.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.set_border_width(10)
        sc.add(content)
        box.pack_start(sc, True, True, 0)

        def nota(txt):
            l = Gtk.Label()
            l.set_markup("<i>%s</i>" % GLib.markup_escape_text(txt))
            l.set_line_wrap(True)
            l.set_xalign(0)
            content.pack_start(l, False, False, 6)

        if not est["hay"]:
            nota("Este equipo no tiene Bluetooth (o está desactivado en la BIOS).")
        elif not est["on"]:
            nota("El Bluetooth está apagado. Encendelo con el interruptor de arriba.")
        else:
            content.pack_start(self._section_label("Mis dispositivos"), False, False, 2)
            if not est["devs"]:
                nota("Todavía no hay dispositivos vinculados. Tocá «Buscar dispositivos».")
            for d in sorted(est["devs"], key=lambda d: (not d["connected"], d["name"].lower())):
                content.pack_start(self._bt_fila(d, vinculado=True), False, False, 0)

            content.pack_start(self._section_label("Otros dispositivos cerca"), False, False, 2)
            ya = {d["mac"] for d in est["devs"]}
            cerca = getattr(self, "_bt_cerca", None)
            if cerca is None:
                nota("Prendé el dispositivo, ponelo en modo vincular y tocá «Buscar dispositivos».")
            else:
                otros = [d for d in cerca if d["mac"] not in ya]
                if not otros:
                    nota("No se encontraron dispositivos nuevos.")
                for d in otros:
                    content.pack_start(self._bt_fila(d, vinculado=False), False, False, 0)
            bb = Gtk.Button(label="Buscando…" if getattr(self, "_bt_buscando", False)
                            else "Buscar dispositivos")
            bb.set_sensitive(not getattr(self, "_bt_buscando", False))
            bb.connect("clicked", lambda *_: self._bt_buscar())
            content.pack_start(bb, False, False, 4)

        if getattr(self, "_bt_msg", ""):
            m = Gtk.Label()
            m.set_markup("<small>%s</small>" % GLib.markup_escape_text(self._bt_msg))
            m.set_line_wrap(True)
            m.set_xalign(0)
            content.pack_start(m, False, False, 4)

        if shutil.which("blueman-manager"):
            cfg = Gtk.Button(label="Configuración avanzada")
            cfg.connect("clicked", lambda *_: (self._close_bt_win(), detached_run("blueman-manager")))
            box.pack_end(cfg, False, False, 8)
        box.show_all()

    def _bt_icono(self, d):
        ic = d.get("icon") or ""
        for clave, nombre in (("headset", "audio-headset"), ("headphone", "audio-headphones"),
                              ("audio", "audio-speakers"), ("mouse", "input-mouse"),
                              ("keyboard", "input-keyboard"), ("phone", "phone"),
                              ("printer", "printer"), ("computer", "computer"),
                              ("gaming", "input-gaming"), ("input", "input-tablet")):
            if clave in ic:
                return nombre
        return "bluetooth"

    def _bt_fila(self, d, vinculado):
        row = Gtk.Box(spacing=8)
        row.get_style_context().add_class("fp-item")
        row.set_border_width(4)
        row.pack_start(Gtk.Image.new_from_icon_name(self._bt_icono(d), Gtk.IconSize.LARGE_TOOLBAR),
                       False, False, 0)
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        n = Gtk.Label(label=d["name"])
        n.set_xalign(0)
        n.set_ellipsize(Pango.EllipsizeMode.END)
        n.set_max_width_chars(22)
        txt.pack_start(n, False, False, 0)
        if vinculado:
            est = "Conectado" if d["connected"] else "No conectado"
            if d.get("battery") is not None:
                est += " · batería %d%%" % d["battery"]
            s = Gtk.Label()
            s.set_markup("<small>%s</small>" % est)
            s.set_xalign(0)
            txt.pack_start(s, False, False, 0)
        row.pack_start(txt, True, True, 0)
        ocupado = getattr(self, "_bt_ocupado", False)
        if vinculado:
            if self._bt_confirmar == d["mac"]:
                q = Gtk.Button(label="¿Quitar?")
                q.get_style_context().add_class("fp-pri")
                q.set_tooltip_text("Tocá otra vez para olvidar este dispositivo")
                q.connect("clicked", lambda *_: self._bt_accion("quitar", d))
            else:
                q = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
                q.set_relief(Gtk.ReliefStyle.NONE)
                q.set_tooltip_text("Quitar (olvidar) este dispositivo")
                q.connect("clicked", lambda *_: self._bt_pedir_quitar(d))
            q.set_sensitive(not ocupado)
            row.pack_end(q, False, False, 0)
            b = Gtk.Button(label="Desconectar" if d["connected"] else "Conectar")
            if not d["connected"]:
                b.get_style_context().add_class("fp-pri")
            b.connect("clicked", lambda *_: self._bt_accion(
                "desconectar" if d["connected"] else "conectar", d))
        else:
            b = Gtk.Button(label="Vincular")
            b.get_style_context().add_class("fp-pri")
            b.connect("clicked", lambda *_: self._bt_accion("vincular", d))
        b.set_sensitive(not ocupado)
        b.set_valign(Gtk.Align.CENTER)
        row.pack_end(b, False, False, 0)
        return row

    def _bt_pedir_quitar(self, d):
        self._bt_confirmar = d["mac"]
        self._build_bt_ui(getattr(self, "_bt_ultimo", None) or self._bt_estado())

    def _bt_refrescar(self, msg=None):
        """Relee el estado en un hilo y rearma la ventana (y el ícono)."""
        if msg is not None:
            self._bt_msg = msg

        def work():
            est = self._bt_estado()
            GLib.idle_add(self._bt_refrescar_ui, est)
        threading.Thread(target=work, daemon=True).start()

    def _bt_refrescar_ui(self, est):
        self._bt_ultimo = est
        self._bt_pintar(est)
        if getattr(self, "_btwin", None) is not None:
            self._build_bt_ui(est)
        return False

    def _bt_on_switch(self, sw, _p):
        on = sw.get_active()
        if on == bool((getattr(self, "_bt_ultimo", None) or {}).get("on")):
            return

        def work():
            if on:
                subprocess.run(["rfkill", "unblock", "bluetooth"], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=5) if shutil.which("rfkill") else None
            self._btctl("power", "on" if on else "off")
            time.sleep(1)
            est = self._bt_estado()
            if on and not est["on"]:
                self._bt_msg = "No se pudo encender el Bluetooth (puede estar apagado con una tecla del equipo)."
            else:
                self._bt_msg = ""
            GLib.idle_add(self._bt_refrescar_ui, est)
        threading.Thread(target=work, daemon=True).start()

    def _bt_buscar(self):
        if getattr(self, "_bt_buscando", False):
            return
        self._bt_buscando = True
        self._bt_msg = "Buscando dispositivos cerca (unos 12 segundos)…"
        self._build_bt_ui(getattr(self, "_bt_ultimo", None) or self._bt_estado())

        def work():
            try:
                self._btctl("--timeout", "12", "scan", "on", timeout=20)
                encontrados = []
                for mac, nombre in self._bt_lista(self._btctl("devices")):
                    # sin nombre (solo la MAC) = basura de alrededor: no se muestra
                    if not nombre or re.match(r"^([0-9A-F]{2}[-:]){5}[0-9A-F]{2}$", nombre, re.I):
                        continue
                    encontrados.append({"mac": mac, "name": nombre, "icon": "", "battery": None,
                                        "paired": False, "connected": False})
                self._bt_cerca = encontrados
            finally:
                self._bt_buscando = False
            self._bt_refrescar("")
        threading.Thread(target=work, daemon=True).start()

    def _bt_accion(self, que, d):
        if getattr(self, "_bt_ocupado", False):
            return
        self._bt_ocupado = True
        self._bt_confirmar = None
        nombre = d["name"]
        self._bt_msg = {"conectar": "Conectando %s…", "desconectar": "Desconectando %s…",
                        "quitar": "Quitando %s…", "vincular": "Vinculando %s… (aceptá en el "
                        "dispositivo si lo pide)"}[que] % nombre
        self._build_bt_ui(getattr(self, "_bt_ultimo", None) or self._bt_estado())
        mac = d["mac"]

        def work():
            msg = ""
            try:
                if que == "conectar":
                    self._btctl("connect", mac, timeout=25)
                    ok = self._bt_info(mac)["connected"]
                    msg = ("%s quedó conectado." if ok else
                           "No se pudo conectar %s: revisá que esté prendido y cerca.") % nombre
                elif que == "desconectar":
                    self._btctl("disconnect", mac, timeout=15)
                    msg = "%s quedó desconectado." % nombre
                elif que == "quitar":
                    self._btctl("remove", mac, timeout=15)
                    msg = "%s se quitó. Para usarlo otra vez hay que vincularlo." % nombre
                else:   # vincular: sin pedir códigos (la mayoría: parlantes, audífonos, mouse)
                    self._btctl("--agent", "NoInputNoOutput", "pair", mac, timeout=40)
                    info = self._bt_info(mac)
                    if info["paired"]:
                        self._btctl("trust", mac)
                        self._btctl("connect", mac, timeout=25)
                        msg = "%s quedó vinculado." % nombre
                        if self._bt_cerca:
                            self._bt_cerca = [x for x in self._bt_cerca if x["mac"] != mac]
                    else:
                        msg = ("No se pudo vincular %s. Ponelo en modo vincular y probá otra vez; "
                               "si pide un código, usá «Configuración avanzada»." % nombre)
            finally:
                self._bt_ocupado = False
            self._bt_refrescar(msg)
        threading.Thread(target=work, daemon=True).start()

    def _bt_click_outside(self, win, event):
        a = win.get_allocation()
        if event.x < 0 or event.y < 0 or event.x > a.width or event.y > a.height:
            self._close_bt_win()
            return True
        return False

    def _bt_key(self, win, event):
        if self._tecla_recorte(event, self._close_bt_win):
            return True
        if event.keyval == Gdk.KEY_Escape:
            self._close_bt_win()
            return True
        return False

    def _close_bt_win(self):
        win = getattr(self, "_btwin", None)
        if win is None:
            return
        try:
            win.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        self._btwin = None
        win.destroy()

    # ---------- Equipo (info del sistema) ----------
    def _os_pretty(self):
        try:
            with open("/etc/os-release") as f:
                for ln in f:
                    if ln.startswith("PRETTY_NAME="):
                        return ln.split("=", 1)[1].strip().strip('"')
        except Exception:
            pass
        return "Linux"

    def _ram_info(self):
        total = avail = 0
        try:
            with open("/proc/meminfo") as f:
                for ln in f:
                    if ln.startswith("MemTotal:"):
                        total = int(ln.split()[1])
                    elif ln.startswith("MemAvailable:"):
                        avail = int(ln.split()[1])
        except Exception:
            pass
        g = 1048576.0
        return total / g, (total - avail) / g, avail / g   # total, usado, libre (GB)

    def _disks(self):
        out = []
        try:
            r = subprocess.run(
                ["df", "-h", "--output=source,target,size,used,avail,pcent",
                 "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs", "-x", "overlay"],
                capture_output=True, text=True, timeout=5).stdout
            for ln in r.splitlines()[1:]:
                p = ln.split()
                if len(p) >= 6 and p[0].startswith("/dev"):
                    out.append(tuple(p[:6]))
        except Exception:
            pass
        return out

    def _open_system_update(self):
        for cmd in ("mintupdate", "update-manager", "gnome-software --mode=updates", "pkupdate"):
            if cmd_available(cmd):
                detached_run(cmd)
                return
        detached_run("x-terminal-emulator -e sh -c "
                     "'sudo apt update; sudo apt full-upgrade; echo; echo Listo; read x'")

    def open_equipo(self, *_):
        if getattr(self, "_eqwin", None) is not None:
            self._close_eq_win()
            return
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_decorated(False)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        win.set_keep_above(True)
        win.set_resizable(False)
        win.set_size_request(440, -1)
        win.get_style_context().add_class("fp-startmenu")
        self._eqwin = win

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(14)
        win.add(box)

        head = Gtk.Box(spacing=10)
        head.pack_start(Gtk.Image.new_from_icon_name("computer", Gtk.IconSize.DIALOG), False, False, 0)
        ht = Gtk.Label()
        ht.set_markup("<span size='large'><b>Equipo</b></span>")
        ht.set_xalign(0)
        head.pack_start(ht, True, True, 0)
        box.pack_start(head, False, False, 4)
        box.pack_start(Gtk.Separator(), False, False, 4)

        nb = Gtk.Box(spacing=8)
        nl = Gtk.Label()
        nl.set_markup("Nombre del equipo:  <b>%s</b>" % GLib.markup_escape_text(socket.gethostname()))
        nl.set_xalign(0)
        nb.pack_start(nl, True, True, 0)
        cb = Gtk.Button(label="Cambiar nombre")
        cb.connect("clicked", lambda *_: self._change_hostname())
        nb.pack_start(cb, False, False, 0)
        box.pack_start(nb, False, False, 0)

        sl = Gtk.Label()
        sl.set_markup("Sistema:  <b>%s</b>" % GLib.markup_escape_text(self._os_pretty()))
        sl.set_xalign(0)
        box.pack_start(sl, False, False, 0)
        kl = Gtk.Label()
        kl.set_markup("Kernel:  <b>%s</b>" % GLib.markup_escape_text(os.uname().release))
        kl.set_xalign(0)
        box.pack_start(kl, False, False, 0)

        total, used, free = self._ram_info()
        rl = Gtk.Label()
        rl.set_markup("Memoria RAM:  total <b>%.1f GB</b> · en uso <b>%.1f GB</b> · libre <b>%.1f GB</b>"
                      % (total, used, free))
        rl.set_xalign(0)
        box.pack_start(rl, False, False, 0)

        box.pack_start(self._section_label("Espacio en discos"), False, False, 4)
        for src, tgt, size, used_d, avail, pct in self._disks():
            dl = Gtk.Label()
            dl.set_markup("<b>%s</b> (%s):  total %s · usado %s · libre %s  (%s)"
                          % (GLib.markup_escape_text(tgt), GLib.markup_escape_text(src),
                             size, used_d, avail, pct))
            dl.set_xalign(0)
            box.pack_start(dl, False, False, 0)

        box.pack_start(Gtk.Separator(), False, False, 6)
        btns = Gtk.Box(spacing=6)
        ub = Gtk.Button(label="Buscar actualizaciones del sistema")
        ub.connect("clicked", lambda *_: (self._close_eq_win(), self._open_system_update()))
        btns.pack_start(ub, True, True, 0)
        fb = Gtk.Button(label="Explorar archivos")
        fb.connect("clicked", lambda *_: (self._close_eq_win(),
                   detached_run("nemo computer:///" if cmd_available("nemo") else "xdg-open computer:///")))
        btns.pack_start(fb, False, False, 0)
        box.pack_start(btns, False, False, 0)

        win.show_all()
        geo = self._geo
        _m, nat = win.get_preferred_size()
        w, h = nat.width, nat.height
        x = geo.x + (geo.width - w) // 2
        y = geo.y + (geo.height - h) // 2
        win.move(max(geo.x, x), max(geo.y, y))
        win.connect("button-press-event", self._eq_click_outside)
        win.connect("key-press-event", self._eq_key)
        win.connect("destroy", lambda *_: setattr(self, "_eqwin", None))
        GLib.idle_add(self._grab_eq_win, win)

    def _change_hostname(self):
        try:
            self._eqwin.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        d = Gtk.Dialog(title="Cambiar nombre del equipo", transient_for=self._eqwin, modal=True)
        d.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        d.add_button("Aplicar", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        ca = d.get_content_area()
        ca.set_border_width(10)
        ca.set_spacing(6)
        ca.add(Gtk.Label(label="Nuevo nombre del equipo (sin espacios):"))
        e = Gtk.Entry()
        e.set_text(socket.gethostname())
        e.set_activates_default(True)
        ca.add(e)
        d.show_all()
        resp = d.run()
        name = re.sub(r"[^A-Za-z0-9-]", "-", e.get_text().strip())
        d.destroy()
        if resp == Gtk.ResponseType.OK and name and name != socket.gethostname():
            self._notify("Cambiando nombre del equipo a %s..." % name)

            def work():
                ok, msg = self._run_priv(["hostnamectl", "set-hostname", name])
                GLib.idle_add(self._after_hostname, ok, msg)
            threading.Thread(target=work, daemon=True).start()
        elif getattr(self, "_eqwin", None) is not None:
            GLib.idle_add(self._grab_eq_win, self._eqwin)

    def _after_hostname(self, ok, msg):
        self._notify("Nombre del equipo actualizado" if ok else (msg or "Error"))
        if getattr(self, "_eqwin", None) is not None:
            self._close_eq_win()
            self.open_equipo()
        return False

    def _grab_eq_win(self, win):
        gw = win.get_window()
        if gw is None:
            return False
        try:
            win.get_display().get_default_seat().grab(
                gw, Gdk.SeatCapabilities.ALL, True, None, None, None, None)
        except Exception:
            pass
        return False

    def _eq_click_outside(self, win, event):
        a = win.get_allocation()
        if event.x < 0 or event.y < 0 or event.x > a.width or event.y > a.height:
            self._close_eq_win()
            return True
        return False

    def _eq_key(self, win, event):
        if self._tecla_recorte(event, self._close_eq_win):
            return True
        if event.keyval == Gdk.KEY_Escape:
            self._close_eq_win()
            return True
        return False

    def _close_eq_win(self):
        win = getattr(self, "_eqwin", None)
        if win is None:
            return
        try:
            win.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        self._eqwin = None
        win.destroy()

    # ---------- mostrar escritorio ----------
    def toggle_show_desktop(self, *_):
        showing = self.wnck_screen.get_showing_desktop()
        self.wnck_screen.toggle_showing_desktop(not showing)

    # ---------- auto-actualización ----------
    def _check_update_loop(self):
        self._check_update_once()
        self._check_apps_update_bg()
        self._aviso_reinicio()
        return True   # seguir repitiendo cada UPDATE_INTERVAL

    def _aviso_reinicio(self):
        """1.7.3 (#2942): el Actualizador aplica parches de SEGURIDAD sin reiniciar nunca. Si
        alguno termina de aplicarse al reiniciar (/run/reboot-required), se avisa UNA vez por
        sesión — reiniciar lo decide la persona, no la barra."""
        if os.path.exists(REBOOT_FLAG) and not getattr(self, "_reinicio_avisado", False):
            self._reinicio_avisado = True
            self._notify("Se instalaron parches de seguridad. Terminan de aplicarse al "
                         "reiniciar: reinicie el equipo cuando le quede bien (no hay apuro).")
        return False

    # ---------- las DEMÁS apps FactuPOS (1.7.0, #2942) ----------
    def _check_apps_update_bg(self):
        threading.Thread(target=self._check_apps_update, daemon=True).start()
        return False

    def _apps_revisar(self):
        """{'atrasadas': [(pkg, instalada, nueva)], 'faltan': [pkg], 'instaladas': n} de las apps
        del repo FactuPOS, o None si no se pudo leer. 'faltan' = las OBLIGATORIAS de la lista
        del Actualizador que no están. Lee el índice público del repo APT (sin root) y dpkg."""
        try:
            req = urllib.request.Request(APPS_REPO_INDEX, headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=15) as r:
                txt = r.read().decode("utf-8", "replace")
        except Exception as e:
            sys.stderr.write("apps: no se pudo leer el repo: %s\n" % e)
            return None
        repo, pkg = {}, None
        for ln in txt.splitlines():
            if ln.startswith("Package:"):
                pkg = ln.split(":", 1)[1].strip()
            elif ln.startswith("Version:") and pkg:
                v = ln.split(":", 1)[1].strip()
                if pkg not in repo or _deb_lt(repo[pkg], v):
                    repo[pkg] = v
        if not repo:
            return None
        try:
            out = subprocess.run(["dpkg-query", "-W", "-f", "${Package} ${Version} ${Status}\n"]
                                 + sorted(repo), capture_output=True, text=True, timeout=20,
                                 env=dict(os.environ, LC_ALL="C")).stdout
        except Exception:
            return None
        atras, inst = [], set()
        for ln in out.splitlines():
            p = ln.split()
            if len(p) >= 3 and ln.endswith("install ok installed"):
                inst.add(p[0])
                if _deb_lt(p[1], repo.get(p[0], "")):
                    atras.append((p[0], p[1], repo[p[0]]))
        faltan = []
        try:
            quitadas = {ln.strip() for ln in open(APPS_QUITADAS, encoding="utf-8")}
        except Exception:
            quitadas = set()
        try:
            for ln in open(APPS_BASE, encoding="utf-8"):
                q = ln.strip()
                if q and not q.startswith("#") and q in repo and q not in inst and q not in quitadas:
                    faltan.append(q)
        except Exception:
            pass
        return {"atrasadas": atras, "faltan": faltan, "instaladas": len(inst)}

    def _check_apps_update(self):
        """Automático (al arrancar y cada hora): si falta alguna app obligatoria o alguna está
        atrasada, arranca el Actualizador SIN clave (polkit 47) y avisa qué quedó."""
        if getattr(self, "_apps_upd_corriendo", False):
            return
        self._apps_upd_corriendo = True
        try:
            rev = self._apps_revisar()
            if not rev or not (rev["atrasadas"] or rev["faltan"]):
                return
            sys.stderr.write("apps: atrasadas %s · faltan %s\n" % (
                ", ".join("%s %s->%s" % a for a in rev["atrasadas"]), ", ".join(rev["faltan"])))
            # 1.7.8 (#3037, dueño: «el panel debe saber si hay versiones nuevas y abrir FactuPOS Apps»):
            # aviso al encontrarlas; tocarlo abre la Tienda. La instalación sigue sola igual.
            nuevas = ["%s %s" % (_nombre_app(p), v) for p, _o, v in rev["atrasadas"]]
            nuevas += ["%s (nueva)" % _nombre_app(p) for p in rev["faltan"]]
            GLib.idle_add(self._notify, "Hay versiones nuevas: %s. Se instalan solas; puede seguir "
                          "trabajando." % ", ".join(nuevas), True)
            r = subprocess.run(["systemctl", "--no-ask-password", "start", "factupos-actualizador.service"],
                               capture_output=True, text=True, timeout=1800)
            if r.returncode != 0:
                sys.stderr.write("apps: el actualizador no arrancó: %s\n" % (r.stderr or "").strip())
                return
            desp = self._apps_revisar() or {"atrasadas": [], "faltan": []}
            quedan = {a[0] for a in desp["atrasadas"]} | set(desp["faltan"])
            hecho = ["%s %s" % (_nombre_app(p), v) for p, _o, v in rev["atrasadas"]
                     if p not in quedan and p != "factupos-panel"]
            hecho += ["%s (nueva)" % _nombre_app(p) for p in rev["faltan"] if p not in quedan]
            if hecho:
                GLib.idle_add(self._notify, "Apps FactuPOS al día: " + ", ".join(hecho), True)
        except Exception as e:
            sys.stderr.write("apps: %s\n" % e)
        finally:
            self._apps_upd_corriendo = False

    def _check_update_manual(self, *_):
        """Disparado por el usuario (clic derecho): chequea y avisa el resultado."""
        self._notify("Buscando actualizaciones del panel...")
        threading.Thread(
            target=lambda: self._check_update_once(notify_uptodate=True),
            daemon=True).start()

    def _check_update_once(self, notify_uptodate=False):
        """Lee el archivo de versiones; si hay una nueva, baja el .py y reinicia."""
        try:
            req = urllib.request.Request(UPDATE_MANIFEST,
                                         headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=8) as r:
                man = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            sys.stderr.write("update: no se pudo leer manifiesto: %s\n" % e)
            if notify_uptodate:
                self._notify("No se pudo verificar actualizaciones (sin conexión)")
            return False
        newv = str(man.get("version", "")).strip()
        if not newv or _vtuple(newv) <= _vtuple(VERSION):
            if notify_uptodate:
                self._notify("El panel ya está actualizado (v%s)" % VERSION)
            return False
        pyurl = man.get("py") or (UPDATE_BASE + "/factupos-panel.py")
        try:
            with urllib.request.urlopen(pyurl, timeout=25) as r:
                data = r.read()
        except Exception as e:
            sys.stderr.write("update: descarga falló: %s\n" % e)
            return False
        # validación mínima: que sea realmente el script
        if b"FactuPOS Panel" not in data or b"def main(" not in data:
            sys.stderr.write("update: contenido inválido, se descarta\n")
            return False
        try:
            os.makedirs(os.path.dirname(UPDATE_PY_LOCAL), exist_ok=True)
            tmp = UPDATE_PY_LOCAL + ".new"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, UPDATE_PY_LOCAL)
        except Exception as e:
            sys.stderr.write("update: no se pudo guardar: %s\n" % e)
            return False
        sys.stderr.write("Panel %s -> %s actualizado, reiniciando...\n" % (VERSION, newv))
        self._notify("FactuPOS Panel actualizado a la versión %s" % newv)
        GLib.timeout_add_seconds(1, self._restart_self)
        return False

    def _restart_self(self):
        try:
            py = UPDATE_PY_LOCAL if os.path.exists(UPDATE_PY_LOCAL) else os.path.abspath(__file__)
            os.execv(sys.executable, [sys.executable, py] + sys.argv[1:])
        except Exception as e:
            sys.stderr.write("update: no se pudo reiniciar: %s\n" % e)
        return False

    def _notify(self, msg, abrir_tienda=False):
        """abrir_tienda (1.7.8, #3037): el aviso trae «Abrir FactuPOS Apps» y tocarlo la abre.
        notify-send con acción espera la respuesta: va en un hilo para no trabar la barra."""
        if not shutil.which("notify-send"):
            return False
        cmd = ["notify-send", "-i", "start-here", "FactuPOS Panel", msg]
        if not (abrir_tienda and cmd_available("factupos-apps")):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            return False

        def esperar():
            try:
                r = subprocess.run(cmd + ["-A", "default=Abrir FactuPOS Apps"],
                                   capture_output=True, text=True, timeout=3600)
                if r.returncode != 0 and "action" in (r.stderr or "").lower():
                    subprocess.run(cmd, timeout=30)   # notify-send viejo, sin acciones
                elif r.stdout.strip() == "default":
                    detached_run("factupos-apps")
            except Exception:
                pass
        threading.Thread(target=esperar, daemon=True).start()
        return False

    # ---------- menú Inicio (estilo Windows 2000 moderno, navy) ----------
    def toggle_start_menu(self, *_):
        if getattr(self, "_startwin", None) is not None:
            self._close_start_menu()
            return
        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_decorated(False)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        win.set_keep_above(True)
        win.set_resizable(False)
        win.set_size_request(340, -1)
        win.get_style_context().add_class("fp-startmenu")
        win.get_style_context().add_class("fp-claro")  # 1.6.8: blanco, grises y azules, sin sombras

        # items con hover (se llena en _mitem): [(boton, abridor_de_submenu|None)]
        self._hover_items = []

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        win.add(row)

        # --- banner vertical "FactuPOS" ---
        banner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        banner.get_style_context().add_class("fp-banner")
        banner.set_size_request(40, -1)
        bl = Gtk.Label()
        bl.set_angle(90)
        ver = os_version()
        ostxt = (" · OS %s" % GLib.markup_escape_text(ver)) if ver else ""
        vtxt = "   <span size='small'>Panel v%s%s</span>" % (VERSION, ostxt)
        bl.set_markup("<span size='large'><b>FactuPOS OS</b></span>%s" % vtxt)
        bl.set_valign(Gtk.Align.CENTER)
        banner.pack_start(bl, True, True, 6)
        row.pack_start(banner, False, False, 0)

        # --- columna de opciones ---
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        col.set_size_request(280, -1)
        col.set_border_width(4)
        row.pack_start(col, True, True, 0)

        ud, D = GLib.get_user_special_dir, GLib.UserDirectory
        home = os.path.expanduser("~")

        # --- buscador de aplicaciones ---
        search = Gtk.SearchEntry()
        search.set_placeholder_text("Buscar aplicaciones...")
        col.pack_start(search, False, False, 2)

        # --- items normales del menú (se ocultan al buscar) ---
        items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        col.pack_start(items, True, True, 0)
        # Accesos rápidos arriba: Documentos, Imágenes y Ayuda y soporte.
        items.pack_start(self._mitem("Documentos", "folder-documents", lambda *_:
            (self._close_start_menu(),
             detached_run("xdg-open %s" % shlex.quote(ud(D.DIRECTORY_DOCUMENTS) or home)))), False, False, 0)
        items.pack_start(self._mitem("Imágenes", "folder-pictures", lambda *_:
            (self._close_start_menu(),
             detached_run("xdg-open %s" % shlex.quote(ud(D.DIRECTORY_PICTURES) or home)))), False, False, 0)
        items.pack_start(self._mitem("Ayuda y soporte", "help-browser", lambda *_:
            (self._close_start_menu(),
             detached_run("xdg-open https://soportereal.com"))), False, False, 0)
        # --- Menú CURADO: solo FactuPOS y sus aplicaciones (decisión del dueño).
        # Lo demás instalado se encuentra con el buscador de arriba.
        # Herramientas / Aplicaciones / Configuración van en el PRIMER nivel
        # (antes colgaban de un item "FactuPOS ▶", que se eliminó junto con el
        # acceso "Facturación FactuPOS" — pedido del dueño).
        items.pack_start(self._msep(), False, False, 2)
        items.pack_start(self._mitem("Herramientas", "applications-system",
            lambda w: self._open_flyout(self._herramientas_menu, w), arrow=True), False, False, 0)
        items.pack_start(self._mitem("Aplicaciones", "applications-other",
            lambda w: self._open_flyout(self._aplicaciones_menu, w), arrow=True), False, False, 0)
        items.pack_start(self._mitem("Configuración", "preferences-system",
            lambda w: self._open_flyout(self._settings_menu, w), arrow=True), False, False, 0)
        items.pack_start(self._msep(), False, False, 2)
        items.pack_start(self._mitem("Ofimática", "applications-office",
            lambda w: self._open_flyout(self._office_menu, w), arrow=True), False, False, 0)
        items.pack_start(self._mitem("Navegadores", "web-browser",
            lambda w: self._open_flyout(self._browsers_menu, w), arrow=True), False, False, 0)
        items.pack_start(self._mitem("Mensajería",
            icono_tema("internet-chat", "im-message-new", "chat",
                       "mail-message-new", "user-available"),
            lambda w: self._open_flyout(self._messaging_menu, w), arrow=True), False, False, 0)
        items.pack_start(self._mitem("Programas", "applications-other",
            lambda w: self._open_flyout(self._essentials_menu, w), arrow=True), False, False, 0)
        items.pack_start(self._msep(), False, False, 2)
        items.pack_start(self._mitem("Equipo", "computer",
            lambda *_: (self._close_start_menu(),
                        detached_run("factupos-dataequipo")
                        if cmd_available("factupos-dataequipo")
                        else self.open_equipo())), False, False, 0)
        items.pack_start(self._mitem("Terminal", "utilities-terminal", lambda *_:
            (self._close_start_menu(), detached_run("x-terminal-emulator"))), False, False, 0)
        items.pack_start(self._msep(), False, False, 2)
        items.pack_start(self._mitem("Apagar", "system-shutdown",
            lambda w: self._open_flyout(self._power_menu, w), arrow=True), False, False, 0)

        # --- resultados de búsqueda (ocultos hasta escribir) ---
        results_scroll = Gtk.ScrolledWindow()
        results_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        results_scroll.set_min_content_height(340)
        results_scroll.set_no_show_all(True)
        results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        results_scroll.add(results)
        col.pack_start(results_scroll, True, True, 0)

        def _on_search(entry):
            q = entry.get_text().strip().lower()
            for c in results.get_children():
                results.remove(c)
            if not q:
                results_scroll.hide()
                items.show()
                return
            items.hide()
            buckets, otros = self._categorize()
            allapps = []
            for lst in buckets.values():
                allapps += lst
            allapps += otros
            seenk, matches = set(), []
            for nm, ai in allapps:
                k = (nm or "").lower()
                if not k or k in seenk:
                    continue
                if q in k:
                    matches.append((nm, ai))
                    seenk.add(k)
            matches.sort(key=lambda x: (x[0] or "").lower())
            for nm, ai in matches[:40]:
                b = Gtk.Button()
                b.set_relief(Gtk.ReliefStyle.NONE)
                b.get_style_context().add_class("fp-mitem")
                rr = Gtk.Box(spacing=10)
                gi = ai.get_icon()
                img = (Gtk.Image.new_from_gicon(gi, Gtk.IconSize.LARGE_TOOLBAR) if gi
                       else Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.LARGE_TOOLBAR))
                rr.pack_start(img, False, False, 0)
                ll = Gtk.Label(label=nm)
                ll.set_xalign(0)
                rr.pack_start(ll, True, True, 0)
                b.add(rr)
                b.connect("clicked", lambda _w, a=ai: (self._close_start_menu(), self._launch_appinfo(a)))
                self._pin_conectar_item(b, pin_desde_appinfo(ai))
                results.pack_start(b, False, False, 0)
            if not matches:
                lab = Gtk.Label(label="Sin resultados")
                lab.set_xalign(0)
                results.pack_start(lab, False, False, 8)
            results.show_all()
            results_scroll.show()

        search.connect("search-changed", _on_search)

        win.show_all()
        self._position_start_menu(win)
        win.connect("button-press-event", self._start_menu_click_outside)
        win.connect("key-press-event", self._start_menu_key)
        win.connect("destroy", lambda *_: setattr(self, "_startwin", None))
        self._startwin = win
        GLib.idle_add(self._grab_start_menu, win)
        self._hover_start()

    # ---------- helpers del menú Inicio (Windows 2000) ----------
    def _mitem(self, label, icon, on_click, arrow=False):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.get_style_context().add_class("fp-mitem")
        r = Gtk.Box(spacing=10)
        if icon and icon.startswith("/") and os.path.exists(icon):
            # icono por RUTA de archivo (logo FactuPOS), escalado a 20px
            pb = GdkPixbuf.Pixbuf.new_from_file_at_size(icon, 20, 20)
            img = Gtk.Image.new_from_pixbuf(pb)
        else:
            img = Gtk.Image.new_from_icon_name(icon or "application-x-executable",
                                               Gtk.IconSize.LARGE_TOOLBAR)
            img.set_pixel_size(20)
        r.pack_start(img, False, False, 0)
        l = Gtk.Label(label=label)
        l.set_xalign(0)
        r.pack_start(l, True, True, 0)
        if arrow:
            r.pack_start(Gtk.Image.new_from_icon_name("pan-end-symbolic", Gtk.IconSize.MENU),
                         False, False, 0)
        b.add(r)
        b.connect("clicked", lambda _w: on_click(b))
        # Los items con flecha (submenú) se abren solos al pasar el mouse; los
        # demás se registran igual para poder CERRAR el submenú abierto al pasarles.
        try:
            self._hover_items.append((b, on_click if arrow else None))
        except AttributeError:
            pass
        return b

    def _msep(self):
        s = Gtk.Separator()
        return s

    def _img_menu_item(self, label, icon=None, gicon=None):
        mi = Gtk.MenuItem()
        box = Gtk.Box(spacing=8)
        if gicon is not None:
            img = Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.MENU)
        elif icon and icon.startswith("/") and os.path.exists(icon):
            # icono por RUTA de archivo (ej. logo FactuPOS), escalado a 16px
            pb = GdkPixbuf.Pixbuf.new_from_file_at_size(icon, 16, 16)
            img = Gtk.Image.new_from_pixbuf(pb)
        else:
            img = Gtk.Image.new_from_icon_name(icon or "application-x-executable", Gtk.IconSize.MENU)
        # Forzar 16px: si un .desktop trae un Icon que solo existe como PNG grande
        # (p.ej. factupos-print), new_from_gicon NO lo escala y se ve gigante.
        img.set_pixel_size(16)
        box.pack_start(img, False, False, 0)
        l = Gtk.Label(label=label)
        l.set_xalign(0)
        box.pack_start(l, True, True, 0)
        mi.add(box)
        return mi

    def _menu_header_item(self, text):
        mi = Gtk.MenuItem()
        mi.set_sensitive(False)
        l = Gtk.Label()
        l.set_markup("<b>%s</b>" % GLib.markup_escape_text(text))
        l.set_xalign(0)
        mi.add(l)
        return mi

    def _app_item(self, label, cmd=None, gicon=None, icon=None, appinfo=None):
        mi = self._img_menu_item(label, icon=icon, gicon=gicon)
        if appinfo is not None:
            mi.connect("activate", lambda _w, a=appinfo: (self._close_start_menu(), self._launch_appinfo(a)))
            self._pin_conectar_item(mi, pin_desde_appinfo(appinfo))
        else:
            mi.connect("activate", lambda _w, c=cmd: (self._close_start_menu(), detached_run(c)))
            self._pin_conectar_item(mi, self._pin_desde_cmd(label, cmd, icon))
        return mi

    def _programs_menu(self):
        """Flyout único de 2 niveles: favoritos 'Programas' + apps por categoría
        (con encabezados), SIN Utilidades/Herramientas (esos van en su propio menú)."""
        menu = Gtk.Menu()
        menu.get_style_context().add_class("fp-flyout")
        added = False
        seen = set()   # evita duplicados (favorito quemado vs escaneo automático)
        for item in load_menu().get("Programas", []):
            label, cmd, ic = (item + ["", "", ""])[:3]
            if not cmd_available(cmd):
                continue
            k = label.strip().lower()
            if k in seen:
                continue
            seen.add(k)
            menu.append(self._app_item(label, cmd=cmd, icon=ic))
            added = True
        buckets, otros = self._categorize()
        for _k, es in list(CATEGORIES) + [("Otros", "Otros")]:
            if es in ("Herramientas del sistema", "Accesorios", "Configuración",
                      "Oficina"):  # Oficina tiene su propio menú "Ofimática"
                continue
            apps = otros if es == "Otros" else buckets.get(es, [])
            apps = [(nm, ai) for (nm, ai) in apps if nm.strip().lower() not in seen]
            if not apps:
                continue
            if added:
                menu.append(Gtk.SeparatorMenuItem())
            menu.append(self._menu_header_item(es))
            for nm, ai in apps:
                k = nm.strip().lower()
                if k in seen:
                    continue
                seen.add(k)
                menu.append(self._app_item(nm, gicon=ai.get_icon(), appinfo=ai))
            added = True
        return menu

    def _category_menu(self, *cats):
        """Flyout plano con las apps de una o más categorías (sin repetir)."""
        menu = Gtk.Menu()
        menu.get_style_context().add_class("fp-flyout")
        buckets, otros = self._categorize()
        added = False
        for es in cats:
            apps = otros if es == "Otros" else buckets.get(es, [])
            if not apps:
                continue
            if added and len(cats) > 1:
                menu.append(Gtk.SeparatorMenuItem())
                menu.append(self._menu_header_item(es))
            for nm, ai in apps:
                menu.append(self._app_item(nm, gicon=ai.get_icon(), appinfo=ai))
            added = True
        if not added:
            mi = Gtk.MenuItem(label="(sin elementos)")
            mi.set_sensitive(False)
            menu.append(mi)
        return menu

    def _fp_add(self, sub, label, icon, cmd=None, desktop=None):
        """Agrega un item al menú si el programa existe en el equipo."""
        ai = None
        if desktop:
            try:
                ai = Gio.DesktopAppInfo.new(desktop)
            except Exception:
                ai = None
            if ai is None:
                return
        elif not cmd_available((cmd or "").split()[0]):
            return
        mi = self._img_menu_item(label, icon)
        if ai is not None:
            mi.connect("activate", lambda _w, a=ai:
                       (self._close_start_menu(), self._launch_appinfo(a)))
            p = pin_desde_appinfo(ai)
            p["label"] = label          # el nombre que ve el usuario en el menú
            if icon:
                p["icon"] = icon
            self._pin_conectar_item(mi, p)
        else:
            mi.connect("activate", lambda _w, c=cmd:
                       (self._close_start_menu(), detached_run(c)))
            self._pin_conectar_item(mi, self._pin_desde_cmd(label, cmd, icon))
        sub.append(mi)

    def _herramientas_menu(self):
        """Herramientas FactuPOS. Subió al PRIMER nivel del menú Inicio
        (antes colgaba de un item FactuPOS ▶, eliminado a pedido del dueño).
        Solo muestra lo que exista en el equipo."""
        herr = Gtk.Menu()
        herr.get_style_context().add_class("fp-flyout")
        add = self._fp_add

        hay_actualizador = os.path.exists(
            "/usr/lib/factupos-actualizador/factupos-actualizador.sh")
        if cmd_available("factupos-apps"):
            add(herr, "FactuPOS Apps", "system-software-install", cmd="factupos-apps")
        elif hay_actualizador:
            # La tienda no está (pero el Actualizador sí): instalarla directo.
            # Si TAMPOCO hay Actualizador no se muestra este item — el de
            # "Instalar herramientas FactuPOS" de abajo ya instala TODO.
            mi = self._img_menu_item("Instalar FactuPOS Apps",
                                     "system-software-install")
            mi.connect("activate", self._instalar_tienda)
            herr.append(mi)
        # «FactuPOS Update» ya no existe (#3037): todo lo hace FactuPOS Apps.
        if not hay_actualizador:
            # PC sin el Actualizador (ej: solo tiene el panel): bootstrap —
            # baja e instala el Actualizador, que configura el repo apt e
            # instala la tienda y las demás apps base. Un clic = PC completa.
            mi = self._img_menu_item("Instalar herramientas FactuPOS",
                                     "system-software-install")
            mi.connect("activate", self._bootstrap_factupos)
            herr.append(mi)
        mi = self._img_menu_item("Actualizar repositorios", "view-refresh")
        mi.connect("activate", self._actualizar_repos)
        herr.append(mi)
        add(herr, "FactuPOS Impresoras", "printer", cmd="factupos-printer-inst")
        add(herr, "Monitores", "video-display", cmd="factupos-pantalla")
        add(herr, "Administrador de Tareas", "utilities-system-monitor",
            cmd="factupos-tareas")
        add(herr, "Conexiones de Red", "network-workgroup", cmd="factupos-conexiones")
        add(herr, "Fondo de Escritorio", "preferences-desktop-wallpaper",
            cmd="factupos-fondo")
        add(herr, "Opciones de Energía", "preferences-system-power",
            cmd="factupos-energia")
        add(herr, "Inicio de sesión automático", "system-lock-screen",
            cmd="factupos-autologin")
        return herr

    def _aplicaciones_menu(self):
        """Aplicaciones FactuPOS. Subió al PRIMER nivel del menú Inicio."""
        apps = Gtk.Menu()
        apps.get_style_context().add_class("fp-flyout")
        add = self._fp_add
        add(apps, "FactuPOS Print", "printer", desktop="factupos-print.desktop")
        add(apps, "FactuPOS Bridge", "network-transmit-receive",
            desktop="factupos-print-bridge.desktop")
        add(apps, "FactuPOS IA", "user-available", cmd="factupos-ia")
        add(apps, "Datos del Equipo", "computer", cmd="factupos-dataequipo")
        add(apps, "Soporte Remoto FactuPOS", icono_soporte(), cmd="rustdesk")
        return apps

    def _utils_menu(self):
        """Utilidades: apps curadas de FactuPOS + el resto de Accesorios ('y demás')."""
        menu = Gtk.Menu()
        menu.get_style_context().add_class("fp-flyout")
        seen = set()
        curated = (
            ("Calculadora", "accessories-calculator", "gnome-calculator"),
            ("Editores", "accessories-text-editor", "xed"),
            ("Notas", "accessories-text-editor", "sticky"),
        )
        for label, icon, cmd in curated:
            base = cmd.split()[0]
            if not cmd_available(base):
                continue
            mi = self._img_menu_item(label, icon)
            mi.connect("activate", lambda _w, c=cmd: (self._close_start_menu(), detached_run(c)))
            self._pin_conectar_item(mi, self._pin_curado(label, cmd, icon))
            menu.append(mi)
            seen.add(base)
        buckets, _otros = self._categorize()
        extras = [(nm, ai) for nm, ai in buckets.get("Accesorios", [])
                  if (ai.get_executable() or "").split("/")[-1].split()[0] not in seen]
        if extras:
            menu.append(Gtk.SeparatorMenuItem())
            for nm, ai in extras:
                menu.append(self._app_item(nm, gicon=ai.get_icon(), appinfo=ai))
        return menu

    def _office_menu(self):
        """Ofimática: LibreOffice y demás apps de oficina instaladas."""
        return self._category_menu("Oficina")

    def _browsers_menu(self):
        """Navegadores instalados: Chrome, Brave, Firefox, Edge, Chromium."""
        menu = Gtk.Menu()
        menu.get_style_context().add_class("fp-flyout")
        curated = (
            ("Google Chrome",  icono_tema("google-chrome", "web-browser"), "google-chrome"),
            ("Brave",          icono_tema("brave-browser", "brave", "web-browser"), "brave-browser"),
            ("Firefox",        icono_tema("firefox", "firefox-esr", "web-browser"),
             self._cmd_disponible("firefox", "firefox-esr")),
            ("Microsoft Edge", icono_tema("microsoft-edge", "web-browser"),
             self._cmd_disponible("microsoft-edge-stable", "microsoft-edge")),
            ("Chromium",       icono_tema("chromium", "chromium-browser", "web-browser"), "chromium"),
        )
        added = False
        for label, icon, cmd in curated:
            if not cmd_available(cmd.split()[0]):
                continue
            mi = self._img_menu_item(label, icon)
            mi.connect("activate", lambda _w, c=cmd:
                       (self._close_start_menu(), detached_run(c)))
            self._pin_conectar_item(mi, self._pin_curado(label, cmd, icon))
            menu.append(mi)
            added = True
        if not added:
            mi = Gtk.MenuItem(label="(ninguno instalado)")
            mi.set_sensitive(False)
            menu.append(mi)
        return menu

    @staticmethod
    def _icono_app(nombre_png, fallback):
        """Logo empaquetado en el .deb del panel; si no está, ícono de tema."""
        p = "/usr/lib/factupos-panel/" + nombre_png
        return p if os.path.exists(p) else fallback

    def _messaging_menu(self):
        """Mensajería: Telegram y WhatsApp (web-app si no hay cliente nativo)."""
        menu = Gtk.Menu()
        menu.get_style_context().add_class("fp-flyout")
        tele = self._cmd_disponible("telegram-desktop", "Telegram", "telegram")
        if cmd_available(tele.split()[0]):
            mi = self._img_menu_item("Telegram",
                                     self._icono_app("telegram.png", "internet-chat"))
            mi.connect("activate", lambda _w, c=tele:
                       (self._close_start_menu(), detached_run(c)))
            self._pin_conectar_item(mi, self._pin_curado(
                "Telegram", tele, self._icono_app("telegram.png", "internet-chat")))
            menu.append(mi)
        # WhatsApp: la app de FactuPOS (factupos-navegadores, #2942); si no, nativo;
        # si no, app web con Chrome; último: navegador
        wa = self._cmd_disponible("factupos-whatsapp", "whatsapp-for-linux", "whatsdesk")
        if not cmd_available(wa.split()[0]):
            if cmd_available("google-chrome"):
                wa = ("google-chrome --app=https://web.whatsapp.com "
                      "--password-store=basic")
            else:
                wa = "xdg-open https://web.whatsapp.com"
        mi = self._img_menu_item("WhatsApp",
                                 self._icono_app("whatsapp.png", "internet-chat"))
        mi.connect("activate", lambda _w, c=wa:
                   (self._close_start_menu(), detached_run(c)))
        self._pin_conectar_item(mi, self._pin_curado(
            "WhatsApp", wa, self._icono_app("whatsapp.png", "internet-chat")))
        menu.append(mi)
        return menu

    def _essentials_menu(self):
        """Programas: esenciales de la distro que (aún) no desarrollamos
        nosotros — lista CURADA, cada uno con su cadena de alternativas."""
        menu = Gtk.Menu()
        menu.get_style_context().add_class("fp-flyout")
        curated = (
            ("Archivos", "system-file-manager",
             self._cmd_disponible("thunar", "nemo", "pcmanfm")),
            ("Editor de texto", "accessories-text-editor",
             self._cmd_disponible("xed", "mousepad", "gedit", "featherpad")),
            ("Calculadora", "accessories-calculator",
             self._cmd_disponible("gnome-calculator", "galculator", "mate-calc")),
            ("Captura de pantalla", "applets-screenshooter",
             self._cmd_disponible("xfce4-screenshooter", "gnome-screenshot", "flameshot gui")),
            ("Visor de PDF", "application-pdf",
             self._cmd_disponible("xreader", "evince", "atril")),
            ("Configurar impresoras", "printer",
             self._cmd_disponible("system-config-printer")),
            ("Synaptic (paquetes)", "system-software-install",
             self._cmd_disponible("synaptic-pkexec", "synaptic")),
        )
        added = False
        for label, icon, cmd in curated:
            if not cmd_available(cmd.split()[0]):
                continue
            mi = self._img_menu_item(label, icon)
            mi.connect("activate", lambda _w, c=cmd:
                       (self._close_start_menu(), detached_run(c)))
            self._pin_conectar_item(mi, self._pin_curado(label, cmd, icon))
            menu.append(mi)
            added = True
        if not added:
            mi = Gtk.MenuItem(label="(sin elementos)")
            mi.set_sensitive(False)
            menu.append(mi)
        return menu

    def _tools_menu(self):
        return self._category_menu("Herramientas del sistema")

    def _settings_menu(self):
        """Configuración: ajustes curados de FactuPOS OS (lista fija).
        FUSIONADO: antes había DOS 'Configuración' — esta y otra colgando de
        FactuPOS ▶, que compartían Apariencia/Idioma/Teclado. Al subir las ramas
        al primer nivel quedaban duplicadas, así que se unieron acá. De la de
        FactuPOS se conservaron sus comandos CON RESPALDO (xfce4 → cinnamon),
        que aguantan mejor un escritorio que no sea Cinnamon."""
        menu = Gtk.Menu()
        menu.get_style_context().add_class("fp-flyout")
        cd = self._cmd_disponible
        # (etiqueta, icono, comando)  -- solo se muestra si el binario existe
        curated = (
            ("Pantalla", "video-display",
             cd("xfce4-display-settings", "cinnamon-settings display")),
            ("Impresoras", "printer", "system-config-printer"),
            ("Apariencia", "preferences-desktop-theme",
             cd("xfce4-appearance-settings", "cinnamon-settings themes")),
            ("Idioma y región", "preferences-desktop-locale",
             cd("mintlocale", "gnome-language-selector", "cinnamon-settings region")),
            ("Teclado", "input-keyboard",
             cd("xfce4-keyboard-settings", "cinnamon-settings keyboard")),
            ("Ratón y touchpad", "input-mouse",
             cd("xfce4-mouse-settings", "cinnamon-settings mouse")),
            ("Fecha y hora", "preferences-system-time",
             cd("time-admin", "cinnamon-settings calendar", "xfce4-settings-manager")),
            ("Red", "network-wireless", "nm-connection-editor"),
            ("Bluetooth", "bluetooth", "blueman-manager"),
        )
        self._append_curated(menu, curated)
        return menu

    def _system_menu(self):
        """Sistema: administración del equipo (lista fija)."""
        menu = Gtk.Menu()
        menu.get_style_context().add_class("fp-flyout")
        curated = (
            ("Cortafuegos", "security-high", "gufw"),
            ("Administrador de tareas", "utilities-system-monitor", "@taskmgr"),
            ("Usuarios", "system-users", "cinnamon-settings user"),
            ("Gestor de actualizaciones", "system-software-update", "mintupdate"),
            ("Gestor de software", "system-software-install", "mintinstall"),
            ("Discos", "drive-harddisk", "gnome-disks"),
            ("Seguridad", "preferences-system-privacy", "seahorse"),
        )
        self._append_curated(menu, curated)
        # Instalar/actualizar/quitar apps FactuPOS y navegadores: FactuPOS Apps (#3037);
        # acá solo quedan cosas del sistema.
        return menu

    def _bootstrap_factupos(self, *_):
        """El panel como INSTALADOR del sistema: en una PC que solo tiene el
        panel, baja e instala el Actualizador (el .deb ya configura el repo
        apt) y lo dispara — este instala la tienda y todas las apps base.
        Un clic deja la PC con la suite FactuPOS completa."""
        self._close_start_menu()
        self._notify("Instalando herramientas FactuPOS… (toma un momento)")
        url = ("https://soportereal.com/software/factupos-app/linux/"
               "Factupos-Actualizador.deb")
        script = ("sed -i '/cdrom:/s/^[^#]/#&/' /etc/apt/sources.list 2>/dev/null; DEBIAN_FRONTEND=noninteractive dpkg --configure -a --force-confdef --force-confold >/dev/null 2>&1; "
                  "cd /tmp && rm -f fp-act.deb && "
                  "(wget -qO fp-act.deb %s || curl -fsSL -o fp-act.deb %s) && "
                  "DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=180 install -y /tmp/fp-act.deb && "
                  "systemctl start factupos-actualizador.service; "
                  "systemctl start factupos-actualizador.service; "
                  "rm -f /tmp/fp-act.deb") % (url, url)

        def work():
            try:
                r = subprocess.run(["pkexec", "sh", "-c", script],
                                   capture_output=True, text=True, timeout=900)
                if r.returncode == 0:
                    self._notify("Herramientas FactuPOS instaladas ✓ "
                                 "Abrí el menú FactuPOS de nuevo.")
                else:
                    err = (r.stderr or r.stdout or "").strip().splitlines()
                    self._notify("No se pudo instalar: %s" %
                                 (err[-1] if err else "autorización cancelada"))
            except Exception as e:
                self._notify("No se pudo instalar: %s" % e)
        threading.Thread(target=work, daemon=True).start()

    def _instalar_tienda(self, *_):
        """Instala la tienda FactuPOS Apps desde el panel. Si el equipo aún no
        tiene el repo apt configurado, corre el bootstrap completo (que además
        instala el Actualizador y las apps base)."""
        if not os.path.exists("/etc/apt/sources.list.d/factupos.list"):
            return self._bootstrap_factupos()
        self._close_start_menu()
        self._notify("Instalando FactuPOS Apps…")
        script = ("sed -i '/cdrom:/s/^[^#]/#&/' /etc/apt/sources.list 2>/dev/null; DEBIAN_FRONTEND=noninteractive dpkg --configure -a --force-confdef --force-confold >/dev/null 2>&1; "
                  "apt-get -o DPkg::Lock::Timeout=180 update -o Dir::Etc::sourcelist="
                  "/etc/apt/sources.list.d/factupos.list "
                  "-o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0 -qq; "
                  "DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=180 install -y factupos-apps")

        def work():
            try:
                r = subprocess.run(["pkexec", "sh", "-c", script],
                                   capture_output=True, text=True, timeout=600)
                if r.returncode == 0:
                    self._notify("FactuPOS Apps instalada ✓ Ya aparece en el menú.")
                else:
                    err = (r.stderr or r.stdout or "").strip().splitlines()
                    self._notify("No se pudo instalar: %s" %
                                 (err[-1] if err else "autorización cancelada"))
            except Exception as e:
                self._notify("No se pudo instalar: %s" % e)
        threading.Thread(target=work, daemon=True).start()

    def _actualizar_repos(self, *_):
        """apt-get -o DPkg::Lock::Timeout=180 update de TODOS los repositorios (root vía pkexec).
        También desactiva la fuente cdrom si quedó del instalador."""
        self._close_start_menu()
        self._notify("Actualizando repositorios…")

        def work():
            try:
                r = subprocess.run(
                    ["pkexec", "sh", "-c",
                     "sed -i '/cdrom:/s/^[^#]/#&/' /etc/apt/sources.list 2>/dev/null; DEBIAN_FRONTEND=noninteractive dpkg --configure -a --force-confdef --force-confold >/dev/null 2>&1; "
                     "apt-get -o DPkg::Lock::Timeout=180 update"],
                    capture_output=True, text=True, timeout=600)
                if r.returncode == 0:
                    self._notify("Repositorios actualizados ✓")
                else:
                    err = (r.stderr or r.stdout or "").strip().splitlines()
                    self._notify("Error al actualizar: %s" %
                                 (err[-1] if err else "autorización cancelada"))
            except Exception as e:
                self._notify("Error al actualizar: %s" % e)
        threading.Thread(target=work, daemon=True).start()

    def _append_curated(self, menu, curated):
        """Agrega items (etiqueta, icono, comando) a un flyout; omite los que no
        tengan binario (los @tokens y multi-palabra se muestran siempre)."""
        any_added = False
        for label, icon, cmd in curated:
            base = cmd.split()[0]
            if not base.startswith("@") and not cmd_available(base):
                continue
            mi = self._img_menu_item(label, icon)
            mi.connect("activate", lambda _w, c=cmd: (self._close_start_menu(), detached_run(c)))
            self._pin_conectar_item(mi, self._pin_curado(label, cmd, icon))
            menu.append(mi)
            any_added = True
        if not any_added:
            mi = Gtk.MenuItem(label="(sin elementos)")
            mi.set_sensitive(False)
            menu.append(mi)

    @staticmethod
    def _cmd_disponible(*candidatos):
        """Primer comando cuyo ejecutable existe (agnóstico al escritorio)."""
        for c in candidatos:
            if shutil.which(c.split()[0]):
                return c
        return candidatos[-1]

    @staticmethod
    def _cadena_poder(*candidatos, final):
        """Comando de energía multi-escritorio: intenta el del escritorio
        (Cinnamon en Mint LMDE, XFCE en Debian puro) y si falla cae a
        systemctl. Compatible con .deb viejos sin la regla polkit."""
        partes = [c for c in candidatos if shutil.which(c.split()[0])]
        partes.append(final)
        return " || ".join(partes)

    def _power_menu(self):
        menu = Gtk.Menu()
        menu.get_style_context().add_class("fp-flyout")
        apagar = self._cadena_poder(
            "cinnamon-session-quit --power-off --no-prompt",  # Mint LMDE
            "xfce4-session-logout --halt --fast",             # Debian XFCE
            final="systemctl poweroff")
        reiniciar = self._cadena_poder(
            "cinnamon-session-quit --reboot --no-prompt",
            "xfce4-session-logout --reboot --fast",
            final="systemctl reboot")
        logout = self._cmd_disponible(
            "cinnamon-session-quit --logout --no-prompt",   # Cinnamon (LMDE)
            "xfce4-session-logout --logout --fast",          # XFCE (Debian puro)
            "loginctl terminate-user %s" % os.environ.get("USER", ""),
        )
        for label, icon, cmd in (
            ("Apagar", "system-shutdown", apagar),
            ("Reiniciar", "system-reboot", reiniciar),
            ("Suspender", "system-suspend", "systemctl suspend"),
            ("Cerrar sesión", "system-log-out", logout),
        ):
            mi = self._img_menu_item(label, icon)
            mi.connect("activate", lambda _w, c=cmd: (self._close_start_menu(), detached_run(c)))
            menu.append(mi)
        return menu

    def _open_flyout(self, build_menu, widget):
        try:
            self._startwin.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        menu = build_menu()
        self._flyout = menu

        def _on_deact(m):
            # Solo soltamos la referencia si sigue siendo el submenú vigente
            # (al cambiar de submenú por hover, el viejo se desactiva DESPUÉS
            # de que el nuevo ya se registró).
            if getattr(self, "_flyout", None) is m:
                self._flyout = None
            GLib.idle_add(self._regrab_start)

        menu.connect("deactivate", _on_deact)
        self._menu_escucha_recorte(menu)
        menu.show_all()
        # La cascada se abre a la derecha; hacia ARRIBA si la barra está abajo,
        # hacia abajo si está arriba (para no salirse de pantalla).
        if self.edge == "top":
            wa, ma = Gdk.Gravity.SOUTH_EAST, Gdk.Gravity.NORTH_WEST
        else:
            wa, ma = Gdk.Gravity.NORTH_EAST, Gdk.Gravity.SOUTH_WEST
        menu.popup_at_widget(widget, wa, ma, None)

    def _regrab_start(self):
        # Si hay un submenú abierto (p.ej. cambiamos de uno a otro por hover),
        # el grab es SUYO: recuperarlo aquí lo cerraría de inmediato.
        if getattr(self, "_flyout", None) is not None:
            return False
        # Lo mismo con un menú de clic derecho ("Agregar a la barra").
        if getattr(self, "_ctxmenu", None) is not None:
            return False
        # Y mientras se arrastra una app al escritorio o corre un recorte: el
        # puntero es del arrastre / de la herramienta de recortes (#3398).
        if getattr(self, "_arrastrando", False) or getattr(self, "_recortando", False):
            return False
        if getattr(self, "_startwin", None) is not None:
            self._grab_start_menu(self._startwin)
        return False

    # ---------- apertura automática de submenús al pasar el mouse ----------
    # Se hace por POLLING del puntero y no con enter-notify a propósito: cuando
    # un Gtk.Menu está desplegado toma el grab del puntero, así que la ventana
    # del menú Inicio deja de recibir eventos de hover y no se podría pasar de
    # un submenú a otro. Consultar la posición del puntero funciona igual.
    def _hover_start(self):
        self._hover_item = None
        self._hover_stop()
        self._hover_timer = GLib.timeout_add(HOVER_POLL_MS, self._hover_tick)

    def _hover_stop(self):
        t = getattr(self, "_hover_timer", None)
        if t:
            try:
                GLib.source_remove(t)
            except Exception:
                pass
        self._hover_timer = None
        self._hover_item = None

    def _hover_tick(self):
        win = getattr(self, "_startwin", None)
        if win is None:
            self._hover_timer = None
            return False
        # Con un menú de clic derecho abierto, no abrir/cerrar submenús por
        # hover: le robaría el grab y se cerraría solo. Tampoco mientras se
        # ARRASTRA una app (#3398): al cruzar otro item cambiaría de submenú y
        # destruiría el item que se está arrastrando.
        if getattr(self, "_ctxmenu", None) is not None:
            return True
        if getattr(self, "_arrastrando", False) or getattr(self, "_recortando", False):
            return True
        try:
            gw = win.get_window()
            if gw is None:
                return True
            _, px, py = win.get_display().get_default_seat().get_pointer().get_position()

            # Si el puntero está DENTRO del submenú abierto, no tocar nada:
            # el usuario está yendo hacia sus opciones.
            fly = getattr(self, "_flyout", None)
            if fly is not None:
                fw = fly.get_window()
                if fw is not None:
                    _, fx, fy = fw.get_origin()
                    if (fx <= px <= fx + fw.get_width()
                            and fy <= py <= fy + fw.get_height()):
                        return True

            _, ox, oy = gw.get_origin()
            rx, ry = px - ox, py - oy

            # Si hay un cierre diferido pendiente (clic afuera) y el mouse
            # vuelve sobre el menú, se cancela: el usuario lo sigue usando.
            aw = win.get_allocation()
            if 0 <= rx <= aw.width and 0 <= ry <= aw.height:
                self._cancel_close()

            hit = None
            for btn, opener in getattr(self, "_hover_items", []):
                if not btn.get_mapped():
                    continue
                a = btn.get_allocation()
                if (a.x <= rx <= a.x + a.width) and (a.y <= ry <= a.y + a.height):
                    hit = (btn, opener)
                    break

            if hit is None:
                # Fuera de los items (buscador, banner, afuera): no cerramos nada,
                # para no matar el submenú mientras el mouse viaja hacia él.
                return True

            btn, opener = hit
            if btn is getattr(self, "_hover_item", None):
                return True          # mismo item, ya está resuelto
            self._hover_item = btn

            if opener is not None:
                if fly is not None:
                    fly.popdown()
                opener(btn)
            elif fly is not None:
                # Item sin submenú: se cierra el que estuviera abierto (como Windows).
                fly.popdown()
        except Exception:
            pass
        return True

    def _run_dialog(self):
        try:
            self._startwin.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        d = Gtk.Dialog(title="Ejecutar", transient_for=self._startwin, modal=True)
        d.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        d.add_button("Ejecutar", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        ca = d.get_content_area()
        ca.set_border_width(10)
        ca.set_spacing(6)
        ca.add(Gtk.Label(label="Programa o comando a ejecutar:"))
        e = Gtk.Entry()
        e.set_activates_default(True)
        ca.add(e)
        d.show_all()
        resp = d.run()
        cmd = e.get_text().strip()
        d.destroy()
        self._close_start_menu()
        if resp == Gtk.ResponseType.OK and cmd:
            detached_run(cmd)

    def _categorize(self):
        """Agrupa las apps instaladas por categoría (Accesorios, Internet, ...)."""
        buckets = {es: [] for _k, es in CATEGORIES}
        otros = []
        for ai in Gio.AppInfo.get_all():
            try:
                if not ai.should_show():
                    continue
            except Exception:
                continue
            nm = ai.get_display_name() or ai.get_name() or ""
            cats = ""
            try:
                cats = ai.get_categories() or ""
            except Exception:
                pass
            cset = set(c for c in cats.split(";") if c)
            ex = (ai.get_executable() or "").split("/")[-1].split()[0] \
                if ai.get_executable() else ""
            # Las apps FactuPOS viven SOLO en el menú "FactuPOS" propio;
            # no repetirlas en Programas/Utilidades/Herramientas/Configuración.
            did = ""
            try:
                did = ai.get_id() or ""
            except Exception:
                pass
            if ex.startswith("factupos-") or did.startswith("factupos-"):
                continue
            # 1) División curada Utilidades/Herramientas por ejecutable
            if ex in FORCE_TOOLS:
                buckets["Herramientas del sistema"].append((nm, ai))
                continue
            if ex in FORCE_UTILS:
                buckets["Accesorios"].append((nm, ai))
                continue
            # 2) Categoría freedesktop (System gana sobre Utility por el orden)
            placed = False
            for key, es in CATEGORIES:
                if key in cset:
                    buckets[es].append((nm, ai))
                    placed = True
                    break
            if not placed:
                otros.append((nm, ai))
        for es in buckets:
            buckets[es].sort(key=lambda x: x[0].lower())
        otros.sort(key=lambda x: x[0].lower())
        return buckets, otros

    def _launch_appinfo(self, ai):
        try:
            ai.launch(None, None)
        except Exception as e:
            _error_dialog("No se pudo abrir:\n%s" % e)

    def _position_start_menu(self, win):
        geo = self._geo
        _m, nat = win.get_preferred_size()
        ww = max(nat.width, 300)
        wh = max(nat.height, 200)
        if self.edge == "left":
            x, y = geo.x + self.height, geo.y
        elif self.edge == "right":
            x, y = geo.x + geo.width - self.height - ww, geo.y
        elif self.edge == "top":
            x, y = geo.x + 2, geo.y + self.height
        else:  # bottom
            x, y = geo.x + 2, geo.y + geo.height - self.height - wh
        win.move(x, y)

    def _grab_start_menu(self, win):
        gw = win.get_window()
        if gw is None:
            return False
        try:
            seat = win.get_display().get_default_seat()
            seat.grab(gw, Gdk.SeatCapabilities.ALL, True, None, None, None, None)
        except Exception:
            pass
        return False

    def _clic_en_boton_inicio(self, event):
        """¿El clic cayó sobre el propio botón Inicio? (en coords de pantalla)"""
        btn = getattr(self, "start_btn", None)
        if btn is None or not btn.get_realized():
            return False
        gw = btn.get_window()
        if gw is None:
            return False
        a = btn.get_allocation()
        rx, ry = gw.get_root_coords(a.x, a.y)
        return (rx <= event.x_root < rx + a.width and
                ry <= event.y_root < ry + a.height)

    def _start_menu_click_outside(self, win, event):
        """🪤 El grab manda TODOS los clics acá, pero `event.x/y` vienen en las
        coordenadas de la ventana DONDE SE HIZO EL CLIC, no en las del menú.
        Compararlas contra `win.get_allocation()` daba "adentro" FALSO: un clic
        en el botón Inicio llega como (30,22) y cae dentro de los 340x484 del
        menú, así que el menú se quedaba abierto para siempre (ni cerraba ni
        arrancaba el cierre diferido). Hay que comparar en coordenadas de
        PANTALLA (`x_root`/`y_root`) contra la posición real del menú."""
        gw = win.get_window()
        if gw is None:
            return False
        ox, oy = gw.get_root_coords(0, 0)
        a = win.get_allocation()
        if (ox <= event.x_root < ox + a.width and
                oy <= event.y_root < oy + a.height):
            return False                      # clic de verdad adentro del menú
        if self._clic_en_boton_inicio(event):
            self._close_start_menu()          # 2do clic en Inicio = TOGGLE: cerrar YA
            return True
        self._schedule_close()
        return True

    # ---------- cierre diferido del menú Inicio (clic afuera) ----------
    def _schedule_close(self, delay=START_CLOSE_DELAY):
        """Clic afuera: esconde el menú. Con `delay` en 0 (lo normal) cierra al
        instante; con un valor mayor espera esos segundos.
        🔑 En el caso diferido el grab se suelta YA: mientras el menú lo tenga,
        los clics no llegan a nada más y el escritorio quedaría bloqueado todo
        ese rato."""
        win = getattr(self, "_startwin", None)
        if win is None or getattr(self, "_close_timer", None):
            return
        if delay <= 0:
            self._close_start_menu()
            return
        try:
            win.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        fly = getattr(self, "_flyout", None)
        if fly is not None:
            self._flyout = None
            try:
                fly.popdown()
            except Exception:
                pass
        self._close_timer = GLib.timeout_add_seconds(delay, self._close_timeout)

    def _close_timeout(self):
        self._close_timer = None
        self._close_start_menu()
        return False

    def _cancel_close(self):
        """El mouse volvió sobre el menú antes de que venciera: se queda."""
        t = getattr(self, "_close_timer", None)
        if not t:
            return
        try:
            GLib.source_remove(t)
        except Exception:
            pass
        self._close_timer = None
        self._regrab_start()      # volver a escuchar clics afuera

    def _start_menu_key(self, win, event):
        if self._tecla_recorte(event, self._close_start_menu):
            return True
        if event.keyval == Gdk.KEY_Escape:
            self._close_start_menu()
            return True
        return False

    def _close_start_menu(self):
        win = getattr(self, "_startwin", None)
        if win is None:
            return
        self._hover_stop()
        self._hover_items = []
        t = getattr(self, "_close_timer", None)
        if t:
            try:
                GLib.source_remove(t)
            except Exception:
                pass
        self._close_timer = None
        fly = getattr(self, "_flyout", None)
        if fly is not None:
            self._flyout = None
            try:
                fly.popdown()
            except Exception:
                pass
        try:
            win.get_display().get_default_seat().ungrab()
        except Exception:
            pass
        self._startwin = None
        win.destroy()

    # ---------- clic derecho en la barra (menú contextual tipo Windows) ----------
    def _toggle_lock(self, item):
        """Bloquea/desbloquea la barra y lo recuerda para el próximo arranque.
        Con --monitor all hay un Panel por pantalla: se marcan TODOS, si no
        quedaría una barra bloqueada y las otras no."""
        self.locked = bool(item.get_active())
        for p in PANELES:
            p.locked = self.locked
        save_state(locked=self.locked)

    def _on_panel_click(self, widget, event):
        if event.button != 3:
            return False
        menu = Gtk.Menu()

        # --- Pantalla y escritorio (arriba, como el clic derecho de Windows).
        # Se prefieren las herramientas propias de FactuPOS; si no están en el
        # equipo, se cae a la del escritorio (Cinnamon/XFCE) y por último a una
        # genérica, para que la opción sirva en cualquier instalación.
        mi = Gtk.MenuItem(label="Propiedades del monitor")
        mi.connect("activate", lambda *_: detached_run(self._cmd_disponible(
            "factupos-pantalla", "cinnamon-settings display",
            "xfce4-display-settings", "arandr")))
        menu.append(mi)

        mi = Gtk.MenuItem(label="Fondo de escritorio")
        mi.connect("activate", lambda *_: detached_run(self._cmd_disponible(
            "factupos-fondo", "cinnamon-settings backgrounds",
            "xfce4-desktop-settings", "nitrogen")))
        menu.append(mi)

        menu.append(Gtk.SeparatorMenuItem())

        mi = Gtk.MenuItem(label="Agregar un acceso rápido a la barra…")
        # Bloqueada: se ve en gris (igual que mover la barra), no se esconde.
        mi.set_sensitive(not self.locked)
        mi.connect("activate", lambda *_: self.open_anclados())
        menu.append(mi)

        menu.append(Gtk.SeparatorMenuItem())

        mi = Gtk.MenuItem(label="Administrador de tareas")
        mi.connect("activate", lambda *_: detached_run("@taskmgr"))
        menu.append(mi)

        mi = Gtk.MenuItem(label="Mostrar el escritorio")
        mi.connect("activate", self.toggle_show_desktop)
        menu.append(mi)

        menu.append(Gtk.SeparatorMenuItem())

        # Submenú: mover la barra a otro monitor (útil con 2-3 pantallas)
        disp = Gdk.Display.get_default()
        n = disp.get_n_monitors()
        if n > 1:
            mover = Gtk.MenuItem(label="Mover la barra a")
            sub = Gtk.Menu()
            for i in range(n):
                g = disp.get_monitor(i).get_geometry()
                prim = ""
                try:
                    if disp.get_monitor(i).is_primary():
                        prim = " · primario"
                except Exception:
                    pass
                actual = " ✓" if i == (self.monitor_index
                                       if self.monitor_index is not None
                                       else self._primary_index()) else ""
                it = Gtk.MenuItem(
                    label="Monitor %d  (%dx%d)%s%s" % (i + 1, g.width, g.height, prim, actual))
                it.connect("activate", lambda _w, idx=i: self.move_to_monitor(idx))
                sub.append(it)
            mover.set_submenu(sub)
            # Bloqueada: se muestra igual pero en gris, para que se vea que la
            # opción existe y que está deshabilitada a propósito.
            if self.locked:
                mover.set_sensitive(False)
            menu.append(mover)

        # Submenú: posición / orientación de la barra
        pos = Gtk.MenuItem(label="Posición de la barra")
        psub = Gtk.Menu()
        for lbl, e in (("Arriba", "top"), ("Abajo", "bottom"),
                       ("Izquierda (vertical)", "left"), ("Derecha (vertical)", "right")):
            it = Gtk.MenuItem(label=lbl + ("  ✓" if e == self.edge else ""))
            it.connect("activate", lambda _w, ed=e: self._set_edge(ed))
            psub.append(it)
        pos.set_submenu(psub)
        if self.locked:
            pos.set_sensitive(False)
        menu.append(pos)

        lock = Gtk.CheckMenuItem(label="Bloquear la barra")
        lock.set_active(self.locked)
        lock.connect("toggled", self._toggle_lock)
        menu.append(lock)

        menu.append(Gtk.SeparatorMenuItem())

        mi = Gtk.MenuItem(label="Buscar actualizaciones del panel")
        mi.connect("activate", self._check_update_manual)
        menu.append(mi)

        mi = Gtk.MenuItem(label="Configuración del sistema")
        mi.connect("activate", lambda *_: detached_run("cinnamon-settings"))
        menu.append(mi)

        mi = Gtk.MenuItem(label="Reiniciar el panel")
        mi.connect("activate", lambda *_: self._restart_self())
        menu.append(mi)

        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    # ---------- X11: strut + atajo global ----------
    def _on_realize(self, *_):
        if HAVE_XLIB:
            try:
                self._reserve_strut()
            except Exception as e:
                sys.stderr.write("strut: %s\n" % e)
            if self.primary:   # los atajos globales se registran una sola vez
                try:
                    self._setup_hotkeys()
                except Exception as e:
                    sys.stderr.write("hotkey: %s\n" % e)
                try:
                    self._setup_tray()
                except Exception as e:
                    sys.stderr.write("tray: %s\n" % e)
                try:
                    self._setup_sni_tray()
                except Exception as e:
                    sys.stderr.write("sni: %s\n" % e)

    def _reserve_strut(self):
        xid = self.get_window().get_xid()
        d = XDisplay()
        w = d.create_resource_object("window", xid)
        geo = self._geo
        sh = d.screen().height_in_pixels
        sw = d.screen().width_in_pixels
        th = self.height
        x1, x2 = geo.x, geo.x + geo.width - 1
        y1, y2 = geo.y, geo.y + geo.height - 1
        if self.edge == "top":
            v = geo.y + th
            strut = [0, 0, v, 0]
            partial = [0, 0, v, 0, 0, 0, x1, x2, 0, 0, 0, 0]
        elif self.edge == "bottom":
            v = sh - (geo.y + geo.height) + th
            strut = [0, 0, 0, v]
            partial = [0, 0, 0, v, 0, 0, 0, 0, 0, 0, x1, x2]
        elif self.edge == "left":
            v = geo.x + th
            strut = [v, 0, 0, 0]
            partial = [v, 0, 0, 0, y1, y2, 0, 0, 0, 0, 0, 0]
        else:  # right
            v = sw - (geo.x + geo.width) + th
            strut = [0, v, 0, 0]
            partial = [0, v, 0, 0, 0, 0, y1, y2, 0, 0, 0, 0]
        CARD = d.intern_atom("CARDINAL")
        w.change_property(d.intern_atom("_NET_WM_STRUT"), CARD, 32, strut)
        w.change_property(d.intern_atom("_NET_WM_STRUT_PARTIAL"), CARD, 32, partial)
        d.flush()

    def _setup_hotkeys(self):
        d = XDisplay()
        root = d.screen().root
        root.change_attributes(event_mask=X.KeyPressMask)
        combos = []
        # Ctrl+Shift+Esc -> administrador de tareas
        combos.append((XK.XK_Escape, X.ControlMask | X.ShiftMask, "@taskmgr"))
        # Súper -> Inicio (best-effort; suele estar tomada por el WM)
        combos.append((XK.XK_Super_L, 0, "@start"))
        masks_extra = (0, X.Mod2Mask, X.LockMask, X.Mod2Mask | X.LockMask)
        self._hotkey_map = {}
        for keysym, mod, action in combos:
            kc = d.keysym_to_keycode(keysym)
            if not kc:
                continue
            self._hotkey_map[(kc, mod)] = action
            for extra in masks_extra:
                try:
                    root.grab_key(kc, mod | extra, True,
                                  X.GrabModeAsync, X.GrabModeAsync)
                except Exception:
                    pass
        d.sync()
        self._xhotkey = d
        GLib.io_add_watch(d.fileno(), GLib.IO_IN, self._on_xevent)

    def _on_xevent(self, source, condition):
        d = self._xhotkey
        while d.pending_events():
            ev = d.next_event()
            if ev.type != X.KeyPress:
                continue
            mod = ev.state & (X.ControlMask | X.ShiftMask | X.Mod4Mask)
            # buscar acción ignorando Lock/Mod2
            action = None
            for (kc, m), a in self._hotkey_map.items():
                if ev.detail == kc:
                    action = a
                    break
            if action == "@start":
                GLib.idle_add(self.toggle_start_menu)
            elif action:
                GLib.idle_add(lambda a=action: detached_run(a))
            _ = mod
        return True

    # ---------- bandeja StatusNotifier / AppIndicator (host DBus) ----------
    _SNI_WATCHER_XML = """
    <node><interface name="org.kde.StatusNotifierWatcher">
      <method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
      <method name="RegisterStatusNotifierHost"><arg type="s" direction="in"/></method>
      <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
      <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
      <property name="ProtocolVersion" type="i" access="read"/>
      <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
      <signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
      <signal name="StatusNotifierHostRegistered"/>
    </interface></node>"""

    def _setup_sni_tray(self):
        """Host de StatusNotifier (AppIndicator): muestra en la bandeja los iconos
        de apps que NO usan XEmbed (FactuPOS Print/Bridge via pystray, etc.)."""
        self._sni_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._sni_items = {}          # service -> {box, busname, path}
        self._sni_regd = []           # lista de services (rol watcher)
        self._sni_node = Gio.DBusNodeInfo.new_for_xml(self._SNI_WATCHER_XML)
        self._sni_host = "org.kde.StatusNotifierHost-%d" % os.getpid()
        Gio.bus_own_name_on_connection(
            self._sni_bus, self._sni_host, Gio.BusNameOwnerFlags.NONE, None, None)
        # Intentar ser el Watcher; si ya existe (Cinnamon), actuar solo de host.
        Gio.bus_own_name_on_connection(
            self._sni_bus, "org.kde.StatusNotifierWatcher",
            Gio.BusNameOwnerFlags.NONE,
            lambda *_a: self._sni_become_watcher(),
            lambda *_a: self._sni_become_host())
        # Quitar items cuando su app se cierra.
        self._sni_bus.signal_subscribe(
            "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
            "/org/freedesktop/DBus", None, Gio.DBusSignalFlags.NONE,
            self._sni_name_owner_changed)

    def _sni_become_watcher(self):
        self._sni_bus.register_object(
            "/StatusNotifierWatcher", self._sni_node.interfaces[0],
            self._sni_watcher_call, self._sni_watcher_getprop, None)
        try:
            self._sni_bus.emit_signal(None, "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher", "StatusNotifierHostRegistered", None)
        except Exception:
            pass
        # DIFERIDO A PROPOSITO. Esto corre dentro del callback de "nombre
        # adquirido" de DBus; hacer ahi una llamada SINCRONA sobre la MISMA
        # conexion bloquea el despacho del bus, el panel se cuelga y el
        # keepalive.sh lo relanza -> se cerraba y abria solo, en bucle
        # (v1.5.50). Con idle_add corre despues, ya fuera del callback.
        GLib.idle_add(self._sni_adoptar_existentes)

    def _sni_adoptar_existentes(self):
        """Recoger los iconos de apps que YA estaban corriendo antes que el panel.

        Sin esto, un icono solo aparecia si la app llamaba a
        RegisterStatusNotifierItem, y las apps eso lo hacen UNA sola vez al
        arrancar. Al iniciar sesion, FactuPOS Print arranca por el autostart
        ANTES que el panel: se registra contra un Watcher que todavia no existe,
        se pierde, y el icono no sale nunca. El sintoma en campo era justo ese:
        "abro la app y no aparece en la bandeja; reinicio el panel y ya sale"
        — al reiniciarlo, el nombre del Watcher desaparece y vuelve, y ahi la
        libreria de la app se re-registra sola.
        Ahora el panel barre el bus al volverse Watcher y adopta lo que encuentre,
        sin importar quien arranco primero.
        """
        try:
            v = self._sni_bus.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus", "ListNames", None,
                GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, 2000, None)
        except Exception as e:
            sys.stderr.write("sni adoptar: %s\n" % e)
            return False          # no repetir el idle
        for nombre in v.unpack()[0]:
            if not nombre.startswith("org.kde.StatusNotifierItem"):
                continue
            service = nombre + "/StatusNotifierItem"
            if service in self._sni_regd:
                continue
            self._sni_regd.append(service)
            try:
                self._sni_bus.emit_signal(
                    None, "/StatusNotifierWatcher",
                    "org.kde.StatusNotifierWatcher", "StatusNotifierItemRegistered",
                    GLib.Variant("(s)", (service,)))
            except Exception:
                pass
            GLib.idle_add(self._sni_add_item, service)

        return False      # idle_add: correr UNA vez, no repetir

    def _sni_become_host(self):
        try:
            self._sni_bus.call_sync(
                "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher", "RegisterStatusNotifierHost",
                GLib.Variant("(s)", (self._sni_host,)), None,
                Gio.DBusCallFlags.NONE, -1, None)
        except Exception as e:
            sys.stderr.write("sni host: %s\n" % e)
        for sig in ("StatusNotifierItemRegistered", "StatusNotifierItemUnregistered"):
            self._sni_bus.signal_subscribe(
                None, "org.kde.StatusNotifierWatcher", sig, "/StatusNotifierWatcher",
                None, Gio.DBusSignalFlags.NONE, self._sni_watcher_signal)
        try:
            v = self._sni_bus.call_sync(
                "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                "org.freedesktop.DBus.Properties", "Get",
                GLib.Variant("(ss)", ("org.kde.StatusNotifierWatcher",
                                      "RegisteredStatusNotifierItems")),
                GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, -1, None)
            for svc in v.unpack()[0]:
                self._sni_add_item(svc)
        except Exception as e:
            sys.stderr.write("sni list: %s\n" % e)

    # --- rol watcher: handlers ---
    def _sni_watcher_call(self, conn, sender, path, iface, method, params, inv):
        if method == "RegisterStatusNotifierItem":
            arg = params.unpack()[0]
            service = (sender + arg) if arg.startswith("/") else (arg + "/StatusNotifierItem")
            if service not in self._sni_regd:
                self._sni_regd.append(service)
                conn.emit_signal(None, "/StatusNotifierWatcher",
                    "org.kde.StatusNotifierWatcher", "StatusNotifierItemRegistered",
                    GLib.Variant("(s)", (service,)))
                GLib.idle_add(self._sni_add_item, service)
            inv.return_value(None)
        elif method == "RegisterStatusNotifierHost":
            conn.emit_signal(None, "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher", "StatusNotifierHostRegistered", None)
            inv.return_value(None)
        else:
            inv.return_value(None)

    def _sni_watcher_getprop(self, conn, sender, path, iface, prop):
        if prop == "RegisteredStatusNotifierItems":
            return GLib.Variant("as", self._sni_regd)
        if prop == "IsStatusNotifierHostRegistered":
            return GLib.Variant("b", True)
        if prop == "ProtocolVersion":
            return GLib.Variant("i", 0)
        return None

    def _sni_watcher_signal(self, conn, sender, path, iface, signal, params):
        svc = params.unpack()[0]
        if signal == "StatusNotifierItemRegistered":
            self._sni_add_item(svc)
        else:
            self._sni_remove_item(svc)

    def _sni_name_owner_changed(self, conn, sender, path, iface, signal, params):
        name, old, new = params.unpack()
        if new == "":            # una app se fue
            for svc in list(self._sni_items):
                if svc.split("/", 1)[0] == name or svc.startswith(name):
                    self._sni_remove_item(svc)

    # --- render de los items ---
    def _sni_split(self, service):
        i = service.find("/")
        return (service, "/StatusNotifierItem") if i < 0 else (service[:i], service[i:])

    def _sni_prop(self, busname, path, name):
        v = self._sni_bus.call_sync(
            busname, path, "org.freedesktop.DBus.Properties", "Get",
            GLib.Variant("(ss)", ("org.kde.StatusNotifierItem", name)),
            GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 2000, None)
        return v.unpack()[0]

    def _sni_programa(self, busname):
        """Línea de comando del programa dueño de un ícono de la bandeja (vía DBus → PID →
        /proc). RustDesk no se anuncia con un nombre que diga «rustdesk» (#2942): hay que
        preguntar QUIÉN es."""
        try:
            pid = self._sni_bus.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                "GetConnectionUnixProcessID", GLib.Variant("(s)", (busname,)),
                GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 2000, None).unpack()[0]
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                return f.read().replace(b"\0", b" ").decode("utf-8", "replace")
        except Exception:
            return ""

    def _sni_add_item(self, service):
        if service in self._sni_items:
            return
        busname, path = self._sni_split(service)
        ev = Gtk.EventBox()
        ev.set_visible_window(False)
        img = Gtk.Image()
        ev.add(img)
        ev.connect("button-press-event", self._sni_click, service)
        ev.connect("scroll-event", self._sni_scroll, service)
        self._sni_items[service] = {"box": ev, "img": img, "busname": busname, "path": path,
                                    "programa": self._sni_programa(busname)}
        self._tray_box.pack_start(ev, False, False, 1)
        ev.show_all()
        self._sni_refresh_icon(service)
        for sig in ("NewIcon", "NewAttentionIcon", "NewStatus", "NewToolTip"):
            self._sni_bus.signal_subscribe(
                busname, "org.kde.StatusNotifierItem", sig, path, None,
                Gio.DBusSignalFlags.NONE,
                lambda *a, s=service: GLib.idle_add(self._sni_refresh_icon, s))

    def _sni_remove_item(self, service):
        it = self._sni_items.pop(service, None)
        if it:
            it["box"].destroy()
        if service in self._sni_regd:
            self._sni_regd.remove(service)

    def _sni_refresh_icon(self, service):
        it = self._sni_items.get(service)
        if not it:
            return False
        busname, path, img = it["busname"], it["path"], it["img"]
        px = None
        name = theme_path = ""
        try:
            theme_path = self._sni_prop(busname, path, "IconThemePath") or ""
        except Exception:
            pass
        try:
            name = self._sni_prop(busname, path, "IconName") or ""
        except Exception:
            pass
        try:
            sni_id = self._sni_prop(busname, path, "Id") or ""
        except Exception:
            sni_id = ""
        try:
            # 0) RustDesk: la diadema de Soporte Remoto FactuPOS (#2942)
            if es_soporte(sni_id, name, busname, it.get("programa")):
                px = icono_soporte(22)
            # 1) IconName como ruta absoluta a un archivo
            if px is None and name and name.startswith("/") and os.path.exists(name):
                px = GdkPixbuf.Pixbuf.new_from_file_at_size(name, 22, 22)
            # 2) IconThemePath + IconName (lo que usa pystray/appindicator)
            if px is None and name and theme_path:
                for ext in (".png", ".svg", ".xpm", ""):
                    fp = os.path.join(theme_path, name + ext)
                    if os.path.exists(fp):
                        px = GdkPixbuf.Pixbuf.new_from_file_at_size(fp, 22, 22)
                        break
            # 3) IconPixmap (datos crudos ARGB)
            if px is None:
                px = self._sni_pixmap(busname, path)
            # 4) nombre de icono del tema
            if px is None and name and not name.startswith("/"):
                try:
                    px = Gtk.IconTheme.get_default().load_icon(name, 22, 0)
                except Exception:
                    px = None
        except Exception as e:
            sys.stderr.write("sni icon err: %s\n" % e)
        sys.stderr.write("sni icon: name=%r theme=%r -> %s\n"
                         % (name, theme_path, "ok" if px is not None else "GENERICO"))
        if px is not None:
            img.set_from_pixbuf(px)
        else:
            img.set_from_icon_name("application-x-executable", Gtk.IconSize.MENU)
        try:
            tt = self._sni_prop(busname, path, "Title")
            if tt:
                it["box"].set_tooltip_text(str(tt))
        except Exception:
            pass
        return False

    def _sni_pixmap(self, busname, path):
        """Convierte IconPixmap (ARGB32 big-endian) al pixbuf mas grande disponible."""
        try:
            arr = self._sni_prop(busname, path, "IconPixmap")
        except Exception:
            return None
        if not arr:
            return None
        best = max(arr, key=lambda t: t[0] * t[1])
        w, h, data = best[0], best[1], bytes(best[2])
        if w <= 0 or h <= 0 or len(data) < w * h * 4:
            return None
        out = bytearray(len(data))
        for i in range(0, w * h * 4, 4):       # ARGB -> RGBA
            out[i] = data[i + 1]
            out[i + 1] = data[i + 2]
            out[i + 2] = data[i + 3]
            out[i + 3] = data[i]
        pb = GdkPixbuf.Pixbuf.new_from_bytes(
            GLib.Bytes.new(bytes(out)), GdkPixbuf.Colorspace.RGB, True, 8, w, h, w * 4)
        return pb.scale_simple(22, 22, GdkPixbuf.InterpType.BILINEAR)

    def _sni_click(self, widget, event, service):
        it = self._sni_items.get(service)
        if not it:
            return True
        busname, path = it["busname"], it["path"]
        x, y = int(event.x_root), int(event.y_root)
        if event.button == 2:
            self._sni_invoke(busname, path, "SecondaryActivate", x, y)
            return True
        menupath = ""
        try:
            menupath = self._sni_prop(busname, path, "Menu") or ""
        except Exception:
            menupath = ""
        if event.button == 1:
            # Clic izq.: abrir la app directo. Si es menu-only (Print/Bridge),
            # dispara su item tipo "Mostrar"; si no lo hay, muestra el menu.
            if menupath:
                did = self._sni_default_item(busname, menupath)
                if did is not None:
                    self._dbusmenu_event(busname, menupath, did)
                else:
                    self._sni_show_dbusmenu(busname, menupath, widget)
            else:
                self._sni_invoke(busname, path, "Activate", x, y)
        else:
            # Clic der.: menu completo.
            if menupath:
                self._sni_show_dbusmenu(busname, menupath, widget)
            else:
                self._sni_invoke(busname, path, "ContextMenu", x, y)
        return True   # frena la propagacion -> el panel no abre TAMBIEN su menu

    _SNI_SHOW_WORDS = ("mostrar", "show", "abrir", "open", "restaurar", "ventana", "ver")

    def _sni_default_item(self, busname, menupath):
        """Busca en el dbusmenu un item hoja tipo 'Mostrar/Abrir' (para el clic
        izq.). Devuelve su id, o None si no hay (se muestra el menu completo)."""
        try:
            v = self._sni_bus.call_sync(
                busname, menupath, "com.canonical.dbusmenu", "GetLayout",
                GLib.Variant("(iias)", (0, -1, [])),
                GLib.VariantType("(u(ia{sv}av))"), Gio.DBusCallFlags.NONE, 3000, None)
            _rev, layout = v.unpack()
        except Exception:
            return None
        found = [None]

        def walk(node):
            if found[0] is not None:
                return
            nid, props, children = node
            label = (props.get("label", "") or "").replace("_", "").strip().lower()
            is_sep = props.get("type", "") == "separator"
            if (not children and not is_sep and props.get("enabled", True)
                    and props.get("visible", True)
                    and any(w in label for w in self._SNI_SHOW_WORDS)):
                found[0] = nid
                return
            for c in children:
                walk(c)
        for c in layout[2]:
            walk(c)
        return found[0]

    def _sni_scroll(self, widget, event, service):
        it = self._sni_items.get(service)
        if not it:
            return
        delta = -1 if event.direction == Gdk.ScrollDirection.UP else 1
        try:
            self._sni_bus.call(
                it["busname"], it["path"], "org.kde.StatusNotifierItem", "Scroll",
                GLib.Variant("(is)", (delta, "vertical")), None,
                Gio.DBusCallFlags.NONE, -1, None, None, None)
        except Exception:
            pass

    def _sni_invoke(self, busname, path, method, x, y):
        try:
            self._sni_bus.call(
                busname, path, "org.kde.StatusNotifierItem", method,
                GLib.Variant("(ii)", (x, y)), None,
                Gio.DBusCallFlags.NONE, -1, None, None, None)
        except Exception as e:
            sys.stderr.write("sni %s: %s\n" % (method, e))

    # --- menu via com.canonical.dbusmenu ---
    def _sni_show_dbusmenu(self, busname, menupath, anchor):
        try:
            v = self._sni_bus.call_sync(
                busname, menupath, "com.canonical.dbusmenu", "GetLayout",
                GLib.Variant("(iias)", (0, -1, [])),
                GLib.VariantType("(u(ia{sv}av))"), Gio.DBusCallFlags.NONE, 3000, None)
            _rev, layout = v.unpack()
        except Exception as e:
            sys.stderr.write("dbusmenu: %s\n" % e)
            return
        menu = Gtk.Menu()
        for child in layout[2]:
            mi = self._dbusmenu_item(busname, menupath, child)
            if mi:
                menu.append(mi)
        menu.show_all()
        menu.popup_at_widget(anchor, Gdk.Gravity.NORTH, Gdk.Gravity.SOUTH, None)

    def _dbusmenu_item(self, busname, menupath, node):
        nid, props, children = node
        if props.get("visible", True) is False:
            return None
        if props.get("type", "") == "separator":
            return Gtk.SeparatorMenuItem()
        label = (props.get("label", "") or "").replace("_", "")
        mi = Gtk.MenuItem(label=label)
        if props.get("enabled", True) is False:
            mi.set_sensitive(False)
        if children:
            sub = Gtk.Menu()
            for c in children:
                ci = self._dbusmenu_item(busname, menupath, c)
                if ci:
                    sub.append(ci)
            mi.set_submenu(sub)
        else:
            mi.connect("activate", lambda _w, i=nid: self._dbusmenu_event(busname, menupath, i))
        return mi

    def _dbusmenu_event(self, busname, menupath, nid):
        try:
            self._sni_bus.call(
                busname, menupath, "com.canonical.dbusmenu", "Event",
                GLib.Variant("(isvu)", (nid, "clicked", GLib.Variant("s", ""), 0)),
                None, Gio.DBusCallFlags.NONE, -1, None, None, None)
        except Exception as e:
            sys.stderr.write("dbusmenu event: %s\n" % e)

    # ---------- bandeja del sistema (XEmbed) ----------
    def _setup_tray(self):
        """Se vuelve el 'System Tray manager': las apps (AnyDesk, RustDesk,
        Telegram...) piden meter su icono y los embebemos en la barra."""
        d = XDisplay()
        self._traydisp = d
        screen = d.screen()
        root = screen.root
        sn = d.get_default_screen()
        self._tray_sel = d.intern_atom("_NET_SYSTEM_TRAY_S%d" % sn)
        self._atom_opcode = d.intern_atom("_NET_SYSTEM_TRAY_OPCODE")
        self._tray_manager_atom = d.intern_atom("MANAGER")
        orient_atom = d.intern_atom("_NET_SYSTEM_TRAY_ORIENTATION")
        win = root.create_window(
            -1, -1, 1, 1, 0, screen.root_depth,
            window_class=X.InputOutput, visual=X.CopyFromParent,
            background_pixel=screen.black_pixel,
            event_mask=X.StructureNotifyMask | X.PropertyChangeMask)
        self._traywin = win
        win.change_property(orient_atom, Xatom.CARDINAL, 32,
                            [1 if self.vertical else 0])
        # set_selection_owner es método de la VENTANA, no del Display (python-xlib).
        win.set_selection_owner(self._tray_sel, X.CurrentTime)
        d.sync()
        if d.get_selection_owner(self._tray_sel).id != win.id:
            sys.stderr.write("tray: no se pudo tomar la selección (otro tray activo)\n")
        self._tray_announce()
        GLib.io_add_watch(d.fileno(), GLib.IO_IN, self._on_tray_event)

    def _tray_announce(self):
        """Avisa al sistema que ya hay un tray manager -> las apps re-aparecen."""
        d = self._traydisp
        root = d.screen().root
        ev = Xevent.ClientMessage(
            window=root, client_type=self._tray_manager_atom,
            data=(32, [X.CurrentTime, self._tray_sel, self._traywin.id, 0, 0]))
        root.send_event(ev, event_mask=X.StructureNotifyMask)
        d.sync()

    def _on_tray_event(self, source, condition):
        d = self._traydisp
        while d.pending_events():
            ev = d.next_event()
            if ev.type == X.ClientMessage and ev.client_type == self._atom_opcode:
                try:
                    fmt, data = ev.data
                except Exception:
                    continue
                if fmt == 32 and data[1] == 0:        # SYSTEM_TRAY_REQUEST_DOCK
                    GLib.idle_add(self._tray_embed, data[2])
        return True

    def _tray_embed(self, xid):
        box = getattr(self, "_tray_box", None)
        if box is None:
            return False
        try:
            icon = max(16, min(self.height - 6, 24))
            sock = Gtk.Socket()
            sock.set_size_request(icon, icon)
            # NO estirar a la altura de la barra: centrar al tamaño del icono
            # (si no, el plug -AnyDesk- se estira a lo alto del panel).
            sock.set_valign(Gtk.Align.CENTER)
            sock.set_halign(Gtk.Align.CENTER)
            sock.set_vexpand(False)
            sock.set_hexpand(False)
            box.pack_start(sock, False, False, 1)
            box.show_all()

            def _embed(*_a):
                # add_id debe correr con el socket YA realizado, si no el XEMBED
                # no completa y el icono queda 1x1 sin mapear.
                try:
                    sock.add_id(xid)
                    self._tray_force_size(xid, icon)
                    # Algunas apps (AnyDesk) se RE-dimensionan grandes despues de
                    # embeber -> re-forzar el tamaño varias veces.
                    for delay in (120, 350, 800, 1600, 3000):
                        GLib.timeout_add(delay, self._tray_force_size, xid, icon)
                except Exception as e:
                    sys.stderr.write("tray embed (realize): %s\n" % e)
                return False

            if sock.get_realized():
                _embed()
            else:
                sock.connect("realize", _embed)
            # Clamp: si el plug (AnyDesk) se vuelve a agrandar, re-achicarlo.
            sock._fp_clamp = 0

            def _clamp(s, alloc, _xid=xid, _icon=icon):
                if (alloc.width > _icon + 1 or alloc.height > _icon + 1) and s._fp_clamp < 40:
                    s._fp_clamp += 1
                    s.set_size_request(_icon, _icon)
                    GLib.idle_add(self._tray_force_size, _xid, _icon)
            sock.connect("size-allocate", _clamp)
            # si la app cierra su icono, soltar el socket
            sock.connect("plug-removed", lambda _s: (_s.destroy() or True))
        except Exception as e:
            sys.stderr.write("tray embed: %s\n" % e)
        return False

    def _tray_force_size(self, xid, icon):
        """Re-fuerza el tamaño del icono XEmbed (apps que se re-agrandan: AnyDesk,
        indicador de teclado, etc.). Además del configure, fija hints min=max=icono
        en WM_NORMAL_HINTS (las apps que ignoran el configure suelen respetar esto)."""
        try:
            w = self._traydisp.create_resource_object("window", xid)
            try:
                # PMinSize (1<<4) | PMaxSize (1<<5) = 48
                w.set_wm_normal_hints(
                    flags=48, min_width=icon, min_height=icon,
                    max_width=icon, max_height=icon)
            except Exception:
                pass
            w.configure(width=icon, height=icon)
            w.map()
            self._traydisp.sync()
        except Exception:
            pass
        return False   # no repetir el timeout


def _wait_for_wm(timeout=25.0):
    """Bloquea hasta que el gestor de ventanas EWMH esté activo (la raíz tiene
    _NET_SUPPORTING_WM_CHECK) o se agote el tiempo. En el login el panel puede
    arrancar ANTES que muffin/cinnamon; si el tasklist (Wnck) nace sin WM, la
    lista de ventanas abiertas queda VACÍA para siempre. Por eso esperamos al WM
    antes de crear la barra."""
    if not HAVE_XLIB:
        return
    try:
        d = XDisplay()
    except Exception:
        return
    try:
        root = d.screen().root
        atom = d.intern_atom("_NET_SUPPORTING_WM_CHECK")
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                p = root.get_full_property(atom, X.AnyPropertyType)
                if p is not None and p.value:
                    return
            except Exception:
                pass
            time.sleep(0.3)
    finally:
        try:
            d.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description="FactuPOS Panel")
    ap.add_argument("--edge", choices=["bottom", "top", "left", "right"], default="bottom",
                    help="borde de la pantalla: bottom/top (horizontal) o left/right (vertical)")
    ap.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    ap.add_argument("--monitor", default=None,
                    help="índice de monitor (0,1,2...), 'all' para TODOS, o vacío = primario")
    ap.add_argument("--list-monitors", action="store_true",
                    help="lista los monitores detectados y sale")
    args = ap.parse_args()

    if args.list_monitors:
        disp = Gdk.Display.get_default()
        for i in range(disp.get_n_monitors()):
            m = disp.get_monitor(i)
            g = m.get_geometry()
            prim = " (primario)" if (hasattr(disp, "get_primary_monitor")
                                     and disp.get_monitor(i) == disp.get_primary_monitor()) else ""
            model = ""
            try:
                model = m.get_model() or ""
            except Exception:
                pass
            print("Monitor %d: %dx%d en (%d,%d) %s%s"
                  % (i, g.width, g.height, g.x, g.y, model, prim))
        return

    # Wnck necesita un nombre de aplicación.
    try:
        Wnck.set_client_type(Wnck.ClientType.PAGER)
    except Exception:
        pass

    # Esperar a que el WM esté listo ANTES de crear la barra (si no, el tasklist
    # queda vacío al autoarrancar en el login). Ver _wait_for_wm().
    _wait_for_wm(25.0)

    # ¿En qué monitores? "all" = todos; un número = ese; vacío = primario.
    global MONITOR_ALL, PANEL_ARGS
    PANEL_ARGS = {"edge": args.edge, "height": args.height}
    if args.monitor is None:
        monitors = [None]
    elif str(args.monitor).lower() == "all":
        MONITOR_ALL = True
        monitors = list(range(Gdk.Display.get_default().get_n_monitors()))
    else:
        try:
            monitors = [int(args.monitor)]
        except ValueError:
            monitors = [None]

    # Una barra por monitor (en UN solo proceso). Solo la 1a es "primaria"
    # (maneja atajos globales y auto-actualización; las demás solo se muestran).
    panels = []
    for idx, m in enumerate(monitors):
        p = Panel(edge=args.edge, height=args.height, monitor=m, primary=(idx == 0))
        p.show_all()
        panels.append(p)

    # Escuchar cambios de pantallas (resolución, monitor conectado/desconectado)
    # para re-acomodar las barras solas. Ver resync_monitors().
    scr = Gdk.Screen.get_default()
    if scr is not None:
        for sig in ("monitors-changed", "size-changed"):
            try:
                scr.connect(sig, schedule_resync)
            except Exception:
                pass
    disp = Gdk.Display.get_default()
    if disp is not None:
        for sig in ("monitor-added", "monitor-removed"):
            try:
                disp.connect(sig, schedule_resync)
            except Exception:
                pass
    # Repaso al arrancar: el escritorio suele terminar de acomodar los monitores
    # unos segundos DESPUÉS del login (por eso había que reiniciar el panel a mano).
    for _d in (2, 5, 10, 20, 40):
        GLib.timeout_add_seconds(_d, resync_monitors)

    # #3654: que la próxima vez la barra vuelva a salir sola al iniciar sesión.
    GLib.timeout_add_seconds(3, vigilar_autoarranque)

    Gtk.main()


if __name__ == "__main__":
    main()
