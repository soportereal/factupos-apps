#!/usr/bin/env python3
"""
FactuPOS Print Client v2.4
===========================
Cliente de impresión con GUI para seleccionar impresoras.
Conecta al servidor de colas via WebSocket con failover.
Se minimiza a la bandeja del sistema (system tray).
Auto-update silencioso cuando el servidor reporta nueva versión.

Compatible: Windows 7+ y Linux (Ubuntu/Debian con CUPS).

Requisitos Windows:
    pip install websocket-client pywin32 pystray Pillow

Requisitos Linux:
    pip install websocket-client pystray Pillow
    sudo apt install python3-tk cups

Empaquetar como .exe (Win7 32-bit compatible):
    Usar Python 3.8.x (32-bit) — última versión con soporte Win7.
    Ver build_win7.bat y requirements_win7.txt para instrucciones.

Empaquetar como .deb (Ubuntu):
    Ver build_linux.sh para instrucciones.
"""

import json
import base64
import sys
import os
import time
import threading
import logging
import socket
import subprocess
import urllib.request
import platform
import tempfile
from datetime import datetime
from collections import deque

IS_LINUX = platform.system() == 'Linux'
IS_WINDOWS = platform.system() == 'Windows'

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

def _dir_datos():
    """Carpeta donde viven config.json y print_client.log.

    Lo normal es la carpeta de la app: el postinst del .deb la deja en chmod 777
    y el instalador de Windows da Modify, asi que config y log quedan junto al
    programa. PERO si no es escribible — .deb desempacado que quedo SIN
    CONFIGURAR por dependencias, permisos apretados a mano — la app se moria con
    PermissionError al crear el FileHandler del log, o sea ANTES de dibujar la
    ventana: no abria, no dejaba proceso y no mostraba ni un error (el .desktop
    va con Terminal=false). Sintoma en campo: "solo arranca con sudo".
    Ahora cae al perfil del usuario, que siempre es escribible.
    """
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        prueba = os.path.join(APP_DIR, '.prueba_escritura')
        with open(prueba, 'w'):
            pass
        os.remove(prueba)
        return APP_DIR
    except Exception:
        try:
            alterno = os.path.join(os.path.expanduser('~'), '.config', 'factupos-print')
            os.makedirs(alterno, exist_ok=True)
            return alterno
        except Exception:
            return tempfile.gettempdir()


DATA_DIR = _dir_datos()
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
LOG_FILE = os.path.join(DATA_DIR, 'print_client.log')

# Auto-update en Linux: el .deb instala el .py crudo (no es un binario frozen),
# así que NO se puede usar el flujo de Windows (.exe + updater.bat). En su lugar
# se reemplaza el propio .py en sitio (el postinst deja /opt/factupos-print en
# chmod 777 → escribible sin sudo) y el proceso se re-lanza.
# OJO: el server WS anuncia la versión leyendo el manifest print_client_version.json
# y manda un único downloadUrl (el .exe de Windows). En Linux ese downloadUrl se
# IGNORA y se baja el .py de estas URLs. El .py publicado DEBE ir en la misma
# versión que el manifest, o el cliente entra en loop de update.
# Host ÚNICO = soportereal.com/software/factupos-app/linux/ (todas las apps de
# FactuPOS se publican ahí). invefacon.com se RETIRÓ de la config (2026-06-30):
# todo el auto-update apunta solo a soportereal. NOTA de transición: los clientes
# instalados ANTES de la 4.54 traían invefacon hardcodeado; siguen sirviéndose el
# .py 4.54 desde factupos.com/downloads (= invefacon, mismo server) para que hagan
# ESA actualización y queden ya apuntando solo a soportereal. El .py publicado DEBE
# ir en la misma versión que el manifest, o el cliente entra en loop de update.
LINUX_UPDATE_URLS = [
    'https://soportereal.com/software/factupos-app/linux/factupos_print_client.py',
]
# Archivo de versión DEDICADO a Linux: la app Linux lo consulta directo (solo
# soportereal.com), independiente del manifest del WS (que es de Windows). Así se
# controla la versión Linux por separado de la de Windows. Mismo host que el .py.
LINUX_VERSION_URLS = [
    'https://soportereal.com/software/factupos-app/linux/print_client_version_linux.json',
]
# Cada cuántos segundos revisa la versión el chequeo periódico (Linux). 600 = 10 min.
UPDATE_CHECK_INTERVAL = 600
# El servidor de colas expone una API HTTP en el puerto del WS + 1 (9300 → 9301).
# Se usa para vaciar la cola del servidor (POST /job-delete).
HTTP_API_PORT = 9301
# PUERTO LOCAL (#1778, FactuSuper): la web del MISMO equipo le entrega el trabajo directo a la
# app cuando NO hay internet (con internet todo sigue por la nube). Solo escucha en 127.0.0.1:
# desde la red no se alcanza. 9302 y no 8765 porque el 8765 es del Bridge (ruta 3) y pueden
# estar instalados los dos en la misma caja.
PUERTO_LOCAL = 9302
PUERTO_LOCAL_MAX_BYTES = 2 * 1024 * 1024
# Solo estas páginas pueden mandar a imprimir (si no, cualquier sitio abierto en el navegador
# de la caja podría sacar papel). Se amplía por config.json → "puertoLocalOrigenes".
PUERTO_LOCAL_DOMINIOS = ('factupos.com', 'factupos.local', 'soportereal.com', 'invefacon.com')
# Un trabajo a la vez en la impresora, venga de la nube o del puerto local.
IMPRESION_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Ultimo seguro: aunque _dir_datos() ya devuelve una carpeta escribible, si el
# archivo de log no se puede abrir la app NO debe morir — se queda sin log pero
# abre. Antes esto era la causa #1 de "instale y no pasa nada".
_handlers = [logging.StreamHandler(sys.stdout)]
try:
    _handlers.append(logging.FileHandler(LOG_FILE, encoding='utf-8'))
except Exception as _e:
    print(f"AVISO: sin archivo de log ({_e}). La app sigue funcionando.")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=_handlers
)
log = logging.getLogger('PrintClient')

# ---------------------------------------------------------------------------
# Imports opcionales
# ---------------------------------------------------------------------------
try:
    import websocket
except ImportError:
    print("ERROR: Falta librería 'websocket-client'")
    print("Instale con: pip install websocket-client")
    sys.exit(1)

HAS_WIN32 = False
HAS_WIN32UI = False
if IS_WINDOWS:
    try:
        import win32print
        HAS_WIN32 = True
    except ImportError:
        log.warning("win32print no disponible — modo simulación")
    try:
        import win32ui
        import win32con
        HAS_WIN32UI = True
    except ImportError:
        log.warning("win32ui no disponible — spooler usará texto raw sin fuente")

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# System tray
# Se atrapa Exception y no solo ImportError: pystray elige backend al importarse
# y puede reventar por cosas que NO son "falta el modulo" (sin servidor X, DISPLAY
# mal, AppIndicator roto). Eso escapaba del except y mataba la app entera antes de
# abrir la ventana — sin bandeja tiene que quedar visible, no muerta.
try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except Exception as _e:
    HAS_TRAY = False
    log.warning(f"Sin bandeja del sistema ({_e}) — la ventana queda visible")

# VERSION por plataforma (canales independientes): en Linux la app consulta su propio
# archivo (print_client_version_linux.json en invefacon); en Windows lo anuncia el WS.
VERSION = ("4.61" if IS_LINUX else "4.54")  # 4.61(linux)/4.54(win): PUERTO LOCAL 127.0.0.1:9302 (#1778, FactuSuper). Regla del dueño: la unica parte que necesita internet es mandar la venta a procesar; imprimir tiene que salir igual sin internet. La web arma el documento en el equipo y lo entrega a la app por 127.0.0.1:9302 (GET /ping, POST /print {queue, data base64|text, empresa?, jobId?}); sale por el MISMO imprimir_trabajo() que los trabajos de la nube (separado de _handle_print_job, que ahora solo hace el ACK), con la impresora, corte, cajon y letra de esa cola. Solo 127.0.0.1 (desde la red no se alcanza) y solo paginas de factupos.com/soportereal.com/invefacon.com/factupos.local (CORS + Private-Network); jobId repetido no reimprime; un trabajo a la vez (IMPRESION_LOCK) entre nube y puerto local. 9302 y no 8765: el 8765 es del Bridge. Si el puerto esta ocupado la app sigue por la nube. 4.60(linux)/4.53(win): #760 (Francisco Aguero, ferrebribri) IMPRESION QUE SE CORTA SOLA. Una matricial Epson tiene el buffer de entrada chico: si se le entrega un documento largo de un solo write, imprime hasta donde le alcanzo y el resto SE PIERDE. No da error — el trabajo sale como "impreso" y el papel termina a mitad. Se vio con una proforma de 19 lineas (~90 renglones): salieron TODAS las lineas y se corto justo antes de los totales. El envio en trozos con pausa ya existia pero SOLO para termicas (print_raw_thermal); las matriciales seguian yendo de un tiro. Ahora el troceo es UNO SOLO (_escribir_en_trozos) y lo usan print_raw (RAW de Windows) y print_raw_virtual_port (LPTx / /dev/usb/lpX), que es el camino sin spooler y por lo tanto el que de verdad pierde bytes. 🔑 El flush va DENTRO del bucle: sin el, Python junta los trozos en su propio buffer y la pausa no sirve de nada. Se puede afinar POR IMPRESORA con chunkSize/chunkDelay en el perfil, sin tocar el programa. Linux por CUPS (lp) no cambia: ahi el control de flujo lo hace el spooler. 4.59(linux): ventana mas ancha. La tabla de impresoras cortaba "Impresora" y "Modo/Opciones" — justo las dos que uno mira para saber por donde sale cada cola, y peor desde 4.58 que la columna de impresora lleva el transporte adelante ("Red · 192.168.1.50:9100"). Ancho 880->1160 y columnas con minwidth+stretch. El alto se limita al de la PANTALLA (min(800, alto-120)): en cajas de 1366x768 una ventana de 800 dejaba los botones fuera del monitor, sin forma de llegarles. Mismo cuidado en el formulario de impresora. 4.58(linux): PARIDAD DE TRANSPORTES CON ANDROID. Cada impresora ahora tiene `transport` y el formulario cambia los campos segun cual se elija, igual que el FactuPOS Print de Android. NUEVOS: **ip** (socket 9100, con tope duro de 20s en hilo aparte porque una impresora de red puede aceptar la conexion y colgarse -> congelaria toda la cola; boton "Probar conexion" antes de guardar), **serial** de verdad con pyserial fijando baudios 8N1 (antes se abria /dev/ttyUSB0 como archivo y se heredaba la velocidad del puerto = simbolos raros), **bluetooth** por RFCOMM con el socket NATIVO de Python (AF_BLUETOOTH, sin pybluez; envio en chunks de 256 como en Android). USB ya funcionaba via CUPS o /dev/usb/lp0. `despachar_raw()` es el UNICO punto de salida (equivale a PrinterManager.printBytes de Android) y "Probar" usa ese mismo camino. Migracion automatica: los perfiles de campo deducen su transport y **siguen imprimiendo igual** (un serial migrado sin baudios usa el metodo viejo a proposito). Agregar y Editar eran 354 lineas calcadas -> un solo `_dialogo_impresora`. Las filas de la tabla ahora se identifican por INDICE y no comparando textos (Quitar borraba TODOS los perfiles que coincidieran en cola+empresa+impresora). 4.57(linux): INSTALACION a prueba de balas. (1) config.json y el log ya no matan el arranque: si la carpeta de la app no es escribible se cae a ~/.config/factupos-print (antes el FileHandler del log reventaba a nivel de modulo, ANTES de la ventana -> "instale y no abre / solo con sudo", sin proceso ni mensaje porque el .desktop va con Terminal=false). (2) --hidden por fin SE LEE: oculta solo desde el autostart; abierta del menu se VE (antes se ocultaba siempre y en GNOME sin AppIndicator quedaba inalcanzable). (3) el .deb trae /opt/factupos-print ya en 0777 y con icono de escritorio, asi no depende de que el postinst corra. 4.56(linux)/4.52(win): boton "Limpiar cola" en MainWindow — cancela los trabajos pegados en el spooler del equipo (win32print JOB_CONTROL_DELETE / CUPS `cancel -a`) Y borra del servidor los jobs 'queued' de esa cola (POST /job-delete con {empresa,queue}, rama NUEVA en server.js de la .17). Hay que vaciar las DOS: si solo se limpia el spooler, el server re-entrega los pendientes al reconectar (flushPendingJobs); si solo se limpia el server, lo ya spooleado igual sale por la impresora. Las impresoras por puerto virtual (/dev/usb*, COM*) no pasan por el spooler → solo se limpia la del server. 4.55(linux): PRUEBA de auto-update (sin cambios funcionales). 4.54(linux)/4.51(win): factura FIPVIVI005 — linea "Detalle:" (instrucciones de entrega) ahora 12pt y TODA en negrita (estilo DetalleGrande; antes N8=8pt con solo el rotulo en negrita). Pedido reporte #111 (Cpinto). 4.53(linux)/4.50(win): auto-update SOLO si el server reporta version MAYOR (antes era '!=', que hacia downgrade/loop si el manifest quedaba atras). Nuevo helper _version_gt compara por componentes numericos. 4.49: auto-update en LINUX — el .deb instala el .py crudo (no frozen) asi que el flujo Windows (.exe+updater.bat) no aplicaba; ahora en Linux se baja el .py de factupos.com/downloads, se valida version+integridad, se reemplaza en sitio (/opt es 777, sin sudo) y el proceso se re-lanza desacoplado. El server WS no cambia (anuncia latestVersion del manifest); en Linux se ignora el downloadUrl del .exe. AL PUBLICAR: subir el .py a downloads/ en la MISMA version del manifest. 4.48: factura FIPVIVI005 — la etiqueta ORIGINAL/COPIA la decide el SERVIDOR (PHP) y manda un trabajo por hoja con json 'copia_etiqueta' (vacio = sin etiqueta; respeta el parametro 394). La app ya no itera copias ni rotula: imprime lo que le llega. Compat con web vieja (json 'copias' -> itera/rotula). 4.47: formato factura FIPVIVI005 — numeracion "Pagina X de Y", Codigo antes de Cabys, letra mas grande en detalle, "Recibido Conforme"/legal/ORIGINAL no se parte entre hojas (KeepTogether). 4.46: instalador Windows (Inno Setup) — autostart oculto + auto-update sin UAC (icacls Modify); se quitaron los checkboxes Auto-ocultar/Iniciar con el sistema (los maneja el instalador); arranque oculto con flag --hidden. 4.45: paridad con Linux — boton Probar (ticket A/B + cajon + corte), tipo de letra Epson A/B por impresora, look navy + version grande, letra grande. Conserva fix hashlib + barcode128 GDI propios de Windows.
def _version_gt(remote, local):
    """True solo si la version 'remote' (la que reporta el server) es ESTRICTAMENTE
    MAYOR que 'local' (la del cliente). Compara por componentes numericos
    ('4.49' -> (4, 49)). Asi el cliente NUNCA hace downgrade ni entra en loop de
    actualizacion cuando el server reporta una version igual o anterior a la suya."""
    def _t(v):
        try:
            return tuple(int(p) for p in str(v).strip().split('.'))
        except (ValueError, AttributeError):
            return ()
    rt, lt = _t(remote), _t(local)
    if not rt:
        return False  # version remota ilegible -> no actualizar
    return rt > lt


# Fix ReportLab con Python/_hashlib viejo: algunas versiones de ReportLab llaman
# hashlib.md5(data, usedforsecurity=False) para los IDs de objetos del PDF, pero
# el openssl_md5 del build congelado no acepta ese keyword y rompe la generación
# del PDF con: "'usedforsecurity' is an invalid keyword argument for openssl_md5()".
# Envolvemos md5 para reintentar sin el keyword solo si no está soportado.
import hashlib as _hashlib
_orig_md5 = _hashlib.md5
def _safe_md5(*args, **kwargs):
    try:
        return _orig_md5(*args, **kwargs)
    except TypeError:
        kwargs.pop('usedforsecurity', None)
        return _orig_md5(*args, **kwargs)
_hashlib.md5 = _safe_md5

# ReportLab para FIPVIVI005 DataReport
HAS_REPORTLAB = False
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import mm, cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    HAS_REPORTLAB = True
except ImportError:
    log.warning("reportlab no disponible — FIPVIVI005 DataReport deshabilitado")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "servers": [
        "ws://print.invefacon.com:9300",
        "ws://print.invefacon.net:9300"
    ],
    "clientId": "",
    "token": "",
    "reconnectInterval": 5,
    "autoHide": False,
    "printers": []
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        # Migrar campo "server" viejo a "servers"
        if 'server' in cfg and 'servers' not in cfg:
            cfg['servers'] = [cfg.pop('server')]
        # Migrar formato viejo Linux (device/deviceType) a formato unificado
        migrated = False
        for p in cfg.get('printers', []):
            if 'device' in p and 'windowsPrinter' not in p:
                device = p.get('device', '')
                device_type = p.get('deviceType', 'cups')
                # cups:PrinterName → windowsPrinter=PrinterName, printMode=spooler
                if device.startswith('cups:'):
                    p['windowsPrinter'] = device.replace('cups:', '')
                    p['printMode'] = 'spooler'
                # serial:/dev/ttyUSBx → windowsPrinter=/dev/ttyUSBx, printMode=raw, virtualPort
                elif device_type == 'serial' or device.startswith('/dev/'):
                    p['windowsPrinter'] = device
                    p['printMode'] = 'raw'
                    p['virtualPort'] = device
                    p['isThermal'] = True
                else:
                    p['windowsPrinter'] = device
                    p['printMode'] = 'raw'
                if 'printerCode' not in p:
                    p['printerCode'] = p.get('queueCode', '')
                migrated = True

            # --- Migracion a `transport` (paridad con Android) ---
            # Los perfiles de campo no tienen el campo: se DEDUCE de lo que ya
            # hay, sin preguntarle nada al usuario y sin cambiar por donde sale
            # el papel. Solo se le pone nombre a lo que ya hacia.
            if 'transport' not in p:
                vport = str(p.get('virtualPort', '') or '').strip()
                if vport:
                    # /dev/ttyUSB0 y /dev/ttyS0 son SERIE aunque hasta hoy se
                    # abrieran como archivo. Se marcan como 'serial' pero sin
                    # baudios: sin baudios el envio usa el metodo viejo, o sea
                    # se comporta EXACTAMENTE igual que antes. Si el usuario
                    # despues elige velocidad, mejora.
                    if '/ttyUSB' in vport or '/ttyACM' in vport or '/ttyS' in vport:
                        p['transport'] = 'serial'
                    else:
                        p['transport'] = 'virtual'
                    p.setdefault('address', vport)
                else:
                    p['transport'] = 'cups'
                    p.setdefault('address', p.get('windowsPrinter', p.get('printer', '')))
                migrated = True

        if migrated:
            save_config(cfg)
        return cfg
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)

# ---------------------------------------------------------------------------
# ESC/POS Commands
# ---------------------------------------------------------------------------
ESCPOS_CUT_PAPER  = b'\x1d\x56\x42\x03'    # GS V 66 3 = feed 3 lines + partial cut
ESCPOS_OPEN_DRAWER = b'\x1b\x70\x00\x19\x19'  # ESC p 0 25 25 = kick pin 2
ESCPOS_INIT       = b'\x1b\x40'              # ESC @ = inicializar impresora

# ---------------------------------------------------------------------------
# Tema visual NAVY (look del modal "Configuración de Estación")
# ---------------------------------------------------------------------------
NAVY      = '#1a4d80'   # header
NAVY_DARK = '#15406b'   # hover/activo
BODY      = '#eef3fa'   # fondo cuerpo
CARD      = '#ffffff'
TEXT      = '#1f2937'
HEADTXT   = '#bfe3ff'   # versión / acentos claros
STRIP     = '#dbe7f5'   # barra de estado
BASE_FONT_SIZE = 13     # letra grande, legible para adulto mayor

def apply_navy_theme(widget):
    """Aplica el look navy + letra grande (legible para adulto mayor) a toda la app."""
    import tkinter as tk
    from tkinter import ttk
    import tkinter.font as tkfont
    try:
        widget.configure(bg=BODY)
    except Exception:
        pass

    # Escalar fuentes base de Tk (afecta tk y ttk, incluido combobox/entry/menús)
    for fname in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
        try:
            tkfont.nametofont(fname).configure(size=BASE_FONT_SIZE)
        except Exception:
            pass

    FB = ('Segoe UI', BASE_FONT_SIZE)
    FBB = ('Segoe UI', BASE_FONT_SIZE, 'bold')
    style = ttk.Style(widget)
    try:
        style.theme_use('clam')
    except Exception:
        pass
    style.configure('.', background=BODY, foreground=TEXT, font=FB)
    style.configure('TFrame', background=BODY)
    style.configure('TLabel', background=BODY, foreground=TEXT, font=FB)
    style.configure('TLabelframe', background=BODY, bordercolor='#c9d8ea')
    style.configure('TLabelframe.Label', background=BODY, foreground=NAVY, font=FBB)
    style.configure('TButton', background=NAVY, foreground='white', bordercolor=NAVY,
                    focuscolor=NAVY, padding=(14, 9), font=FBB)
    style.map('TButton',
              background=[('active', NAVY_DARK), ('disabled', '#9fb3cc')],
              foreground=[('disabled', '#e5e7eb')])
    style.configure('Accent.TButton', background=NAVY, foreground='white',
                    padding=(16, 10), font=('Segoe UI', BASE_FONT_SIZE + 1, 'bold'))
    style.map('Accent.TButton', background=[('active', NAVY_DARK)])
    style.configure('TCheckbutton', background=BODY, foreground=TEXT, font=FB)
    style.map('TCheckbutton', background=[('active', BODY)])
    style.configure('TRadiobutton', background=BODY, foreground=TEXT, font=FB)
    style.map('TRadiobutton', background=[('active', BODY)])
    style.configure('TEntry', fieldbackground='white', bordercolor='#c9d8ea', font=FB)
    style.configure('TCombobox', fieldbackground='white', background='white',
                    bordercolor='#c9d8ea', font=FB)
    style.configure('Treeview', background='white', fieldbackground='white',
                    foreground=TEXT, rowheight=BASE_FONT_SIZE * 2 + 10, font=FB)
    style.configure('Treeview.Heading', background=NAVY, foreground='white', font=FBB)
    style.map('Treeview.Heading', background=[('active', NAVY_DARK)])
    style.map('Treeview', background=[('selected', '#2f6fb3')],
              foreground=[('selected', 'white')])

def navy_header(parent, subtitle='', version=''):
    """Crea un encabezado navy con título + versión en grande. Devuelve el frame."""
    import tkinter as tk
    h = tk.Frame(parent, bg=NAVY, height=60)
    h.pack(fill='x')
    h.pack_propagate(False)
    left = tk.Frame(h, bg=NAVY)
    left.pack(side='left', padx=14)
    tk.Label(left, text="FactuPOS Print", font=("Segoe UI", 14, "bold"),
             fg='white', bg=NAVY).pack(anchor='w', pady=(8, 0))
    if subtitle:
        tk.Label(left, text=subtitle, font=("Segoe UI", 9),
                 fg=HEADTXT, bg=NAVY).pack(anchor='w')
    if version:
        tk.Label(h, text="v" + version, font=("Segoe UI", 22, "bold"),
                 fg=HEADTXT, bg=NAVY).pack(side='right', padx=16)
    return h

def build_test_ticket(printer_name='', cols=32, font='A'):
    """Genera un tiquete de prueba ESC/POS (mini factura de test): muestra título grande,
    cliente en negrita, total grande y los tamaños de letra soportados.
    `cols` = ancho del papel en columnas; `font` = 'A' (normal) o 'B' (condensada).
    Termina abriendo el cajón monedero y cortando el papel."""
    import datetime
    W = int(cols) if cols else 32
    if W < 16:
        W = 16
    is_b = str(font).upper() == 'B'
    ESC = b'\x1b'; GS = b'\x1d'
    bold_on  = ESC + b'\x45\x01'
    bold_off = ESC + b'\x45\x00'
    al_c = ESC + b'\x61\x01'      # centrar
    al_l = ESC + b'\x61\x00'      # izquierda
    al_r = ESC + b'\x61\x02'      # derecha
    fontA = ESC + b'\x21\x00'     # Font A (normal)
    fontB = ESC + b'\x21\x01'     # Font B (condensada)
    base = fontB if is_b else fontA   # fuente base de todo el ticket
    def size(w, h):               # multiplicadores 1..2 (alto/ancho)
        return GS + b'\x21' + bytes([((w - 1) << 4) | (h - 1)])
    sz_n  = size(1, 1)            # normal
    sz_2h = size(1, 2)            # doble alto
    sz_2w = size(2, 1)            # doble ancho
    sz_2b = size(2, 2)            # doble alto + ancho
    def L(s=''):
        return (s + '\n').encode('cp437', errors='replace')
    sep = ('-' * W + '\n').encode('cp437')
    def row(cant, desc, total):
        # cant(4) + espacio + desc(relleno) + espacio + total(10 der), ajustado al ancho W
        tot = str(total).rjust(10)
        mid = max(1, W - 4 - 1 - 1 - 10)
        d = str(desc)[:mid].ljust(mid)
        return L('{:<4} {} {}'.format(str(cant)[:4], d, tot))
    try:
        ahora = datetime.datetime.now().strftime('%d/%m/%Y %H:%M')
    except Exception:
        ahora = ''

    out = bytearray()
    out += ESCPOS_INIT
    out += base                       # fuente base (A o B)
    # --- Cabecera: TÍTULO GRANDE ---
    out += al_c
    out += sz_2b + bold_on + L('FACTUPOS') + bold_off + sz_n + base
    out += L('TIQUETE DE PRUEBA')
    out += L('Fuente {}  ·  {} columnas'.format('B' if is_b else 'A', W))
    if printer_name:
        out += L(printer_name)
    out += al_l + sep
    # --- Datos del documento ---
    out += L('Fecha: ' + ahora)
    out += L('Factura: TEST-0001')
    out += bold_on + L('Cliente: CLIENTE DE PRUEBA') + bold_off   # CLIENTE EN NEGRITA
    out += L('Cedula:  000000000')
    out += sep
    # --- Detalle (ajustado al ancho) ---
    out += row('Cant', 'Descripcion', 'Total')
    out += sep
    out += row('1', 'Producto A', '1000.00')
    out += row('2', 'Producto B', '500.00')
    out += sep
    # --- Totales: TOTAL GRANDE ---
    out += al_r
    out += L('Subtotal: 1500.00')
    out += L('IVA 13%:   195.00')
    out += sz_2h + bold_on + L('TOTAL: 1695.00') + bold_off + sz_n   # TOTAL GRANDE
    out += al_l + sep
    # --- Muestra de tamaños de letra ---
    out += al_c + L('--- TAMANOS DE LETRA ---') + al_l
    out += fontA + L('Normal (Font A)')
    out += fontB + L('Condensada (Font B)') + fontA
    out += sz_2h + L('Doble alto') + sz_n
    out += sz_2w + L('Doble ancho') + sz_n
    out += sz_2b + L('Doble alto+ancho') + sz_n
    out += bold_on + L('Negrita') + bold_off + base
    out += sep
    out += al_c + L('*** SIN VALIDEZ FISCAL ***') + al_l
    # --- Cajón monedero + corte ---
    out += b'\n'
    out += ESCPOS_OPEN_DRAWER
    out += b'\n\n\n'
    out += ESCPOS_CUT_PAPER
    return bytes(out)


def ask_paper_width(parent, default_cols=48, default_font='A'):
    """Diálogo: elegir fuente (A/B) y columnas del papel para la prueba.
    Las Epson térmicas tienen Font A (normal) y Font B (condensada), con distinto
    nº de columnas. Devuelve (cols, font) o None si cancela."""
    import tkinter as tk
    from tkinter import ttk
    dlg = tk.Toplevel(parent)
    dlg.title("Prueba de impresora")
    dlg.transient(parent)
    dlg.resizable(False, False)
    dlg.configure(bg=BODY)
    result = {'val': None}

    # Fuente A/B
    ttk.Label(dlg, text="Fuente de la impresora:", padding=(12, 12, 12, 2)).pack(anchor='w')
    font_var = tk.StringVar(value=str(default_font).upper())
    frow = ttk.Frame(dlg, padding=(12, 0))
    frow.pack(anchor='w')

    cmb = None  # def. abajo, referenciado por on_font

    def on_font(*_):
        # Sugerir columnas típicas según fuente (el usuario puede cambiarlas)
        if cmb is not None and not cmb.get().strip().isdigit():
            return
        if font_var.get() == 'A':
            cmb.set('48')
        else:
            cmb.set('64')

    ttk.Radiobutton(frow, text="A (normal)", value='A',
                    variable=font_var, command=on_font).pack(side='left', padx=(0, 10))
    ttk.Radiobutton(frow, text="B (condensada)", value='B',
                    variable=font_var, command=on_font).pack(side='left')

    # Columnas
    ttk.Label(dlg, text="Columnas (ancho de papel):", padding=(12, 10, 12, 2)).pack(anchor='w')
    crow = ttk.Frame(dlg, padding=(12, 0))
    crow.pack(anchor='w')
    cmb = ttk.Combobox(crow, width=8, values=['32', '40', '42', '48', '56', '64'])
    cmb.set(str(default_cols))
    cmb.pack(side='left')
    ttk.Label(crow, text="  58mm: A=32 B=42   ·   80mm: A=48 B=64").pack(side='left')

    def aceptar(*_):
        try:
            c = int(str(cmb.get()).strip())
        except (ValueError, TypeError):
            c = None
        if c and c >= 16:
            result['val'] = (c, font_var.get())
            dlg.destroy()
    btns = ttk.Frame(dlg, padding=12)
    btns.pack(fill='x')
    ttk.Button(btns, text="Imprimir prueba", command=aceptar).pack(side='right', padx=(5, 0))
    ttk.Button(btns, text="Cancelar", command=dlg.destroy).pack(side='right')
    cmb.bind('<Return>', aceptar)

    try:
        dlg.update_idletasks()
        dlg.grab_set()
        cmb.focus_set()
    except Exception:
        pass
    dlg.wait_window()
    return result['val']

# ESC/P Commands para dot matrix (FX-890, LX-300, etc.)
ESCP_INIT         = b'\x1b\x40'              # ESC @ = inicializar
ESCP_DRAFT        = b'\x1b\x78\x00'          # ESC x 0 = Draft
ESCP_NLQ          = b'\x1b\x78\x01'          # ESC x 1 = NLQ (Roman/Sans Serif)
ESCP_10CPI        = b'\x1b\x50'              # ESC P = 10 CPI (80 cols)
ESCP_12CPI        = b'\x1b\x4d'              # ESC M = 12 CPI (96 cols)
ESCP_15CPI        = b'\x1b\x67'              # ESC g = 15 CPI (120 cols)
ESCP_CONDENSED_ON = b'\x0f'                  # SI = condensed on (17/20 CPI)
ESCP_CONDENSED_OFF = b'\x12'                 # DC2 = condensed off
ESCP_BOLD_ON      = b'\x1b\x45'              # ESC E = bold on
ESCP_BOLD_OFF     = b'\x1b\x46'              # ESC F = bold off
ESCP_FORM_FEED    = b'\x0c'                  # FF = form feed / expulsar página

# Mapeo fuente spooler → comandos ESC/P para dot matrix
ESCP_FONT_MAP = {
    'draft 10cpi':  ESCP_DRAFT + ESCP_10CPI,
    'draft 12cpi':  ESCP_DRAFT + ESCP_12CPI,
    'draft 15cpi':  ESCP_DRAFT + ESCP_15CPI,
    'draft 17cpi':  ESCP_DRAFT + ESCP_10CPI + ESCP_CONDENSED_ON,
    'draft 20cpi':  ESCP_DRAFT + ESCP_12CPI + ESCP_CONDENSED_ON,
    'roman 10cpi':  ESCP_NLQ + ESCP_10CPI,
    'roman 12cpi':  ESCP_NLQ + ESCP_12CPI,
    'roman 15cpi':  ESCP_NLQ + ESCP_15CPI,
    'roman 17cpi':  ESCP_NLQ + ESCP_10CPI + ESCP_CONDENSED_ON,
    'roman 20cpi':  ESCP_NLQ + ESCP_12CPI + ESCP_CONDENSED_ON,
    'draft 16cpi':  ESCP_DRAFT + ESCP_10CPI + ESCP_CONDENSED_ON,
    'roman 16cpi':  ESCP_NLQ + ESCP_10CPI + ESCP_CONDENSED_ON,
}

def is_plain_text(data_bytes):
    """Detecta si los datos son texto plano (sin ESC/POS ni VB6)."""
    # Si tiene bytes de control ESC (0x1B) o GS (0x1D), es ESC/POS
    if b'\x1b' in data_bytes or b'\x1d' in data_bytes:
        return False
    # Si tiene separadores VB6
    if is_vb6_protocol(data_bytes):
        return False
    return True

def _get_escp_normal(printer_config):
    """Obtiene el comando ESC/P normal según config de impresora."""
    font = printer_config.get('spoolerFont', 'Draft 12cpi').lower().strip()
    font_size = printer_config.get('spoolerFontSize', 10)
    if isinstance(font_size, str):
        try: font_size = float(font_size)
        except: font_size = 10

    if font in ('lucida console', 'courier new', 'consolas', 'terminal', 'monospace'):
        if font_size <= 7:
            return ESCP_DRAFT + ESCP_12CPI + ESCP_CONDENSED_ON
        elif font_size <= 8:
            return ESCP_DRAFT + ESCP_15CPI
        elif font_size <= 10:
            return ESCP_DRAFT + ESCP_12CPI
        else:
            return ESCP_DRAFT + ESCP_10CPI
    return ESCP_FONT_MAP.get(font, ESCP_DRAFT + ESCP_12CPI)

def plain_to_escp(data_bytes, printer_config):
    """Envuelve texto plano con comandos ESC/P para dot matrix.
    Soporta marcadores: {{G}}=Grande(10cpi), {{N}}=Normal, {{B}}=Bold, {{C}}=Centrar."""
    escp_normal = _get_escp_normal(printer_config)
    escp_grande = ESCP_NLQ + ESCP_10CPI  # Grande = NLQ 10 CPI

    text = data_bytes.decode('latin-1', errors='replace')

    result = bytearray()
    result.extend(ESCP_INIT)
    result.extend(escp_normal)

    bold_on = False
    for line in text.split('\n'):
        # Procesar marcadores en la línea
        has_grande = '{{G}}' in line
        has_center = '{{C}}' in line
        has_bold = '{{B}}' in line
        has_right = '{{D}}' in line

        # Limpiar marcadores del texto
        clean = line.replace('{{G}}', '').replace('{{N}}', '').replace('{{B}}', '').replace('{{C}}', '').replace('{{D}}', '')

        # Aplicar Grande
        if has_grande:
            result.extend(escp_grande)

        # Aplicar Bold
        if has_bold:
            result.extend(ESCP_BOLD_ON)

        result.extend(clean.encode('cp437', errors='replace'))
        result.extend(b'\r\n')

        # Restaurar después de Grande
        if has_grande:
            result.extend(escp_normal)

        # Restaurar Bold
        if has_bold:
            result.extend(ESCP_BOLD_OFF)

    result.extend(ESCP_FORM_FEED)
    return bytes(result)

# Protocolo VB6 separadores
VB6_DF = '\xDF'   # Separador de campo
VB6_DD = '\xDD'   # Fin de línea
VB6_E3 = '\xE3'   # Sub-separador (dentro de código 3)

# Mapeo fuente VB6 → ESC/POS
# Formato código 3: "NombreFuente CPI[E3]Tamaño[E3]Modo"
ESCPOS_FONT_MAP = {
    # Draft = Font A/B normal
    'draft 5cpi':  b'\x1b\x21\x19',   # Font B + bold + doble alto (grande)
    'draft 10cpi': b'\x1b\x21\x01',   # Font B normal
    'draft 12cpi': b'\x1b\x21\x01',   # Font B normal (condensado)
    # Roman = Font A (más legible)
    'roman 6cpi':  b'\x1b\x21\x18',   # Font A + bold + doble alto
    'roman 10cpi': b'\x1b\x21\x00',   # Font A normal
    'roman 12cpi': b'\x1b\x21\x00',   # Font A normal
}

# ---------------------------------------------------------------------------
# Protocolo VB6 Parser
# ---------------------------------------------------------------------------
def parse_vb6_protocol(data_text):
    """
    Parsea texto con protocolo VB6 embebido.
    Retorna lista de tuplas: (codigo, texto, fuente_info)

    Códigos:
      1  = texto alineado izquierda
      3  = cambio de fuente (fuente[E3]tamaño[E3]modo)
      4  = reset
      9  = fin de reporte / corte
      13 = texto alineado derecha
      14 = texto centrado
    """
    lines = data_text.split(VB6_DD)
    parsed = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split(VB6_DF)
        if len(parts) < 2:
            continue
        code = parts[0].strip()
        text = parts[1] if len(parts) > 1 else ''
        parsed.append((code, text))
    return parsed

def is_vb6_protocol(data_bytes):
    """Detecta si los datos usan protocolo VB6 (contienen separadores DF/DD)."""
    try:
        text = data_bytes.decode('latin-1')
        return VB6_DF in text and VB6_DD in text
    except:
        return False

def vb6_to_escpos(data_bytes, printer_config):
    """
    Convierte protocolo VB6 a bytes ESC/POS para modo RAW.
    """
    text = data_bytes.decode('latin-1')
    parsed = parse_vb6_protocol(text)
    result = bytearray()
    result.extend(ESCPOS_INIT)
    result.extend(b'\x1b\x33\x12')  # Interlineado 18 dots

    ESC_CENTRO    = b'\x1b\x61\x01'
    ESC_IZQUIERDA = b'\x1b\x61\x00'
    ESC_DERECHA   = b'\x1b\x61\x02'
    FONT_NORMAL   = b'\x1b\x21\x01'  # Font B normal

    for code, text in parsed:
        if code == '3':
            # Cambio de fuente: "Draft 10cpi[E3]10[E3]1"
            font_parts = text.split(VB6_E3)
            font_name = font_parts[0].strip().lower() if font_parts else ''
            esc_cmd = ESCPOS_FONT_MAP.get(font_name, FONT_NORMAL)
            result.extend(esc_cmd)

        elif code == '4':
            # Reset
            result.extend(FONT_NORMAL)
            result.extend(ESC_IZQUIERDA)

        elif code == '1':
            # Texto alineado izquierda
            result.extend(ESC_IZQUIERDA)
            result.extend(text.encode('latin-1', errors='replace'))
            result.extend(b'\n')

        elif code == '13':
            # Texto alineado derecha
            result.extend(ESC_DERECHA)
            result.extend(text.encode('latin-1', errors='replace'))
            result.extend(b'\n')
            result.extend(ESC_IZQUIERDA)  # Reset alineación

        elif code == '14':
            # Texto centrado
            result.extend(ESC_CENTRO)
            result.extend(text.encode('latin-1', errors='replace'))
            result.extend(b'\n')
            result.extend(ESC_IZQUIERDA)  # Reset alineación

        elif code == '9':
            # Fin de reporte
            result.extend(b'\n\n\n')
            if printer_config.get('cutPaper', False):
                result.extend(ESCPOS_CUT_PAPER)

    return bytes(result)

def vb6_to_plain(data_bytes, ancho=93):
    """
    Convierte protocolo VB6 a texto plano para modo spooler.
    Centra/alinea usando espacios. Ignora códigos de fuente.
    """
    text = data_bytes.decode('latin-1')
    parsed = parse_vb6_protocol(text)
    lines = []

    for code, text in parsed:
        if code == '3' or code == '4':
            # Fuente/reset: ignorar en spooler (la fuente la maneja el SO)
            continue

        elif code == '1':
            lines.append(text)

        elif code == '13':
            # Alinear derecha con espacios
            lines.append(text.rjust(ancho))

        elif code == '14':
            # Centrar con espacios
            lines.append(text.center(ancho))

        elif code == '9':
            # Fin de reporte: form feed
            lines.append('\f')

    return '\n'.join(lines)

# ---------------------------------------------------------------------------
# Printer functions
# ---------------------------------------------------------------------------
def list_printers():
    if IS_LINUX:
        return _list_printers_linux()
    if HAS_WIN32:
        return _list_printers_win32()
    return ["SIMULADOR-POS-1 (mock)", "SIMULADOR-POS-2 (mock)"], "SIMULADOR-POS-1 (mock)"

def _list_printers_win32():
    impresoras = []
    default = win32print.GetDefaultPrinter()
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    for printer in win32print.EnumPrinters(flags, None, 2):
        impresoras.append(printer['pPrinterName'])
    return impresoras, default

def _list_printers_linux():
    """Listar impresoras CUPS en Linux."""
    impresoras = []
    default = ''
    try:
        result = subprocess.run(['lpstat', '-a'], capture_output=True, text=True, timeout=5)
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                name = line.split()[0]
                impresoras.append(name)
    except Exception as e:
        log.warning(f"No se pudo listar impresoras CUPS: {e}")
    # Obtener default
    try:
        result = subprocess.run(['lpstat', '-d'], capture_output=True, text=True, timeout=5)
        # "system default destination: PrinterName"
        if ':' in result.stdout:
            default = result.stdout.split(':')[-1].strip()
    except:
        pass
    if not impresoras:
        impresoras = ['(sin impresoras CUPS)']
    return impresoras, default

# ---------------------------------------------------------------------------
# #760 — Envio EN TROZOS CON PAUSA (Francisco Aguero, ferrebribri)
#
# Una matricial Epson tiene un buffer de entrada chico. Si se le entrega un
# documento largo de un solo golpe, imprime hasta donde le alcanzo el buffer y
# el resto SE PIERDE. Lo peor del sintoma es que **no da error**: el trabajo
# sale como "impreso" y el papel simplemente termina a mitad — en el reporte
# original, con las 19 lineas de la proforma completas y sin los totales.
#
# La receta de siempre para esas impresoras: mandar un pedazo, esperar a que lo
# saque, mandar el siguiente. Ya estaba implementada, pero SOLO para las
# termicas (`print_raw_thermal`); las matriciales seguian yendo de un tiro.
#
# 🔑 Que valores tocar si una impresora sigue cortando: bajar `chunk_size` o
#    subir `delay` en el perfil de esa impresora (`chunkSize` / `chunkDelay`).
#    No hay un valor bueno para todas: depende del buffer y de la velocidad.
# ---------------------------------------------------------------------------
CHUNK_TAMANO = 256      # bytes por envio
CHUNK_PAUSA  = 0.05     # segundos entre envios


def _escribir_en_trozos(escribir, data_bytes, chunk_size, delay, vaciar=None):
    """Entregar `data_bytes` de a pedazos, con una pausa entre uno y otro.

    `escribir` es la funcion de salida (f.write, WritePrinter, sock.sendall…) y
    `vaciar` el flush opcional: sin el, el buffer de Python junta los trozos y
    la pausa no sirve de nada — se termina mandando todo junto igual.
    """
    try:
        chunk_size = max(32, int(chunk_size or CHUNK_TAMANO))
    except (TypeError, ValueError):
        chunk_size = CHUNK_TAMANO
    try:
        delay = max(0.0, float(delay if delay is not None else CHUNK_PAUSA))
    except (TypeError, ValueError):
        delay = CHUNK_PAUSA

    total = len(data_bytes)
    offset = 0
    while offset < total:
        escribir(data_bytes[offset:offset + chunk_size])
        if vaciar:
            vaciar()
        offset += chunk_size
        if offset < total and delay:
            time.sleep(delay)


def print_raw(printer_name, data_bytes, chunk_size=CHUNK_TAMANO, delay=CHUNK_PAUSA):
    """Enviar bytes RAW directo a la impresora (modo POS).

    #760 — En Windows va en trozos con pausa, igual que el camino termico. En
    Linux sale por `lp` (CUPS), que hace su propio control de flujo contra el
    puerto, asi que ahi no hace falta trocear nada.
    """
    if IS_LINUX:
        return _print_raw_linux(printer_name, data_bytes)
    if not HAS_WIN32:
        log.info(f"[MOCK] RAW {len(data_bytes)} bytes → '{printer_name}' (trozos {chunk_size})")
        return True, f"Simulado OK en {printer_name}"
    try:
        hPrinter = win32print.OpenPrinter(printer_name)
        try:
            win32print.StartDocPrinter(hPrinter, 1, ("FactuPOS", None, "RAW"))
            try:
                win32print.StartPagePrinter(hPrinter)
                _escribir_en_trozos(lambda t: win32print.WritePrinter(hPrinter, t),
                                    data_bytes, chunk_size, delay)
                win32print.EndPagePrinter(hPrinter)
            finally:
                win32print.EndDocPrinter(hPrinter)
        finally:
            win32print.ClosePrinter(hPrinter)
        return True, f"Impreso en {printer_name}"
    except Exception as e:
        return False, f"Error: {e}"

def _print_raw_linux(printer_name, data_bytes):
    """Enviar bytes RAW a impresora CUPS en Linux."""
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.bin') as tmp:
            tmp.write(data_bytes)
            tmp_path = tmp.name
        result = subprocess.run(
            ['lp', '-d', printer_name, '-o', 'raw', tmp_path],
            capture_output=True, text=True, timeout=15
        )
        os.unlink(tmp_path)
        subprocess.run(['cupsenable', printer_name], capture_output=True, timeout=5)
        if result.returncode == 0:
            return True, f"Impreso en {printer_name} (raw/cups)"
        return False, f"Error lp: {result.stderr.strip()}"
    except Exception as e:
        return False, f"Error: {e}"

def _find_chrome():
    """Busca el ejecutable de Chrome/Chromium en el sistema."""
    if IS_WINDOWS:
        paths = [
            os.path.expandvars(r'%ProgramFiles%\Google\Chrome\Application\chrome.exe'),
            os.path.expandvars(r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe'),
            os.path.expandvars(r'%LocalAppData%\Google\Chrome\Application\chrome.exe'),
            # Edge como fallback
            os.path.expandvars(r'%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe'),
            os.path.expandvars(r'%ProgramFiles%\Microsoft\Edge\Application\msedge.exe'),
        ]
    else:
        paths = [
            '/usr/bin/google-chrome',
            '/usr/bin/google-chrome-stable',
            '/usr/bin/chromium-browser',
            '/usr/bin/chromium',
            '/snap/bin/chromium',
        ]
    for p in paths:
        if os.path.isfile(p):
            return p
    # Buscar en PATH
    import shutil
    for name in ['google-chrome', 'chromium-browser', 'chromium', 'chrome']:
        found = shutil.which(name)
        if found:
            return found
    return None

def _print_url_silent(url, printer_name=''):
    """Imprime URL silenciosamente via Chrome headless + kiosk-printing."""
    chrome = _find_chrome()
    if not chrome:
        import webbrowser
        webbrowser.open(url)
        return True, "Chrome no encontrado, abierto en navegador default"

    browser_name = os.path.basename(chrome)

    # Chrome/Edge con --headless=new --kiosk-printing imprime directo sin ventana
    cmd = [
        chrome,
        '--headless=new',
        '--disable-gpu',
        '--no-sandbox',
        '--no-first-run',
        '--disable-extensions',
        '--kiosk-printing',
        url
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        return True, f"Impreso silencioso via {browser_name}"
    except subprocess.TimeoutExpired:
        # Si timeout, puede que haya impreso igual pero Chrome no cerró
        return True, f"Impreso via {browser_name} (timeout, puede haber impreso)"
    except Exception as e:
        # Fallback: abrir con kiosk-printing visible
        try:
            cmd_fallback = [chrome, '--kiosk-printing', url]
            subprocess.Popen(cmd_fallback, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, f"Impreso via {browser_name} (fallback kiosk)"
        except Exception as e2:
            return False, f"Error: {e2}"


def _monto_en_letras(monto, moneda='CRC'):
    """Convierte monto a texto en español."""
    entero = int(abs(monto))
    decimales = int(round((abs(monto) - entero) * 100))
    moneda_nombre = 'DOLARES' if moneda == 'USD' else 'COLONES'
    unidades = ['','UN','DOS','TRES','CUATRO','CINCO','SEIS','SIETE','OCHO','NUEVE']
    decenas = ['','DIEZ','VEINTE','TREINTA','CUARENTA','CINCUENTA','SESENTA','SETENTA','OCHENTA','NOVENTA']
    especiales = {11:'ONCE',12:'DOCE',13:'TRECE',14:'CATORCE',15:'QUINCE',16:'DIECISEIS',17:'DIECISIETE',18:'DIECIOCHO',19:'DIECINUEVE'}
    centenas = ['','CIENTO','DOSCIENTOS','TRESCIENTOS','CUATROCIENTOS','QUINIENTOS','SEISCIENTOS','SETECIENTOS','OCHOCIENTOS','NOVECIENTOS']
    def conv(n):
        if n == 0: return 'CERO'
        if n == 100: return 'CIEN'
        if n < 10: return unidades[n]
        if 11 <= n <= 19: return especiales[n]
        if n == 10: return 'DIEZ'
        if 21 <= n <= 29: return 'VEINTI' + unidades[n-20]
        if n < 100:
            d, u = divmod(n, 10)
            return decenas[d] + (' Y ' + unidades[u] if u else '')
        if n < 1000:
            c, r = divmod(n, 100)
            return centenas[c] + (' ' + conv(r) if r else '')
        if n < 1000000:
            m, r = divmod(n, 1000)
            p = 'MIL' if m == 1 else conv(m) + ' MIL'
            return p + (' ' + conv(r) if r else '')
        if n < 1000000000:
            m, r = divmod(n, 1000000)
            p = 'UN MILLON' if m == 1 else conv(m) + ' MILLONES'
            return p + (' ' + conv(r) if r else '')
        return f"{n:,}"
    return conv(entero) + f' CON {decimales:02d}/100 ' + moneda_nombre


def _print_json_datareport(json_data, printer_name=''):
    """Genera PDF desde JSON e imprime. Maneja copias (ORIGINAL + N copias)."""
    if not HAS_REPORTLAB:
        return False, "reportlab no instalado"

    # Nuevo (server-driven): el servidor (PHP) decide la etiqueta ORIGINAL/COPIA
    # y manda UN trabajo por hoja a la cola. La app solo imprime lo que le llega.
    if 'copia_etiqueta' in json_data:
        etiqueta = json_data.get('copia_etiqueta', '')  # '' = sin etiqueta
        return _print_json_datareport_single(json_data, printer_name, etiqueta)

    # Compatibilidad (web vieja): manda 'copias=N' y la app rotula/itera.
    copias = max(1, int(json_data.get('copias', 1)))
    total_impresiones = copias  # copias = total hojas (1=solo original, 2=original+copia)
    resultados = []
    for i in range(total_impresiones):
        etiqueta = 'ORIGINAL' if i == 0 else 'COPIA'
        ok, msg = _print_json_datareport_single(json_data, printer_name, etiqueta)
        resultados.append((ok, msg))
        if not ok:
            return False, msg
    return True, f"DataReport impreso ({total_impresiones}x, {len(json_data.get('lineas', []))} líneas)"


def _print_json_datareport_single(json_data, printer_name='', copia_etiqueta='ORIGINAL'):
    """Genera un PDF e imprime una copia."""
    if not HAS_REPORTLAB:
        return False, "reportlab no instalado"

    import tempfile
    import urllib.request
    from reportlab.platypus import HRFlowable, KeepTogether
    from reportlab.pdfgen import canvas as _rl_canvas

    # Lienzo con numeración "Página X de Y" al pie de cada hoja (caso #46/#72/#73)
    class NumberedCanvas(_rl_canvas.Canvas):
        def __init__(self, *a, **kw):
            _rl_canvas.Canvas.__init__(self, *a, **kw)
            self._saved_page_states = []
        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()
        def save(self):
            n = len(self._saved_page_states)
            for st in self._saved_page_states:
                self.__dict__.update(st)
                self.setFont("Helvetica", 7)
                self.setFillColor(colors.HexColor('#666'))
                self.drawRightString(letter[0] - 12*mm, 6*mm,
                                     f"Página {self._pageNumber} de {n}")
                _rl_canvas.Canvas.showPage(self)
            _rl_canvas.Canvas.save(self)

    d = json_data
    emisor = d.get('emisor', {})
    documento = d.get('documento', {})
    cliente = d.get('cliente', {})
    vendedor = d.get('vendedor', {})
    agente = d.get('agente', {})
    referido = d.get('referido', {})
    lineas_data = d.get('lineas', [])
    totales = d.get('totales', {})
    pagos = d.get('pagos', [])
    mensajes = d.get('mensajes', {})
    tipo_doc = d.get('tipo_documento', 'factura')
    tipo_doc_nombre = d.get('tipo_doc_nombre', 'DOCUMENTO')
    moneda = documento.get('moneda', 'CRC')
    fmt = lambda n: f"{n:,.2f}"

    pdf_path = os.path.join(tempfile.gettempdir(), f'factupos_dr_{int(time.time())}.pdf')

    try:
        doc = SimpleDocTemplate(pdf_path, pagesize=letter,
                                leftMargin=12*mm, rightMargin=12*mm,
                                topMargin=15*mm, bottomMargin=10*mm)
        pw = doc.width  # ancho disponible

        styles = getSampleStyleSheet()
        s = lambda name, **kw: styles.add(ParagraphStyle(name=name, **kw))
        s('H1', fontSize=15, fontName='Helvetica-Bold', spaceAfter=4)
        s('H2', fontSize=9, fontName='Helvetica', spaceAfter=1)
        s('H3', fontSize=8, fontName='Helvetica', textColor=colors.HexColor('#444'), spaceAfter=0)
        s('DocTitulo', fontSize=12, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceBefore=4, spaceAfter=4,
          textColor=colors.black)
        s('N8', fontSize=8, fontName='Helvetica', spaceAfter=1, leading=10)
        s('N8B', fontSize=8, fontName='Helvetica-Bold', spaceAfter=1, leading=10)
        s('N7', fontSize=7, fontName='Helvetica', spaceAfter=0, leading=9)
        s('T8', fontSize=9, fontName='Helvetica', spaceAfter=0, spaceBefore=0, leading=11)
        s('T8R', fontSize=9, fontName='Helvetica', spaceAfter=0, spaceBefore=0, leading=11, alignment=TA_RIGHT)
        s('T7', fontSize=8, fontName='Helvetica', spaceAfter=0, spaceBefore=0, leading=10, textColor=colors.black)
        s('Label', fontSize=7, fontName='Helvetica-Bold', textColor=colors.HexColor('#666'), spaceAfter=0)
        s('CliNombre', fontSize=11, fontName='Helvetica-Bold', spaceAfter=2)
        s('TotalGrande', fontSize=14, fontName='Helvetica-Bold', alignment=TA_RIGHT, spaceBefore=3)
        s('DetalleGrande', fontSize=12, fontName='Helvetica-Bold', spaceAfter=2, leading=14)
        s('Pie', fontSize=7, fontName='Helvetica', alignment=TA_CENTER, spaceAfter=1)
        s('PieBold', fontSize=8, fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=1)

        el = []  # elements

        # ── HEADER: Emisor izq | Logo der ──
        nombre_emp = emisor.get('nombre_comercial', '') or emisor.get('razon_social', 'EMPRESA')
        razon = emisor.get('razon_social', '')

        emisor_parts = [Paragraph(f"<b>{nombre_emp}</b>", styles['H1'])]
        if razon and razon.upper() != nombre_emp.upper():
            emisor_parts.append(Paragraph(razon, styles['H2']))
        info = []
        if emisor.get('cedula'): info.append(f"Céd: {emisor['cedula']}")
        if emisor.get('telefono'): info.append(f"Tel: {emisor['telefono']}")
        if emisor.get('email'): info.append(emisor['email'])
        if info:
            emisor_parts.append(Paragraph(' · '.join(info), styles['H3']))
        if emisor.get('direccion'):
            emisor_parts.append(Paragraph(emisor['direccion'], styles['H3']))
        for enc in mensajes.get('encabezado', []):
            if enc.strip():
                emisor_parts.append(Paragraph(enc.strip(), styles['H3']))

        # Logo
        logo_cell = ''
        logo_url = emisor.get('logo_url', '')
        if logo_url:
            try:
                logo_tmp = os.path.join(tempfile.gettempdir(), 'factupos_logo_tmp.png')
                urllib.request.urlretrieve(logo_url, logo_tmp)
                logo_cell = RLImage(logo_tmp, width=45*mm, height=18*mm, kind='proportional')
            except:
                pass

        header_data = [[emisor_parts, logo_cell if logo_cell else '']]
        header_table = Table(header_data, colWidths=[pw - 55*mm, 55*mm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ]))
        el.append(header_table)

        # ── BARRA TIPO DOCUMENTO ──
        clave = documento.get('clave', '')
        doc_titulo = f"{tipo_doc_nombre} &nbsp;&nbsp; {documento.get('numero', '')} &nbsp;&nbsp; {documento.get('fecha', '')}"
        barra_data = [[Paragraph(doc_titulo, styles['DocTitulo'])]]
        barra = Table(barra_data, colWidths=[pw])
        barra.setStyle(TableStyle([
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LINEABOVE', (0, 0), (-1, 0), 1, colors.black),
            ('LINEBELOW', (0, 0), (-1, 0), 1, colors.black),
        ]))
        el.append(Spacer(1, 2*mm))
        el.append(barra)
        if clave:
            el.append(Paragraph(f"Clave: {clave}", styles['N7']))
        el.append(Spacer(1, 2*mm))

        # ── 2 FICHAS: Receptor | Documento ──
        def ficha_label_valor(label, valor):
            return f"<b>{label}</b> {valor}"

        # Ficha Receptor
        receptor_lines = []
        nom_cli = cliente.get('nombre_comercial') or cliente.get('nombre', 'CLIENTE')
        receptor_lines.append(Paragraph(f"<font size='10'><b>{nom_cli}</b></font>", styles['N8']))
        if not cliente.get('es_generico', True):
            razon_cli = cliente.get('nombre_juridico') or cliente.get('nombre', '')
            # Siempre mostrar "codigo - nombre_juridico" debajo del comercial
            if razon_cli:
                receptor_lines.append(Paragraph(f"{cliente.get('codigo', '')} - {razon_cli}", styles['N7']))
            elif cliente.get('codigo'):
                receptor_lines.append(Paragraph(f"Código: {cliente.get('codigo', '')}", styles['N7']))
            ced_line = []
            if cliente.get('cedula'): ced_line.append(f"Céd: {cliente['cedula']}")
            if cliente.get('actividad'): ced_line.append(f"Act: {cliente['actividad']}")
            if cliente.get('estado'): ced_line.append(f"<b>{cliente['estado']}</b>")
            if ced_line:
                receptor_lines.append(Paragraph(ficha_label_valor('Cédula:', ' · '.join(ced_line)), styles['N7']))
            if cliente.get('telefono'):
                receptor_lines.append(Paragraph(ficha_label_valor('Tel:', cliente['telefono']), styles['N7']))
            if cliente.get('email'):
                receptor_lines.append(Paragraph(ficha_label_valor('Email:', cliente['email']), styles['N7']))
            if cliente.get('direccion'):
                receptor_lines.append(Paragraph(ficha_label_valor('Dirección:', cliente['direccion']), styles['N7']))
            if cliente.get('dia_cobro'):
                receptor_lines.append(Paragraph(ficha_label_valor('Día Cobro:', cliente['dia_cobro']), styles['N7']))

        # Ficha Documento
        doc_lines = []
        cond = documento.get('condicion', 'CONTADO')
        cond_line = cond
        if documento.get('plazo_credito', 0) > 0:
            cond_line += f" — Plazo: {documento['plazo_credito']} días"
        cond_line += f" · Vence: {documento.get('fecha_vence', '')}"
        doc_lines.append(Paragraph(ficha_label_valor('Condición:', cond_line), styles['N7']))
        ofi = []
        if documento.get('oficina'): ofi.append(f"<b>Oficina:</b> {documento['oficina']}")
        if documento.get('caja'): ofi.append(f"<b>Caja:</b> {documento['caja']}")
        if documento.get('referencia'): ofi.append(f"<b>Ref:</b> {documento['referencia']}")
        if ofi:
            doc_lines.append(Paragraph(' · '.join(ofi), styles['N7']))
        oc_ped = []
        if documento.get('orden_compra'): oc_ped.append(f"<b>OC:</b> {documento['orden_compra']}")
        if documento.get('pedido_por'): oc_ped.append(f"<b>Pedido:</b> {documento['pedido_por']}")
        if oc_ped:
            doc_lines.append(Paragraph(' · '.join(oc_ped), styles['N7']))
        if referido.get('nombre'):
            doc_lines.append(Paragraph(ficha_label_valor('Referido:', referido['nombre']), styles['N7']))
        if agente.get('nombre'):
            doc_lines.append(Paragraph(ficha_label_valor('Agente:', f"{agente['nombre']} ({agente['codigo']})"), styles['N7']))
        if vendedor.get('nombre'):
            doc_lines.append(Paragraph(ficha_label_valor('Usuario:', f"{vendedor['nombre']} ({vendedor['codigo']})"), styles['N7']))
        fichas_data = [[receptor_lines, doc_lines]]
        fichas = Table(fichas_data, colWidths=[pw * 0.55, pw * 0.45])
        fichas.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOX', (0, 0), (0, 0), 0.5, colors.HexColor('#ddd')),
            ('BOX', (1, 0), (1, 0), 0.5, colors.HexColor('#ddd')),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        el.append(fichas)

        # ── TABLA ARTÍCULOS ──
        el.append(Spacer(1, 3*mm))
        mostrar_cabys = d.get('mostrar_cabys', True)
        linea_division = d.get('linea_division', False)  # param 21
        param_36 = d.get('param_36', False)  # imprime bodega
        param_344 = d.get('param_344', False)  # ocultar descuento
        span_desc_rows = []  # (legacy layout) no usado en factura con nuevo layout 6 col
        span_cabys_rows = []
        span_fila2_rows = []  # fila 2 concatenada: SPAN de col 0 a col -1
        sep_rows = []  # fin-de-artículo: línea gris sutil (param 21)
        if tipo_doc == 'proforma':
            tabla_data = [['Cant', 'Código', 'Descripción', 'Precio/U', 'SubTotal', 'IVA', 'Total']]
        else:
            # Layout igual a ver_factura_desktop.php: 6 columnas
            tabla_data = [['Cant', 'Descripción', 'Precio/Ud', 'SubTotal', 'IVA', 'Total']]

        for l in lineas_data:
            nombre = l.get('nombre', '')
            serie = l.get('serie', '')
            param343 = d.get('param_343', False)
            param391 = d.get('param_391', False)
            # Si param 343 activo, nombre ya viene como serie (desde PHP)
            # Si no, y hay serie:
            #   param 391=0: todo en una línea "Nombre — DETALLE1 DETALLE2"
            #   param 391=1: nombre en fila 1, cada detalle en fila separada
            if not param343 and serie:
                serie_clean = serie.replace('\r\n', '\n').replace('\r', '\n').strip()
                if param391:
                    # Fila separada: nombre solo, serie se agrega después como filas
                    pass  # serie se maneja después
                else:
                    # Misma fila: reemplazar enters por espacios
                    serie_inline = serie_clean.replace('\n', ' ')
                    nombre = nombre + ' — ' + serie_inline
            cant = l.get('cantidad', 0)
            cant_str = str(int(cant)) if cant == int(cant) else f"{cant:.2f}"
            desc_pct = l.get('desc_pct', 0)
            desc_str = f"{desc_pct:.0f}%" if desc_pct > 0 else ''
            iva_pct = l.get('iva_pct', 0)
            iva_str = f"{iva_pct:.0f}%" if iva_pct > 0 else '0%'
            subtotal_linea = l.get('gravado', 0) + l.get('exento', 0) + l.get('exonerado', 0)
            if subtotal_linea == 0:
                subtotal_linea = l.get('precio', 0) * l.get('cantidad', 0) - l.get('desc_monto', 0)

            if tipo_doc == 'proforma':
                nombre_mostrar = nombre
                if desc_pct > 0:
                    nombre_mostrar += f" (-{desc_pct:.0f}%)"
                nombre_html = nombre_mostrar.replace('&', '&amp;')
                tabla_data.append([
                    cant_str,
                    l.get('codigo', ''),
                    Paragraph(nombre_html, styles['T8']),
                    fmt(l.get('precio', 0)),
                    fmt(subtotal_linea),
                    fmt(l.get('iva_monto', 0)),
                    fmt(l.get('total', 0)),
                ])
                # Filas de detalle separadas (param 391=1)
                if param391 and serie and not param343:
                    serie_clean = serie.replace('\r\n', '\n').replace('\r', '\n').strip()
                    for det_line in serie_clean.split('\n'):
                        if det_line.strip():
                            tabla_data.append(['', '', Paragraph(f"<b>{det_line.strip()}</b>", styles['T8']), '', '', '', ''])
            else:
                # Layout igual a ver_factura_desktop.php: 6 columnas, 2 filas por artículo
                nombre_html = nombre.replace('\n', '<br/>').replace('&', '&amp;')
                bodega = str(l.get('bodega', '') or '').strip()
                bod_prefix = ''
                if param_36 and bodega and bodega != '0':
                    bod_prefix = f"<font color='#2563eb'><b>(B{bodega})</b></font> "
                codigo = l.get('codigo', '')
                cabys = l.get('cabys', '')
                unidad = l.get('unidad', '') or 'Unid'
                desc_monto = l.get('desc_monto', 0)
                grav = l.get('gravado', 0)
                exo = l.get('exonerado', 0)
                ext = l.get('exento', 0)
                # Fila 1: Cant | Descripción(B0) | Precio/Ud | SubTotal((Dc%)) | IVA((IVA%)) | Total
                nombre_celda = f"<b>{bod_prefix}{nombre_html}</b>"
                desc_badge = ''
                if not param_344 and desc_pct > 0:
                    desc_badge = f"<font size='6' color='#666666'>({desc_pct:.0f}%)</font> "
                subtotal_cell = Paragraph(f"{desc_badge}{fmt(subtotal_linea)}", styles['T8R'] if 'T8R' in styles else styles['T8'])
                iva_badge = f"<font size='6' color='#666666'>({iva_pct:.0f}%)</font> "
                iva_cell = Paragraph(f"{iva_badge}{fmt(l.get('iva_monto', 0))}", styles['T8R'] if 'T8R' in styles else styles['T8'])
                tabla_data.append([
                    cant_str,
                    Paragraph(nombre_celda, styles['T8']),
                    fmt(l.get('precio', 0)),
                    subtotal_cell,
                    iva_cell,
                    fmt(l.get('total', 0)),
                ])
                # Filas de detalle separadas (param 391=1)
                if param391 and serie and not param343:
                    serie_clean = serie.replace('\r\n', '\n').replace('\r', '\n').strip()
                    for det_line in serie_clean.split('\n'):
                        if det_line.strip():
                            tabla_data.append(['', Paragraph(f"<b>{det_line.strip()}</b>", styles['T8']), '', '', '', ''])
                # Fila 2: detalle concatenado (colspan=6)
                partes = [f"C\u00f3digo: {codigo}", f"Cabys: {cabys}", f"Unidad: {unidad}"]
                if not param_344:
                    partes.append(f"Desc monto: {fmt(desc_monto)}")
                partes.append(f"Gravado: {fmt(grav)}")
                partes.append(f"Exonerado: {fmt(exo)}")
                partes.append(f"Exento: {fmt(ext)}")
                detalle2 = ", ".join(partes)
                tabla_data.append([
                    Paragraph(detalle2, styles['T7'] if 'T7' in styles else styles['T8']),
                    '', '', '', '', '',
                ])
                span_fila2_rows.append(len(tabla_data) - 1)
                sep_rows.append(len(tabla_data) - 1)

        if tipo_doc == 'proforma':
            fixed = 30 + 70 + 55 + 55 + 45 + 55
            col_w = [30, 70, pw - fixed, 55, 55, 45, 55]
        else:
            # 6 columnas: Cant | Descripción | Precio/Ud | SubTotal | IVA | Total
            fixed = 35 + 55 + 65 + 65 + 65
            col_w = [35, pw - fixed, 55, 65, 65, 65]
        tabla = Table(tabla_data, colWidths=col_w, repeatRows=1)
        estilo_tabla = [
            # Header sin fondo, negro bold, rayas 1.5px arriba/abajo
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('LINEABOVE', (0, 0), (-1, 0), 1.5, colors.black),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.black),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ]
        # SPAN fila 2 concatenada (colspan=6)
        for r in span_fila2_rows:
            estilo_tabla.append(('SPAN', (0, r), (-1, r)))
            estilo_tabla.append(('ALIGN', (0, r), (-1, r), 'LEFT'))
            estilo_tabla.append(('BACKGROUND', (0, r), (-1, r), colors.HexColor('#f9f9f9')))
            estilo_tabla.append(('TEXTCOLOR', (0, r), (-1, r), colors.black))
        # SPAN descripción fila 1 → todo el ancho cuando cabys=1 (layout legacy proforma)
        for r in span_desc_rows:
            estilo_tabla.append(('SPAN', (2, r), (-1, r)))
            estilo_tabla.append(('ALIGN', (2, r), (-1, r), 'LEFT'))
        # SPAN fila 2 cabys legacy
        for r in span_cabys_rows:
            estilo_tabla.append(('SPAN', (0, r), (2, r)))
            estilo_tabla.append(('ALIGN', (0, r), (2, r), 'LEFT'))
        # Línea sutil gris entre artículos (param 21)
        if linea_division:
            for r in sep_rows[:-1]:  # no dibujar en el último (ya hay línea final)
                estilo_tabla.append(('LINEBELOW', (0, r), (-1, r), 0.25, colors.lightgrey))
        tabla.setStyle(TableStyle(estilo_tabla))
        el.append(tabla)

        # ── TOTALES ──
        el.append(Spacer(1, 2*mm))

        # Info izquierda
        num_lineas = len(lineas_data)
        sum_arts = sum(l.get('cantidad', 0) for l in lineas_data)
        arts_str = str(int(sum_arts)) if sum_arts == int(sum_arts) else f"{sum_arts:.2f}"

        resumen_iva = totales.get('resumen_iva', {})
        iva_detail = ''
        if resumen_iva:
            parts = [f"{k}%: {fmt(v)}" for k, v in (resumen_iva.items() if isinstance(resumen_iva, dict) else [])]
            if parts: iva_detail = f"Detalle IVA: {' | '.join(parts)}"

        info_izq = [
            Paragraph(f"LÍNEAS: {num_lineas} &nbsp;&nbsp; ARTÍCULOS: {arts_str}", styles['N8B']),
        ]
        if iva_detail:
            info_izq.append(Paragraph(iva_detail, styles['N7']))

        # Tabla totales derecha
        t_rows = []
        if tipo_doc == 'proforma':
            sub_from_lines = sum(l.get('precio', 0) * l.get('cantidad', 0) for l in lineas_data)
            desc_from_lines = sum(l.get('desc_monto', 0) for l in lineas_data)
            iva_from_lines = sum(l.get('iva_monto', 0) for l in lineas_data)
            sub_total = totales.get('subtotal', 0)
            if not sub_total:
                sub_total = sub_from_lines - desc_from_lines
            iva_total = totales.get('iva', 0)
            if not iva_total:
                iva_total = iva_from_lines
            desc = totales.get('descuento', 0)
            if desc > 0: t_rows.append([f'Líneas: {num_lineas} | Arts: {arts_str}      DESCUENTO', fmt(desc)])
            else: t_rows.append([f'Líneas: {num_lineas} | Arts: {arts_str}', ''])
            iva_detail_str = ''
            if resumen_iva:
                parts = [f"{k}%: {fmt(v)}" for k, v in (resumen_iva.items() if isinstance(resumen_iva, dict) else [])]
                if parts: iva_detail_str = f"IVA: {' | '.join(parts)}      "
            t_rows.append([f'{iva_detail_str}SUB TOTAL', fmt(sub_total)])
            if iva_total > 0: t_rows.append(['IVA', fmt(iva_total)])
        else:
            # Factura: 3 columnas (Servicios | Mercancías | Impuestos)
            sg = totales.get('serv_gravado', 0)
            se = totales.get('serv_exento', 0)
            seo = totales.get('serv_exonerado', 0)
            mg = totales.get('merc_gravado', 0)
            me = totales.get('merc_exento', 0)
            meo = totales.get('merc_exonerado', 0)
            desc = totales.get('descuento', 0)
            sub = totales.get('subtotal', 0) or (sg+se+seo+mg+me+meo - desc)
            iva_t = totales.get('iva', 0)
            ivd = totales.get('iva_devuelto', 0)
            ims = totales.get('imp_servicio', 0)

            vb = sg + se + seo + mg + me + meo

            def _mini_tabla(rows):
                """Crea mini-tabla con label izq y monto derecha."""
                t = Table(rows, colWidths=[None, 55])
                t.setStyle(TableStyle([
                    ('FONTSIZE', (0, 0), (-1, -1), 7),
                    ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
                    ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), -1),
                    ('TOPPADDING', (0, 0), (-1, -1), -1),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                    ('LEADING', (0, 0), (-1, -1), 8),
                ]))
                return t

            # Columna 1: Detalle IVA
            iva_rows = []
            if resumen_iva and isinstance(resumen_iva, dict):
                for k, v in resumen_iva.items():
                    if v > 0:
                        iva_rows.append([f"IVA {k}%", fmt(v)])
            if not iva_rows:
                iva_rows.append(['SIN IVA', '0.00'])
            col_iva = _mini_tabla(iva_rows)

            # Columna 2: Servicios
            serv_rows = [
                ['GRAVADO', fmt(sg)],
                ['EXONERADO', fmt(seo)],
                ['EXENTO', fmt(se)],
            ]
            col_serv = _mini_tabla(serv_rows)

            # Columna 3: Mercancías
            merc_rows = [
                ['GRAVADO', fmt(mg)],
                ['EXONERADO', fmt(meo)],
                ['EXENTO', fmt(me)],
            ]
            col_merc = _mini_tabla(merc_rows)

            # Columna 4: Totales
            imp_rows = [
                ['VENTA BRUTA', fmt(vb)],
            ]
            if desc > 0: imp_rows.append(['DESCUENTO', fmt(desc)])
            imp_rows.append(['SUB TOTAL', fmt(sub)])
            if iva_t > 0: imp_rows.append(['TOTAL IVA', fmt(iva_t)])
            if ivd > 0: imp_rows.append(['IVA DEV.', fmt(ivd)])
            if ims > 0: imp_rows.append(['IMP. SERV.', fmt(ims)])
            col_imp = _mini_tabla(imp_rows)

            col4_w = pw / 4
            # Títulos de cada grupo
            titulos_data = [['Detalle IVA', 'Servicios', 'Mercancía', 'Totales']]
            titulos_t = Table(titulos_data, colWidths=[col4_w, col4_w, col4_w, col4_w])
            titulos_t.setStyle(TableStyle([
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                ('TOPPADDING', (0, 0), (-1, -1), 1),
                ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#999')),
            ]))

            t4_data = [[col_iva, col_serv, col_merc, col_imp]]
            t4 = Table(t4_data, colWidths=[col4_w, col4_w, col4_w, col4_w])
            t4.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOX', (0, 0), (0, 0), 0.5, colors.HexColor('#ddd')),
                ('BOX', (1, 0), (1, 0), 0.5, colors.HexColor('#ddd')),
                ('BOX', (2, 0), (2, 0), 0.5, colors.HexColor('#ddd')),
                ('BOX', (3, 0), (3, 0), 0.5, colors.HexColor('#ddd')),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ]))
            el.append(Spacer(1, 2*mm))
            el.append(titulos_t)
            el.append(t4)

            # Líneas, Artículos y Total en misma fila
            total_final = totales.get('total', 0)
            info_data = [[f"LÍNEAS: {num_lineas}", f"ARTÍCULOS: {arts_str}", '', f"TOTAL: {moneda} {fmt(total_final)}"]]
            info_t = Table(info_data, colWidths=[col4_w, col4_w, col4_w, col4_w])
            info_t.setStyle(TableStyle([
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                ('ALIGN', (0, 0), (1, 0), 'LEFT'),
                ('ALIGN', (3, 0), (3, 0), 'RIGHT'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ('LINEABOVE', (0, 0), (-1, 0), 1, colors.black),
            ]))
            el.append(info_t)
            # Detalle del documento debajo
            if documento.get('detalle'):
                el.append(Paragraph(f"<b>Detalle:</b> {documento['detalle']}", styles['DetalleGrande']))
            # No usar t_rows para facturas, ya se renderizó con t3
            t_rows = []

        if t_rows:
            t_tabla = Table(t_rows, colWidths=[130, 90], hAlign='RIGHT')
            t_tabla.setStyle(TableStyle([
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica'),
                ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
                ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
            ]))
            el.append(t_tabla)

        # TOTAL (solo para proformas, facturas ya lo tienen en la fila de LÍNEAS/ARTÍCULOS)
        if tipo_doc == 'proforma':
            el.append(HRFlowable(width='100%', thickness=1, color=colors.black))
            total_final = totales.get('total', 0)
            el.append(Paragraph(f"TOTAL: {moneda} {fmt(total_final)}", styles['TotalGrande']))

        # Monto en letras
        total_final_letras = totales.get('total', 0) if tipo_doc != 'proforma' else total_final
        el.append(Paragraph(f"SON: {_monto_en_letras(total_final_letras, moneda)}", styles['N7']))

        # ── PAGOS (en una sola línea) ──
        if pagos:
            pago_parts = []
            vuelto = 0
            for p in pagos:
                monto = p.get('monto', 0)
                medio = p.get('medio_codigo', '')
                nombre = p.get('medio_nombre', '')
                if medio in ('00', '99') or monto < 0:
                    vuelto += abs(monto)
                elif monto > 0:
                    pago_parts.append(f"{nombre}: {fmt(monto)}")
            if vuelto > 0:
                pago_parts.append(f"Vuelto: {fmt(vuelto)}")
            if pago_parts:
                el.append(Paragraph(f"<b>Pago:</b> {', '.join(pago_parts)}", styles['N8']))

        # ── CUENTAS BANCARIAS ──
        cuentas = d.get('cuentas_bancarias', [])
        if cuentas:
            el.append(Spacer(1, 2*mm))
            el.append(Paragraph('<b>CUENTAS PARA DEPÓSITO:</b>', styles['N8B']))
            for cuenta in cuentas:
                el.append(Paragraph(cuenta, styles['N7']))

        # ── PIE (se mantiene junto: no se parte "Recibido Conforme"/legal entre hojas) ──
        pie_block = [Spacer(1, 4*mm)]

        if tipo_doc == 'proforma':
            pie_block.append(Paragraph('<b>DOCUMENTO SIN VALOR FISCAL</b>', styles['PieBold']))
            pie_block.append(Paragraph('LOS PRECIOS ESTÁN SUJETOS A CAMBIO SIN PREVIO AVISO', styles['Pie']))
        else:
            pie_block.append(Spacer(1, 8*mm))
            pie_block.append(Paragraph('_' * 60, styles['N7']))
            gen_texto = f"Generado por FactuPOS | {time.strftime('%d/%m/%Y %H:%M:%S')}"
            pie_data = [['RECIBIDO CONFORME / NOMBRE / CÉDULA', gen_texto]]
            pie_tabla = Table(pie_data, colWidths=[pw * 0.5, pw * 0.5])
            pie_tabla.setStyle(TableStyle([
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
            ]))
            pie_block.append(pie_tabla)
            # Condiciones de venta (param 139)
            condiciones = d.get('condiciones_venta', '')
            if condiciones:
                pie_block.append(Spacer(1, 2*mm))
                pie_block.append(Paragraph(condiciones, styles['Pie']))
            # Resolución (param 123)
            resolucion = d.get('resolucion', '')
            if resolucion:
                pie_block.append(Paragraph(resolucion, styles['Pie']))

        # Etiqueta ORIGINAL/COPIA — el TEXTO lo decide el servidor (PHP).
        # Vacío = no se imprime ninguna etiqueta (lo decide el lado del server, no la app).
        if copia_etiqueta:
            pie_block.append(Spacer(1, 3*mm))
            pie_block.append(Paragraph(f"<b>{copia_etiqueta}</b>", styles['PieBold']))

        el.append(KeepTogether(pie_block))

        doc.build(el, canvasmaker=NumberedCanvas)

    except Exception as e:
        return False, f"Error generando PDF: {e}"

    if not os.path.isfile(pdf_path) or os.path.getsize(pdf_path) < 100:
        return False, "PDF no generado"

    # ── IMPRIMIR SILENCIOSAMENTE ──
    try:
        if IS_WINDOWS:
            printed = False
            # SumatraPDF (portable, silencioso)
            # PyInstaller: sys.executable es el .exe real, __file__ es temporal
            exe_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
            sumatra_paths = [
                os.path.join(exe_dir, 'SumatraPDF.exe'),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), 'SumatraPDF.exe'),
                r'C:\invefacon\SumatraPDF.exe',
                r'C:\SumatraPDF\SumatraPDF.exe',
                os.path.expandvars(r'%ProgramFiles%\SumatraPDF\SumatraPDF.exe'),
                os.path.expandvars(r'%ProgramFiles(x86)%\SumatraPDF\SumatraPDF.exe'),
            ]
            sumatra = None
            for sp in sumatra_paths:
                if os.path.isfile(sp):
                    sumatra = sp
                    break
            if sumatra:
                try:
                    cmd = [sumatra, '-print-to', printer_name or 'default', '-silent', pdf_path]
                    log.info(f"[DR] SumatraPDF: {cmd}")
                    subprocess.run(cmd, capture_output=True, timeout=30)
                    printed = True
                except Exception as e:
                    log.warning(f"SumatraPDF error: {e}")
            else:
                log.warning(f"[DR] SumatraPDF NO encontrado. exe_dir={exe_dir}")
            if not printed:
                os.startfile(pdf_path)
                time.sleep(5)
            time.sleep(2)
        elif IS_LINUX:
            lp_cmd = ['lp']
            if printer_name: lp_cmd += ['-d', printer_name]
            lp_cmd.append(pdf_path)
            subprocess.run(lp_cmd, capture_output=True, timeout=15)

        time.sleep(1)
        try: os.unlink(pdf_path)
        except: pass
        return True, f"DataReport impreso ({len(lineas_data)} líneas)"
    except Exception as e:
        try: os.unlink(pdf_path)
        except: pass
        return False, f"Error imprimiendo PDF: {e}"


def print_raw_thermal(printer_name, data_bytes, chunk_size=CHUNK_TAMANO, delay=CHUNK_PAUSA):
    """Enviar bytes RAW — en Linux usa el mismo método que raw normal.

    #760 — Desde que `print_raw` tambien va en trozos, esto es lo mismo con otro
    rotulo. Se conserva el nombre porque hay perfiles marcados `isThermal` que
    entran por aca, pero el troceo es UNO SOLO: si mañana hay que ajustarlo, se
    ajusta en `_escribir_en_trozos` y vale para todas.
    """
    return print_raw(printer_name, data_bytes, chunk_size, delay)

def print_raw_virtual_port(port_name, data_bytes, chunk_size=CHUNK_TAMANO, delay=CHUNK_PAUSA):
    """Enviar bytes RAW via puerto virtual (LPTx en Windows, /dev/usb/lpX en Linux).

    #760 — Va EN TROZOS CON PAUSA, no de un solo write. Por este camino no hay spooler
    en el medio: los bytes entran directo al buffer de la impresora, y una matricial
    Epson lo tiene chico. Si se le manda un documento largo de golpe, imprime hasta
    donde le alcanzo y el resto se PIERDE — sin error, sin aviso, y el trabajo se
    reporta como impreso. Se detecto con una proforma de 19 lineas (~90 renglones):
    salieron todas las lineas y se corto justo antes de los totales.
    """
    try:
        with open(port_name, 'wb') as f:
            _escribir_en_trozos(f.write, data_bytes, chunk_size, delay, f.flush)
        return True, f"Impreso via {port_name}"
    except Exception as e:
        return False, f"Error puerto {port_name}: {e}"


# ===========================================================================
# TRANSPORTES (paridad con FactuPOS Print de Android)
# ---------------------------------------------------------------------------
# Android define cada impresora como un perfil con un `transport`, y de ahi
# salen los campos que pide el formulario. Aca se replica el mismo modelo:
#
#   cups      nombre de cola CUPS      (lo de siempre; cubre USB via CUPS)
#   virtual   /dev/usb/lp0, LPT2       (abrir el dispositivo como archivo)
#   ip        host + puerto 9100       NUEVO
#   serial    /dev/ttyUSB0 + baudios   NUEVO (antes se abria sin fijar baudios)
#   bluetooth MAC + canal RFCOMM       NUEVO
#
# Todas devuelven (ok: bool, mensaje: str) igual que las funciones viejas, para
# que el despachador no tenga que distinguir casos.
# ===========================================================================

PUERTO_IP_DEFECTO = 9100
BAUDIOS_COMUNES = ['9600', '19200', '38400', '57600', '115200']


def print_raw_ip(host, port, data_bytes, timeout_conexion=5, timeout_total=20):
    """Enviar bytes RAW a una impresora de red (JetDirect/RAW, puerto 9100).

    El tope duro `timeout_total` NO es adorno: una impresora de red puede
    aceptar la conexion y quedarse colgada sin leer. Sin el tope, ese socket
    congelaria el worker y con el toda la cola de impresion. Por eso el envio
    corre en un hilo aparte y, si no termina a tiempo, se abandona.
    """
    host = (host or '').strip()
    if not host:
        return False, "Impresora IP sin direccion configurada"
    try:
        port = int(port or PUERTO_IP_DEFECTO)
    except (TypeError, ValueError):
        port = PUERTO_IP_DEFECTO

    resultado = {}

    def _enviar():
        s = None
        try:
            s = socket.create_connection((host, port), timeout=timeout_conexion)
            s.settimeout(10)
            s.sendall(data_bytes)
            # Algunas termicas cortan el trabajo si uno cierra de golpe.
            try:
                s.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            resultado['ok'] = (True, f"Impreso via {host}:{port}")
        except Exception as e:
            resultado['ok'] = (False, f"Error {host}:{port}: {e}")
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass

    h = threading.Thread(target=_enviar, daemon=True)
    h.start()
    h.join(timeout_total)
    if h.is_alive():
        return False, f"Sin respuesta de {host}:{port} tras {timeout_total}s"
    return resultado.get('ok', (False, f"Fallo desconocido con {host}:{port}"))


def probar_ip(host, port, timeout=5):
    """Solo abre y cierra el socket. Para el boton 'Probar conexion' del
    formulario: dice si la impresora contesta ANTES de guardar el perfil."""
    host = (host or '').strip()
    if not host:
        return False, "Escriba la direccion IP"
    try:
        port = int(port or PUERTO_IP_DEFECTO)
    except (TypeError, ValueError):
        return False, "Puerto invalido"
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True, f"{host}:{port} responde"
    except Exception as e:
        return False, f"{host}:{port} no responde: {e}"


def print_raw_serial(device, data_bytes, baudrate=9600, timeout_total=20):
    """Enviar bytes RAW por puerto serie FIJANDO los baudios.

    Antes el serial se trataba como 'puerto virtual': se abria /dev/ttyUSB0 y
    se escribia. Eso hereda la velocidad que tenga el puerto, que casi nunca es
    la de la impresora — sintoma tipico: salen simbolos raros o no sale nada.
    Con pyserial se fija velocidad y formato (8N1) antes de escribir.
    Si pyserial no esta instalado se cae al metodo viejo, que al menos imprime
    cuando la velocidad ya coincide.
    """
    device = (device or '').strip()
    if not device:
        return False, "Impresora serial sin dispositivo configurado"
    try:
        baudrate = int(baudrate or 9600)
    except (TypeError, ValueError):
        baudrate = 9600

    try:
        import serial as _pyserial
    except Exception:
        ok, msg = print_raw_virtual_port(device, data_bytes)
        return ok, msg + " (sin pyserial: velocidad sin fijar)"

    resultado = {}

    def _enviar():
        sp = None
        try:
            sp = _pyserial.Serial(
                port=device, baudrate=baudrate,
                bytesize=_pyserial.EIGHTBITS,
                parity=_pyserial.PARITY_NONE,
                stopbits=_pyserial.STOPBITS_ONE,
                timeout=5, write_timeout=10,
            )
            sp.write(data_bytes)
            sp.flush()
            resultado['ok'] = (True, f"Impreso via {device} @ {baudrate}")
        except Exception as e:
            resultado['ok'] = (False, f"Error {device} @ {baudrate}: {e}")
        finally:
            if sp is not None:
                try:
                    sp.close()
                except Exception:
                    pass

    h = threading.Thread(target=_enviar, daemon=True)
    h.start()
    h.join(timeout_total)
    if h.is_alive():
        return False, f"{device} no termino en {timeout_total}s"
    return resultado.get('ok', (False, f"Fallo desconocido en {device}"))


def print_raw_bluetooth(mac, data_bytes, canal=1, timeout_total=25):
    """Enviar bytes RAW a una impresora Bluetooth por RFCOMM (perfil SPP).

    Usa el socket Bluetooth NATIVO de Python en Linux (AF_BLUETOOTH +
    BTPROTO_RFCOMM): no hace falta pybluez ni ninguna dependencia nueva.
    La impresora tiene que estar YA emparejada en el sistema — igual que en
    Android, que solo lista los dispositivos emparejados.
    El canal 1 es el habitual de SPP en impresoras termicas.
    """
    mac = (mac or '').strip().upper()
    if not mac:
        return False, "Impresora Bluetooth sin MAC configurada"
    if not hasattr(socket, 'AF_BLUETOOTH'):
        return False, "Este sistema no expone sockets Bluetooth"
    try:
        canal = int(canal or 1)
    except (TypeError, ValueError):
        canal = 1

    resultado = {}

    def _enviar():
        s = None
        try:
            s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                              socket.BTPROTO_RFCOMM)
            s.settimeout(10)
            s.connect((mac, canal))
            # En chunks: varias termicas Bluetooth pierden bytes si se les
            # manda el trabajo entero de un golpe (mismo cuidado que el
            # BluetoothPrinter de Android).
            paso = 256
            for i in range(0, len(data_bytes), paso):
                s.send(data_bytes[i:i + paso])
                time.sleep(0.02)
            resultado['ok'] = (True, f"Impreso via BT {mac}")
        except Exception as e:
            resultado['ok'] = (False, f"Error BT {mac}: {e}")
        finally:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass

    h = threading.Thread(target=_enviar, daemon=True)
    h.start()
    h.join(timeout_total)
    if h.is_alive():
        return False, f"BT {mac} no respondio en {timeout_total}s"
    return resultado.get('ok', (False, f"Fallo desconocido con BT {mac}"))


def listar_seriales():
    """Dispositivos serie/USB-serie presentes, para el combo del formulario."""
    encontrados = []
    try:
        import serial.tools.list_ports as _lp
        for p in _lp.comports():
            etiqueta = p.device
            if p.description and p.description != 'n/a':
                etiqueta += f"  ({p.description})"
            encontrados.append(etiqueta)
    except Exception:
        pass
    if not encontrados and IS_LINUX:
        # Sin pyserial: barrido de los nombres tipicos.
        import glob as _glob
        for patron in ('/dev/ttyUSB*', '/dev/ttyACM*', '/dev/ttyS[0-3]',
                       '/dev/usb/lp*'):
            encontrados.extend(sorted(_glob.glob(patron)))
    return encontrados


def listar_bluetooth():
    """Impresoras Bluetooth YA emparejadas, leidas de bluetoothctl.

    Solo emparejadas a proposito: escanear al vuelo tarda y llena la lista de
    telefonos y audifonos del local.
    """
    dispositivos = []
    if not IS_LINUX:
        return dispositivos
    try:
        r = subprocess.run(['bluetoothctl', 'paired-devices'],
                           capture_output=True, text=True, timeout=8)
        for linea in r.stdout.strip().split('\n'):
            # formato: "Device AA:BB:CC:DD:EE:FF Nombre del equipo"
            partes = linea.split(None, 2)
            if len(partes) >= 2 and partes[0] == 'Device':
                mac = partes[1]
                nombre = partes[2] if len(partes) > 2 else ''
                dispositivos.append(f"{mac}  ({nombre})" if nombre else mac)
    except Exception as e:
        log.debug(f"No se pudieron listar dispositivos Bluetooth: {e}")
    return dispositivos


def despachar_raw(perfil, data_bytes, nombre_cups=''):
    """Elegir por donde sale el trabajo, segun el `transport` del perfil.

    Unico punto donde se decide la salida fisica — el equivalente al
    PrinterManager.printBytes() de Android. Todo lo de arriba (VB6, ESC/POS,
    fuente, cajon, corte) ya se aplico y aca solo se entrega el `data_bytes`.
    """
    transporte = str(perfil.get('transport', '') or '').strip().lower()
    direccion = str(perfil.get('address', '') or '').strip()
    vport = str(perfil.get('virtualPort', '') or '').strip()

    # #760 — Troceo del envio. Se puede afinar POR IMPRESORA sin tocar el programa:
    # si una matricial sigue cortando el final, se le baja `chunkSize` o se le sube
    # `chunkDelay` en su perfil. Sin nada configurado van los valores de siempre.
    trozo = perfil.get('chunkSize', CHUNK_TAMANO)
    pausa = perfil.get('chunkDelay', CHUNK_PAUSA)

    # Perfil viejo que nunca paso por la migracion: comportamiento de siempre.
    if not transporte:
        transporte = 'virtual' if vport else 'cups'
        if not direccion:
            direccion = vport or nombre_cups

    if transporte == 'ip':
        return print_raw_ip(perfil.get('host', direccion),
                            perfil.get('port', PUERTO_IP_DEFECTO), data_bytes)

    if transporte == 'serial':
        destino = direccion or vport
        baud = perfil.get('baudRate') or perfil.get('baud')
        if not baud:
            # Serial que viene migrado y todavia sin velocidad elegida: se usa
            # el metodo viejo a proposito, para NO cambiarle el comportamiento
            # a una estacion que hoy imprime bien.
            return print_raw_virtual_port(destino, data_bytes)
        return print_raw_serial(destino, data_bytes, baud)

    if transporte == 'bluetooth':
        return print_raw_bluetooth(direccion, data_bytes,
                                   perfil.get('btChannel', 1))

    if transporte == 'virtual':
        return print_raw_virtual_port(direccion or vport, data_bytes, trozo, pausa)

    # 'cups' y cualquier valor desconocido → exactamente lo de antes.
    if vport:
        return print_raw_virtual_port(vport, data_bytes, trozo, pausa)
    if perfil.get('isThermal', False):
        return print_raw_thermal(nombre_cups or direccion, data_bytes, trozo, pausa)
    return print_raw(nombre_cups or direccion, data_bytes, trozo, pausa)


def solo_direccion(valor):
    """Del texto del combo ('/dev/ttyUSB0  (FTDI)' o 'AA:BB:..  (POS-58)')
    saca la direccion pelada. Los combos muestran descripcion para que el
    usuario reconozca el aparato, pero guardar la descripcion romperia el
    envio."""
    return (valor or '').split('  (')[0].strip()

def print_spooler(printer_name, text, font_name="Lucida Console", font_size=10):
    """Enviar texto plano a la cola del SO (modo spooler)."""
    if IS_LINUX:
        return _print_spooler_linux(printer_name, text, font_name, font_size)
    if not HAS_WIN32:
        log.info(f"[MOCK] SPOOLER {len(text)} chars → '{printer_name}' ({font_name} {font_size}pt)")
        return True, f"Simulado OK en {printer_name}"

    # Intentar GDI (respeta fuente y tamaño) — fallback a WritePrinter raw
    gdi_error = None
    if HAS_WIN32UI:
        try:
            return _print_spooler_windows_gdi(printer_name, text, font_name, float(font_size))
        except Exception as e:
            gdi_error = str(e)

    try:
        hPrinter = win32print.OpenPrinter(printer_name)
        try:
            win32print.StartDocPrinter(hPrinter, 1, ("FactuPOS", None, "TEXT"))
            try:
                win32print.StartPagePrinter(hPrinter)
                win32print.WritePrinter(hPrinter, text.encode('cp1252', errors='replace'))
                win32print.EndPagePrinter(hPrinter)
            finally:
                win32print.EndDocPrinter(hPrinter)
        finally:
            win32print.ClosePrinter(hPrinter)
        msg = f"Impreso en {printer_name} (spooler/raw)"
        if gdi_error:
            msg += f" GDI-ERROR: {gdi_error}"
        return True, msg
    except Exception as e:
        return False, f"Error: {e}"


def _gdi_create_font(font_name, font_height, bold=False):
    """Crea un objeto font GDI."""
    return win32ui.CreateFont({
        'name': font_name,
        'height': font_height,
        'weight': 700 if bold else 400,
        'pitch and family': win32con.FIXED_PITCH | win32con.FF_MODERN,
    })

def _gdi_line_height(hDC, font_height):
    """Calcula interlineado desde TextMetrics o fallback."""
    try:
        tm = hDC.GetTextMetrics()
        h = tm.get('Height', tm.get('tmHeight', 0))
        ext = tm.get('ExternalLeading', tm.get('tmExternalLeading', 0))
        if h > 0:
            return h + ext
    except:
        pass
    return int(abs(font_height) * 1.2)

def _print_spooler_windows_gdi(printer_name, text, font_name="Lucida Console", font_size=10):
    """Impresión Windows GDI — respeta fuente y tamaño.
    Soporta marcadores: {{G}}=Grande, {{N}}=Normal, {{B}}=Bold, {{C}}=Centrar."""
    hDC = win32ui.CreateDC()
    hDC.CreatePrinterDC(printer_name)

    try:
        dpi_y = hDC.GetDeviceCaps(win32con.LOGPIXELSY)
        font_height_normal = -int(round(float(font_size) * dpi_y / 72.0))
        font_height_grande = -int(round(float(font_size) * 1.6 * dpi_y / 72.0))

        font_normal = _gdi_create_font(font_name, font_height_normal, False)
        font_normal_bold = _gdi_create_font(font_name, font_height_normal, True)
        font_grande = _gdi_create_font(font_name, font_height_grande, True)

        hDC.SelectObject(font_normal)
        lh_normal = _gdi_line_height(hDC, font_height_normal)
        hDC.SelectObject(font_grande)
        lh_grande = _gdi_line_height(hDC, font_height_grande)

        # Restaurar fuente normal
        hDC.SelectObject(font_normal)

        page_width = hDC.GetDeviceCaps(win32con.HORZRES)
        page_height = hDC.GetDeviceCaps(win32con.VERTRES)
        margin_x = int(dpi_y * 0.2)
        margin_y = int(dpi_y * 0.2)
        printable_width = page_width - margin_x * 2

        hDC.StartDoc("FactuPOS")
        lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        y = margin_y
        hDC.StartPage()

        for line in lines:
            # Detectar marcadores
            is_grande = '{{G}}' in line
            is_bold = '{{B}}' in line
            is_center = '{{C}}' in line
            is_right = '{{D}}' in line

            # Limpiar marcadores
            clean = line.replace('{{G}}', '').replace('{{N}}', '').replace('{{B}}', '').replace('{{C}}', '').replace('{{D}}', '')

            # Seleccionar fuente
            if is_grande:
                hDC.SelectObject(font_grande)
                lh = lh_grande
            elif is_bold:
                hDC.SelectObject(font_normal_bold)
                lh = lh_normal
            else:
                hDC.SelectObject(font_normal)
                lh = lh_normal

            # Salto de página
            if y + lh > page_height - margin_y:
                hDC.EndPage()
                hDC.StartPage()
                y = margin_y

            # Posición X (centrado, derecha o izquierda)
            x = margin_x
            if is_center and clean.strip():
                try:
                    tw, th = hDC.GetTextExtent(clean.strip())
                    x = max(margin_x, margin_x + (printable_width - tw) // 2)
                except:
                    pass
                clean = clean.strip()
            elif is_right and clean.strip():
                try:
                    tw, th = hDC.GetTextExtent(clean.strip())
                    x = max(margin_x, margin_x + printable_width - tw)
                except:
                    pass
                clean = clean.strip()

            hDC.TextOut(x, y, clean)
            y += lh

            # Restaurar fuente normal
            if is_grande or is_bold:
                hDC.SelectObject(font_normal)

        hDC.EndPage()
        hDC.EndDoc()

        return True, f"Impreso en {printer_name} (GDI, {font_name} {font_size}pt)"
    finally:
        hDC.DeleteDC()


# ---------------------------------------------------------------------------
# Code128-B barcode encoding
# ---------------------------------------------------------------------------
def _barcode128b_values(text):
    """Calcula los valores Code128-B (sin codificar a fuente)."""
    values = [104]  # Start B
    for i, ch in enumerate(text):
        val = ord(ch) - 32
        if val < 0 or val > 94:
            val = 0
        values.append(val)
    checksum = values[0]
    for i in range(1, len(values)):
        checksum += values[i] * i
    values.append(checksum % 103)
    values.append(106)  # Stop
    return values

# Patrones de barras Code128 (cada valor = 6 anchos de barras: b s b s b s)
CODE128_PATTERNS = [
    "212222","222122","222221","121223","121322","131222","122213","122312",
    "132212","221213","221312","231212","112232","122132","122231","113222",
    "123122","123221","223211","221132","221231","213212","223112","312131",
    "311222","321122","321221","312212","322112","322211","212123","212321",
    "232121","111323","131123","131321","112313","132113","132311","211313",
    "231113","231311","112133","112331","132131","113123","113321","133121",
    "313121","211331","231131","213113","213311","213131","311123","311321",
    "331121","312113","312311","332111","314111","221411","431111","111224",
    "111422","121124","121421","141122","141221","112214","112412","122114",
    "122411","142112","142211","241211","221114","413111","241112","134111",
    "111242","121142","121241","114212","124112","124211","411212","421112",
    "421211","212141","214121","412121","111143","111341","131141","114113",
    "114311","411113","411311","113141","114131","311141","411131","211412",
    "211214","211232","2331112",  # 106 = Stop pattern (7 elements)
]

def _draw_barcode128_gdi(hDC, x_px, y_px, payload, bar_height, dpi_x, target_w_mm=0.0):
    """Dibuja código de barras Code 128 usando rectángulos GDI.

    payload: str → se codifica internamente en Code128-B (legacy / fallback).
             list[int] → valores de símbolo ya codificados por PHP con auto B/C
             (más angosto en códigos numéricos).
    target_w_mm: si >0, ancho total objetivo del código en mm (incluye la
             quiet zone izquierda de 10 módulos). Se computa module_w para
             entrar exacto, con piso de 1 dot. 0 → módulo fijo 0.25mm GS1.

    Estrategia de dibujo: PatBlt con ROP BLACKNESS (0x42) fuerza relleno negro
    sólido sin depender del brush/pen seleccionado y SIN modificar BkColor/
    TextColor de la DC, así no ensucia TextOut posterior.
    """
    if isinstance(payload, (list, tuple)):
        values = [int(v) for v in payload]
    else:
        values = _barcode128b_values(str(payload))

    QZ = 10  # quiet zone izquierda (módulos)

    # Unidades totales = QZ + suma de anchos de cada patrón (cada patrón es
    # una cadena de 6-7 dígitos, cada uno = ancho en módulos).
    total_units = QZ
    for v in values:
        if 0 <= v < len(CODE128_PATTERNS):
            total_units += sum(int(c) for c in CODE128_PATTERNS[v])

    if target_w_mm and target_w_mm > 0 and total_units > 0:
        # Ajustar el módulo para que el código entre en target_w_mm.
        # floor con epsilon (~0.02 módulos = ~0.0025mm) para corregir el redondeo
        # mm→px que hace caer valores "casi enteros" al dot anterior. Ej a 203dpi
        # un código de 15 dígitos (144 unidades) con target 36mm da raw=1.998 →
        # sin epsilon caería a 1 dot (18mm); con epsilon sube a 2 dots (36mm).
        target_px = target_w_mm * dpi_x / 25.4
        raw_mw   = target_px / total_units
        module_w = max(1, int(raw_mw + 0.02))
    else:
        # 0.025cm = 0.25mm = X-dimension mínima GS1 para uso general
        # (antes 0.033 = 0.33mm, no cabía Code128 de 4+ chars en etiquetas de 3cm)
        module_w = max(1, int(round(dpi_x * 0.025 / 2.54)))

    cur_x = x_px + module_w * QZ

    BLACKNESS = 0x00000042  # ROP3: ignora pen/brush, llena con negro

    for val in values:
        if val < 0 or val >= len(CODE128_PATTERNS):
            continue
        pattern = CODE128_PATTERNS[val]
        for j, ch in enumerate(pattern):
            w = int(ch) * module_w
            if j % 2 == 0:
                # Barra (negro sólido) — PatBlt(BLACKNESS) no toca state
                drawn = False
                try:
                    hDC.PatBlt((cur_x, y_px), (w, bar_height), BLACKNESS)
                    drawn = True
                except Exception:
                    pass
                if not drawn:
                    # Fallback 1: BitBlt con BLACKNESS (alternativa)
                    try:
                        hDC.BitBlt((cur_x, y_px), (w, bar_height), hDC, (0, 0), BLACKNESS)
                        drawn = True
                    except Exception:
                        pass
                if not drawn:
                    # Fallback 2: Rectangle con BLACK_BRUSH + NULL_PEN (con restore)
                    old_brush = None
                    old_pen = None
                    try:
                        old_brush = hDC.SelectStockObject(win32con.BLACK_BRUSH)
                    except Exception:
                        pass
                    try:
                        old_pen = hDC.SelectStockObject(win32con.NULL_PEN)
                    except Exception:
                        pass
                    try:
                        hDC.Rectangle((cur_x, y_px, cur_x + w, y_px + bar_height))
                    except Exception:
                        pass
                    try:
                        if old_brush is not None:
                            hDC.SelectObject(old_brush)
                    except Exception:
                        pass
                    try:
                        if old_pen is not None:
                            hDC.SelectObject(old_pen)
                    except Exception:
                        pass
            # Espacio (blanco) — no dibujamos nada
            cur_x += w


# ---------------------------------------------------------------------------
# GDI con coordenadas absolutas (formato COORD — ex MODVENT100 VB6)
# ---------------------------------------------------------------------------
def _print_gdi_coordenadas(json_data, printer_name):
    """Impresión GDI con coordenadas absolutas en centímetros.

    Recibe un JSON con lista de comandos:
      cmd=1  →  imagen de fondo (reservado, no implementado aún)
      cmd=2  →  TextOut(x_cm, y_cm, texto) con fuente/tamaño
      cmd=9  →  fin de página (form feed)

    Cada comando tipo 2:
      {"cmd": 2, "y": 0.30, "x": 15.80, "fuente": "Lucida Console",
       "tamano": 10, "valor": "00100001010000005057"}
    """
    if not HAS_WIN32UI:
        return False, "win32ui no disponible — se requiere Windows con GDI"

    comandos = json_data.get('comandos', [])
    copias = json_data.get('copias', 1)

    if not comandos:
        return False, "Sin comandos para imprimir"

    total_textos = 0

    for copia in range(copias):
        hDC = win32ui.CreateDC()
        hDC.CreatePrinterDC(printer_name)
        try:
            dpi_x = hDC.GetDeviceCaps(win32con.LOGPIXELSX)
            dpi_y = hDC.GetDeviceCaps(win32con.LOGPIXELSY)

            # Cache de fuentes: (nombre, tamaño) → objeto font GDI
            font_cache = {}

            hDC.StartDoc("FactuPOS COORD")
            hDC.StartPage()
            page_started = True

            for cmd in comandos:
                tipo = cmd.get('cmd', 0)

                if tipo == 9:
                    # --- Fin de página / form feed ---
                    if page_started:
                        hDC.EndPage()
                        page_started = False

                elif tipo == 2:
                    # --- TextOut en coordenadas absolutas ---
                    if not page_started:
                        hDC.StartPage()
                        page_started = True

                    # Y en unidades VB6 (dividir entre escala), X en cm directo
                    escala_y = float(json_data.get('escala_y', 3.1))
                    x_cm = float(cmd.get('x', 0))
                    y_cm = float(cmd.get('y', 0)) / escala_y
                    fuente = cmd.get('fuente', 'Lucida Console')
                    tamano = int(cmd.get('tamano', 10))
                    valor = str(cmd.get('valor', ''))
                    is_barcode = cmd.get('barcode', False)

                    if not valor:
                        continue

                    # Si es código de barras, codificar en Code128-B
                    # Convertir cm → pixels
                    x_px = int(round(x_cm * dpi_x / 2.54))
                    y_px = int(round(y_cm * dpi_y / 2.54))

                    # Obtener o crear fuente (cacheada)
                    font_key = (fuente, tamano)
                    if font_key not in font_cache:
                        font_height = -int(round(tamano * dpi_y / 72.0))
                        font_cache[font_key] = win32ui.CreateFont({
                            'name': fuente,
                            'height': font_height,
                            'weight': 400,
                        })

                    if is_barcode:
                        # Dibujar código de barras como rectángulos
                        # Grosor en mm → pixels
                        grosor_mm = float(cmd.get('grosor', 10))
                        bar_h = int(round(grosor_mm * dpi_y / 25.4))
                        if bar_h < 10:
                            bar_h = int(round(10 * dpi_y / 25.4))
                        # 'barcode_values' (>=v4.29): símbolos ya codificados por
                        # PHP con auto-switch B/C. Si no viene, re-encode 'valor'
                        # en Code-B (compat con servidor viejo).
                        bvals = cmd.get('barcode_values')
                        payload = bvals if isinstance(bvals, list) and bvals else valor
                        # 'ancho' (>=v4.29, opcional): ancho total deseado en mm
                        # (0 = automático, módulo fijo 0.25mm).
                        try:
                            target_w_mm = float(cmd.get('ancho', 0) or 0)
                        except (TypeError, ValueError):
                            target_w_mm = 0.0
                        _draw_barcode128_gdi(hDC, x_px, y_px, payload,
                                             bar_h, dpi_x, target_w_mm)
                    else:
                        hDC.SelectObject(font_cache[font_key])
                        hDC.TextOut(x_px, y_px, valor)
                    total_textos += 1

            # Cerrar última página si quedó abierta
            if page_started:
                hDC.EndPage()

            hDC.EndDoc()
        finally:
            hDC.DeleteDC()

    label = "ORIGINAL" if copias == 1 else f"{copias}x"
    return True, f"COORD impreso ({label}, {total_textos} campos)"


def _print_spooler_linux(printer_name, text, font_name="Monospace", font_size=10):
    """Enviar texto plano a impresora CUPS en Linux con fuente específica."""
    import tempfile
    import shutil
    try:
        # Mapear fuentes Windows → Linux
        font_map = {
            'lucida console': 'Monospace',
            'courier new': 'Courier',
            'consolas': 'Monospace',
            'terminal': 'Monospace',
        }
        linux_font = font_map.get(font_name.lower(), 'Monospace')

        if isinstance(font_size, str):
            try: font_size = float(font_size)
            except: font_size = 10
        font_size = float(font_size)

        # Tamaño grande: +4pt (8→12, 10→14, 12→16)
        font_size_grande = font_size + 4

        # Detectar marcadores y convertir a Pango markup
        tiene_marcadores = '{{G}}' in text or '{{C}}' in text or '{{B}}' in text
        usar_markup = tiene_marcadores and shutil.which('paps')

        if usar_markup:
            # Convertir marcadores a Pango markup
            # Ancho aprox en caracteres según tamaño de fuente
            ancho_chars = 95
            lineas = text.split('\n')
            markup_lines = []
            for linea in lineas:
                es_grande = '{{G}}' in linea
                es_bold = '{{B}}' in linea
                es_derecha = '{{D}}' in linea
                # Limpiar marcadores
                clean = linea.replace('{{G}}', '').replace('{{C}}', '').replace('{{D}}', '').replace('{{B}}', '').replace('{{N}}', '')
                # Alinear derecha con espacios (menos ancho si es grande)
                if es_derecha:
                    clean_stripped = clean.strip()
                    ancho_efectivo = int(ancho_chars * 0.8) if es_grande else ancho_chars
                    pad = max(0, ancho_efectivo - len(clean_stripped))
                    clean = ' ' * pad + clean_stripped
                # Escapar XML
                clean = clean.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                if es_grande:
                    markup_lines.append(f'<span font="{linux_font} Bold {font_size_grande}">{clean}</span>')
                elif es_bold:
                    markup_lines.append(f'<span font="{linux_font} Bold {font_size}">{clean}</span>')
                else:
                    markup_lines.append(clean)
            text_final = '\n'.join(markup_lines)
        else:
            # Sin marcadores: limpiar y usar texto plano
            text_final = text.replace('{{G}}', '').replace('{{C}}', '').replace('{{D}}', '').replace('{{B}}', '').replace('{{N}}', '')

        with tempfile.NamedTemporaryFile(delete=False, suffix='.txt', mode='w', encoding='utf-8') as tmp:
            tmp.write(text_final)
            tmp_path = tmp.name

        # Intentar con paps (texto → PostScript con fuente/tamaño)
        if shutil.which('paps'):
            ps_path = tmp_path + '.ps'
            paps_cmd = ['paps',
                        f'--font={linux_font} {font_size}',
                        '--left-margin=18',
                        '--right-margin=18',
                        '--top-margin=72',
                        '--bottom-margin=18']
            if usar_markup:
                paps_cmd.append('--markup')
            paps_cmd.append(tmp_path)
            with open(ps_path, 'wb') as ps_file:
                r1 = subprocess.run(paps_cmd, stdout=ps_file, stderr=subprocess.PIPE, timeout=10)
            os.unlink(tmp_path)
            result = subprocess.run(
                ['lp', '-d', printer_name, ps_path],
                capture_output=True, text=True, timeout=15
            )
            os.unlink(ps_path)
        else:
            # Fallback: lp directo (sin control de fuente)
            result = subprocess.run(
                ['lp', '-d', printer_name, tmp_path],
                capture_output=True, text=True, timeout=15
            )
            os.unlink(tmp_path)

        # Reactivar impresora (CUPS a veces la pausa después de imprimir)
        subprocess.run(['cupsenable', printer_name], capture_output=True, timeout=5)

        if result.returncode == 0:
            return True, f"Impreso en {printer_name} (spooler/cups, {linux_font} {font_size}pt)"
        return False, f"Error lp: {result.stderr.strip()}"
    except Exception as e:
        return False, f"Error: {e}"

# ---------------------------------------------------------------------------
# Limpiar cola de impresión
# ---------------------------------------------------------------------------
# Hay DOS colas distintas y hay que vaciar las dos:
#   1. La del SPOOLER del equipo (CUPS en Linux / spooler de Windows): trabajos ya
#      entregados a la impresora que quedaron pegados.
#   2. La del SERVIDOR (SQLite print_jobs en la .17): trabajos 'queued' que todavía
#      no se entregaron a esta terminal y que se re-enviarían al reconectar.
# Vaciar solo la (1) no sirve: el server vuelve a mandar los pendientes en el
# próximo `register` (ver flushPendingJobs). Vaciar solo la (2) tampoco: lo que ya
# está en el spooler local sigue saliendo por la impresora.

def purge_spooler_queue(printer_name):
    """Cancelar los trabajos pendientes en el spooler del SO para una impresora.

    Devuelve (ok, cancelados, mensaje). Las impresoras por puerto virtual
    (/dev/usb*, COM*) NO pasan por el spooler → no hay nada que cancelar.
    """
    if not printer_name:
        return False, 0, "La impresora no tiene nombre de spooler"

    if IS_WINDOWS:
        try:
            hPrinter = win32print.OpenPrinter(
                printer_name, {"DesiredAccess": win32print.PRINTER_ALL_ACCESS})
        except Exception as e:
            return False, 0, f"No se pudo abrir '{printer_name}': {e}"
        try:
            jobs = win32print.EnumJobs(hPrinter, 0, -1, 1)
            cancelados = 0
            for job in jobs:
                try:
                    win32print.SetJob(hPrinter, job['JobId'], 0, None,
                                      win32print.JOB_CONTROL_DELETE)
                    cancelados += 1
                except Exception:
                    pass  # job ya terminó entre el Enum y el SetJob
            return True, cancelados, f"{cancelados} trabajo(s) cancelado(s)"
        except Exception as e:
            return False, 0, f"Error al cancelar: {e}"
        finally:
            win32print.ClosePrinter(hPrinter)

    # Linux / CUPS: contar primero (cancel no reporta cuántos borró)
    try:
        r = subprocess.run(['lpstat', '-o', printer_name],
                           capture_output=True, text=True, timeout=10)
        pendientes = len([l for l in r.stdout.splitlines() if l.strip()])
    except Exception:
        pendientes = 0
    try:
        r = subprocess.run(['cancel', '-a', printer_name],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return False, 0, f"Error cancel: {(r.stderr or '').strip()}"
        return True, pendientes, f"{pendientes} trabajo(s) cancelado(s)"
    except FileNotFoundError:
        return False, 0, "CUPS no instalado (falta el comando `cancel`)"
    except Exception as e:
        return False, 0, f"Error al cancelar: {e}"


def _http_base_from_ws(ws_url):
    """ws://host:9300 → http://host:9301. Toma SOLO el host del WS; el puerto es
    siempre HTTP_API_PORT (el del WS se descarta)."""
    try:
        sin_esquema = ws_url.split('://', 1)[-1]
        host = sin_esquema.split('/', 1)[0].split(':', 1)[0]
        return f"http://{host}:{HTTP_API_PORT}"
    except Exception:
        return None


def purge_server_queue(ws_url, empresa, queue_code):
    """Borrar del servidor los jobs 'queued' de UNA cola de esta empresa.

    Pega a `POST /job-delete` con {empresa, queue}. Devuelve (ok, borrados, msg).
    """
    base = _http_base_from_ws(ws_url)
    if not base:
        return False, 0, f"URL de servidor inválida: {ws_url}"
    if not empresa:
        return False, 0, "La impresora no tiene empresa asignada"

    payload = json.dumps({'empresa': empresa, 'queue': queue_code}).encode('utf-8')
    req = urllib.request.Request(
        f"{base}/job-delete", data=payload, method='POST',
        headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return False, 0, f"No se pudo contactar al servidor: {e}"

    if not data.get('ok'):
        return False, 0, data.get('error', 'error desconocido')
    borrados = int(data.get('deleted', 0))
    return True, borrados, f"{borrados} job(s) borrado(s)"

# ---------------------------------------------------------------------------
# WebSocket Client
# ---------------------------------------------------------------------------
class PrintQueueClient:
    def __init__(self, config, on_log=None, on_status=None):
        self.config = config
        self.servers = config.get('servers', ['ws://127.0.0.1:9300'])
        self.current_server = self.servers[0]
        self.server_index = 0
        self.client_id = config.get('clientId', socket.gethostname())
        self.token = config.get('token', '')
        self.reconnect_interval = config.get('reconnectInterval', 5)
        self.printers = config.get('printers', [])
        self.ws = None
        self.connected = False
        self.running = True
        self.jobs_ok = 0
        self.jobs_err = 0
        self.log_buffer = deque(maxlen=200)
        self._on_log = on_log
        self._on_status = on_status

        self._update_checked = False

        self.queue_map = {}
        for p in self.printers:
            self.queue_map[p['queueCode']] = p

    def _log(self, msg, level='info'):
        ts = datetime.now().strftime('%H:%M:%S')
        entry = f"{ts} {msg}"
        self.log_buffer.append(entry)
        getattr(log, level)(msg)
        if self._on_log:
            self._on_log(entry)

    def _set_status(self, connected):
        self.connected = connected
        if self._on_status:
            self._on_status(connected)

    def get_queue_codes(self):
        return [p['queueCode'] for p in self.printers]

    def _build_queue_list(self):
        """Construir lista de colas con empresa por cada una."""
        result = []
        for p in self.printers:
            result.append({
                "code": p['queueCode'],
                "empresa": p.get('empresa', ''),
            })
        return result

    def on_open(self, ws):
        self._log(f"Conectado a {self.current_server}")
        self._set_status(True)
        queues = self._build_queue_list()
        ws.send(json.dumps({
            "action": "register",
            "queues": queues,
            "clientId": self.client_id,
            "clientVersion": VERSION,
            "plataforma": "linux" if IS_LINUX else "windows",
            "token": self.token,
        }))
        empresas = set(q.get('empresa', '?') for q in queues)
        self._log(f"Registrando {len(queues)} cola(s) [empresas: {', '.join(empresas)}]")
        # Linux: chequear actualización al CONECTAR (autónomo, no depende de registrar
        # colas). Windows: la version la anuncia el server en la respuesta 'registered'.
        if IS_LINUX:
            threading.Thread(target=self._check_update_linux, daemon=True).start()

    def on_message(self, ws, message):
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            self._log(f"JSON inválido: {message[:100]}", 'error')
            return

        action = msg.get('action', '')
        if action == 'registered':
            self._log(f"Registrado OK como '{msg.get('clientId')}'")
            # Windows: la version la anuncia el server aquí. (Linux se chequea en on_open.)
            if not IS_LINUX:
                latest = msg.get('latestVersion', '')
                download_url = msg.get('downloadUrl', '')
                # Solo actualizar si el SERVER reporta una version MAYOR que la del cliente
                # (nunca downgrade ni "distinta" -> evita el loop si el server quedo atras).
                if latest and download_url and _version_gt(latest, VERSION):
                    self._log(f"Nueva versión disponible: {latest} (actual: {VERSION})")
                    threading.Thread(target=self._auto_update, args=(latest, download_url), daemon=True).start()
                elif latest and latest != VERSION:
                    self._log(f"Server reporta v{latest} pero el cliente ya está en v{VERSION}; no se actualiza.")
        elif action == 'print':
            self._handle_print_job(ws, msg)
        elif action == 'ack_received':
            pass
        elif msg.get('ok') is False:
            self._log(f"Error del servidor: {msg.get('error')}", 'error')

    def _handle_print_job(self, ws, msg):
        job_id = msg.get('jobId', '?')
        queue = msg.get('queue', '')
        self._log(f"Job {job_id[:8]} recibido → cola {queue}")
        ok, result_msg = self.imprimir_trabajo(job_id, queue, msg.get('data', ''))
        if ok:
            self._send_ack(ws, job_id, 'ok')
        else:
            self._send_ack(ws, job_id, 'error', result_msg)

    def buscar_cola(self, queue, empresa=''):
        """Perfil de impresora de una cola. Con `empresa`, la de ESA empresa (el mismo
        código de cola puede estar en dos empresas del mismo equipo)."""
        if empresa:
            for p in self.printers:
                if p.get('queueCode') == queue and p.get('empresa', '') == empresa:
                    return p
        return self.queue_map.get(queue)

    def imprimir_trabajo(self, job_id, queue, data_b64, empresa=''):
        """El ÚNICO camino de impresión de un trabajo, venga de la nube (WS) o del
        puerto local (sin internet). → (ok, mensaje). Un trabajo a la vez: la nube y el
        puerto local pueden coincidir y la impresora no se comparte a medias."""
        with IMPRESION_LOCK:
            return self._imprimir_trabajo(job_id, queue, data_b64, empresa)

    def _imprimir_trabajo(self, job_id, queue, data_b64, empresa=''):
        short_id = job_id[:8]
        printer_config = self.buscar_cola(queue, empresa)
        if not printer_config:
            self._log(f"Job {short_id} → cola no mapeada: {queue}", 'error')
            self.jobs_err += 1
            return False, f'Cola no mapeada: {queue}'

        win_printer = printer_config.get('windowsPrinter', printer_config.get('printer', ''))
        try:
            data_bytes = base64.b64decode(data_b64)
        except Exception as e:
            self._log(f"Job {short_id} → error base64: {e}", 'error')
            self.jobs_err += 1
            return False, str(e)

        print_mode = printer_config.get('printMode', 'raw')
        uses_vb6 = is_vb6_protocol(data_bytes)

        t0 = time.time()

        # --- Modo JSON (FIPVIVI005 DataReport): generar PDF e imprimir ---
        text_check = data_bytes.decode('utf-8', errors='replace').strip()
        if text_check.startswith('JSON:'):
            json_str = text_check[5:]
            self._log(f"Job {short_id} → DataReport (JSON → PDF → impresora)")
            try:
                json_data = json.loads(json_str)
                ok, result_msg = _print_json_datareport(json_data, win_printer)
            except json.JSONDecodeError as e:
                ok, result_msg = False, f"JSON inválido: {e}"
            except Exception as e:
                ok, result_msg = False, f"Error: {e}"

            elapsed = time.time() - t0
            if ok:
                self._log(f"Job {short_id} → DataReport OK ({elapsed:.1f}s) [{result_msg}]")
                self.jobs_ok += 1
            else:
                self._log(f"Job {short_id} → ERROR: {result_msg}", 'error')
                self.jobs_err += 1
            return ok, result_msg

        # --- Modo COORD (GDI con coordenadas absolutas): impresoras matriciales ---
        if text_check.startswith('COORD:'):
            json_str = text_check[6:]
            self._log(f"Job {short_id} → COORD (GDI coordenadas → {win_printer})")
            try:
                json_data = json.loads(json_str)
                ok, result_msg = _print_gdi_coordenadas(json_data, win_printer)
            except json.JSONDecodeError as e:
                ok, result_msg = False, f"JSON inválido: {e}"
            except Exception as e:
                ok, result_msg = False, f"Error: {e}"

            elapsed = time.time() - t0
            if ok:
                self._log(f"Job {short_id} → COORD OK ({elapsed:.1f}s) [{result_msg}]")
                self.jobs_ok += 1
            else:
                self._log(f"Job {short_id} → ERROR: {result_msg}", 'error')
                self.jobs_err += 1
            return ok, result_msg

        # --- Modo URL (fallback): abrir en navegador ---
        if text_check.startswith('URL:'):
            url = text_check[4:].strip()
            self._log(f"Job {short_id} → abriendo URL en navegador")
            try:
                ok, result_msg = _print_url_silent(url, win_printer)
            except Exception as e:
                ok, result_msg = False, f"Error: {e}"

            elapsed = time.time() - t0
            if ok:
                self._log(f"Job {short_id} → URL OK ({elapsed:.1f}s) [{result_msg}]")
                self.jobs_ok += 1
            else:
                self._log(f"Job {short_id} → ERROR: {result_msg}", 'error')
                self.jobs_err += 1
            return ok, result_msg

        if print_mode == 'spooler':
            # --- Modo Spooler: texto plano a la cola del SO ---
            if uses_vb6:
                plain_text = vb6_to_plain(data_bytes)
            else:
                plain_text = data_bytes.decode('latin-1', errors='replace')

            font_name = printer_config.get('spoolerFont', 'Lucida Console')
            font_size = printer_config.get('spoolerFontSize', 10)
            self._log(f"Job {short_id} → spooler fuente={font_name} tamaño={font_size} GDI={'sí' if HAS_WIN32UI else 'no'}")
            ok, result_msg = print_spooler(win_printer, plain_text, font_name, float(font_size))
            self._log(f"Job {short_id} → resultado: {result_msg}")

        else:
            # --- Modo RAW (POS) ---
            is_escpos = True
            if uses_vb6:
                # Protocolo VB6 → convertir a ESC/POS
                data_bytes = vb6_to_escpos(data_bytes, printer_config)
            elif is_plain_text(data_bytes):
                # Texto plano (FIPVIVI003) → envolver con ESC/P para dot matrix
                data_bytes = plain_to_escp(data_bytes, printer_config)
                is_escpos = False
            else:
                # Ya viene con ESC/POS (FIPVIVI002, etc.)
                if printer_config.get('cutPaper', False):
                    data_bytes = data_bytes + ESCPOS_CUT_PAPER

            # Fuente Epson configurada por impresora (A=normal / B=condensada).
            # ESC M n selecciona la fuente sin tocar negrita/tamaño. Solo ESC/POS.
            if is_escpos:
                esc_font = str(printer_config.get('escposFont', '')).upper()
                if esc_font == 'B':
                    data_bytes = b'\x1b\x4d\x01' + data_bytes
                elif esc_font == 'A':
                    data_bytes = b'\x1b\x4d\x00' + data_bytes

            # Inyectar cajón si está configurado
            if printer_config.get('openDrawer', False):
                data_bytes = ESCPOS_OPEN_DRAWER + data_bytes

            ok, result_msg = despachar_raw(printer_config, data_bytes, win_printer)

        elapsed = time.time() - t0

        if ok:
            mode_str = f"{print_mode}" + (" vb6" if uses_vb6 else "")
            self._log(f"Job {short_id} → {win_printer} OK ({elapsed:.1f}s, {mode_str}) [{result_msg}]")
            self.jobs_ok += 1
        else:
            self._log(f"Job {short_id} → ERROR: {result_msg}", 'error')
            self.jobs_err += 1
        return ok, result_msg

    def _send_ack(self, ws, job_id, status, error=None):
        ack = {"action": "ack", "jobId": job_id, "status": status}
        if error:
            ack["error"] = error
        try:
            ws.send(json.dumps(ack))
        except Exception as e:
            self._log(f"Error enviando ACK: {e}", 'error')

    def _auto_update(self, new_version, download_url):
        """Descargar nueva versión y reemplazarse silenciosamente."""
        if self._update_checked:
            return
        self._update_checked = True

        if IS_LINUX:
            # En Linux se reemplaza el .py en sitio + re-exec (ignora download_url
            # del server, que apunta al .exe de Windows).
            self._auto_update_linux(new_version)
            return

        if not getattr(sys, 'frozen', False):
            self._log(f"Auto-update: modo script, no se puede actualizar automáticamente")
            return

        try:
            exe_name = os.path.basename(sys.executable)
            new_exe = os.path.join(APP_DIR, exe_name.replace('.exe', '_new.exe'))

            self._log(f"Descargando {download_url}...")
            urllib.request.urlretrieve(download_url, new_exe)

            # Verificar tamaño mínimo (>1MB) para evitar HTML de error
            file_size = os.path.getsize(new_exe)
            if file_size < 1_000_000:
                self._log(f"Auto-update: archivo descargado muy pequeño ({file_size} bytes), abortando", 'error')
                try:
                    os.remove(new_exe)
                except OSError:
                    pass
                return

            self._log(f"Descargado OK ({file_size:,} bytes). Preparando actualización...")

            # Crear updater.bat
            bat_path = os.path.join(APP_DIR, 'updater.bat')
            bat_content = f'''@echo off
timeout /t 3 /nobreak >nul
del "{exe_name}"
ren "{os.path.basename(new_exe)}" "{exe_name}"
start "" "{exe_name}"
del "%~f0"
'''
            with open(bat_path, 'w', encoding='ascii') as f:
                f.write(bat_content)

            self._log(f"Actualizando a v{new_version}... reiniciando.")

            # Lanzar updater.bat detached
            subprocess.Popen(
                ['cmd.exe', '/c', bat_path],
                cwd=APP_DIR,
                creationflags=0x00000008,  # DETACHED_PROCESS
                close_fds=True,
            )

            # Cerrar la app
            os._exit(0)

        except Exception as e:
            self._log(f"Auto-update error: {e}", 'error')

    def _periodic_update_check_loop(self):
        """Linux: revisa la versión cada UPDATE_CHECK_INTERVAL seg (autónomo)."""
        while self.running:
            time.sleep(UPDATE_CHECK_INTERVAL)
            if self.running and IS_LINUX:
                self._check_update_linux()

    def manual_check_update(self):
        """Chequeo manual de actualización (botón de la UI)."""
        self._update_checked = False
        if IS_LINUX:
            self._log("Buscando actualización (Linux)...")
            threading.Thread(target=self._check_update_linux, daemon=True).start()
        else:
            self._log("Windows: la actualización se gestiona al conectar con el servidor.")

    def _check_update_linux(self):
        """Linux: consulta el archivo de versión DEDICADO (LINUX_VERSION_URLS:
        solo soportereal.com) y, si hay una versión MAYOR, dispara el auto-update.
        Independiente del manifest del WS (que es de Windows)."""
        if self._update_checked:
            return
        data = None
        for url in LINUX_VERSION_URLS:
            try:
                with urllib.request.urlopen(url, timeout=15) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                break
            except Exception as e:
                self._log(f"Check update Linux: falló {url} ({e}); probando siguiente")
                continue
        if not data:
            self._log("Check update Linux: no se pudo leer el archivo de versión")
            return
        latest = str(data.get('version', '')).strip()
        if latest and _version_gt(latest, VERSION):
            self._update_checked = True
            self._log(f"Nueva versión Linux disponible: {latest} (actual: {VERSION})")
            self._auto_update_linux(latest)
            # Si _auto_update_linux retornó, es que FALLÓ (en éxito hace os._exit).
            # Reseteamos para que el chequeo periódico/al-conectar reintente luego.
            self._update_checked = False
        elif latest and latest != VERSION:
            self._log(f"Archivo Linux reporta v{latest}; el cliente ya está en v{VERSION}; no se actualiza.")
        elif latest:
            # Mismo número → al día. SIN este log el botón "Buscar actualización"
            # imprimía "Buscando actualización…" y después nada: parecía colgado.
            self._log(f"Ya tiene la última versión (v{VERSION}).")
        else:
            self._log("Check update Linux: el archivo de versión no trae campo 'version'")

    def _auto_update_linux(self, new_version):
        """Linux: bajar el .py nuevo, reemplazarlo en sitio y re-lanzar el proceso.

        El .deb instala el script en /opt/factupos-print (chmod 777 → escribible
        sin sudo). Se descarga a un temporal, se valida que sea el script correcto
        y de la versión anunciada (evita loops), se reemplaza atómicamente y se
        relanza un proceso desacoplado que espera a que este muera (libera tray /
        sockets) y arranca la versión nueva.
        """
        script_path = os.path.abspath(__file__)
        target_dir = os.path.dirname(script_path)
        tmp_path = os.path.join(target_dir, 'factupos_print_client_new.py')

        # Descarga desde soportereal.com (host único, ver LINUX_UPDATE_URLS). Si no
        # responde o no entrega un .py válido de la versión anunciada, NO se reemplaza
        # (se reintenta en el próximo chequeo). La lista admite más URLs si hiciera falta.
        content = None
        file_size = 0
        for url in LINUX_UPDATE_URLS:
            try:
                self._log(f"Auto-update Linux: descargando {url} ...")
                urllib.request.urlretrieve(url, tmp_path)
            except Exception as e:
                self._log(f"Auto-update: falló {url} ({e}); probando siguiente", 'error')
                self._safe_remove(tmp_path)
                continue

            file_size = os.path.getsize(tmp_path)
            with open(tmp_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

            # Validar: tamaño razonable + que sea el script (no un HTML de error)
            if (file_size < 50_000 or 'VERSION' not in content
                    or 'def main' not in content
                    or '<html' in content[:500].lower()):
                self._log(f"Auto-update: descarga inválida desde {url} ({file_size} bytes); probando siguiente", 'error')
                self._safe_remove(tmp_path)
                content = None
                continue

            # Confirmar que la versión bajada coincide con la anunciada (anti-loop)
            downloaded_ver = ''
            for ln in content.splitlines():
                s = ln.strip()
                if s.startswith('VERSION') and '=' in s:
                    seg = s.split('=', 1)[1]
                    for q in ('"', "'"):
                        if q in seg:
                            parts = seg.split(q)
                            if len(parts) >= 2:
                                downloaded_ver = parts[1]
                            break
                    break
            if downloaded_ver != new_version:
                self._log(f"Auto-update: versión bajada '{downloaded_ver}' != anunciada "
                          f"'{new_version}' desde {url}; probando siguiente", 'error')
                self._safe_remove(tmp_path)
                content = None
                continue

            # Descarga válida → dejar de rotar
            break

        if not content:
            self._log("Auto-update Linux: ninguna URL entregó un .py válido; abortando", 'error')
            return

        try:
            self._log(f"Descargado OK ({file_size:,} bytes). Actualizando a v{new_version} y reiniciando...")
            os.replace(tmp_path, script_path)  # atómico (mismo filesystem)

            # Relanzador desacoplado: espera 2s a que este proceso muera (libera el
            # icono de bandeja y los sockets) y ejecuta el script actualizado con
            # el mismo intérprete y argumentos. close_fds + nueva sesión = no hereda
            # descriptores ni queda atado a este proceso.
            relaunch = (
                "import os, sys, time; time.sleep(2); "
                f"os.execv({sys.executable!r}, "
                f"[{sys.executable!r}, {script_path!r}] + {list(sys.argv[1:])!r})"
            )
            subprocess.Popen(
                [sys.executable, '-c', relaunch],
                cwd=target_dir,
                start_new_session=True,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os._exit(0)

        except Exception as e:
            self._log(f"Auto-update Linux error: {e}", 'error')
            self._safe_remove(tmp_path)

    @staticmethod
    def _safe_remove(path):
        try:
            os.remove(path)
        except OSError:
            pass

    def on_error(self, ws, error):
        self._log(f"WS Error: {error}", 'error')

    def on_close(self, ws, close_status_code, close_msg):
        self._set_status(False)
        self._log(f"Desconectado (code={close_status_code})")

    def _next_server(self):
        self.server_index = (self.server_index + 1) % len(self.servers)
        self.current_server = self.servers[self.server_index]

    def connect(self):
        # Linux: hilo de chequeo periódico de versión (cada UPDATE_CHECK_INTERVAL).
        if IS_LINUX:
            threading.Thread(target=self._periodic_update_check_loop, daemon=True).start()
        while self.running:
            try:
                self._log(f"Conectando a {self.current_server}...")
                self.ws = websocket.WebSocketApp(
                    self.current_server,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                )
                self.ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                self._log(f"Error: {e}", 'error')

            if self.running:
                if len(self.servers) > 1:
                    self._next_server()
                    self._log(f"Failover → {self.current_server} (en {self.reconnect_interval}s)")
                else:
                    self._log(f"Reconectando en {self.reconnect_interval}s...")
                time.sleep(self.reconnect_interval)

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()



# ═══════════════════════════════════════════════════════════════════════════
# Puerto local 127.0.0.1:9302 — imprimir SIN internet (#1778, FactuSuper)
# ═══════════════════════════════════════════════════════════════════════════
# La web arma el documento en el equipo y lo entrega acá con la MISMA forma que un trabajo
# de la nube ({queue, data base64}); sale por el mismo imprimir_trabajo(), así que la
# impresora, el corte, el cajón y la letra son los de esa cola, sin nada aparte.
#   GET  /ping   → {ok, app, version, puerto, colas:[{queue, empresa, impresora}]}
#   POST /print  {queue, data(base64) | text, empresa?, jobId?} → {ok, mensaje}
# jobId repetido NO vuelve a imprimir (el navegador reintenta si no le llegó la respuesta).
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse


class _ServidorLocal(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    # Linux: sin reuse, al reiniciar la app el puerto queda tomado ~60 s por conexiones viejas
    # (TIME_WAIT). Windows: con reuse OTRO proceso podría abrir el mismo puerto encima.
    allow_reuse_address = not IS_WINDOWS


def origen_permitido(origen, extra=()):
    """¿Esta página puede mandar a imprimir? Sin Origin = un programa del propio equipo
    (curl, pruebas): se acepta, ya está adentro de la máquina."""
    if not origen:
        return True
    try:
        host = (urlparse(origen).hostname or '').lower()
    except Exception:
        return False
    if host in ('127.0.0.1', 'localhost'):
        return True
    for d in tuple(PUERTO_LOCAL_DOMINIOS) + tuple(extra or ()):
        d = str(d).lower().strip().lstrip('.')
        if d and (host == d or host.endswith('.' + d)):
            return True
    return False


class PuertoLocal:
    def __init__(self, obtener_cliente, config, on_log=None):
        self._cliente = obtener_cliente          # el cliente se recrea al reconectar
        self._config = config
        self._on_log = on_log
        self._servidor = None
        self._hechos = deque(maxlen=500)         # jobId ya impresos
        self._hechos_lock = threading.Lock()

    def _log(self, msg, level='info'):
        getattr(log, level)(msg)
        if self._on_log:
            self._on_log(f"{datetime.now().strftime('%H:%M:%S')} {msg}")

    def iniciar(self):
        dueno = self
        extra = self._config.get('puertoLocalOrigenes', []) or []

        class Handler(BaseHTTPRequestHandler):
            server_version = 'FactuPOSPrint/' + VERSION

            def log_message(self, *a):
                pass

            def _origen(self):
                return self.headers.get('Origin', '')

            def _cors(self):
                o = self._origen()
                if o and origen_permitido(o, extra):
                    self.send_header('Access-Control-Allow-Origin', o)
                    self.send_header('Vary', 'Origin')
                    self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                    self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                    # Chrome: una página de internet que llama a 127.0.0.1 pide este permiso.
                    self.send_header('Access-Control-Allow-Private-Network', 'true')
                    self.send_header('Access-Control-Max-Age', '600')

            def _json(self, obj, status=200):
                cuerpo = json.dumps(obj, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(cuerpo)))
                self._cors()
                self.end_headers()
                try:
                    self.wfile.write(cuerpo)
                except Exception:
                    pass

            def _rechazar_origen(self):
                if origen_permitido(self._origen(), extra):
                    return False
                dueno._log(f"Puerto local: pedido rechazado de {self._origen()}", 'warning')
                self._json({'ok': False, 'mensaje': 'Origen no permitido'}, 403)
                return True

            def do_OPTIONS(self):
                self.send_response(204 if origen_permitido(self._origen(), extra) else 403)
                self._cors()
                self.send_header('Content-Length', '0')
                self.end_headers()

            def do_GET(self):
                if self._rechazar_origen():
                    return
                if self.path.split('?')[0] != '/ping':
                    return self._json({'ok': False, 'mensaje': 'Ruta no encontrada'}, 404)
                c = dueno._cliente()
                colas = [{'queue': p.get('queueCode', ''), 'empresa': p.get('empresa', ''),
                          'impresora': p.get('windowsPrinter', p.get('printer', ''))}
                         for p in (c.printers if c else [])]
                self._json({'ok': True, 'app': 'FactuPOS Print', 'version': VERSION,
                            'puerto': PUERTO_LOCAL, 'nube': bool(c and c.connected), 'colas': colas})

            def do_POST(self):
                if self._rechazar_origen():
                    return
                if self.path.split('?')[0] != '/print':
                    return self._json({'ok': False, 'mensaje': 'Ruta no encontrada'}, 404)
                try:
                    largo = int(self.headers.get('Content-Length', 0) or 0)
                except ValueError:
                    largo = -1
                if largo <= 0 or largo > PUERTO_LOCAL_MAX_BYTES:
                    return self._json({'ok': False, 'mensaje': 'Tamaño de trabajo no válido'}, 413)
                try:
                    cuerpo = json.loads(self.rfile.read(largo).decode('utf-8'))
                    if not isinstance(cuerpo, dict):
                        raise ValueError('se esperaba un objeto')
                except Exception as e:
                    return self._json({'ok': False, 'mensaje': f'JSON inválido: {e}'}, 400)
                self._json(*dueno.imprimir(cuerpo))

        try:
            self._servidor = _ServidorLocal(('127.0.0.1', PUERTO_LOCAL), Handler)
        except OSError as e:
            # Otra copia de la app ya lo tiene, o algo más usa el puerto: la app sigue
            # imprimiendo por la nube igual.
            self._log(f"Puerto local 127.0.0.1:{PUERTO_LOCAL} no disponible ({e}) — sin impresión sin internet", 'warning')
            return False
        threading.Thread(target=self._servidor.serve_forever, daemon=True).start()
        self._log(f"Puerto local 127.0.0.1:{PUERTO_LOCAL} escuchando (impresión sin internet)")
        return True

    def imprimir(self, cuerpo):
        """→ (respuesta, status http)"""
        queue = str(cuerpo.get('queue', '')).strip()
        empresa = str(cuerpo.get('empresa', '') or '').strip()
        job_id = str(cuerpo.get('jobId', '') or '').strip()[:80]
        if not queue:
            return {'ok': False, 'mensaje': 'Falta la cola (queue)'}, 400
        data = cuerpo.get('data', '')
        if not data and cuerpo.get('text'):
            # Texto: en latin-1, que es como lo lee el resto del camino (plain_to_escp / spooler
            # decodifican latin-1) — igual que un trabajo de la nube. Lo que no entre, "?".
            data = base64.b64encode(str(cuerpo['text']).encode('latin-1', errors='replace')).decode('ascii')
        if not data:
            return {'ok': False, 'mensaje': 'Falta el documento (data o text)'}, 400
        cliente = self._cliente()
        if not cliente:
            return {'ok': False, 'mensaje': 'La app todavía está arrancando'}, 503
        if not cliente.buscar_cola(queue, empresa):
            return {'ok': False, 'mensaje': f'La cola {queue} no está configurada en este equipo'}, 404
        if job_id:
            with self._hechos_lock:
                if job_id in self._hechos:
                    return {'ok': True, 'duplicado': True, 'mensaje': 'Ya se había impreso'}, 200
        id_log = job_id or f"local-{int(time.time() * 1000)}"
        cliente._log(f"Job {id_log[:12]} recibido por el PUERTO LOCAL → cola {queue}")
        ok, msg = cliente.imprimir_trabajo(id_log, queue, data, empresa)
        if ok and job_id:
            with self._hechos_lock:
                self._hechos.append(job_id)
        return {'ok': bool(ok), 'mensaje': msg}, (200 if ok else 500)

    def detener(self):
        if self._servidor:
            try:
                self._servidor.shutdown()
                self._servidor.server_close()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════
# GUI - Pantalla de Configuración (Setup)
# ═══════════════════════════════════════════════════════════════════════════
class SetupWindow:
    """Ventana para configurar servidor, ID de cliente e impresoras."""

    def __init__(self, config, on_done):
        self.config = config
        self.on_done = on_done
        self.win = tk.Tk()
        self.win.title(f"FactuPOS Print v{VERSION} — Configuración")
        self.win.geometry("920x740")
        self.win.minsize(800, 640)
        self.win.resizable(True, True)

        # Centrar ventana
        self.win.update_idletasks()
        x = (self.win.winfo_screenwidth() // 2) - 460
        y = (self.win.winfo_screenheight() // 2) - 370
        self.win.geometry(f"+{x}+{y}")

        self._build_ui()

    def _build_ui(self):
        apply_navy_theme(self.win)

        # --- Header navy con versión grande ---
        header = tk.Frame(self.win, bg=NAVY, height=60)
        header.pack(fill='x')
        header.pack_propagate(False)
        tk.Label(header, text="FactuPOS Print", font=("Segoe UI", 15, "bold"),
                 fg='white', bg=NAVY).pack(side='left', padx=14)
        tk.Label(header, text=f"v{VERSION}", font=("Segoe UI", 22, "bold"),
                 fg=HEADTXT, bg=NAVY).pack(side='right', padx=16)

        main = ttk.Frame(self.win, padding=15)
        main.pack(fill='both', expand=True)

        # --- Conexión ---
        conn_frame = ttk.LabelFrame(main, text="Conexión al Servidor", padding=10)
        conn_frame.pack(fill='x', pady=(0, 10))

        ttk.Label(conn_frame, text="Servidor principal:").grid(row=0, column=0, sticky='w', pady=2)
        self.entry_server1 = ttk.Entry(conn_frame, width=45)
        self.entry_server1.grid(row=0, column=1, padx=(5, 0), pady=2, sticky='ew')
        self.entry_server1.insert(0, self.config['servers'][0] if self.config['servers'] else 'ws://print.invefacon.com:9300')

        ttk.Label(conn_frame, text="Servidor failover:").grid(row=1, column=0, sticky='w', pady=2)
        self.entry_server2 = ttk.Entry(conn_frame, width=45)
        self.entry_server2.grid(row=1, column=1, padx=(5, 0), pady=2, sticky='ew')
        s2 = self.config['servers'][1] if len(self.config['servers']) > 1 else 'ws://print.invefacon.net:9300'
        self.entry_server2.insert(0, s2)

        ttk.Label(conn_frame, text="ID del cliente:").grid(row=2, column=0, sticky='w', pady=2)
        self.entry_client_id = ttk.Entry(conn_frame, width=45)
        self.entry_client_id.grid(row=2, column=1, padx=(5, 0), pady=2, sticky='ew')
        client_id = self.config.get('clientId', '') or socket.gethostname()
        self.entry_client_id.insert(0, client_id)

        conn_frame.columnconfigure(1, weight=1)

        # --- Impresoras ---
        prn_frame = ttk.LabelFrame(main, text="Impresoras", padding=10)
        prn_frame.pack(fill='both', expand=True, pady=(0, 10))

        # Instrucciones
        ttk.Label(prn_frame, text="Seleccione las impresoras y asigne un código de cola a cada una:",
                  font=("Segoe UI", 9)).pack(anchor='w')

        # Botón refrescar
        btn_frame = ttk.Frame(prn_frame)
        btn_frame.pack(fill='x', pady=(5, 5))
        ttk.Button(btn_frame, text="Refrescar impresoras", command=self._refresh_printers).pack(side='left')
        ttk.Button(btn_frame, text="Probar impresora (cajón + corte)",
                   command=self._test_printer).pack(side='left', padx=(6, 0))
        self.lbl_count = ttk.Label(btn_frame, text="")
        self.lbl_count.pack(side='left', padx=10)

        # Tabla
        table_frame = ttk.Frame(prn_frame)
        table_frame.pack(fill='both', expand=True)

        cols = ('sel', 'printer', 'queue_code', 'empresa', 'description', 'cut', 'drawer')
        self.tree = ttk.Treeview(table_frame, columns=cols, show='headings', height=8)
        self.tree.heading('sel', text='✓')
        self.tree.heading('printer', text='Impresora Windows')
        self.tree.heading('queue_code', text='Código')
        self.tree.heading('empresa', text='Empresa BD')
        self.tree.heading('description', text='Descripción')
        self.tree.heading('cut', text='Corte')
        self.tree.heading('drawer', text='Cajón')
        self.tree.column('sel', width=30, anchor='center', stretch=False)
        self.tree.column('printer', width=180)
        self.tree.column('queue_code', width=70)
        self.tree.column('empresa', width=90)
        self.tree.column('description', width=120)
        self.tree.column('cut', width=45, anchor='center')
        self.tree.column('drawer', width=45, anchor='center')

        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        self.tree.bind('<Double-1>', self._on_double_click)
        self.tree.bind('<Button-1>', self._on_click)

        # Edit row frame
        edit_frame = ttk.Frame(prn_frame)
        edit_frame.pack(fill='x', pady=(5, 0))

        ttk.Label(edit_frame, text="Código:").pack(side='left')
        self.entry_code = ttk.Entry(edit_frame, width=8)
        self.entry_code.pack(side='left', padx=(3, 8))

        ttk.Label(edit_frame, text="Empresa:").pack(side='left')
        self.entry_empresa = ttk.Entry(edit_frame, width=12)
        self.entry_empresa.pack(side='left', padx=(3, 8))

        ttk.Label(edit_frame, text="Desc:").pack(side='left')
        self.entry_desc = ttk.Entry(edit_frame, width=14)
        self.entry_desc.pack(side='left', padx=(3, 8))

        self.chk_cut_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(edit_frame, text="Corte", variable=self.chk_cut_var).pack(side='left', padx=(0, 5))

        self.chk_drawer_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(edit_frame, text="Cajón", variable=self.chk_drawer_var).pack(side='left', padx=(0, 8))

        ttk.Button(edit_frame, text="Aplicar", command=self._apply_edit).pack(side='left')

        # Cargar impresoras
        self._refresh_printers()

        # --- Botones ---
        btn_bar = ttk.Frame(main)
        btn_bar.pack(fill='x')

        ttk.Button(btn_bar, text="Guardar y Conectar", command=self._save_and_connect,
                   style='Accent.TButton').pack(side='right', padx=(5, 0))
        ttk.Button(btn_bar, text="Cancelar", command=self.win.destroy).pack(side='right')

        # Style
        style = ttk.Style()
        style.configure('Accent.TButton', font=("Segoe UI", 10, "bold"))

    def _test_printer(self):
        """Prueba la impresora seleccionada en la lista: abre el cajón monedero y corta el papel."""
        item = self.tree.focus()
        if not item:
            messagebox.showinfo("Probar impresora",
                                "Seleccione (haga clic en) una impresora de la lista primero.")
            return
        vals = self.tree.item(item, 'values')
        printer_name = vals[1] if len(vals) > 1 else ''
        if not printer_name:
            messagebox.showwarning("Probar impresora", "La fila seleccionada no tiene impresora.")
            return
        sel = ask_paper_width(self.win)
        if sel is None:
            return
        cols, font = sel
        try:
            data = build_test_ticket(printer_name, cols, font)
            ok, msg = print_raw(printer_name, data)
        except Exception as e:
            ok, msg = False, str(e)
        if ok:
            messagebox.showinfo("Probar impresora",
                                f"Prueba enviada a:\n{printer_name}\n\n"
                                "Debe abrirse el cajón y cortarse el papel.")
        else:
            messagebox.showerror("Probar impresora", f"No se pudo enviar la prueba:\n{msg}")

    def _refresh_printers(self):
        """Listar impresoras Windows y mostrar en la tabla."""
        self.tree.delete(*self.tree.get_children())

        try:
            printers, default_printer = list_printers()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudieron listar impresoras:\n{e}")
            return

        self.lbl_count.config(text=f"{len(printers)} impresora(s) encontrada(s)")

        # Mapeo existente por nombre de impresora
        existing = {}
        for p in self.config.get('printers', []):
            existing[p['windowsPrinter']] = p

        for name in printers:
            if name in existing:
                cfg = existing[name]
                sel = '✓'
                code = cfg.get('printerCode', '')
                empresa = cfg.get('empresa', '')
                desc = cfg.get('description', '')
                cut = '✓' if cfg.get('cutPaper', False) else ''
                drawer = '✓' if cfg.get('openDrawer', False) else ''
            else:
                sel = ''
                code = ''
                empresa = ''
                desc = ''
                cut = ''
                drawer = ''

            tag = 'selected' if sel else ''
            self.tree.insert('', 'end', values=(sel, name, code, empresa, desc, cut, drawer), tags=(tag,))

        self.tree.tag_configure('selected', background='#e0f2fe')

    def _on_click(self, event):
        """Toggle selección al hacer clic en la columna ✓."""
        region = self.tree.identify_region(event.x, event.y)
        if region != 'cell':
            return

        col = self.tree.identify_column(event.x)
        if col != '#1':  # Solo columna ✓
            return

        item = self.tree.identify_row(event.y)
        if not item:
            return

        vals = list(self.tree.item(item, 'values'))
        if vals[0] == '✓':
            vals[0] = ''
            self.tree.item(item, values=vals, tags=())
        else:
            vals[0] = '✓'
            self.tree.item(item, values=vals, tags=('selected',))

    def _on_double_click(self, event):
        """Al hacer doble clic, cargar fila en los campos de edición."""
        item = self.tree.focus()
        if not item:
            return
        vals = self.tree.item(item, 'values')
        self.entry_code.delete(0, 'end')
        self.entry_code.insert(0, vals[2])
        self.entry_empresa.delete(0, 'end')
        self.entry_empresa.insert(0, vals[3])
        self.entry_desc.delete(0, 'end')
        self.entry_desc.insert(0, vals[4])
        self.chk_cut_var.set(vals[5] == '✓')
        self.chk_drawer_var.set(vals[6] == '✓')

    def _apply_edit(self):
        """Aplicar código y descripción a la fila seleccionada."""
        item = self.tree.focus()
        if not item:
            messagebox.showwarning("Aviso", "Seleccione una impresora primero.")
            return

        vals = list(self.tree.item(item, 'values'))
        code = self.entry_code.get().strip()
        desc = self.entry_desc.get().strip()

        if code:
            empresa = self.entry_empresa.get().strip().lower()
            vals[0] = '✓'  # Auto-seleccionar
            vals[2] = code
            vals[3] = empresa
            vals[4] = desc
            vals[5] = '✓' if self.chk_cut_var.get() else ''
            vals[6] = '✓' if self.chk_drawer_var.get() else ''
            self.tree.item(item, values=vals, tags=('selected',))

    def _save_and_connect(self):
        """Guardar config y lanzar la ventana principal."""
        # Validar
        server1 = self.entry_server1.get().strip()
        if not server1:
            messagebox.showerror("Error", "Ingrese al menos un servidor.")
            return

        client_id = self.entry_client_id.get().strip()
        if not client_id:
            messagebox.showerror("Error", "Ingrese un ID de cliente.")
            return

        # Recopilar impresoras seleccionadas
        printers = []
        for item in self.tree.get_children():
            vals = self.tree.item(item, 'values')
            if vals[0] == '✓':
                code = vals[2].strip()
                if not code:
                    messagebox.showerror("Error", f"La impresora '{vals[1]}' está seleccionada pero no tiene código de cola.")
                    return
                printers.append({
                    "queueCode": code,
                    "printerCode": code.split(',')[-1] if ',' in code else code,
                    "windowsPrinter": vals[1],
                    "empresa": vals[3].strip().lower(),
                    "description": vals[4],
                    "cutPaper": vals[5] == '✓',
                    "openDrawer": vals[6] == '✓',
                })

        if not printers:
            messagebox.showerror("Error", "Seleccione al menos una impresora.")
            return

        # Construir config
        servers = [server1]
        server2 = self.entry_server2.get().strip()
        if server2:
            servers.append(server2)

        self.config['servers'] = servers
        self.config['clientId'] = client_id
        self.config['printers'] = printers

        # Guardar
        save_config(self.config)

        # Cerrar setup, lanzar main
        self.win.destroy()
        self.on_done(self.config)

    def run(self):
        self.win.mainloop()


# ═══════════════════════════════════════════════════════════════════════════
# GUI - Pantalla Principal (Monitor)
# ═══════════════════════════════════════════════════════════════════════════
class MainWindow:
    def __init__(self, config, arrancar_oculto=False):
        self.config = config
        self.arrancar_oculto = arrancar_oculto
        self.root = tk.Tk()
        self.root.title(f"FactuPOS Print v{VERSION}")
        # 1160 de ancho = la suma de las columnas de la tabla (1080) + la barra
        # de desplazamiento y los márgenes. Con los 880 de antes se cortaban
        # "Impresora" y "Modo/Opciones", que son justo las que uno mira para
        # saber por dónde sale cada cola.
        # Pero NUNCA más grande que la pantalla: muchas cajas son de 1366x768 y
        # una ventana de 800 de alto quedaría con los botones fuera del monitor,
        # sin forma de llegarles.
        ancho = min(1160, self.root.winfo_screenwidth() - 60)
        alto = min(800, self.root.winfo_screenheight() - 120)
        self.root.geometry(f"{ancho}x{alto}")
        self.root.minsize(min(900, ancho), min(620, alto))
        self.root.protocol("WM_DELETE_WINDOW", self._hide_to_tray)

        # Interceptar minimizar para ocultar a bandeja
        self.root.bind('<Unmap>', self._on_minimize)

        # Centrar
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - 440
        y = (self.root.winfo_screenheight() // 2) - 390
        self.root.geometry(f"+{x}+{y}")

        self._build_ui()

        # System tray
        self.tray_icon = None
        if HAS_TRAY:
            self._create_tray_icon()

        # Client
        self.client = PrintQueueClient(
            config,
            on_log=self._append_log,
            on_status=self._update_status,
        )

        # Start connection
        self.conn_thread = threading.Thread(target=self.client.connect, daemon=True)
        self.conn_thread.start()

        # Puerto local 127.0.0.1:9302: la web imprime directo cuando no hay internet (#1778).
        # Se le pasa CÓMO obtener el cliente, no el cliente: al reconectar se crea otro.
        self.puerto_local = PuertoLocal(lambda: self.client, config, on_log=self._append_log)
        self.puerto_local.iniciar()

        self._update_counters()

        # Arrancar oculto SOLO si lo pidieron con --hidden, que es lo que pasan el
        # autostart de Linux (autostart.sh) y el Run de Windows. Si el usuario la
        # abre del menú, tiene que VERLA.
        # Antes se ocultaba SIEMPRE y --hidden ni se leía: la abrías del menú, salía
        # 300 ms y se iba. Peor en GNOME, que sin la extensión de AppIndicator no
        # muestra la bandeja → la app quedaba inalcanzable (ni ventana ni icono).
        # Sigue condicionado a que HAYA bandeja: sin ella, ocultarse la dejaría
        # imposible de recuperar.
        if self.arrancar_oculto and HAS_TRAY and self.tray_icon:
            self.root.after(300, self.root.withdraw)

    def _build_ui(self):
        apply_navy_theme(self.root)

        # --- Header navy con versión en grande ---
        header = tk.Frame(self.root, bg=NAVY, height=60)
        header.pack(fill='x')
        header.pack_propagate(False)

        tk.Label(header, text="FactuPOS Print", font=("Segoe UI", 15, "bold"),
                 fg='white', bg=NAVY).pack(side='left', padx=(14, 6))

        tk.Label(header, text=f"v{VERSION}", font=("Segoe UI", 22, "bold"),
                 fg=HEADTXT, bg=NAVY).pack(side='right', padx=(8, 16))

        btn_config = tk.Button(header, text="⚙", font=("Segoe UI", 14), fg='white', bg=NAVY,
                               activebackground=NAVY_DARK, activeforeground='white',
                               bd=0, cursor='hand2', command=self._open_config)
        btn_config.pack(side='right', padx=4)

        tk.Label(header, text=f"ID: {self.config.get('clientId', '?')}",
                 font=("Segoe UI", 9), fg=HEADTXT, bg=NAVY).pack(side='right', padx=8)

        # --- Barra de estado ---
        status_bar = tk.Frame(self.root, bg=STRIP, height=26)
        status_bar.pack(fill='x')
        status_bar.pack_propagate(False)

        self.status_dot = tk.Label(status_bar, text="●", font=("Arial", 16), fg='#dc2626', bg=STRIP)
        self.status_dot.pack(side='left', padx=(12, 5))

        self.status_label = tk.Label(status_bar, text="Conectando...",
                                     font=("Segoe UI", 13), fg=NAVY, bg=STRIP)
        self.status_label.pack(side='left')

        # --- Impresoras ---
        prn_frame = ttk.LabelFrame(self.root, text="Impresoras Registradas", padding=8)
        prn_frame.pack(fill='both', expand=True, padx=10, pady=(10, 5))

        # Tabla
        table_frame = ttk.Frame(prn_frame)
        table_frame.pack(fill='both', expand=True)

        cols = ('code', 'empresa', 'printer', 'description', 'options')
        self.tree = ttk.Treeview(table_frame, columns=cols, show='headings',
                                 height=min(len(self.config.get('printers', [])), 10) or 4)
        self.tree.heading('code', text='Cola')
        self.tree.heading('empresa', text='Empresa BD')
        self.tree.heading('printer', text='Impresora')
        self.tree.heading('description', text='Descripción')
        self.tree.heading('options', text='Modo/Opciones')
        # Anchos pensados para que NO se corte lo que importa. Las dos que se
        # cortaban eran "Impresora" (ahora lleva el transporte adelante:
        # "Red · 192.168.1.50:9100") y "Modo/Opciones", que puede juntar
        # RAW + Térmica + Letra B + Corte + Cajón.
        # `minwidth` evita que al angostar la ventana queden en un hilo, y
        # `stretch` reparte el espacio sobrante entre las dos que más lo usan.
        self.tree.column('code', width=70, minwidth=60, stretch=False)
        self.tree.column('empresa', width=140, minwidth=100, stretch=False)
        self.tree.column('printer', width=300, minwidth=200, stretch=True)
        self.tree.column('description', width=220, minwidth=140, stretch=False)
        self.tree.column('options', width=350, minwidth=200, stretch=True)
        self.tree.pack(side='left', fill='both', expand=True)

        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')

        self._reload_printer_table()

        # Botones +/−
        btn_prn = ttk.Frame(prn_frame)
        btn_prn.pack(fill='x', pady=(5, 0))

        ttk.Button(btn_prn, text="+ Agregar", command=self._add_printer).pack(side='left', padx=(0, 5))
        ttk.Button(btn_prn, text="Editar", command=self._edit_printer).pack(side='left', padx=(0, 5))
        ttk.Button(btn_prn, text="− Quitar", command=self._remove_printer).pack(side='left')
        ttk.Button(btn_prn, text="Probar (cajón + corte)", command=self._test_printer).pack(side='left', padx=(8, 0))
        ttk.Button(btn_prn, text="Limpiar cola", command=self._purge_printer).pack(side='left', padx=(8, 0))

        # NOTA: el auto-inicio (oculto en la bandeja) lo configura el INSTALADOR de
        # Windows (Inno Setup: HKLM\...\Run con --hidden). Por eso ya no hay
        # checkboxes "Auto-ocultar" / "Iniciar con el sistema" en la interfaz.

        # --- Counters ---
        counter_frame = ttk.Frame(self.root, padding=(10, 5))
        counter_frame.pack(fill='x')

        self.lbl_ok = tk.Label(counter_frame, text="Impresos: 0", font=("Segoe UI", 13, "bold"),
                               fg='#16a34a', bg=BODY)
        self.lbl_ok.pack(side='left', padx=(0, 20))

        self.lbl_err = tk.Label(counter_frame, text="Errores: 0", font=("Segoe UI", 13, "bold"),
                                fg='#dc2626', bg=BODY)
        self.lbl_err.pack(side='left')

        self.lbl_server = tk.Label(counter_frame, text="", font=("Segoe UI", 10), fg='#5b7596', bg=BODY)
        self.lbl_server.pack(side='right')

        # --- Log ---
        log_frame = ttk.LabelFrame(self.root, text="Log", padding=8)
        log_frame.pack(fill='x', padx=10, pady=(5, 10))

        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap='word', font=("Consolas", 9), state='disabled',
            bg='#1e1e1e', fg='#d4d4d4', insertbackground='white', height=6,
        )
        self.log_text.pack(fill='x')

        # Botón copiar log
        log_btn_frame = ttk.Frame(log_frame)
        log_btn_frame.pack(fill='x', pady=(5, 0))
        ttk.Button(log_btn_frame, text="Copiar Log", command=self._copy_log).pack(side='right')
        ttk.Button(log_btn_frame, text="Buscar actualización", command=self._check_update).pack(side='right', padx=(0, 5))

        # Tags para colores en log
        self.log_text.tag_configure('error', foreground='#fca5a5')
        self.log_text.tag_configure('ok', foreground='#86efac')

    def _append_log(self, msg):
        def _do():
            self.log_text.config(state='normal')
            tag = 'error' if 'ERROR' in msg or 'error' in msg.lower() else ('ok' if ' OK ' in msg else '')
            self.log_text.insert('end', msg + '\n', tag or ())
            self.log_text.see('end')
            self.log_text.config(state='disabled')
        self.root.after(0, _do)

    def _copy_log(self):
        """Copiar todo el log al portapapeles."""
        self.log_text.config(state='normal')
        text = self.log_text.get('1.0', 'end').strip()
        self.log_text.config(state='disabled')
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        messagebox.showinfo("Copiado", "Log copiado al portapapeles.", parent=self.root)

    def _check_update(self):
        """Botón: forzar chequeo de actualización."""
        if getattr(self, 'client', None):
            self.client.manual_check_update()

    def _update_status(self, connected):
        def _do():
            if connected:
                self.status_dot.config(fg='#16a34a')
                self.status_label.config(text=f"Conectado — {self.client.current_server}")
            else:
                self.status_dot.config(fg='#dc2626')
                self.status_label.config(text="Desconectado — reintentando...")
        self.root.after(0, _do)

    def _update_counters(self):
        if hasattr(self, 'client'):
            self.lbl_ok.config(text=f"Impresos: {self.client.jobs_ok}")
            self.lbl_err.config(text=f"Errores: {self.client.jobs_err}")
            if self.client.connected:
                self.lbl_server.config(text=self.client.current_server)
        self.root.after(2000, self._update_counters)

    def _reload_printer_table(self):
        """Recargar tabla de impresoras desde config."""
        self.tree.delete(*self.tree.get_children())
        for indice, p in enumerate(self.config.get('printers', [])):
            mode = p.get('printMode', 'raw').upper()
            opts = [mode]
            if mode == 'RAW':
                if p.get('isThermal', False):
                    opts.append('Térmica')
                ef = str(p.get('escposFont', '')).upper()
                if ef in ('A', 'B'):
                    opts.append('Letra ' + ef)
                if p.get('virtualPort', ''):
                    opts.append(p['virtualPort'])
                if p.get('cutPaper', False):
                    opts.append('Corte')
                if p.get('openDrawer', False):
                    opts.append('Cajón')
            else:
                font = p.get('spoolerFont', 'Lucida Console')
                size = p.get('spoolerFontSize', 10)
                opts.append(f"{font} {size}pt")
            # Igual que en Android: la columna de impresora dice POR DÓNDE sale,
            # no solo el nombre. Con varias impresoras en la misma cola, saber
            # si una es de red o del sistema es lo primero que uno necesita.
            rotulo = {'ip': 'Red', 'serial': 'Serie', 'bluetooth': 'Bluetooth',
                      'virtual': 'Directo', 'cups': 'Sistema'}.get(
                          str(p.get('transport', '') or '').lower(), '')
            nombre = p.get('windowsPrinter', p.get('printer', '(sin nombre)'))
            # El id de la fila es la POSICION en config['printers']. Antes cada
            # boton (Editar/Probar/Quitar) volvia a buscar el perfil comparando
            # los textos de la fila; bastaba con cambiar como se muestra una
            # columna para que dejaran de encontrarlo. Con el indice en el id,
            # lo que se ve y lo que se edita ya no pueden desincronizarse.
            self.tree.insert('', 'end', iid=str(indice), values=(
                p.get('printerCode', p.get('queueCode', '')),
                p.get('empresa', ''),
                f"{rotulo} · {nombre}" if rotulo else nombre,
                p.get('description', ''),
                ', '.join(opts),
            ))

    def _perfil_seleccionado(self, accion="continuar"):
        """(indice, perfil) de la fila marcada, o (-1, None) si no hay ninguna."""
        sel = self.tree.focus()
        if not sel:
            messagebox.showwarning("Aviso", f"Seleccione una impresora para {accion}.")
            return -1, None
        try:
            indice = int(sel)
            return indice, self.config.get('printers', [])[indice]
        except (ValueError, IndexError):
            messagebox.showerror("Error", "No se encontró la impresora en la configuración.")
            return -1, None

    # Etiquetas visibles de cada transporte. El usuario NO ve la palabra
    # "transport" ni los codigos internos: ve "Red (IP)" y elige.
    TRANSPORTES = [
        ('cups',      'Impresora del sistema (CUPS)'),
        ('ip',        'Red (IP)'),
        ('serial',    'Serie / USB-Serie'),
        ('bluetooth', 'Bluetooth'),
        ('virtual',   'Dispositivo directo (/dev/usb/lp0)'),
    ]

    def _add_printer(self):
        """Agregar una impresora."""
        self._dialogo_impresora(None, -1)

    def _edit_printer(self):
        """Editar la impresora seleccionada."""
        indice, perfil = self._perfil_seleccionado("editar")
        if perfil is None:
            return
        self._dialogo_impresora(perfil, indice)

    def _dialogo_impresora(self, perfil, indice):
        """Formulario de impresora — MISMO diálogo para agregar y editar.

        Antes eran dos métodos calcados de ~170 líneas cada uno; cualquier campo
        nuevo había que agregarlo dos veces y era cuestión de tiempo que se
        desincronizaran. Ahora `perfil=None` significa agregar.

        Sigue el modelo de FactuPOS Print de Android: se elige el TRANSPORTE y
        los campos de abajo cambian solos según lo que ese transporte necesita
        (IP pide dirección y puerto, Serie pide dispositivo y velocidad,
        Bluetooth pide el equipo emparejado).
        """
        editando = perfil is not None
        perfil = perfil or {}

        dlg = tk.Toplevel(self.root)
        dlg.title("Editar Impresora" if editando else "Agregar Impresora")
        # Igual que la ventana principal: cómodo, pero nunca más alto que la
        # pantalla o los botones Guardar/Cancelar quedan fuera del monitor.
        dlg.geometry(f"700x{min(760, self.root.winfo_screenheight() - 120)}")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.configure(bg=BODY)
        dlg.update_idletasks()
        dlg.geometry(f"+{self.root.winfo_x() + 80}+{self.root.winfo_y() + 60}")

        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)

        # ---------------- Transporte ----------------
        etiquetas = [e for _, e in self.TRANSPORTES]
        codigos = [c for c, _ in self.TRANSPORTES]
        actual = str(perfil.get('transport', 'cups') or 'cups').lower()
        if actual not in codigos:
            actual = 'cups'

        ttk.Label(frame, text="Conexión:").grid(row=0, column=0, sticky='w', pady=5)
        combo_transporte = ttk.Combobox(frame, values=etiquetas, width=35, state='readonly')
        combo_transporte.grid(row=0, column=1, padx=(5, 0), pady=5, sticky='ew')
        combo_transporte.current(codigos.index(actual))

        # ---------------- Panel que cambia según el transporte ----------------
        destino = ttk.LabelFrame(frame, text="Destino", padding=8)
        destino.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(5, 0))
        destino.columnconfigure(1, weight=1)

        # -- CUPS
        f_cups = ttk.Frame(destino)
        ttk.Label(f_cups, text="Impresora:").grid(row=0, column=0, sticky='w')
        try:
            lista_cups, _ = list_printers()
        except Exception:
            lista_cups = []
        combo_cups = ttk.Combobox(f_cups, values=lista_cups, width=32)
        combo_cups.grid(row=0, column=1, padx=(5, 0), sticky='ew')
        f_cups.columnconfigure(1, weight=1)

        # -- IP
        f_ip = ttk.Frame(destino)
        ttk.Label(f_ip, text="Dirección IP:").grid(row=0, column=0, sticky='w')
        entry_host = ttk.Entry(f_ip, width=22)
        entry_host.grid(row=0, column=1, padx=(5, 0), sticky='w')
        ttk.Label(f_ip, text="Puerto:").grid(row=1, column=0, sticky='w', pady=(5, 0))
        entry_puerto = ttk.Entry(f_ip, width=8)
        entry_puerto.grid(row=1, column=1, padx=(5, 0), sticky='w', pady=(5, 0))
        lbl_prueba = ttk.Label(f_ip, text="", font=("Segoe UI", 8))
        lbl_prueba.grid(row=3, column=0, columnspan=2, sticky='w', pady=(4, 0))

        def _probar_conexion():
            lbl_prueba.config(text="Probando…", foreground='gray')
            dlg.update_idletasks()
            ok, msg = probar_ip(entry_host.get(), entry_puerto.get())
            lbl_prueba.config(text=msg, foreground=('green' if ok else 'red'))

        ttk.Button(f_ip, text="Probar conexión", command=_probar_conexion)\
            .grid(row=2, column=1, sticky='w', padx=(5, 0), pady=(6, 0))
        ttk.Label(f_ip, text="La mayoría de impresoras de red usan el puerto 9100",
                  font=("Segoe UI", 8), foreground='gray')\
            .grid(row=4, column=0, columnspan=2, sticky='w')

        # -- Serie
        f_serial = ttk.Frame(destino)
        ttk.Label(f_serial, text="Dispositivo:").grid(row=0, column=0, sticky='w')
        combo_serial = ttk.Combobox(f_serial, values=listar_seriales(), width=32)
        combo_serial.grid(row=0, column=1, padx=(5, 0), sticky='ew')
        ttk.Label(f_serial, text="Velocidad:").grid(row=1, column=0, sticky='w', pady=(5, 0))
        combo_baud = ttk.Combobox(f_serial, values=BAUDIOS_COMUNES, width=10, state='readonly')
        combo_baud.grid(row=1, column=1, padx=(5, 0), sticky='w', pady=(5, 0))
        ttk.Label(f_serial, text="Si sale texto ilegible, casi siempre es la velocidad",
                  font=("Segoe UI", 8), foreground='gray')\
            .grid(row=2, column=0, columnspan=2, sticky='w', pady=(4, 0))
        f_serial.columnconfigure(1, weight=1)

        # -- Bluetooth
        f_bt = ttk.Frame(destino)
        ttk.Label(f_bt, text="Equipo:").grid(row=0, column=0, sticky='w')
        combo_bt = ttk.Combobox(f_bt, values=listar_bluetooth(), width=32)
        combo_bt.grid(row=0, column=1, padx=(5, 0), sticky='ew')
        ttk.Label(f_bt, text="Solo aparecen los equipos ya emparejados en el sistema",
                  font=("Segoe UI", 8), foreground='gray')\
            .grid(row=1, column=0, columnspan=2, sticky='w', pady=(4, 0))
        f_bt.columnconfigure(1, weight=1)

        # -- Dispositivo directo
        f_virtual = ttk.Frame(destino)
        ttk.Label(f_virtual, text="Ruta:").grid(row=0, column=0, sticky='w')
        entry_virtual = ttk.Entry(f_virtual, width=32)
        entry_virtual.grid(row=0, column=1, padx=(5, 0), sticky='ew')
        ttk.Label(f_virtual, text="Ej: /dev/usb/lp0",
                  font=("Segoe UI", 8), foreground='gray')\
            .grid(row=1, column=0, columnspan=2, sticky='w', pady=(4, 0))
        f_virtual.columnconfigure(1, weight=1)

        paneles = {'cups': f_cups, 'ip': f_ip, 'serial': f_serial,
                   'bluetooth': f_bt, 'virtual': f_virtual}

        # ---------------- Campos comunes ----------------
        ttk.Label(frame, text="Código de cola:").grid(row=2, column=0, sticky='w', pady=5)
        entry_code = ttk.Entry(frame, width=37)
        entry_code.grid(row=2, column=1, padx=(5, 0), pady=5, sticky='ew')
        ttk.Label(frame, text="Ej: 301", font=("Segoe UI", 8), foreground='gray')\
            .grid(row=3, column=1, sticky='w', padx=(5, 0))

        ttk.Label(frame, text="Empresa (BD):").grid(row=4, column=0, sticky='w', pady=5)
        entry_empresa = ttk.Entry(frame, width=37)
        entry_empresa.grid(row=4, column=1, padx=(5, 0), pady=5, sticky='ew')
        ttk.Label(frame, text="Nombre de la base de datos (ej: invefacon, fiorella)",
                  font=("Segoe UI", 8), foreground='gray')\
            .grid(row=5, column=1, sticky='w', padx=(5, 0))

        ttk.Label(frame, text="Descripción:").grid(row=6, column=0, sticky='w', pady=5)
        entry_desc = ttk.Entry(frame, width=37)
        entry_desc.grid(row=6, column=1, padx=(5, 0), pady=5, sticky='ew')

        # ---------------- Modo ----------------
        ttk.Label(frame, text="Modo:").grid(row=7, column=0, sticky='w', pady=5)
        var_mode = tk.StringVar(value=perfil.get('printMode', 'raw'))
        mode_frame = ttk.Frame(frame)
        mode_frame.grid(row=7, column=1, sticky='w', padx=(5, 0), pady=5)
        rb_raw = ttk.Radiobutton(mode_frame, text="POS (RAW)", variable=var_mode,
                                 value='raw', command=lambda: _pintar())
        rb_raw.pack(side='left', padx=(0, 15))
        rb_spool = ttk.Radiobutton(mode_frame, text="Spooler (Cola SO)", variable=var_mode,
                                   value='spooler', command=lambda: _pintar())
        rb_spool.pack(side='left')

        pos_frame = ttk.LabelFrame(frame, text="Opciones POS", padding=5)
        pos_frame.grid(row=8, column=0, columnspan=2, sticky='ew', pady=(5, 0))
        var_cut = tk.BooleanVar(value=perfil.get('cutPaper', True))
        var_drawer = tk.BooleanVar(value=perfil.get('openDrawer', False))
        var_thermal = tk.BooleanVar(value=perfil.get('isThermal', False))
        ttk.Checkbutton(pos_frame, text="Cortar papel", variable=var_cut)\
            .grid(row=0, column=0, sticky='w')
        ttk.Checkbutton(pos_frame, text="Abrir cajón", variable=var_drawer)\
            .grid(row=0, column=1, sticky='w', padx=(10, 0))
        ttk.Checkbutton(pos_frame, text="Es térmica (envío lento)", variable=var_thermal)\
            .grid(row=1, column=0, columnspan=2, sticky='w')
        ttk.Label(pos_frame, text="Tipo de letra (Epson):")\
            .grid(row=2, column=0, sticky='w', pady=(5, 0))
        combo_escfont = ttk.Combobox(pos_frame, values=['A (normal)', 'B (condensada)'],
                                     width=15, state='readonly')
        combo_escfont.grid(row=2, column=1, sticky='w', padx=(5, 0), pady=(5, 0))
        combo_escfont.set('B (condensada)'
                          if str(perfil.get('escposFont', 'A')).upper() == 'B'
                          else 'A (normal)')

        spool_frame = ttk.LabelFrame(frame, text="Opciones Spooler", padding=5)
        spool_frame.grid(row=9, column=0, columnspan=2, sticky='ew', pady=(5, 0))
        ttk.Label(spool_frame, text="Fuente:").grid(row=0, column=0, sticky='w')
        combo_font = ttk.Combobox(spool_frame, values=[
            "Lucida Console", "Courier New", "Consolas", "Terminal",
            "Draft 10cpi", "Draft 12cpi", "Draft 15cpi", "Draft 16cpi",
            "Draft 17cpi", "Draft 20cpi",
            "Roman 10cpi", "Roman 12cpi", "Roman 15cpi", "Roman 16cpi",
            "Roman 17cpi", "Roman 20cpi"], width=20)
        combo_font.grid(row=0, column=1, padx=(5, 0), sticky='w')
        combo_font.set(perfil.get('spoolerFont', 'Lucida Console'))
        ttk.Label(spool_frame, text="Tamaño:").grid(row=1, column=0, sticky='w', pady=(5, 0))
        combo_fsize = ttk.Combobox(
            spool_frame, values=["7", "7.5", "8", "8.5", "9", "9.5", "10", "11", "12", "14"],
            width=8, state='readonly')
        combo_fsize.grid(row=1, column=1, padx=(5, 0), sticky='w', pady=(5, 0))
        combo_fsize.set(str(perfil.get('spoolerFontSize', 10)))

        aviso_modo = ttk.Label(frame, text="", font=("Segoe UI", 8), foreground='gray')
        aviso_modo.grid(row=10, column=0, columnspan=2, sticky='w')

        def _transporte_actual():
            return codigos[etiquetas.index(combo_transporte.get())]

        def _pintar(*_):
            """Mostrar solo lo que aplica al transporte y modo elegidos."""
            t = _transporte_actual()
            for cod, panel in paneles.items():
                if cod == t:
                    panel.grid(row=0, column=0, columnspan=2, sticky='ew')
                else:
                    panel.grid_remove()

            # El Spooler es la cola del sistema operativo: solo existe para
            # impresoras instaladas en CUPS. Una impresora de red, serie o
            # Bluetooth se maneja mandando bytes directo, no hay cola del SO
            # donde encolar — por eso ahi se fuerza POS y se explica.
            if t == 'cups':
                rb_spool.state(['!disabled'])
                aviso_modo.config(text="")
            else:
                if var_mode.get() != 'raw':
                    var_mode.set('raw')
                rb_spool.state(['disabled'])
                aviso_modo.config(
                    text="Con esta conexión los datos van directo a la impresora, "
                         "sin pasar por la cola del sistema.")

            if var_mode.get() == 'raw':
                pos_frame.grid()
                spool_frame.grid_remove()
            else:
                pos_frame.grid_remove()
                spool_frame.grid()

        combo_transporte.bind('<<ComboboxSelected>>', _pintar)

        # ---------------- Precargar valores ----------------
        direccion = str(perfil.get('address', '') or '')
        nombre_previo = perfil.get('windowsPrinter', perfil.get('printer', ''))
        if actual == 'cups':
            if nombre_previo in lista_cups:
                combo_cups.set(nombre_previo)
            elif nombre_previo:
                combo_cups.set(nombre_previo)
            elif lista_cups:
                combo_cups.current(0)
        elif actual == 'ip':
            entry_host.insert(0, str(perfil.get('host', direccion)))
            entry_puerto.insert(0, str(perfil.get('port', PUERTO_IP_DEFECTO)))
        elif actual == 'serial':
            combo_serial.set(direccion or perfil.get('virtualPort', ''))
            combo_baud.set(str(perfil.get('baudRate', '') or '9600'))
        elif actual == 'bluetooth':
            combo_bt.set(direccion)
        else:
            entry_virtual.insert(0, direccion or perfil.get('virtualPort', ''))

        if not entry_puerto.get():
            entry_puerto.insert(0, str(PUERTO_IP_DEFECTO))
        if not combo_baud.get():
            combo_baud.set('9600')
        entry_code.insert(0, perfil.get('queueCode', ''))
        entry_empresa.insert(0, perfil.get('empresa', ''))
        entry_desc.insert(0, perfil.get('description', ''))
        _pintar()

        # ---------------- Guardar ----------------
        def _guardar():
            t = _transporte_actual()
            code = entry_code.get().strip()
            empresa = entry_empresa.get().strip().lower()
            desc = entry_desc.get().strip()

            # Cada transporte valida SU dato y arma la etiqueta que se ve en la
            # lista. `etiqueta` es solo para mostrar/identificar; lo que manda a
            # la hora de imprimir son transport + address/host/port.
            host = puerto = baud = ''
            if t == 'cups':
                direccion_nueva = combo_cups.get().strip()
                if not direccion_nueva:
                    messagebox.showwarning("Aviso", "Seleccione una impresora.", parent=dlg)
                    return
                etiqueta = direccion_nueva
            elif t == 'ip':
                host = entry_host.get().strip()
                puerto = entry_puerto.get().strip() or str(PUERTO_IP_DEFECTO)
                if not host:
                    messagebox.showwarning("Aviso", "Escriba la dirección IP de la impresora.", parent=dlg)
                    return
                if not puerto.isdigit() or not (1 <= int(puerto) <= 65535):
                    messagebox.showwarning("Aviso", "El puerto debe ser un número entre 1 y 65535.", parent=dlg)
                    return
                direccion_nueva = f"{host}:{puerto}"
                etiqueta = direccion_nueva
            elif t == 'serial':
                direccion_nueva = solo_direccion(combo_serial.get())
                if not direccion_nueva:
                    messagebox.showwarning("Aviso", "Elija el dispositivo serie.", parent=dlg)
                    return
                baud = combo_baud.get().strip() or '9600'
                etiqueta = f"{direccion_nueva} @{baud}"
            elif t == 'bluetooth':
                direccion_nueva = solo_direccion(combo_bt.get()).upper()
                if not direccion_nueva:
                    messagebox.showwarning("Aviso", "Elija la impresora Bluetooth.", parent=dlg)
                    return
                etiqueta = direccion_nueva
            else:
                direccion_nueva = entry_virtual.get().strip()
                if not direccion_nueva:
                    messagebox.showwarning("Aviso", "Escriba la ruta del dispositivo.", parent=dlg)
                    return
                etiqueta = direccion_nueva

            if not code:
                messagebox.showwarning("Aviso", "Ingrese un código de cola.", parent=dlg)
                return
            if not empresa:
                messagebox.showwarning("Aviso", "Ingrese la empresa (base de datos).", parent=dlg)
                return

            # Duplicado = misma cola + misma empresa + mismo destino. Dos
            # perfiles iguales se pisarían y solo uno recibiría los trabajos.
            for i, p in enumerate(self.config.get('printers', [])):
                if i == indice:
                    continue
                if (p.get('queueCode', '') == code and p.get('empresa', '') == empresa
                        and p.get('windowsPrinter', p.get('printer', '')) == etiqueta):
                    messagebox.showwarning(
                        "Aviso", f"'{etiqueta}' ya está en la cola '{code}' para '{empresa}'.",
                        parent=dlg)
                    return

            nuevo = {
                "queueCode": code,
                "printerCode": code.split(',')[-1] if ',' in code else code,
                "windowsPrinter": etiqueta,
                "empresa": empresa,
                "description": desc,
                "printMode": var_mode.get(),
                "transport": t,
                "address": direccion_nueva,
            }
            if t == 'ip':
                nuevo["host"] = host
                nuevo["port"] = int(puerto)
            elif t == 'serial':
                nuevo["baudRate"] = int(baud)
                # Se conserva virtualPort para que una version anterior del
                # cliente que lea esta misma config siga imprimiendo.
                nuevo["virtualPort"] = direccion_nueva
            elif t == 'virtual':
                nuevo["virtualPort"] = direccion_nueva

            if var_mode.get() == 'raw':
                nuevo["cutPaper"] = var_cut.get()
                nuevo["openDrawer"] = var_drawer.get()
                nuevo["isThermal"] = var_thermal.get()
                nuevo["escposFont"] = 'B' if combo_escfont.get().startswith('B') else 'A'
            else:
                nuevo["spoolerFont"] = combo_font.get()
                nuevo["spoolerFontSize"] = float(combo_fsize.get())

            impresoras = self.config.setdefault('printers', [])
            if editando and 0 <= indice < len(impresoras):
                impresoras[indice] = nuevo
            else:
                impresoras.append(nuevo)
            save_config(self.config)
            self._reload_printer_table()
            self._reconnect_with_new_config()
            dlg.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=11, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn_frame, text="Guardar" if editando else "Agregar",
                   command=_guardar).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Cancelar", command=dlg.destroy).pack(side='left')

    def _test_printer(self):
        """Probar la impresora seleccionada: abre el cajón monedero y corta el papel."""
        _, printer_config = self._perfil_seleccionado("probar")
        if printer_config is None:
            return

        win_printer = printer_config.get('windowsPrinter', printer_config.get('printer', ''))
        if not win_printer:
            messagebox.showwarning("Probar impresora", "La fila seleccionada no tiene impresora.")
            return

        # Preguntar fuente (A/B) y columnas, y armar el ticket según eso
        # (pre-selecciona la fuente guardada de la impresora)
        sel = ask_paper_width(self.root, default_font=printer_config.get('escposFont', 'A'))
        if sel is None:
            return
        cols, font = sel

        # Tiquete de prueba: título grande, cliente en negrita, total grande,
        # muestra de tamaños de letra + abre cajón y corta papel.
        data = build_test_ticket(win_printer, cols, font)

        # Despachar por el MISMO camino que la impresión real. Si "Probar" usara
        # otra ruta, probaría algo distinto de lo que hace en producción — que es
        # justo lo que uno no quiere de un botón de prueba.
        try:
            ok, msg = despachar_raw(printer_config, data, win_printer)
        except Exception as e:
            ok, msg = False, str(e)

        if ok:
            messagebox.showinfo("Probar impresora",
                                f"Prueba enviada a:\n{win_printer}\n\n"
                                "Debe abrirse el cajón y cortarse el papel.")
        else:
            messagebox.showerror("Probar impresora", f"No se pudo enviar la prueba:\n{msg}")

    def _purge_printer(self):
        """Vaciar la cola de la impresora seleccionada: spooler del equipo + servidor."""
        _, printer_config = self._perfil_seleccionado("limpiar la cola")
        if printer_config is None:
            return
        queue_code = printer_config.get('queueCode', '')
        empresa = printer_config.get('empresa', '')
        printer_name = printer_config.get('windowsPrinter', printer_config.get('printer', ''))

        if not messagebox.askyesno(
                "Limpiar cola",
                f"Se van a CANCELAR los trabajos pendientes de:\n\n"
                f"Impresora: {printer_name}\n"
                f"Cola: {queue_code}   Empresa: {empresa}\n\n"
                "Se limpia la cola del equipo (spooler) y la del servidor.\n"
                "Los documentos NO impresos se pierden.\n\n¿Continuar?"):
            return

        lineas = []

        # 1. Spooler del equipo (los de puerto virtual no pasan por el spooler)
        virtual_port = printer_config.get('virtualPort', '').strip()
        if virtual_port:
            lineas.append(f"Equipo: sin cola (puerto directo {virtual_port})")
        else:
            win_printer = printer_config.get('windowsPrinter', printer_config.get('printer', ''))
            ok, _n, detalle = purge_spooler_queue(win_printer)
            lineas.append(f"Equipo: {detalle}" if ok else f"Equipo: FALLÓ — {detalle}")
            self._append_log(f"{'' if ok else 'ERROR '}Limpiar cola "
                             f"[{printer_name}] spooler: {detalle}")

        # 2. Cola del servidor (jobs 'queued' que se re-enviarían al reconectar)
        ok, _n, detalle = purge_server_queue(self.client.current_server, empresa, queue_code)
        lineas.append(f"Servidor: {detalle}" if ok else f"Servidor: FALLÓ — {detalle}")
        self._append_log(f"{'' if ok else 'ERROR '}Limpiar cola "
                         f"[{queue_code}/{empresa}] servidor: {detalle}")

        messagebox.showinfo("Limpiar cola", "\n".join(lineas))

    def _remove_printer(self):
        """Quitar la impresora seleccionada."""
        indice, perfil = self._perfil_seleccionado("quitar")
        if perfil is None:
            return
        empresa = perfil.get('empresa', '')
        printer_name = perfil.get('windowsPrinter', perfil.get('printer', ''))

        if not messagebox.askyesno("Confirmar", f"¿Quitar '{printer_name}' ({empresa}) de la lista?"):
            return

        # Se borra POR POSICION. El filtrado por campos de antes tenia un
        # problema silencioso: dos perfiles con la misma cola/empresa/impresora
        # se borraban LOS DOS de un solo clic.
        del self.config.setdefault('printers', [])[indice]
        save_config(self.config)
        self._reload_printer_table()
        self._reconnect_with_new_config()

    def _get_exe_path(self):
        """Ruta del ejecutable actual."""
        if getattr(sys, 'frozen', False):
            return sys.executable
        return os.path.abspath(sys.argv[0])

    # NOTA: el auto-inicio (oculto, con tray) lo configura el INSTALADOR de Windows
    # (Inno Setup → HKLM\...\Run con --hidden) y, en Linux, el postinst del .deb
    # (autostart per-user). Por eso se eliminaron los métodos _toggle_autostart /
    # _toggle_autohide / _is_autostart_enabled / _get_startup_shortcut_path: la app
    # ya no gestiona el auto-inicio desde su interfaz.

    def _reconnect_with_new_config(self):
        """Reconectar con la config actualizada (nuevas colas)."""
        self.client.stop()
        self.client = PrintQueueClient(
            self.config,
            on_log=self._append_log,
            on_status=self._update_status,
        )
        self.conn_thread = threading.Thread(target=self.client.connect, daemon=True)
        self.conn_thread.start()

    def _open_config(self):
        """Diálogo para editar servidor y ID del cliente."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Configuración de Conexión")
        dlg.geometry("600x300")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.configure(bg=BODY)

        dlg.update_idletasks()
        x = self.root.winfo_x() + 80
        y = self.root.winfo_y() + 80
        dlg.geometry(f"+{x}+{y}")

        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill='both', expand=True)

        ttk.Label(frame, text="Servidor principal:").grid(row=0, column=0, sticky='w', pady=4)
        entry_s1 = ttk.Entry(frame, width=40)
        entry_s1.grid(row=0, column=1, padx=(5, 0), pady=4, sticky='ew')
        entry_s1.insert(0, self.config['servers'][0] if self.config.get('servers') else '')

        ttk.Label(frame, text="Servidor failover:").grid(row=1, column=0, sticky='w', pady=4)
        entry_s2 = ttk.Entry(frame, width=40)
        entry_s2.grid(row=1, column=1, padx=(5, 0), pady=4, sticky='ew')
        s2 = self.config['servers'][1] if len(self.config.get('servers', [])) > 1 else ''
        entry_s2.insert(0, s2)

        ttk.Label(frame, text="ID del cliente:").grid(row=2, column=0, sticky='w', pady=4)
        entry_id = ttk.Entry(frame, width=40)
        entry_id.grid(row=2, column=1, padx=(5, 0), pady=4, sticky='ew')
        entry_id.insert(0, self.config.get('clientId', ''))

        frame.columnconfigure(1, weight=1)

        def do_save():
            s1 = entry_s1.get().strip()
            cid = entry_id.get().strip()
            if not s1:
                messagebox.showwarning("Aviso", "Ingrese al menos un servidor.", parent=dlg)
                return
            if not cid:
                messagebox.showwarning("Aviso", "Ingrese un ID de cliente.", parent=dlg)
                return
            servers = [s1]
            s2v = entry_s2.get().strip()
            if s2v:
                servers.append(s2v)
            self.config['servers'] = servers
            self.config['clientId'] = cid
            save_config(self.config)
            dlg.destroy()
            self._reconnect_with_new_config()
            self._append_log("Configuración actualizada — reconectando...")

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn_frame, text="Guardar y Reconectar", command=do_save).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Cancelar", command=dlg.destroy).pack(side='left')

    # --- System Tray ---
    def _create_tray_icon(self):
        """Crear ícono de bandeja del sistema."""
        image = self._create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Mostrar", self._show_from_tray, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir", self._quit_from_tray),
        )
        self.tray_icon = pystray.Icon("FactuPOS Print", image, f"FactuPOS Print v{VERSION}", menu)
        tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        tray_thread.start()

    def _create_tray_image(self):
        """Generar ícono verde con 'F' para la bandeja."""
        size = 64
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # rounded_rectangle requiere Pillow >= 8.2; fallback a rectangle
        if hasattr(draw, 'rounded_rectangle'):
            draw.rounded_rectangle([2, 2, size - 2, size - 2], radius=12, fill='#166534')
        else:
            draw.rectangle([2, 2, size - 2, size - 2], fill='#166534')
        # Letra F centrada
        try:
            from PIL import ImageFont
            font = ImageFont.truetype("arial.ttf", 38)
        except Exception:
            font = ImageFont.load_default()
        # textbbox requiere Pillow >= 8.0; fallback a textsize
        if hasattr(draw, 'textbbox'):
            bbox = draw.textbbox((0, 0), "F", font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        else:
            tw, th = draw.textsize("F", font=font)
        draw.text(((size - tw) / 2, (size - th) / 2 - 4), "F", fill='white', font=font)
        return img

    def _hide_to_tray(self):
        """Ocultar ventana a la bandeja del sistema."""
        if HAS_TRAY and self.tray_icon:
            self.root.withdraw()
            log.info("Ventana oculta en bandeja del sistema")
        else:
            # Sin tray, preguntar si quiere salir
            if messagebox.askyesno("Salir", "¿Cerrar FactuPOS Print Client?"):
                self._quit_app()

    def _show_from_tray(self, icon=None, item=None):
        """Restaurar ventana desde la bandeja."""
        self.root.after(0, self._do_show)

    def _do_show(self):
        """Restaurar ventana (debe ejecutarse en el thread de tkinter)."""
        self.root.deiconify()
        self.root.state('normal')
        self.root.lift()
        self.root.focus_force()

    def _quit_from_tray(self, icon=None, item=None):
        """Salir completamente desde la bandeja."""
        self.root.after(0, self._quit_app)

    def _quit_app(self):
        """Cerrar todo: cliente WS, bandeja e interfaz."""
        self.client.stop()
        if getattr(self, 'puerto_local', None):
            self.puerto_local.detener()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()

    def _on_minimize(self, event):
        """Al minimizar ventana, ocultar a bandeja."""
        if event.widget == self.root and self.root.state() == 'iconic':
            if HAS_TRAY and self.tray_icon:
                self.root.after(10, self._hide_to_tray)

    def on_close(self):
        self._quit_app()

    def run(self):
        self.root.mainloop()


# ═══════════════════════════════════════════════════════════════════════════
# App Launch
# ═══════════════════════════════════════════════════════════════════════════
def launch_app():
    config = load_config()
    # Auto-asignar clientId si está vacío
    if not config.get('clientId'):
        config['clientId'] = socket.gethostname()
        save_config(config)
    # --hidden lo pasan el autostart de Linux y el Run de Windows; a mano nunca.
    main = MainWindow(config, arrancar_oculto=('--hidden' in sys.argv[1:]))
    main.run()


if __name__ == "__main__":

    launch_app()
