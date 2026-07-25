#!/usr/bin/env python3
"""
Servicio local de huella digital para FactuPOS (Linux) v2.2.0
Usa libfprint2 identify_sync/enroll_sync en thread dedicado.
NO usa GLib MainLoop (async callbacks no funcionan con este driver).

Endpoints:
  GET    /get_connection            - Info del dispositivo
  GET    /status                    - Estado del servicio
  GET    /prints                    - Lista de prints registrados
  GET    /fingerprint/enroll/progress - Progreso del enroll en curso (done/needed/msg)
  POST   /fingerprint/enroll        - Enrolar dedo (N toques). Devuelve template_b64 + serial
  POST   /fingerprint/enroll/cancel - Cancela el enroll en curso
  POST   /fingerprint/identify      - Identificar dedo
  POST   /fingerprint/capture       - Captura imagen (compatibilidad)
  POST   /prints/clear              - Vacia los prints en memoria (y disco si wipe_disk)
  POST   /prints/import             - Importa templates desde la BD (base64) a memoria/disco
  POST   /prints/reload             - Recarga los prints desde el disco
  DELETE /prints/:user_id           - Eliminar prints de un usuario
  GET    /update/check              - Consulta si hay version nueva (sin aplicar)
  POST   /update                    - Busca, descarga y aplica la actualizacion (reinicia)

Cambios v2.2.0 (kiosko Linux):
  - /prints/clear + /prints/import  -> el kiosko standalone sincroniza las huellas desde la BD
  - /fingerprint/enroll/progress + /cancel -> progreso y cancelacion del registro
  - /fingerprint/enroll ahora devuelve template_b64 (para guardar en la BD) y serial
"""

import functools
print = functools.partial(print, flush=True)

import json
import ssl
import base64
import io
import os
import glob
import shutil
import fcntl
import threading
import time
import signal
import sys
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

import gi
from gi.repository import GLib, Gio   # python3-gi (siempre presente)
# El binding de libfprint (gir1.2-fprint-2.0 + libfprint-2-2) es opcional al ARRANQUE:
# si falta, el servicio igual levanta (HTTP/status responde y el auto-update funciona),
# solo que reporta el lector como no disponible. Antes un import fallido mataba el
# proceso entero -> systemd entraba en crash-loop -> "el servicio no levanta".
try:
    gi.require_version('FPrint', '2.0')
    from gi.repository import FPrint
    FPRINT_OK = True
    FPRINT_ERR = ''
except Exception as _e:
    FPrint = None
    FPRINT_OK = False
    FPRINT_ERR = 'libfprint no disponible: %s — instala: sudo apt install gir1.2-fprint-2.0 libfprint-2-2' % _e

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

VERSION = '2.5.2'
# v2.5.2: auto-chequeo cada 1 HORA (antes 6h).
# v2.5.1: página web de estado con TEMA OSCURO en GET / (https://127.0.0.1:52181/):
#         dashboard navy autocontenido que muestra versión, servicio activo, lector y
#         libfprint, auto-refresh cada 3s. Sirve además como prueba VISIBLE del
#         auto-update (en 2.5.0 GET / daba 404; en 2.5.1 aparece el panel oscuro).
# v2.5.0: AUTO-ACTUALIZACIÓN (igual que el FactuPOS Panel). El servicio lee un
#         manifiesto JSON publicado en descargas; si hay versión mayor baja el .py,
#         lo valida (sintaxis + contenido), lo reemplaza EN SITIO (corre como root)
#         y se reinicia (systemd Restart=always lo relevanta con el .py nuevo).
#         Auto-check a los 20s y cada 6h + endpoints para el botón del kiosko:
#         GET /update/check (solo consulta) y POST /update (consulta + aplica).
#         No reinicia si hay un enroll/identify en curso (espera a que termine).
# v2.4.5: cuando el lector se cuelga a nivel USB (lo que se arregla desconectando/
#         reconectando el cable), el watchdog hace un RESET USB por software (ioctl
#         USBDEVFS_RESET al device 05ba = replug sin tocar el cable) + reinicio limpio.
#         Recupera solo sin intervención física.
# v2.4.4: AUTO-REPARACIÓN. systemd con StartLimitIntervalSec=0 (nunca se rinde tras
#         crashes) + watchdog que, si no recupera el lector en 2 intentos, fuerza un
#         reinicio limpio del proceso (os._exit -> systemd lo relevanta fresco, que es
#         lo que sí restablece el lector). El kiosko muestra botón "Reiniciar servicio".
# v2.4.3: FIX CRÍTICO — al abrir el kiosko se caía el servicio. Causa: cancelar el
#         identify_sync en vuelo (Gio.Cancellable desde un timer) CRASHEA el uru4000.
#         Ahora identify corre en un hilo SIN cancelar (modelo polling): si no hay dedo
#         devuelve {waiting}; el resultado se entrega en el siguiente poll. No más crash.
# v2.4.2: FIX CRÍTICO del loop "inicia y se cae". _reinit_device creaba un FPrint.Context
#         NUEVO en cada recuperación -> crash tod_shared_drivers_register. Ahora se usa
#         UN SOLO contexto global (fp_ctx) en todo el proceso.
# v2.4.1: arregla el flapping "detectado/no-detectado". El lector solo se marca caído
#         si FALLA EL OPEN (desconexión real), con 1 reintento; los errores normales de
#         lectura ya NO lo marcan caído.
# v2.4.0: ROBUSTEZ — el servicio ya no se cae ni queda inservible. Si una operación
#         falla, marca el lector "caído" y un watchdog lo RECUPERA solo cada 5s
#         (reinicializa el contexto). Si el lector no está al arrancar, el servicio
#         igual levanta (status responde) y se recupera al reconectarlo.
# v2.3.0: open/close del lector POR OPERACIÓN (identify/enroll/capture abren y cierran
#         el device). Antes quedaba abierto entre operaciones -> LED prendido y la 2.ª
#         operación segfaulteaba el driver uru4000 y tumbaba el servicio.
# v2.3.1: identify con TIMEOUT real (Gio.Cancellable). Antes identify_sync sin dedo
#         bloqueaba para siempre reteniendo dev_lock -> el servicio quedaba "trabado"
#         con toques muy seguidos y ya no marcaba ni registraba. Ahora hace timeout,
#         devuelve {waiting:True} y SIEMPRE suelta el lock. + settle al cerrar el lector.

# --- Config ---
HOST = '127.0.0.1'
PORT = 52181
CERT_DIR = '/opt/factupos-fingerprint-servicio/certs'
CERT_FILE = f'{CERT_DIR}/cert.pem'
KEY_FILE = f'{CERT_DIR}/key.pem'
PRINTS_DIR = '/opt/factupos-fingerprint-servicio/prints'

# --- Auto-actualización ---
# Manifiesto JSON publicado en la MISMA carpeta de descargas que el .deb. El
# servicio lo lee, y si hay versión mayor baja el .py y se reinicia (systemd lo
# relevanta con el archivo nuevo). Corre como root => escribe el .py en sitio.
UPDATE_BASE = 'https://soportereal.com/software/factupos-app/linux'
UPDATE_MANIFEST = UPDATE_BASE + '/factupos-fingerprint-servicio_version.json'
UPDATE_PY_FALLBACK = UPDATE_BASE + '/fingerprint_service.py'
UPDATE_INTERVAL = 1 * 3600   # re-chequeo cada 1 hora
SELF_PATH = os.path.abspath(__file__)

# --- Globals ---
device_name = None
device_driver = None
device_ready = False
fp_dev = None
fp_ctx = None   # UN SOLO FPrint.Context en todo el proceso (crear 2 -> crash tod_shared_drivers_register)
enroll_stages = 5
cooling_down = False

# Lock para serializar acceso al dispositivo (solo 1 operación a la vez)
dev_lock = threading.Lock()

# Prints en memoria
loaded_prints = {}  # user_id -> [FPrint.Print, ...]

# Estado del enroll en curso (para /fingerprint/enroll/progress)
ENROLL_STATE = {'active': False, 'done': 0, 'needed': enroll_stages, 'msg': ''}
ENROLL_CANCEL = None  # Gio.Cancellable del enroll activo

# Estado del identify (modelo polling sin cancelar el lector)
IDENTIFY = {'busy': False, 'result': None}

# Estado de la auto-actualización (para /update/check sin tocar la red)
UPDATE_STATE = {'checking': False, 'last_check': 0, 'latest': None,
                'available': False, 'msg': ''}


def _dev_open():
    """Abre el lector si está cerrado. Idempotente.
    Si el open FALLA (desconexión real), marca el lector caído para que el watchdog
    lo recupere — pero NO marcamos caído por errores de lectura normales (evita flapping)."""
    try:
        if fp_dev and fp_dev.is_open():
            return
    except Exception:
        pass
    last = None
    for attempt in range(2):
        try:
            fp_dev.open_sync()
            return
        except Exception as e:
            last = e
            if attempt == 0:
                time.sleep(0.3)   # reintento ante hipo transitorio del USB
    _mark_dev_down(f'open falló: {last}')
    raise last


def _dev_close():
    """Cierra el lector: apaga el LED y resetea el driver. Best-effort, nunca lanza.
    Clave para uru4000: dejarlo abierto entre operaciones deja la captura activa
    (LED prendido) y hace que la 2.ª operación segfaultee y tumbe el servicio."""
    if not fp_dev:
        return
    try:
        fp_dev.close_sync()
        time.sleep(0.15)   # settle: el uru4000 necesita un respiro antes del próximo open
    except Exception as e:
        print(f"[FP] aviso al cerrar lector: {e}")


def _reinit_device():
    """(Re)inicializa el lector: recrea el contexto y lo abre/cierra para leer su info.
    Deja device_ready=True si lo logra. Best-effort, nunca lanza."""
    global fp_dev, fp_ctx, device_name, device_driver, enroll_stages, device_ready
    if not FPRINT_OK:
        device_ready = False
        return False
    try:
        try:
            if fp_dev and fp_dev.is_open():
                fp_dev.close_sync()
        except Exception:
            pass
        # UN SOLO contexto en todo el proceso: crear un segundo crashea el driver.
        if fp_ctx is None:
            fp_ctx = FPrint.Context()
        devs = fp_ctx.get_devices()
        if not devs:
            device_ready = False
            return False
        fp_dev = devs[0]
        fp_dev.open_sync()
        device_name = fp_dev.get_name()
        device_driver = fp_dev.get_driver()
        enroll_stages = fp_dev.get_nr_enroll_stages()
        ENROLL_STATE['needed'] = enroll_stages
        try:
            fp_dev.close_sync()   # modelo open/close: queda cerrado entre operaciones
        except Exception:
            pass
        device_ready = True
        print(f"[FP] (re)init OK: {device_name} ({device_driver}), {enroll_stages} stages")
        return True
    except Exception as e:
        print(f"[FP] reinit del lector falló: {e}")
        device_ready = False
        return False


USBDEVFS_RESET = (ord('U') << 8) | 20   # ioctl USBDEVFS_RESET = _IO('U', 20)

def _usb_reset_reader():
    """Reset USB por software del lector (vendor 05ba DigitalPersona) = 'replug'
    sin tocar el cable. Recupera el lector cuando se cuelga a nivel USB."""
    done = False
    for dev in glob.glob('/sys/bus/usb/devices/*'):
        try:
            vid = open(os.path.join(dev, 'idVendor')).read().strip().lower()
        except Exception:
            continue
        if vid != '05ba':   # DigitalPersona
            continue
        try:
            busnum = int(open(os.path.join(dev, 'busnum')).read().strip())
            devnum = int(open(os.path.join(dev, 'devnum')).read().strip())
        except Exception:
            continue
        path = '/dev/bus/usb/%03d/%03d' % (busnum, devnum)
        try:
            fd = os.open(path, os.O_WRONLY)
            try:
                fcntl.ioctl(fd, USBDEVFS_RESET, 0)
                print(f"[FP] USB reset OK: {path} (05ba)")
                done = True
            finally:
                os.close(fd)
        except Exception as e:
            print(f"[FP] USB reset falló en {path}: {e}")
    if not done:
        print("[FP] USB reset: no se encontró el lector 05ba")
    return done


def _mark_dev_down(reason=''):
    """Marca el lector como caído para que el watchdog lo recupere."""
    global device_ready
    device_ready = False
    print(f"[FP] lector marcado caído ({reason}); el watchdog lo recuperará")


def _watchdog():
    """Hilo de auto-reparación. Si el lector queda caído, intenta recuperarlo en proceso;
    si no lo logra en 2 intentos, fuerza un REINICIO LIMPIO del proceso (systemd lo relevanta
    fresco, que es lo que sí funciona). Con StartLimitIntervalSec=0 systemd nunca se rinde."""
    fails = 0
    while True:
        time.sleep(5)
        # Si falta el binding de libfprint, reiniciar NO sirve (no es un cuelgue del
        # lector): el HTTP queda arriba reportando el problema y NO entramos en loop.
        if not FPRINT_OK:
            continue
        if device_ready or cooling_down:
            fails = 0
            continue
        ok = False
        if dev_lock.acquire(timeout=1):
            try:
                print("[FP] watchdog: lector caído, intentando recuperar...")
                ok = _reinit_device()
            except Exception as e:
                print(f"[FP] watchdog error: {e}")
                ok = False
            finally:
                dev_lock.release()
        if ok:
            fails = 0
            print("[FP] watchdog: lector recuperado")
        else:
            fails += 1
            print(f"[FP] watchdog: recuperación falló ({fails}/2)")
            if fails >= 2:
                # El lector suele estar colgado a nivel USB: reset USB (= replug por
                # software) y reinicio limpio (systemd arranca fresco con el USB ya reseteado).
                print("[SVC] watchdog: reset USB del lector + reinicio limpio")
                try:
                    if fp_dev:
                        fp_dev.close_sync()
                except Exception:
                    pass
                _usb_reset_reader()
                time.sleep(1.5)   # dar tiempo a la re-enumeración USB
                os._exit(1)


def ensure_dirs():
    os.makedirs(PRINTS_DIR, exist_ok=True)
    os.makedirs(CERT_DIR, exist_ok=True)


def image_to_png(image):
    if not image:
        return None
    width = image.get_width()
    height = image.get_height()
    data = image.get_data()
    if not data or width == 0 or height == 0:
        return None
    if HAS_PIL:
        img = Image.frombytes('L', (width, height), bytes(data))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()
    return None


def _print_to_raw(fp_print):
    """Serializa un FPrint.Print a bytes."""
    data = fp_print.serialize()
    return bytes(data) if isinstance(data, (bytes, bytearray)) else bytes(data.get_data())


def save_print(user_id, finger_name, fp_print):
    user_dir = os.path.join(PRINTS_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)
    raw = _print_to_raw(fp_print)
    path = os.path.join(user_dir, f'{finger_name}.fpr')
    with open(path, 'wb') as f:
        f.write(raw)
    print(f"[FP] Print guardado: {path} ({len(raw)} bytes)")
    return path


def load_all_prints():
    global loaded_prints
    loaded_prints = {}
    if not os.path.exists(PRINTS_DIR):
        return
    for user_dir in os.listdir(PRINTS_DIR):
        user_path = os.path.join(PRINTS_DIR, user_dir)
        if not os.path.isdir(user_path):
            continue
        prints = []
        for fpr_file in glob.glob(os.path.join(user_path, '*.fpr')):
            try:
                with open(fpr_file, 'rb') as f:
                    raw = f.read()
                fp_print = FPrint.Print.deserialize(list(raw))
                if fp_print:
                    prints.append(fp_print)
            except Exception as e:
                print(f"[FP] Error cargando {fpr_file}: {e}")
        if prints:
            loaded_prints[user_dir] = prints
    total = sum(len(v) for v in loaded_prints.values())
    print(f"[FP] {total} prints cargados de {len(loaded_prints)} usuarios")


def handle_overheating():
    global device_ready, cooling_down
    if cooling_down:
        return
    cooling_down = True
    device_ready = False
    print("[FP] Sensor sobrecalentado, cooldown 20s...")
    def cooldown():
        global device_ready, cooling_down
        time.sleep(20)
        device_ready = True
        cooling_down = False
        print("[FP] Sensor recuperado")
    threading.Thread(target=cooldown, daemon=True).start()


def _identify_worker(all_prints, print_to_user):
    """Corre en un hilo: identify_sync BLOQUEANTE (sin cancelar -> no crashea el uru4000).
    Cachea el resultado en IDENTIFY['result'] y suelta dev_lock al terminar."""
    res = None
    try:
        _dev_open()
        print(f"[FP] Identify: esperando dedo ({len(all_prints)} prints)...")
        result = fp_dev.identify_sync(all_prints)
        fp_match = result[0]
        if fp_match is not None:
            user_id = None
            try:
                match_data = bytes(fp_match.serialize())
            except Exception:
                match_data = None
            if match_data:
                for i, p in enumerate(all_prints):
                    try:
                        if bytes(p.serialize()) == match_data:
                            user_id = print_to_user.get(i)
                            break
                    except Exception:
                        continue
            if not user_id:
                user_id = fp_match.get_username() or fp_match.get_description()
            if not user_id and len(loaded_prints) == 1:
                user_id = list(loaded_prints.keys())[0]
            print(f"[FP] Identificado: {user_id}")
            res = {'ok': True, 'matched': True, 'user_id': user_id}
        else:
            print("[FP] No identificado")
            res = {'ok': True, 'matched': False}
    except Exception as e:
        err = str(e)
        print(f"[FP] Error identify: {err}")
        if 'overheating' in err.lower() or 'disabled' in err.lower():
            handle_overheating()
        res = {'ok': False, 'error': err}
    finally:
        _dev_close()
        IDENTIFY['result'] = res
        IDENTIFY['busy'] = False
        dev_lock.release()


def do_identify(timeout=10):
    """Modelo POLLING: NO cancela el lector (cancelar un sync en vuelo crashea el uru4000).
    Lanza la lectura en un hilo; si no llega dedo en `timeout`, devuelve {waiting:True} y el
    hilo sigue esperando. El resultado del dedo se entrega en el siguiente poll."""
    if not device_ready or not fp_dev:
        return {'ok': False, 'error': 'Dispositivo no disponible'}

    # ¿hay un resultado pendiente de una lectura previa? entregarlo
    if IDENTIFY['result'] is not None:
        r = IDENTIFY['result']; IDENTIFY['result'] = None
        return r
    # ¿ya hay una lectura en curso esperando dedo?
    if IDENTIFY['busy']:
        return {'ok': True, 'waiting': True}

    all_prints = []
    print_to_user = {}
    idx = 0
    for uid, prints in loaded_prints.items():
        for p in prints:
            all_prints.append(p)
            print_to_user[idx] = uid
            idx += 1
    if not all_prints:
        return {'ok': True, 'matched': False, 'error': 'No hay huellas registradas'}

    if not dev_lock.acquire(blocking=False):
        return {'ok': True, 'waiting': True}
    IDENTIFY['busy'] = True
    threading.Thread(target=_identify_worker, args=(all_prints, print_to_user),
                     name='identify', daemon=True).start()

    # esperar un toque por si el dedo ya está puesto (respuesta inmediata)
    waited = 0.0
    while waited < max(1, timeout) and IDENTIFY['busy']:
        time.sleep(0.2)
        waited += 0.2
    if IDENTIFY['result'] is not None:
        r = IDENTIFY['result']; IDENTIFY['result'] = None
        return r
    return {'ok': True, 'waiting': True}


def do_enroll(user_id, finger='right-index'):
    """Ejecuta enroll_sync con progreso y cancelacion. Bloquea hasta completar N toques."""
    global ENROLL_CANCEL
    if not device_ready or not fp_dev:
        return {'ok': False, 'error': 'Dispositivo no disponible'}

    acquired = dev_lock.acquire(timeout=5)
    if not acquired:
        return {'ok': False, 'error': 'Dispositivo ocupado'}

    cancellable = Gio.Cancellable()
    ENROLL_CANCEL = cancellable
    ENROLL_STATE.update({'active': True, 'done': 0, 'needed': enroll_stages,
                         'msg': 'Coloque el dedo en el lector...'})

    def progress_cb(dev, completed_stages, fp_print, error, user_data=None):
        ENROLL_STATE['done'] = int(completed_stages)
        ENROLL_STATE['needed'] = enroll_stages
        if error is not None:
            ENROLL_STATE['msg'] = 'Reintente: %s' % getattr(error, 'message', str(error))
        else:
            ENROLL_STATE['msg'] = 'Toque %d de %d capturado' % (completed_stages, enroll_stages)

    try:
        _dev_open()
        print(f"[FP] Enroll {user_id}: {enroll_stages} toques...")
        template = FPrint.Print.new(fp_dev)
        try:
            template.set_username(user_id)
            template.set_description(finger)
        except Exception:
            pass
        fp_print = fp_dev.enroll_sync(template, cancellable, progress_cb, None)

        if fp_print:
            try:
                fp_print.set_username(user_id)
                fp_print.set_description(finger)
            except Exception:
                pass
            save_print(user_id, finger, fp_print)
            loaded_prints.setdefault(user_id, [])
            loaded_prints[user_id].append(fp_print)
            tmpl_b64 = base64.b64encode(_print_to_raw(fp_print)).decode()
            ENROLL_STATE.update({'active': False, 'done': enroll_stages, 'msg': 'Completado'})
            print(f"[FP] Enroll OK: {user_id}")
            return {'ok': True, 'user_id': user_id, 'finger': finger, 'stages': enroll_stages,
                    'template_b64': tmpl_b64, 'serial': device_name or ''}
        else:
            ENROLL_STATE.update({'active': False, 'msg': 'Enroll falló'})
            return {'ok': False, 'error': 'Enroll falló'}

    except GLib.Error as e:
        err = str(e)
        cancelled = ('cancel' in err.lower())
        print(f"[FP] Error enroll: {err}")
        ENROLL_STATE.update({'active': False, 'msg': 'Cancelado' if cancelled else err})
        if 'overheating' in err.lower() or 'disabled' in err.lower():
            handle_overheating()
        return {'ok': False, 'error': 'cancelado' if cancelled else err}
    except Exception as e:
        err = str(e)
        print(f"[FP] Error enroll: {err}")
        ENROLL_STATE.update({'active': False, 'msg': err})
        if 'overheating' in err.lower() or 'disabled' in err.lower():
            handle_overheating()
        # Nota: NO marcamos el lector caído por errores de lectura (evita flapping
        # detectado/no-detectado). El device solo se marca caído si falla el open.
        return {'ok': False, 'error': err}
    finally:
        ENROLL_CANCEL = None
        _dev_close()
        dev_lock.release()


def do_enroll_cancel():
    c = ENROLL_CANCEL
    if c is not None:
        try:
            c.cancel()
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        return {'ok': True, 'cancelled': True}
    return {'ok': True, 'cancelled': False, 'msg': 'No hay enroll activo'}


def do_capture():
    """Captura imagen (compatibilidad)."""
    if not device_ready or not fp_dev:
        return {'ok': False, 'error': 'Dispositivo no disponible'}

    acquired = dev_lock.acquire(timeout=2)
    if not acquired:
        return {'ok': False, 'error': 'Dispositivo ocupado'}

    try:
        _dev_open()
        image = fp_dev.capture_sync(wait_for_finger=True)
        if image:
            png = image_to_png(image)
            if png:
                return {'ok': True, 'png': png}
        return {'ok': False, 'error': 'Sin imagen'}
    except Exception as e:
        err = str(e)
        if 'overheating' in err.lower() or 'disabled' in err.lower():
            handle_overheating()
        return {'ok': False, 'error': err}
    finally:
        _dev_close()
        dev_lock.release()


def do_prints_clear(wipe_disk=False):
    """Vacia los prints en memoria. Si wipe_disk, borra tambien los .fpr del disco."""
    global loaded_prints
    n = len(loaded_prints)
    loaded_prints = {}
    if wipe_disk and os.path.isdir(PRINTS_DIR):
        for d in os.listdir(PRINTS_DIR):
            pth = os.path.join(PRINTS_DIR, d)
            try:
                if os.path.isdir(pth):
                    shutil.rmtree(pth)
                else:
                    os.remove(pth)
            except Exception as e:
                print(f"[FP] clear: no se pudo borrar {pth}: {e}")
    print(f"[FP] prints/clear (wipe_disk={wipe_disk}): {n} usuario(s) limpiados")
    return {'ok': True, 'cleared': n}


def do_prints_import(huellas, write_disk=True):
    """Importa templates desde la BD (base64 del .fpr serializado) a memoria/disco.
    huellas: [{usuario_codigo, dedo, template_b64}, ...]"""
    imported = 0
    errors = []
    for h in (huellas or []):
        uid = str(h.get('usuario_codigo', '')).strip()
        finger = h.get('dedo') or 'right-index'
        b64 = h.get('template_b64') or ''
        if not uid or not b64:
            continue
        try:
            raw = base64.b64decode(b64)
            fp_print = FPrint.Print.deserialize(list(raw))
            if not fp_print:
                errors.append(f'{uid}: deserialize devolvio None')
                continue
            try:
                fp_print.set_username(uid)
                fp_print.set_description(finger)
            except Exception:
                pass
            loaded_prints.setdefault(uid, [])
            loaded_prints[uid].append(fp_print)
            if write_disk:
                user_dir = os.path.join(PRINTS_DIR, uid)
                os.makedirs(user_dir, exist_ok=True)
                with open(os.path.join(user_dir, f'{finger}.fpr'), 'wb') as f:
                    f.write(raw)
            imported += 1
        except Exception as e:
            errors.append(f'{uid}: {e}')
            print(f"[FP] import error {uid}: {e}")
    total = sum(len(v) for v in loaded_prints.values())
    print(f"[FP] prints/import: {imported} importados, {len(loaded_prints)} usuarios, {total} prints")
    return {'ok': True, 'imported': imported, 'users': len(loaded_prints), 'total': total, 'errors': errors}


def do_prints_reload():
    load_all_prints()
    return {'ok': True, 'users': len(loaded_prints),
            'total': sum(len(v) for v in loaded_prints.values())}


# --- Auto-actualización ---
def _vtuple(v):
    """'2.5.10' -> (2,5,10) para comparar versiones numéricamente."""
    try:
        return tuple(int(x) for x in str(v).strip().split('.'))
    except Exception:
        return (0,)


def _update_busy():
    """No conviene reiniciar a mitad de un registro o identificación."""
    return bool(ENROLL_STATE.get('active')) or bool(IDENTIFY.get('busy'))


def check_update(apply=False):
    """Lee el manifiesto de versiones. Informa si hay una versión nueva; si
    apply=True y la hay, baja el .py, lo valida (contenido + sintaxis), lo
    reemplaza en sitio y programa el reinicio (systemd lo relevanta).
    Devuelve siempre un dict listo para responder por HTTP."""
    UPDATE_STATE['checking'] = True
    UPDATE_STATE['msg'] = ''
    try:
        req = urllib.request.Request(UPDATE_MANIFEST, headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=8) as r:
            man = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        UPDATE_STATE.update({'checking': False, 'msg': f'sin conexión: {e}'})
        return {'ok': False, 'error': f'No se pudo verificar: {e}', 'current': VERSION}

    latest = str(man.get('version', '')).strip()
    UPDATE_STATE['latest'] = latest
    UPDATE_STATE['last_check'] = time.time()
    available = bool(latest) and _vtuple(latest) > _vtuple(VERSION)
    UPDATE_STATE['available'] = available

    if not available:
        UPDATE_STATE.update({'checking': False, 'msg': 'al día'})
        return {'ok': True, 'updated': False, 'update_available': False,
                'current': VERSION, 'latest': latest or VERSION}

    if not apply:
        UPDATE_STATE.update({'checking': False, 'msg': f'disponible {latest}'})
        return {'ok': True, 'updated': False, 'update_available': True,
                'current': VERSION, 'latest': latest, 'notes': man.get('notes', '')}

    # No reiniciar a mitad de un registro/identificación
    if _update_busy():
        UPDATE_STATE.update({'checking': False, 'msg': 'lector ocupado'})
        return {'ok': False, 'busy': True, 'update_available': True,
                'error': 'El lector está ocupado (registro/identificación en curso). Intente de nuevo en un momento.',
                'current': VERSION, 'latest': latest}

    pyurl = man.get('py') or UPDATE_PY_FALLBACK
    try:
        req = urllib.request.Request(pyurl, headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=25) as r:
            data = r.read()
    except Exception as e:
        UPDATE_STATE.update({'checking': False, 'msg': f'descarga falló: {e}'})
        return {'ok': False, 'error': f'Descarga falló: {e}', 'current': VERSION, 'latest': latest}

    # Validación mínima: que sea realmente este servicio
    if b'factupos-fingerprint-servicio' not in data or b'def main(' not in data:
        UPDATE_STATE.update({'checking': False, 'msg': 'contenido inválido'})
        return {'ok': False, 'error': 'El archivo descargado no es válido.', 'current': VERSION}
    # Validación de sintaxis: nunca instalar un .py roto
    try:
        compile(data, SELF_PATH, 'exec')
    except SyntaxError as e:
        UPDATE_STATE.update({'checking': False, 'msg': f'sintaxis inválida: {e}'})
        return {'ok': False, 'error': f'El archivo nuevo tiene un error de sintaxis: {e}', 'current': VERSION}

    # Reemplazo atómico en sitio (corremos como root)
    try:
        tmp = SELF_PATH + '.new'
        with open(tmp, 'wb') as f:
            f.write(data)
        try:
            shutil.copymode(SELF_PATH, tmp)
        except Exception:
            pass
        os.replace(tmp, SELF_PATH)
    except Exception as e:
        UPDATE_STATE.update({'checking': False, 'msg': f'no se pudo guardar: {e}'})
        return {'ok': False, 'error': f'No se pudo guardar la actualización: {e}', 'current': VERSION}

    print(f"[UPD] Actualizado {VERSION} -> {latest}; reiniciando...")
    UPDATE_STATE.update({'checking': False, 'msg': f'actualizado a {latest}, reiniciando'})

    def _restart():
        time.sleep(1.5)   # dar tiempo a que salga la respuesta HTTP
        os._exit(0)       # systemd (Restart=always) relevanta con el .py nuevo
    threading.Thread(target=_restart, name='update-restart', daemon=True).start()
    return {'ok': True, 'updated': True, 'from': VERSION, 'to': latest,
            'msg': 'Actualizado. El servicio se reiniciará en unos segundos.'}


def _update_loop():
    """Auto-check: a los 20s de arrancar y luego cada UPDATE_INTERVAL. Auto-aplica.
    Si el lector está ocupado reintenta pronto en vez de esperar 6h."""
    time.sleep(20)
    while True:
        wait = UPDATE_INTERVAL
        try:
            r = check_update(apply=True)
            if r.get('updated'):
                return   # vamos a reiniciar; el hilo termina
            if r.get('busy'):
                wait = 60
        except Exception as e:
            print(f"[UPD] auto-check error: {e}")
        time.sleep(wait)


def _status_page_html():
    """Página de estado con TEMA OSCURO (navy). Autocontenida, auto-refresh 3s."""
    activo = '<span class="b ok">● ACTIVO</span>'
    lector = ('<span class="b ok">● Conectado</span>' if device_ready
              else '<span class="b bad">● No detectado</span>')
    if FPRINT_OK:
        fp = '<span class="b ok">● OK</span>'
    else:
        fp = '<span class="b bad">● Falta libfprint</span>'
    users = len(loaded_prints)
    prints = sum(len(v) for v in loaded_prints.values())
    return f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="3">
<title>FactuPOS FingerPrint · Estado</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:system-ui,Segoe UI,Roboto,sans-serif;
         background:#0b1626; color:#e6eefc; min-height:100vh;
         display:flex; align-items:center; justify-content:center; }}
  .card {{ background:linear-gradient(160deg,#13243f,#0e1b33); border:1px solid #25406b;
          border-radius:18px; padding:28px 32px; width:min(440px,92vw);
          box-shadow:0 18px 50px rgba(0,0,0,.5); }}
  h1 {{ margin:0 0 2px; font-size:20px; letter-spacing:.3px; }}
  .ver {{ display:inline-block; margin:6px 0 18px; padding:3px 10px; border-radius:999px;
         background:#1d3a66; color:#9fc2ff; font-size:13px; font-weight:700; }}
  .row {{ display:flex; justify-content:space-between; align-items:center;
         padding:11px 0; border-top:1px solid #1d3257; }}
  .row span:first-child {{ color:#9fb3d4; font-size:14px; }}
  .b {{ font-weight:700; font-size:13px; }}
  .ok {{ color:#3ddc84; }} .bad {{ color:#ff6b6b; }}
  .foot {{ margin-top:16px; font-size:11px; color:#6f86ad; text-align:center; }}
</style></head><body>
<div class="card">
  <h1>🖐 FactuPOS FingerPrint</h1>
  <div class="ver">Servicio v{VERSION}</div>
  <div class="row"><span>Servicio</span>{activo}</div>
  <div class="row"><span>Lector de huella</span>{lector}</div>
  <div class="row"><span>libfprint</span>{fp}</div>
  <div class="row"><span>Usuarios / huellas</span><span class="b">{users} / {prints}</span></div>
  <div class="foot">Tema oscuro · se actualiza cada 3 s · 127.0.0.1:52181</div>
</div></body></html>"""


# --- HTTP ---
class FPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        if args:
            print(f"[HTTP] {format % args}")

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self._cors()
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, code, html):
        body = html.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self._cors()
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get('Content-Length', 0))
        if n > 0:
            try: return json.loads(self.rfile.read(n))
            except: pass
        return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        p = self.path.split('?')[0].rstrip('/')
        if p == '':
            # Página de estado con tema oscuro (raíz). En v2.5.0 esto daba 404.
            self._html(200, _status_page_html())
        elif p == '/get_connection':
            self._json(200, {
                'ok': True,
                'connected': device_ready, 'device': device_name, 'driver': device_driver,
                'platform': 'linux-libfprint', 'enroll_stages': enroll_stages,
                'matching': 'libfprint-minutiae', 'web_sdk_id': None, 'port': None
            })
        elif p == '/status':
            self._json(200, {
                'ok': True,
                'service': 'factupos-fingerprint-servicio', 'version': VERSION,
                'device_ready': device_ready, 'cooling_down': cooling_down,
                'fprint_ok': FPRINT_OK, 'fprint_error': FPRINT_ERR,
                'users_enrolled': len(loaded_prints),
                'total_prints': sum(len(v) for v in loaded_prints.values())
            })
        elif p == '/prints':
            self._json(200, {'ok': True, 'users': {k: len(v) for k, v in loaded_prints.items()}})
        elif p == '/fingerprint/enroll/progress':
            self._json(200, {
                'ok': True,
                'active': bool(ENROLL_STATE.get('active', False)),
                'done': int(ENROLL_STATE.get('done', 0)),
                'needed': int(ENROLL_STATE.get('needed', enroll_stages)),
                'msg': ENROLL_STATE.get('msg', '')
            })
        elif p == '/update/check':
            # Consulta en vivo el manifiesto (sin aplicar). Para el indicador
            # "hay actualización" del kiosko.
            self._json(200, check_update(apply=False))
        else:
            self._json(404, {'error': 'Not found'})

    def do_POST(self):
        p = self.path.split('?')[0].rstrip('/')

        # --- Operaciones que NO requieren el lector ---
        if p == '/prints/clear':
            body = self._body()
            self._json(200, do_prints_clear(bool(body.get('wipe_disk', False))))
            return
        elif p == '/prints/import':
            body = self._body()
            self._json(200, do_prints_import(body.get('huellas', []), bool(body.get('write_disk', True))))
            return
        elif p == '/prints/reload':
            self._json(200, do_prints_reload())
            return
        elif p == '/fingerprint/enroll/cancel':
            self._json(200, do_enroll_cancel())
            return
        elif p == '/update':
            # Botón "Buscar actualizaciones" del kiosko: consulta y, si hay
            # versión nueva, la aplica y reinicia el servicio.
            self._json(200, check_update(apply=True))
            return

        # --- Operaciones que requieren el lector ---
        if p == '/fingerprint/identify':
            if not device_ready:
                self._json(503, {'error': 'Dispositivo no disponible', 'cooling': cooling_down})
                return
            result = do_identify()
            code = 200 if result.get('ok') else 408
            self._json(code, result)

        elif p == '/fingerprint/enroll':
            if not device_ready:
                self._json(503, {'error': 'Dispositivo no disponible'})
                return
            body = self._body()
            uid = str(body.get('user_id', '')).strip()
            finger = body.get('finger', 'right-index')
            if not uid:
                self._json(400, {'error': 'Falta user_id'})
                return
            result = do_enroll(uid, finger)
            self._json(200 if result.get('ok') else 400, result)

        elif p == '/fingerprint/capture':
            if not device_ready:
                self._json(503, {'error': 'Dispositivo no disponible'})
                return
            result = do_capture()
            if result.get('ok') and result.get('png'):
                self._json(200, {
                    'image': base64.b64encode(result['png']).decode(),
                    'format': 'png', 'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
                })
            else:
                self._json(408, {'error': result.get('error', 'Sin imagen')})

        else:
            self._json(404, {'error': 'Not found'})

    def do_DELETE(self):
        p = self.path.split('?')[0].rstrip('/')
        if p.startswith('/prints/'):
            uid = p.split('/prints/')[1]
            user_dir = os.path.join(PRINTS_DIR, uid)
            if os.path.exists(user_dir):
                shutil.rmtree(user_dir)
                loaded_prints.pop(uid, None)
                self._json(200, {'ok': True, 'deleted': uid})
            else:
                self._json(404, {'error': 'No encontrado'})
        else:
            self._json(404, {'error': 'Not found'})


class ThreadedHTTPServer(HTTPServer):
    def process_request(self, request, client_address):
        threading.Thread(target=self._h, args=(request, client_address), daemon=True).start()
    def _h(self, req, addr):
        try: self.finish_request(req, addr)
        except: self.handle_error(req, addr)
        finally: self.shutdown_request(req)


def main():
    global fp_dev, device_name, device_driver, device_ready, enroll_stages

    print(f"[SVC] Servicio de huella digital FactuPOS v{VERSION}")
    print("[SVC] Matching: libfprint minutiae (sync, thread-safe)")
    if not FPRINT_OK:
        print(f"[SVC] ⚠ {FPRINT_ERR}")
        print("[SVC] El servicio levanta igual (HTTP/status responde), pero el lector NO funcionará hasta instalar libfprint.")
    ensure_dirs()

    # Inicialización del lector: si falla, NO matamos el servicio — el watchdog
    # lo recupera cuando se reconecte. Así el /status siempre responde.
    if not _reinit_device():
        print("[FP] Lector no disponible al arrancar; el watchdog reintentará cada 5s.")

    load_all_prints()

    # Watchdog de recuperación del lector
    threading.Thread(target=_watchdog, name='watchdog', daemon=True).start()

    # Auto-actualización (chequea a los 20s y cada 6h, igual que el panel)
    threading.Thread(target=_update_loop, name='updater', daemon=True).start()

    server = ThreadedHTTPServer((HOST, PORT), FPHandler)
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    server.socket = ssl_ctx.wrap_socket(server.socket, server_side=True)

    def shutdown(sig, frame):
        print("\n[SVC] Cerrando...")
        os._exit(0)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    print(f"[SVC] https://{HOST}:{PORT} — Listo")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == '__main__':
    main()
