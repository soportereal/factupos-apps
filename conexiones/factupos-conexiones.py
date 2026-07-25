#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FactuPOS · Conexiones de Red
-----------------------------
Herramienta propia de FactuPOS OS para ver, en vivo, las conexiones de red
entrantes y salientes del equipo: qué puertos están escuchando (puertas de
entrada abiertas) y qué conexiones activas hay en ese momento, marcando
cuáles fueron iniciadas por otro equipo (entrante) y cuáles por este mismo
equipo (saliente). Lee la salida de `ss` (iproute2); si no está disponible
cae a leer directo de /proc/net/{tcp,tcp6,udp,udp6}.

Uso:
  factupos-conexiones              ventana gráfica
  factupos-conexiones --listado    imprime en consola las conexiones ya
                                    clasificadas (escuchando/entrante/
                                    saliente). Sirve para probar la lógica
                                    de lectura y clasificación sin la GUI.
"""

import os
import re
import sys
import socket
import ipaddress
import subprocess

VERSION = "1.0.0"                                 # fuente única de versión


# ----------------------------------------------------------------------
# Utilidades de direcciones IP:puerto
# ----------------------------------------------------------------------

def parsear_direccion(campo):
    """Separa un campo 'ip:puerto' de `ss` en (ip, puerto).

    Soporta IPv4 ('0.0.0.0:80', '*:80') e IPv6 entre corchetes
    ('[::1]:80', '[fe80::1]:80').
    """
    campo = campo.strip()
    if campo.startswith("["):
        cierre = campo.find("]")
        if cierre == -1:
            return campo, ""
        ip = campo[1:cierre]
        resto = campo[cierre + 1:]
        puerto = resto[1:] if resto.startswith(":") else resto
        return ip, puerto
    ip, sep, puerto = campo.rpartition(":")
    if not sep:
        return campo, ""
    return ip, puerto


def es_loopback(ip):
    """True si la IP es de loopback (127.0.0.0/8 o ::1). Direcciones
    comodín ('0.0.0.0', '::', '*') NO se consideran loopback."""
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def extraer_proceso(campo):
    """De un campo 'users:(("nombre",pid=123,fd=4),...)' devuelve
    'nombre(123), otro(456)'. Cadena vacía si no hay info (sin permiso
    o no aplica)."""
    if not campo:
        return ""
    pares = re.findall(r'"([^"]+)",pid=(\d+)', campo)
    if not pares:
        return ""
    return ", ".join("%s(%s)" % (nombre, pid) for nombre, pid in pares)


# ----------------------------------------------------------------------
# Lectura de conexiones vía `ss` (camino principal)
# ----------------------------------------------------------------------

def _parsear_linea_ss(linea):
    """Convierte una línea de `ss -tunapH` en un dict de fila cruda, o
    None si la línea no tiene el formato esperado."""
    partes = linea.split()
    if len(partes) < 6:
        return None
    proto, estado = partes[0], partes[1]
    local, remoto = partes[4], partes[5]
    proceso_campo = partes[6] if len(partes) > 6 else ""
    ip_local, puerto_local = parsear_direccion(local)
    ip_remoto, puerto_remoto = parsear_direccion(remoto)
    return {
        "proto": proto,
        "estado": estado,
        "ip_local": ip_local,
        "puerto_local": puerto_local,
        "ip_remoto": ip_remoto,
        "puerto_remoto": puerto_remoto,
        "proceso": extraer_proceso(proceso_campo),
    }


def listar_conexiones_ss():
    """Ejecuta `ss -tunapH` y devuelve la lista de filas crudas.

    Devuelve None si el comando `ss` no existe o falla por completo (para
    que el llamador use el fallback de /proc/net/*). Sin privilegios de
    root se ven todas las conexiones del sistema igual, pero la columna
    de proceso solo se resuelve para los sockets propios (comportamiento
    normal de `ss`, no es un bug de esta herramienta).
    """
    try:
        entorno = dict(os.environ, LC_ALL="C")
        resultado = subprocess.run(
            ["ss", "-tunapH"],
            capture_output=True, text=True, timeout=5, env=entorno,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if resultado.returncode != 0 and not resultado.stdout.strip():
        return None
    filas = []
    for linea in resultado.stdout.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        fila = _parsear_linea_ss(linea)
        if fila:
            filas.append(fila)
    return filas


# ----------------------------------------------------------------------
# Fallback: lectura directa de /proc/net/{tcp,tcp6,udp,udp6}
# (se usa solo si el binario `ss` no está disponible en el equipo)
# ----------------------------------------------------------------------

_ESTADOS_PROC_NET = {
    "01": "ESTAB", "02": "SYN-SENT", "03": "SYN-RECV", "04": "FIN-WAIT-1",
    "05": "FIN-WAIT-2", "06": "TIME-WAIT", "07": "CLOSE", "08": "CLOSE-WAIT",
    "09": "LAST-ACK", "0A": "LISTEN", "0B": "CLOSING",
}


def _hex_ip_a_texto(hexip):
    """IP en hex de /proc/net/{tcp,udp} (palabras de 32 bits en orden de
    host) a texto legible. Soporta IPv4 (8 caracteres hex) e IPv6 (32)."""
    hexip = hexip.strip()
    try:
        if len(hexip) == 8:
            crudo = bytes.fromhex(hexip)[::-1]
            return socket.inet_ntoa(crudo)
        if len(hexip) == 32:
            palabras = [hexip[i:i + 8] for i in range(0, 32, 8)]
            crudo = b"".join(bytes.fromhex(w)[::-1] for w in palabras)
            return socket.inet_ntop(socket.AF_INET6, crudo)
    except (ValueError, OSError):
        pass
    return hexip


def _listar_pids():
    try:
        return [int(p) for p in os.listdir("/proc") if p.isdigit()]
    except FileNotFoundError:
        return []


def _mapa_inodo_pid():
    """inode de socket -> pid, escaneando /proc/[pid]/fd. Sin privilegios
    de root solo se pueden leer los fd de los procesos propios (igual
    limitación que tiene `ss` para resolver procesos ajenos)."""
    mapa = {}
    for pid in _listar_pids():
        ruta_fd = "/proc/%d/fd" % pid
        try:
            entradas = os.listdir(ruta_fd)
        except OSError:
            continue
        for fd in entradas:
            try:
                destino = os.readlink(os.path.join(ruta_fd, fd))
            except OSError:
                continue
            if destino.startswith("socket:["):
                mapa[destino[8:-1]] = pid
    return mapa


def _nombre_proceso(pid):
    try:
        with open("/proc/%d/comm" % pid) as f:
            return f.read().strip()
    except OSError:
        return "?"


def _leer_proc_net(ruta, proto_base, ipv6, mapa_inodo_pid):
    filas = []
    try:
        with open(ruta) as f:
            lineas = f.readlines()[1:]  # saltar encabezado
    except OSError:
        return filas
    for linea in lineas:
        campos = linea.split()
        if len(campos) < 10:
            continue
        local_hex, remoto_hex, estado_hex, inode = (
            campos[1], campos[2], campos[3], campos[9])
        ip_l_hex, puerto_l_hex = local_hex.split(":")
        ip_r_hex, puerto_r_hex = remoto_hex.split(":")
        ip_local = _hex_ip_a_texto(ip_l_hex)
        ip_remoto = _hex_ip_a_texto(ip_r_hex)
        puerto_local = str(int(puerto_l_hex, 16))
        puerto_remoto = str(int(puerto_r_hex, 16))

        if proto_base == "tcp":
            estado = _ESTADOS_PROC_NET.get(estado_hex, estado_hex)
        else:
            # UDP no tiene maquina de estados como TCP: si el remoto es
            # 0.0.0.0:0 (o su equivalente IPv6) el socket solo esta
            # ligado (bound) para recibir -> se trata como "escuchando".
            sin_remoto = puerto_r_hex == "0000" and int(ip_r_hex, 16) == 0
            estado = "UNCONN" if sin_remoto else "ESTAB"
            if sin_remoto:
                puerto_remoto = "*"

        pid = mapa_inodo_pid.get(inode)
        proceso = "%s(%d)" % (_nombre_proceso(pid), pid) if pid else ""

        filas.append({
            "proto": proto_base + ("6" if ipv6 else ""),
            "estado": estado,
            "ip_local": ip_local,
            "puerto_local": puerto_local,
            "ip_remoto": ip_remoto,
            "puerto_remoto": puerto_remoto,
            "proceso": proceso,
        })
    return filas


def listar_conexiones_proc():
    """Fallback sin `ss`: junta tcp/tcp6/udp/udp6 de /proc/net/*."""
    mapa = _mapa_inodo_pid()
    filas = []
    filas += _leer_proc_net("/proc/net/tcp", "tcp", False, mapa)
    filas += _leer_proc_net("/proc/net/tcp6", "tcp", True, mapa)
    filas += _leer_proc_net("/proc/net/udp", "udp", False, mapa)
    filas += _leer_proc_net("/proc/net/udp6", "udp", True, mapa)
    return filas


def listar_conexiones():
    """Lista de filas crudas: intenta `ss` primero, si no existe usa
    /proc/net/* como respaldo."""
    filas = listar_conexiones_ss()
    if filas is not None:
        return filas
    return listar_conexiones_proc()


# ----------------------------------------------------------------------
# Clasificación: escuchando / entrante / saliente
# ----------------------------------------------------------------------

def clasificar_conexiones(filas):
    """Separa las filas crudas en:
      escuchando = puertos en estado de escucha (puertas de entrada)
      activas    = conexiones en curso, marcadas 'entrante' o 'saliente'

    Regla: una fila en estado LISTEN (TCP) o un socket UDP ligado sin
    remoto (puerto_remoto == '*') va a 'escuchando'. Del resto, si el
    puerto LOCAL coincide con alguno en 'escuchando' (mismo proto base
    tcp/udp) es 'entrante' (alguien de afuera se conectó a un servicio
    propio); si no, es 'saliente' (este equipo inició la conexión).

    'origen' siempre es quien inició la conexión: la IP remota si es
    entrante, la IP local si es saliente.
    """
    escuchando = []
    candidatas = []
    for f in filas:
        proto_base = "udp" if f["proto"].startswith("udp") else "tcp"
        es_escucha = (
            f["estado"] == "LISTEN"
            or (proto_base == "udp" and f["puerto_remoto"] == "*")
        )
        if es_escucha:
            escuchando.append({
                "proto": f["proto"],
                "ip_local": f["ip_local"],
                "puerto_local": f["puerto_local"],
                "proceso": f["proceso"] or "-",
                "es_local": es_loopback(f["ip_local"]),
            })
        else:
            candidatas.append(f)

    puertos_escucha = {"tcp": set(), "udp": set()}
    for e in escuchando:
        base = "udp" if e["proto"].startswith("udp") else "tcp"
        puertos_escucha[base].add(e["puerto_local"])

    activas = []
    for f in candidatas:
        proto_base = "udp" if f["proto"].startswith("udp") else "tcp"
        entrante = f["puerto_local"] in puertos_escucha[proto_base]
        if entrante:
            direccion = "entrante"
            ip_origen, puerto_origen = f["ip_remoto"], f["puerto_remoto"]
            ip_destino, puerto_destino = f["ip_local"], f["puerto_local"]
        else:
            direccion = "saliente"
            ip_origen, puerto_origen = f["ip_local"], f["puerto_local"]
            ip_destino, puerto_destino = f["ip_remoto"], f["puerto_remoto"]
        activas.append({
            "direccion": direccion,
            "proto": f["proto"],
            "ip_origen": ip_origen,
            "puerto_origen": puerto_origen,
            "ip_destino": ip_destino,
            "puerto_destino": puerto_destino,
            "estado": f["estado"],
            "proceso": f["proceso"] or "-",
            "es_local": es_loopback(f["ip_local"]) or es_loopback(f["ip_remoto"]),
        })
    return escuchando, activas


def contar(escuchando, activas):
    """(n_escuchando, n_entrantes, n_salientes) para el resumen del header."""
    n_entrantes = sum(1 for a in activas if a["direccion"] == "entrante")
    n_salientes = len(activas) - n_entrantes
    return len(escuchando), n_entrantes, n_salientes


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main_cli(argv):
    if argv[0] == "--listado":
        filas = listar_conexiones()
        escuchando, activas = clasificar_conexiones(filas)
        escuchando.sort(key=lambda e: (
            e["proto"], int(e["puerto_local"]) if e["puerto_local"].isdigit() else 0))
        activas.sort(key=lambda a: (a["direccion"], a["proto"]))
        n_esc, n_ent, n_sal = contar(escuchando, activas)

        print("=== Puertos escuchando (%d) ===" % n_esc)
        for e in escuchando:
            print("%-6s %-22s %-7s %s" % (
                e["proto"], e["ip_local"], e["puerto_local"], e["proceso"]))

        print()
        print("=== Conexiones activas (%d entrantes, %d salientes) ===" % (n_ent, n_sal))
        for a in activas:
            flecha = "ENTRANTE" if a["direccion"] == "entrante" else "SALIENTE"
            print("%-9s %-5s %-22s:%-7s -> %-22s:%-7s %-11s %s" % (
                flecha, a["proto"],
                a["ip_origen"], a["puerto_origen"],
                a["ip_destino"], a["puerto_destino"],
                a["estado"], a["proceso"]))
        return 0
    print(__doc__)
    return 1


# ----------------------------------------------------------------------
# GUI (GTK3, mismo look navy del panel de FactuPOS OS)
# ----------------------------------------------------------------------

CSS = """
.fpc-win { background: #f4f6f9; }
.fpc-header { background: #0e1b33; }
.fpc-header-title { color: #ffffff; font-weight: bold; font-size: 15px; }
.fpc-header-resumen { color: #9fb3d9; font-size: 12px; }
.fpc-text { color: #14233f; }
.fpc-seccion-titulo {
    color: #14233f; font-weight: bold; font-size: 12px;
    background: #e8ecf5; padding: 4px 8px;
}

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
"""

# columnas tabla "escuchando"
EC_PROTO, EC_IP, EC_PUERTO, EC_PROCESO, EC_LOCAL = range(5)
# columnas tabla "activas"
AC_DIRECCION, AC_PROTO, AC_IP_ORIGEN, AC_PUERTO_ORIGEN, \
    AC_IP_DESTINO, AC_PUERTO_DESTINO, AC_ESTADO, AC_PROCESO, AC_LOCAL = range(9)

COLOR_ENTRANTE = "#b8860b"  # ambar
COLOR_SALIENTE = "#2d5aa6"  # azul


def main_gui():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, GLib

    prov = Gtk.CssProvider()
    prov.load_from_data(CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), prov,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    win = Gtk.Window(title="Conexiones de Red")
    win.set_default_size(880, 520)
    hb = Gtk.HeaderBar()
    hb.set_show_close_button(True)
    hb.set_decoration_layout(":close")
    hb.props.title = "Conexiones de Red"
    hb.get_style_context().add_class("fp-titlebar")
    win.set_titlebar(hb)
    win.set_position(Gtk.WindowPosition.CENTER)
    win.get_style_context().add_class("fpc-win")
    win.connect("destroy", Gtk.main_quit)

    vbox_root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    win.add(vbox_root)

    # -- header navy con resumen --
    header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin=10)
    header.get_style_context().add_class("fpc-header")
    titulo = Gtk.Label(label="Conexiones de Red", xalign=0)
    titulo.get_style_context().add_class("fpc-header-title")
    lbl_resumen = Gtk.Label(label="0 escuchando · 0 entrantes · 0 salientes", xalign=0)
    lbl_resumen.get_style_context().add_class("fpc-header-resumen")
    header.pack_start(titulo, False, False, 0)
    header.pack_start(lbl_resumen, False, False, 0)
    vbox_root.pack_start(header, False, False, 0)

    # -- buscador + check de conexiones locales --
    fila_buscar = Gtk.Box(spacing=6, margin=8)
    lbl_buscar = Gtk.Label(label="Buscar:")
    lbl_buscar.get_style_context().add_class("fpc-text")
    buscador = Gtk.SearchEntry()
    buscador.set_placeholder_text("Filtrar por IP, puerto o proceso…")
    check_locales = Gtk.CheckButton(label="Mostrar conexiones locales")
    check_locales.get_style_context().add_class("fpc-text")
    fila_buscar.pack_start(lbl_buscar, False, False, 0)
    fila_buscar.pack_start(buscador, True, True, 0)
    fila_buscar.pack_start(check_locales, False, False, 0)
    vbox_root.pack_start(fila_buscar, False, False, 0)

    # -- cuerpo: dos bloques verticales (escuchando arriba, activas abajo) --
    paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
    paned.set_wide_handle(True)
    vbox_root.pack_start(paned, True, True, 0)

    def agregar_columna(treeview, titulo_col, idx, ancho=None, formateador=None, expand=False):
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

    # ------------------------------------------------------------------
    # bloque a) Puertos escuchando (entrada)
    # ------------------------------------------------------------------
    box_esc = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    paned.pack1(box_esc, True, False)

    lbl_esc = Gtk.Label(label="Puertos escuchando (entrada)", xalign=0)
    lbl_esc.get_style_context().add_class("fpc-seccion-titulo")
    box_esc.pack_start(lbl_esc, False, False, 0)

    store_esc = Gtk.ListStore(str, str, str, str, bool)  # proto, ip, puerto, proceso, es_local
    filtro_esc = store_esc.filter_new()

    def visible_esc(model, it, data):
        if not check_locales.get_active() and model.get_value(it, EC_LOCAL):
            return False
        texto = buscador.get_text().strip().lower()
        if not texto:
            return True
        campos = (model.get_value(it, EC_IP) or "", model.get_value(it, EC_PUERTO) or "",
                  model.get_value(it, EC_PROCESO) or "")
        return any(texto in c.lower() for c in campos)

    filtro_esc.set_visible_func(visible_esc)
    orden_esc = Gtk.TreeModelSort(model=filtro_esc)
    tv_esc = Gtk.TreeView(model=orden_esc)
    tv_esc.set_rules_hint(True)
    agregar_columna(tv_esc, "Proto", EC_PROTO, ancho=70)
    agregar_columna(tv_esc, "IP local", EC_IP, expand=True)
    agregar_columna(tv_esc, "Puerto", EC_PUERTO, ancho=90)
    agregar_columna(tv_esc, "Proceso", EC_PROCESO, ancho=220)

    scroll_esc = Gtk.ScrolledWindow()
    scroll_esc.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll_esc.set_vexpand(True)
    scroll_esc.add(tv_esc)
    box_esc.pack_start(scroll_esc, True, True, 0)

    # ------------------------------------------------------------------
    # bloque b) Conexiones activas
    # ------------------------------------------------------------------
    box_act = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    paned.pack2(box_act, True, False)

    lbl_act = Gtk.Label(label="Conexiones activas", xalign=0)
    lbl_act.get_style_context().add_class("fpc-seccion-titulo")
    box_act.pack_start(lbl_act, False, False, 0)

    # direccion, proto, ip_origen, puerto_origen, ip_destino, puerto_destino, estado, proceso, es_local
    store_act = Gtk.ListStore(str, str, str, str, str, str, str, str, bool)
    filtro_act = store_act.filter_new()

    def visible_act(model, it, data):
        if not check_locales.get_active() and model.get_value(it, AC_LOCAL):
            return False
        texto = buscador.get_text().strip().lower()
        if not texto:
            return True
        campos = (
            model.get_value(it, AC_IP_ORIGEN) or "", model.get_value(it, AC_PUERTO_ORIGEN) or "",
            model.get_value(it, AC_IP_DESTINO) or "", model.get_value(it, AC_PUERTO_DESTINO) or "",
            model.get_value(it, AC_PROCESO) or "",
        )
        return any(texto in c.lower() for c in campos)

    filtro_act.set_visible_func(visible_act)
    orden_act = Gtk.TreeModelSort(model=filtro_act)
    tv_act = Gtk.TreeView(model=orden_act)
    tv_act.set_rules_hint(True)

    def fmt_direccion(column, cell, model, it, data):
        d = model.get_value(it, AC_DIRECCION)
        if d == "entrante":
            cell.set_property("text", "⬇ Entrante")
            cell.set_property("foreground", COLOR_ENTRANTE)
        else:
            cell.set_property("text", "⬆ Saliente")
            cell.set_property("foreground", COLOR_SALIENTE)

    agregar_columna(tv_act, "Dirección", AC_DIRECCION, ancho=100, formateador=fmt_direccion)
    agregar_columna(tv_act, "Proto", AC_PROTO, ancho=60)
    agregar_columna(tv_act, "IP origen", AC_IP_ORIGEN, ancho=130)
    agregar_columna(tv_act, "Puerto origen", AC_PUERTO_ORIGEN, ancho=90)
    agregar_columna(tv_act, "IP destino", AC_IP_DESTINO, ancho=130)
    agregar_columna(tv_act, "Puerto destino", AC_PUERTO_DESTINO, ancho=100)
    agregar_columna(tv_act, "Estado", AC_ESTADO, ancho=100)
    agregar_columna(tv_act, "Proceso", AC_PROCESO, expand=True)

    scroll_act = Gtk.ScrolledWindow()
    scroll_act.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll_act.set_vexpand(True)
    scroll_act.add(tv_act)
    box_act.pack_start(scroll_act, True, True, 0)

    # ------------------------------------------------------------------
    # menu contextual: clic derecho -> Copiar IP
    # ------------------------------------------------------------------
    def copiar_al_portapapeles(texto):
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clip.set_text(texto, -1)
        clip.store()

    def mostrar_menu_copiar(treeview, event, obtener_ip):
        if event.button != 3:
            return False
        resultado = treeview.get_path_at_pos(int(event.x), int(event.y))
        if resultado is None:
            return False
        path, columna, _cx, _cy = resultado
        treeview.get_selection().select_path(path)
        modelo = treeview.get_model()
        it = modelo.get_iter(path)
        ip = obtener_ip(modelo, it, columna)
        if not ip:
            return False
        menu = Gtk.Menu()
        item = Gtk.MenuItem(label="Copiar IP (%s)" % ip)
        item.connect("activate", lambda _w: copiar_al_portapapeles(ip))
        menu.append(item)
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def ip_click_esc(modelo, it, _columna):
        return modelo.get_value(it, EC_IP)

    def ip_click_act(modelo, it, columna):
        titulo_col = columna.get_title() if columna else ""
        if titulo_col == "IP destino":
            return modelo.get_value(it, AC_IP_DESTINO)
        return modelo.get_value(it, AC_IP_ORIGEN)

    tv_esc.connect("button-press-event", lambda w, e: mostrar_menu_copiar(w, e, ip_click_esc))
    tv_act.connect("button-press-event", lambda w, e: mostrar_menu_copiar(w, e, ip_click_act))

    # ------------------------------------------------------------------
    # refresco: actualiza filas EN SITIO (no limpia los store) para no
    # perder la seleccion ni la posicion del scroll
    # ------------------------------------------------------------------
    claves_esc = {}  # (proto, ip, puerto) -> TreeIter
    claves_act = {}  # (proto, ip_o, puerto_o, ip_d, puerto_d) -> TreeIter

    def refrescar():
        adj_esc = scroll_esc.get_vadjustment()
        adj_act = scroll_act.get_vadjustment()
        pos_esc = adj_esc.get_value()
        pos_act = adj_act.get_value()

        filas = listar_conexiones()
        escuchando, activas = clasificar_conexiones(filas)

        vivos_esc = set()
        for e in escuchando:
            clave = (e["proto"], e["ip_local"], e["puerto_local"])
            vivos_esc.add(clave)
            fila = (e["proto"], e["ip_local"], e["puerto_local"], e["proceso"], e["es_local"])
            it = claves_esc.get(clave)
            if it is None:
                claves_esc[clave] = store_esc.append(fila)
            else:
                store_esc.set(it, (0, 1, 2, 3, 4), fila)
        for clave in list(claves_esc.keys()):
            if clave not in vivos_esc:
                store_esc.remove(claves_esc.pop(clave))

        vivos_act = set()
        for a in activas:
            clave = (a["proto"], a["ip_origen"], a["puerto_origen"],
                      a["ip_destino"], a["puerto_destino"])
            vivos_act.add(clave)
            fila = (a["direccion"], a["proto"], a["ip_origen"], a["puerto_origen"],
                     a["ip_destino"], a["puerto_destino"], a["estado"], a["proceso"], a["es_local"])
            it = claves_act.get(clave)
            if it is None:
                claves_act[clave] = store_act.append(fila)
            else:
                store_act.set(it, (0, 1, 2, 3, 4, 5, 6, 7, 8), fila)
        for clave in list(claves_act.keys()):
            if clave not in vivos_act:
                store_act.remove(claves_act.pop(clave))

        n_esc, n_ent, n_sal = contar(escuchando, activas)
        lbl_resumen.set_text("%d escuchando · %d entrantes · %d salientes" % (n_esc, n_ent, n_sal))

        for adj, pos in ((adj_esc, pos_esc), (adj_act, pos_act)):
            nuevo_max = max(0.0, adj.get_upper() - adj.get_page_size())
            adj.set_value(min(pos, nuevo_max))

    def on_timeout():
        refrescar()
        return True  # repetir

    buscador.connect("search-changed", lambda w: (filtro_esc.refilter(), filtro_act.refilter()))
    check_locales.connect("toggled", lambda w: (filtro_esc.refilter(), filtro_act.refilter()))

    refrescar()
    GLib.timeout_add(3000, on_timeout)

    paned.set_position(180)  # ~180px para el bloque de escuchando arriba

    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main_cli(sys.argv[1:]))
    main_gui()
