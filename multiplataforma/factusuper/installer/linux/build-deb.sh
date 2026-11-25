#!/bin/bash
# #3957 — Paquete .deb de FactuSuper para FactuPOS OS (Debian 13 / Mint 22), como las demás apps del repo
# https://soportereal.com/apt: la Tienda (FactuPOS Apps) lo instala con un clic y el Actualizador lo pone al día.
# Es OPCIONAL (solo donde hay caja de supermercado): en publicar.py va en OPCIONALES, si no la flota vieja lo instala en todas.
# Uso (lo corre el CI después de `flutter build linux --release`):
#   installer/linux/build-deb.sh <VERSION> <CARPETA_BUNDLE> [DIR_SALIDA]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PKG=factupos-factusuper
VERSION="${1:?falta la versión}"
BUNDLE="${2:?falta la carpeta del bundle}"
OUT="${3:-$HERE/Output}"
[ -x "$BUNDLE/factusuper" ] || { echo "no está $BUNDLE/factusuper"; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
install -d "$STAGE/opt/factusuper" "$STAGE/usr/bin" "$STAGE/usr/share/applications" \
           "$STAGE/usr/share/icons/hicolor/192x192/apps" "$STAGE/DEBIAN"
cp -a "$BUNDLE/." "$STAGE/opt/factusuper/"
chmod 755 "$STAGE/opt/factusuper/factusuper"
ln -s /opt/factusuper/factusuper "$STAGE/usr/bin/factusuper"
install -m644 "$HERE/factupos-factusuper.desktop" "$STAGE/usr/share/applications/factupos-factusuper.desktop"
install -m644 "$HERE/factusuper.png" "$STAGE/usr/share/icons/hicolor/192x192/apps/factusuper.png"

TAM=$(du -sk "$STAGE/opt" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: $PKG
Version: $VERSION
Section: misc
Priority: optional
Architecture: amd64
Installed-Size: $TAM
Depends: libgtk-3-0t64 | libgtk-3-0, libglib2.0-0t64 | libglib2.0-0, libstdc++6
Maintainer: Soporte Real <soporte@soportereal.com>
Homepage: https://soportereal.com
Description: FactuSuper - caja de supermercado de FactuPOS
 La caja FactuSuper como aplicación del equipo: vende, imprime y guarda
 las ventas aunque se vaya el internet, y las envía solas cuando vuelve.
CONTROL
cat > "$STAGE/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q || true
exit 0
POST
chmod 755 "$STAGE/DEBIAN/postinst"
chmod 755 "$STAGE"
mkdir -p "$OUT"
DEB="$OUT/${PKG}_${VERSION}_amd64.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB" >/dev/null
echo "OK -> $DEB"
