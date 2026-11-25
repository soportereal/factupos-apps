#!/bin/sh
# FactuPOS Apps — lo que la Tienda hace como root (#3037, 20-oct-2026). Lo arranca systemd:
#   factupos-apps-op@instalar-<paquete>.service   instala, o actualiza si ya está
#   factupos-apps-op@quitar-<paquete>.service     desinstala y lo anota en QUITADAS
#   factupos-apps-op@todo.service                 «Instalar y actualizar todo»
# La regla polkit 51 deja que la Tienda los arranque sin clave. Por eso ESTE script es la barrera:
# solo acepta paquetes del repositorio FactuPOS o los navegadores que mantenemos.
#
# QUITADAS: lo que alguien quitó a propósito. El Actualizador y Navegadores NO lo reinstalan
# (antes Chrome y las apps obligatorias volvían solas a las pocas horas). Instalarlo de nuevo
# desde la Tienda lo saca de la lista.
if [ "${1:-}" != "--copia" ]; then
    # al actualizar la Tienda (factupos-apps) apt reemplaza este archivo mientras corre: se corre una copia
    cp -f "$0" "/run/factupos-apps-op.$$.sh" && exec sh "/run/factupos-apps-op.$$.sh" --copia "$@"
fi
shift
trap 'rm -f "$0"' EXIT
export LC_ALL=C DEBIAN_FRONTEND=noninteractive
QUITADAS=/var/lib/factupos-apps/quitadas.txt
NAV=/usr/lib/factupos-navegadores/navegadores.sh
NAVEGADORES="google-chrome-stable brave-browser"
# sin estas la PC se queda sin barra, sin forma de instalar nada o sin recibir versiones nuevas
INTOCABLES="factupos-apps factupos-actualizador factupos-panel"
REPO_LIST=/etc/apt/sources.list.d/factupos.list

log() { echo "factupos-apps: $*"; }
fallo() { log "$*"; exit 1; }
instalado() { dpkg-query -Wf'${Status}' "$1" 2>/dev/null | grep -q "install ok installed"; }
en_lista() { for x in $2; do [ "$x" = "$1" ] && return 0; done; return 1; }

ARG="${1:-}"
if [ "$ARG" = todo ]; then
    systemctl start factupos-actualizador.service || fallo "el Actualizador no terminó bien"
    if [ -x "$NAV" ]; then
        systemctl start factupos-navegadores.service || fallo "Navegadores no terminó bien"
    fi
    exit 0
fi

OP=${ARG%%-*}
PKG=${ARG#*-}
case "$OP" in instalar|quitar) ;; *) fallo "acción desconocida: «$ARG»" ;; esac
echo "$PKG" | grep -qE '^[a-z0-9][a-z0-9.-]+$' || fallo "nombre de paquete inválido: «$PKG»"
if ! en_lista "$PKG" "$NAVEGADORES" && \
   ! awk '/^Package:/{print $2}' /var/lib/apt/lists/*soportereal*_Packages 2>/dev/null | grep -qxF "$PKG"; then
    fallo "$PKG no es del repositorio FactuPOS ni un navegador de los que mantenemos"
fi

if [ "$OP" = quitar ]; then
    en_lista "$PKG" "$INTOCABLES" && fallo "$PKG no se puede quitar desde la Tienda"
    if instalado "$PKG"; then
        apt-get -o DPkg::Lock::Timeout=300 remove -y "$PKG" || fallo "no se pudo quitar $PKG"
    fi
    mkdir -p "$(dirname "$QUITADAS")"
    grep -qxF "$PKG" "$QUITADAS" 2>/dev/null || echo "$PKG" >> "$QUITADAS"
    log "$PKG quitado (no se reinstala solo)"
    exit 0
fi

# instalar (o actualizar): primero se saca de QUITADAS, para que nada lo vuelva a quitar
if [ -f "$QUITADAS" ]; then
    grep -vxF "$PKG" "$QUITADAS" > "$QUITADAS.tmp"; mv -f "$QUITADAS.tmp" "$QUITADAS"
fi
if en_lista "$PKG" "$NAVEGADORES"; then
    # el repositorio y la llave de cada navegador los mantiene la app Navegadores y WhatsApp
    [ -x "$NAV" ] || fallo "falta la app Navegadores y WhatsApp (la instala el Actualizador)"
    sh "$NAV" --instalar "$PKG" || fallo "no se pudo instalar $PKG"
else
    if [ -f "$REPO_LIST" ]; then
        apt-get -o DPkg::Lock::Timeout=300 update -qq -o Dir::Etc::sourcelist="$REPO_LIST" \
            -o Dir::Etc::sourceparts="-" -o APT::Get::List-Cleanup="0" || log "(sin índice nuevo, sigo con el que hay)"
    fi
    apt-get -o DPkg::Lock::Timeout=300 install -y "$PKG" || fallo "no se pudo instalar $PKG"
fi
instalado "$PKG" || fallo "$PKG no quedó instalado"
log "$PKG listo: $(dpkg-query -Wf'${Version}' "$PKG")"
exit 0
