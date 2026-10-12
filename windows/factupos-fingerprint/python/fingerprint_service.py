#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FactuPOS - Servicio de Huella Digital para Windows (intermediario en Python)
============================================================================

Reemplaza al servicio C# (.NET DPFP) que sufria el bug de "foco de ventana":
el wrapper .NET crea la adquisicion con prioridad NORMAL, que solo recibe
eventos del lector cuando la app esta en primer plano. Aqui usamos directamente
la C-API del "DigitalPersona One Touch for Windows SDK" via ctypes y creamos la
adquisicion con prioridad HIGH (DP_PRIORITY_HIGH), que recibe los eventos del
dispositivo de forma EXCLUSIVA, independientemente del foco. Eso elimina el bug.

Arquitectura
------------
  popup_huella.php (Chrome)  --fetch HTTPS-->  este servicio (127.0.0.1:52181)
        |  /fingerprint/identify, /fingerprint/enroll, /prints, /get_connection
        v
  DPFPApi.dll      -> captura de imagenes (DPFPCreateAcquisition + ventana msg-only)
  dpHFtrEx.dll     -> extraccion de minutiae (FX_extractFeatures)
  dpHMatch.dll     -> enrolamiento + verificacion 1:1 (MC_generateRegFeatures / MC_verifyFeaturesEx)
        v
  DigitalPersona U.are.U 4500 (USB) + servicio "DigitalPersona ... (DpHostW)"

Requisitos en el PC Windows
---------------------------
  * Python 3.8+ (32 o 64 bits, debe coincidir con el RTE instalado). En la
    carpeta Compartido hay un python-3.8.10.exe.
  * "DigitalPersona One Touch for Windows SDK" (o su RTE) instalado: registra
    DPFPApi.dll / dpHFtrEx.dll / dpHMatch.dll y el servicio DpHostW.
    (El mismo runtime que ya usa el servicio .NET actual.)
  * Lector DigitalPersona U.are.U 4500 conectado.
  * Sin dependencias pip: solo stdlib (ctypes, http.server, ssl, json, ...).

API HTTP (identica a la del servicio Linux/C# para que popup_huella.php no cambie)
  GET  /status               -> estado general
  GET  /get_connection       -> {connected, device, enroll_stages, matching}
  GET  /prints               -> {users: {user_id: cantidad_dedos}}
  POST /fingerprint/identify -> {ok, matched, user_id, finger} | {ok, waiting:true}
  POST /fingerprint/enroll   -> body {user_id, finger}; bloqueante (5 toques) -> {ok} | {ok:false,error}
  DELETE /prints/{user_id}   -> borra todas las huellas del usuario

Templates en disco: prints/{user_id}/{finger}.fpt (binario, template DigitalPersona)
"""

import os
import sys
import json
import time
import ssl
import base64
import threading
import traceback
import ctypes
from ctypes import wintypes
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
VERSION              = "1.0.5"
BUILD_DATE           = "2026-10-11"
PORT                 = 52181
# Carpeta base: la del .exe si está compilado con PyInstaller, si no la del .py
BASE_DIR             = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
PRINTS_DIR           = os.path.join(BASE_DIR, "prints")
CERTS_DIR            = os.path.join(BASE_DIR, "certs")
LOGS_DIR             = os.path.join(BASE_DIR, "logs")
CERT_FILE            = os.path.join(CERTS_DIR, "cert.pem")
KEY_FILE             = os.path.join(CERTS_DIR, "key.pem")

ENROLL_TOUCHES       = 4          # DigitalPersona requiere 4 feature sets (el .NET decia 4)
CAPTURE_TIMEOUT_S    = 12.0       # espera maxima por una imagen tras pedirla
ENROLL_TOUCH_WAIT_S  = 30.0       # espera maxima por cada toque durante el enroll
COOLDOWN_S           = 0.0        # el U.are.U 4500 (optico) no se sobrecalienta como el 4000

# Eventos de notificacion (de DPDevClt.h)
WN_COMPLETED         = 0
WN_ERROR             = 1
WN_DISCONNECT        = 2
WN_RECONNECT         = 3
WN_SAMPLE_QUALITY    = 4
WN_FINGER_TOUCHED    = 5
WN_FINGER_GONE       = 6
WN_IMAGE_READY       = 7
WN_OPERATION_STOPPED = 10

# Prioridades de adquisicion
DP_PRIORITY_HIGH     = 1
DP_PRIORITY_NORMAL   = 2
DP_PRIORITY_LOW      = 3

DP_SAMPLE_TYPE_IMAGE = 4

# Tipos de feature set (dpDefs.h FT_FTR_TYPE)
FT_PRE_REG_FTR       = 0   # para enrolamiento
FT_REG_FTR           = 1   # template
FT_VER_FTR           = 2   # para verificacion

# Calidades (dpDefs.h)
FT_GOOD_IMG          = 0
FT_GOOD_FTR          = 0

# Mensaje de ventana usado para las notificaciones de la adquisicion
WM_APP               = 0x8000
WM_FP_NOTIFY         = WM_APP + 7

S_OK                 = 0


# ---------------------------------------------------------------------------
# Log simple (consola + archivo del dia)
# ---------------------------------------------------------------------------
_log_lock = threading.Lock()

def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    with _log_lock:
        try:
            print(line, flush=True)
        except Exception:
            pass
        try:
            os.makedirs(LOGS_DIR, exist_ok=True)
            fn = os.path.join(LOGS_DIR, "fingerprint-%s.log" % datetime.now().strftime("%Y-%m-%d"))
            with open(fn, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Estructuras ctypes
# ---------------------------------------------------------------------------
class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32),
                ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]

    def __str__(self):
        return "{%08X-%04X-%04X-%02X%02X-%02X%02X%02X%02X%02X%02X}" % (
            self.Data1, self.Data2, self.Data3,
            self.Data4[0], self.Data4[1], self.Data4[2], self.Data4[3],
            self.Data4[4], self.Data4[5], self.Data4[6], self.Data4[7])

GUID_NULL = GUID()  # todo en cero

class DP_DEVICE_VERSION(ctypes.Structure):
    _fields_ = [("uMajor", ctypes.c_ulong),
                ("uMinor", ctypes.c_ulong),
                ("uBuild", ctypes.c_ulong)]

DP_MAX_USB_STRING_SIZE = 128

class DP_HW_INFO(ctypes.Structure):
    _fields_ = [("uLanguageId", ctypes.c_uint),
                ("szVendor",   ctypes.c_wchar * DP_MAX_USB_STRING_SIZE),
                ("szProduct",  ctypes.c_wchar * DP_MAX_USB_STRING_SIZE),
                ("szSerialNb", ctypes.c_wchar * DP_MAX_USB_STRING_SIZE),
                ("HardwareRevision", DP_DEVICE_VERSION),
                ("FirmwareRevision", DP_DEVICE_VERSION)]

class DP_DEVICE_INFO(ctypes.Structure):
    _fields_ = [("DeviceUid", GUID),
                ("eUidType", ctypes.c_int),
                ("eDeviceModality", ctypes.c_int),
                ("eDeviceTech", ctypes.c_int),
                ("HwInfo", DP_HW_INFO)]

# DATA_BLOB de Windows (wincrypt.h): {DWORD cbData; BYTE* pbData;}
class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong),
                ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

# MC_SETTINGS de dpMatch.h
class MC_SETTINGS(ctypes.Structure):
    _fields_ = [("numPreRegFeatures", ctypes.c_int)]

# LRESULT / LONG_PTR son del tamaño de un puntero (8 bytes en x64)
LRESULT = ctypes.c_ssize_t

# WNDCLASSEXW minima
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)

class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint),
                ("style", ctypes.c_uint),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm", wintypes.HICON)]

class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND),
                ("message", ctypes.c_uint),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt_x", ctypes.c_long),
                ("pt_y", ctypes.c_long)]

HWND_MESSAGE = wintypes.HWND(-3)


# ---------------------------------------------------------------------------
# Carga de DLLs
# ---------------------------------------------------------------------------
class SdkUnavailable(Exception):
    pass

def _try_load(loader, names):
    errs = []
    for n in names:
        try:
            return loader(n), n
        except OSError as e:
            errs.append("%s -> %s" % (n, e))
    raise SdkUnavailable("No se pudo cargar ninguna DLL de %r:\n    %s" % (names, "\n    ".join(errs)))

# Las DLLs del SDK se cargan en _load_sdk_dlls() (llamado desde init_sdk), no a nivel de modulo,
# para que el servicio HTTP igual arranque y /status pueda reportar el error.
dpfp_dll = fx_dll = mc_dll = None
dpfp_name = fx_name = mc_name = None
SDK_LOAD_ERROR = None

def _load_sdk_dlls():
    global dpfp_dll, fx_dll, mc_dll, dpfp_name, fx_name, mc_name, SDK_LOAD_ERROR
    if dpfp_dll is not None:
        return
    # DPFPApi: STDAPICALLTYPE = __stdcall -> WinDLL
    dpfp_dll, dpfp_name = _try_load(ctypes.WinDLL, ["DPFPApi.dll", "DpDevClt.dll"])
    # Feature extraction / matching: __cdecl -> CDLL
    fx_dll, fx_name = _try_load(ctypes.CDLL, ["dpHFtrEx.dll", "DpHFtrEx.dll", "dpFtrEx.dll", "DpFtrEx.dll"])
    mc_dll, mc_name = _try_load(ctypes.CDLL, ["dpHMatch.dll", "DpHMatch.dll", "dpMatch.dll", "DpMatch.dll"])

    # --- prototipos DPFPApi ---
    dpfp_dll.DPFPInit.restype = ctypes.c_long
    dpfp_dll.DPFPInit.argtypes = []
    dpfp_dll.DPFPTerm.restype = None
    dpfp_dll.DPFPTerm.argtypes = []
    dpfp_dll.DPFPEnumerateDevices.restype = ctypes.c_long
    dpfp_dll.DPFPEnumerateDevices.argtypes = [ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(GUID))]
    dpfp_dll.DPFPGetDeviceInfo.restype = ctypes.c_long
    dpfp_dll.DPFPGetDeviceInfo.argtypes = [ctypes.POINTER(GUID), ctypes.POINTER(DP_DEVICE_INFO)]
    dpfp_dll.DPFPCreateAcquisition.restype = ctypes.c_long
    dpfp_dll.DPFPCreateAcquisition.argtypes = [ctypes.c_int, ctypes.POINTER(GUID), ctypes.c_ulong,
                                               wintypes.HWND, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
    dpfp_dll.DPFPStartAcquisition.restype = ctypes.c_long
    dpfp_dll.DPFPStartAcquisition.argtypes = [ctypes.c_ulong]
    dpfp_dll.DPFPStopAcquisition.restype = ctypes.c_long
    dpfp_dll.DPFPStopAcquisition.argtypes = [ctypes.c_ulong]
    dpfp_dll.DPFPDestroyAcquisition.restype = ctypes.c_long
    dpfp_dll.DPFPDestroyAcquisition.argtypes = [ctypes.c_ulong]
    dpfp_dll.DPFPBufferFree.restype = None
    dpfp_dll.DPFPBufferFree.argtypes = [ctypes.c_void_p]

    # --- prototipos dpHFtrEx ---
    fx_dll.FX_init.restype = ctypes.c_int
    fx_dll.FX_init.argtypes = []
    fx_dll.FX_terminate.restype = ctypes.c_int
    fx_dll.FX_terminate.argtypes = []
    fx_dll.FX_createContext.restype = ctypes.c_int
    fx_dll.FX_createContext.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    fx_dll.FX_closeContext.restype = ctypes.c_int
    fx_dll.FX_closeContext.argtypes = [ctypes.c_void_p]
    fx_dll.FX_getFeaturesLen.restype = ctypes.c_int
    fx_dll.FX_getFeaturesLen.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
    fx_dll.FX_extractFeatures.restype = ctypes.c_int
    fx_dll.FX_extractFeatures.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_void_p,
                                          ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                          ctypes.POINTER(ctypes.c_int)]

    # --- prototipos dpHMatch ---
    mc_dll.MC_init.restype = ctypes.c_int
    mc_dll.MC_init.argtypes = []
    mc_dll.MC_terminate.restype = ctypes.c_int
    mc_dll.MC_terminate.argtypes = []
    mc_dll.MC_createContext.restype = ctypes.c_int
    mc_dll.MC_createContext.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    mc_dll.MC_closeContext.restype = ctypes.c_int
    mc_dll.MC_closeContext.argtypes = [ctypes.c_void_p]
    mc_dll.MC_getSettings.restype = ctypes.c_int
    mc_dll.MC_getSettings.argtypes = [ctypes.POINTER(MC_SETTINGS)]
    mc_dll.MC_setSecurityLevel.restype = ctypes.c_int
    mc_dll.MC_setSecurityLevel.argtypes = [ctypes.c_void_p, ctypes.c_double]
    mc_dll.MC_getFeaturesLen.restype = ctypes.c_int
    mc_dll.MC_getFeaturesLen.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
    mc_dll.MC_generateRegFeatures.restype = ctypes.c_int
    mc_dll.MC_generateRegFeatures.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                              ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)), ctypes.c_int,
                                              ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    mc_dll.MC_verifyFeaturesEx.restype = ctypes.c_int
    mc_dll.MC_verifyFeaturesEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
                                           ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_void_p, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_int)]
    log("DLLs SDK cargadas: %s / %s / %s" % (dpfp_name, fx_name, mc_name))


# user32 / kernel32
user32   = ctypes.WinDLL("user32",   use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ole32    = ctypes.WinDLL("ole32",    use_last_error=True)

user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.GetMessageW.restype = ctypes.c_int
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint]
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


# ---------------------------------------------------------------------------
# Estado del dispositivo / captura (compartido entre hilos)
# ---------------------------------------------------------------------------
class DeviceState(object):
    def __init__(self):
        self.lock              = threading.Lock()
        self.device_connected  = False
        self.device_serial     = ""
        self.device_product    = ""
        self.hop               = None     # handle de adquisicion
        self.hwnd              = None
        self.acq_priority      = None     # 'HIGH' | 'LOW' | 'NORMAL'
        # ultima imagen capturada
        self.last_image        = None      # bytes
        self.last_image_ts     = 0.0       # monotonic
        # señales
        self.image_event       = threading.Event()
        self.finger_on         = False
        self.ev_counts         = {}       # diagnostico: conteo de eventos del lector por tipo
        self.last_error        = 0
        self.cooling_until     = 0.0
        # contadores extraccion
        self.feat_len_recommended = 0
        self.feat_len_minimum     = 0
        self.tmpl_len_recommended = 0
        self.tmpl_len_minimum     = 0
        self.enroll_feature_sets  = ENROLL_TOUCHES

DEV = DeviceState()

# Contextos de FtrEx / Match + lock que serializa su uso
SDK_LOCK = threading.Lock()
FX_CTX   = ctypes.c_void_p()
MC_CTX   = ctypes.c_void_p()

# Lock que serializa operaciones de alto nivel (identify / enroll) — una a la vez
OP_LOCK  = threading.Lock()

# Progreso del enroll en curso (para que el kiosko muestre "toque N de M") + flag de cancelacion
ENROLL_LOCK   = threading.Lock()
ENROLL_STATE  = {"active": False, "done": 0, "needed": ENROLL_TOUCHES, "user": "", "finger": "", "msg": "", "result": None, "ts": 0.0}
ENROLL_CANCEL = threading.Event()
def _enroll_set(**kw):
    with ENROLL_LOCK:
        ENROLL_STATE.update(kw); ENROLL_STATE["ts"] = time.monotonic()
def _enroll_get():
    with ENROLL_LOCK:
        return dict(ENROLL_STATE)

# Templates en memoria: { user_id: { finger: bytes_template } }
TEMPLATES = {}
TEMPLATES_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# WNDPROC: recibe las notificaciones de la adquisicion
# ---------------------------------------------------------------------------
_EV_NAMES = {0:"COMPLETED",1:"ERROR",2:"DISCONNECT",3:"RECONNECT",4:"SAMPLE_QUALITY",
             5:"FINGER_TOUCHED",6:"FINGER_GONE",7:"IMAGE_READY",10:"OPERATION_STOPPED"}

def _wndproc(hwnd, msg, wparam, lparam):
    try:
        if msg == WM_FP_NOTIFY:
            ev = int(wparam)
            # DIAGNOSTICO: registrar todo evento del lector (asi vemos en el log si llegan al tocar)
            log("[evento lector] %s (ev=%d, lParam=%d)" % (_EV_NAMES.get(ev, "?"), ev, int(lparam)))
            with DEV.lock:
                DEV.ev_counts[ev] = DEV.ev_counts.get(ev, 0) + 1
            if ev == WN_COMPLETED:
                # lParam = puntero a DATA_BLOB con la imagen del lector
                try:
                    blob = ctypes.cast(lparam, ctypes.POINTER(DATA_BLOB)).contents
                    n = int(blob.cbData)
                    if n > 0 and blob.pbData:
                        data = ctypes.string_at(blob.pbData, n)
                        with DEV.lock:
                            DEV.last_image = data
                            DEV.last_image_ts = time.monotonic()
                        DEV.image_event.set()
                        log("Imagen capturada (%d bytes)" % n)
                    else:
                        log("WN_COMPLETED con blob vacio")
                except Exception as e:
                    log("Error procesando WN_COMPLETED: %s" % e)
            elif ev == WN_FINGER_TOUCHED:
                DEV.finger_on = True
            elif ev == WN_FINGER_GONE:
                DEV.finger_on = False
            elif ev == WN_SAMPLE_QUALITY:
                # lParam = DP_SAMPLE_QUALITY
                pass
            elif ev == WN_ERROR:
                DEV.last_error = int(lparam)
                log("WN_ERROR: 0x%08X" % (int(lparam) & 0xFFFFFFFF))
            elif ev == WN_DISCONNECT:
                with DEV.lock:
                    DEV.device_connected = False
                log("Lector DESCONECTADO")
            elif ev == WN_RECONNECT:
                with DEV.lock:
                    DEV.device_connected = True
                log("Lector RECONECTADO")
            elif ev == WN_OPERATION_STOPPED:
                log("Adquisicion detenida")
            return 0
    except Exception:
        log("Excepcion en WNDPROC:\n" + traceback.format_exc())
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

# Mantener referencia viva al callback (si se recolecta -> crash)
_WNDPROC_CB = WNDPROC(_wndproc)


# ---------------------------------------------------------------------------
# Inicializacion del SDK (en el hilo principal, antes del message loop)
# ---------------------------------------------------------------------------
def hr_ok(hr):
    return (hr & 0x80000000) == 0  # FAILED(hr) == False

def init_sdk():
    # 1) cargar las DLLs del SDK (DPFPApi / dpHFtrEx / dpHMatch) — si falla, RTE no instalado
    try:
        _load_sdk_dlls()
    except SdkUnavailable as e:
        raise SdkUnavailable(str(e) + "\n  -> ¿Está instalado el RUNTIME del 'DigitalPersona One Touch for "
                                       "Windows SDK'? Es el que registra DPFPApi.dll / dpHFtrEx.dll / dpHMatch.dll. "
                                       "Y Python debe ser de la misma arquitectura (32/64 bits) que el RTE.")

    # COM en STA (igual que el [STAThread] del servicio .NET)
    try:
        ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
    except Exception:
        pass

    hr = dpfp_dll.DPFPInit()
    if not hr_ok(hr):
        if (hr & 0xFFFFFFFF) == 0x800706B3:
            raise SdkUnavailable("DPFPInit: el servicio 'DigitalPersona (DpHostW)' no esta corriendo. "
                                 "Instala/arranca el RTE del DigitalPersona SDK.")
        raise SdkUnavailable("DPFPInit fallo: 0x%08X" % (hr & 0xFFFFFFFF))
    log("DPFPInit OK")

    # FtrEx
    rc = fx_dll.FX_init()
    if rc != 0 and rc != 1:  # FT_OK o FT_WRN_NO_INIT? (1 = warning ya inicializado en algunas builds)
        if rc < 0:
            raise SdkUnavailable("FX_init fallo: %d" % rc)
    if fx_dll.FX_createContext(ctypes.byref(FX_CTX)) != 0:
        raise SdkUnavailable("FX_createContext fallo")
    # Match
    rc = mc_dll.MC_init()
    if rc < 0:
        raise SdkUnavailable("MC_init fallo: %d" % rc)
    if mc_dll.MC_createContext(ctypes.byref(MC_CTX)) != 0:
        raise SdkUnavailable("MC_createContext fallo")
    # Seguridad media por defecto (1/1000) — igual que el DFLT
    try:
        mc_dll.MC_setSecurityLevel(MC_CTX, ctypes.c_double(0.0010))
    except Exception:
        pass

    # Longitudes recomendadas de feature set / template
    rec = ctypes.c_int(0); mn = ctypes.c_int(0)
    if fx_dll.FX_getFeaturesLen(FT_PRE_REG_FTR, ctypes.byref(rec), ctypes.byref(mn)) == 0:
        DEV.feat_len_recommended = rec.value
        DEV.feat_len_minimum     = mn.value
    rec = ctypes.c_int(0); mn = ctypes.c_int(0)
    if fx_dll.FX_getFeaturesLen(FT_VER_FTR, ctypes.byref(rec), ctypes.byref(mn)) == 0:
        # usamos el mayor para que sirva a ambos propositos
        DEV.feat_len_recommended = max(DEV.feat_len_recommended, rec.value)
        DEV.feat_len_minimum     = max(DEV.feat_len_minimum, mn.value)
    rec = ctypes.c_int(0); mn = ctypes.c_int(0)
    if mc_dll.MC_getFeaturesLen(FT_REG_FTR, 0, ctypes.byref(rec), ctypes.byref(mn)) == 0:
        DEV.tmpl_len_recommended = rec.value
        DEV.tmpl_len_minimum     = mn.value

    settings = MC_SETTINGS()
    if mc_dll.MC_getSettings(ctypes.byref(settings)) == 0 and settings.numPreRegFeatures > 0:
        DEV.enroll_feature_sets = settings.numPreRegFeatures
    log("Enroll feature sets requeridos: %d | featLen rec/min=%d/%d | tmplLen rec/min=%d/%d" % (
        DEV.enroll_feature_sets, DEV.feat_len_recommended, DEV.feat_len_minimum,
        DEV.tmpl_len_recommended, DEV.tmpl_len_minimum))

    refresh_device_info()
    create_acquisition_window_and_start()


def refresh_device_info():
    count = ctypes.c_ulong(0)
    arr   = ctypes.POINTER(GUID)()
    hr = dpfp_dll.DPFPEnumerateDevices(ctypes.byref(count), ctypes.byref(arr))
    if not hr_ok(hr):
        with DEV.lock:
            DEV.device_connected = False
        log("DPFPEnumerateDevices fallo: 0x%08X" % (hr & 0xFFFFFFFF))
        return
    n = count.value
    if n == 0:
        with DEV.lock:
            DEV.device_connected = False
            DEV.device_serial = ""
            DEV.device_product = ""
        log("No hay lectores conectados")
        if arr:
            dpfp_dll.DPFPBufferFree(arr)
        return
    first = arr[0]
    info = DP_DEVICE_INFO()
    serial = ""
    product = "U.are.U"
    if hr_ok(dpfp_dll.DPFPGetDeviceInfo(ctypes.byref(first), ctypes.byref(info))):
        try:
            product = info.HwInfo.szProduct.strip() or product
            serial  = (info.HwInfo.szSerialNb or "").strip() or str(info.DeviceUid)
        except Exception:
            serial = str(first)
    else:
        serial = str(first)
    with DEV.lock:
        DEV.device_connected = True
        DEV.device_serial = serial
        DEV.device_product = product
    log("Lector detectado: %s  serial=%s  (%d lector/es)" % (product, serial, n))
    dpfp_dll.DPFPBufferFree(arr)


def create_acquisition_window_and_start():
    # 1) clase de ventana msg-only
    hInst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.style = 0
    wc.lpfnWndProc = _WNDPROC_CB
    wc.cbClsExtra = 0
    wc.cbWndExtra = 0
    wc.hInstance = hInst
    wc.hIcon = None
    wc.hCursor = None
    wc.hbrBackground = None
    wc.lpszMenuName = None
    wc.lpszClassName = "FactuPOSFpSvcWnd"
    wc.hIconSm = None
    atom = user32.RegisterClassExW(ctypes.byref(wc))
    if not atom:
        err = ctypes.get_last_error()
        if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS
            raise SdkUnavailable("RegisterClassExW fallo: %d" % err)
    hwnd = user32.CreateWindowExW(0, "FactuPOSFpSvcWnd", "fpsvc", 0,
                                  0, 0, 0, 0, HWND_MESSAGE, None, hInst, None)
    if not hwnd:
        raise SdkUnavailable("CreateWindowExW fallo: %d" % ctypes.get_last_error())
    DEV.hwnd = hwnd
    log("Ventana msg-only creada: 0x%X" % (hwnd & 0xFFFFFFFFFFFFFFFF))

    # 2) crear adquisicion. Orden de preferencia: HIGH (recibe eventos SIEMPRE, sin importar el foco)
    #    -> LOW (tampoco depende del foco; sólo cede ante un suscriptor de mayor prioridad)
    #    -> NORMAL (ULTIMO recurso: SOLO recibe eventos en primer plano = vuelve el bug del foco).
    #    HIGH suele requerir ejecutar como Administrador, o que no haya otro agente DigitalPersona usando
    #    el lector (cerrar el servicio C# viejo, agentes DPAgent/OneTouch, etc.).
    hop = ctypes.c_ulong(0)
    chosen = None
    for prio_val, prio_name in ((DP_PRIORITY_HIGH, "HIGH"), (DP_PRIORITY_LOW, "LOW"), (DP_PRIORITY_NORMAL, "NORMAL")):
        hr = dpfp_dll.DPFPCreateAcquisition(prio_val, ctypes.byref(GUID_NULL), DP_SAMPLE_TYPE_IMAGE,
                                            hwnd, WM_FP_NOTIFY, ctypes.byref(hop))
        if hr_ok(hr):
            chosen = prio_name
            break
        log("DPFPCreateAcquisition(%s) fallo 0x%08X%s" % (
            prio_name, hr & 0xFFFFFFFF,
            "  (0x80070005 = acceso denegado: probá 'Ejecutar como administrador' o cerrá otros clientes DigitalPersona)"
            if (hr & 0xFFFFFFFF) == 0x80070005 else ""))
    if chosen is None:
        raise SdkUnavailable("DPFPCreateAcquisition fallo en todas las prioridades: 0x%08X" % (hr & 0xFFFFFFFF))
    DEV.acq_priority = chosen
    DEV.hop = hop.value
    hr = dpfp_dll.DPFPStartAcquisition(hop.value)
    if not hr_ok(hr):
        raise SdkUnavailable("DPFPStartAcquisition fallo: 0x%08X" % (hr & 0xFFFFFFFF))
    log("Adquisicion iniciada (prioridad %s, hOp=%d)%s" % (
        chosen, hop.value,
        "  ⚠ NORMAL = sólo funciona con la ventana del kiosko en primer plano (bug de foco)." if chosen == "NORMAL" else ""))


def shutdown_sdk():
    try:
        if DEV.hop:
            dpfp_dll.DPFPStopAcquisition(DEV.hop)
            dpfp_dll.DPFPDestroyAcquisition(DEV.hop)
    except Exception:
        pass
    try:
        if FX_CTX: fx_dll.FX_closeContext(FX_CTX)
        fx_dll.FX_terminate()
    except Exception:
        pass
    try:
        if MC_CTX: mc_dll.MC_closeContext(MC_CTX)
        mc_dll.MC_terminate()
    except Exception:
        pass
    try:
        dpfp_dll.DPFPTerm()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Captura: pedir una imagen "fresca"
# ---------------------------------------------------------------------------
def grab_fresh_image(timeout_s, cancel_event=None):
    """Espera a que llegue una imagen nueva (posterior a la llamada). Devuelve bytes o None.
       Si cancel_event se activa, retorna None enseguida."""
    started = time.monotonic()
    with DEV.lock:
        baseline = DEV.last_image_ts
    DEV.image_event.clear()
    while time.monotonic() - started < timeout_s:
        if cancel_event is not None and cancel_event.is_set():
            return None
        if DEV.image_event.wait(0.2):
            with DEV.lock:
                if DEV.last_image_ts > baseline and DEV.last_image:
                    return DEV.last_image
            DEV.image_event.clear()
    return None

def peek_recent_image(max_age_s):
    """Devuelve la ultima imagen si es reciente (modo polling no bloqueante)."""
    with DEV.lock:
        if DEV.last_image and (time.monotonic() - DEV.last_image_ts) <= max_age_s:
            img = DEV.last_image
            # consumimos: la marcamos como vieja para no re-identificar la misma huella
            DEV.last_image = None
            return img
    return None


# ---------------------------------------------------------------------------
# Extraccion / matching
# ---------------------------------------------------------------------------
def extract_features(image_bytes, purpose):
    """Devuelve (feature_set_bytes, img_quality, ftr_quality) o (None, iq, fq)."""
    feat_size = DEV.feat_len_recommended or DEV.feat_len_minimum or 2048
    buf = (ctypes.c_ubyte * feat_size)()
    img_q = ctypes.c_int(-1)
    ftr_q = ctypes.c_int(-1)
    created = ctypes.c_int(0)
    img_arr = (ctypes.c_ubyte * len(image_bytes)).from_buffer_copy(image_bytes)
    with SDK_LOCK:
        rc = fx_dll.FX_extractFeatures(FX_CTX, len(image_bytes), ctypes.cast(img_arr, ctypes.c_void_p),
                                       purpose, feat_size, ctypes.cast(buf, ctypes.c_void_p),
                                       ctypes.byref(img_q), ctypes.byref(ftr_q), ctypes.byref(created))
    if rc != 0:
        log("FX_extractFeatures rc=%d imgQ=%d ftrQ=%d" % (rc, img_q.value, ftr_q.value))
        return None, img_q.value, ftr_q.value
    if not created.value:
        return None, img_q.value, ftr_q.value
    return bytes(bytearray(buf)), img_q.value, ftr_q.value


def make_template(feature_sets):
    """feature_sets: lista de bytes (cada uno un feature set FT_PRE_REG_FTR). -> bytes template o None."""
    n = len(feature_sets)
    if n < DEV.enroll_feature_sets:
        return None
    feat_size = DEV.feat_len_recommended or DEV.feat_len_minimum or 2048
    tmpl_size = DEV.tmpl_len_recommended or DEV.tmpl_len_minimum or 2048
    # array de punteros a cada feature set (de tamaño feat_size; rellenamos)
    bufs = []
    ptr_arr = (ctypes.POINTER(ctypes.c_ubyte) * n)()
    for i, fs in enumerate(feature_sets):
        b = (ctypes.c_ubyte * feat_size)()
        src = fs[:feat_size]
        ctypes.memmove(b, src, len(src))
        bufs.append(b)
        ptr_arr[i] = ctypes.cast(b, ctypes.POINTER(ctypes.c_ubyte))
    out = (ctypes.c_ubyte * tmpl_size)()
    created = ctypes.c_int(0)
    with SDK_LOCK:
        rc = mc_dll.MC_generateRegFeatures(MC_CTX, 0, n, feat_size, ptr_arr, tmpl_size,
                                           ctypes.cast(out, ctypes.c_void_p), None, ctypes.byref(created))
    if rc != 0 or not created.value:
        log("MC_generateRegFeatures rc=%d created=%d" % (rc, created.value))
        return None
    return bytes(bytearray(out))


def verify(template_bytes, feature_set_bytes):
    """Devuelve (decision_bool, achieved_far)."""
    far = ctypes.c_double(0.0)
    decision = ctypes.c_int(0)
    tmpl_arr = (ctypes.c_ubyte * len(template_bytes)).from_buffer_copy(template_bytes)
    feat_arr = (ctypes.c_ubyte * len(feature_set_bytes)).from_buffer_copy(feature_set_bytes)
    with SDK_LOCK:
        rc = mc_dll.MC_verifyFeaturesEx(MC_CTX,
                                        len(template_bytes), ctypes.cast(tmpl_arr, ctypes.c_void_p),
                                        len(feature_set_bytes), ctypes.cast(feat_arr, ctypes.c_void_p),
                                        0, None, None, None,
                                        ctypes.byref(far), ctypes.byref(decision))
    if rc != 0:
        log("MC_verifyFeaturesEx rc=%d" % rc)
        return False, 1.0
    return bool(decision.value), far.value


# ---------------------------------------------------------------------------
# Templates en disco
# ---------------------------------------------------------------------------
def load_all_templates():
    TEMPLATES.clear()
    if not os.path.isdir(PRINTS_DIR):
        os.makedirs(PRINTS_DIR, exist_ok=True)
        return
    for uid in os.listdir(PRINTS_DIR):
        d = os.path.join(PRINTS_DIR, uid)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.lower().endswith(".fpt"):
                continue
            finger = fn[:-4]
            try:
                with open(os.path.join(d, fn), "rb") as f:
                    TEMPLATES.setdefault(uid, {})[finger] = f.read()
            except Exception as e:
                log("No se pudo cargar %s/%s: %s" % (uid, fn, e))
    log("Templates cargados: %d usuario(s)" % len(TEMPLATES))

def save_template(user_id, finger, template_bytes, write_disk=True):
    if write_disk:
        d = os.path.join(PRINTS_DIR, str(user_id))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "%s.fpt" % finger), "wb") as f:
            f.write(template_bytes)
    with TEMPLATES_LOCK:
        TEMPLATES.setdefault(str(user_id), {})[finger] = template_bytes

def clear_templates(wipe_disk=False):
    with TEMPLATES_LOCK:
        TEMPLATES.clear()
    if wipe_disk and os.path.isdir(PRINTS_DIR):
        for uid in list(os.listdir(PRINTS_DIR)):
            d = os.path.join(PRINTS_DIR, uid)
            if not os.path.isdir(d):
                continue
            for fn in list(os.listdir(d)):
                if fn.lower().endswith(".fpt"):
                    try: os.remove(os.path.join(d, fn))
                    except Exception: pass
            try: os.rmdir(d)
            except Exception: pass

def delete_user_templates(user_id):
    d = os.path.join(PRINTS_DIR, str(user_id))
    removed = 0
    if os.path.isdir(d):
        for fn in os.listdir(d):
            try:
                os.remove(os.path.join(d, fn)); removed += 1
            except Exception:
                pass
        try: os.rmdir(d)
        except Exception: pass
    with TEMPLATES_LOCK:
        TEMPLATES.pop(str(user_id), None)
    return removed

def prints_summary():
    with TEMPLATES_LOCK:
        return {uid: len(fingers) for uid, fingers in TEMPLATES.items()}


# ---------------------------------------------------------------------------
# Operaciones de alto nivel
# ---------------------------------------------------------------------------
def do_identify_nonblocking():
    """Modelo polling: si hay imagen reciente -> identifica; si no -> {waiting:true}."""
    if time.monotonic() < DEV.cooling_until:
        return ("cooling", None, None)
    # si hay un enroll en curso (OP_LOCK tomado) no bloqueamos: respondemos waiting
    if not OP_LOCK.acquire(blocking=False):
        return ("waiting", None, None)
    try:
        img = peek_recent_image(max_age_s=2.5)
        if img is None:
            return ("waiting", None, None)
        fs, iq, fq = extract_features(img, FT_VER_FTR)
        if fs is None:
            log("Identify: extraccion fallo (imgQ=%d ftrQ=%d)" % (iq, fq))
            return ("nomatch", None, None)
        best_uid, best_finger, best_far = None, None, 2.0
        with TEMPLATES_LOCK:
            snapshot = {uid: dict(f) for uid, f in TEMPLATES.items()}
        for uid, fingers in snapshot.items():
            for finger, tmpl in fingers.items():
                ok, far = verify(tmpl, fs)
                if ok and far < best_far:
                    best_uid, best_finger, best_far = uid, finger, far
        if best_uid is not None:
            log("Identify: MATCH user=%s finger=%s far=%.6f" % (best_uid, best_finger, best_far))
            return ("match", best_uid, best_finger)
        log("Identify: sin coincidencia")
        return ("nomatch", None, None)
    finally:
        OP_LOCK.release()


def do_enroll(user_id, finger):
    """Bloqueante: captura N toques (DEV.enroll_feature_sets) y genera el template.
       Publica progreso en ENROLL_STATE; se puede cancelar con ENROLL_CANCEL."""
    with OP_LOCK:
        needed = DEV.enroll_feature_sets
        ENROLL_CANCEL.clear()
        _enroll_set(active=True, done=0, needed=needed, user=str(user_id), finger=str(finger),
                    msg="Coloque el dedo en el lector (toque 1 de %d)" % needed, result=None)
        feats = []
        with DEV.lock:
            DEV.last_image = None
        log("Enroll inicio user=%s finger=%s (necesita %d toques)" % (user_id, finger, needed))
        attempts = 0
        try:
            while len(feats) < needed and attempts < needed * 5:
                if ENROLL_CANCEL.is_set():
                    _enroll_set(active=False, msg="Cancelado", result="cancel")
                    return False, "Cancelado por el usuario", None
                attempts += 1
                _enroll_set(msg="Coloque el dedo (toque %d de %d)..." % (len(feats) + 1, needed))
                img = grab_fresh_image(ENROLL_TOUCH_WAIT_S, cancel_event=ENROLL_CANCEL)
                if ENROLL_CANCEL.is_set():
                    _enroll_set(active=False, msg="Cancelado", result="cancel")
                    return False, "Cancelado por el usuario", None
                if img is None:
                    _enroll_set(active=False, msg="Tiempo agotado esperando el toque %d/%d" % (len(feats) + 1, needed), result="timeout")
                    return False, "Tiempo agotado esperando el toque %d/%d (¿el lector está entregando eventos? probá cerrar agentes DigitalPersona o correr el servicio como admin)" % (len(feats) + 1, needed), None
                fs, iq, fq = extract_features(img, FT_PRE_REG_FTR)
                if fs is None:
                    log("Enroll: toque rechazado (imgQ=%d ftrQ=%d) — repetir" % (iq, fq))
                    _enroll_set(msg="Dedo poco claro, intente de nuevo (toque %d de %d)" % (len(feats) + 1, needed))
                    time.sleep(0.4)
                    continue
                feats.append(fs)
                log("Enroll: toque %d/%d aceptado" % (len(feats), needed))
                _enroll_set(done=len(feats),
                            msg=("Toque %d de %d OK — generando..." % (len(feats), needed)) if len(feats) >= needed
                                 else ("Toque %d de %d OK — levante el dedo y vuelva a ponerlo" % (len(feats), needed)))
                time.sleep(0.3)
            if len(feats) < needed:
                _enroll_set(active=False, msg="No se completaron los toques", result="fail")
                return False, "No se lograron %d capturas validas" % needed, None
            tmpl = make_template(feats)
            if tmpl is None:
                _enroll_set(active=False, msg="No se pudo generar el template", result="fail")
                return False, "No se pudo generar el template (intente de nuevo)", None
            save_template(user_id, finger, tmpl)
            log("Enroll OK user=%s finger=%s tmpl=%d bytes" % (user_id, finger, len(tmpl)))
            _enroll_set(active=False, done=needed, msg="Registrado", result="ok")
            return True, None, tmpl
        finally:
            with ENROLL_LOCK:
                ENROLL_STATE["active"] = False


# ---------------------------------------------------------------------------
# Servidor HTTP
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FactuPOSFingerprintPy/" + VERSION

    def log_message(self, fmt, *args):
        pass  # silenciamos el log por defecto de http.server

    # --- helpers ---
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length", "0") or "0")
            if n <= 0:
                return {}
            raw = self.rfile.read(n)
            return json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return {}

    # --- verbos ---
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            if path == "/status":
                with DEV.lock:
                    conn = DEV.device_connected
                    serial = DEV.device_serial
                    product = DEV.device_product
                self._send_json({
                    "ok": True,
                    "service": "factupos-fingerprint",
                    "version": VERSION,
                    "platform": "windows-python",
                    "matching": "minutiae",
                    "device_connected": conn,
                    "connected": conn,
                    "device": (product + " " + serial).strip() if conn else "",
                    "device_serial": serial,
                    "users_enrolled": len(prints_summary()),
                    "enroll_stages": DEV.enroll_feature_sets,
                    "cooling_down": time.monotonic() < DEV.cooling_until,
                    "acq_priority": DEV.acq_priority,
                    "sdk_loaded": dpfp_dll is not None,
                    "ev_counts": {(_EV_NAMES.get(k, str(k))): v for k, v in DEV.ev_counts.items()},
                })
            elif path == "/get_connection":
                with DEV.lock:
                    conn = DEV.device_connected
                    serial = DEV.device_serial
                    product = DEV.device_product
                self._send_json({
                    "ok": True,
                    "connected": conn,
                    "device": (product + " " + serial).strip() if conn else "",
                    "device_id": serial,
                    "enroll_stages": DEV.enroll_feature_sets,
                    "matching": "minutiae",
                })
            elif path == "/prints":
                self._send_json({"ok": True, "users": prints_summary()})
            elif path == "/fingerprint/enroll/progress":
                pg = _enroll_get()
                pg["ok"] = True
                self._send_json(pg)
            else:
                self._send_json({"ok": False, "error": "ruta no encontrada"}, 404)
        except Exception:
            log("Excepcion en GET %s:\n%s" % (path, traceback.format_exc()))
            self._send_json({"ok": False, "error": "error interno"}, 500)

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            if path == "/fingerprint/identify":
                with DEV.lock:
                    conn = DEV.device_connected
                if not conn:
                    self._send_json({"ok": False, "error": "lector no conectado"}, 503)
                    return
                state, uid, finger = do_identify_nonblocking()
                if state == "cooling":
                    self._send_json({"ok": False, "error": "sensor enfriando"}, 503)
                elif state == "waiting":
                    self._send_json({"ok": True, "waiting": True})
                elif state == "match":
                    self._send_json({"ok": True, "matched": True, "user_id": uid, "finger": finger})
                else:  # nomatch
                    self._send_json({"ok": True, "matched": False})
            elif path == "/fingerprint/enroll":
                data = self._read_json()
                user_id = str(data.get("user_id", "")).strip()
                finger  = str(data.get("finger", "right-index")).strip() or "right-index"
                if not user_id:
                    self._send_json({"ok": False, "error": "falta user_id"}, 400)
                    return
                with DEV.lock:
                    conn = DEV.device_connected
                if not conn:
                    self._send_json({"ok": False, "error": "lector no conectado"}, 503)
                    return
                ok, err, tmpl = do_enroll(user_id, finger)
                if ok:
                    with DEV.lock:
                        serial = DEV.device_serial
                    self._send_json({
                        "ok": True, "user_id": user_id, "finger": finger,
                        "platform": "windows",
                        "serial": serial,
                        "template_b64": base64.b64encode(tmpl).decode("ascii"),
                    })
                else:
                    self._send_json({"ok": False, "error": err or "enroll fallo"})
            elif path == "/prints/import":
                # Inyectar uno o varios templates en memoria (+ cache a disco). Usado por el kiosko
                # para cargar las plantillas guardadas en la BD via la API web.
                data = self._read_json()
                items = data.get("huellas")
                if not isinstance(items, list):
                    items = [data]
                n = 0; bad = 0
                for it in items:
                    try:
                        uid = str(it.get("user_id") or it.get("usuario_codigo") or "").strip()
                        finger = str(it.get("finger") or it.get("dedo") or "right-index").strip() or "right-index"
                        b64 = it.get("template_b64") or it.get("template")
                        if not uid or not b64:
                            bad += 1; continue
                        raw = base64.b64decode(b64)
                        if len(raw) < 16:
                            bad += 1; continue
                        save_template(uid, finger, raw, write_disk=bool(data.get("write_disk", True)))
                        n += 1
                    except Exception:
                        bad += 1
                self._send_json({"ok": True, "imported": n, "bad": bad, "users": len(prints_summary())})
            elif path == "/prints/clear":
                data = self._read_json()
                clear_templates(wipe_disk=bool(data.get("wipe_disk", False)))
                self._send_json({"ok": True, "users": len(prints_summary())})
            elif path == "/prints/reload":
                load_all_templates()
                self._send_json({"ok": True, "users": len(prints_summary())})
            elif path == "/fingerprint/enroll/cancel":
                ENROLL_CANCEL.set()
                _enroll_set(msg="Cancelando...")
                self._send_json({"ok": True})
            elif path == "/fingerprint/capture":
                # compat: devuelve si hay imagen reciente (no PNG, solo flag)
                img = peek_recent_image(2.5)
                self._send_json({"ok": img is not None, "has_image": img is not None})
            else:
                self._send_json({"ok": False, "error": "ruta no encontrada"}, 404)
        except Exception:
            log("Excepcion en POST %s:\n%s" % (path, traceback.format_exc()))
            self._send_json({"ok": False, "error": "error interno"}, 500)

    def do_DELETE(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            if path.startswith("/prints/"):
                uid = path[len("/prints/"):]
                removed = delete_user_templates(uid)
                self._send_json({"ok": True, "removed": removed})
            else:
                self._send_json({"ok": False, "error": "ruta no encontrada"}, 404)
        except Exception:
            self._send_json({"ok": False, "error": "error interno"}, 500)


def run_http_server():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    if os.path.isfile(CERT_FILE) and os.path.isfile(KEY_FILE):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    else:
        scheme = "http"
        log("ADVERTENCIA: no se encontro certs/cert.pem — sirviendo en HTTP plano")
    log("HTTP server escuchando en %s://127.0.0.1:%d" % (scheme, PORT))
    httpd.serve_forever()


# ---------------------------------------------------------------------------
# Bandeja del sistema (opcional, sin dependencias: usa Shell_NotifyIcon via ctypes)
# ---------------------------------------------------------------------------
# (Se omite por simplicidad: la consola/ventana del proceso sirve de "tray".
#  Para correrlo sin ventana usar pythonw.exe; para detenerlo, matar el proceso.)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def _liberar_lector():
    """Best-effort: cerrar lo que acapara el lector (servicio C# viejo, agentes DigitalPersona,
       Servicio biometrico de Windows). Requiere admin para que funcione; si no, no pasa nada."""
    import subprocess
    SW = subprocess.SW_HIDE if hasattr(subprocess, "SW_HIDE") else 0
    si = subprocess.STARTUPINFO()
    try:
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 0
    except Exception:
        si = None
    def run(args):
        try:
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=15, startupinfo=si, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            pass
    run(["schtasks", "/change", "/tn", "FactuPOS Fingerprint", "/disable"])
    run(["schtasks", "/end",    "/tn", "FactuPOS Fingerprint"])
    for x in ("FingerprintService.exe", "DPAgent.exe", "DpAgnt.exe", "DPApp.exe",
              "OneTouch.exe", "FpAgent.exe", "DPClientSrv.exe", "dpcardengine.exe"):
        run(["taskkill", "/F", "/T", "/IM", x])
    run(["net", "stop", "WbioSrvc"])
    run(["net", "start", "DpHostW"])
    log("Limpieza del lector ejecutada (best-effort).")


def _lanzar_kiosko():
    """Lanza la interfaz del kiosko (FactuposKiosko.exe si esta compilado, si no kiosk.py con pythonw)."""
    import subprocess
    try:
        if getattr(sys, "frozen", False):
            exe = os.path.join(BASE_DIR, "FactuposKiosko.exe")
            if not os.path.isfile(exe):
                log("No se encontro FactuposKiosko.exe junto al servicio; no se lanza el kiosko.")
                return
            cmd = [exe]
        else:
            kpy = os.path.join(BASE_DIR, "kiosk.py")
            if not os.path.isfile(kpy):
                return
            pyw = sys.executable
            cand = pyw.lower().replace("python.exe", "pythonw.exe")
            if os.path.isfile(cand):
                pyw = cand
            cmd = [pyw, kpy]
        subprocess.Popen(cmd, cwd=BASE_DIR, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        log("Kiosko lanzado: %s" % " ".join(cmd))
    except Exception as e:
        log("No se pudo lanzar el kiosko: %s" % e)


def main():
    os.makedirs(PRINTS_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    log("=" * 60)
    log("FactuPOS Biometria - Servicio de Huella v%s (build %s)  puerto %d" % (VERSION, BUILD_DATE, PORT))
    log("BASE_DIR=%s  frozen=%s" % (BASE_DIR, getattr(sys, "frozen", False)))
    log("=" * 60)

    if sys.platform != "win32":
        log("ERROR: este servicio es solo para Windows.")
        sys.exit(1)

    # Single-instance check: si ya hay un servicio escuchando en el puerto, salir
    # (evita que un segundo INICIAR.bat o el auto-inicio lance un kiosko duplicado).
    try:
        import socket as _sock
        _probe = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        _probe.settimeout(0.5)
        if _probe.connect_ex(("127.0.0.1", PORT)) == 0:
            _probe.close()
            log("Ya hay otra instancia del servicio escuchando en 127.0.0.1:%d — salgo (no lanzo otro kiosko)." % PORT)
            sys.exit(0)
        _probe.close()
    except Exception:
        pass

    args = set(a.lower() for a in sys.argv[1:])
    if "--no-cleanup" not in args:
        _liberar_lector()
    if "--no-kiosk" not in args:
        _lanzar_kiosko()

    load_all_templates()

    try:
        init_sdk()
    except SdkUnavailable as e:
        log("ERROR inicializando el SDK DigitalPersona: %s" % e)
        log("Verifica: (1) el RTE del 'DigitalPersona One Touch SDK' instalado, "
            "(2) el servicio 'DigitalPersona ... (DpHostW)' corriendo, "
            "(3) el lector U.are.U 4500 conectado, "
            "(4) que Python y el RTE sean de la misma arquitectura (32/64 bits).")
        # seguimos levantando el HTTP igual para que /status reporte el error
    except Exception:
        log("ERROR inesperado en init_sdk:\n" + traceback.format_exc())

    # HTTP en hilo daemon
    t = threading.Thread(target=run_http_server, name="http", daemon=True)
    t.start()

    # message loop en el hilo principal (necesario para recibir las notificaciones)
    if DEV.hwnd:
        log("Entrando al message loop. Cierra la ventana/proceso para detener.")
        msg = MSG()
        while True:
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        log("Message loop terminado.")
    else:
        # sin ventana (SDK no disponible): solo mantener el HTTP vivo
        log("Sin ventana de adquisicion (SDK no disponible). El HTTP sigue activo para /status.")
        while True:
            time.sleep(3600)

    shutdown_sdk()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        log("FATAL:\n" + traceback.format_exc())
        sys.exit(1)
