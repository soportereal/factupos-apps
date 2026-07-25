#!/bin/bash
# Construye el paquete .deb de factupos-apps (arch: all, Python+GTK).
# Uso:  ./installer/build-deb.sh [VERSION] [DIR_SALIDA]
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"        # carpeta appstore/
PKG="factupos-apps"
PYVER="$(grep -m1 '^VERSION = ' "$HERE/$PKG.py" | sed 's/[^0-9.]//g')"
VERSION="${1:-${PYVER:-1.0.0}}"
OUT="${2:-$HERE/installer/Output}"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

install -d "$STAGE/usr/lib/$PKG"
install -m644 "$HERE/$PKG.py" "$STAGE/usr/lib/$PKG/$PKG.py"

install -d "$STAGE/usr/bin"
cat > "$STAGE/usr/bin/$PKG" <<'LAUNCH'
#!/bin/sh
exec python3 /usr/lib/factupos-apps/factupos-apps.py "$@"
LAUNCH
chmod 755 "$STAGE/usr/bin/$PKG"

install -d "$STAGE/usr/share/applications"
install -m644 "$HERE/$PKG.desktop" "$STAGE/usr/share/applications/$PKG.desktop"

# Regla polkit: apt-get via pkexec SIN contrasena (instalar con un clic en POS)
install -d "$STAGE/etc/polkit-1/rules.d"
install -m644 "$HERE/installer/debian/50-factupos-apps.rules" \
    "$STAGE/etc/polkit-1/rules.d/50-factupos-apps.rules"

install -d "$STAGE/DEBIAN"
sed "s/__VERSION__/$VERSION/" "$HERE/installer/debian/control" > "$STAGE/DEBIAN/control"

chmod 755 "$STAGE"
mkdir -p "$OUT"
DEB="$OUT/${PKG}_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB" >/dev/null
echo "OK -> $DEB"
