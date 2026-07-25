#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PKG="factupos-dataequipo"
PYVER="$(grep -m1 '^VERSION = ' "$HERE/$PKG.py" | sed 's/[^0-9.]//g')"
VERSION="${1:-${PYVER:-1.0.0}}"
OUT="${2:-$HERE/installer/Output}"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
install -d "$STAGE/usr/lib/$PKG"
install -m644 "$HERE/$PKG.py" "$STAGE/usr/lib/$PKG/$PKG.py"
install -d "$STAGE/usr/bin"
cat > "$STAGE/usr/bin/$PKG" <<'LAUNCH'
#!/bin/sh
# Corre la copia más nueva: la del sistema o la auto-actualizada del usuario.
SYS="/usr/lib/factupos-dataequipo/factupos-dataequipo.py"
LOCAL="$HOME/.local/share/factupos-dataequipo/factupos-dataequipo.py"
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
install -d "$STAGE/DEBIAN"
sed "s/__VERSION__/$VERSION/" "$HERE/installer/debian/control" > "$STAGE/DEBIAN/control"
chmod 755 "$STAGE"; mkdir -p "$OUT"
DEB="$OUT/${PKG}_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB" >/dev/null
echo "OK -> $DEB"
