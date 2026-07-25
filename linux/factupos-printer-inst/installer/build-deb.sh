#!/bin/bash
# Construye el paquete .deb de factupos-printer-inst (arch: all, Python+GTK).
# Uso:  ./installer/build-deb.sh [VERSION] [DIR_SALIDA]
#   VERSION     por defecto 1.0.0
#   DIR_SALIDA  por defecto printer-inst/installer/Output
set -euo pipefail

VERSION="${1:-1.0.0}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"        # carpeta printer-inst/
OUT="${2:-$HERE/installer/Output}"
PKG="factupos-printer-inst"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# --- arbol de archivos ---
install -d "$STAGE/usr/lib/$PKG"
install -m644 "$HERE/factupos-printer-inst.py" "$STAGE/usr/lib/$PKG/factupos-printer-inst.py"
install -m755 "$HERE/helper.py"                "$STAGE/usr/lib/$PKG/helper.py"

install -d "$STAGE/usr/bin"
cat > "$STAGE/usr/bin/$PKG" <<'LAUNCH'
#!/bin/sh
# Corre la copia más nueva: la del sistema o la auto-actualizada del usuario.
SYS="/usr/lib/factupos-printer-inst/factupos-printer-inst.py"
LOCAL="$HOME/.local/share/factupos-printer-inst/factupos-printer-inst.py"
ver() { grep -m1 '^VERSION = ' "$1" 2>/dev/null | sed 's/[^0-9.]//g'; }
TARGET="$SYS"
if [ -f "$LOCAL" ]; then
    NEWEST="$(printf '%s\n%s\n' "$(ver "$LOCAL")" "$(ver "$SYS")" | sort -V | tail -1)"
    [ "$NEWEST" = "$(ver "$LOCAL")" ] && [ -n "$(ver "$LOCAL")" ] && TARGET="$LOCAL"
fi
exec python3 "$TARGET" "$@"
LAUNCH
chmod 755 "$STAGE/usr/bin/$PKG"

install -d "$STAGE/usr/share/applications"
install -m644 "$HERE/$PKG.desktop" "$STAGE/usr/share/applications/$PKG.desktop"

install -d "$STAGE/usr/share/polkit-1/rules.d"
install -m644 "$HERE/polkit/49-$PKG.rules" "$STAGE/usr/share/polkit-1/rules.d/49-$PKG.rules"

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
