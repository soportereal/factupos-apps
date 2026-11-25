# -*- coding: utf-8 -*-
"""
Aplicaciones FactuPOS (Windows) — una aplicación para descargar e instalar las demás.
Idea del dueño, 25-nov-2026 (sale del caso #3907).

Por qué existe: Google marcó como peligrosa la carpeta pública de instaladores y el
navegador los frena. Esta app NO es un navegador: baja directo del servidor, así que
ni Chrome ni Google se meten. Y lo que baja una app no lleva la marca «descargado de
internet», por eso Windows tampoco frena cada instalador.

- Lista de apps: https://soportereal.com/descarga/catalogo.php (la versión de cada una
  sale de su propio *_version.json, la misma que usa su auto-actualización).
- Versión instalada: «Agregar o quitar programas» del registro (vistas de 64 y 32 bits).
- Instala con ShellExecuteEx: así Windows pide permiso de administrador cuando el
  instalador lo necesita (con subprocess daría error 740).
- Se actualiza sola: si el catálogo trae una versión mayor de esta app, la instala y se reabre.

Python 3.8 (corre en Windows 7+) · tkinter · se compila en 32 bits (corre en 32 y 64).
"""
import ctypes
import json
import os
import re
import sys
import tempfile
import threading
import urllib.request
import zipfile
from ctypes import wintypes

import tkinter as tk
from tkinter import ttk, messagebox

VERSION = "1.0.2"
CATALOGO_URL = "https://soportereal.com/descarga/catalogo.php"
AGENTE = "FactuPOS-Aplicaciones/" + VERSION   # sin «Mozilla»: el servidor deja pasar a las apps
CARPETA = os.path.join(tempfile.gettempdir(), "FactuPOS-Aplicaciones")

AZUL = "#0b2447"
AZUL2 = "#19376d"
CLARO = "#f1f5f9"
VERDE = "#15803d"
GRIS = "#64748b"


# ─────────────── Versiones ───────────────

def version_tupla(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def es_mayor(nueva, actual):
    return bool(nueva) and version_tupla(nueva) > version_tupla(actual)


def programas_instalados():
    """[(nombre, versión, comando para desinstalar)] de «Agregar o quitar programas» (máquina y usuario, 64 y 32 bits)."""
    import winreg
    salida = []
    ruta = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for raiz in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for vista in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                clave = winreg.OpenKey(raiz, ruta, 0, winreg.KEY_READ | vista)
            except OSError:
                continue
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(clave, i)
                except OSError:
                    break
                i += 1
                try:
                    k = winreg.OpenKey(clave, sub, 0, winreg.KEY_READ | vista)
                    nombre = winreg.QueryValueEx(k, "DisplayName")[0]
                    try:
                        ver = winreg.QueryValueEx(k, "DisplayVersion")[0]
                    except OSError:
                        ver = ""
                    try:
                        desinst = winreg.QueryValueEx(k, "UninstallString")[0]
                    except OSError:
                        desinst = ""
                    salida.append((str(nombre), str(ver), str(desinst)))
                except OSError:
                    pass
    return salida


def buscar_instalada(app, instalados):
    """(versión o '?', comando para desinstalar) si está instalada; ('', '') si no.
    Compara el nombre EXACTO (sin mayúsculas): «FactuPOS Print Bridge» contiene «FactuPOS Print», y con
    «Desinstalar» confundirlos quitaría el programa equivocado."""
    for texto in app.get("detectar") or []:
        t = texto.strip().lower()
        for nombre, ver, desinst in instalados:
            if nombre.strip().lower() == t:
                return (ver or "?"), desinst
    return "", ""


def partir_comando(cmd):
    """'"C:\\x\\unins000.exe" /X' -> ('C:\\x\\unins000.exe', '/X') · 'MsiExec.exe /X{..}' -> ('MsiExec.exe', '/X{..}')."""
    cmd = (cmd or "").strip()
    if cmd.startswith('"'):
        fin = cmd.find('"', 1)
        if fin > 0:
            return cmd[1:fin], cmd[fin + 1:].strip()
    m = re.match(r"(?i)^(.+?\.exe)\b(.*)$", cmd)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return cmd, ""


def windows_64():
    return os.environ.get("PROCESSOR_ARCHITEW6432", os.environ.get("PROCESSOR_ARCHITECTURE", "")).upper().endswith("64")


# ─────────────── Ejecutar con permiso de Windows ───────────────

class SHELLEXECUTEINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
    ]


def ejecutar(archivo, parametros="", esperar=True):
    """Abre un archivo como si se le diera doble clic (Windows pide permiso si hace falta).
    Devuelve el código de salida (o 0 si no espera). Lanza OSError si el usuario cancela."""
    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    info = SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "open"
    info.lpFile = archivo
    info.lpParameters = parametros or None
    info.lpDirectory = os.path.dirname(archivo) or None
    info.nShow = 1
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        raise ctypes.WinError()
    codigo = 0
    if esperar and info.hProcess:
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        c = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(c))
        codigo = c.value
    if info.hProcess:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return codigo


def instalar_archivo(app, ruta):
    """Instala/abre según el tipo. Devuelve un texto para el usuario."""
    tipo = app.get("tipo")
    if tipo == "inno":
        # /SILENT: muestra el avance pero no hace preguntas; las opciones quedan las de siempre.
        c = ejecutar(ruta, "/SILENT /SUPPRESSMSGBOXES /NORESTART")
        return "Listo" if c == 0 else "El instalador terminó con código %d" % c
    if tipo == "msi":
        sysdir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "msiexec.exe")
        c = ejecutar(sysdir, '/i "%s" /passive /norestart' % ruta)
        return "Listo" if c in (0, 3010) else "El instalador terminó con código %d" % c
    if tipo == "zip":
        destino = os.path.join(os.path.expanduser("~"), "Desktop", os.path.splitext(os.path.basename(ruta))[0])
        os.makedirs(destino, exist_ok=True)
        with zipfile.ZipFile(ruta) as z:
            z.extractall(destino)
        os.startfile(destino)
        return "Se descomprimió en el Escritorio"
    # exe (instalador propio), reg (pide confirmar), fuente (abre el visor con «Instalar»)
    ejecutar(ruta, "", esperar=False)
    return "Abierto: seguí los pasos en pantalla"


# ─────────────── Descargas ───────────────

def bajar_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def bajar_archivo(url, avance):
    """Baja a la carpeta temporal; avance(fracción) se llama mientras baja."""
    os.makedirs(CARPETA, exist_ok=True)
    nombre = urllib.request.unquote(url.rsplit("/", 1)[-1])
    destino = os.path.join(CARPETA, nombre)
    parcial = destino + ".parcial"
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(req, timeout=30) as r, open(parcial, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        hecho = 0
        while True:
            bloque = r.read(256 * 1024)
            if not bloque:
                break
            f.write(bloque)
            hecho += len(bloque)
            if total:
                avance(hecho / total)
    if total and hecho != total:
        raise IOError("La descarga quedó incompleta (%d de %d bytes)" % (hecho, total))
    if os.path.exists(destino):
        os.remove(destino)
    os.replace(parcial, destino)
    return destino


# ─────────────── Ventana ───────────────

class App:
    def __init__(self, raiz):
        self.raiz = raiz
        self.ocupado = False
        self.apps = []
        raiz.title("Aplicaciones FactuPOS para Windows")
        # 1.0.1: con el zoom de Windows (125-200 %) la ventana fija de 760x600 píxeles salía chica y cortada.
        # Se mide el zoom real (píxeles por pulgada / 96) y la ventana ocupa ~80 % de la pantalla, centrada.
        self.zoom = max(1.0, raiz.winfo_fpixels("1i") / 96.0)
        ancho_p, alto_p = raiz.winfo_screenwidth(), raiz.winfo_screenheight()
        ancho = min(int(900 * self.zoom), int(ancho_p * 0.85))
        alto = min(int(760 * self.zoom), int(alto_p * 0.85))
        raiz.geometry("%dx%d+%d+%d" % (ancho, alto, (ancho_p - ancho) // 2, max(0, (alto_p - alto) // 3)))
        raiz.minsize(min(int(620 * self.zoom), ancho_p), min(int(420 * self.zoom), alto_p))
        raiz.configure(bg=CLARO)

        cab = tk.Frame(raiz, bg=AZUL)
        cab.pack(fill="x")
        tk.Label(cab, text="Aplicaciones FactuPOS para Windows", bg=AZUL, fg="white",
                 font=("Segoe UI", 15, "bold")).pack(side="left", padx=16, pady=12)
        tk.Label(cab, text="v" + VERSION, bg=AZUL, fg="#cbd5e1",
                 font=("Segoe UI", 9)).pack(side="left", pady=(18, 12))
        tk.Button(cab, text="↻ Actualizar lista", command=self.cargar, bg=AZUL2, fg="white",
                  relief="flat", activebackground=AZUL2, activeforeground="white",
                  font=("Segoe UI", 9)).pack(side="right", padx=16)

        cuerpo = tk.Frame(raiz, bg=CLARO)
        cuerpo.pack(fill="both", expand=True)
        self.lienzo = tk.Canvas(cuerpo, bg=CLARO, highlightthickness=0)
        barra = ttk.Scrollbar(cuerpo, orient="vertical", command=self.lienzo.yview)
        self.lista = tk.Frame(self.lienzo, bg=CLARO)
        self.lista.bind("<Configure>", lambda e: self.lienzo.configure(scrollregion=self.lienzo.bbox("all")))
        self.ventana_lista = self.lienzo.create_window((0, 0), window=self.lista, anchor="nw")
        self.lienzo.bind("<Configure>", lambda e: self.lienzo.itemconfigure(self.ventana_lista, width=e.width))
        self.lienzo.configure(yscrollcommand=barra.set)
        self.lienzo.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        raiz.bind_all("<MouseWheel>", lambda e: self.lienzo.yview_scroll(int(-e.delta / 120), "units"))

        pie = tk.Frame(raiz, bg="white")
        pie.pack(fill="x")
        self.estado = tk.Label(pie, text="", bg="white", fg=GRIS, font=("Segoe UI", 9), anchor="w")
        self.estado.pack(fill="x", padx=16, pady=(8, 2))
        self.barra = ttk.Progressbar(pie, mode="determinate", maximum=1.0)
        self.barra.pack(fill="x", padx=16, pady=(0, 10))

        self.cargar()

    # Todo lo que toca la ventana desde otro hilo pasa por acá.
    def en_ventana(self, fn, *args):
        self.raiz.after(0, lambda: fn(*args))

    def poner_estado(self, texto, avance=None):
        self.estado.configure(text=texto)
        if avance is not None:
            self.barra.configure(value=avance)

    def cargar(self):
        if self.ocupado:
            return
        self.poner_estado("Buscando las aplicaciones disponibles…", 0)

        def trabajo():
            try:
                apps = bajar_json(CATALOGO_URL).get("apps", [])
                instalados = programas_instalados()
                for a in apps:
                    a["_instalada"], a["_desinstalar"] = buscar_instalada(a, instalados)
                self.en_ventana(self.mostrar, apps)
            except Exception as e:
                self.en_ventana(self.poner_estado, "No se pudo leer la lista (¿hay internet?): %s" % e, 0)

        threading.Thread(target=trabajo, daemon=True).start()

    def mostrar(self, apps):
        self.apps = apps
        for w in self.lista.winfo_children():
            w.destroy()

        tool = next((a for a in apps if a.get("id") == "tool"), None)
        if tool and es_mayor(tool.get("version"), VERSION):
            self.ofrecer_autoactualizar(tool)

        grupo = None
        for a in apps:
            if a.get("id") == "tool":
                continue
            if a.get("grupo") != grupo:
                grupo = a.get("grupo")
                tk.Label(self.lista, text=(grupo or "").upper(), bg=CLARO, fg=GRIS,
                         font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", padx=18, pady=(12, 2))
            self.fila(a)
        self.poner_estado("%d aplicaciones disponibles" % (len(apps) - (1 if tool else 0)), 0)

    def fila(self, a):
        f = tk.Frame(self.lista, bg="white", highlightbackground="#e2e8f0", highlightthickness=1)
        f.pack(fill="x", padx=14, pady=3)
        izq = tk.Frame(f, bg="white")
        izq.pack(side="left", fill="x", expand=True, padx=12, pady=8)
        tk.Label(izq, text=a.get("nombre", ""), bg="white", fg=AZUL, font=("Segoe UI", 11, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(izq, text=a.get("desc", ""), bg="white", fg=GRIS, font=("Segoe UI", 9),
                 anchor="w", wraplength=int(520 * self.zoom), justify="left").pack(fill="x")

        disp = a.get("version") or ""
        inst = a.get("_instalada") or ""
        partes = ["Disponible: " + (("v" + disp) if disp else a.get("fecha", ""))]
        if inst:
            partes.append("Instalada: " + ("v" + inst if inst != "?" else "sí"))
        tk.Label(izq, text="   ·   ".join(partes), bg="white", fg="#334155", font=("Segoe UI", 8),
                 anchor="w").pack(fill="x", pady=(2, 0))

        if not inst:
            texto, color = "Instalar", AZUL2
        elif disp and inst != "?" and es_mayor(disp, inst):
            texto, color = "Actualizar", "#b45309"
        else:
            texto, color = "Reinstalar", GRIS
        if a.get("tipo") in ("reg", "zip", "fuente", "exe") and not inst:
            texto = "Descargar y abrir"
        b = tk.Button(f, text=texto, bg=color, fg="white", relief="flat", width=16,
                      activebackground=color, activeforeground="white", font=("Segoe UI", 9, "bold"),
                      command=lambda: self.instalar(a))
        b.pack(side="right", padx=12)
        # 1.0.2 (pedido del dueño): si está instalada y Windows sabe cómo quitarla, botón Desinstalar.
        if inst and a.get("_desinstalar"):
            tk.Button(f, text="Desinstalar", bg="white", fg="#b91c1c", relief="flat", width=12,
                      activebackground="#fee2e2", activeforeground="#b91c1c", font=("Segoe UI", 9),
                      highlightbackground="#fecaca", highlightthickness=1,
                      command=lambda: self.desinstalar(a)).pack(side="right", padx=(0, 4))
        if inst and texto == "Reinstalar":
            tk.Label(f, text="✓ Al día", bg="white", fg=VERDE, font=("Segoe UI", 9, "bold")).pack(side="right")

    def url_de(self, a):
        if a.get("url_x86") and not windows_64():
            return a["url_x86"]
        return a["url"]

    def instalar(self, a, al_terminar=None):
        if self.ocupado:
            messagebox.showinfo("Aplicaciones FactuPOS", "Esperá a que termine lo que se está instalando.")
            return
        self.ocupado = True
        nombre = a.get("nombre", "")

        def trabajo():
            try:
                self.en_ventana(self.poner_estado, "Descargando %s…" % nombre, 0)
                ruta = bajar_archivo(self.url_de(a),
                                     lambda x: self.en_ventana(self.poner_estado, "Descargando %s… %d%%" % (nombre, x * 100), x))
                self.en_ventana(self.poner_estado, "Instalando %s… (Windows puede pedir permiso)" % nombre, 1)
                if al_terminar:
                    al_terminar(ruta)
                    return
                msg = instalar_archivo(a, ruta)
                self.en_ventana(self.poner_estado, "%s: %s" % (nombre, msg), 0)
            except OSError as e:
                if getattr(e, "winerror", None) == 1223:   # el usuario dijo «No» al permiso
                    self.en_ventana(self.poner_estado, "Se canceló la instalación de %s" % nombre, 0)
                else:
                    self.en_ventana(self.poner_estado, "No se pudo instalar %s: %s" % (nombre, e), 0)
            except Exception as e:
                self.en_ventana(self.poner_estado, "No se pudo instalar %s: %s" % (nombre, e), 0)
            finally:
                self.ocupado = False
                if not al_terminar:
                    self.en_ventana(self.cargar)

        threading.Thread(target=trabajo, daemon=True).start()

    def desinstalar(self, a):
        if self.ocupado:
            messagebox.showinfo("Aplicaciones FactuPOS", "Esperá a que termine lo que se está haciendo.")
            return
        nombre = a.get("nombre", "")
        if not messagebox.askyesno("Aplicaciones FactuPOS", "¿Desinstalar %s de esta computadora?" % nombre):
            return
        self.ocupado = True

        def trabajo():
            try:
                self.en_ventana(self.poner_estado, "Desinstalando %s… (Windows puede pedir permiso)" % nombre, 0)
                exe, args = partir_comando(a["_desinstalar"])
                c = ejecutar(exe, args)
                if c in (0, 3010):
                    self.en_ventana(self.poner_estado, "%s se desinstaló" % nombre, 0)
                else:
                    self.en_ventana(self.poner_estado, "El desinstalador de %s terminó con código %d" % (nombre, c), 0)
            except OSError as e:
                if getattr(e, "winerror", None) == 1223:
                    self.en_ventana(self.poner_estado, "Se canceló la desinstalación de %s" % nombre, 0)
                else:
                    self.en_ventana(self.poner_estado, "No se pudo desinstalar %s: %s" % (nombre, e), 0)
            finally:
                self.ocupado = False
                self.en_ventana(self.cargar)

        threading.Thread(target=trabajo, daemon=True).start()

    def ofrecer_autoactualizar(self, tool):
        if not messagebox.askyesno("Aplicaciones FactuPOS",
                                   "Hay una versión nueva de esta aplicación (v%s).\n¿Actualizar ahora?" % tool["version"]):
            return

        def instalar_y_salir(ruta):
            # El instalador reabre la app solo (ver [Run] del .iss) y esta se cierra.
            ejecutar(ruta, "/SILENT /SUPPRESSMSGBOXES /NORESTART", esperar=False)
            self.en_ventana(self.raiz.destroy)

        self.instalar(tool, al_terminar=instalar_y_salir)


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # letra nítida en pantallas con zoom
    except Exception:
        pass
    raiz = tk.Tk()
    try:
        raiz.iconbitmap(os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(__file__)), "aplicaciones.ico"))
    except Exception:
        pass
    App(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    main()
