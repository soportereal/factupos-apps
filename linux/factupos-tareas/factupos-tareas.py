#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FactuPOS · Administrador de Tareas
-----------------------------------
Herramienta propia de FactuPOS OS, al estilo del Administrador de Tareas de
Windows: lista procesos con CPU % y memoria, permite ordenar, filtrar y
finalizar tareas; a la derecha, panel de rendimiento en vivo (Memoria,
Procesador, Discos) con gráficos dibujados a mano con cairo. Lee directo de
/proc, sin dependencias externas (no usa psutil).

Uso:
  factupos-tareas              ventana gráfica
  factupos-tareas --top N      imprime en consola los N procesos con más
                                CPU (por defecto 5). Sirve para probar la
                                lógica de lectura de /proc sin la GUI.
"""

import os
import sys
import time
import math
import signal
import pwd
import subprocess

VERSION = "1.1.4"                                 # fuente única de versión

CLK_TCK = os.sysconf("SC_CLK_TCK") or 100          # jiffies por segundo


# ----------------------------------------------------------------------
# Lógica (sirve igual para CLI, GUI y pruebas por import)
# ----------------------------------------------------------------------

def listar_pids():
    """PIDs vivos según /proc (solo entradas numéricas)."""
    try:
        return [int(p) for p in os.listdir("/proc") if p.isdigit()]
    except FileNotFoundError:
        return []


def leer_proceso_jiffies(pid):
    """Lee /proc/[pid]/stat y devuelve (nombre, utime+stime en jiffies).

    Devuelve None si el proceso ya no existe o el archivo es ilegible
    (puede pasar por condición de carrera: el proceso murió entre el
    listado y la lectura).
    """
    try:
        with open("/proc/%d/stat" % pid, "rb") as f:
            data = f.read().decode(errors="replace")
        # el nombre va entre parentesis y puede tener espacios/parentesis
        # adentro (ej: "(kworker/0:1-events)"), por eso se usa index/rindex
        ini = data.index("(")
        fin = data.rindex(")")
        nombre = data[ini + 1:fin]
        resto = data[fin + 2:].split()
        # a partir de aqui: campo 3 (state) = resto[0], campo 4 (ppid) = resto[1], ...
        # campo 14 (utime) = resto[11], campo 15 (stime) = resto[12]
        utime = int(resto[11])
        stime = int(resto[12])
        return nombre, utime + stime
    except (FileNotFoundError, ProcessLookupError, ValueError, IndexError, OSError):
        return None


def leer_usuario(pid):
    """Usuario dueño del proceso (dueño del directorio /proc/[pid])."""
    try:
        uid = os.stat("/proc/%d" % pid).st_uid
        return pwd.getpwuid(uid).pw_name
    except (FileNotFoundError, KeyError, OSError):
        return "?"


def leer_memoria_mb(pid):
    """Memoria residente (VmRSS) del proceso, en MB."""
    try:
        with open("/proc/%d/status" % pid) as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024.0, 1)
    except (FileNotFoundError, OSError, ValueError, IndexError):
        pass
    return 0.0


def leer_stat_cpu():
    """Totales de CPU del sistema (jiffies) desde /proc/stat.

    Devuelve (idle, total) para poder calcular %CPU global entre dos
    muestras (igual principio que por proceso).
    """
    try:
        with open("/proc/stat") as f:
            linea = f.readline()
        valores = [int(v) for v in linea.split()[1:]]
    except (FileNotFoundError, ValueError, OSError):
        return 0, 0
    if not valores:
        return 0, 0
    # campos: user nice system idle iowait irq softirq steal guest guest_nice
    idle = valores[3] + (valores[4] if len(valores) > 4 else 0)  # idle + iowait
    total = sum(valores)
    return idle, total


def cpu_sistema_percent(prev, curr):
    """%CPU global del sistema entre dos muestras de leer_stat_cpu()."""
    idle_prev, total_prev = prev
    idle_curr, total_curr = curr
    d_total = total_curr - total_prev
    d_idle = idle_curr - idle_prev
    if d_total <= 0:
        return 0.0
    return round(100.0 * (d_total - d_idle) / d_total, 1)


def memoria_sistema():
    """(usada_gb, total_gb) del sistema, según /proc/meminfo."""
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if ":" not in line:
                    continue
                clave, valor = line.split(":", 1)
                partes = valor.strip().split()
                if partes:
                    info[clave] = int(partes[0])  # kB
    except (FileNotFoundError, ValueError, OSError):
        pass
    total_kb = info.get("MemTotal", 0)
    disponible_kb = info.get("MemAvailable", total_kb)
    usada_kb = max(0, total_kb - disponible_kb)
    return usada_kb / 1024.0 / 1024.0, total_kb / 1024.0 / 1024.0


def tomar_muestra_procesos():
    """Instantánea de todos los procesos vivos.

    Devuelve (muestra, tiempo, cpu_stat) donde:
      muestra  = { pid: (nombre, jiffies) }
      tiempo   = time.monotonic() al momento de la muestra
      cpu_stat = leer_stat_cpu() al momento de la muestra
    """
    muestra = {}
    for pid in listar_pids():
        r = leer_proceso_jiffies(pid)
        if r:
            muestra[pid] = r
    return muestra, time.monotonic(), leer_stat_cpu()


def calcular_procesos(muestra_prev, t_prev, muestra_curr, t_curr):
    """Combina dos muestras y arma la lista de procesos con %CPU y memoria.

    El %CPU se calcula igual que herramientas tipo top/ps (sin normalizar
    por cantidad de núcleos): puede superar 100% en procesos multi-hilo.
    Devuelve la lista ordenada por CPU descendente.
    """
    dt = max(t_curr - t_prev, 0.001)
    resultado = []
    for pid, (nombre, jif_curr) in muestra_curr.items():
        _, jif_prev = muestra_prev.get(pid, (nombre, jif_curr))  # nuevo -> delta 0
        d_jif = max(0, jif_curr - jif_prev)
        cpu_pct = round(100.0 * (d_jif / CLK_TCK) / dt, 1)
        resultado.append({
            "pid": pid,
            "nombre": nombre,
            "usuario": leer_usuario(pid),
            "cpu": cpu_pct,
            "memoria_mb": leer_memoria_mb(pid),
        })
    resultado.sort(key=lambda p: p["cpu"], reverse=True)
    return resultado


def procesos_top(n=5, intervalo=0.5):
    """Función de conveniencia para pruebas/CLI: toma dos muestras
    separadas por 'intervalo' segundos y devuelve los N procesos con
    más CPU. Reutiliza la misma lógica que usa la GUI (tomar_muestra_
    procesos + calcular_procesos), solo que aquí duerme entre ambas
    muestras porque no hay bucle de refresco continuo esperando.
    """
    muestra1, t1, _ = tomar_muestra_procesos()
    time.sleep(intervalo)
    muestra2, t2, _ = tomar_muestra_procesos()
    return calcular_procesos(muestra1, t1, muestra2, t2)[:n]


def finalizar_proceso(pid):
    """Intenta terminar un proceso con SIGTERM. Si no hay permiso (proceso
    de otro usuario), reintenta pidiendo autorización con pkexec.

    Devuelve (ok, mensaje_error).
    """
    try:
        os.kill(pid, signal.SIGTERM)
        return True, ""
    except ProcessLookupError:
        return True, ""  # ya no existía, se da por finalizado
    except PermissionError:
        try:
            rc = subprocess.call(["pkexec", "kill", "-TERM", str(pid)])
        except FileNotFoundError:
            return False, "pkexec no está disponible en este equipo"
        if rc == 0:
            return True, ""
        return False, "autorización cancelada o falló"
    except OSError as e:
        return False, str(e)


# ----------------------------------------------------------------------
# Rendimiento del sistema: memoria detallada, CPU por núcleo, discos
# (alimenta el panel de rendimiento de la GUI, estilo Adm. de Tareas Win)
# ----------------------------------------------------------------------

def _leer_meminfo_kb():
    """Dict crudo de /proc/meminfo, valores en KB (sin el sufijo 'kB')."""
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if ":" not in line:
                    continue
                clave, valor = line.split(":", 1)
                partes = valor.strip().split()
                if partes:
                    info[clave] = int(partes[0])
    except (FileNotFoundError, ValueError, OSError):
        pass
    return info


def memoria_sistema_detalle():
    """(total_gb, usada_gb, libre_gb) del sistema, según /proc/meminfo.

    'libre' usa MemAvailable (lo que el kernel considera realmente
    disponible para procesos nuevos), no el MemFree crudo.
    """
    info = _leer_meminfo_kb()
    total_kb = info.get("MemTotal", 0)
    disponible_kb = info.get("MemAvailable", total_kb)
    usada_kb = max(0, total_kb - disponible_kb)
    return (total_kb / 1024.0 / 1024.0,
            usada_kb / 1024.0 / 1024.0,
            disponible_kb / 1024.0 / 1024.0)


def num_nucleos():
    """Cantidad de núcleos lógicos (label de la ficha Procesador)."""
    return os.cpu_count() or 1


def leer_stat_cpu_nucleos():
    """Lista [(idle, total), ...] por núcleo, una tupla por línea 'cpuN'
    de /proc/stat (mismo principio que leer_stat_cpu(), pero por núcleo).
    """
    resultado = []
    try:
        with open("/proc/stat") as f:
            for line in f:
                partes = line.split()
                if not partes:
                    continue
                etiqueta = partes[0]
                if etiqueta == "cpu":
                    continue  # línea total, ya la cubre leer_stat_cpu()
                if not (etiqueta.startswith("cpu") and etiqueta[3:].isdigit()):
                    if resultado:
                        break  # ya pasamos las líneas cpu*, no seguir leyendo
                    continue
                valores = [int(v) for v in partes[1:]]
                if not valores:
                    continue
                idle = valores[3] + (valores[4] if len(valores) > 4 else 0)
                resultado.append((idle, sum(valores)))
    except (FileNotFoundError, ValueError, OSError, IndexError):
        pass
    return resultado


def cpu_nucleos_percent(prev_lista, curr_lista):
    """%CPU por núcleo entre dos muestras de leer_stat_cpu_nucleos()."""
    n = min(len(prev_lista), len(curr_lista))
    return [cpu_sistema_percent(prev_lista[i], curr_lista[i]) for i in range(n)]


_FS_DISCOS_REALES = {
    "ext4", "ext3", "ext2", "xfs", "btrfs", "vfat", "ntfs", "ntfs3",
    "exfat", "f2fs", "reiserfs", "jfs",
}


def listar_discos():
    """Discos reales montados, leídos de /proc/mounts.

    Filtra a dispositivos /dev/* con sistema de archivos "real" (se
    descartan pseudo-fs como proc/sysfs/tmpfs/overlay/squashfs, etc.) y
    deduplica por device (si el mismo device aparece montado dos veces
    se conserva el primer punto de montaje encontrado).
    Devuelve [{device, punto_montaje, fs}, ...].
    """
    vistos = set()
    discos = []
    try:
        with open("/proc/mounts") as f:
            for line in f:
                partes = line.split()
                if len(partes) < 3:
                    continue
                device, punto, fs = partes[0], partes[1], partes[2]
                if not device.startswith("/dev/") or fs not in _FS_DISCOS_REALES:
                    continue
                if device in vistos:
                    continue
                vistos.add(device)
                # /proc/mounts escapa espacios/tabs como \040 \011
                punto = punto.replace("\\040", " ").replace("\\011", "\t")
                discos.append({"device": device, "punto_montaje": punto, "fs": fs})
    except (FileNotFoundError, OSError):
        pass
    return discos


def espacio_disco(punto_montaje):
    """(total_gb, usado_gb, libre_gb) de un punto de montaje vía os.statvfs.

    'libre' = espacio disponible para el usuario (f_bavail, igual que
    'df -h'); 'usado' se calcula contra el libre real f_bfree (incluye
    la reserva de root), igual que la columna "Used" de df.
    """
    try:
        st = os.statvfs(punto_montaje)
        total = st.f_blocks * st.f_frsize
        libre_root = st.f_bfree * st.f_frsize
        libre_usuario = st.f_bavail * st.f_frsize
        usado = max(0, total - libre_root)
        return (total / 1024.0 ** 3, usado / 1024.0 ** 3, libre_usuario / 1024.0 ** 3)
    except OSError:
        return 0.0, 0.0, 0.0


def discos_info():
    """Une listar_discos() + espacio_disco(): lista lista para pintar,
    con % usado ya calculado. Descarta discos con total 0 (montaje raro
    o error de statvfs).
    """
    resultado = []
    for d in listar_discos():
        total_gb, usado_gb, libre_gb = espacio_disco(d["punto_montaje"])
        if total_gb <= 0:
            continue
        resultado.append({
            "device": d["device"],
            "punto_montaje": d["punto_montaje"],
            "fs": d["fs"],
            "total_gb": total_gb,
            "usado_gb": usado_gb,
            "libre_gb": libre_gb,
            "pct_usado": round(100.0 * usado_gb / total_gb, 1),
        })
    return resultado


def agregar_historial(historial, valor, maximo=60):
    """Agrega 'valor' a la lista 'historial' (la muta) y la recorta a
    'maximo' muestras. Usado por los gráficos en vivo de Memoria/CPU
    del panel de rendimiento (~60 muestras = 3 minutos con tick de 3s).
    """
    historial.append(valor)
    if len(historial) > maximo:
        del historial[0]


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main_cli(argv):
    if argv[0] == "--top":
        n = 5
        if len(argv) > 1:
            try:
                n = int(argv[1])
            except ValueError:
                pass
        for p in procesos_top(n):
            print("%-28s PID=%-8d USR=%-12s CPU=%5.1f%%  MEM=%8.1f MB" % (
                p["nombre"][:28], p["pid"], p["usuario"], p["cpu"], p["memoria_mb"]))
        return 0
    print(__doc__)
    return 1


# ----------------------------------------------------------------------
# GUI (GTK3, mismo look claro/navy del panel de FactuPOS OS)
# ----------------------------------------------------------------------

CSS = """
.fpt-win { background: #f4f6f9; }
.fpt-header { background: #0e1b33; }
.fpt-header-title { color: #ffffff; font-weight: bold; font-size: 15px; }
.fpt-header-resumen { color: #9fb3d9; font-size: 12px; }
.fpt-text { color: #14233f; }
.fpt-finalizar {
    background: #c0392b; color: #ffffff; font-weight: bold;
    border-radius: 6px; padding: 6px 18px;
}
.fpt-finalizar:hover { background: #a5301f; }
.fpt-finalizar:disabled { background: #e3b8b3; color: #f6e6e4; }

/* Barra de titulo propia: navy flat, letra blanca, minimalista */
.fp-titlebar {
    background: #0e1b33;
    color: #ffffff;
    border: none;
    box-shadow: none;
    min-height: 38px;
    padding: 0 4px;
}
.fp-titlebar .title { color: #ffffff; font-weight: bold; font-size: 13px; }
.fp-titlebar button {
    background: transparent; color: #ffffff;
    border: none; box-shadow: none; min-width: 26px; min-height: 26px;
}
.fp-titlebar button:hover { background: rgba(255,255,255,0.18); border-radius: 6px; }

/* Panel de rendimiento (columna derecha) */
.fpt-panel-derecho { background: #f4f6f9; }
.fpt-ficha {
    background: #ffffff;
    border: 1px solid #e2e6ee;
    border-radius: 8px;
    padding: 10px;
}
.fpt-ficha-titulo { color: #14233f; font-weight: bold; font-size: 13px; }
.fpt-ficha-clave { color: #5b6b85; font-size: 11px; }
.fpt-ficha-valor { color: #14233f; font-weight: bold; font-size: 11px; }
"""

COL_NOMBRE, COL_PID, COL_USUARIO, COL_CPU, COL_MEM = range(5)


def main_gui():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, GLib, Pango
    import cairo  # constantes de fuente (bold) para el texto de la barra de uso

    prov = Gtk.CssProvider()
    prov.load_from_data(CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), prov,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    win = Gtk.Window(title="Administrador de Tareas")
    # 520 de alto quedaba corto: el panel izquierdo apila Memoria + Procesador +
    # Discos y la lista de procesos, y abajo se cortaba (no se alcanzaba a ver
    # "Finalizar tarea"). Se sube a 760, pero NUNCA mas que la pantalla: en cajas
    # de 1366x768 una ventana fija de 760 dejaria los botones fuera del monitor.
    _alto = 760
    try:
        _mon = Gdk.Display.get_default().get_primary_monitor()
        if _mon is not None:
            _alto = min(_alto, max(520, _mon.get_workarea().height - 80))
    except Exception:
        pass
    win.set_default_size(980, _alto)
    hb = Gtk.HeaderBar()
    hb.set_show_close_button(True)
    hb.set_decoration_layout(":close")
    hb.props.title = "Administrador de Tareas"
    hb.get_style_context().add_class("fp-titlebar")
    win.set_titlebar(hb)
    win.set_position(Gtk.WindowPosition.CENTER)
    win.get_style_context().add_class("fpt-win")
    win.connect("destroy", Gtk.main_quit)

    vbox_root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    win.add(vbox_root)

    # -- header navy con resumen --
    header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin=10)
    header.get_style_context().add_class("fpt-header")
    titulo = Gtk.Label(label="Administrador de Tareas", xalign=0)
    titulo.get_style_context().add_class("fpt-header-title")
    lbl_resumen = Gtk.Label(label="CPU: —  ·  Memoria: —", xalign=0)
    lbl_resumen.get_style_context().add_class("fpt-header-resumen")
    header.pack_start(titulo, False, False, 0)
    header.pack_start(lbl_resumen, False, False, 0)
    vbox_root.pack_start(header, False, False, 0)

    # -- cuerpo: tabla de procesos (izquierda) + panel de rendimiento (derecha) --
    paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
    paned.set_wide_handle(True)
    vbox_root.pack_start(paned, True, True, 0)

    izq_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    paned.pack2(izq_box, True, False)   # procesos a la DERECHA (crece con la ventana)

    # -- buscador --
    fila_buscar = Gtk.Box(spacing=6, margin=8)
    lbl_buscar = Gtk.Label(label="Buscar:")
    lbl_buscar.get_style_context().add_class("fpt-text")
    buscador = Gtk.SearchEntry()
    buscador.set_placeholder_text("Filtrar por nombre de proceso…")
    fila_buscar.pack_start(lbl_buscar, False, False, 0)
    fila_buscar.pack_start(buscador, True, True, 0)
    izq_box.pack_start(fila_buscar, False, False, 0)

    # -- lista de procesos --
    store = Gtk.ListStore(str, int, str, float, float)  # nombre, pid, usuario, cpu, mem
    filtro = store.filter_new()

    def filtro_visible(model, it, data):
        texto = buscador.get_text().strip().lower()
        if not texto:
            return True
        nombre = model.get_value(it, COL_NOMBRE) or ""
        return texto in nombre.lower()

    filtro.set_visible_func(filtro_visible)

    modelo_orden = Gtk.TreeModelSort(model=filtro)
    modelo_orden.set_sort_column_id(COL_CPU, Gtk.SortType.DESCENDING)

    treeview = Gtk.TreeView(model=modelo_orden)
    treeview.set_rules_hint(True)

    def fmt_cpu(column, cell, model, it, data):
        cell.set_property("text", "%.1f" % model.get_value(it, COL_CPU))

    def fmt_mem(column, cell, model, it, data):
        cell.set_property("text", "%.1f" % model.get_value(it, COL_MEM))

    def agregar_columna(titulo_col, idx, ancho=None, formateador=None, expand=False):
        renderer = Gtk.CellRendererText()
        if formateador:
            columna = Gtk.TreeViewColumn(titulo_col, renderer)
            columna.set_cell_data_func(renderer, formateador)
        else:
            columna = Gtk.TreeViewColumn(titulo_col, renderer, text=idx)
        columna.set_resizable(True)
        columna.set_sort_column_id(idx)
        if ancho:
            columna.set_fixed_width(ancho)
        if expand:
            columna.set_expand(True)
        treeview.append_column(columna)
        return columna

    agregar_columna("Nombre", COL_NOMBRE, expand=True)
    agregar_columna("PID", COL_PID, ancho=70)
    agregar_columna("Usuario", COL_USUARIO, ancho=110)
    agregar_columna("CPU %", COL_CPU, ancho=80, formateador=fmt_cpu)
    agregar_columna("Memoria MB", COL_MEM, ancho=100, formateador=fmt_mem)

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll.set_vexpand(True)
    scroll.add(treeview)
    izq_box.pack_start(scroll, True, True, 0)

    # -- footer con boton finalizar --
    footer = Gtk.Box(spacing=8, margin=8)
    footer.set_halign(Gtk.Align.END)
    btn_finalizar = Gtk.Button(label="Finalizar tarea")
    btn_finalizar.get_style_context().add_class("fpt-finalizar")
    btn_finalizar.set_sensitive(False)
    footer.pack_end(btn_finalizar, False, False, 0)
    izq_box.pack_start(footer, False, False, 0)

    # ------------------------------------------------------------------
    # panel de rendimiento (columna derecha, ~270px, estilo Adm. Tareas)
    # ------------------------------------------------------------------
    panel_scroll = Gtk.ScrolledWindow()
    panel_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    panel_scroll.set_size_request(270, -1)
    panel_scroll.get_style_context().add_class("fpt-panel-derecho")
    paned.pack1(panel_scroll, False, False)  # rendimiento a la IZQUIERDA, ancho fijo

    panel_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=10)
    panel_box.get_style_context().add_class("fpt-panel-derecho")
    panel_scroll.add(panel_box)

    def dibujar_historial(area, cr, historial):
        """Grafico de area/linea 0-100% con el historial de muestras."""
        ancho = area.get_allocated_width()
        alto = area.get_allocated_height()
        cr.set_source_rgb(0.933, 0.949, 0.972)  # #eef2f8
        cr.rectangle(0, 0, ancho, alto)
        cr.fill()
        datos = list(historial)
        if len(datos) < 2 or ancho <= 0 or alto <= 0:
            return True
        n = len(datos)
        paso_x = ancho / float(n - 1)
        pts = []
        for i, v in enumerate(datos):
            x = i * paso_x
            y = alto - (min(max(v, 0.0), 100.0) / 100.0) * (alto - 4) - 2
            pts.append((x, y))
        # relleno bajo la linea
        cr.move_to(pts[0][0], alto)
        for x, y in pts:
            cr.line_to(x, y)
        cr.line_to(pts[-1][0], alto)
        cr.close_path()
        cr.set_source_rgba(0.176, 0.353, 0.651, 0.22)  # #2d5aa6 translucido
        cr.fill()
        # linea
        cr.move_to(*pts[0])
        for x, y in pts[1:]:
            cr.line_to(x, y)
        cr.set_source_rgb(0.176, 0.353, 0.651)
        cr.set_line_width(1.6)
        cr.stroke()
        return True

    def dibujar_barras_nucleos(area, cr, porcentajes):
        """Mini-barras verticales, una por nucleo (% de uso)."""
        ancho = area.get_allocated_width()
        alto = area.get_allocated_height()
        cr.set_source_rgb(0.933, 0.949, 0.972)
        cr.rectangle(0, 0, ancho, alto)
        cr.fill()
        n = len(porcentajes)
        if n == 0 or ancho <= 0 or alto <= 0:
            return True
        gap = 2.0
        ancho_barra = max(1.0, (ancho - gap * (n - 1)) / n)
        cr.set_source_rgb(0.176, 0.353, 0.651)
        for i, pct in enumerate(porcentajes):
            x = i * (ancho_barra + gap)
            h = (min(max(pct, 0.0), 100.0) / 100.0) * (alto - 2)
            cr.rectangle(x, alto - h, ancho_barra, h)
        cr.fill()
        return True

    def dibujar_barra_uso(area, cr, pct_usado, texto=None):
        """Barra horizontal apilada, bordes redondeados: porción USADA en
        rojo (#c0392b) y porción LIBRE en verde (#1e7e34), proporcional a
        pct_usado. Si se pasa 'texto' se centra en blanco/negrita sobre la
        barra (lo usa la ficha Memoria); los discos la llaman sin texto
        porque ya muestran el detalle en un label aparte debajo.
        """
        ancho = area.get_allocated_width()
        alto = area.get_allocated_height()
        if ancho <= 0 or alto <= 0:
            return True
        radio = min(alto / 2.0, 8.0)
        cr.new_path()
        cr.arc(ancho - radio, radio, radio, -math.pi / 2, 0)
        cr.arc(ancho - radio, alto - radio, radio, 0, math.pi / 2)
        cr.arc(radio, alto - radio, radio, math.pi / 2, math.pi)
        cr.arc(radio, radio, radio, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.clip()

        pct = min(max(pct_usado, 0.0), 100.0)
        w_usado = (pct / 100.0) * ancho
        cr.set_source_rgb(0.753, 0.224, 0.169)  # #c0392b usado
        cr.rectangle(0, 0, w_usado, alto)
        cr.fill()
        cr.set_source_rgb(0.118, 0.494, 0.204)  # #1e7e34 libre
        cr.rectangle(w_usado, 0, ancho - w_usado, alto)
        cr.fill()
        cr.reset_clip()

        if texto:
            cr.select_font_face(
                "sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(max(9.0, alto * 0.5))
            cr.set_source_rgb(1, 1, 1)
            ext = cr.text_extents(texto)
            tx = (ancho - ext.width) / 2.0 - ext.x_bearing
            ty = (alto - ext.height) / 2.0 - ext.y_bearing
            cr.move_to(tx, ty)
            cr.show_text(texto)
        return True

    def fila_clave_valor(grid, fila, clave):
        """Agrega una fila 'clave ........ valor' a un Gtk.Grid de ficha
        y devuelve el Label del valor (para actualizarlo en refrescos)."""
        lbl_c = Gtk.Label(label=clave, xalign=0)
        lbl_c.get_style_context().add_class("fpt-ficha-clave")
        lbl_v = Gtk.Label(label="—", xalign=1)
        lbl_v.get_style_context().add_class("fpt-ficha-valor")
        lbl_v.set_hexpand(True)
        grid.attach(lbl_c, 0, fila, 1, 1)
        grid.attach(lbl_v, 1, fila, 1, 1)
        return lbl_v

    # ---- ficha Memoria ----
    ficha_mem = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    ficha_mem.get_style_context().add_class("fpt-ficha")
    tit_mem = Gtk.Label(label="Memoria", xalign=0)
    tit_mem.get_style_context().add_class("fpt-ficha-titulo")
    ficha_mem.pack_start(tit_mem, False, False, 0)
    barra_mem = Gtk.DrawingArea()
    barra_mem.set_size_request(240, 22)
    # barra limpia (sin texto adentro); la leyenda va debajo en colores
    barra_mem.connect("draw", lambda a, cr: dibujar_barra_uso(
        a, cr, pct_mem_actual[0]))
    ficha_mem.pack_start(barra_mem, False, False, 0)
    lbl_leyenda_mem = Gtk.Label(xalign=0)
    lbl_leyenda_mem.set_margin_top(2)
    ficha_mem.pack_start(lbl_leyenda_mem, False, False, 0)
    grafico_mem = Gtk.DrawingArea()
    grafico_mem.set_size_request(240, 80)
    grafico_mem.connect("draw", lambda a, cr: dibujar_historial(a, cr, historial_mem))
    ficha_mem.pack_start(grafico_mem, False, False, 0)
    grid_mem = Gtk.Grid(column_spacing=6, row_spacing=2)
    v_mem_total = fila_clave_valor(grid_mem, 0, "Total")
    v_mem_uso = fila_clave_valor(grid_mem, 1, "En uso")
    v_mem_libre = fila_clave_valor(grid_mem, 2, "Libre")
    ficha_mem.pack_start(grid_mem, False, False, 0)
    panel_box.pack_start(ficha_mem, False, False, 0)

    # ---- ficha Procesador ----
    ficha_cpu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    ficha_cpu.get_style_context().add_class("fpt-ficha")
    tit_cpu = Gtk.Label(label="Procesador", xalign=0)
    tit_cpu.get_style_context().add_class("fpt-ficha-titulo")
    ficha_cpu.pack_start(tit_cpu, False, False, 0)
    grafico_cpu = Gtk.DrawingArea()
    grafico_cpu.set_size_request(240, 80)
    grafico_cpu.connect("draw", lambda a, cr: dibujar_historial(a, cr, historial_cpu))
    ficha_cpu.pack_start(grafico_cpu, False, False, 0)
    grid_cpu = Gtk.Grid(column_spacing=6, row_spacing=2)
    v_cpu_nucleos = fila_clave_valor(grid_cpu, 0, "Núcleos")
    v_cpu_uso = fila_clave_valor(grid_cpu, 1, "En uso")
    v_cpu_libre = fila_clave_valor(grid_cpu, 2, "Libre")
    ficha_cpu.pack_start(grid_cpu, False, False, 0)
    lbl_nucleos_tit = Gtk.Label(label="Por núcleo", xalign=0)
    lbl_nucleos_tit.get_style_context().add_class("fpt-ficha-clave")
    ficha_cpu.pack_start(lbl_nucleos_tit, False, False, 0)
    grafico_nucleos = Gtk.DrawingArea()
    grafico_nucleos.set_size_request(240, 32)
    grafico_nucleos.connect("draw", lambda a, cr: dibujar_barras_nucleos(a, cr, pct_nucleos_actual))
    ficha_cpu.pack_start(grafico_nucleos, False, False, 0)
    panel_box.pack_start(ficha_cpu, False, False, 0)
    v_cpu_nucleos.set_text(str(num_nucleos()))

    # ---- ficha Discos ----
    ficha_discos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    ficha_discos.get_style_context().add_class("fpt-ficha")
    tit_discos = Gtk.Label(label="Discos", xalign=0)
    tit_discos.get_style_context().add_class("fpt-ficha-titulo")
    ficha_discos.pack_start(tit_discos, False, False, 0)
    discos_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    ficha_discos.pack_start(discos_container, False, False, 0)
    panel_box.pack_start(ficha_discos, False, False, 0)

    # ------------------------------------------------------------------
    # refresco: actualiza filas EN SITIO (no limpia el store) para no
    # perder la seleccion ni la posicion del scroll
    # ------------------------------------------------------------------
    estado = {
        "muestra": {}, "t": time.monotonic(), "cpu_stat": leer_stat_cpu(),
        "cpu_nucleos": leer_stat_cpu_nucleos(),
    }
    pid_iters = {}  # pid -> TreeIter del store (no del filtro/orden)

    # historiales para los graficos del panel de rendimiento (~60 muestras)
    historial_mem = []
    historial_cpu = []
    pct_nucleos_actual = []  # ultimo %CPU por nucleo (lo lee dibujar_barras_nucleos)
    pct_mem_actual = [0.0]   # ultimo %RAM usado (celda mutable, la lee barra_mem)

    def refrescar():
        adj = scroll.get_vadjustment()
        pos_scroll = adj.get_value()

        muestra_curr, t_curr, cpu_stat_curr = tomar_muestra_procesos()
        procesos = calcular_procesos(estado["muestra"], estado["t"], muestra_curr, t_curr)

        vivos = set()
        for p in procesos:
            vivos.add(p["pid"])
            fila = (p["nombre"], p["pid"], p["usuario"], p["cpu"], p["memoria_mb"])
            it = pid_iters.get(p["pid"])
            if it is None:
                pid_iters[p["pid"]] = store.append(fila)
            else:
                store.set(it, (0, 1, 2, 3, 4), fila)

        for pid in list(pid_iters.keys()):
            if pid not in vivos:
                store.remove(pid_iters.pop(pid))

        cpu_sistema = cpu_sistema_percent(estado["cpu_stat"], cpu_stat_curr)
        cpu_nucleos_curr = leer_stat_cpu_nucleos()
        pct_nucleos = cpu_nucleos_percent(estado["cpu_nucleos"], cpu_nucleos_curr)
        total_gb, usada_gb, libre_gb = memoria_sistema_detalle()
        lbl_resumen.set_text("CPU: %.1f%%  ·  Memoria: %.1f / %.1f GB" % (
            cpu_sistema, usada_gb, total_gb))

        estado["muestra"], estado["t"], estado["cpu_stat"] = muestra_curr, t_curr, cpu_stat_curr
        estado["cpu_nucleos"] = cpu_nucleos_curr

        # -- panel de rendimiento: ficha Memoria y ficha Procesador --
        pct_mem = (usada_gb / total_gb * 100.0) if total_gb > 0 else 0.0
        agregar_historial(historial_mem, pct_mem)
        agregar_historial(historial_cpu, cpu_sistema)
        pct_nucleos_actual[:] = pct_nucleos  # muta en sitio: la conocen los draw callbacks
        pct_mem_actual[0] = pct_mem

        v_mem_total.set_text("%.1f GB" % total_gb)
        v_mem_uso.set_text("%.1f GB" % usada_gb)
        v_mem_libre.set_text("%.1f GB" % libre_gb)
        lbl_leyenda_mem.set_markup(
            '<span foreground="#c0392b" weight="bold" size="small">%.0f%% en uso</span>'
            '<span foreground="#5b6b85" size="small">  ·  </span>'
            '<span foreground="#1e7e34" weight="bold" size="small">%.0f%% libre</span>'
            % (pct_mem, max(0.0, 100.0 - pct_mem)))
        v_cpu_uso.set_text("%.1f%%" % cpu_sistema)
        v_cpu_libre.set_text("%.1f%%" % max(0.0, 100.0 - cpu_sistema))
        barra_mem.queue_draw()
        grafico_mem.queue_draw()
        grafico_cpu.queue_draw()
        grafico_nucleos.queue_draw()

        # restaurar scroll (clamp por si la lista encogio)
        nuevo_max = max(0.0, adj.get_upper() - adj.get_page_size())
        adj.set_value(min(pos_scroll, nuevo_max))

    def refrescar_discos():
        """Ficha Discos: se refresca aparte y mas espaciado (statvfs es
        mas pesado que leer /proc/stat o /proc/meminfo)."""
        for hijo in discos_container.get_children():
            discos_container.remove(hijo)

        discos = discos_info()
        if not discos:
            lbl_vacio = Gtk.Label(label="No se detectaron discos.", xalign=0)
            lbl_vacio.get_style_context().add_class("fpt-ficha-clave")
            discos_container.pack_start(lbl_vacio, False, False, 0)
        else:
            for d in discos:
                fila = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                nombre = d["device"].rsplit("/", 1)[-1]
                lbl_nombre = Gtk.Label(
                    label="%s  (%s)" % (nombre, d["punto_montaje"]), xalign=0)
                lbl_nombre.set_ellipsize(Pango.EllipsizeMode.END)
                lbl_nombre.get_style_context().add_class("fpt-ficha-valor")
                barra = Gtk.DrawingArea()
                barra.set_size_request(240, 12)
                barra.connect("draw", lambda a, cr, pct=d["pct_usado"]: dibujar_barra_uso(a, cr, pct))
                lbl_detalle = Gtk.Label(
                    label="%.1f / %.1f GB usados (%.0f%%) · libre %.1f GB" % (
                        d["usado_gb"], d["total_gb"], d["pct_usado"], d["libre_gb"]),
                    xalign=0)
                lbl_detalle.get_style_context().add_class("fpt-ficha-clave")
                fila.pack_start(lbl_nombre, False, False, 0)
                fila.pack_start(barra, False, False, 0)
                fila.pack_start(lbl_detalle, False, False, 0)
                discos_container.pack_start(fila, False, False, 0)

        discos_container.show_all()

    def on_timeout():
        refrescar()
        return True  # repetir

    def on_timeout_discos():
        refrescar_discos()
        return True  # repetir

    def obtener_seleccion():
        modelo, it = treeview.get_selection().get_selected()
        if it is None:
            return None, None
        return modelo.get_value(it, COL_PID), modelo.get_value(it, COL_NOMBRE)

    def on_seleccion_cambia(_sel):
        pid, _ = obtener_seleccion()
        btn_finalizar.set_sensitive(pid is not None)

    treeview.get_selection().connect("changed", on_seleccion_cambia)
    buscador.connect("search-changed", lambda w: filtro.refilter())

    def on_finalizar(_b):
        pid, nombre = obtener_seleccion()
        if pid is None:
            return
        dialogo = Gtk.MessageDialog(
            transient_for=win, modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text="¿Finalizar la tarea «%s» (PID %d)?" % (nombre, pid))
        dialogo.format_secondary_text(
            "El programa se cerrará sin guardar. Esta acción no se puede deshacer.")
        respuesta = dialogo.run()
        dialogo.destroy()
        if respuesta != Gtk.ResponseType.YES:
            return
        ok, msg = finalizar_proceso(pid)
        if not ok:
            err = Gtk.MessageDialog(
                transient_for=win, modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="No se pudo finalizar la tarea")
            err.format_secondary_text(msg or "Error desconocido")
            err.run()
            err.destroy()
        refrescar()

    btn_finalizar.connect("clicked", on_finalizar)

    refrescar()          # primera pasada (arranca en 0% mientras se toma la 2da muestra)
    refrescar_discos()   # primera pasada de discos (fuera del tick de 3s)
    GLib.timeout_add(3000, on_timeout)
    GLib.timeout_add(15000, on_timeout_discos)

    paned.set_position(280)  # ~280px para el panel de rendimiento a la izquierda

    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main_cli(sys.argv[1:]))
    main_gui()
