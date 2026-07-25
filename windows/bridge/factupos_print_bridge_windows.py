#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FactuPOS Print Bridge (Windows)
===============================
Equivalente Windows del Print Bridge Linux / APK Bridge de Android.
Servidor HTTP local en 127.0.0.1:8765 que recibe tiquetes desde la web de
FactuPOS (ruta "APK Bridge") y los imprime por el PUERTO COM que Windows crea
al emparejar una impresora Bluetooth Classic (SPP) — usando pyserial.

Mismo protocolo que los otros bridges (/ping, /print, CORS + PNA), asi la web
lo detecta igual. NO depende de Web Bluetooth.

Diferencia con el de Linux: Linux usa socket RFCOMM nativo; Windows usa el
puerto serie COM (ej. COM5) que el sistema asigna a la impresora BT emparejada.

Empaquetado: PyInstaller -> .exe (ver build_windows.bat / factupos-print-bridge.spec).
Dependencias: pyserial, pystray, pillow.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import serial                      # pyserial
    import serial.tools.list_ports as list_ports
except Exception:
    serial = None
    list_ports = None

# Version del Bridge Windows. Debe COINCIDIR con la publicada en el manifest
# (Factupos-Bridge_version.json) para no entrar en loop de auto-update.
VERSION = "1.2"

# Auto-update: el Bridge no se conecta a ningun server (es un HTTP local), asi
# que chequea un manifest propio al arrancar y cada UPDATE_CHECK_INTERVAL.
# Manifest nuevo (nombre = app). El viejo bridge_windows_version.json se deja
# publicado como ALIAS temporal para las instalaciones que aun leen esa URL.
UPDATE_MANIFEST_URL = "https://factupos.com/downloads/Factupos-Bridge_version.json"
UPDATE_CHECK_INTERVAL = 6 * 3600  # 6 horas

HOST = "127.0.0.1"
PORT = 8765

# Carpeta de datos: junto al .exe (o al .py)
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "bridge_config.json")
LOG_PATH = os.path.join(BASE_DIR, "bridge.log")

DEFAULT_CONFIG = {
    "printer_name": "",            # vacio = autodetectar
    "com_port": "",               # ej. "COM5"; vacio = autodetectar puerto BT
    "baudrate": 9600,
    "encoding": "cp858",
    "reset_init": True,
    "codepage_cmd": [27, 116, 19],  # ESC t 19 = PC858
    "cut_paper": False,
    "write_timeout": 8,
}

CONFIG = dict(DEFAULT_CONFIG)


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + str(msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config():
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(CONFIG, f, indent=2)
    except Exception as e:
        log("no se pudo guardar config: %s" % e)


def list_com_ports():
    """Lista puertos COM como (device, descripcion, es_bluetooth)."""
    res = []
    if list_ports is None:
        return res
    try:
        for p in list_ports.comports():
            desc = (p.description or "") + " " + (p.hwid or "")
            es_bt = "bluetooth" in desc.lower() or "bth" in (p.hwid or "").lower()
            res.append((p.device, p.description or p.device, es_bt))
    except Exception as e:
        log("listar COM: %s" % e)
    return res


def ensure_printer():
    """Si no hay COM configurado, autodetecta: prefiere puertos Bluetooth; si hay
    uno solo, lo usa. NO asume ningun COM fijo."""
    if CONFIG.get("com_port"):
        return True
    ports = list_com_ports()
    bt = [p for p in ports if p[2]] or ports
    if len(bt) >= 1:
        CONFIG["com_port"] = bt[0][0]
        CONFIG["printer_name"] = bt[0][1]
        save_config()
        log("Puerto autodetectado: %s (%s)" % (bt[0][0], bt[0][1]))
        return True
    log("No hay puertos COM. Empareja la impresora BT en Windows (crea un COM).")
    return False


def build_payload(text):
    out = bytearray()
    if CONFIG.get("reset_init"):
        out += bytes([0x1B, 0x40])
    cp = CONFIG.get("codepage_cmd") or []
    if cp:
        out += bytes(cp)
    enc = CONFIG.get("encoding", "cp858")
    try:
        out += text.encode(enc, errors="replace")
    except LookupError:
        out += text.encode("latin-1", errors="replace")
    if CONFIG.get("cut_paper"):
        out += bytes([0x1D, 0x56, 0x42, 0x03])
    return bytes(out)


def serial_send(data):
    """Abre el COM, escribe los bytes y cierra. Devuelve (True, com)."""
    if serial is None:
        raise OSError("pyserial no esta instalado")
    if not CONFIG.get("com_port"):
        ensure_printer()
    com = CONFIG.get("com_port")
    if not com:
        raise OSError("No hay puerto COM configurado (emparejá la impresora BT en Windows)")
    ser = serial.Serial(
        port=com,
        baudrate=int(CONFIG.get("baudrate", 9600)),
        timeout=int(CONFIG.get("write_timeout", 8)),
        write_timeout=int(CONFIG.get("write_timeout", 8)),
    )
    try:
        ser.write(data)
        ser.flush()
        time.sleep(0.4)
        return True, com
    finally:
        try:
            ser.close()
        except Exception:
            pass


class Handler(BaseHTTPRequestHandler):
    server_version = "FactuposPrintBridgeWin/" + VERSION

    def log_message(self, *a):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "86400")

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _active_json(self):
        return {"type": "bluetooth", "name": CONFIG.get("printer_name") or CONFIG.get("com_port"),
                "address": CONFIG.get("com_port")}

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/ping":
            self._json({"ok": True, "printer": CONFIG.get("printer_name") or CONFIG.get("com_port"),
                        "activePrinter": self._active_json()})
        elif p == "/status":
            self._json({"ok": True, "connected": True, "paper": True})
        elif p == "/printers":
            self._json({"ok": True, "printers": [{"type": "bluetooth", "name": d[1], "address": d[0]}
                                                 for d in list_com_ports()]})
        elif p == "/printer/active":
            self._json({"ok": True, "printer": self._active_json()})
        else:
            self._json({"ok": False, "error": "Ruta no encontrada: " + p}, 404)

    def do_POST(self):
        p = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        if p == "/print":
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception as e:
                return self._json({"ok": False, "error": "JSON invalido: %s" % e}, 400)
            text = body.get("text", "")
            if not text:
                return self._json({"ok": False, "error": "Campo 'text' vacio"}, 400)
            log("POST /print: %d chars" % len(text))
            try:
                ok, com = serial_send(build_payload(text))
                log("Impreso OK por %s" % com)
                self._json({"ok": True, "message": "Impreso", "printer": CONFIG.get("printer_name") or com,
                            "type": "bluetooth"})
            except Exception as e:
                log("ERROR impresion: %s" % e)
                self._json({"ok": False, "error": str(e)}, 200)
        elif p == "/printer/select":
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
                if body.get("address"):
                    CONFIG["com_port"] = body["address"]
                if body.get("name"):
                    CONFIG["printer_name"] = body["name"]
                save_config()
            except Exception:
                pass
            self._json({"ok": True, "printer": self._active_json()})
        else:
            self._json({"ok": False, "error": "Ruta no encontrada: " + p}, 404)


# ----------------- Bandeja del sistema -----------------
_TRAY_ICON = None


def _make_tray_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (22, 101, 52, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([14, 26, 50, 46], fill=(255, 255, 255, 255))
    d.rectangle([20, 14, 44, 26], fill=(255, 255, 255, 255))
    d.rectangle([22, 46, 42, 56], fill=(220, 220, 220, 255))
    return img


def _tray_test_print(icon=None, item=None):
    try:
        ok, com = serial_send(build_payload("FactuPOS Print Bridge\nPrueba de impresion\n\n\n"))
        log("Prueba impresa por %s" % com)
    except Exception as e:
        log("Prueba fallo: %s" % e)


def _tray_quit(icon=None, item=None):
    log("Salir desde la bandeja")
    try:
        if icon:
            icon.stop()
    except Exception:
        pass
    os._exit(0)


def _select_port(com, name):
    CONFIG["com_port"] = com
    CONFIG["printer_name"] = name
    save_config()
    log("Puerto elegido: %s (%s)" % (com, name))
    _refresh_tray()


def _refresh_tray(icon=None, item=None):
    if _TRAY_ICON is not None:
        try:
            _TRAY_ICON.menu = _build_menu()
            _TRAY_ICON.update_menu()
        except Exception:
            pass


def _build_menu():
    import pystray
    from pystray import MenuItem as Item
    ports = list_com_ports()
    sub = []
    if ports:
        for com, name, es_bt in ports:
            etiqueta = ("🖨 " if es_bt else "") + com + " — " + name
            sub.append(Item(etiqueta,
                            lambda i, it, _c=com, _n=name: _select_port(_c, _n),
                            checked=lambda it, _c=com: CONFIG.get("com_port") == _c,
                            radio=True))
    else:
        sub.append(Item("(sin puertos COM — emparejá la impresora BT)", None, enabled=False))
    sub.append(pystray.Menu.SEPARATOR)
    sub.append(Item("Refrescar puertos", _refresh_tray))
    actual = CONFIG.get("printer_name") or CONFIG.get("com_port") or "sin impresora"
    return pystray.Menu(
        Item("FactuPOS Print Bridge  ·  :8765", None, enabled=False),
        pystray.Menu.SEPARATOR,
        Item("Impresora: " + actual, pystray.Menu(*sub)),
        Item("Imprimir prueba", _tray_test_print),
        pystray.Menu.SEPARATOR,
        Item("Salir", _tray_quit),
    )


def run_tray():
    global _TRAY_ICON
    import pystray
    _TRAY_ICON = pystray.Icon("factupos-print-bridge", _make_tray_image(),
                              "FactuPOS Print Bridge", _build_menu())
    _TRAY_ICON.run()


def _version_tuple(v):
    """'1.2.3' -> (1,2,3) para comparar versiones numericamente."""
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except Exception:
        return (0,)


def _apply_update(new_version, url):
    """Descargar el .exe nuevo y reemplazar el actual via updater.bat (silencioso)."""
    try:
        exe_name = os.path.basename(sys.executable)
        new_exe = os.path.join(BASE_DIR, exe_name.replace(".exe", "_new.exe"))
        log("Auto-update: descargando %s" % url)
        urllib.request.urlretrieve(url, new_exe)

        size = os.path.getsize(new_exe)
        if size < 500000:  # < 0.5MB = probablemente un HTML de error, abortar
            log("Auto-update: descarga muy pequena (%d bytes), abortando" % size)
            try:
                os.remove(new_exe)
            except OSError:
                pass
            return

        bat = os.path.join(BASE_DIR, "updater.bat")
        with open(bat, "w", encoding="ascii") as f:
            f.write("@echo off\r\n")
            f.write("timeout /t 3 /nobreak >nul\r\n")
            f.write('taskkill /f /im "%s" >nul 2>&1\r\n' % exe_name)
            f.write('del "%s"\r\n' % exe_name)
            f.write('ren "%s" "%s"\r\n' % (os.path.basename(new_exe), exe_name))
            f.write('start "" "%s"\r\n' % exe_name)
            f.write('del "%%~f0"\r\n')

        log("Auto-update: aplicando v%s, reiniciando" % new_version)
        subprocess.Popen(
            ["cmd.exe", "/c", bat],
            cwd=BASE_DIR,
            creationflags=0x00000008,  # DETACHED_PROCESS
            close_fds=True,
        )
        os._exit(0)
    except Exception as e:
        log("Auto-update error: %s" % e)


def update_loop():
    """Chequea el manifest al arrancar y cada UPDATE_CHECK_INTERVAL. Defensivo:
    cualquier fallo se loguea y NO afecta al Bridge (sigue imprimiendo)."""
    if not getattr(sys, "frozen", False):
        return  # en modo script no se auto-actualiza
    time.sleep(8)  # dejar que el server/tray levante primero
    while True:
        try:
            req = urllib.request.Request(UPDATE_MANIFEST_URL,
                                         headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
            latest = str(data.get("version", "")).strip()
            url = str(data.get("downloadUrl", "")).strip()
            if latest and url and _version_tuple(latest) > _version_tuple(VERSION):
                log("Auto-update: nueva version %s (actual %s)" % (latest, VERSION))
                _apply_update(latest, url)
        except Exception as e:
            log("Auto-update check: %s" % e)
        time.sleep(UPDATE_CHECK_INTERVAL)


def main():
    global CONFIG
    CONFIG = load_config()
    if not os.path.exists(CONFIG_PATH):
        save_config()
    try:
        ensure_printer()
    except Exception as e:
        log("autodeteccion: %s" % e)
    log("FactuPOS Print Bridge (Windows) en http://%s:%d" % (HOST, PORT))
    log("Impresora: %s [%s] enc=%s" % (CONFIG.get("printer_name"), CONFIG.get("com_port"), CONFIG.get("encoding")))

    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    # Auto-update en segundo plano (chequea manifest; no rompe si falla)
    threading.Thread(target=update_loop, daemon=True).start()

    try:
        run_tray()
    except Exception as e:
        log("Bandeja no disponible (%s) -> headless" % e)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
