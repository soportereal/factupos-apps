#!/bin/bash
# Construye el paquete .deb de factupos-printer-inst (arch: all, Python+GTK).
# Uso:  ./installer/build-deb.sh [VERSION] [DIR_SALIDA]
#   VERSION     por defecto la del .py (VERSION = "x.y.z"). #2698: antes era 1.0.0 fijo y el
#               .deb del repo quedaba atrasado respecto del .py del auto-update.
#   DIR_SALIDA  por defecto printer-inst/installer/Output
set -euo pipefail

PYVER="$(grep -m1 '^VERSION = ' "$(cd "$(dirname "$0")/.." && pwd)/factupos-printer-inst.py" | sed 's/[^0-9.]//g')"
VERSION="${1:-${PYVER:-1.0.0}}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"        # carpeta printer-inst/
OUT="${2:-$HERE/installer/Output}"
PKG="factupos-printer-inst"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# --- arbol de archivos ---
install -d "$STAGE/usr/lib/$PKG"
install -m644 "$HERE/factupos-printer-inst.py" "$STAGE/usr/lib/$PKG/factupos-printer-inst.py"
install -m755 "$HERE/helper.py"                "$STAGE/usr/lib/$PKG/helper.py"
# #3420: impresora virtual en un puerto COM (un servicio por COM).
install -m755 "$HERE/vport.py"                 "$STAGE/usr/lib/$PKG/vport.py"
install -d "$STAGE/lib/systemd/system"
install -m644 "$HERE/systemd/factupos-vport@.service" "$STAGE/lib/systemd/system/factupos-vport@.service"
# 1.4.4: driver «FactuPOS térmica» (PPD + filtro de CUPS).
install -d "$STAGE/usr/share/ppd/factupos" "$STAGE/usr/lib/cups/filter"
install -m644 "$HERE/ppd/factupos-termica.ppd"   "$STAGE/usr/share/ppd/factupos/factupos-termica.ppd"
install -m755 "$HERE/filter/rastertofactupos"    "$STAGE/usr/lib/cups/filter/rastertofactupos"

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
install -m755 "$HERE/installer/debian/prerm"    "$STAGE/DEBIAN/prerm"

# --- actualizacion propia del paquete (#2831): el auto-update de la app solo cambia el
#     .py del usuario; helper.py (root) solo se renueva con el .deb. Con este revisor el
#     paquete entero se pone al dia solo, cada hora, como las demas apps (#2698). ---
source "$HERE/../_comun/autoupdate.sh"
agregar_autoupdate "$STAGE" "$PKG"

# --- construir ---
chmod 755 "$STAGE"
mkdir -p "$OUT"
DEB="$OUT/${PKG}_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB" >/dev/null
echo "OK -> $DEB"
