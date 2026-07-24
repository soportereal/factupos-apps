#!/usr/bin/env python3
"""Factupos-IA — asistente de soporte remoto con Claude (GTK3).

El técnico abre la ventana en la PC del cliente, describe el problema y la IA
diagnostica/corrige la estación ejecutando comandos LOCALES (con confirmación).

NO contiene la API key: habla con el proxy de la página (soportereal.com/claude-proxy),
que le agrega la key del servidor. Solo usa la librería estándar (urllib) — sin SDK.

Config por variables de entorno (o editá las constantes):
  SOPORTE_BASE_URL   -> URL del proxy
  SOPORTE_APP_TOKEN  -> token de la app (NO la key de Claude)
"""

import os
import sys
import json
import time
import socket
import platform
import threading
import datetime
import subprocess
import urllib.request
import urllib.error
import uuid

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango, Gdk

# ---------------------------------------------------------------------------
# Versión y auto-actualización
# ---------------------------------------------------------------------------
VERSION = "1.1.5"                                   # fuente única de versión
UPDATE_INTERVAL = 6 * 3600                          # re-chequeo cada 6 horas
# Ambos manifests en soportereal.com: es el server de la oficina, alcanzable
# desde PCs remotas (igual que el proxy) y desplegable con deploy.sh. El público
# factupos.com vive en AWS y NO tiene /downloads/ → daba 404 a clientes remotos.
MANIFEST_WIN   = "https://soportereal.com/software/factupos-app/windows/Factupos-IA_version.json"
MANIFEST_LINUX = "https://soportereal.com/software/factupos-app/linux/Factupos-IA_version.json"
PY_LOCAL = os.path.expanduser("~/.local/share/factupos-ia/factupos_ia.py")

# ---------------------------------------------------------------------------
# Configuración del proxy
# ---------------------------------------------------------------------------
def _cargar_config():
    """Lee base_url/token de un config.json (para la versión instalada). Env tiene prioridad."""
    rutas = []
    if os.environ.get("APPDATA"):
        rutas.append(os.path.join(os.environ["APPDATA"], "Factupos-IA", "config.json"))
    rutas += [os.path.expanduser("~/.config/factupos-ia/config.json"),
              "/etc/factupos-ia/config.json"]
    for p in rutas:
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {}

_CFG = _cargar_config()
BASE_URL  = os.environ.get("SOPORTE_BASE_URL")  or _CFG.get("base_url") or "https://soportereal.com/claude-proxy"
APP_TOKEN = os.environ.get("SOPORTE_APP_TOKEN") or _CFG.get("token")    or "pon-aqui-un-token-largo-secreto"
MODELO    = os.environ.get("SOPORTE_MODELO")    or _CFG.get("modelo")   or "claude-opus-4-8"

PLACEHOLDER_TOKEN = "pon-aqui-un-token-largo-secreto"

# URL OCULTA de donde la app baja el token vigente, sola, en cada arranque.
# El técnico no la ve ni configura nada. La rotación se hace en
# factupos.local/soporte_ia/token.php y todas las apps la toman al abrir.
# 'x-app' es un filtro liviano (no es secreto: este .py se publica). El control
# real contra abuso es el LÍMITE DE CONSUMO POR EQUIPO (device_id) en el proxy.
TOKEN_FETCH_URL = (BASE_URL.rstrip("/") + "/v1/token")
APP_IDENT       = "factupos-ia"


def _ruta_config():
    """Ruta del config.json que la app escribe (misma que lee primero)."""
    if os.environ.get("APPDATA"):
        cfgdir = os.path.join(os.environ["APPDATA"], "Factupos-IA")
    else:
        cfgdir = os.path.expanduser("~/.config/factupos-ia")
    os.makedirs(cfgdir, exist_ok=True)
    return os.path.join(cfgdir, "config.json")


def _guardar_config(cfg):
    """Escribe el dict de config completo (preserva device_id, base_url, token…)."""
    try:
        with open(_ruta_config(), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return True
    except Exception:
        return False


# device_id: identificador único y estable de ESTE equipo. Se genera una sola vez
# y se persiste; el proxy lo usa para limitar el consumo por equipo.
DEVICE_ID = (_CFG.get("device_id") or "").strip()
if not DEVICE_ID:
    DEVICE_ID = uuid.uuid4().hex
    _CFG["device_id"] = DEVICE_ID
    _guardar_config(_CFG)


def actualizar_token_remoto():
    """Baja el token vigente del servidor y lo guarda solo. Silencioso:
    si el server no responde, sigue con el token cacheado en config.json."""
    global APP_TOKEN, BASE_URL
    try:
        req = urllib.request.Request(
            TOKEN_FETCH_URL,
            headers={"x-app": APP_IDENT, "x-device-id": DEVICE_ID,
                     "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        tok = (data.get("token") or "").strip()
        if tok:
            APP_TOKEN = tok
            if data.get("base_url"):
                BASE_URL = str(data["base_url"]).strip()
            _CFG["token"]    = APP_TOKEN
            _CFG["base_url"] = BASE_URL
            _guardar_config(_CFG)
            return True
    except Exception:
        pass
    return False

SO   = platform.system()           # 'Windows' o 'Linux'
HOST = socket.gethostname()

LOG_DIR = (os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Factupos-IA")
           if SO == "Windows" else os.path.expanduser("~/.factupos-ia"))
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "bitacora.log")

SISTEMA = f"""Sos un técnico de soporte de FactuPOS trabajando EN VIVO en la PC de un cliente.
Sistema operativo: {SO} ({platform.platform()}). Equipo: {HOST}.

Diagnosticás y corregís problemas de la estación FactuPOS: Apache/PHP, conexión a
SQL Server, servicios del sistema, archivos de configuración, impresoras y APIs.

Reglas:
- Antes de cambiar algo, revisá el estado actual con comandos de SOLO LECTURA.
- Explicá en español, breve, qué vas a hacer y por qué.
- Usá comandos propios de {SO}.
- No ejecutes acciones destructivas salvo que sean necesarias; el técnico las confirma.
- Cuando termines o necesites una decisión del técnico, decilo claramente."""

PELIGROSOS = ["rm ", "del ", "format", "mkfs", "dd ", "shutdown", "reboot",
              "rmdir", "rd /s", "drop ", "truncate", "fdisk", "diskpart",
              "reg delete", "remove-item", "rm-rf", "rm -rf"]


def es_peligroso(cmd: str) -> bool:
    c = cmd.lower()
    return any(p in c for p in PELIGROSOS)


# ---------------------------------------------------------------------------
# Herramientas que la IA puede pedir ejecutar
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "ejecutar_comando",
        "description": f"Ejecuta un comando de shell en esta PC ({SO}) y devuelve stdout+stderr.",
        "input_schema": {
            "type": "object",
            "properties": {
                "comando": {"type": "string", "description": "Comando a ejecutar"},
                "motivo":  {"type": "string", "description": "Para qué sirve este comando"},
            },
            "required": ["comando"],
        },
    },
    {
        "name": "leer_archivo",
        "description": "Lee el contenido de un archivo de la PC (máx 8000 caracteres).",
        "input_schema": {
            "type": "object",
            "properties": {"ruta": {"type": "string"}},
            "required": ["ruta"],
        },
    },
    {
        "name": "escribir_archivo",
        "description": "Escribe/reemplaza un archivo. SIEMPRE requiere confirmación del técnico.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ruta":      {"type": "string"},
                "contenido": {"type": "string"},
            },
            "required": ["ruta", "contenido"],
        },
    },
    {
        "name": "info_sistema",
        "description": "Devuelve información básica del sistema (SO, equipo, red).",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def ejecutar_tool(app, nombre, args):
    """Ejecuta la herramienta pedida por la IA. Corre en el hilo de trabajo."""
    if nombre == "ejecutar_comando":
        cmd    = args.get("comando", "")
        motivo = args.get("motivo", "")
        if app.requiere_confirmacion(cmd):
            if not app.confirmar("¿Ejecutar este comando?", cmd, motivo):
                app.log(f"⛔ Comando rechazado por el técnico: {cmd}")
                return "El técnico RECHAZÓ este comando. No lo ejecutes; proponé otra alternativa."
        app.log(f"$ {cmd}")
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True,
                               text=True, timeout=120)
            salida = (r.stdout + r.stderr).strip() or "(sin salida)"
        except Exception as e:
            salida = f"ERROR: {e}"
        app.log(salida[:2000])
        return salida[:8000]

    if nombre == "leer_archivo":
        ruta = args.get("ruta", "")
        app.log(f"📄 Leyendo: {ruta}")
        try:
            with open(ruta, "r", encoding="utf-8", errors="replace") as f:
                return f.read()[:8000]
        except Exception as e:
            return f"ERROR: {e}"

    if nombre == "escribir_archivo":
        ruta      = args.get("ruta", "")
        contenido = args.get("contenido", "")
        if not app.confirmar("¿Escribir este archivo?", ruta,
                             f"Se reemplazará el contenido de:\n{ruta}"):
            app.log(f"⛔ Escritura rechazada: {ruta}")
            return "El técnico RECHAZÓ escribir este archivo."
        try:
            if os.path.exists(ruta):
                os.replace(ruta, ruta + ".bak")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(contenido)
            app.log(f"💾 Escrito: {ruta} (respaldo .bak)")
            return f"Archivo escrito correctamente: {ruta}"
        except Exception as e:
            return f"ERROR: {e}"

    if nombre == "info_sistema":
        try:
            usuario = os.getlogin()
        except Exception:
            usuario = os.environ.get("USER") or os.environ.get("USERNAME") or "?"
        return (f"SO: {platform.platform()}\nEquipo: {HOST}\n"
                f"Python: {platform.python_version()}\nUsuario: {usuario}")

    return f"Herramienta desconocida: {nombre}"


# ---------------------------------------------------------------------------
# Llamada al proxy (stdlib, sin SDK)
# ---------------------------------------------------------------------------
def llamar_claude(messages):
    body = json.dumps({
        "model": MODELO,
        "max_tokens": 8000,
        "system": SISTEMA,
        "tools": TOOLS,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "medium"},
        "messages": messages,
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL.rstrip("/") + "/v1/messages",
        data=body, method="POST",
        headers={"content-type": "application/json",
                 "Authorization": "Bearer " + APP_TOKEN,
                 "x-device-id": DEVICE_ID,
                 "x-hostname": HOST})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Auto-actualización (estilo Bridge/Panel)
# ---------------------------------------------------------------------------
def _vtuple(v):
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except Exception:
        return (0,)


def _leer_manifest(url):
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _update_windows(app, manual=False):
    if not getattr(sys, "frozen", False):
        if manual:
            app.log("Auto-update: solo disponible en la versión instalada (.exe).")
        return
    man    = _leer_manifest(MANIFEST_WIN)
    latest = str(man.get("version", "")).strip()
    url    = str(man.get("downloadUrl", "")).strip()
    if not (latest and url and _vtuple(latest) > _vtuple(VERSION)):
        if manual:
            app.log(f"Ya estás en la última versión (v{VERSION}).")
        return
    base = os.path.dirname(sys.executable)
    exe  = os.path.basename(sys.executable)
    new  = os.path.join(base, exe.replace(".exe", "_new.exe"))
    app.log(f"⬇️ Descargando v{latest}…")
    urllib.request.urlretrieve(url, new)
    if os.path.getsize(new) < 500000:        # < 0.5MB = HTML de error, abortar
        os.remove(new)
        app.log("Auto-update: descarga inválida, abortado.")
        return
    bat = os.path.join(base, "updater.bat")
    with open(bat, "w", encoding="ascii") as f:
        f.write("@echo off\r\n")
        f.write("timeout /t 3 /nobreak >nul\r\n")
        f.write('taskkill /f /im "%s" >nul 2>&1\r\n' % exe)
        f.write('del "%s"\r\n' % exe)
        f.write('ren "%s" "%s"\r\n' % (os.path.basename(new), exe))
        f.write('start "" "%s"\r\n' % exe)
        f.write('del "%%~f0"\r\n')
    app.log(f"Actualizando a v{latest}, reiniciando…")
    subprocess.Popen(["cmd.exe", "/c", bat], cwd=base,
                     creationflags=0x00000008, close_fds=True)  # DETACHED_PROCESS
    os._exit(0)


def _update_linux(app, manual=False):
    man  = _leer_manifest(MANIFEST_LINUX)
    newv = str(man.get("version", "")).strip()
    if not newv or _vtuple(newv) <= _vtuple(VERSION):
        if manual:
            app.log(f"Ya estás en la última versión (v{VERSION}).")
        return
    pyurl = man.get("py")
    if not pyurl:
        return
    app.log(f"⬇️ Descargando v{newv}…")
    with urllib.request.urlopen(pyurl, timeout=25) as r:
        data = r.read()
    if b"Factupos-IA" not in data or b"def main(" not in data:
        app.log("Auto-update: contenido inválido, descartado.")
        return
    os.makedirs(os.path.dirname(PY_LOCAL), exist_ok=True)
    tmp = PY_LOCAL + ".new"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, PY_LOCAL)
    app.log(f"Actualizado a v{newv}, reiniciando…")
    GLib.timeout_add_seconds(1, app.reiniciar)


def buscar_actualizacion(app, manual=False):
    try:
        if SO == "Windows":
            _update_windows(app, manual)
        else:
            _update_linux(app, manual)
    except Exception as e:
        app.log(f"Auto-update: {e}")


def update_loop(app):
    time.sleep(8)
    while True:
        buscar_actualizacion(app, manual=False)
        time.sleep(UPDATE_INTERVAL)


# ---------------------------------------------------------------------------
# Ventana principal
# ---------------------------------------------------------------------------
class SoporteApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="Factupos-IA")
        self.set_default_size(840, 660)
        self.set_border_width(8)

        self._busy = False
        self.messages = []

        # Estilos del campo: verde = listo para escribir, rojo = trabajando
        _css = Gtk.CssProvider()
        _css.load_from_data(
            b"entry{background:#fff176;color:#000000;caret-color:#000000;"
            b"font-size:14px;padding:8px;}"
            b"entry.listo{border:2px solid #2e7d32;}"
            b"entry.ocupado{border:2px solid #c62828;}"
            b"entry placeholder{color:#777777;}"
            b"textview, textview text{background:#ffffff;color:#000000;font-size:14px;}")
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), _css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        caja = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(caja)

        # Encabezado con versión + botón de actualización
        hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        titulo = Gtk.Label(xalign=0)
        titulo.set_markup(f"<b>Factupos-IA</b>  v{VERSION}  —  {HOST} · {SO}")
        hdr.pack_start(titulo, True, True, 0)
        btn_upd = Gtk.Button(label="Buscar actualización")
        btn_upd.connect("clicked", self.on_buscar_update)
        hdr.pack_start(btn_upd, False, False, 0)
        caja.pack_start(hdr, False, False, 0)

        # Conversación / bitácora
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.vista = Gtk.TextView()
        self.vista.set_editable(False)
        self.vista.set_cursor_visible(False)
        self.vista.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.vista.override_font(Pango.FontDescription("Monospace 14"))
        scroll.add(self.vista)
        caja.pack_start(scroll, True, True, 0)

        fila = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.entrada = Gtk.Entry()
        self.entrada.set_placeholder_text("Describí el problema de la estación…")
        self.entrada.get_style_context().add_class("listo")
        self.entrada.connect("activate", self.on_enviar)
        self.boton = Gtk.Button(label="Enviar")
        self.boton.connect("clicked", self.on_enviar)
        fila.pack_start(self.entrada, True, True, 0)
        fila.pack_start(self.boton, False, False, 0)
        caja.pack_start(fila, False, False, 0)

        self.log(f"Factupos-IA v{VERSION} · conectado a: {BASE_URL}")
        if APP_TOKEN == PLACEHOLDER_TOKEN:
            self.log("⚠️ Sin conexión con el servidor de soporte. Reintentá más tarde.")
        self.log("Escribí el problema y presioná Enviar.\n")

    # --- utilidades de UI (seguras desde otros hilos) ---
    def log(self, texto):
        def _append():
            buf = self.vista.get_buffer()
            buf.insert(buf.get_end_iter(), texto + "\n")
            # Autoscroll fiable al FINAL. Antes usaba get_insert() (el cursor), que en
            # un TextView no editable queda en la posición 0 → el log saltaba al INICIO
            # y lo último quedaba abajo sin verse. Un mark propio en el final, alineado
            # abajo (yalign=1.0), mantiene siempre a la vista lo recién escrito.
            fin = buf.get_mark("fin")
            if fin is None:
                fin = buf.create_mark("fin", buf.get_end_iter(), False)
            else:
                buf.move_mark(fin, buf.get_end_iter())
            self.vista.scroll_to_mark(fin, 0.0, True, 0.0, 1.0)
            return False
        GLib.idle_add(_append)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now().isoformat()} | {texto}\n")
        except Exception:
            pass

    def set_busy(self, busy):
        self._busy = busy
        self.boton.set_sensitive(not busy)
        self.boton.set_label("Trabajando…" if busy else "Enviar")
        ctx = self.entrada.get_style_context()
        if busy:
            ctx.remove_class("listo"); ctx.add_class("ocupado")
        else:
            ctx.remove_class("ocupado"); ctx.add_class("listo")

    def requiere_confirmacion(self, cmd):
        return es_peligroso(cmd)

    def confirmar(self, titulo, detalle, motivo=""):
        """Bloquea el hilo de trabajo hasta que el técnico decide."""
        evento    = threading.Event()
        resultado = {"ok": False}

        def _dialog():
            d = Gtk.MessageDialog(transient_for=self, modal=True,
                                  message_type=Gtk.MessageType.WARNING,
                                  buttons=Gtk.ButtonsType.NONE, text=titulo)
            d.format_secondary_text((motivo + "\n\n" if motivo else "") + detalle)
            d.add_button("Rechazar", Gtk.ResponseType.NO)
            btn_ok = d.add_button("Ejecutar", Gtk.ResponseType.YES)
            btn_ok.get_style_context().add_class("suggested-action")
            resultado["ok"] = (d.run() == Gtk.ResponseType.YES)
            d.destroy()
            evento.set()
            return False

        GLib.idle_add(_dialog)
        evento.wait()
        return resultado["ok"]

    def reiniciar(self):
        launcher = "/usr/bin/factupos-ia"
        try:
            if os.path.exists(launcher):
                os.execv(launcher, [launcher])
            else:
                destino = PY_LOCAL if os.path.exists(PY_LOCAL) else os.path.abspath(sys.argv[0])
                os.execv(sys.executable, [sys.executable, destino])
        except Exception as e:
            self.log(f"No se pudo reiniciar: {e}")
        return False

    # --- acciones ---
    def on_buscar_update(self, *_):
        self.log("Buscando actualizaciones…")
        threading.Thread(target=buscar_actualizacion, args=(self, True), daemon=True).start()

    def on_enviar(self, *_):
        if self._busy:
            self.log("Esperá a que termine la respuesta anterior (campo en rojo).")
            return
        texto = self.entrada.get_text().strip()
        if not texto:
            return
        self.entrada.set_text("")
        self.log(f"\n🧑 {texto}")
        self.messages.append({"role": "user", "content": texto})
        self.set_busy(True)
        threading.Thread(target=self.correr_agente, daemon=True).start()

    def correr_agente(self):
        try:
            while True:
                try:
                    resp = llamar_claude(self.messages)
                except urllib.error.HTTPError as e:
                    cuerpo = e.read().decode("utf-8", "replace")
                    self.log(f"⚠️ Error {e.code}: {cuerpo[:400]}")
                    break

                if resp.get("type") == "error":
                    self.log(f"⚠️ {resp.get('error', {}).get('message', resp)}")
                    break

                contenido = resp.get("content", [])
                self.messages.append({"role": "assistant", "content": contenido})

                for b in contenido:
                    if b.get("type") == "text" and b.get("text", "").strip():
                        self.log(f"🤖 {b['text'].strip()}")

                if resp.get("stop_reason") != "tool_use":
                    break

                resultados = []
                for b in contenido:
                    if b.get("type") == "tool_use":
                        salida = ejecutar_tool(self, b["name"], b.get("input", {}))
                        resultados.append({"type": "tool_result",
                                           "tool_use_id": b["id"], "content": salida})
                self.messages.append({"role": "user", "content": resultados})
        except Exception as e:
            self.log(f"⚠️ Error: {e}")
        finally:
            GLib.idle_add(lambda: self.set_busy(False))


def main():
    # En cada arranque, bajar el token vigente del servidor (silencioso).
    actualizar_token_remoto()
    app = SoporteApp()
    app.connect("destroy", Gtk.main_quit)
    app.show_all()
    threading.Thread(target=update_loop, args=(app,), daemon=True).start()
    Gtk.main()


if __name__ == "__main__":
    main()
