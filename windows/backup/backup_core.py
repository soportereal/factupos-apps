"""
FactuposBackup — Motor del respaldo SQL Server.

Sin UI ni CLI: lo usan backup_app.py (app gráfica) y backup_cli.py (línea de comandos).
"""

APP_VERSION = "1.2.0"

import json
import logging
import sys
import time
import zipfile  # solo para restaurar backups .zip antiguos
import py7zr
from datetime import datetime
from pathlib import Path

CONFIG_DEFAULT = {
    "server": "127.0.0.1",
    "user": "sa",
    "password": "",
    "backup_path": "R:\\BACKUPTEMP",
    "schedule_hour": "23:00",
    "exclude_dbs": ["master", "tempdb", "model", "msdb", "dbcontrol_audit"],
    "include_dbs": [],
    "compress": True,
    "delete_bak_after_zip": True,
    "retention_days": 7,
    "compression_level": 6,
    "log_file": "FactuposBackup.log",
    "connection_retries": 3,
    "connection_retry_delay": 10,
    "backup_retries": 2,
    "backup_retry_delay": 15,
    "reboot_enabled": False,
    "reboot_hour": "03:00",
    "reboot_grace_seconds": 1,
    "auto_update_enabled": True,
    "update_check_url": "https://invefacon.factupos.com/downloads/Factupos-Backup_version.json",
    "restore_data_path": "D:\\SqlData",
    "restore_log_path": "C:\\SqlLog",
    "network_drives": [],
}


def app_dir() -> Path:
    """Carpeta donde viven config.json y log, sea corriendo como .py o como .exe (PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def config_path() -> Path:
    return app_dir() / "config.json"


def load_config() -> dict:
    p = config_path()
    if not p.exists():
        save_config(CONFIG_DEFAULT.copy())
        return CONFIG_DEFAULT.copy()
    try:
        text = p.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError("config.json vacío")
        cfg = json.loads(text)
        if not isinstance(cfg, dict):
            raise ValueError("config.json no es un objeto JSON")
    except (json.JSONDecodeError, ValueError, OSError):
        # Respaldar el archivo corrupto y arrancar con defaults
        try:
            corrupt = p.with_suffix(".json.corrupt")
            if corrupt.exists():
                corrupt.unlink()
            p.replace(corrupt)
        except Exception:
            pass
        cfg = CONFIG_DEFAULT.copy()
        try:
            save_config(cfg)
        except Exception:
            pass
    for k, v in CONFIG_DEFAULT.items():
        cfg.setdefault(k, v)
    return cfg


def save_config(cfg: dict) -> None:
    config_path().write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def get_logger(name: str = "FactuposBackup") -> logging.Logger:
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(app_dir() / load_config().get("log_file", "FactuposBackup.log"), encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    return log


def fmt_size(bytes_: int) -> str:
    mb = bytes_ / 1024 / 1024
    return f"{mb/1024:.2f} GB" if mb >= 1024 else f"{mb:.1f} MB"


def get_connection(cfg: dict):
    try:
        import pyodbc
    except ImportError:
        raise RuntimeError("pyodbc no está instalado. pip install pyodbc")
    drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
    if not drivers:
        raise RuntimeError("No hay ODBC Driver para SQL Server. Instalá Microsoft ODBC Driver 17 o 18.")
    conn_str = (
        f"DRIVER={{{drivers[-1]}}};"
        f"SERVER={cfg['server']};"
        f"UID={cfg['user']};"
        f"PWD={cfg['password']};"
        f"TrustServerCertificate=yes;Encrypt=no;"
    )
    return pyodbc.connect(conn_str, autocommit=True, timeout=15)


def get_connection_with_retry(cfg: dict, log: logging.Logger):
    """Conecta con reintentos (default 3 intentos, espera creciente)."""
    retries = max(1, int(cfg.get("connection_retries", 3)))
    delay = max(1, int(cfg.get("connection_retry_delay", 10)))
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            if attempt > 1:
                log.info(f"Reintento conexión {attempt}/{retries} a {cfg['server']}…")
            return get_connection(cfg)
        except Exception as e:
            last_err = e
            log.warning(f"Conexión fallida ({attempt}/{retries}): {e}")
            if attempt < retries:
                wait = delay * attempt  # backoff lineal: 10s, 20s, 30s
                log.info(f"  Esperando {wait}s antes de reintentar…")
                time.sleep(wait)
    raise RuntimeError(f"No se pudo conectar tras {retries} intentos: {last_err}")


def list_databases(conn, exclude, include):
    cur = conn.cursor()
    cur.execute(
        "SELECT name FROM sys.databases "
        "WHERE state = 0 AND database_id > 4 AND is_read_only = 0 "
        "ORDER BY name"
    )
    dbs = [r[0] for r in cur.fetchall()]
    excl = {d.lower() for d in (exclude or [])}
    incl = {d.lower() for d in (include or [])}
    if incl:
        dbs = [d for d in dbs if d.lower() in incl]
    return [d for d in dbs if d.lower() not in excl]


def backup_database(conn, dbname, backup_path, ts):
    safe_name = dbname.replace("[", "").replace("]", "")
    bak_file = Path(backup_path) / f"{safe_name}_{ts}.bak"
    cur = conn.cursor()
    sql = (
        f"BACKUP DATABASE [{safe_name}] "
        f"TO DISK = N'{bak_file}' "
        # Sin COMPRESSION: el .bak sale crudo para que 7z (LZMA2) lo comprima
        # desde cero y logre un ratio mucho mayor que la compresión nativa de SQL.
        f"WITH FORMAT, INIT, "
        f"NAME = N'{safe_name} backup {ts}', SKIP, STATS = 25"
    )
    cur.execute(sql)
    while cur.nextset():
        pass
    return bak_file


def compress_to_7z(bak_file, level):
    """Comprime el .bak a un archivo .7z (LZMA2). level = preset 0-9 (6 ≈ 'Normal')."""
    archive = bak_file.with_suffix(".7z")
    preset = max(0, min(9, int(level)))
    filters = [{"id": py7zr.FILTER_LZMA2, "preset": preset}]
    with py7zr.SevenZipFile(archive, "w", filters=filters) as z:
        z.write(bak_file, bak_file.name)
    return archive


# ---------- restore helpers ----------

def extract_archive_to_temp(archive_path: Path) -> Path:
    """Extrae el primer .bak del archivo (.7z o .zip) a una carpeta temporal y devuelve el path."""
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="fpbk_"))
    if archive_path.suffix.lower() == ".7z":
        with py7zr.SevenZipFile(archive_path, "r") as z:
            bak_members = [n for n in z.getnames() if n.lower().endswith(".bak")]
            if not bak_members:
                raise RuntimeError(f"{archive_path.name} no contiene un .bak")
            z.extract(path=tmp, targets=[bak_members[0]])
        return tmp / bak_members[0]
    # .zip: backups generados por versiones anteriores (compatibilidad)
    with zipfile.ZipFile(archive_path, "r") as zf:
        bak_members = [n for n in zf.namelist() if n.lower().endswith(".bak")]
        if not bak_members:
            raise RuntimeError(f"{archive_path.name} no contiene un .bak")
        zf.extract(bak_members[0], tmp)
    return tmp / bak_members[0]


def bak_get_header(conn, bak_path: Path) -> dict:
    """RESTORE HEADERONLY → dict con metadata (DatabaseName, BackupSize, BackupStartDate, etc.)."""
    cur = conn.cursor()
    cur.execute(f"RESTORE HEADERONLY FROM DISK = N'{bak_path}'")
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"No se pudo leer header de {bak_path}")
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


def bak_get_filelist(conn, bak_path: Path) -> list:
    """RESTORE FILELISTONLY → lista de dicts con LogicalName, PhysicalName, Type ('D'/'L')."""
    cur = conn.cursor()
    cur.execute(f"RESTORE FILELISTONLY FROM DISK = N'{bak_path}'")
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def default_data_path(conn) -> str:
    cur = conn.cursor()
    cur.execute("SELECT CONVERT(NVARCHAR(500), SERVERPROPERTY('InstanceDefaultDataPath'))")
    p = cur.fetchval()
    return p or "C:\\"


def default_log_path(conn) -> str:
    cur = conn.cursor()
    cur.execute("SELECT CONVERT(NVARCHAR(500), SERVERPROPERTY('InstanceDefaultLogPath'))")
    p = cur.fetchval()
    return p or "C:\\"


def restore_one(conn, bak_path: Path, target_name: str = None,
                data_path: str = None, log_path: str = None,
                log: logging.Logger = None) -> str:
    """
    Restaura una BD desde un .bak. target_name = nombre destino (default: el del .bak).
    data_path/log_path: carpetas destino para .mdf/.ldf (default: InstanceDefaults del server).
    Hace WITH REPLACE + WITH MOVE. Devuelve el nombre final restaurado.
    """
    log = log or logging.getLogger("backup_sql")
    header = bak_get_header(conn, bak_path)
    src_name = header.get("DatabaseName") or bak_path.stem.split("_")[0]
    target = target_name or src_name

    files = bak_get_filelist(conn, bak_path)
    data_dir = (data_path or default_data_path(conn)).rstrip("\\") + "\\"
    log_dir = (log_path or default_log_path(conn)).rstrip("\\") + "\\"

    # Naming físico LIMPIO basado en el destino (sin arrastrar el logical name viejo):
    #   1 data file:     <target>.mdf
    #   N data files:    <target>.mdf, <target>_2.ndf, <target>_3.ndf, …
    #   1 log file:      <target>_log.ldf
    #   N log files:     <target>_log.ldf, <target>_log_2.ldf, …
    data_files = [f for f in files if (f.get("Type") or "").upper() == "D"]
    log_files = [f for f in files if (f.get("Type") or "").upper() == "L"]

    moves = []
    for idx, f in enumerate(data_files):
        logical = f["LogicalName"]
        if idx == 0:
            new_name = f"{target}.mdf"
        else:
            new_name = f"{target}_{idx + 1}.ndf"
        new_path = data_dir + new_name
        logical_esc = logical.replace("'", "''")
        new_path_esc = new_path.replace("'", "''")
        moves.append(f"MOVE N'{logical_esc}' TO N'{new_path_esc}'")

    for idx, f in enumerate(log_files):
        logical = f["LogicalName"]
        if idx == 0:
            new_name = f"{target}_log.ldf"
        else:
            new_name = f"{target}_log_{idx + 1}.ldf"
        new_path = log_dir + new_name
        logical_esc = logical.replace("'", "''")
        new_path_esc = new_path.replace("'", "''")
        moves.append(f"MOVE N'{logical_esc}' TO N'{new_path_esc}'")

    sql = (
        f"RESTORE DATABASE [{target}] FROM DISK = N'{bak_path}' "
        f"WITH REPLACE, RECOVERY, STATS = 25, " + ", ".join(moves)
    )

    log.info(f"  RESTORE DATABASE [{target}] desde {bak_path.name}…")
    cur = conn.cursor()
    cur.execute(sql)
    while cur.nextset():
        pass
    return target


def scan_backup_folder(folder: Path) -> list:
    """Devuelve lista de archivos .bak, .7z y .zip encontrados (sorted by name)."""
    files = list(folder.glob("*.bak")) + list(folder.glob("*.7z")) + list(folder.glob("*.zip"))
    return sorted(files, key=lambda p: p.name.lower())


def derive_db_name(path: Path, strip_suffix: str = "") -> str:
    """
    Deriva el nombre de BD destino del nombre del archivo.
    Regla: corta en el PRIMER underscore. Todo lo que viene después se ignora
    (timestamps de nuestros backups, sufijos tipo _INVEFACON, etc.).

    Si strip_suffix se especifica explícitamente y el nombre termina con él,
    también se quita (compatibilidad con la versión anterior).

    Ejemplos:
      'factupos_20260514_230003.bak'  → 'factupos'
      'alianzamarket_INVEFACON.bak'   → 'alianzamarket'
      'mibd.bak'                      → 'mibd'
      'mi_base_datos.bak'             → 'mi'   (ojo: si querés conservar el resto, editá manual)
    """
    stem = path.stem
    if strip_suffix and stem.endswith(strip_suffix):
        result = stem[: -len(strip_suffix)]
        if result:
            stem = result
    if "_" in stem:
        return stem.split("_", 1)[0]
    return stem


def run_restore(cfg, folder: Path, files_to_restore: list, log=None,
                on_progress=None, data_path: str = None, log_path: str = None,
                targets: dict = None):
    """
    Restaura cada archivo (.bak, .7z o .zip) de la lista. files_to_restore = [Path, ...].
    data_path/log_path: carpetas destino para .mdf/.ldf (None = defaults del server).
    targets: dict {filename: dbname_destino} — si no está, usa derive_db_name().
    on_progress(stage, done, total, filename, dbname) callback opcional.
    Retorna dict {ok: [...], fail: [(file, error), ...]}.
    """
    targets = targets or {}
    log = log or get_logger()
    log.info("=" * 70)
    log.info(f"Inicio RESTORE — folder={folder} archivos={len(files_to_restore)}")

    try:
        conn = get_connection_with_retry(cfg, log)
    except Exception as e:
        log.error(f"No se pudo conectar a SQL: {e}")
        return {"ok": [], "fail": [], "error": str(e)}

    ok, fail = [], []
    total = len(files_to_restore)
    for i, src in enumerate(files_to_restore, 1):
        src = Path(src)
        bak_path = None
        tmp_to_clean = None
        try:
            if on_progress:
                on_progress("prep", i, total, src.name, "")
            log.info(f"[{src.name}]")
            if src.suffix.lower() in (".7z", ".zip"):
                log.info(f"  Extrayendo {src.suffix.lstrip('.').upper()}…")
                bak_path = extract_archive_to_temp(src)
                tmp_to_clean = bak_path.parent
            else:
                bak_path = src

            header = bak_get_header(conn, bak_path)
            src_db = header.get("DatabaseName") or "?"
            # Nombre destino: prioriza el dict targets, si no usa derive_db_name (filename)
            dbname = targets.get(src.name) or derive_db_name(src)
            log.info(f"  BD origen (en .bak): {src_db}  →  Destino: {dbname}")
            if on_progress:
                on_progress("restore", i, total, src.name, dbname)

            restored = restore_one(conn, bak_path, target_name=dbname,
                                   data_path=data_path, log_path=log_path, log=log)
            log.info(f"  OK restaurada: [{restored}]")
            ok.append((src.name, restored))
        except Exception as e:
            log.error(f"[{src.name}] FALLA: {e}")
            fail.append((src.name, str(e)))
        finally:
            if tmp_to_clean and tmp_to_clean.exists():
                try:
                    import shutil
                    shutil.rmtree(tmp_to_clean, ignore_errors=True)
                except Exception:
                    pass

    log.info("-" * 70)
    log.info(f"FIN RESTORE — OK={len(ok)} FAIL={len(fail)}")
    return {"ok": ok, "fail": fail}


# ---------- backup helpers (continúa) ----------

def cleanup_old(backup_path, days, log):
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for pattern in ("*.7z", "*.zip", "*.bak"):
        for f in Path(backup_path).glob(pattern):
            if f.stat().st_mtime < cutoff:
                try:
                    f.unlink()
                    removed += 1
                except OSError as e:
                    log.warning(f"  No se pudo borrar {f.name}: {e}")
    return removed


# ---------- auto-update ----------

def _version_tuple(v: str):
    parts = []
    for x in v.strip().split("."):
        try:
            parts.append(int(x))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def check_for_update(current_version: str, url: str, log=None) -> dict:
    """
    Consulta el manifest JSON. Devuelve dict con info si hay nueva versión, None si no, o {'error': ...}.
    Manifest esperado: { "version": "1.0.2", "download_url": "https://...", "released": "...", "notes": "..." }
    """
    import urllib.request
    import ssl
    log = log or get_logger()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"FactuposBackup/{current_version}"})
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            data = json.loads(r.read().decode("utf-8"))
        srv_ver = data.get("version", "0.0.0")
        if _version_tuple(srv_ver) > _version_tuple(current_version):
            log.info(f"Update disponible: v{srv_ver} (actual v{current_version})")
            data["update_available"] = True
            return data
        log.info(f"Sin actualización (server v{srv_ver}, local v{current_version}).")
        return None
    except Exception as e:
        log.warning(f"check_for_update falló: {e}")
        return {"error": str(e)}


def download_update(url: str, dest: Path, on_progress=None, log=None) -> Path:
    """Descarga el .exe nuevo a `dest`. on_progress(downloaded, total) callback opcional."""
    import urllib.request
    import ssl
    log = log or get_logger()
    log.info(f"Descargando update desde {url}…")
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "FactuposBackup-Updater"})
    with urllib.request.urlopen(req, timeout=120, context=ctx) as r:
        total = int(r.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)
    log.info(f"Descarga OK: {dest} ({fmt_size(dest.stat().st_size)})")
    return dest


UPDATER_BAT = r"""@echo off
REM FactuposBackup — updater
REM Espera a que el .exe viejo cierre, lo reemplaza, relanza, y se borra.

cd /d "%~dp0"

echo Esperando que FactuposBackup.exe termine...
:wait
tasklist /fi "imagename eq FactuposBackup.exe" 2>nul | find /i "FactuposBackup.exe" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)

REM Backup del .exe viejo (rotando 1 copia)
if exist "FactuposBackup.exe.old" del /q "FactuposBackup.exe.old" >nul 2>&1
if exist "FactuposBackup.exe" move /y "FactuposBackup.exe" "FactuposBackup.exe.old" >nul

REM Aplicar el nuevo
move /y "FactuposBackup.new.exe" "FactuposBackup.exe" >nul

REM Re-lanzar (oculto si la app estaba en autostart-hidden)
start "" "FactuposBackup.exe" {RELAUNCH_ARGS}

REM Auto-borrar
(goto) 2>nul & del "%~f0"
"""


# ---------- mapear unidades de red ----------

def map_network_drives(drives: list, log=None) -> dict:
    r"""
    Ejecuta `net use LETRA: \\srv\share /user:USR PWD /persistent:yes` para cada drive.
    drives = [{letter, unc, user, password, persistent}, ...]
    Si la unidad ya está mapeada al mismo UNC → no hace nada (skip).
    Si está mapeada a OTRO UNC → primero la desmapea y la vuelve a hacer.
    Retorna {ok: [...], fail: [(letter, error), ...]}.
    """
    import subprocess
    log = log or get_logger()
    if sys.platform != "win32":
        return {"ok": [], "fail": [], "error": "Solo Windows."}

    ok, fail = [], []
    for d in drives or []:
        letter = (d.get("letter") or "").rstrip(":").upper()
        unc = (d.get("unc") or "").strip()
        user = (d.get("user") or "").strip()
        pwd = d.get("password") or ""
        persistent = d.get("persistent", True)
        if not letter or not unc:
            continue

        # Chequear si ya está mapeado y a qué UNC
        try:
            r = subprocess.run(
                ["net", "use", f"{letter}:"],
                capture_output=True, text=True, timeout=8,
            )
            if r.returncode == 0:
                # Ya está mapeado — verificar si coincide el UNC
                txt = r.stdout.lower()
                if unc.lower() in txt:
                    log.info(f"  {letter}: ya mapeado a {unc}")
                    ok.append(letter)
                    continue
                else:
                    log.info(f"  {letter}: mapeado a otro UNC, desconectando…")
                    subprocess.run(["net", "use", f"{letter}:", "/delete", "/y"],
                                   capture_output=True, timeout=8)
        except Exception as e:
            log.warning(f"  No se pudo chequear {letter}:: {e}")

        # Construir el comando net use
        cmd = ["net", "use", f"{letter}:", unc]
        if user:
            cmd.append(pwd)  # net use LETRA: \\srv\sh PWD /user:USR
            cmd.extend(["/user:" + user])
        cmd.extend(["/persistent:" + ("yes" if persistent else "no")])

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                log.info(f"  Mapeado {letter}: → {unc}")
                ok.append(letter)
            else:
                err = (r.stderr or r.stdout or "").strip()
                log.warning(f"  Falló {letter}: → {unc}: {err}")
                fail.append((letter, err))
        except Exception as e:
            log.warning(f"  Error mapeando {letter}: {e}")
            fail.append((letter, str(e)))

    return {"ok": ok, "fail": fail}


# ---------- auto-logon Windows ----------

def windows_set_autologon(username: str, password: str, domain: str = "", log=None) -> dict:
    """
    Configura el auto-logon de Windows escribiendo en el registro:
      HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon

    También baja DevicePasswordLessBuildVersion=0 (necesario en Win10/11/Server 2022+)
    para que la opción aparezca y el auto-logon funcione.

    REQUIERE permisos de administrador (HKLM). Si la app no corre as admin, falla.
    Devuelve dict {ok: bool, error: str}.
    """
    log = log or get_logger()
    if sys.platform != "win32":
        return {"ok": False, "error": "Solo Windows."}
    try:
        import winreg
    except ImportError:
        return {"ok": False, "error": "winreg no disponible (no es Windows)."}

    if not username:
        return {"ok": False, "error": "Usuario vacío."}

    try:
        # 1) Habilitar la opción de password-less en Win10/11/Server 2022+
        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device",
                0, winreg.KEY_ALL_ACCESS,
            ) as k:
                winreg.SetValueEx(k, "DevicePasswordLessBuildVersion", 0, winreg.REG_DWORD, 0)
            log.info("Set DevicePasswordLessBuildVersion=0 (habilita auto-logon en Win10/11/Server 2022+)")
        except OSError as e:
            log.warning(f"No se pudo setear DevicePasswordLessBuildVersion: {e}")

        # 2) Configurar Winlogon
        with winreg.OpenKeyEx(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon",
            0, winreg.KEY_ALL_ACCESS,
        ) as k:
            winreg.SetValueEx(k, "AutoAdminLogon", 0, winreg.REG_SZ, "1")
            winreg.SetValueEx(k, "DefaultUserName", 0, winreg.REG_SZ, username)
            winreg.SetValueEx(k, "DefaultPassword", 0, winreg.REG_SZ, password)
            if domain:
                winreg.SetValueEx(k, "DefaultDomainName", 0, winreg.REG_SZ, domain)
            # AutoLogonCount=0 evita login infinito accidental
            try:
                winreg.DeleteValue(k, "AutoLogonCount")
            except OSError:
                pass

        log.info(f"Auto-logon configurado: usuario='{username}', dominio='{domain or '(none)'}'")
        return {"ok": True, "error": ""}
    except PermissionError:
        return {"ok": False,
                "error": "Acceso denegado. Cerrá la app y abrila como Administrador (botón derecho → Ejecutar como administrador)."}
    except OSError as e:
        return {"ok": False, "error": f"Error de registro: {e}"}


def windows_disable_autologon(log=None) -> dict:
    """Borra las claves de auto-logon (vuelve al login manual)."""
    log = log or get_logger()
    if sys.platform != "win32":
        return {"ok": False, "error": "Solo Windows."}
    try:
        import winreg
        with winreg.OpenKeyEx(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon",
            0, winreg.KEY_ALL_ACCESS,
        ) as k:
            try:
                winreg.SetValueEx(k, "AutoAdminLogon", 0, winreg.REG_SZ, "0")
            except OSError:
                pass
            for v in ("DefaultPassword",):
                try:
                    winreg.DeleteValue(k, v)
                except OSError:
                    pass
        log.info("Auto-logon deshabilitado.")
        return {"ok": True, "error": ""}
    except PermissionError:
        return {"ok": False,
                "error": "Acceso denegado. Abrí la app como Administrador."}
    except OSError as e:
        return {"ok": False, "error": str(e)}


def apply_update(current_exe: Path, new_exe: Path, hidden: bool = True, log=None) -> Path:
    """
    Escribe updater.bat al lado del .exe y lo lanza desligado del proceso actual.
    El llamador DEBE hacer sys.exit() inmediatamente después.
    """
    import subprocess
    log = log or get_logger()
    bat_path = current_exe.parent / "updater.bat"
    relaunch = "--hidden" if hidden else ""
    bat_path.write_text(UPDATER_BAT.replace("{RELAUNCH_ARGS}", relaunch), encoding="utf-8")
    log.info(f"Lanzando updater.bat (relaunch_args='{relaunch}')…")
    # DETACHED + new console group así sobrevive al cierre del .exe
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
        cwd=str(current_exe.parent),
    )
    return bat_path


def run_backup(cfg=None, log=None, on_progress=None):
    """
    Ejecuta el backup completo. Retorna dict con resumen.
    on_progress(stage:str, done:int, total:int, msg:str) — callback opcional para UI.
    """
    cfg = cfg or load_config()
    log = log or get_logger()

    log.info("=" * 70)
    log.info(f"Inicio backup — servidor={cfg['server']} ruta={cfg['backup_path']}")
    if not cfg.get("password"):
        msg = "Password vacío. Configurá la app antes de respaldar."
        log.error(msg)
        return {"ok": False, "error": msg}

    try:
        conn = get_connection_with_retry(cfg, log)
    except Exception as e:
        log.error(f"No se pudo conectar a SQL: {e}")
        return {"ok": False, "error": str(e)}

    dbs = list_databases(conn, cfg.get("exclude_dbs", []), cfg.get("include_dbs", []))
    total = len(dbs)
    log.info(f"Bases a respaldar: {total}")
    if not dbs:
        return {"ok": True, "ok_dbs": [], "fail_dbs": [], "total_bak": 0, "total_zip": 0}

    backup_dir = Path(cfg["backup_path"])
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.error(f"No se pudo crear/acceder a {backup_dir}: {e}")
        return {"ok": False, "error": f"Ruta inválida: {e}"}

    do_compress = cfg.get("compress", True)
    delete_bak = cfg.get("delete_bak_after_zip", True)
    level = cfg.get("compression_level", 6)
    backup_retries = max(1, int(cfg.get("backup_retries", 2)))
    backup_retry_delay = max(1, int(cfg.get("backup_retry_delay", 15)))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    ok, fail = [], []
    total_bak = total_zip = 0

    for i, db in enumerate(dbs, 1):
        if on_progress:
            on_progress("backup", i, total, db)

        last_err = None
        success = False
        bak_size = zip_size = 0

        for attempt in range(1, backup_retries + 1):
            try:
                if attempt > 1:
                    log.info(f"[{db}] Reintento {attempt}/{backup_retries}…")
                else:
                    log.info(f"[{db}] BACKUP …")

                # Si se cayó la conexión entre BDs, reabrirla
                try:
                    conn.cursor().execute("SELECT 1")
                except Exception:
                    log.warning("  Conexión perdida, reabriendo…")
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = get_connection_with_retry(cfg, log)

                t0 = time.time()
                bak = backup_database(conn, db, cfg["backup_path"], ts)
                bak_size = bak.stat().st_size
                log.info(f"  OK .bak {fmt_size(bak_size)} en {time.time()-t0:.1f}s")

                if do_compress:
                    if on_progress:
                        on_progress("zip", i, total, db)
                    t0 = time.time()
                    zf = compress_to_7z(bak, level)
                    zip_size = zf.stat().st_size
                    ratio = (1 - zip_size / bak_size) * 100 if bak_size else 0
                    log.info(f"  7z {fmt_size(zip_size)} (-{ratio:.0f}%) en {time.time()-t0:.1f}s")
                    if delete_bak:
                        bak.unlink()
                success = True
                break
            except Exception as e:
                last_err = e
                log.warning(f"[{db}] Falló intento {attempt}/{backup_retries}: {e}")
                # Limpiar .bak parcial si quedó
                try:
                    bak_partial = Path(cfg["backup_path"]) / f"{db}_{ts}.bak"
                    if bak_partial.exists():
                        bak_partial.unlink()
                        log.info(f"  Limpieza .bak parcial: {bak_partial.name}")
                except Exception:
                    pass
                if attempt < backup_retries:
                    log.info(f"  Esperando {backup_retry_delay}s antes de reintentar [{db}]…")
                    time.sleep(backup_retry_delay)

        if success:
            total_bak += bak_size
            total_zip += zip_size
            ok.append(db)
        else:
            log.error(f"[{db}] FALLA tras {backup_retries} intentos: {last_err}")
            fail.append((db, str(last_err)))

    removed = cleanup_old(cfg["backup_path"], cfg.get("retention_days", 0), log)
    if removed:
        log.info(f"Retención: {removed} archivos > {cfg['retention_days']} días eliminados")

    log.info("-" * 70)
    log.info(
        f"FIN — OK={len(ok)} FAIL={len(fail)} "
        f".bak={fmt_size(total_bak)} .7z={fmt_size(total_zip)}"
    )
    return {
        "ok": True,
        "ok_dbs": ok,
        "fail_dbs": fail,
        "total_bak": total_bak,
        "total_zip": total_zip,
    }
