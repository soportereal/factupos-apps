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

CONFIG_FILE = os.path.join(APP_DIR, 'config.json')
LOG_FILE = os.path.join(APP_DIR, 'print_client.log')

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
    ]
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
try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False
    log.warning("pystray/Pillow no disponible — sin bandeja del sistema")

VERSION = "4.46"  # 4.46: instalador Windows (Inno Setup) — autostart oculto + auto-update sin UAC (icacls Modify); se quitaron los checkboxes Auto-ocultar/Iniciar con el sistema (los maneja el instalador); arranque oculto con flag --hidden. 4.45: paridad con Linux — boton Probar (ticket A/B + cajon + corte), tipo de letra Epson A/B por impresora, look navy + version grande, letra grande. Conserva fix hashlib + barcode128 GDI propios de Windows.
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

def print_raw(printer_name, data_bytes):
    """Enviar bytes RAW directo a la impresora (modo POS)."""
    if IS_LINUX:
        return _print_raw_linux(printer_name, data_bytes)
    if not HAS_WIN32:
        log.info(f"[MOCK] RAW {len(data_bytes)} bytes → '{printer_name}'")
        return True, f"Simulado OK en {printer_name}"
    try:
        hPrinter = win32print.OpenPrinter(printer_name)
        try:
            win32print.StartDocPrinter(hPrinter, 1, ("FactuPOS", None, "RAW"))
            try:
                win32print.StartPagePrinter(hPrinter)
                win32print.WritePrinter(hPrinter, data_bytes)
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
    from reportlab.platypus import HRFlowable

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
        s('T8', fontSize=8, fontName='Helvetica', spaceAfter=0, spaceBefore=0, leading=10)
        s('T8R', fontSize=8, fontName='Helvetica', spaceAfter=0, spaceBefore=0, leading=10, alignment=TA_RIGHT)
        s('T7', fontSize=7, fontName='Helvetica', spaceAfter=0, spaceBefore=0, leading=9, textColor=colors.black)
        s('Label', fontSize=7, fontName='Helvetica-Bold', textColor=colors.HexColor('#666'), spaceAfter=0)
        s('CliNombre', fontSize=11, fontName='Helvetica-Bold', spaceAfter=2)
        s('TotalGrande', fontSize=14, fontName='Helvetica-Bold', alignment=TA_RIGHT, spaceBefore=3)
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
                partes = [f"Cabys: {cabys}", f"C\u00f3digo: {codigo}", f"Unidad: {unidad}"]
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
                el.append(Paragraph(f"<b>Detalle:</b> {documento['detalle']}", styles['N8']))
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

        # ── PIE ──
        el.append(Spacer(1, 4*mm))

        if tipo_doc == 'proforma':
            el.append(Paragraph('<b>DOCUMENTO SIN VALOR FISCAL</b>', styles['PieBold']))
            el.append(Paragraph('LOS PRECIOS ESTÁN SUJETOS A CAMBIO SIN PREVIO AVISO', styles['Pie']))
        else:
            el.append(Spacer(1, 8*mm))
            el.append(Paragraph('_' * 60, styles['N7']))
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
            el.append(pie_tabla)
            # Condiciones de venta (param 139)
            condiciones = d.get('condiciones_venta', '')
            if condiciones:
                el.append(Spacer(1, 2*mm))
                el.append(Paragraph(condiciones, styles['Pie']))
            # Resolución (param 123)
            resolucion = d.get('resolucion', '')
            if resolucion:
                el.append(Paragraph(resolucion, styles['Pie']))

        # Etiqueta ORIGINAL/COPIA
        el.append(Spacer(1, 3*mm))
        el.append(Paragraph(f"<b>{copia_etiqueta}</b>", styles['PieBold']))

        doc.build(el)

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


def print_raw_thermal(printer_name, data_bytes, chunk_size=256, delay=0.05):
    """Enviar bytes RAW — en Linux usa el mismo método que raw normal."""
    if IS_LINUX:
        return _print_raw_linux(printer_name, data_bytes)
    if not HAS_WIN32:
        log.info(f"[MOCK] RAW-THERMAL {len(data_bytes)} bytes → '{printer_name}' (chunks {chunk_size})")
        return True, f"Simulado OK en {printer_name}"
    try:
        hPrinter = win32print.OpenPrinter(printer_name)
        try:
            win32print.StartDocPrinter(hPrinter, 1, ("FactuPOS", None, "RAW"))
            try:
                win32print.StartPagePrinter(hPrinter)
                offset = 0
                while offset < len(data_bytes):
                    chunk = data_bytes[offset:offset + chunk_size]
                    win32print.WritePrinter(hPrinter, chunk)
                    offset += chunk_size
                    if offset < len(data_bytes):
                        time.sleep(delay)
                win32print.EndPagePrinter(hPrinter)
            finally:
                win32print.EndDocPrinter(hPrinter)
        finally:
            win32print.ClosePrinter(hPrinter)
        return True, f"Impreso en {printer_name} (thermal)"
    except Exception as e:
        return False, f"Error: {e}"

def print_raw_virtual_port(port_name, data_bytes):
    """Enviar bytes RAW via puerto virtual (LPTx en Windows, /dev/usb/lpX en Linux)."""
    try:
        with open(port_name, 'wb') as f:
            f.write(data_bytes)
        return True, f"Impreso via {port_name}"
    except Exception as e:
        return False, f"Error puerto {port_name}: {e}"

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
            "token": self.token,
        }))
        empresas = set(q.get('empresa', '?') for q in queues)
        self._log(f"Registrando {len(queues)} cola(s) [empresas: {', '.join(empresas)}]")

    def on_message(self, ws, message):
        try:
            msg = json.loads(message)
        except json.JSONDecodeError:
            self._log(f"JSON inválido: {message[:100]}", 'error')
            return

        action = msg.get('action', '')
        if action == 'registered':
            self._log(f"Registrado OK como '{msg.get('clientId')}'")
            latest = msg.get('latestVersion', '')
            download_url = msg.get('downloadUrl', '')
            if latest and download_url and latest != VERSION:
                self._log(f"Nueva versión disponible: {latest} (actual: {VERSION})")
                threading.Thread(target=self._auto_update, args=(latest, download_url), daemon=True).start()
        elif action == 'print':
            self._handle_print_job(ws, msg)
        elif action == 'ack_received':
            pass
        elif msg.get('ok') is False:
            self._log(f"Error del servidor: {msg.get('error')}", 'error')

    def _handle_print_job(self, ws, msg):
        job_id = msg.get('jobId', '?')
        queue = msg.get('queue', '')
        data_b64 = msg.get('data', '')
        short_id = job_id[:8]
        self._log(f"Job {short_id} recibido → cola {queue}")

        printer_config = self.queue_map.get(queue)
        if not printer_config:
            self._log(f"Job {short_id} → cola no mapeada: {queue}", 'error')
            self._send_ack(ws, job_id, 'error', f'Cola no mapeada: {queue}')
            self.jobs_err += 1
            return

        win_printer = printer_config.get('windowsPrinter', printer_config.get('printer', ''))
        try:
            data_bytes = base64.b64decode(data_b64)
        except Exception as e:
            self._log(f"Job {short_id} → error base64: {e}", 'error')
            self._send_ack(ws, job_id, 'error', str(e))
            self.jobs_err += 1
            return

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
                self._send_ack(ws, job_id, 'ok')
                self.jobs_ok += 1
            else:
                self._log(f"Job {short_id} → ERROR: {result_msg}", 'error')
                self._send_ack(ws, job_id, 'error', result_msg)
                self.jobs_err += 1
            return

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
                self._send_ack(ws, job_id, 'ok')
                self.jobs_ok += 1
            else:
                self._log(f"Job {short_id} → ERROR: {result_msg}", 'error')
                self._send_ack(ws, job_id, 'error', result_msg)
                self.jobs_err += 1
            return

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
                self._send_ack(ws, job_id, 'ok')
                self.jobs_ok += 1
            else:
                self._log(f"Job {short_id} → ERROR: {result_msg}", 'error')
                self._send_ack(ws, job_id, 'error', result_msg)
                self.jobs_err += 1
            return

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

            # Puerto virtual (net use LPTx) o win32print
            virtual_port = printer_config.get('virtualPort', '').strip()
            is_thermal = printer_config.get('isThermal', False)

            if virtual_port:
                ok, result_msg = print_raw_virtual_port(virtual_port, data_bytes)
            elif is_thermal:
                ok, result_msg = print_raw_thermal(win_printer, data_bytes)
            else:
                ok, result_msg = print_raw(win_printer, data_bytes)

        elapsed = time.time() - t0

        if ok:
            mode_str = f"{print_mode}" + (" vb6" if uses_vb6 else "")
            self._log(f"Job {short_id} → {win_printer} OK ({elapsed:.1f}s, {mode_str}) [{result_msg}]")
            self._send_ack(ws, job_id, 'ok')
            self.jobs_ok += 1
        else:
            self._log(f"Job {short_id} → ERROR: {result_msg}", 'error')
            self._send_ack(ws, job_id, 'error', result_msg)
            self.jobs_err += 1

    def _send_ack(self, ws, job_id, status, error=None):
        ack = {"action": "ack", "jobId": job_id, "status": status}
        if error:
            ack["error"] = error
        try:
            ws.send(json.dumps(ack))
        except Exception as e:
            self._log(f"Error enviando ACK: {e}", 'error')

    def _auto_update(self, new_version, download_url):
        """Descargar nueva versión y reemplazar el .exe silenciosamente."""
        if self._update_checked:
            return
        self._update_checked = True

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

    def on_error(self, ws, error):
        self._log(f"WS Error: {error}", 'error')

    def on_close(self, ws, close_status_code, close_msg):
        self._set_status(False)
        self._log(f"Desconectado (code={close_status_code})")

    def _next_server(self):
        self.server_index = (self.server_index + 1) % len(self.servers)
        self.current_server = self.servers[self.server_index]

    def connect(self):
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
    def __init__(self, config):
        self.config = config
        self.root = tk.Tk()
        self.root.title(f"FactuPOS Print v{VERSION}")
        self.root.geometry("880x780")
        self.root.minsize(760, 600)
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

        self._update_counters()

        # Auto-ocultar al iniciar (autostart del instalador pasa --hidden;
        # abierto a mano desde el menú Inicio = ventana visible)
        if (self.config.get('autoHide', False) or '--hidden' in sys.argv) and HAS_TRAY:
            self.root.after(200, self._hide_to_tray)

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
        self.tree.column('code', width=90)
        self.tree.column('empresa', width=130)
        self.tree.column('printer', width=230)
        self.tree.column('description', width=190)
        self.tree.column('options', width=160)
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
        for p in self.config.get('printers', []):
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
            self.tree.insert('', 'end', values=(
                p.get('printerCode', p.get('queueCode', '')),
                p.get('empresa', ''),
                p.get('windowsPrinter', p.get('printer', '(sin nombre)')),
                p.get('description', ''),
                ', '.join(opts),
            ))

    def _add_printer(self):
        """Diálogo para agregar una impresora."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Agregar Impresora")
        dlg.geometry("600x640")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.configure(bg=BODY)

        # Centrar
        dlg.update_idletasks()
        x = self.root.winfo_x() + 100
        y = self.root.winfo_y() + 100
        dlg.geometry(f"+{x}+{y}")

        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill='both', expand=True)

        # Impresora Windows
        ttk.Label(frame, text="Impresora Windows:").grid(row=0, column=0, sticky='w', pady=5)
        try:
            printers_list, _ = list_printers()
        except:
            printers_list = []
        combo_printer = ttk.Combobox(frame, values=printers_list, width=35)
        combo_printer.grid(row=0, column=1, padx=(5, 0), pady=5, sticky='ew')
        if printers_list:
            combo_printer.current(0)

        # Código de cola
        ttk.Label(frame, text="Código de cola:").grid(row=1, column=0, sticky='w', pady=5)
        entry_code = ttk.Entry(frame, width=37)
        entry_code.grid(row=1, column=1, padx=(5, 0), pady=5, sticky='ew')
        ttk.Label(frame, text="Ej: 301", font=("Segoe UI", 8),
                  foreground='gray').grid(row=2, column=1, sticky='w', padx=(5, 0))

        # Empresa (BD)
        ttk.Label(frame, text="Empresa (BD):").grid(row=3, column=0, sticky='w', pady=5)
        entry_empresa = ttk.Entry(frame, width=37)
        entry_empresa.grid(row=3, column=1, padx=(5, 0), pady=5, sticky='ew')
        ttk.Label(frame, text="Nombre de la base de datos (ej: invefacon, fiorella)", font=("Segoe UI", 8),
                  foreground='gray').grid(row=4, column=1, sticky='w', padx=(5, 0))

        # Descripción
        ttk.Label(frame, text="Descripción:").grid(row=5, column=0, sticky='w', pady=5)
        entry_desc = ttk.Entry(frame, width=37)
        entry_desc.grid(row=5, column=1, padx=(5, 0), pady=5, sticky='ew')

        # === MODO DE IMPRESIÓN ===
        ttk.Label(frame, text="Modo:").grid(row=6, column=0, sticky='w', pady=5)
        var_mode = tk.StringVar(value='raw')
        mode_frame = ttk.Frame(frame)
        mode_frame.grid(row=6, column=1, sticky='w', padx=(5, 0), pady=5)
        rb_raw = ttk.Radiobutton(mode_frame, text="POS (RAW)", variable=var_mode, value='raw',
                                  command=lambda: _toggle_mode())
        rb_raw.pack(side='left', padx=(0, 15))
        rb_spooler = ttk.Radiobutton(mode_frame, text="Spooler (Cola SO)", variable=var_mode, value='spooler',
                                      command=lambda: _toggle_mode())
        rb_spooler.pack(side='left')

        # --- Panel opciones POS (RAW) ---
        pos_frame = ttk.LabelFrame(frame, text="Opciones POS", padding=5)
        pos_frame.grid(row=7, column=0, columnspan=2, sticky='ew', pady=(5, 0))

        var_cut = tk.BooleanVar(value=True)
        var_drawer = tk.BooleanVar(value=False)
        var_thermal = tk.BooleanVar(value=False)
        ttk.Checkbutton(pos_frame, text="Cortar papel", variable=var_cut).grid(row=0, column=0, sticky='w')
        ttk.Checkbutton(pos_frame, text="Abrir cajón", variable=var_drawer).grid(row=0, column=1, sticky='w', padx=(10, 0))
        ttk.Checkbutton(pos_frame, text="Es térmica (envío lento)", variable=var_thermal).grid(row=1, column=0, columnspan=2, sticky='w')

        ttk.Label(pos_frame, text="Tipo de letra (Epson):").grid(row=2, column=0, sticky='w', pady=(5, 0))
        combo_escfont = ttk.Combobox(pos_frame, values=['A (normal)', 'B (condensada)'],
                                     width=15, state='readonly')
        combo_escfont.grid(row=2, column=1, sticky='w', padx=(5, 0), pady=(5, 0))
        combo_escfont.set('A (normal)')

        ttk.Label(pos_frame, text="Puerto virtual (LPT):").grid(row=3, column=0, sticky='w', pady=(5, 0))
        entry_vport = ttk.Entry(pos_frame, width=15)
        entry_vport.grid(row=3, column=1, sticky='w', padx=(5, 0), pady=(5, 0))
        ttk.Label(pos_frame, text="Ej: LPT2 (dejar vacío si no usa)", font=("Segoe UI", 8),
                  foreground='gray').grid(row=4, column=0, columnspan=2, sticky='w')

        # --- Panel opciones Spooler ---
        spool_frame = ttk.LabelFrame(frame, text="Opciones Spooler", padding=5)
        spool_frame.grid(row=8, column=0, columnspan=2, sticky='ew', pady=(5, 0))

        ttk.Label(spool_frame, text="Fuente:").grid(row=0, column=0, sticky='w')
        combo_font = ttk.Combobox(spool_frame, values=[
            "Lucida Console", "Courier New", "Consolas", "Terminal",
            "Draft 10cpi", "Draft 12cpi", "Draft 15cpi", "Draft 16cpi", "Draft 17cpi", "Draft 20cpi",
            "Roman 10cpi", "Roman 12cpi", "Roman 15cpi", "Roman 16cpi", "Roman 17cpi", "Roman 20cpi"
        ], width=20)
        combo_font.grid(row=0, column=1, padx=(5, 0), sticky='w')
        combo_font.set("Lucida Console")

        ttk.Label(spool_frame, text="Tamaño:").grid(row=1, column=0, sticky='w', pady=(5, 0))
        combo_fsize = ttk.Combobox(spool_frame, values=["7", "7.5", "8", "8.5", "9", "9.5", "10", "11", "12", "14"],
                                    width=8, state='readonly')
        combo_fsize.grid(row=1, column=1, padx=(5, 0), sticky='w', pady=(5, 0))
        combo_fsize.set("10")

        frame.columnconfigure(1, weight=1)

        def _toggle_mode():
            if var_mode.get() == 'raw':
                pos_frame.grid()
                spool_frame.grid_remove()
            else:
                pos_frame.grid_remove()
                spool_frame.grid()

        # Iniciar con spooler oculto
        spool_frame.grid_remove()

        def do_add():
            printer = combo_printer.get().strip()
            code = entry_code.get().strip()
            empresa = entry_empresa.get().strip().lower()
            desc = entry_desc.get().strip()
            if not printer:
                messagebox.showwarning("Aviso", "Seleccione una impresora.", parent=dlg)
                return
            if not code:
                messagebox.showwarning("Aviso", "Ingrese un código de cola.", parent=dlg)
                return
            if not empresa:
                messagebox.showwarning("Aviso", "Ingrese la empresa (base de datos).", parent=dlg)
                return

            # Verificar duplicado
            for p in self.config.get('printers', []):
                if p.get('windowsPrinter', p.get('printer', '')) == printer and p.get('queueCode', '') == code and p.get('empresa', '') == empresa:
                    messagebox.showwarning("Aviso", f"'{printer}' ya está en cola '{code}' para '{empresa}'.", parent=dlg)
                    return

            new_printer = {
                "queueCode": code,
                "printerCode": code.split(',')[-1] if ',' in code else code,
                "windowsPrinter": printer,
                "empresa": empresa,
                "description": desc,
                "printMode": var_mode.get(),
            }

            if var_mode.get() == 'raw':
                new_printer["cutPaper"] = var_cut.get()
                new_printer["openDrawer"] = var_drawer.get()
                new_printer["isThermal"] = var_thermal.get()
                new_printer["escposFont"] = 'B' if combo_escfont.get().startswith('B') else 'A'
                vport = entry_vport.get().strip().upper()
                if vport:
                    new_printer["virtualPort"] = vport
            else:
                new_printer["spoolerFont"] = combo_font.get()
                new_printer["spoolerFontSize"] = float(combo_fsize.get())

            self.config.setdefault('printers', []).append(new_printer)
            save_config(self.config)
            self._reload_printer_table()
            self._reconnect_with_new_config()
            dlg.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=9, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btn_frame, text="Agregar", command=do_add).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Cancelar", command=dlg.destroy).pack(side='left')

    def _test_printer(self):
        """Probar la impresora seleccionada: abre el cajón monedero y corta el papel."""
        sel = self.tree.focus()
        if not sel:
            messagebox.showwarning("Aviso", "Seleccione una impresora para probar.")
            return

        vals = self.tree.item(sel, 'values')
        queue_code = vals[0]
        empresa = vals[1]
        printer_name = vals[2]

        # Buscar el registro en config (igual que _edit_printer)
        printer_config = None
        for p in self.config.get('printers', []):
            if (p.get('empresa', '') == empresa and p.get('queueCode', '') == queue_code
                    and p.get('windowsPrinter', p.get('printer', '')) == printer_name):
                printer_config = p
                break
        if printer_config is None:
            printer_config = {'windowsPrinter': printer_name}

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

        # Despachar igual que la impresión real (puerto virtual / térmica / CUPS)
        try:
            virtual_port = printer_config.get('virtualPort', '').strip()
            is_thermal = printer_config.get('isThermal', False)
            if virtual_port:
                ok, msg = print_raw_virtual_port(virtual_port, data)
            elif is_thermal:
                ok, msg = print_raw_thermal(win_printer, data)
            else:
                ok, msg = print_raw(win_printer, data)
        except Exception as e:
            ok, msg = False, str(e)

        if ok:
            messagebox.showinfo("Probar impresora",
                                f"Prueba enviada a:\n{win_printer}\n\n"
                                "Debe abrirse el cajón y cortarse el papel.")
        else:
            messagebox.showerror("Probar impresora", f"No se pudo enviar la prueba:\n{msg}")

    def _remove_printer(self):
        """Quitar la impresora seleccionada."""
        sel = self.tree.focus()
        if not sel:
            messagebox.showwarning("Aviso", "Seleccione una impresora para quitar.")
            return

        vals = self.tree.item(sel, 'values')
        # Columnas: code(0), empresa(1), printer(2), description(3), options(4)
        queue_code = vals[0]
        empresa = vals[1]
        printer_name = vals[2]

        if not messagebox.askyesno("Confirmar", f"¿Quitar '{printer_name}' ({empresa}) de la lista?"):
            return

        self.config['printers'] = [
            p for p in self.config.get('printers', [])
            if not (p.get('empresa', '') == empresa
                    and (p.get('queueCode', '') == queue_code or p.get('printerCode', '') == queue_code)
                    and p.get('windowsPrinter', p.get('printer', '')) == printer_name)
        ]
        save_config(self.config)
        self._reload_printer_table()
        self._reconnect_with_new_config()

    def _edit_printer(self):
        """Editar la impresora seleccionada."""
        sel = self.tree.focus()
        if not sel:
            messagebox.showwarning("Aviso", "Seleccione una impresora para editar.")
            return

        vals = self.tree.item(sel, 'values')
        queue_code = vals[0]
        empresa = vals[1]
        printer_name = vals[2]

        # Buscar el registro en config
        printer_data = None
        printer_idx = -1
        for i, p in enumerate(self.config.get('printers', [])):
            if (p.get('empresa', '') == empresa and p.get('queueCode', '') == queue_code
                    and p.get('windowsPrinter', p.get('printer', '')) == printer_name):
                printer_data = p
                printer_idx = i
                break

        if printer_data is None:
            messagebox.showerror("Error", "No se encontró la impresora en la configuración.")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Editar Impresora")
        dlg.geometry("600x640")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.configure(bg=BODY)

        dlg.update_idletasks()
        x = self.root.winfo_x() + 100
        y = self.root.winfo_y() + 100
        dlg.geometry(f"+{x}+{y}")

        frame = ttk.Frame(dlg, padding=15)
        frame.pack(fill='both', expand=True)

        # Impresora Windows
        ttk.Label(frame, text="Impresora:").grid(row=0, column=0, sticky='w', pady=5)
        try:
            printers_list, _ = list_printers()
        except:
            printers_list = []
        combo_printer = ttk.Combobox(frame, values=printers_list, width=35)
        combo_printer.grid(row=0, column=1, padx=(5, 0), pady=5, sticky='ew')
        # Seleccionar la actual
        if printer_name in printers_list:
            combo_printer.set(printer_name)
        elif printers_list:
            combo_printer.current(0)

        # Código de cola
        ttk.Label(frame, text="Código de cola:").grid(row=1, column=0, sticky='w', pady=5)
        entry_code = ttk.Entry(frame, width=37)
        entry_code.grid(row=1, column=1, padx=(5, 0), pady=5, sticky='ew')
        entry_code.insert(0, printer_data.get('queueCode', ''))

        # Empresa
        ttk.Label(frame, text="Empresa (BD):").grid(row=3, column=0, sticky='w', pady=5)
        entry_empresa = ttk.Entry(frame, width=37)
        entry_empresa.grid(row=3, column=1, padx=(5, 0), pady=5, sticky='ew')
        entry_empresa.insert(0, printer_data.get('empresa', ''))

        # Descripción
        ttk.Label(frame, text="Descripción:").grid(row=5, column=0, sticky='w', pady=5)
        entry_desc = ttk.Entry(frame, width=37)
        entry_desc.grid(row=5, column=1, padx=(5, 0), pady=5, sticky='ew')
        entry_desc.insert(0, printer_data.get('description', ''))

        # === MODO ===
        ttk.Label(frame, text="Modo:").grid(row=6, column=0, sticky='w', pady=5)
        current_mode = printer_data.get('printMode', 'raw')
        var_mode = tk.StringVar(value=current_mode)
        mode_frame = ttk.Frame(frame)
        mode_frame.grid(row=6, column=1, sticky='w', padx=(5, 0), pady=5)
        rb_raw = ttk.Radiobutton(mode_frame, text="POS (RAW)", variable=var_mode, value='raw',
                                  command=lambda: _toggle_mode())
        rb_raw.pack(side='left', padx=(0, 15))
        rb_spooler = ttk.Radiobutton(mode_frame, text="Spooler (Cola SO)", variable=var_mode, value='spooler',
                                      command=lambda: _toggle_mode())
        rb_spooler.pack(side='left')

        # --- Panel POS ---
        pos_frame = ttk.LabelFrame(frame, text="Opciones POS", padding=5)
        pos_frame.grid(row=7, column=0, columnspan=2, sticky='ew', pady=(5, 0))

        var_cut = tk.BooleanVar(value=printer_data.get('cutPaper', True))
        var_drawer = tk.BooleanVar(value=printer_data.get('openDrawer', False))
        var_thermal = tk.BooleanVar(value=printer_data.get('isThermal', False))
        ttk.Checkbutton(pos_frame, text="Cortar papel", variable=var_cut).grid(row=0, column=0, sticky='w')
        ttk.Checkbutton(pos_frame, text="Abrir cajón", variable=var_drawer).grid(row=0, column=1, sticky='w', padx=(10, 0))
        ttk.Checkbutton(pos_frame, text="Es térmica (envío lento)", variable=var_thermal).grid(row=1, column=0, columnspan=2, sticky='w')

        ttk.Label(pos_frame, text="Tipo de letra (Epson):").grid(row=2, column=0, sticky='w', pady=(5, 0))
        combo_escfont = ttk.Combobox(pos_frame, values=['A (normal)', 'B (condensada)'],
                                     width=15, state='readonly')
        combo_escfont.grid(row=2, column=1, sticky='w', padx=(5, 0), pady=(5, 0))
        combo_escfont.set('B (condensada)' if str(printer_data.get('escposFont', 'A')).upper() == 'B' else 'A (normal)')

        ttk.Label(pos_frame, text="Puerto virtual (LPT):").grid(row=3, column=0, sticky='w', pady=(5, 0))
        entry_vport = ttk.Entry(pos_frame, width=15)
        entry_vport.grid(row=3, column=1, sticky='w', padx=(5, 0), pady=(5, 0))
        entry_vport.insert(0, printer_data.get('virtualPort', ''))

        # --- Panel Spooler ---
        spool_frame = ttk.LabelFrame(frame, text="Opciones Spooler", padding=5)
        spool_frame.grid(row=8, column=0, columnspan=2, sticky='ew', pady=(5, 0))

        ttk.Label(spool_frame, text="Fuente:").grid(row=0, column=0, sticky='w')
        combo_font = ttk.Combobox(spool_frame, values=[
            "Lucida Console", "Courier New", "Consolas", "Terminal",
            "Draft 10cpi", "Draft 12cpi", "Draft 15cpi", "Draft 16cpi", "Draft 17cpi", "Draft 20cpi",
            "Roman 10cpi", "Roman 12cpi", "Roman 15cpi", "Roman 16cpi", "Roman 17cpi", "Roman 20cpi"
        ], width=20)
        combo_font.grid(row=0, column=1, padx=(5, 0), sticky='w')
        combo_font.set(printer_data.get('spoolerFont', 'Lucida Console'))

        ttk.Label(spool_frame, text="Tamaño:").grid(row=1, column=0, sticky='w', pady=(5, 0))
        combo_fsize = ttk.Combobox(spool_frame, values=["7", "7.5", "8", "8.5", "9", "9.5", "10", "11", "12", "14"],
                                    width=8, state='readonly')
        combo_fsize.grid(row=1, column=1, padx=(5, 0), sticky='w', pady=(5, 0))
        combo_fsize.set(str(printer_data.get('spoolerFontSize', 10)))

        frame.columnconfigure(1, weight=1)

        def _toggle_mode():
            if var_mode.get() == 'raw':
                pos_frame.grid()
                spool_frame.grid_remove()
            else:
                pos_frame.grid_remove()
                spool_frame.grid()

        # Mostrar panel correcto
        if current_mode == 'spooler':
            pos_frame.grid_remove()
        else:
            spool_frame.grid_remove()

        def do_save():
            new_printer = combo_printer.get().strip()
            code = entry_code.get().strip()
            emp = entry_empresa.get().strip().lower()
            desc = entry_desc.get().strip()
            if not new_printer or not code or not emp:
                messagebox.showwarning("Aviso", "Complete impresora, código y empresa.", parent=dlg)
                return

            updated = {
                "queueCode": code,
                "printerCode": code.split(',')[-1] if ',' in code else code,
                "windowsPrinter": new_printer,
                "empresa": emp,
                "description": desc,
                "printMode": var_mode.get(),
            }

            if var_mode.get() == 'raw':
                updated["cutPaper"] = var_cut.get()
                updated["openDrawer"] = var_drawer.get()
                updated["isThermal"] = var_thermal.get()
                updated["escposFont"] = 'B' if combo_escfont.get().startswith('B') else 'A'
                vport = entry_vport.get().strip().upper()
                if vport:
                    updated["virtualPort"] = vport
            else:
                updated["spoolerFont"] = combo_font.get()
                updated["spoolerFontSize"] = float(combo_fsize.get())

            self.config['printers'][printer_idx] = updated
            save_config(self.config)
            self._reload_printer_table()
            self._reconnect_with_new_config()
            dlg.destroy()

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=9, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btn_frame, text="Guardar", command=do_save).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Cancelar", command=dlg.destroy).pack(side='left')

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
    main = MainWindow(config)
    main.run()


if __name__ == "__main__":

    launch_app()
