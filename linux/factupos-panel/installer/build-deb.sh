#!/bin/bash
# Construye el paquete .deb de factupos-panel (arch: all, Python+GTK+Wnck).
# Uso:  ./installer/build-deb.sh [VERSION] [DIR_SALIDA]
#   VERSION     por defecto 1.0.0
#   DIR_SALIDA  por defecto panel/installer/Output
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"        # carpeta panel/
PKG="factupos-panel"
# Versión: argumento, o la del propio script (constante VERSION).
PYVER="$(grep -m1 '^VERSION = ' "$HERE/factupos-panel.py" | sed 's/[^0-9.]//g')"
VERSION="${1:-${PYVER:-1.0.0}}"
OUT="${2:-$HERE/installer/Output}"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# --- arbol de archivos ---
install -d "$STAGE/usr/lib/$PKG"
install -m644 "$HERE/factupos-panel.py" "$STAGE/usr/lib/$PKG/factupos-panel.py"
# Logo FactuPOS (hexagono) para el menu Inicio (acceso Facturacion + rama FactuPOS)
install -m644 "$HERE/factupos.png" "$STAGE/usr/lib/$PKG/factupos.png"
# Logos de mensajeria (menu Mensajeria)
install -m644 "$HERE/telegram.png" "$STAGE/usr/lib/$PKG/telegram.png"
install -m644 "$HERE/whatsapp.png" "$STAGE/usr/lib/$PKG/whatsapp.png"

install -d "$STAGE/usr/bin"
cat > "$STAGE/usr/bin/$PKG" <<'LAUNCH'
#!/bin/sh
# Corre la copia más nueva: la del sistema o la auto-actualizada del usuario.
SYS="/usr/lib/factupos-panel/factupos-panel.py"
LOCAL="$HOME/.local/share/factupos-panel/factupos-panel.py"
ver() { grep -m1 '^VERSION = ' "$1" 2>/dev/null | sed 's/[^0-9.]//g'; }
TARGET="$SYS"
if [ -f "$LOCAL" ]; then
    NEWEST="$(printf '%s\n%s\n' "$(ver "$LOCAL")" "$(ver "$SYS")" | sort -V | tail -1)"
    [ "$NEWEST" = "$(ver "$LOCAL")" ] && [ -n "$(ver "$LOCAL")" ] && TARGET="$LOCAL"
fi
exec python3 "$TARGET" "$@"
LAUNCH
chmod 755 "$STAGE/usr/bin/$PKG"

# Lanzador en el menu de aplicaciones
install -d "$STAGE/usr/share/applications"
install -m644 "$HERE/$PKG.desktop" "$STAGE/usr/share/applications/$PKG.desktop"

# Soporte Remoto FactuPOS (#2942): diadema amarilla (iconos/diadema.py) + lanzador de RustDesk
# con ese icono. Va en /usr/local/share/applications (el sistema lo lee ANTES que /usr/share):
# no se toca el paquete de RustDesk, que sigue actualizandose normal.
for t in 16 22 24 32 48 64 128 256; do
    install -d "$STAGE/usr/share/icons/hicolor/${t}x${t}/apps"
    install -m644 "$HERE/iconos/factupos-soporte-$t.png" \
        "$STAGE/usr/share/icons/hicolor/${t}x${t}/apps/factupos-soporte.png"
done
install -d "$STAGE/usr/local/share/applications"
install -m644 "$HERE/rustdesk.desktop" "$STAGE/usr/local/share/applications/rustdesk.desktop"

# Keepalive: relanza el panel si se cae (un POS no debe quedar sin barra).
install -m755 "$HERE/keepalive.sh" "$STAGE/usr/lib/$PKG/keepalive.sh"

# Autostart: arranca el panel VIA keepalive (auto-reinicio), no directo.
install -d "$STAGE/etc/xdg/autostart"
install -m644 "$HERE/$PKG-autostart.desktop" "$STAGE/etc/xdg/autostart/$PKG.desktop"

# Regla polkit: apagar/reiniciar/suspender SIN contrasena (equipo POS).
# Sin esto el boton Reiniciar no funciona si hay varias sesiones abiertas.
install -d "$STAGE/etc/polkit-1/rules.d"
install -m644 "$HERE/installer/debian/49-factupos-power.rules" \
    "$STAGE/etc/polkit-1/rules.d/49-factupos-power.rules"

# Regla polkit: administrar red SIN contrasena (Debian puro pide auth admin
# para nmcli modify; en Mint/LMDE no hacia falta).
install -m644 "$HERE/installer/debian/48-factupos-network.rules" \
    "$STAGE/etc/polkit-1/rules.d/48-factupos-network.rules"

# Regla polkit: la barra arranca el Actualizador de apps FactuPOS SIN contrasena
# (#2942: la barra pone al dia las demas apps, no solo a si misma).
install -m644 "$HERE/installer/debian/47-factupos-actualizador.rules" \
    "$STAGE/etc/polkit-1/rules.d/47-factupos-actualizador.rules"

# --- metadatos DEBIAN ---
install -d "$STAGE/DEBIAN"
sed "s/__VERSION__/$VERSION/" "$HERE/installer/debian/control" > "$STAGE/DEBIAN/control"
install -m755 "$HERE/installer/debian/postinst" "$STAGE/DEBIAN/postinst"

# --- construir ---
chmod 755 "$STAGE"
mkdir -p "$OUT"
DEB="$OUT/${PKG}_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB" >/dev/null
echo "OK -> $DEB"
