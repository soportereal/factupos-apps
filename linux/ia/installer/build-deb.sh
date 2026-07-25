#!/bin/bash
# Construye el .deb de Factupos-IA.  Uso: build-deb.sh [version] [dir_salida]
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"        # carpeta ia/
PYVER="$(grep -m1 '^VERSION = ' "$HERE/factupos_ia.py" | sed 's/[^0-9.]//g')"
VERSION="${1:-${PYVER:-1.0.0}}"
OUT="${2:-$HERE/installer/Output}"
PKG="factupos-ia"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# --- App ---
install -d "$STAGE/usr/lib/$PKG"
install -m644 "$HERE/factupos_ia.py" "$STAGE/usr/lib/$PKG/factupos_ia.py"

# --- Lanzador: elige la versión más nueva (sistema vs ~/.local del auto-update) ---
install -d "$STAGE/usr/bin"
cat > "$STAGE/usr/bin/$PKG" <<'LAUNCH'
#!/bin/sh
SYS="/usr/lib/factupos-ia/factupos_ia.py"
LOCAL="$HOME/.local/share/factupos-ia/factupos_ia.py"
ver() { grep -m1 '^VERSION = ' "$1" 2>/dev/null | sed 's/[^0-9.]//g'; }
TARGET="$SYS"
if [ -f "$LOCAL" ]; then
  NEWEST="$(printf '%s\n%s\n' "$(ver "$LOCAL")" "$(ver "$SYS")" | sort -V | tail -1)"
  [ "$NEWEST" = "$(ver "$LOCAL")" ] && [ -n "$(ver "$LOCAL")" ] && TARGET="$LOCAL"
fi
exec python3 "$TARGET" "$@"
LAUNCH
chmod 755 "$STAGE/usr/bin/$PKG"

# --- Lanzador de menú ---
install -d "$STAGE/usr/share/applications"
install -m644 "$HERE/$PKG.desktop" "$STAGE/usr/share/applications/$PKG.desktop"

# --- Metadatos DEBIAN ---
install -d "$STAGE/DEBIAN"
sed "s/__VERSION__/$VERSION/" "$HERE/installer/debian/control" > "$STAGE/DEBIAN/control"
install -m755 "$HERE/installer/debian/postinst" "$STAGE/DEBIAN/postinst"

# --- Construir ---
chmod 755 "$STAGE"
mkdir -p "$OUT"
DEB="$OUT/${PKG}_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB" >/dev/null
echo "OK -> $DEB"
