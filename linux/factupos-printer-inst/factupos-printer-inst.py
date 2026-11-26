#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# FactuPOS · Instalador de Impresoras  (factupos-printer-inst)
# Asistente grafico para instalar impresoras USB / Serial (tickets Epson TM, etc.)
# como cola RAW en CUPS. No requiere pycups: usa lpadmin/lpinfo via un helper con pkexec.
# FactuPOS / Soporte Real - https://soportereal.com

import os
import sys
import json
import glob
import shutil
import threading
import subprocess
import urllib.request

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib  # noqa: E402

try:
    import serial  # pyserial
    HAVE_SERIAL = True
except Exception:
    HAVE_SERIAL = False

VERSION = "1.0.0"                                # fuente única de versión

# Auto-actualización (mismo esquema que factupos-panel): lee el manifest publicado,
# y si hay versión nueva baja el .py a una carpeta del usuario (sin root) y reinicia.
UPDATE_BASE = "https://soportereal.com/software/factupos-app/linux"
UPDATE_MANIFEST = UPDATE_BASE + "/Factupos-Printer-Inst_version.json"
UPDATE_PY_LOCAL = os.path.expanduser(
    "~/.local/share/factupos-printer-inst/factupos-printer-inst.py")
UPDATE_INTERVAL = 6 * 3600                       # re-chequeo cada 6 horas


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

CSS = b"""
.fp-title { font-size: 18px; font-weight: bold; }
.fp-sub   { color: #6b7280; }
.fp-step  { color: #2563eb; font-weight: bold; }
.fp-log   { font-family: monospace; font-size: 11px; }
"""


def sh(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


class Wizard(Gtk.Window):
    def __init__(self):
        super().__init__(title="FactuPOS · Instalador de Impresoras")
        self.set_default_size(680, 520)
        self.set_position(Gtk.WindowPosition.CENTER)

        self.conn_type = "serial"
        self._found = []

        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)

        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        head.set_border_width(14)
        t = Gtk.Label(label="FactuPOS · Instalador de Impresoras", xalign=0)
        t.get_style_context().add_class("fp-title")
        s = Gtk.Label(label="Asistente para impresoras USB y Serial (tickets) · v" + VERSION,
                      xalign=0)
        s.get_style_context().add_class("fp-sub")
        head.pack_start(t, False, False, 0)
        head.pack_start(s, False, False, 0)
        root.pack_start(head, False, False, 0)
        root.pack_start(Gtk.Separator(), False, False, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_border_width(16)
        root.pack_start(self.stack, True, True, 0)

        self._page_type()
        self._page_device()
        self._page_config()
        self._page_install()
        self._page_done()

        root.pack_start(Gtk.Separator(), False, False, 0)
        self.logbuf = Gtk.TextBuffer()
        logview = Gtk.TextView(buffer=self.logbuf)
        logview.set_editable(False)
        logview.set_cursor_visible(False)
        logview.get_style_context().add_class("fp-log")
        logsc = Gtk.ScrolledWindow()
        logsc.set_min_content_height(90)
        logsc.add(logview)
        root.pack_start(logsc, False, False, 0)

        nav = Gtk.Box(spacing=8)
        nav.set_border_width(12)
        self.btn_back = Gtk.Button(label="Atras")
        self.btn_back.connect("clicked", self.on_back)
        self.btn_next = Gtk.Button(label="Siguiente")
        self.btn_next.get_style_context().add_class("suggested-action")
        self.btn_next.connect("clicked", self.on_next)
        btn_close = Gtk.Button(label="Cerrar")
        btn_close.connect("clicked", lambda *_: self.destroy())
        btn_upd = Gtk.Button(label="Verificar versión")
        btn_upd.set_tooltip_text("Buscar e instalar la última versión (v%s)" % VERSION)
        btn_upd.connect("clicked", self._check_update_manual)
        nav.pack_start(btn_close, False, False, 0)
        nav.pack_start(btn_upd, False, False, 0)
        nav.pack_end(self.btn_next, False, False, 0)
        nav.pack_end(self.btn_back, False, False, 0)
        root.pack_start(nav, False, False, 0)

        self.pages = ["type", "device", "config", "install", "done"]
        self.idx = 0
        self._show()

    # ---------- paginas ----------
    def _page_type(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        lab = Gtk.Label(label="Paso 1 · Como esta conectada la impresora?", xalign=0)
        lab.get_style_context().add_class("fp-step")
        box.pack_start(lab, False, False, 0)
        self.rb_serial = Gtk.RadioButton.new_with_label_from_widget(
            None, "Serial  (adaptador USB->Serial, ej. tickets Epson TM-U220)")
        self.rb_usb = Gtk.RadioButton.new_with_label_from_widget(
            self.rb_serial, "USB directo")
        self.rb_serial.set_active(True)
        box.pack_start(self.rb_serial, False, False, 0)
        box.pack_start(self.rb_usb, False, False, 0)
        self.stack.add_named(box, "type")

    def _page_device(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        lab = Gtk.Label(label="Paso 2 · Elegi el dispositivo", xalign=0)
        lab.get_style_context().add_class("fp-step")
        box.pack_start(lab, False, False, 0)
        self.combo_dev = Gtk.ComboBoxText()
        box.pack_start(self.combo_dev, False, False, 0)
        b = Gtk.Button(label="Volver a detectar")
        b.connect("clicked", lambda *_: self.detect_devices())
        box.pack_start(b, False, False, 0)
        self.lbl_dev_hint = Gtk.Label(label="", xalign=0)
        self.lbl_dev_hint.get_style_context().add_class("fp-sub")
        box.pack_start(self.lbl_dev_hint, False, False, 0)
        self.stack.add_named(box, "device")

    def _page_config(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        lab = Gtk.Label(label="Paso 3 · Configurar y probar", xalign=0)
        lab.get_style_context().add_class("fp-step")
        box.pack_start(lab, False, False, 0)

        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label="Nombre:"), False, False, 0)
        self.ent_name = Gtk.Entry()
        self.ent_name.set_text("TM-U220")
        row.pack_start(self.ent_name, True, True, 0)
        box.pack_start(row, False, False, 0)

        self.serial_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        rowb = Gtk.Box(spacing=8)
        rowb.pack_start(Gtk.Label(label="Velocidad (baud):"), False, False, 0)
        self.combo_baud = Gtk.ComboBoxText()
        for b in BAUDS:
            self.combo_baud.append_text(b)
        self.combo_baud.set_active(0)
        rowb.pack_start(self.combo_baud, False, False, 0)
        rowb.pack_start(Gtk.Label(label="   Flujo:"), False, False, 0)
        self.combo_flow = Gtk.ComboBoxText()
        for f in FLOWS:
            self.combo_flow.append_text(f)
        self.combo_flow.set_active(0)  # dtrdsr
        rowb.pack_start(self.combo_flow, False, False, 0)
        self.serial_box.pack_start(rowb, False, False, 0)

        rowt = Gtk.Box(spacing=8)
        self.btn_sweep = Gtk.Button(label="Probar todas las velocidades")
        self.btn_sweep.connect("clicked", self.on_sweep)
        self.btn_test = Gtk.Button(label="Imprimir prueba (velocidad elegida)")
        self.btn_test.connect("clicked", self.on_test)
        rowt.pack_start(self.btn_sweep, False, False, 0)
        rowt.pack_start(self.btn_test, False, False, 0)
        self.serial_box.pack_start(rowt, False, False, 0)

        hint = Gtk.Label(
            label="Mira la impresora: la velocidad correcta imprime texto legible.\n"
                  "Si salen garabatos, esa NO es la velocidad. La TM-U220 usa cola RAW (ESC/POS).",
            xalign=0)
        hint.get_style_context().add_class("fp-sub")
        self.serial_box.pack_start(hint, False, False, 0)
        box.pack_start(self.serial_box, False, False, 0)
        self.stack.add_named(box, "config")

    def _page_install(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        lab = Gtk.Label(label="Paso 4 · Instalar", xalign=0)
        lab.get_style_context().add_class("fp-step")
        box.pack_start(lab, False, False, 0)
        self.lbl_summary = Gtk.Label(label="", xalign=0)
        self.lbl_summary.set_line_wrap(True)
        box.pack_start(self.lbl_summary, False, False, 0)
        info = Gtk.Label(
            label="Al presionar Instalar puede pedir la contrasena UNA vez "
                  "(normal, como el control de Windows). Crea la cola RAW en CUPS.",
            xalign=0)
        info.get_style_context().add_class("fp-sub")
        box.pack_start(info, False, False, 0)
        self.stack.add_named(box, "install")

    def _page_done(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.lbl_done = Gtk.Label(label="Listo!", xalign=0)
        self.lbl_done.get_style_context().add_class("fp-title")
        box.pack_start(self.lbl_done, False, False, 0)
        self.lbl_done2 = Gtk.Label(label="", xalign=0)
        self.lbl_done2.set_line_wrap(True)
        box.pack_start(self.lbl_done2, False, False, 0)
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
        if b"Instalador de Impresoras" not in data or b"def main(" not in data:
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

    def detect_devices(self):
        self.conn_type = "serial" if self.rb_serial.get_active() else "usb"
        self.combo_dev.remove_all()
        found = []
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
            for p in ports:
                txt = p + ("  (" + descs[p] + ")" if descs.get(p) else "")
                self.combo_dev.append_text(txt)
                found.append(p)
            self.lbl_dev_hint.set_text(
                "Adaptadores serial detectados: %d" % len(found) if found else
                "No detecte adaptadores. Conecta el cable USB->Serial y toca 'Volver a detectar'.")
        else:
            self.log("Detectando impresoras USB (puede pedir contrasena)...")
            rc, out = sh(["pkexec", HELPER, "detect-usb"])
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("usb://"):
                    self.combo_dev.append_text(line)
                    found.append(line)
            self.lbl_dev_hint.set_text(
                "Impresoras USB detectadas: %d" % len(found) if found else
                "No detecte impresoras USB encendidas/conectadas.")
        if found:
            self.combo_dev.set_active(0)
        self._found = found

    def _current_device(self):
        return (self.combo_dev.get_active_text() or "").split("  (")[0].strip()

    def on_sweep(self, *_):
        port = self._current_device()
        if not port:
            self.log("Primero elegi un puerto en el paso anterior.")
            return
        self.btn_sweep.set_sensitive(False)
        self.log("Probando velocidades en %s ..." % port)

        def run():
            import time
            for b in BAUDS:
                ok = self._serial_write(port, b,
                                        "\n==== VELOCIDAD %s ====\nFactuPOS prueba\n\n\n" % b)
                self.log(("  enviado a %s baud" % b) if ok else ("  ERROR a %s baud" % b))
                time.sleep(2)
            self.log("Barrido terminado. Elegi la velocidad que salio legible.")
            GLib.idle_add(self.btn_sweep.set_sensitive, True)
        threading.Thread(target=run, daemon=True).start()

    def on_test(self, *_):
        port = self._current_device()
        b = self.combo_baud.get_active_text() or "9600"
        # ESC @ (init) + texto + avances de linea
        data = "\x1b@FactuPOS - Soporte Real\n--- PRUEBA TM-U220 ---\n%s @ %s baud\nOK!\n\n\n\n" % (port, b)
        ok = self._serial_write(port, b, data)
        self.log("Prueba enviada a %s @ %s baud" % (port, b) if ok else "ERROR enviando prueba")

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

    def do_install(self):
        name = (self.ent_name.get_text() or "Impresora").strip().replace(" ", "_")
        port = self._current_device()
        if self.conn_type == "serial":
            b = self.combo_baud.get_active_text() or "9600"
            flow = self.combo_flow.get_active_text() or "dtrdsr"
            uri = "serial:%s?baud=%s+bits=8+parity=none+flow=%s" % (port, b, flow)
        else:
            uri = port
        self.log("Instalando '%s' -> %s" % (name, uri))
        rc, out = sh(["pkexec", HELPER, "apply", "--name", name, "--uri", uri])
        self.log(out.strip())
        if rc == 0 and "APPLY_OK" in out:
            self.lbl_done.set_text("Listo! Impresora instalada.")
            self.lbl_done2.set_text(
                "'%s' quedo instalada como cola RAW y por defecto.\n"
                "Probala desde cualquier programa." % name)
        else:
            self.lbl_done.set_text("No se pudo instalar")
            self.lbl_done2.set_text("Detalle:\n" + out.strip()[:800])

    # ---------- navegacion ----------
    def _show(self):
        name = self.pages[self.idx]
        self.stack.set_visible_child_name(name)
        self.btn_back.set_sensitive(self.idx > 0)
        self.btn_next.set_label("Instalar" if name == "install"
                                else ("Finalizar" if name == "done" else "Siguiente"))
        if name == "device":
            self.detect_devices()
        if name == "config":
            self.serial_box.set_visible(self.conn_type == "serial")
        if name == "install":
            port = self._current_device()
            if self.conn_type == "serial":
                b = self.combo_baud.get_active_text() or "9600"
                flow = self.combo_flow.get_active_text() or "dtrdsr"
                det = "Serial %s @ %s baud (8N1, flow=%s) · cola RAW" % (port, b, flow)
            else:
                det = "USB: %s · cola RAW" % port
            self.lbl_summary.set_text(
                "Nombre:  %s\nConexion:  %s" %
                ((self.ent_name.get_text() or "Impresora"), det))

    def on_back(self, *_):
        if self.idx > 0:
            self.idx -= 1
            self._show()

    def on_next(self, *_):
        name = self.pages[self.idx]
        if name == "device" and not self._current_device():
            self.log("Elegi un dispositivo (o conecta el adaptador y 'Volver a detectar').")
            return
        if name == "install":
            self.do_install()
            self.idx += 1
            self._show()
            return
        if name == "done":
            self.destroy()
            return
        self.idx += 1
        self._show()


def main():
    w = Wizard()
    w.connect("destroy", Gtk.main_quit)
    w.show_all()
    w.serial_box.set_visible(True)
    # Auto-update: un chequeo al arrancar (a los 20s) y luego cada UPDATE_INTERVAL.
    GLib.timeout_add_seconds(20, lambda: (w._check_update_loop(), False)[1])
    GLib.timeout_add_seconds(UPDATE_INTERVAL, w._check_update_loop)
    Gtk.main()


if __name__ == "__main__":
    main()
