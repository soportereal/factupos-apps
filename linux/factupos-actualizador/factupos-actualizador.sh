#!/bin/sh
# FactuPOS actualizador: mantiene TODAS las apps FactuPOS al dia. Corre como root.
#
# MODO 1 (preferido): repositorio APT propio (https://soportereal.com/apt).
#   Si existe /etc/apt/sources.list.d/factupos.list:
#     - refresca SOLO el indice FactuPOS (no toca los repos de Debian)
#     - ACTUALIZA todo lo del repo que ya este instalado (--only-upgrade)
#     - INSTALA las apps base que falten (lista editable en
#       /etc/factupos-actualizador/apps-base.txt, una por linea, # comenta)
#
# MODO 2 (flota vieja sin repo): manifests versiones.txt de descargas.

REPO_LIST=/etc/apt/sources.list.d/factupos.list

# Al terminar (pase lo que pase): parches de SEGURIDAD del sistema, en otro servicio, sin
# esperar (--no-block) para que FactuPOS Update no se demore (#2942). Nunca reinicia.
al_salir() {
    rm -rf "${TMP:-}"
    systemctl start --no-block factupos-seguridad.service 2>/dev/null || true
}
trap al_salir EXIT
BASE_TXT=/etc/factupos-actualizador/apps-base.txt
QUITADAS=/var/lib/factupos-apps/quitadas.txt   # las anota la Tienda (op.sh) al quitar

# Destraba apt/dpkg antes de trabajar: comenta la fuente cdrom (rompe apt en
# equipos instalados de USB) y termina de configurar paquetes a medias (un
# postinst colgado -ej. VS Code- deja el candado tomado y todo falla).
destrabar() {
    sed -i '/cdrom:/s/^[^#]/#&/' /etc/apt/sources.list 2>/dev/null || true
    DEBIAN_FRONTEND=noninteractive dpkg --configure -a \
        --force-confdef --force-confold >/dev/null 2>&1 || true
}

if [ -f "$REPO_LIST" ]; then
    echo "actualizador: modo repositorio APT"
    destrabar
    apt-get -o DPkg::Lock::Timeout=180 update \
        -o Dir::Etc::sourcelist="$REPO_LIST" \
        -o Dir::Etc::sourceparts="-" \
        -o APT::Get::List-Cleanup="0" -qq || echo "  (update fallo, sigo con indice previo)"

    instalado() { dpkg-query -Wf'${Status}' "$1" 2>/dev/null | grep -q "install ok installed"; }

    # 1) apps base que falten -> instalar
    if [ -f "$BASE_TXT" ]; then
        FALTAN=""
        while read -r p; do
            case "$p" in ""|\#*) continue;; esac
            # quitada a propósito desde FactuPOS Apps (#3037): no se reinstala sola
            grep -qxF "$p" "$QUITADAS" 2>/dev/null && continue
            instalado "$p" || FALTAN="$FALTAN $p"
        done < "$BASE_TXT"
        if [ -n "$FALTAN" ]; then
            echo "actualizador: instalando apps base que faltan:$FALTAN"
            DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=180 install -y $FALTAN
        fi
    fi

    # 2) todo lo del repo FactuPOS ya instalado -> only-upgrade
    LISTA=$(awk '/^Package:/{print $2}' /var/lib/apt/lists/*soportereal*_Packages 2>/dev/null | sort -u)
    ACTUALIZAR=""
    for p in $LISTA; do
        instalado "$p" || continue
        # Soporte Remoto (rustdesk): actualizarlo reinicia su servicio y CORTA la sesión de
        # soporte que esté en curso. Si hay alguien conectado (RustDesk abre su gestor de
        # conexión, «rustdesk --cm»), se deja para la próxima pasada (#2942).
        if [ "$p" = rustdesk ] && pgrep -f "rustdesk --cm" >/dev/null 2>&1; then
            echo "actualizador: hay una sesión de soporte remoto abierta: rustdesk se actualiza la próxima vez"
            continue
        fi
        ACTUALIZAR="$ACTUALIZAR $p"
    done
    if [ -n "$ACTUALIZAR" ]; then
        echo "actualizador: revisando$ACTUALIZAR"
        DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=180 install --only-upgrade -y $ACTUALIZAR
    else
        echo "actualizador: nada del repo FactuPOS instalado aun"
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# MODO 2: metodo clasico por manifests (equipos sin el repo configurado)
# ---------------------------------------------------------------------------
BASES="https://soportereal.com/software/factupos-app/linux https://invefacon.net/software"
TMP=$(mktemp -d)   # lo borra al_salir
BASE=""
for b in $BASES; do
    if curl -fsS --max-time 15 "$b/versiones.txt" -o "$TMP/versiones.txt" 2>/dev/null; then
        BASE="$b"; break
    fi
done
[ -z "$BASE" ] && { echo "actualizador: sin conexion a invefacon"; exit 0; }
echo "actualizador: modo manifests, usando $BASE"
destrabar
python3 - "$TMP/versiones.txt" "$BASE" "$TMP" <<'PY'
import sys, json, subprocess, urllib.request, os
mf, base, tmp = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.load(open(mf))
def cur(pkg):
    return subprocess.run(["dpkg-query","-Wf","${Version}",pkg],capture_output=True,text=True).stdout.strip()
def vt(v):
    try: return tuple(int(x) for x in v.split("."))
    except: return (0,)
for name, info in data.items():
    pkg, ver, deb = info["paquete"], info["version"], info["deb"]
    c = cur(pkg)
    if c and vt(c) >= vt(ver):
        print("  al dia:", pkg, c); continue
    p = os.path.join(tmp, deb)
    try:
        urllib.request.urlretrieve(base+"/"+deb, p)
        subprocess.run(["apt-get","install","-y","--allow-downgrades",p], check=False)
        print("  instalado/actualizado:", pkg, "->", ver)
    except Exception as e:
        print("  error", pkg, e)
PY
