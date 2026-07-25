"""
FactuposBackup — App gráfica de respaldo SQL Server.

- Ventana con configuración (servidor, usuario, password, ruta, hora).
- Tabla en vivo del avance de cada BD (Pendiente / Backup / ZIP / OK / FALLA).
- Barra de progreso global y log en tiempo real.
- Programador interno: dispara el backup todos los días a la hora configurada.
- Bandeja del sistema (tray): ocultar/mostrar, ejecutar ahora, salir.
- Checkboxes: "Iniciar con Windows" (registro Run) e "Iniciar minimizado".

Uso:
    python backup_app.py              # abre la ventana
    python backup_app.py --hidden     # arranca minimizado en la bandeja
"""

import argparse
import logging
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue, Empty

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import backup_core as core

APP_NAME = "FactuposBackup"
APP_VERSION = core.APP_VERSION
APP_TITLE = f"FactuposBackup v{APP_VERSION} — Respaldo SQL Server"

# ---------- Tema visual NAVY (look FactuPOS) ----------
NAVY = '#1a4d80'; NAVY_DARK = '#15406b'; BODY = '#eef3fa'
TEXT = '#1f2937'; HEADTXT = '#bfe3ff'; STRIP = '#dbe7f5'

def apply_navy_theme(widget):
    """Aplica el look navy (ttk.Style global) a toda la app."""
    try:
        widget.configure(bg=BODY)
    except Exception:
        pass
    style = ttk.Style(widget)
    try:
        style.theme_use('clam')
    except Exception:
        pass
    FB = ('Segoe UI', 10)
    style.configure('.', background=BODY, foreground=TEXT, font=FB)
    style.configure('TFrame', background=BODY)
    style.configure('TLabel', background=BODY, foreground=TEXT, font=FB)
    style.configure('TLabelframe', background=BODY, bordercolor='#c9d8ea')
    style.configure('TLabelframe.Label', background=BODY, foreground=NAVY, font=('Segoe UI', 10, 'bold'))
    style.configure('TButton', background=NAVY, foreground='white', bordercolor=NAVY,
                    focuscolor=NAVY, padding=(10, 5), font=('Segoe UI', 9, 'bold'))
    style.map('TButton', background=[('active', NAVY_DARK), ('disabled', '#9fb3cc')],
              foreground=[('disabled', '#e5e7eb')])
    style.configure('TCheckbutton', background=BODY, foreground=TEXT, font=FB)
    style.map('TCheckbutton', background=[('active', BODY)])
    style.configure('TRadiobutton', background=BODY, foreground=TEXT, font=FB)
    style.map('TRadiobutton', background=[('active', BODY)])
    style.configure('TEntry', fieldbackground='white', bordercolor='#c9d8ea')
    style.configure('TCombobox', fieldbackground='white', background='white', bordercolor='#c9d8ea')
    style.configure('Treeview', background='white', fieldbackground='white', foreground=TEXT, rowheight=24)
    style.configure('Treeview.Heading', background=NAVY, foreground='white', font=('Segoe UI', 9, 'bold'))
    style.map('Treeview.Heading', background=[('active', NAVY_DARK)])
    style.map('Treeview', background=[('selected', '#2f6fb3')], foreground=[('selected', 'white')])

def navy_header(parent, version=''):
    """Encabezado navy con título + versión grande."""
    h = tk.Frame(parent, bg=NAVY, height=54)
    h.pack(fill='x')
    h.pack_propagate(False)
    tk.Label(h, text="FactuposBackup", font=("Segoe UI", 14, "bold"), fg='white', bg=NAVY).pack(side='left', padx=14)
    if version:
        tk.Label(h, text="v" + version, font=("Segoe UI", 18, "bold"), fg=HEADTXT, bg=NAVY).pack(side='right', padx=16)
    return h

# Win32 autostart (solo Windows)
if sys.platform == "win32":
    import winreg
    AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    AUTOSTART_NAME = APP_NAME
else:
    winreg = None

# Tray
try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    TRAY_OK = True
except ImportError:
    TRAY_OK = False


# ---------- autostart helpers ----------

def autostart_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --hidden'
    # Para .py: preferir pythonw.exe (sin consola negra) si existe al lado de python.exe
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pyw) if pyw.exists() else sys.executable
    return f'"{exe}" "{Path(__file__).resolve()}" --hidden'


def autostart_is_enabled() -> bool:
    if not winreg:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as k:
            val, _ = winreg.QueryValueEx(k, AUTOSTART_NAME)
            return bool(val)
    except FileNotFoundError:
        return False


def autostart_set(enabled: bool):
    if not winreg:
        return
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_ALL_ACCESS) as k:
        if enabled:
            winreg.SetValueEx(k, AUTOSTART_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(k, AUTOSTART_NAME)
            except FileNotFoundError:
                pass


# ---------- tray icon ----------

def make_tray_image():
    img = Image.new("RGB", (64, 64), (15, 23, 42))
    d = ImageDraw.Draw(img)
    d.rectangle((4, 4, 60, 60), outline=(59, 130, 246), width=3)
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    d.text((10, 18), "SQL", fill=(147, 197, 253), font=font)
    return img


# ---------- log handler que envía al UI ----------

class QueueHandler(logging.Handler):
    def __init__(self, q):
        super().__init__()
        self.q = q

    def emit(self, record):
        try:
            self.q.put(self.format(record))
        except Exception:
            pass


# ---------- app ----------

class BackupApp:
    def __init__(self, start_hidden=False):
        self.cfg = core.load_config()
        self.log = core.get_logger()
        self.log.info(f"=== FactuposBackup v{APP_VERSION} iniciada ===")
        self.log_queue = Queue()
        qh = QueueHandler(self.log_queue)
        qh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        self.log.addHandler(qh)

        self.running_lock = threading.Lock()
        self.is_running = False
        self.scheduler_stop = threading.Event()
        self.tray = None
        self._last_db = None

        self._build_ui()
        self._refresh_status_bar()
        self._poll_log_queue()
        self._start_scheduler_thread()

        if TRAY_OK:
            self._build_tray_async()
        else:
            self.btn_hide.config(state="disabled")

        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        if start_hidden and TRAY_OK:
            self.root.after(50, self.hide_to_tray)

        # Mapear unidades de red al iniciar (background)
        threading.Thread(target=self._map_drives_on_start, daemon=True).start()

        # Chequeo automático de actualizaciones 5s después de iniciar
        if self.cfg.get("auto_update_enabled", True):
            self.root.after(5000, lambda: threading.Thread(
                target=self._run_update_check, args=(False,), daemon=True
            ).start())

    # ----- UI -----

    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("760x560")
        self.root.minsize(680, 460)

        apply_navy_theme(self.root)
        navy_header(self.root, APP_VERSION)

        # ---------- Configuración ----------
        cfgframe = ttk.LabelFrame(self.root, text="Configuración", padding=10)
        cfgframe.pack(fill="x", padx=10, pady=(10, 5))

        self.var_server = tk.StringVar(value=self.cfg["server"])
        self.var_user = tk.StringVar(value=self.cfg["user"])
        self.var_pwd = tk.StringVar(value=self.cfg["password"])
        self.var_path = tk.StringVar(value=self.cfg["backup_path"])
        self.var_hour = tk.StringVar(value=self.cfg.get("schedule_hour", "23:00"))
        self.var_retention = tk.StringVar(value=str(self.cfg.get("retention_days", 7)))
        self.var_autostart = tk.BooleanVar(value=autostart_is_enabled())
        self.var_start_hidden = tk.BooleanVar(value=self.cfg.get("start_hidden", False))
        self.var_reboot = tk.BooleanVar(value=self.cfg.get("reboot_enabled", False))
        self.var_reboot_hour = tk.StringVar(value=self.cfg.get("reboot_hour", "03:00"))
        self.var_compress = tk.BooleanVar(value=self.cfg.get("compress", True))
        self.var_auto_update = tk.BooleanVar(value=self.cfg.get("auto_update_enabled", True))

        row = 0
        ttk.Label(cfgframe, text="Servidor SQL:").grid(row=row, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(cfgframe, textvariable=self.var_server, width=40).grid(row=row, column=1, columnspan=2, sticky="we", padx=4)
        row += 1
        ttk.Label(cfgframe, text="Usuario:").grid(row=row, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(cfgframe, textvariable=self.var_user, width=40).grid(row=row, column=1, columnspan=2, sticky="we", padx=4)
        row += 1
        ttk.Label(cfgframe, text="Password:").grid(row=row, column=0, sticky="w", padx=4, pady=3)
        self.entry_pwd = ttk.Entry(cfgframe, textvariable=self.var_pwd, show="•", width=40)
        self.entry_pwd.grid(row=row, column=1, sticky="we", padx=4)
        self.var_show_pwd = tk.BooleanVar(value=False)
        ttk.Checkbutton(cfgframe, text="Mostrar", variable=self.var_show_pwd, command=self._toggle_pwd).grid(row=row, column=2, sticky="w", padx=4)
        row += 1
        ttk.Label(cfgframe, text="Ruta backup:").grid(row=row, column=0, sticky="w", padx=4, pady=3)
        ttk.Entry(cfgframe, textvariable=self.var_path, width=40).grid(row=row, column=1, sticky="we", padx=4)
        ttk.Button(cfgframe, text="...", width=4, command=self._pick_folder).grid(row=row, column=2, sticky="w", padx=4)
        row += 1
        sub = ttk.Frame(cfgframe)
        sub.grid(row=row, column=0, columnspan=3, sticky="we", pady=3)
        ttk.Label(sub, text="Hora diaria (HH:MM):").pack(side="left", padx=(4, 4))
        ttk.Entry(sub, textvariable=self.var_hour, width=8).pack(side="left")
        ttk.Label(sub, text="    Retención (días):").pack(side="left", padx=(20, 4))
        ttk.Entry(sub, textvariable=self.var_retention, width=6).pack(side="left")
        ttk.Checkbutton(sub, text="Comprimir a 7z", variable=self.var_compress).pack(side="left", padx=(20, 4))
        row += 1
        ttk.Checkbutton(cfgframe, text="Iniciar con Windows", variable=self.var_autostart).grid(row=row, column=0, columnspan=2, sticky="w", padx=4, pady=(8, 0))
        row += 1
        ttk.Checkbutton(cfgframe, text="Iniciar minimizado en la bandeja del sistema", variable=self.var_start_hidden).grid(row=row, column=0, columnspan=2, sticky="w", padx=4)
        row += 1
        rebootrow = ttk.Frame(cfgframe)
        rebootrow.grid(row=row, column=0, columnspan=3, sticky="we", pady=(4, 0))
        ttk.Checkbutton(rebootrow, text="Reiniciar el servidor diariamente a las", variable=self.var_reboot).pack(side="left", padx=(4, 4))
        ttk.Entry(rebootrow, textvariable=self.var_reboot_hour, width=8).pack(side="left")
        ttk.Label(rebootrow, text="(HH:MM, formato 24h — ejecuta shutdown /r /f /t 1)").pack(side="left", padx=(8, 0))
        row += 1
        updrow = ttk.Frame(cfgframe)
        updrow.grid(row=row, column=0, columnspan=3, sticky="we", pady=(4, 0))
        ttk.Checkbutton(updrow, text="Buscar actualizaciones automáticamente al iniciar", variable=self.var_auto_update).pack(side="left", padx=(4, 4))
        ttk.Button(updrow, text="Buscar ahora", command=self.check_update_clicked).pack(side="left", padx=(8, 0))
        row += 1
        wlrow = ttk.Frame(cfgframe)
        wlrow.grid(row=row, column=0, columnspan=3, sticky="we", pady=(4, 0))
        ttk.Label(wlrow, text="Auto-logon Windows:").pack(side="left", padx=(4, 4))
        ttk.Button(wlrow, text="Establecer auto-inicio", command=self.set_winlogon_clicked).pack(side="left")
        ttk.Button(wlrow, text="Quitar auto-inicio", command=self.clear_winlogon_clicked).pack(side="left", padx=(4, 0))
        ttk.Label(wlrow, text="(requiere Administrador, sirve en Server 2019/2022/2025)",
                  foreground="#64748b").pack(side="left", padx=(8, 0))
        row += 1
        ndrow = ttk.Frame(cfgframe)
        ndrow.grid(row=row, column=0, columnspan=3, sticky="we", pady=(4, 0))
        ttk.Label(ndrow, text="Unidades de red:").pack(side="left", padx=(4, 4))
        ttk.Button(ndrow, text="Configurar…", command=self.open_network_drives_dialog).pack(side="left")
        ttk.Label(ndrow, text="(net use al iniciar la app — letra, UNC, usuario, password)",
                  foreground="#64748b").pack(side="left", padx=(8, 0))
        row += 1
        btnrow = ttk.Frame(cfgframe)
        btnrow.grid(row=row, column=0, columnspan=3, sticky="we", pady=(8, 0))
        ttk.Button(btnrow, text="Probar conexión", command=self.test_connection).pack(side="left")
        ttk.Button(btnrow, text="Guardar configuración", command=self.save_settings).pack(side="right")

        cfgframe.columnconfigure(1, weight=1)

        # ---------- Estado, progreso y botón principal ----------
        statframe = ttk.LabelFrame(self.root, text="Estado", padding=8)
        statframe.pack(fill="x", padx=10, pady=5)

        # Botones GRANDES: Iniciar respaldo + Restaurar BDs (lado a lado, siempre visibles)
        style = ttk.Style()
        style.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=8,
                        background=NAVY, foreground="white")
        style.map("Big.TButton", background=[('active', NAVY_DARK)])
        style.configure("BigRestore.TButton", font=("Segoe UI", 10, "bold"), padding=8,
                        background=NAVY, foreground="white")
        style.map("BigRestore.TButton", background=[('active', NAVY_DARK)])
        bigrow = ttk.Frame(statframe)
        bigrow.pack(fill="x", pady=(0, 8))
        self.btn_run_top = ttk.Button(
            bigrow,
            text="▶  INICIAR RESPALDO AHORA",
            style="Big.TButton",
            command=self.run_backup_clicked,
        )
        self.btn_run_top.pack(side="left", fill="x", expand=True)
        ttk.Button(
            bigrow,
            text="↺ RESTAURAR BDs…",
            style="BigRestore.TButton",
            command=self.open_restore_dialog,
        ).pack(side="left", padx=(8, 0))

        self.lbl_status = ttk.Label(statframe, text="Listo. Esperando próxima ejecución.", font=("Segoe UI", 10, "bold"))
        self.lbl_status.pack(anchor="w")
        self.lbl_next = ttk.Label(statframe, text="Próxima corrida: —")
        self.lbl_next.pack(anchor="w")

        progrow = ttk.Frame(statframe)
        progrow.pack(fill="x", pady=(6, 0))
        self.progress = ttk.Progressbar(progrow, mode="determinate", length=600)
        self.progress.pack(side="left", fill="x", expand=True)
        self.lbl_count = ttk.Label(progrow, text="0 / 0", width=10)
        self.lbl_count.pack(side="right", padx=(8, 0))

        # ---------- Tabla de BDs ----------
        tableframe = ttk.LabelFrame(self.root, text="Bases de datos", padding=4)
        tableframe.pack(fill="both", expand=True, padx=10, pady=5)

        cols = ("db", "estado", "bak", "zip", "tiempo")
        self.tree = ttk.Treeview(tableframe, columns=cols, show="headings", height=5)
        self.tree.heading("db", text="Base de datos")
        self.tree.heading("estado", text="Estado")
        self.tree.heading("bak", text="Tamaño .bak")
        self.tree.heading("zip", text="Tamaño .7z")
        self.tree.heading("tiempo", text="Tiempo")
        self.tree.column("db", width=240, anchor="w")
        self.tree.column("estado", width=140, anchor="w")
        self.tree.column("bak", width=110, anchor="e")
        self.tree.column("zip", width=110, anchor="e")
        self.tree.column("tiempo", width=80, anchor="e")
        self.tree.tag_configure("ok", background="#dcfce7")
        self.tree.tag_configure("fail", background="#fee2e2")
        self.tree.tag_configure("running", background="#dbeafe")
        scroll = ttk.Scrollbar(tableframe, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # ---------- Log ----------
        logframe = ttk.LabelFrame(self.root, text="Log", padding=4)
        logframe.pack(fill="both", expand=True, padx=10, pady=5)
        self.txt_log = tk.Text(logframe, height=4, wrap="none", bg="#0f172a", fg="#cbd5e1", font=("Consolas", 9))
        logscroll = ttk.Scrollbar(logframe, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=logscroll.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        logscroll.pack(side="right", fill="y")

        # ---------- Acciones ----------
        actframe = ttk.Frame(self.root)
        actframe.pack(fill="x", padx=10, pady=(0, 10))
        self.btn_run = ttk.Button(actframe, text="▶ Ejecutar respaldo ahora", command=self.run_backup_clicked)
        self.btn_run.pack(side="left")
        self.btn_hide = ttk.Button(actframe, text="Ocultar a bandeja", command=self.hide_to_tray)
        self.btn_hide.pack(side="left", padx=(8, 0))
        ttk.Button(actframe, text="Abrir carpeta de backups", command=self.open_backup_folder).pack(side="left", padx=(8, 0))
        ttk.Button(actframe, text="Salir", command=self.quit_app).pack(side="right")
        ttk.Label(actframe, text=f"v{APP_VERSION}", foreground="#64748b",
                  font=("Segoe UI", 9, "bold")).pack(side="right", padx=(0, 12))

    def _toggle_pwd(self):
        self.entry_pwd.config(show="" if self.var_show_pwd.get() else "•")

    def _pick_folder(self):
        d = filedialog.askdirectory(initialdir=self.var_path.get() or "/", title="Seleccionar carpeta de backup")
        if d:
            self.var_path.set(d.replace("/", "\\"))

    # ----- acciones -----

    def save_settings(self):
        try:
            datetime.strptime(self.var_hour.get(), "%H:%M")
        except ValueError:
            messagebox.showerror("Error", "La hora debe estar en formato HH:MM (24h).")
            return
        try:
            ret = int(self.var_retention.get())
        except ValueError:
            messagebox.showerror("Error", "Retención debe ser un número entero.")
            return

        self.cfg["server"] = self.var_server.get().strip()
        self.cfg["user"] = self.var_user.get().strip()
        self.cfg["password"] = self.var_pwd.get()
        self.cfg["backup_path"] = self.var_path.get().strip()
        self.cfg["schedule_hour"] = self.var_hour.get().strip()
        self.cfg["retention_days"] = ret
        self.cfg["start_hidden"] = self.var_start_hidden.get()
        try:
            datetime.strptime(self.var_reboot_hour.get(), "%H:%M")
        except ValueError:
            messagebox.showerror("Error", "La hora de reinicio debe estar en formato HH:MM (24h).")
            return
        self.cfg["reboot_enabled"] = self.var_reboot.get()
        self.cfg["reboot_hour"] = self.var_reboot_hour.get().strip()
        self.cfg["compress"] = self.var_compress.get()
        self.cfg["auto_update_enabled"] = self.var_auto_update.get()
        core.save_config(self.cfg)

        autostart_set(self.var_autostart.get())

        self._refresh_status_bar()
        messagebox.showinfo("Configuración", "Configuración guardada.")

    def test_connection(self):
        cfg = dict(self.cfg)
        cfg["server"] = self.var_server.get().strip()
        cfg["user"] = self.var_user.get().strip()
        cfg["password"] = self.var_pwd.get()
        try:
            conn = core.get_connection(cfg)
            dbs = core.list_databases(conn, cfg.get("exclude_dbs", []), cfg.get("include_dbs", []))
            messagebox.showinfo("Conexión OK", f"Conexión exitosa a {cfg['server']}.\n{len(dbs)} BDs encontradas.")
        except Exception as e:
            messagebox.showerror("Error de conexión", str(e))

    def open_backup_folder(self):
        path = self.var_path.get()
        if sys.platform == "win32":
            import os
            try:
                os.startfile(path)
            except OSError as e:
                messagebox.showerror("Error", f"No se pudo abrir {path}\n{e}")

    def open_restore_dialog(self):
        RestoreDialog(self.root, self.cfg, self.log)

    # ----- network drives -----

    def _map_drives_on_start(self):
        drives = self.cfg.get("network_drives", [])
        if not drives:
            return
        self.log.info(f"Mapeando {len(drives)} unidad(es) de red al iniciar…")
        core.map_network_drives(drives, log=self.log)

    def open_network_drives_dialog(self):
        NetworkDrivesDialog(self.root, self.cfg, self.log,
                            on_save=self._on_drives_saved)

    def _on_drives_saved(self, new_drives):
        self.cfg["network_drives"] = new_drives
        core.save_config(self.cfg)
        # Re-mapear inmediato en background
        threading.Thread(target=self._map_drives_on_start, daemon=True).start()
        messagebox.showinfo("Unidades de red",
                            "Configuración guardada y mapeo aplicado.")

    # ----- auto-logon Windows -----

    def set_winlogon_clicked(self):
        WinLogonDialog(self.root, self.log)

    def clear_winlogon_clicked(self):
        if not messagebox.askyesno(
            "Quitar auto-logon",
            "Esto deshabilita el auto-logon de Windows.\n\n¿Continuar?",
            icon="warning",
        ):
            return
        result = core.windows_disable_autologon(log=self.log)
        if result["ok"]:
            messagebox.showinfo("Auto-logon", "Auto-logon deshabilitado.")
        else:
            messagebox.showerror("Auto-logon", result["error"])

    # ----- auto-update -----

    def check_update_clicked(self):
        threading.Thread(target=self._run_update_check, args=(True,), daemon=True).start()

    def _run_update_check(self, interactive: bool):
        cfg = core.load_config()
        url = cfg.get("update_check_url", "")
        if not url:
            if interactive:
                self.root.after(0, lambda: messagebox.showerror("Update", "URL de actualización vacía."))
            return
        result = core.check_for_update(APP_VERSION, url, log=self.log)
        if not result:
            if interactive:
                self.root.after(0, lambda: messagebox.showinfo(
                    "Actualizaciones",
                    f"Estás en la última versión (v{APP_VERSION})."
                ))
            return
        if "error" in result:
            if interactive:
                err = result["error"]
                self.root.after(0, lambda: messagebox.showwarning(
                    "Update", f"No se pudo consultar el servidor:\n{err}"
                ))
            return
        # Hay update disponible
        srv_ver = result.get("version", "?")
        notes = result.get("notes", "(sin notas)")
        url_dl = result.get("download_url") or result.get("downloadUrl") or ""
        msg = (
            f"Hay una nueva versión disponible.\n\n"
            f"  Actual:   v{APP_VERSION}\n"
            f"  Nueva:    v{srv_ver}\n"
            f"  Notas:    {notes}\n\n"
            f"¿Descargar e instalar ahora?\n"
            f"(La app se cerrará brevemente y se reiniciará sola)."
        )
        def ask():
            if messagebox.askyesno(f"Actualización disponible — v{srv_ver}", msg, icon="info"):
                threading.Thread(target=self._apply_update, args=(url_dl,), daemon=True).start()
        self.root.after(0, ask)

    def _apply_update(self, url_dl: str):
        from pathlib import Path
        import sys as _sys
        try:
            current_exe = Path(_sys.executable) if getattr(_sys, "frozen", False) else Path(__file__).resolve()
            if not getattr(_sys, "frozen", False):
                self.log.warning("Auto-update solo funciona en el .exe compilado, no en .py.")
                self.root.after(0, lambda: messagebox.showwarning(
                    "Update", "Auto-update solo funciona en el .exe compilado."
                ))
                return
            new_exe = current_exe.parent / "FactuposBackup.new.exe"
            self.log.info(f"Iniciando auto-update → {new_exe}")
            self.root.after(0, lambda: self.lbl_status.config(text="Descargando actualización…"))

            def progress(done, total):
                pct = (done / total * 100) if total else 0
                self.root.after(0, lambda: self.lbl_status.config(
                    text=f"Descargando: {core.fmt_size(done)} / {core.fmt_size(total)} ({pct:.0f}%)"
                ))

            core.download_update(url_dl, new_exe, on_progress=progress, log=self.log)
            hidden = self.cfg.get("start_hidden", False)
            core.apply_update(current_exe, new_exe, hidden=hidden, log=self.log)
            self.log.info("Updater lanzado. Cerrando app actual…")
            self.root.after(100, self.quit_app)
        except Exception as e:
            self.log.error(f"Auto-update falló: {e}")
            self.root.after(0, lambda: messagebox.showerror(
                "Update", f"No se pudo aplicar la actualización:\n{e}"
            ))

    def run_backup_clicked(self):
        with self.running_lock:
            if self.is_running:
                messagebox.showwarning("En curso", "Ya hay un respaldo en ejecución.")
                return
        threading.Thread(target=self._run_backup_thread, daemon=True).start()

    def _run_backup_thread(self):
        with self.running_lock:
            self.is_running = True
        try:
            self.root.after(0, self._reset_table)
            self.root.after(0, lambda: self.lbl_status.config(text="Listando bases de datos…"))
            self.root.after(0, lambda: (self.btn_run.config(state="disabled"), self.btn_run_top.config(state="disabled")))

            cfg = core.load_config()
            try:
                conn = core.get_connection(cfg)
                dbs = core.list_databases(conn, cfg.get("exclude_dbs", []), cfg.get("include_dbs", []))
                conn.close()
            except Exception as e:
                self.root.after(0, lambda: self.lbl_status.config(text=f"Error de conexión: {e}"))
                self.log.error(f"Conexión fallida: {e}")
                return

            self.root.after(0, lambda: self._populate_table(dbs))

            def cb(stage, done, total, dbname):
                self.root.after(0, lambda: self._on_progress(stage, done, total, dbname))

            self.root.after(0, lambda: self.lbl_status.config(text="Respaldo en curso…"))
            result = core.run_backup(cfg, log=self.log, on_progress=cb)

            ok = len(result.get("ok_dbs", []))
            fail = len(result.get("fail_dbs", []))
            txt = f"Finalizado. OK={ok} FALLA={fail}"
            self.root.after(0, lambda: self.lbl_status.config(text=txt))
            for db, _ in result.get("fail_dbs", []):
                self.root.after(0, lambda d=db: self._set_row_state(d, "FALLA", tag="fail"))
        finally:
            with self.running_lock:
                self.is_running = False
            self.root.after(0, lambda: (self.btn_run.config(state="normal"), self.btn_run_top.config(state="normal")))
            self.root.after(0, self._refresh_status_bar)

    def _reset_table(self):
        for it in self.tree.get_children():
            self.tree.delete(it)
        self.progress["value"] = 0
        self.lbl_count.config(text="0 / 0")

    def _populate_table(self, dbs):
        self.progress["maximum"] = len(dbs)
        self.lbl_count.config(text=f"0 / {len(dbs)}")
        for db in dbs:
            self.tree.insert("", "end", iid=db, values=(db, "Pendiente", "—", "—", "—"))

    def _on_progress(self, stage, done, total, dbname):
        self.progress["value"] = done - 1 if stage == "backup" else done
        self.lbl_count.config(text=f"{done} / {total}")
        if stage == "backup":
            self._set_row_state(dbname, "Respaldando…", tag="running")
        elif stage == "zip":
            self._set_row_state(dbname, "Comprimiendo…", tag="running")
        self.root.update_idletasks()

    def _set_row_state(self, dbname, estado, bak=None, zip_=None, tiempo=None, tag=None):
        if dbname not in self.tree.get_children():
            return
        vals = list(self.tree.item(dbname, "values"))
        vals[1] = estado
        if bak is not None: vals[2] = bak
        if zip_ is not None: vals[3] = zip_
        if tiempo is not None: vals[4] = tiempo
        self.tree.item(dbname, values=vals, tags=(tag,) if tag else ())

    # ----- log poller -----

    def _poll_log_queue(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.txt_log.insert("end", line + "\n")
                self.txt_log.see("end")
                self._maybe_extract_size(line)
        except Empty:
            pass
        self.root.after(150, self._poll_log_queue)

    def _maybe_extract_size(self, line):
        if "BACKUP …" in line:
            try:
                self._last_db = line.split("[", 1)[1].split("]", 1)[0]
            except Exception:
                self._last_db = None
        elif "OK .bak" in line and self._last_db:
            try:
                size = line.split("OK .bak", 1)[1].split(" en ")[0].strip()
                tiempo = line.split(" en ", 1)[1].strip()
                self._set_row_state(self._last_db, "Respaldo OK", bak=size, tiempo=tiempo)
            except Exception:
                pass
        elif "ZIP " in line and self._last_db:
            try:
                rest = line.split("ZIP ", 1)[1]
                size = rest.split(" (", 1)[0].strip()
                tiempo = rest.split(" en ", 1)[1].strip() if " en " in rest else "—"
                self._set_row_state(self._last_db, "OK", zip_=size, tiempo=tiempo, tag="ok")
            except Exception:
                pass

    # ----- scheduler -----

    def _start_scheduler_thread(self):
        threading.Thread(target=self._scheduler_loop, daemon=True).start()
        threading.Thread(target=self._reboot_loop, daemon=True).start()

    def _reboot_loop(self):
        import subprocess
        last_fired_minute = None
        while not self.scheduler_stop.is_set():
            try:
                cfg = core.load_config()
                if not cfg.get("reboot_enabled", False):
                    if self.scheduler_stop.wait(timeout=60):
                        return
                    continue
                hh_mm = cfg.get("reboot_hour", "03:00")
                hour, minute = (int(x) for x in hh_mm.split(":"))
                now = datetime.now()
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                wait = (target - now).total_seconds()
                if self.scheduler_stop.wait(timeout=min(wait, 60)):
                    return
                now = datetime.now()
                key = now.strftime("%Y-%m-%d %H:%M")
                if (now >= target and cfg.get("reboot_enabled", False)
                        and key != last_fired_minute):
                    last_fired_minute = key
                    grace = int(cfg.get("reboot_grace_seconds", 1))
                    self.log.info(f"Reinicio programado del servidor ({hh_mm}). shutdown /r /f /t {grace}")
                    try:
                        subprocess.run(
                            ["shutdown", "/r", "/f", "/t", str(grace), "/c",
                             "FactuposBackup: reinicio diario programado"],
                            check=False,
                        )
                    except Exception as e:
                        self.log.error(f"Error ejecutando shutdown: {e}")
                    time.sleep(60)
            except Exception as e:
                self.log.error(f"Reboot scheduler error: {e}")
                time.sleep(30)

    def _scheduler_loop(self):
        while not self.scheduler_stop.is_set():
            try:
                hh_mm = self.cfg.get("schedule_hour", "23:00")
                hour, minute = (int(x) for x in hh_mm.split(":"))
                now = datetime.now()
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                wait = (target - now).total_seconds()
                if self.scheduler_stop.wait(timeout=min(wait, 60)):
                    return
                if datetime.now() >= target:
                    self.log.info(f"Disparo programado ({hh_mm}).")
                    self._run_backup_thread()
                    time.sleep(60)
            except Exception as e:
                self.log.error(f"Scheduler error: {e}")
                time.sleep(30)

    def _refresh_status_bar(self):
        try:
            hh_mm = self.cfg.get("schedule_hour", "23:00")
            hour, minute = (int(x) for x in hh_mm.split(":"))
            now = datetime.now()
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            txt = f"Próxima corrida: {target.strftime('%Y-%m-%d %H:%M')}"
            if self.cfg.get("reboot_enabled", False):
                rh, rm = (int(x) for x in self.cfg.get("reboot_hour", "03:00").split(":"))
                rtarget = now.replace(hour=rh, minute=rm, second=0, microsecond=0)
                if rtarget <= now:
                    rtarget += timedelta(days=1)
                txt += f"   |   Próximo reinicio servidor: {rtarget.strftime('%Y-%m-%d %H:%M')}"
            self.lbl_next.config(text=txt)
        except Exception:
            self.lbl_next.config(text="Próxima corrida: (configurá la hora)")

    # ----- tray -----

    def _build_tray_async(self):
        threading.Thread(target=self._build_tray, daemon=True).start()

    def _build_tray(self):
        try:
            image = make_tray_image()
            menu = pystray.Menu(
                pystray.MenuItem("Mostrar ventana", self._tray_show, default=True),
                pystray.MenuItem("Ejecutar respaldo ahora", self._tray_run),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Salir", self._tray_quit),
            )
            self.tray = pystray.Icon(APP_NAME, image, APP_TITLE, menu)
            self.tray.run()
        except Exception as e:
            self.log.error(f"Tray no disponible: {e}")

    def _tray_show(self, *_):
        self.root.after(0, self.show_window)

    def _tray_run(self, *_):
        self.root.after(0, self.run_backup_clicked)

    def _tray_quit(self, *_):
        self.root.after(0, self.quit_app)

    def hide_to_tray(self):
        if not TRAY_OK or self.tray is None:
            self.root.iconify()
            return
        self.root.withdraw()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def quit_app(self):
        self.scheduler_stop.set()
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


class RestoreDialog:
    """Modal: pickear carpeta, listar .bak/.7z/.zip, marcar cuáles, restaurar."""

    def __init__(self, parent, cfg, log):
        self.cfg = cfg
        self.log = log
        self.files = []
        self.running = False

        self.win = tk.Toplevel(parent)
        self.win.title("Restaurar BDs desde carpeta")
        self.win.geometry("780x640")
        self.win.configure(bg=BODY)
        self.win.minsize(700, 540)
        self.win.transient(parent)

        # ---- Carpeta de origen ----
        top = ttk.LabelFrame(self.win, text="Carpeta origen (.bak / .7z / .zip)", padding=6)
        top.pack(fill="x", padx=8, pady=(8, 4))
        self.var_folder = tk.StringVar()
        rowf = ttk.Frame(top)
        rowf.pack(fill="x")
        ttk.Entry(rowf, textvariable=self.var_folder).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(rowf, text="...", width=4, command=self._pick_folder).pack(side="left")
        ttk.Button(rowf, text="↻ Escanear", command=self._scan).pack(side="left", padx=(8, 0))

        # ---- Carpetas destino para .mdf y .ldf ----
        dest = ttk.LabelFrame(self.win, text="Destino en el SQL Server (¿dónde caen los .mdf y .ldf?)", padding=6)
        dest.pack(fill="x", padx=8, pady=4)
        self.var_data = tk.StringVar(value=cfg.get("restore_data_path", "D:\\SqlData"))
        self.var_log = tk.StringVar(value=cfg.get("restore_log_path", "C:\\SqlLog"))

        rowd = ttk.Frame(dest)
        rowd.pack(fill="x", pady=2)
        ttk.Label(rowd, text="Datos (.mdf):", width=14).pack(side="left")
        ttk.Entry(rowd, textvariable=self.var_data).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(rowd, text="...", width=4, command=lambda: self._pick_dest(self.var_data, "Carpeta destino para .mdf")).pack(side="left")

        rowl = ttk.Frame(dest)
        rowl.pack(fill="x", pady=2)
        ttk.Label(rowl, text="Logs (.ldf):", width=14).pack(side="left")
        ttk.Entry(rowl, textvariable=self.var_log).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(rowl, text="...", width=4, command=lambda: self._pick_dest(self.var_log, "Carpeta destino para .ldf")).pack(side="left")

        rowdh = ttk.Frame(dest)
        rowdh.pack(fill="x", pady=(4, 0))
        ttk.Button(rowdh, text="Usar defaults del server", command=self._fill_defaults_from_server).pack(side="left")
        ttk.Label(rowdh, text="(rutas del SQL: InstanceDefaultDataPath / LogPath)",
                  foreground="#64748b").pack(side="left", padx=(8, 0))

        # ---- Sufijo a quitar de los nombres de archivo ----
        sfx = ttk.LabelFrame(self.win, text="Naming destino", padding=6)
        sfx.pack(fill="x", padx=8, pady=4)
        rowsfx = ttk.Frame(sfx)
        rowsfx.pack(fill="x")
        ttk.Label(rowsfx, text="Sufijo a quitar del nombre:", width=24).pack(side="left")
        self.var_strip_suffix = tk.StringVar()
        ttk.Entry(rowsfx, textvariable=self.var_strip_suffix, width=20).pack(side="left", padx=(0, 4))
        ttk.Button(rowsfx, text="Aplicar", command=self._reapply_suffix).pack(side="left")
        ttk.Label(rowsfx, text="ej: _INVEFACON  →  alianzamarket_INVEFACON.bak se restaura como 'alianzamarket'",
                  foreground="#64748b").pack(side="left", padx=(8, 0))

        # ---- Tabla de archivos ----
        tableframe = ttk.LabelFrame(self.win, text="Archivos detectados (.bak / .7z / .zip)", padding=4)
        tableframe.pack(fill="both", expand=True, padx=8, pady=4)

        cols = ("sel", "archivo", "destino", "tamaño", "estado")
        self.tree = ttk.Treeview(tableframe, columns=cols, show="headings", height=10, selectmode="none")
        self.tree.heading("sel", text="✓")
        self.tree.heading("archivo", text="Archivo")
        self.tree.heading("destino", text="Destino BD (doble click p/editar)")
        self.tree.heading("tamaño", text="Tamaño")
        self.tree.heading("estado", text="Estado")
        self.tree.column("sel", width=40, anchor="center")
        self.tree.column("archivo", width=260, anchor="w")
        self.tree.column("destino", width=200, anchor="w")
        self.tree.column("tamaño", width=80, anchor="e")
        self.tree.column("estado", width=160, anchor="w")
        self.tree.tag_configure("ok", background="#dcfce7")
        self.tree.tag_configure("fail", background="#fee2e2")
        self.tree.tag_configure("running", background="#dbeafe")
        scroll = ttk.Scrollbar(tableframe, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<Double-Button-1>", self._on_tree_dblclick)

        # ---- Acciones de selección ----
        selrow = ttk.Frame(self.win, padding=(8, 0))
        selrow.pack(fill="x")
        ttk.Button(selrow, text="Seleccionar todo", command=self._select_all).pack(side="left")
        ttk.Button(selrow, text="Deseleccionar todo", command=self._select_none).pack(side="left", padx=(4, 0))
        self.lbl_count = ttk.Label(selrow, text="0 seleccionado(s)")
        self.lbl_count.pack(side="right")

        # ---- Progreso ----
        progrow = ttk.Frame(self.win, padding=(8, 4))
        progrow.pack(fill="x")
        self.lbl_status = ttk.Label(progrow, text="Listo.", font=("Segoe UI", 9, "bold"))
        self.lbl_status.pack(anchor="w")
        self.progress = ttk.Progressbar(progrow, mode="determinate")
        self.progress.pack(fill="x", pady=(2, 0))

        # ---- Botones ----
        btnrow = ttk.Frame(self.win, padding=8)
        btnrow.pack(fill="x")
        warn = ttk.Label(btnrow,
            text="⚠ El RESTORE sobreescribe la BD destino (WITH REPLACE). Procede con cuidado.",
            foreground="#c2410c")
        warn.pack(side="left")
        ttk.Button(btnrow, text="Cerrar", command=self.win.destroy).pack(side="right")
        self.btn_restore = ttk.Button(btnrow, text="↺ Restaurar seleccionadas",
                                      command=self._restore_clicked)
        self.btn_restore.pack(side="right", padx=(0, 8))

    def _pick_folder(self):
        d = filedialog.askdirectory(title="Carpeta con archivos .bak / .7z / .zip")
        if d:
            self.var_folder.set(d.replace("/", "\\"))
            self._scan()

    def _pick_dest(self, var, title):
        d = filedialog.askdirectory(title=title)
        if d:
            var.set(d.replace("/", "\\"))

    def _fill_defaults_from_server(self):
        """Conecta y prefilla las carpetas destino con los defaults del SQL Server."""
        try:
            conn = core.get_connection(self.cfg)
            self.var_data.set(core.default_data_path(conn).rstrip("\\"))
            self.var_log.set(core.default_log_path(conn).rstrip("\\"))
            conn.close()
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo consultar el SQL Server:\n{e}")

    def _scan(self):
        from pathlib import Path
        folder = self.var_folder.get().strip()
        if not folder:
            return
        p = Path(folder)
        if not p.exists():
            messagebox.showerror("Error", f"La carpeta no existe:\n{folder}")
            return
        files = core.scan_backup_folder(p)
        for it in self.tree.get_children():
            self.tree.delete(it)
        self.files = files
        suffix = self.var_strip_suffix.get().strip()
        for f in files:
            size = core.fmt_size(f.stat().st_size)
            destino = core.derive_db_name(f, strip_suffix=suffix)
            self.tree.insert("", "end", iid=str(f),
                             values=("☑", f.name, destino, size, ""))
        self._update_count()

    def _reapply_suffix(self):
        """Recalcula la columna 'Destino BD' usando el sufijo actual."""
        suffix = self.var_strip_suffix.get().strip()
        from pathlib import Path as _Path
        for it in self.tree.get_children():
            f = _Path(it)
            destino = core.derive_db_name(f, strip_suffix=suffix)
            v = list(self.tree.item(it, "values"))
            v[2] = destino  # columna Destino BD
            self.tree.item(it, values=v)

    def _on_tree_dblclick(self, event):
        """Doble click en la columna Destino BD → editar inline."""
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row or col != "#3":  # columna 'destino' es la #3
            return
        from tkinter import simpledialog
        current = self.tree.item(row, "values")[2]
        new = simpledialog.askstring("Renombrar destino BD",
                                     f"Nuevo nombre destino para:\n{self.tree.item(row, 'values')[1]}",
                                     initialvalue=current, parent=self.win)
        if new:
            v = list(self.tree.item(row, "values"))
            v[2] = new.strip()
            self.tree.item(row, values=v)

    def _on_tree_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        if not row or col != "#1":
            return
        vals = list(self.tree.item(row, "values"))
        vals[0] = "☐" if vals[0] == "☑" else "☑"
        self.tree.item(row, values=vals)
        self._update_count()

    def _select_all(self):
        for it in self.tree.get_children():
            v = list(self.tree.item(it, "values"))
            v[0] = "☑"
            self.tree.item(it, values=v)
        self._update_count()

    def _select_none(self):
        for it in self.tree.get_children():
            v = list(self.tree.item(it, "values"))
            v[0] = "☐"
            self.tree.item(it, values=v)
        self._update_count()

    def _update_count(self):
        n = sum(1 for it in self.tree.get_children() if self.tree.item(it, "values")[0] == "☑")
        self.lbl_count.config(text=f"{n} seleccionado(s)")

    def _selected_files(self):
        from pathlib import Path
        return [Path(it) for it in self.tree.get_children()
                if self.tree.item(it, "values")[0] == "☑"]

    def _restore_clicked(self):
        if self.running:
            return
        selected = self._selected_files()
        if not selected:
            messagebox.showwarning("Sin selección", "Marcá al menos un archivo para restaurar.")
            return
        data_p = self.var_data.get().strip()
        log_p = self.var_log.get().strip()
        dest_msg = (
            f"\nDatos (.mdf) → {data_p or '(default del server)'}"
            f"\nLogs  (.ldf) → {log_p or '(default del server)'}"
        )
        if not messagebox.askyesno(
            "Confirmar RESTORE",
            f"Vas a restaurar {len(selected)} BD(s). Esto SOBREESCRIBE las BDs destino existentes."
            f"\n{dest_msg}\n\n¿Continuar?",
            icon="warning",
        ):
            return
        threading.Thread(target=self._run_restore_thread, args=(selected,), daemon=True).start()

    def _run_restore_thread(self, files):
        self.running = True
        try:
            self.win.after(0, lambda: self.btn_restore.config(state="disabled"))
            self.win.after(0, lambda: self.progress.config(maximum=len(files), value=0))
            self.win.after(0, lambda: self.lbl_status.config(text="Restaurando…"))
            for it in self.tree.get_children():
                v = list(self.tree.item(it, "values"))
                v[3] = ""
                self.tree.item(it, values=v, tags=())

            def cb(stage, done, total, fname, dbname):
                def upd():
                    self.progress["value"] = done - 1 if stage == "prep" else done
                    iid = next((i for i in self.tree.get_children() if self.tree.item(i, "values")[1] == fname), None)
                    if iid:
                        v = list(self.tree.item(iid, "values"))
                        v[3] = "Preparando…" if stage == "prep" else f"RESTORE [{dbname}]…"
                        self.tree.item(iid, values=v, tags=("running",))
                    self.lbl_status.config(text=f"{done} / {total} — {fname}")
                self.win.after(0, upd)

            data_p = self.var_data.get().strip() or None
            log_p = self.var_log.get().strip() or None
            # Persistir las rutas para próximas corridas
            try:
                cfg_save = core.load_config()
                if data_p:
                    cfg_save["restore_data_path"] = data_p
                if log_p:
                    cfg_save["restore_log_path"] = log_p
                core.save_config(cfg_save)
            except Exception:
                pass
            # Construir dict targets {filename: dbname destino} desde la tabla
            targets = {}
            for it in self.tree.get_children():
                vals = self.tree.item(it, "values")
                if vals[0] == "☑":
                    targets[vals[1]] = vals[2]
            result = core.run_restore(self.cfg, None, files, log=self.log,
                                      on_progress=cb, data_path=data_p, log_path=log_p,
                                      targets=targets)

            for fname, dbname in result["ok"]:
                iid = next((i for i in self.tree.get_children() if self.tree.item(i, "values")[1] == fname), None)
                if iid:
                    v = list(self.tree.item(iid, "values"))
                    v[3] = f"OK → [{dbname}]"
                    self.win.after(0, lambda i=iid, vv=v: self.tree.item(i, values=vv, tags=("ok",)))
            for fname, err in result["fail"]:
                iid = next((i for i in self.tree.get_children() if self.tree.item(i, "values")[1] == fname), None)
                if iid:
                    v = list(self.tree.item(iid, "values"))
                    v[3] = f"FALLA: {err[:80]}"
                    self.win.after(0, lambda i=iid, vv=v: self.tree.item(i, values=vv, tags=("fail",)))

            ok = len(result["ok"])
            fail = len(result["fail"])
            self.win.after(0, lambda: self.lbl_status.config(text=f"Finalizado. OK={ok}  FALLA={fail}"))
            self.win.after(0, lambda: self.progress.config(value=len(files)))
        finally:
            self.running = False
            self.win.after(0, lambda: self.btn_restore.config(state="normal"))


class WinLogonDialog:
    """Modal: pedir usuario+password+(dominio opcional) y aplicar auto-logon de Windows."""

    def __init__(self, parent, log):
        self.log = log
        self.win = tk.Toplevel(parent)
        self.win.title("Establecer auto-logon de Windows")
        self.win.geometry("520x340")
        self.win.configure(bg=BODY)
        self.win.transient(parent)
        self.win.grab_set()

        import os
        cur_user = os.environ.get("USERNAME", "")
        cur_domain = os.environ.get("USERDOMAIN", os.environ.get("COMPUTERNAME", ""))

        frame = ttk.Frame(self.win, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame,
            text="Configura Windows para que loguee automáticamente al usuario\n"
                 "indicado al iniciar el server, sin pedir password.\n",
            foreground="#374151").grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(frame, text="Usuario:").grid(row=1, column=0, sticky="w", pady=(8, 4))
        self.var_user = tk.StringVar(value=cur_user)
        ttk.Entry(frame, textvariable=self.var_user, width=36).grid(row=1, column=1, sticky="we", pady=(8, 4))

        ttk.Label(frame, text="Password:").grid(row=2, column=0, sticky="w", pady=4)
        self.var_pwd = tk.StringVar()
        self.entry_pwd = ttk.Entry(frame, textvariable=self.var_pwd, show="•", width=36)
        self.entry_pwd.grid(row=2, column=1, sticky="we", pady=4)

        self.var_show = tk.BooleanVar()
        ttk.Checkbutton(frame, text="Mostrar password", variable=self.var_show,
                        command=lambda: self.entry_pwd.config(show="" if self.var_show.get() else "•")
                        ).grid(row=3, column=1, sticky="w")

        ttk.Label(frame, text="Dominio / equipo:").grid(row=4, column=0, sticky="w", pady=4)
        self.var_dom = tk.StringVar(value=cur_domain)
        ttk.Entry(frame, textvariable=self.var_dom, width=36).grid(row=4, column=1, sticky="we", pady=4)
        ttk.Label(frame, text="(default: nombre del equipo. Para cuenta local dejá el equipo)",
                  foreground="#64748b", font=("Segoe UI", 8)).grid(row=5, column=1, sticky="w")

        warn = ttk.Label(frame,
            text="\n⚠ El password queda en el registro en TEXTO PLANO\n"
                 "    (HKLM\\…\\Winlogon\\DefaultPassword).\n"
                 "⚠ Requiere ejecutar la app como Administrador.",
            foreground="#c2410c", font=("Segoe UI", 9))
        warn.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 4))

        btnrow = ttk.Frame(frame)
        btnrow.grid(row=7, column=0, columnspan=2, sticky="we", pady=(8, 0))
        ttk.Button(btnrow, text="Cancelar", command=self.win.destroy).pack(side="right")
        ttk.Button(btnrow, text="Aplicar", command=self._apply).pack(side="right", padx=(0, 6))

        frame.columnconfigure(1, weight=1)

    def _apply(self):
        user = self.var_user.get().strip()
        pwd = self.var_pwd.get()
        dom = self.var_dom.get().strip()
        if not user:
            messagebox.showerror("Error", "Usuario obligatorio.", parent=self.win)
            return
        if not pwd:
            if not messagebox.askyesno("Sin password",
                "El password está vacío. ¿Continuar?", parent=self.win):
                return
        result = core.windows_set_autologon(user, pwd, domain=dom, log=self.log)
        if result["ok"]:
            messagebox.showinfo("Auto-logon",
                f"Auto-logon configurado para '{user}'.\n\n"
                "Reiniciá el server para probarlo.", parent=self.win)
            self.win.destroy()
        else:
            messagebox.showerror("Auto-logon", result["error"], parent=self.win)


class NetworkDrivesDialog:
    """Modal: editar las unidades de red que se mapean al iniciar la app."""

    def __init__(self, parent, cfg, log, on_save):
        self.cfg = cfg
        self.log = log
        self.on_save = on_save
        self.rows = []  # cada item: dict con StringVars + Frame

        self.win = tk.Toplevel(parent)
        self.win.title("Unidades de red — net use al iniciar")
        self.win.geometry("840x420")
        self.win.configure(bg=BODY)
        self.win.minsize(720, 320)
        self.win.transient(parent)
        self.win.grab_set()

        ttk.Label(self.win,
            text="Cada fila se mapea con: net use <LETRA>: <UNC> <PASSWORD> /user:<USR> /persistent:yes",
            foreground="#374151", padding=(10, 8)).pack(anchor="w")

        # Header
        hdr = ttk.Frame(self.win, padding=(10, 0, 10, 4))
        hdr.pack(fill="x")
        for txt, w in [("Letra", 8), ("UNC", 32), ("Usuario", 14), ("Password", 14), ("Persist.", 9), ("", 8)]:
            ttk.Label(hdr, text=txt, font=("Segoe UI", 9, "bold"), width=w, anchor="w").pack(side="left", padx=(0, 4))

        # Scrollable rows area
        outer = ttk.Frame(self.win)
        outer.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        canvas = tk.Canvas(outer, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self.list_frame = ttk.Frame(canvas)
        self.list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # Cargar drives existentes
        for d in cfg.get("network_drives", []):
            self._add_row(d)
        if not cfg.get("network_drives"):
            self._add_row()

        # Botones
        btnrow = ttk.Frame(self.win, padding=10)
        btnrow.pack(fill="x")
        ttk.Button(btnrow, text="+ Agregar", command=lambda: self._add_row()).pack(side="left")
        ttk.Button(btnrow, text="Cancelar", command=self.win.destroy).pack(side="right")
        ttk.Button(btnrow, text="Guardar y aplicar", command=self._save).pack(side="right", padx=(0, 6))

    def _add_row(self, drive=None):
        drive = drive or {}
        f = ttk.Frame(self.list_frame)
        f.pack(fill="x", pady=2)
        v_letter = tk.StringVar(value=drive.get("letter", ""))
        v_unc = tk.StringVar(value=drive.get("unc", ""))
        v_user = tk.StringVar(value=drive.get("user", ""))
        v_pwd = tk.StringVar(value=drive.get("password", ""))
        v_pers = tk.BooleanVar(value=drive.get("persistent", True))

        ttk.Entry(f, textvariable=v_letter, width=8).pack(side="left", padx=(0, 4))
        ttk.Entry(f, textvariable=v_unc, width=32).pack(side="left", padx=(0, 4))
        ttk.Entry(f, textvariable=v_user, width=14).pack(side="left", padx=(0, 4))
        ttk.Entry(f, textvariable=v_pwd, width=14, show="•").pack(side="left", padx=(0, 4))
        ttk.Checkbutton(f, variable=v_pers, width=4).pack(side="left", padx=(20, 4))
        row_data = {"letter": v_letter, "unc": v_unc, "user": v_user, "pwd": v_pwd,
                    "persist": v_pers, "frame": f}
        ttk.Button(f, text="✕", width=3,
                   command=lambda r=row_data: self._remove_row(r)).pack(side="left")
        self.rows.append(row_data)

    def _remove_row(self, row):
        try:
            row["frame"].destroy()
            self.rows.remove(row)
        except Exception:
            pass

    def _save(self):
        result = []
        for r in self.rows:
            letter = r["letter"].get().strip().rstrip(":").upper()
            unc = r["unc"].get().strip()
            if not letter or not unc:
                continue
            result.append({
                "letter": letter,
                "unc": unc,
                "user": r["user"].get().strip(),
                "password": r["pwd"].get(),
                "persistent": bool(r["persist"].get()),
            })
        self.on_save(result)
        self.win.destroy()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--hidden", action="store_true", help="Iniciar minimizado en la bandeja")
    args = p.parse_args()

    cfg = core.load_config()
    start_hidden = args.hidden or cfg.get("start_hidden", False)
    BackupApp(start_hidden=start_hidden).run()


if __name__ == "__main__":
    main()
