#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FactuPOS - Kiosko de Marcaje por Huella Digital (standalone, Python/Tkinter)
============================================================================

Programa SEPARADO, sin login web: identifica al empleado con la huella usando el
servicio local fingerprint_service.py y registra la marca consumiendo APIs web
que NO requieren sesion (/apis/biometria/kiosko/*.php).

Se actualiza SOLO (desde 1.0.4): cada hora lee
  https://soportereal.com/software/factupos-app/windows/factupos-fingerprint-windows_version.json
y si hay version nueva baja FactuposKiosko.exe + FactuposFpServicio.exe y se reinicia.

Identificacion de la empresa:
  - token.conf  (texto plano, una linea = el token "<serverdb>~<aleatorio>",
                 generado desde Biometria > Configurar Kiosko en la web). RECOMENDADO.
  - o "db" en config.json (legacy: el serverdb directo).

API web (failover): config.json -> "api_base" puede ser una lista; el kiosko
prueba cada URL en orden hasta que una responde. Ej:
  "api_base": ["https://invefacon.net", "https://invefacon.com"]
  (NO usar "https://factupos.com" — desde internet apunta a otra IP, da 404)

Flujo:
  arranque -> baja plantillas de la BD (huellas_listar.php) -> las carga en el servicio local
  loop     -> POST /fingerprint/identify -> match -> marca_registrar.php -> ENTRADA/SALIDA
  boton "Registrar huella": empleados_listar.php -> /fingerprint/enroll (4 toques)
                            -> huella_registrar.php (guarda en la BD) -> import local + marca

Requisitos: Python 3.8+ con Tkinter. Sin dependencias pip. fingerprint_service.py corriendo.
"""

import os
import sys
import ssl
import json
import time
import threading
import traceback
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except Exception:
    print("ERROR: este programa necesita Tkinter (viene con el instalador estandar de Python).")
    sys.exit(1)

APP_VERSION    = "1.0.5"
BUILD_DATE     = "2026-10-12"
BASE_DIR       = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE    = os.path.join(BASE_DIR, "config.json")
TOKENCONF_FILE = os.path.join(BASE_DIR, "token.conf")
LOGS_DIR       = os.path.join(BASE_DIR, "logs")

DEFAULT_CONFIG = {
    "api_base":        ["https://invefacon.net", "https://invefacon.com"],   # str o lista; failover en orden
    "db":              "",                          # legacy: serverdb directo (si no usás token.conf)
    "token":           "",                          # alternativa a token.conf
    "dispositivo_id":  "KIOSKO-01",
    "fp_service_url":  "https://127.0.0.1:52181",
    "plataforma":      "windows",
    "dedo_default":    "right-index",
    "refresh_minutos": 10,
    "fullscreen":      False,                       # false = ventana chica; true = pantalla completa
    "ventana":         "420x640",                   # tamaño de la ventana cuando fullscreen=false
    "titulo":          "Marcaje de Asistencia",
    "auto_actualizar": True,                      # 1.0.4: buscar version nueva cada hora y aplicarla sola
    "auto_registrar_si_no_existe": True,            # si la huella no esta registrada, abrir el dialogo
                                                    # "Registrar huella" automaticamente (pedir el nombre)
}

try:
    import winsound
except Exception:
    winsound = None

def _beep_ok():
    if winsound:
        try:
            for f in (660, 880, 1175):
                winsound.Beep(f, 110)
        except Exception:
            try: winsound.MessageBeep(0x00000040)
            except Exception: pass

def _beep_err():
    if winsound:
        try:
            winsound.Beep(220, 350)
        except Exception:
            try: winsound.MessageBeep(0x00000010)
            except Exception: pass


# ---------------------------------------------------------------------------
def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try: print(line, flush=True)
    except Exception: pass
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(os.path.join(LOGS_DIR, "kiosk-%s.log" % datetime.now().strftime("%Y-%m-%d")), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception: pass


def _norm_bases(val):
    out = []
    if isinstance(val, str):
        if val.strip(): out.append(val.strip().rstrip("/"))
    elif isinstance(val, (list, tuple)):
        for x in val:
            s = str(x).strip().rstrip("/")
            if s: out.append(s)
    return out


def load_config():
    if not os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        return None  # recien creado
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        raise RuntimeError("config.json invalido: %s" % e)
    out = dict(DEFAULT_CONFIG)
    out.update(cfg or {})
    # api_base -> lista de bases con failover
    bases = _norm_bases(out.get("api_base"))
    bases += _norm_bases(out.get("api_base_fallback"))
    if not bases:
        bases = ["https://invefacon.net", "https://invefacon.com"]
    # dedup preservando orden
    seen = set(); out["api_bases"] = [b for b in bases if not (b in seen or seen.add(b))]
    out["fp_service_url"] = str(out.get("fp_service_url", "")).rstrip("/")
    # token: token.conf manda; si no, "token" del config.json
    tok = ""
    if os.path.isfile(TOKENCONF_FILE):
        try:
            with open(TOKENCONF_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        tok = line; break
        except Exception as e:
            log("No se pudo leer token.conf: %s" % e)
    out["token"] = tok or str(out.get("token", "")).strip()
    out["db"] = str(out.get("db", "")).strip()
    return out


# --- HTTP (stdlib) ---
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

def http_json(method, url, body=None, timeout=15):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        raw = resp.read().decode("utf-8", "replace")
        try:
            return resp.status, json.loads(raw)
        except Exception:
            # Respuesta no-JSON (ej HTML de un server que no es FactuPOS).
            # NO incluimos "ok" para que _api() la detecte como "no es nuestra API"
            # y haga failover a la siguiente base.
            return resp.status, {"_neterr": "respuesta no-JSON", "error": "respuesta no-JSON: " + raw[:200]}

def http_json_safe(method, url, body=None, timeout=15):
    """(status, dict). status==0 => no respondio (red caida / timeout).

    En errores (HTTPError no-JSON, red caida, timeout) NO se incluye la clave 'ok'
    en el dict — solo '_neterr' — para que _api() pueda hacer failover al siguiente
    api_base. Si el server contesta JSON valido con 'ok':False, eso SI tiene 'ok'
    y se respeta (es un error de negocio real, no de red)."""
    try:
        return http_json(method, url, body, timeout)
    except urllib.error.HTTPError as e:
        try:
            body_json = json.loads(e.read().decode("utf-8", "replace"))
            return e.code, body_json
        except Exception:
            return e.code, {"_neterr": "HTTP %s" % e.code, "error": "HTTP %s" % e.code}
    except Exception as e:
        return 0, {"_neterr": "red/timeout", "error": str(e)}

def http_get_safe(url, body=None, timeout=15):
    """GET pasando params como query string."""
    if body:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(body)
    return http_json_safe("GET", url, None, timeout)


# ---------------------------------------------------------------------------
# ACTUALIZACION AUTOMATICA (1.0.4) — mismo patron que el kiosko Linux (Updater.java):
# un manifiesto con la version y las URL de los dos .exe. Solo corre compilado (.exe).
UPDATE_MANIFEST = "https://soportereal.com/software/factupos-app/windows/factupos-fingerprint-windows_version.json"
UPDATE_CADA_SEG = 3600
UPDATE_DIR      = os.path.join(BASE_DIR, "update")


def _ver_tuple(v):
    out = []
    for p in str(v or "0").split("."):
        try: out.append(int("".join(ch for ch in p if ch.isdigit()) or 0))
        except Exception: out.append(0)
    return tuple(out)


def _bajar_archivo(url, destino, timeout=120):
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(destino, "wb") as f:
        while True:
            b = r.read(65536)
            if not b: break
            f.write(b)
    with open(destino, "rb") as f:
        if f.read(2) != b"MZ":
            raise RuntimeError("lo bajado no es un .exe: %s" % url)
    if os.path.getsize(destino) < 500000:
        raise RuntimeError("el .exe bajado es demasiado chico: %s" % url)


def buscar_actualizacion():
    """Devuelve el manifiesto si hay una version MAS NUEVA que APP_VERSION, si no None."""
    req = urllib.request.Request(UPDATE_MANIFEST + "?t=%d" % int(time.time()), headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=10) as r:
        man = json.loads(r.read().decode("utf-8", "replace"))
    if _ver_tuple(man.get("version")) > _ver_tuple(APP_VERSION) and man.get("kiosko") and man.get("servicio"):
        return man
    return None


def aplicar_actualizacion(man):
    """Baja los dos .exe a la carpeta update y deja corriendo un .bat que espera, cierra los dos
    procesos, reemplaza y vuelve a arrancar con iniciar_oculto.vbs. El kiosko muere ahi."""
    import subprocess
    os.makedirs(UPDATE_DIR, exist_ok=True)
    nk = os.path.join(UPDATE_DIR, "FactuposKiosko.exe.new")
    ns = os.path.join(UPDATE_DIR, "FactuposFpServicio.exe.new")
    _bajar_archivo(man["kiosko"], nk)
    _bajar_archivo(man["servicio"], ns)
    bat = os.path.join(UPDATE_DIR, "aplicar.bat")
    arranque = ('start "" wscript.exe "%~dp0..\\iniciar_oculto.vbs"'
                if os.path.isfile(os.path.join(BASE_DIR, "iniciar_oculto.vbs"))
                else 'start "" "%~dp0..\\FactuposFpServicio.exe"')
    with open(bat, "w", encoding="ascii", errors="replace") as f:
        f.write("@echo off\r\n"
                "cd /d \"%~dp0..\"\r\n"
                "timeout /t 3 /nobreak >nul\r\n"
                "taskkill /f /im FactuposKiosko.exe >nul 2>&1\r\n"
                "taskkill /f /im FactuposFpServicio.exe >nul 2>&1\r\n"
                "timeout /t 2 /nobreak >nul\r\n"
                "move /y \"update\\FactuposKiosko.exe.new\" \"FactuposKiosko.exe\" >nul\r\n"
                "move /y \"update\\FactuposFpServicio.exe.new\" \"FactuposFpServicio.exe\" >nul\r\n"
                + arranque + "\r\n")
    log("Actualizacion %s -> %s: aplicando (%s)" % (APP_VERSION, man.get("version"), bat))
    subprocess.Popen(["cmd.exe", "/c", bat], cwd=UPDATE_DIR,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))


# ---------------------------------------------------------------------------
class KioskApp(object):
    def __init__(self, root, cfg):
        self.root = root
        self.cfg = cfg
        self.fp = cfg["fp_service_url"]
        self.api_bases = cfg["api_bases"]
        self.active_api = self.api_bases[0] if self.api_bases else ""
        self.token = cfg.get("token", "")
        self.db = cfg.get("db", "")
        # serverdb "visible" (del token, o el db directo)
        self.serverdb = (self.token.split("~", 1)[0] if "~" in self.token else "") or self.db or ""
        self.running = True
        self.enrolling = False
        self.last_sync_ts = 0.0
        self.fp_connected = False
        self.fp_device = ""
        self.users_loaded = 0

        self._build_ui()
        self._tick_clock()
        threading.Thread(target=self._worker, name="worker", daemon=True).start()
        if cfg.get("auto_actualizar", True) and getattr(sys, "frozen", False):
            threading.Thread(target=self._updater, name="updater", daemon=True).start()
        # si no está configurado, abrir el diálogo de token al arrancar
        if not self.token and not self.db:
            self.root.after(500, self._open_token_config)

    # ---- API web con failover + auth (token o db) ----
    def _updater(self):
        """Cada hora: si hay version nueva, se aplica — nunca a mitad de un registro de huella."""
        time.sleep(60)
        while self.running:
            try:
                man = buscar_actualizacion()
                if man:
                    while self.enrolling or getattr(self, "_has_enroll_dialog", False):
                        time.sleep(15)
                    self.set_status("Actualizando a la version %s..." % man.get("version"))
                    aplicar_actualizacion(man)
                    return
            except Exception as e:
                log("Actualizacion: no se pudo revisar/aplicar: %s" % e)
            time.sleep(UPDATE_CADA_SEG)

    def _auth_params(self):
        if self.token: return {"token": self.token}
        if self.db:    return {"db": self.db}
        return {}

    def _api(self, method, path, body=None, timeout=15):
        body = dict(body or {})
        body.update(self._auth_params())
        # probar primero la base que funciono la ultima vez
        bases = self.api_bases
        if self.active_api in bases:
            bases = [self.active_api] + [b for b in bases if b != self.active_api]
        last = (0, {"ok": False, "error": "sin api_base configurada"})
        for b in bases:
            url = b + path
            if method == "GET":
                st, data = http_get_safe(url, body, timeout)
            else:
                st, data = http_json_safe(method, url, body, timeout)
            # Aceptamos la respuesta solo si es JSON de nuestra API (tiene 'ok'
            # y NO es un fallback de red marcado con '_neterr'). Si no, pasamos
            # al siguiente api_base (caso tipico: factupos.com desde internet da
            # HTML 404 -> _neterr -> probar invefacon.net / invefacon.com).
            if isinstance(data, dict) and "ok" in data and "_neterr" not in data:
                if b != self.active_api:
                    log("API activa -> %s" % b)
                self.active_api = b
                return st, data
            log("%s no parece FactuPOS (HTTP %s) — pruebo siguiente api_base" % (b, st))
            # Si falló esta base y era la 'activa', resetear para que la próxima
            # vez vuelva a probar desde la primera de la lista.
            if b == self.active_api:
                self.active_api = ""
            # convertimos el fallback en ok:False para que el caller pueda mostrar el error
            last = (st, {"ok": False, "error": (data.get("error") if isinstance(data, dict) else "sin respuesta")})
        log("Ninguna api_base respondio nuestra API: %r" % (self.api_bases,))
        return last

    # ---------------- UI ----------------
    def _build_ui(self):
        c = self.cfg
        self.root.title("FactuPOS - " + c.get("titulo", "Marcaje") + " (v" + APP_VERSION + ")")
        self.root.configure(bg="#0f172a")
        geo = str(c.get("ventana", "420x640")).strip() or "420x640"
        if c.get("fullscreen", False):
            try: self.root.attributes("-fullscreen", True)
            except Exception: self.root.geometry(geo)
        else:
            self.root.geometry(geo)
            try: self.root.minsize(360, 520)
            except Exception: pass
        self.root.bind("<Escape>", lambda e: self._toggle_fullscreen())
        self.root.bind("<F10>", lambda e: self.root.destroy())

        hdr = tk.Frame(self.root, bg="#1e293b"); hdr.pack(fill="x")
        self.led = tk.Canvas(hdr, width=16, height=16, bg="#1e293b", highlightthickness=0)
        self._led_id = self.led.create_oval(3, 3, 13, 13, fill="#64748b", outline="")
        self.led.pack(side="left", padx=(14, 8), pady=10)
        self.lbl_status = tk.Label(hdr, text="Conectando...", bg="#1e293b", fg="#94a3b8", font=("Segoe UI", 11))
        self.lbl_status.pack(side="left", pady=10)
        self.lbl_clock = tk.Label(hdr, text="--:--:--", bg="#1e293b", fg="#e2e8f0", font=("Consolas", 14, "bold"))
        self.lbl_clock.pack(side="right", padx=14, pady=10)

        mid = tk.Frame(self.root, bg="#0f172a"); mid.pack(fill="both", expand=True)
        # Fila titulo + pill de version (estilo "código de módulo")
        titulo_row = tk.Frame(mid, bg="#0f172a"); titulo_row.pack(pady=(14, 2))
        self.lbl_company = tk.Label(titulo_row, text=c.get("titulo", "Marcaje de Asistencia"),
                                    bg="#0f172a", fg="#cbd5e1", font=("Segoe UI", 14, "bold"))
        self.lbl_company.pack(side="left")
        self.lbl_ver_pill = tk.Label(titulo_row, text=" v" + APP_VERSION + " ",
                                     bg="#ffff00", fg="#000000", font=("Segoe UI", 9, "bold"),
                                     padx=4)
        self.lbl_ver_pill.pack(side="left", padx=(8, 0))
        ident = ("Token: " + self.serverdb) if self.token else (("Empresa: " + self.db) if self.db else "(sin configurar)")
        self.lbl_db = tk.Label(mid, text=ident, bg="#0f172a", fg="#64748b", font=("Segoe UI", 9))
        self.lbl_db.pack()
        self.lbl_build = tk.Label(mid, text="build " + BUILD_DATE, bg="#0f172a", fg="#94a3b8", font=("Segoe UI", 8))
        self.lbl_build.pack()

        self.lbl_fp = tk.Label(mid, text="\U0001F58A", bg="#0f172a", fg="#64748b", font=("Segoe UI Emoji", 56))
        self.lbl_fp.pack(pady=10)
        self.lbl_msg = tk.Label(mid, text="Coloque su dedo en el lector", bg="#0f172a", fg="#94a3b8",
                                font=("Segoe UI", 12), wraplength=380, justify="center")
        self.lbl_msg.pack(pady=(0, 2))

        self.result = tk.Frame(mid, bg="#0f172a"); self.result.pack(pady=6, fill="x", padx=24)
        self.lbl_result_action = tk.Label(self.result, text="", bg="#0f172a", fg="#e2e8f0", font=("Segoe UI", 11, "bold"))
        self.lbl_result_name = tk.Label(self.result, text="", bg="#0f172a", fg="#f1f5f9", font=("Segoe UI", 18, "bold"))
        self.lbl_result_time = tk.Label(self.result, text="", bg="#0f172a", fg="#94a3b8", font=("Segoe UI", 10))
        self.lbl_result_action.pack(); self.lbl_result_name.pack(); self.lbl_result_time.pack()

        ftr = tk.Frame(self.root, bg="#0f172a"); ftr.pack(fill="x", pady=(0, 8))
        inner = tk.Frame(ftr, bg="#0f172a"); inner.pack()
        self.btn_enroll = tk.Button(inner, text="✋ Registrar huella", command=self._open_enroll,
                                    bg="#1e293b", fg="#e2e8f0", activebackground="#334155", activeforeground="#fff",
                                    relief="flat", font=("Segoe UI", 10), padx=10, pady=6, cursor="hand2", bd=0)
        self.btn_enroll.pack(side="left", padx=(0, 6))
        self.btn_cfg = tk.Button(inner, text="⚙ Config", command=self._open_token_config,
                                 bg="#1e293b", fg="#94a3b8", activebackground="#334155", activeforeground="#fff",
                                 relief="flat", font=("Segoe UI", 10), padx=10, pady=6, cursor="hand2", bd=0)
        self.btn_cfg.pack(side="left")
        self.lbl_ver = tk.Label(self.root, text="FactuPOS Biometria v" + APP_VERSION + " (" + BUILD_DATE + ")  ·  Esc=pantalla completa  ·  F10=salir",
                                bg="#0f172a", fg="#94a3b8", font=("Segoe UI", 8))
        self.lbl_ver.pack(side="bottom", pady=(0, 3))

    def _toggle_fullscreen(self):
        try:
            self.root.attributes("-fullscreen", not bool(self.root.attributes("-fullscreen")))
        except Exception: pass

    def _tick_clock(self):
        self.lbl_clock.config(text=datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._tick_clock)

    def ui(self, fn, *a, **k):
        try: self.root.after(0, lambda: fn(*a, **k))
        except Exception: pass
    def set_led(self, color):     self.ui(self.led.itemconfig, self._led_id, fill=color)
    def set_status(self, text):   self.ui(self.lbl_status.config, text=text)
    def set_msg(self, text):      self.ui(self.lbl_msg.config, text=text)
    def set_fp_color(self, color):self.ui(self.lbl_fp.config, fg=color)

    def show_result(self, action, name, kind="ok", subtitle=None):
        colors = {"ok": "#22c55e", "exit": "#0ea5e9", "err": "#ef4444", "warn": "#f59e0b"}
        col = colors.get(kind, "#e2e8f0"); t = datetime.now().strftime("%H:%M:%S")
        def _do():
            self.lbl_fp.config(text="✓" if kind in ("ok", "exit") else "✗", fg=col)
            self.lbl_msg.config(text="")
            self.lbl_result_action.config(text=action, fg=col)
            self.lbl_result_name.config(text=name)
            self.lbl_result_time.config(text=(subtitle + "   ·   " + t) if subtitle else t)
        self.ui(_do)

    def clear_result(self):
        def _do():
            self.lbl_fp.config(text="\U0001F58A", fg="#22c55e" if self.fp_connected else "#64748b")
            self.lbl_result_action.config(text=""); self.lbl_result_name.config(text=""); self.lbl_result_time.config(text="")
            self.lbl_msg.config(text="Coloque su dedo en el lector" if self.fp_connected else "Lector no detectado")
        self.ui(_do)

    def _hint_for_error(self, msg):
        """Devuelve una pista en español para errores conocidos (None si no aplica)."""
        m = (msg or "").lower()
        if "10061" in m or "denego expresamente" in m or "denegó expresamente" in m:
            return ("El servicio local de huella no esta corriendo.\n"
                    "Cerra esta ventana y ejecuta INICIAR.bat como administrador.")
        if "10060" in m or "timed out" in m or "timeout" in m:
            return "Tiempo agotado conectando al servicio. ¿Esta el lector conectado? ¿Otro proceso lo tiene tomado?"
        if "needs_migration" in m or "migración huellausuario" in m or "migracion huellausuario" in m:
            return "Falta aplicar la migracion HuellaUsuario (20260511104641) en esta empresa."
        if "no existe en empleados" in m:
            return "El usuario no figura en la tabla Empleados de la empresa. Agreguelo primero desde el sistema web."
        if "ucs-2" in m:
            return "Error guardando el template (codificacion binaria). Actualice a la version mas reciente del servicio."
        return None

    def show_error_copiable(self, title, msg, kind="error", parent=None):
        """Diálogo de error con texto seleccionable y botón 'Copiar al portapapeles'.
        Reemplaza a messagebox.showerror/showwarning que NO permiten copiar el texto."""
        def _do():
            par = parent if parent is not None else self.root
            win = tk.Toplevel(par); win.title(title)
            win.configure(bg="#0f172a")
            try: win.transient(par)
            except Exception: pass
            try: win.grab_set()
            except Exception: pass
            # tamaño y centrado
            w, h = 520, 320
            try:
                par.update_idletasks()
                x = par.winfo_rootx() + (par.winfo_width() - w) // 2
                y = par.winfo_rooty() + (par.winfo_height() - h) // 2
                win.geometry("%dx%d+%d+%d" % (w, h, max(x, 0), max(y, 0)))
            except Exception:
                win.geometry("%dx%d" % (w, h))
            ico_color = "#ef4444" if kind == "error" else ("#f59e0b" if kind == "warn" else "#3b82f6")
            ico_text  = "✗" if kind == "error" else ("⚠" if kind == "warn" else "ⓘ")

            hdr = tk.Frame(win, bg="#0f172a"); hdr.pack(fill="x", padx=14, pady=(14, 6))
            tk.Label(hdr, text=ico_text, font=("Segoe UI", 24, "bold"), fg=ico_color, bg="#0f172a").pack(side="left")
            tk.Label(hdr, text=title, font=("Segoe UI", 13, "bold"), fg="#e2e8f0", bg="#0f172a").pack(side="left", padx=(10, 0))

            hint = self._hint_for_error(msg)
            if hint:
                tk.Label(win, text=hint, font=("Segoe UI", 10), fg="#fbbf24", bg="#0f172a",
                         wraplength=480, justify="left").pack(fill="x", padx=14, pady=(0, 6))

            # Text widget con el mensaje (seleccionable + scroll)
            txt_frame = tk.Frame(win, bg="#0f172a"); txt_frame.pack(fill="both", expand=True, padx=14, pady=(4, 4))
            txt = tk.Text(txt_frame, wrap="word", bg="#1e293b", fg="#e2e8f0",
                          insertbackground="#e2e8f0", font=("Consolas", 10),
                          relief="flat", padx=8, pady=6, height=6)
            sb = ttk.Scrollbar(txt_frame, orient="vertical", command=txt.yview)
            txt.configure(yscrollcommand=sb.set)
            txt.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
            txt.insert("1.0", str(msg or ""))
            txt.configure(state="normal")  # editable=true para que el usuario pueda hacer Ctrl+A/C
            txt.bind("<Key>", lambda e: "break" if e.keysym not in ("c", "C", "a", "A", "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next") and not (e.state & 0x4) else None)
            txt.focus_set()

            # Botones
            btns = tk.Frame(win, bg="#0f172a"); btns.pack(fill="x", padx=14, pady=(4, 12))
            copied_state = {"shown": False}
            def do_copy():
                try:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(str(msg or ""))
                    self.root.update()  # mantiene el portapapeles tras cerrar la ventana
                    btn_copy.config(text="✓ Copiado", bg="#16a34a")
                    if not copied_state["shown"]:
                        copied_state["shown"] = True
                        win.after(1500, lambda: btn_copy.config(text="📋 Copiar al portapapeles", bg="#2563eb"))
                except Exception:
                    pass
            btn_copy = tk.Button(btns, text="📋 Copiar al portapapeles", command=do_copy,
                                 bg="#2563eb", fg="#ffffff", activebackground="#1d4ed8",
                                 font=("Segoe UI", 10, "bold"), bd=0, padx=14, pady=7, cursor="hand2")
            btn_copy.pack(side="left")
            tk.Button(btns, text="Aceptar", command=win.destroy,
                      bg="#334155", fg="#ffffff", activebackground="#1f2937",
                      font=("Segoe UI", 10, "bold"), bd=0, padx=18, pady=7, cursor="hand2").pack(side="right")

            # Esc cierra, Ctrl+C copia explícito
            win.bind("<Escape>", lambda e: win.destroy())
            win.bind("<Control-c>", lambda e: do_copy())
            win.bind("<Control-C>", lambda e: do_copy())
            try: win.wait_window()
            except Exception: pass
        self.ui(_do)

    # ---------------- Worker ----------------
    def _worker(self):
        # esperar hasta que haya token (o db). Se puede configurar con el botón "⚙ Token / Config".
        warned = False
        while self.running and not self.token and not self.db:
            if not warned:
                self.set_led("#64748b"); self.set_fp_color("#64748b")
                self.set_status("Sin token configurado")
                self.set_msg("Pulsá «⚙ Token / Config» y pegá el token generado en la web (Biometría → Configurar Kiosko)")
                warned = True
            time.sleep(1.0)
        if not self.running:
            return
        self._wait_fp_service()
        self._sync_templates(initial=True)
        while self.running:
            try:
                if self.enrolling:
                    time.sleep(0.4); continue
                if time.monotonic() - self.last_sync_ts > self.cfg.get("refresh_minutos", 10) * 60:
                    self._sync_templates(initial=False)
                self._refresh_fp_connection()
                if not self.fp_connected:
                    self.set_led("#64748b"); self.set_status("Lector no detectado"); self.set_fp_color("#64748b")
                    self.set_msg("Verifique el lector USB / el servicio de huella")
                    time.sleep(3); continue
                st, data = http_json_safe("POST", self.fp + "/fingerprint/identify", {"timeout": 10000}, timeout=15)
                if st == 503:
                    self.set_msg("Sensor enfriando..."); time.sleep(5); continue
                if not data or not data.get("ok"):
                    time.sleep(1.0); continue
                if data.get("waiting"):
                    time.sleep(1.2); continue
                if data.get("matched") and data.get("user_id"):
                    self._do_marca(str(data["user_id"]))
                    time.sleep(4.0); self.clear_result()
                else:
                    self.set_led("#ef4444")
                    self.show_result("NO RECONOCIDO", "Huella no registrada — elegí tu nombre para registrarla", kind="err")
                    _beep_err()
                    auto = bool(self.cfg.get("auto_registrar_si_no_existe", True))
                    if auto and not self.enrolling and not getattr(self, "_has_enroll_dialog", False):
                        time.sleep(1.2)                       # dar un instante para que se vea el mensaje
                        self.ui(self._open_enroll)            # abrir el dialogo "Registrar huella"
                        # esperar a que el dialogo se cierre (o pase a enroll)
                        waited = 0
                        while waited < 60 and (getattr(self, "_has_enroll_dialog", False) or self.enrolling):
                            time.sleep(0.5); waited += 0.5
                    else:
                        time.sleep(6.0)
                    self.set_led("#22c55e" if self.fp_connected else "#64748b"); self.clear_result()
            except Exception:
                log("Worker:\n" + traceback.format_exc()); time.sleep(2.0)

    def _wait_fp_service(self):
        self.set_status("Conectando al servicio de huella...")
        for _ in range(60):
            st, data = http_json_safe("GET", self.fp + "/status", timeout=3)
            if data and data.get("ok"): return
            time.sleep(1.0)
        self.set_status("No se pudo contactar el servicio local de huella")

    def _refresh_fp_connection(self):
        st, data = http_json_safe("GET", self.fp + "/get_connection", timeout=4)
        if data and data.get("ok"):
            self.fp_connected = bool(data.get("connected"))
            self.fp_device = data.get("device") or ""
            if self.fp_connected:
                self.set_led("#22c55e")
                self.set_status((self.fp_device or "Lector listo") + "  ·  %d huella(s)" % self.users_loaded)
                self.set_fp_color("#22c55e")
        else:
            self.fp_connected = False

    def _sync_templates(self, initial=False):
        st, data = self._api("GET", "/apis/biometria/kiosko/huellas_listar.php",
                             {"plataforma": self.cfg.get("plataforma", "windows")}, timeout=20)
        if not data or not data.get("ok"):
            log("Sync plantillas FALLO: %s" % (data.get("error") if data else "sin respuesta"))
            if initial: self.set_status("Sin conexion a la API — usando cache local del servicio")
            return
        if data.get("needs_migration"):
            log("Falta la tabla HuellaUsuario (migracion 20260511104641) en %s" % self.serverdb)
            self.set_status("Falta migracion HuellaUsuario en %s" % self.serverdb)
            return
        huellas = data.get("huellas", [])
        http_json_safe("POST", self.fp + "/prints/clear", {"wipe_disk": True}, timeout=10)
        if huellas:
            payload = {"huellas": [{"usuario_codigo": h["usuario_codigo"], "dedo": h.get("dedo", "right-index"),
                                    "template_b64": h["template_b64"]} for h in huellas], "write_disk": True}
            st2, r2 = http_json_safe("POST", self.fp + "/prints/import", payload, timeout=30)
            self.users_loaded = (r2 or {}).get("users", len(huellas)) if r2 else len(huellas)
        else:
            self.users_loaded = 0
        self.last_sync_ts = time.monotonic()
        log("Plantillas sincronizadas: %d huella(s), %d usuario(s)" % (len(huellas), self.users_loaded))

    def _do_marca(self, usuario_codigo):
        self.set_led("#f59e0b"); self.set_fp_color("#f59e0b"); self.set_msg("Registrando marca...")
        body = {"usuario_codigo": usuario_codigo, "origen": "HUELLA",
                "dispositivo_id": self.cfg.get("dispositivo_id", "KIOSKO-01")}
        st, data = self._api("POST", "/apis/biometria/kiosko/marca_registrar.php", body, timeout=20)
        if data and data.get("ok"):
            marca = data.get("marca", {}) or {}; emp = data.get("empleado", {}) or {}; jor = data.get("jornada", {}) or {}
            tipo = (marca.get("tipo_nombre") or ("Entrada" if marca.get("tipo") == "E" else "Salida")).upper()
            name = emp.get("nombre") or usuario_codigo
            sub = ("Jornada: %s h" % jor.get("horas_trabajadas")) if (jor.get("horas_trabajadas") is not None and tipo == "SALIDA") else None
            self.show_result(tipo, name, kind=("exit" if tipo == "SALIDA" else "ok"), subtitle=sub)
            _beep_ok(); self._popup_front()
            log("Marca OK: %s %s (%s)" % (usuario_codigo, tipo, name))
        else:
            err = (data or {}).get("error") or "No se pudo registrar la marca"
            kind = "warn" if ("esperar" in err.lower() or "ultima marca" in err.lower()) else "err"
            self.show_result("YA MARCADO" if kind == "warn" else "ERROR", usuario_codigo, kind=kind, subtitle=err[:80])
            _beep_err(); self._popup_front()
            log("Marca FALLO (%s): %s" % (usuario_codigo, err))

    def _popup_front(self):
        """Trae la ventana del kiosko al frente un instante (por si quedo detras)."""
        def _do():
            try:
                self.root.deiconify(); self.root.lift()
                self.root.attributes("-topmost", True)
                self.root.after(1800, lambda: self.root.attributes("-topmost", False))
            except Exception:
                pass
        self.ui(_do)

    # ---------------- Token / Config ----------------
    def _write_token_conf(self, tok):
        with open(TOKENCONF_FILE, "w", encoding="utf-8") as f:
            f.write((tok or "").strip() + "\n")

    # --- Auto-inicio con Windows (igual estilo que FactuPOS Print: .bat en la carpeta Inicio) ---
    def _autostart_path(self):
        startup = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
        return os.path.join(startup, "FactuPOS Huella.bat")

    def _autostart_enabled(self):
        try:
            return os.path.isfile(self._autostart_path())
        except Exception:
            return False

    def _set_autostart(self, enable, lbl=None):
        def _msg(t, color="#fca5a5"):
            if lbl is not None:
                self.ui(lbl.config, text=t, fg=color)
        try:
            path = self._autostart_path()
            if enable:
                vbs = os.path.join(BASE_DIR, "iniciar_oculto.vbs")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write("@echo off\r\n")
                    f.write('start "" wscript.exe "%s"\r\n' % vbs)
                _msg("Auto-inicio ACTIVADO. Arranca el servicio en segundo plano y abre el kiosko al iniciar Windows.", "#86efac")
            else:
                if os.path.isfile(path):
                    os.remove(path)
                _msg("Auto-inicio desactivado.", "#94a3b8")
        except Exception as e:
            _msg("No se pudo cambiar el auto-inicio: %s" % e, "#fca5a5")

    def _update_config_json(self, **fields):
        try:
            cur = {}
            if os.path.isfile(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cur = json.load(f) or {}
            cur.update(fields)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cur, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            log("No se pudo actualizar config.json: %s" % e)
            return False

    def _apply_token(self, tok, dispositivo_id=None, api_bases=None):
        """Aplica un token nuevo en caliente: actualiza estado + labels + fuerza re-sync."""
        tok = (tok or "").strip()
        self.token = tok
        self.serverdb = (tok.split("~", 1)[0] if "~" in tok else "") or self.db or ""
        if dispositivo_id is not None and dispositivo_id.strip():
            self.cfg["dispositivo_id"] = dispositivo_id.strip()
        if api_bases:
            self.api_bases = api_bases
            self.active_api = api_bases[0]
        self.last_sync_ts = 0.0  # fuerza re-sync de plantillas
        ident = ("Token: " + self.serverdb) if self.token else (("Empresa: " + self.db) if self.db else "(sin configurar)")
        self.ui(self.lbl_db.config, text=ident)
        self.set_msg("Token aplicado. Conectando...")

    def _open_token_config(self):
        win = tk.Toplevel(self.root); win.title("Token / Configuración del kiosko"); win.configure(bg="#0f172a")
        win.transient(self.root); win.grab_set()
        w, h = 560, 360
        try:
            win.geometry("%dx%d+%d+%d" % (w, h,
                         self.root.winfo_rootx() + max(0, (self.root.winfo_width() - w) // 2),
                         self.root.winfo_rooty() + max(0, (self.root.winfo_height() - h) // 2)))
        except Exception:
            win.geometry("%dx%d" % (w, h))

        tk.Label(win, text="Token del kiosko", bg="#0f172a", fg="#e2e8f0", font=("Segoe UI", 14, "bold")).pack(pady=(16, 2))
        tk.Label(win, text="Generalo en la web:  FactuPOS → Biometría → Configurar Kiosko → «Generar token»\ny pegalo acá. Formato: empresa~aleatorio  (ej: invefacon~a1b2c3...)",
                 bg="#0f172a", fg="#94a3b8", font=("Segoe UI", 9), justify="center").pack(pady=(0, 10))

        # 1.0.5: los botones se empacan ANTES que el cuerpo y abajo, para que «Guardar» se vea siempre
        # (con la escala de Windows en 125-150 % el alto fijo de 360 lo dejaba afuera).
        btns = tk.Frame(win, bg="#0f172a"); btns.pack(side="bottom", fill="x", padx=22, pady=(8, 14))
        body = tk.Frame(win, bg="#0f172a"); body.pack(fill="both", expand=True, padx=22)
        tk.Label(body, text="Token:", bg="#0f172a", fg="#cbd5e1", font=("Segoe UI", 11)).pack(anchor="w")
        e_tok = tk.Entry(body, font=("Consolas", 12), bg="#0f172a", fg="#fff", insertbackground="#fff",
                         relief="flat", highlightthickness=1, highlightbackground="#475569", highlightcolor="#0ea5e9")
        e_tok.insert(0, self.token or "")
        e_tok.pack(fill="x", ipady=5, pady=(2, 10)); e_tok.focus_set()

        row = tk.Frame(body, bg="#0f172a"); row.pack(fill="x")
        cd = tk.Frame(row, bg="#0f172a"); cd.pack(side="left", fill="x", expand=True, padx=(0, 8))
        tk.Label(cd, text="Identificador del puesto (dispositivo_id):", bg="#0f172a", fg="#cbd5e1", font=("Segoe UI", 10)).pack(anchor="w")
        e_disp = tk.Entry(cd, font=("Segoe UI", 11), bg="#0f172a", fg="#fff", insertbackground="#fff",
                          relief="flat", highlightthickness=1, highlightbackground="#475569")
        e_disp.insert(0, str(self.cfg.get("dispositivo_id", "KIOSKO-01"))); e_disp.pack(fill="x", ipady=4, pady=(2, 8))

        tk.Label(body, text="URLs del servidor (api_base, separadas por coma — la 1ª que responda se usa):", bg="#0f172a", fg="#cbd5e1", font=("Segoe UI", 10)).pack(anchor="w")
        e_api = tk.Entry(body, font=("Segoe UI", 10), bg="#0f172a", fg="#fff", insertbackground="#fff",
                         relief="flat", highlightthickness=1, highlightbackground="#475569")
        e_api.insert(0, ", ".join(self.api_bases)); e_api.pack(fill="x", ipady=4, pady=(2, 8))

        # Auto-inicio con Windows
        auto_var = tk.BooleanVar(value=self._autostart_enabled())
        chk = tk.Checkbutton(body, text="Iniciar automáticamente al arrancar Windows (en segundo plano)",
                             variable=auto_var, bg="#0f172a", fg="#cbd5e1", selectcolor="#0f172a",
                             activebackground="#0f172a", activeforeground="#fff", font=("Segoe UI", 10),
                             command=lambda: self._set_autostart(auto_var.get(), lbl_msg))
        chk.pack(anchor="w", pady=(4, 4))

        lbl_msg = tk.Label(body, text="", bg="#0f172a", fg="#fca5a5", font=("Segoe UI", 9), wraplength=500, justify="left")
        lbl_msg.pack(anchor="w", pady=(2, 0))
        if sys.platform != "win32":
            chk.config(state="disabled")

        def cerrar(): win.destroy()
        def guardar():
            tok = e_tok.get().strip()
            disp = e_disp.get().strip()
            apis = _norm_bases([s.strip() for s in e_api.get().split(",")])
            if not apis: apis = ["https://invefacon.net", "https://invefacon.com"]
            if not tok:
                lbl_msg.config(text="Pegá el token (no puede quedar vacío)."); return
            if "~" not in tok:
                lbl_msg.config(text="El token parece incompleto (debería tener la forma  empresa~aleatorio).", fg="#fbbf24")
                # igual lo dejamos guardar por si es un formato distinto, pero avisamos
            ok_file = True
            try:
                self._write_token_conf(tok)
            except Exception as e:
                ok_file = False
                lbl_msg.config(text="Guardado en memoria (no se pudo escribir token.conf: %s). Copiá la carpeta a C:\\ para que persista." % e, fg="#fbbf24")
            self._update_config_json(dispositivo_id=disp or "KIOSKO-01", api_base=apis)
            self._apply_token(tok, dispositivo_id=disp, api_bases=apis)
            if ok_file:
                win.destroy()
        tk.Button(btns, text="Cancelar", command=cerrar, bg="#334155", fg="#e2e8f0", relief="flat",
                  font=("Segoe UI", 10), padx=14, pady=6, bd=0, cursor="hand2").pack(side="right")
        tk.Button(btns, text="Guardar", command=guardar, bg="#16a34a", fg="#fff", relief="flat",
                  font=("Segoe UI", 10, "bold"), padx=18, pady=6, bd=0, cursor="hand2").pack(side="right", padx=(0, 8))
        e_tok.bind("<Return>", lambda e: guardar())
        win.protocol("WM_DELETE_WINDOW", cerrar)
        # 1.0.5: el alto sale de lo que el contenido pide (escala de Windows), nunca menos de 360
        try:
            win.update_idletasks()
            h2 = max(h, win.winfo_reqheight() + 10)
            h2 = min(h2, max(h, win.winfo_screenheight() - 80))
            win.geometry("%dx%d+%d+%d" % (w, h2,
                         self.root.winfo_rootx() + max(0, (self.root.winfo_width() - w) // 2),
                         max(0, self.root.winfo_rooty() + (self.root.winfo_height() - h2) // 2)))
            win.minsize(w, h2)
        except Exception:
            pass

    # ---------------- Enroll ----------------
    def _open_enroll(self):
        if self.enrolling or getattr(self, "_has_enroll_dialog", False): return
        self._has_enroll_dialog = True
        win = tk.Toplevel(self.root); win.title("Registrar huella"); win.configure(bg="#0f172a")
        win.transient(self.root); win.grab_set()
        w, h = 480, 330
        win.geometry("%dx%d+%d+%d" % (w, h,
                     self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2,
                     self.root.winfo_rooty() + (self.root.winfo_height() - h) // 2))
        # cuando se cierre la ventana (por cualquier motivo) bajar el flag
        def _on_destroy(ev, _w=win):
            if ev.widget is _w:
                self._has_enroll_dialog = False
        win.bind("<Destroy>", _on_destroy)

        tk.Label(win, text="Registrar huella de empleado", bg="#0f172a", fg="#e2e8f0", font=("Segoe UI", 14, "bold")).pack(pady=(18, 4))
        tk.Label(win, text=(("Empresa: " + self.serverdb) if self.serverdb else ""), bg="#0f172a", fg="#64748b", font=("Segoe UI", 9)).pack()

        body = tk.Frame(win, bg="#0f172a"); body.pack(fill="both", expand=True, padx=24, pady=16)
        tk.Label(body, text="Empleado:", bg="#0f172a", fg="#cbd5e1", font=("Segoe UI", 11)).pack(anchor="w")
        cmb = ttk.Combobox(body, state="readonly", font=("Segoe UI", 11)); cmb.pack(fill="x", pady=(2, 6))
        tk.Label(body, text="Dedo:", bg="#0f172a", fg="#cbd5e1", font=("Segoe UI", 11)).pack(anchor="w")
        dedo_cmb = ttk.Combobox(body, state="readonly", font=("Segoe UI", 11),
                                values=["right-index", "right-thumb", "right-middle", "left-index", "left-thumb"])
        dedo_cmb.set(self.cfg.get("dedo_default", "right-index")); dedo_cmb.pack(fill="x", pady=(2, 10))
        lbl_state = tk.Label(body, text="Cargando empleados...", bg="#0f172a", fg="#94a3b8",
                             font=("Segoe UI", 10), wraplength=410, justify="left"); lbl_state.pack(anchor="w", pady=(4, 8))

        btns = tk.Frame(win, bg="#0f172a"); btns.pack(fill="x", padx=24, pady=(0, 16))
        btn_cancel = tk.Button(btns, text="Cancelar", command=win.destroy, bg="#334155", fg="#e2e8f0",
                               relief="flat", font=("Segoe UI", 10), padx=14, pady=6, bd=0, cursor="hand2")
        btn_start = tk.Button(btns, text="Iniciar registro", state="disabled", bg="#16a34a", fg="#fff",
                              relief="flat", font=("Segoe UI", 10, "bold"), padx=14, pady=6, bd=0, cursor="hand2")
        btn_cancel.pack(side="right"); btn_start.pack(side="right", padx=(0, 8))
        state = {"map": {}}

        def load_emps():
            st, data = self._api("GET", "/apis/biometria/kiosko/empleados_listar.php", {}, timeout=15)
            if not data or not data.get("ok"):
                self.ui(lbl_state.config, text="Error cargando empleados: %s" % ((data or {}).get("error") or "sin respuesta")); return
            emps = data.get("empleados", []); fuente = data.get("fuente", "")
            vals = []; mp = {}
            for e in emps:
                extra = ""
                if e.get("tiene_huella"): extra += "  ·  ya tiene huella"
                if e.get("en_empleados") is False: extra += "  ·  ⚠ no figura en Empleados (no podrá marcar)"
                tag = "%s - %s%s" % (e["cod_usuario"], e.get("nombre") or "", extra)
                vals.append(tag); mp[tag] = e
            state["map"] = mp
            def _fill():
                cmb["values"] = vals
                lbl_state.config(text="%d usuario(s) activo(s) [%s]. Seleccione uno y pulse 'Iniciar registro'." % (len(vals), fuente))
            self.ui(_fill)

        def on_select(_evt=None):
            btn_start.config(state=("normal" if cmb.get() else "disabled"))
        cmb.bind("<<ComboboxSelected>>", on_select)

        def cancelar_enroll():
            # señala la cancelación al servicio; el thread run() detecta el resultado y cierra
            self.ui(lbl_state.config, text="Cancelando...")
            threading.Thread(target=lambda: http_json_safe("POST", self.fp + "/fingerprint/enroll/cancel", {}, timeout=4), daemon=True).start()

        def dots(done, needed):
            done = max(0, min(done, needed))
            return "●" * done + "○" * (needed - done)

        def do_enroll_flow():
            tag = cmb.get(); emp = state["map"].get(tag)
            if not emp: return
            usuario_codigo = emp["cod_usuario"]; usuario_nombre = emp.get("nombre") or usuario_codigo
            dedo = dedo_cmb.get() or "right-index"
            btn_start.config(state="disabled")
            btn_cancel.config(text="Cancelar registro", command=cancelar_enroll)  # sigue habilitado: sirve para abortar
            cmb.config(state="disabled"); dedo_cmb.config(state="disabled")
            self.enrolling = True
            self.ui(lbl_state.config, text="Coloque el dedo en el lector... esperando el toque 1")
            self.set_msg("Registrando huella de %s" % usuario_nombre)
            self.set_fp_color("#f59e0b"); self.set_led("#f59e0b")

            def run():
                result = {}
                def post_enroll():
                    try:
                        st, data = http_json_safe("POST", self.fp + "/fingerprint/enroll",
                                                  {"user_id": usuario_codigo, "finger": dedo}, timeout=240)
                        result["data"] = data
                    except Exception as e:
                        result["data"] = {"ok": False, "error": str(e)}
                th = threading.Thread(target=post_enroll, daemon=True); th.start()
                # mientras corre el enroll, pollear el progreso y mostrarlo
                while th.is_alive():
                    st, pg = http_json_safe("GET", self.fp + "/fingerprint/enroll/progress", timeout=4)
                    if pg and pg.get("ok"):
                        done = int(pg.get("done", 0)); needed = int(pg.get("needed", 4)); msg = pg.get("msg", "")
                        self.ui(lbl_state.config, text="%s   (%d/%d)\n%s" % (dots(done, needed), done, needed, msg))
                        self.set_msg("%s — toque %d de %d" % (usuario_nombre, min(done + 1, needed) if done < needed else needed, needed))
                    th.join(0.6)
                data = result.get("data")
                try:
                    if not data or not data.get("ok"):
                        msg = (data or {}).get("error") or "El registro de huella fallo"
                        if "cancel" in msg.lower():
                            self.ui(win.destroy); return
                        self.ui(lbl_state.config, text="FALLO: " + msg)
                        self.show_error_copiable("Registrar huella", msg, kind="error", parent=win); return
                    template_b64 = data.get("template_b64", ""); serial = data.get("serial", "")
                    self.ui(lbl_state.config, text="Huella capturada — guardando en la base de datos...")
                    up = {"usuario_codigo": usuario_codigo, "dedo": dedo, "plataforma": self.cfg.get("plataforma", "windows"),
                          "template_b64": template_b64, "lector_serial": serial, "dispositivo_id": self.cfg.get("dispositivo_id", "KIOSKO-01")}
                    st2, r2 = self._api("POST", "/apis/biometria/kiosko/huella_registrar.php", up, timeout=20)
                    if not r2 or not r2.get("ok"):
                        msg = (r2 or {}).get("error") or "No se pudo guardar la huella en la base de datos"
                        if (r2 or {}).get("needs_migration"): msg = "Falta la migracion HuellaUsuario (20260511104641)"
                        self.ui(lbl_state.config, text="Huella capturada pero NO guardada: " + msg)
                        self.show_error_copiable("Registrar huella", msg, kind="warn", parent=win); return
                    log("Huella registrada en BD: %s/%s/%s" % (usuario_codigo, dedo, self.cfg.get("plataforma")))
                    self.ui(win.destroy)
                    self.show_result("REGISTRADO", usuario_nombre, kind="ok"); time.sleep(1.2)
                    self._do_marca(usuario_codigo); time.sleep(3.5); self.clear_result()
                except Exception:
                    tb = traceback.format_exc()
                    log("Enroll flow:\n" + tb)
                    self.show_error_copiable("Registrar huella", "Error inesperado:\n\n" + tb, kind="error", parent=win)
                finally:
                    self.enrolling = False; self.set_led("#22c55e" if self.fp_connected else "#64748b")
            threading.Thread(target=run, daemon=True).start()

        btn_start.config(command=do_enroll_flow)
        win.protocol("WM_DELETE_WINDOW", lambda: (cancelar_enroll() if self.enrolling else win.destroy()))
        threading.Thread(target=load_emps, daemon=True).start()


# ---------------------------------------------------------------------------
def main():
    try:
        cfg = load_config()
    except Exception as e:
        try:
            r = tk.Tk(); r.withdraw(); messagebox.showerror("FactuPOS Kiosko", str(e))
        except Exception:
            print("ERROR:", e)
        return
    if cfg is None:
        try:
            r = tk.Tk(); r.withdraw()
            messagebox.showinfo("FactuPOS Kiosko",
                "Se creo config.json en:\n%s\n\nGenerá un token en la web (Biometría > Configurar Kiosko), "
                "guardalo en un archivo token.conf en esta carpeta, y volvé a ejecutar este programa.\n\n"
                "(También podés en su lugar poner el campo \"db\" en config.json.)" % CONFIG_FILE)
        except Exception:
            print("Se creo config.json — agregá token.conf (o 'db' en config.json) y reinicia.")
        return
    log("=" * 60)
    log("FactuPOS Biometria - Kiosko v%s (build %s)" % (APP_VERSION, BUILD_DATE))
    log("  %s | api_bases=%r | fp=%s" % (
        ("token:" + (cfg["token"][:24] + "...") if cfg["token"] else "db:" + (cfg["db"] or "(vacio)")),
        cfg["api_bases"], cfg["fp_service_url"]))
    root = tk.Tk()
    app = KioskApp(root, cfg)
    root.protocol("WM_DELETE_WINDOW", lambda: (setattr(app, "running", False), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        log("FATAL:\n" + traceback.format_exc())
