#!/bin/bash
# Construye el paquete .deb de factupos-recortes (arch: all).
# El motor es flameshot; este paquete aporta lanzador en espanol, el
# comando /usr/bin/factupos-recortes y los atajos de teclado del sistema.
# Uso:  ./installer/build-deb.sh [VERSION] [DIR_SALIDA]
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"        # carpeta recortes/
PKG="factupos-recortes"
VERSION="${1:-1.0.0}"
OUT="${2:-$HERE/installer/Output}"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# Comando: arranca la captura directo (no la bandeja).
install -d "$STAGE/usr/bin"
cat > "$STAGE/usr/bin/$PKG" <<'LAUNCH'
#!/bin/sh
# Herramienta de Recortes de FactuPOS OS.
#   sin argumentos -> recorte de zona con barra de dibujo (lo habitual)
#   --pantalla     -> pantalla completa al portapapeles
case "${1:-}" in
    --pantalla) exec flameshot full -c ;;
    *)          exec flameshot gui "$@" ;;
esac
LAUNCH
chmod 755 "$STAGE/usr/bin/$PKG"

install -d "$STAGE/usr/share/applications"
install -m644 "$HERE/$PKG.desktop" "$STAGE/usr/share/applications/$PKG.desktop"

# Atajos de teclado como default del sistema (Cinnamon).
install -d "$STAGE/etc/dconf/db/local.d"
install -m644 "$HERE/installer/debian/dconf-defaults" \
    "$STAGE/etc/dconf/db/local.d/00-factupos-recortes"

install -d "$STAGE/DEBIAN"
sed "s/__VERSION__/$VERSION/" "$HERE/installer/debian/control" > "$STAGE/DEBIAN/control"
for s in preinst postinst postrm; do
    install -m755 "$HERE/installer/debian/$s" "$STAGE/DEBIAN/$s"
done
echo "/etc/dconf/db/local.d/00-factupos-recortes" > "$STAGE/DEBIAN/conffiles"

chmod 755 "$STAGE"
mkdir -p "$OUT"
DEB="$OUT/${PKG}_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB" >/dev/null
echo "OK -> $DEB"
