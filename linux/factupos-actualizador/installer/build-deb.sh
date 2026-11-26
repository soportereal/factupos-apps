#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"; PKG="factupos-actualizador"
VERSION="${1:-2.1.2}"; OUT="${2:-$HERE/installer/Output}"   # 2.1.2: no reinstala lo quitado desde FactuPOS Apps (#3037)
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
install -d "$STAGE/usr/lib/$PKG"
install -m755 "$HERE/$PKG.sh" "$STAGE/usr/lib/$PKG/$PKG.sh"
install -d "$STAGE/lib/systemd/system"
install -m644 "$HERE/$PKG.service" "$STAGE/lib/systemd/system/$PKG.service"
install -m644 "$HERE/$PKG.timer" "$STAGE/lib/systemd/system/$PKG.timer"
# lista editable de apps base (conffile: apt respeta ediciones del tecnico)
# parches de SEGURIDAD del sistema, sin reiniciar (#2942)
install -m755 "$HERE/seguridad.sh" "$STAGE/usr/lib/$PKG/seguridad.sh"
install -m644 "$HERE/factupos-seguridad.service" "$STAGE/lib/systemd/system/factupos-seguridad.service"
install -d "$STAGE/etc/apt/apt.conf.d"
install -m644 "$HERE/52factupos-seguridad" "$STAGE/etc/apt/apt.conf.d/52factupos-seguridad"
install -d "$STAGE/etc/factupos-actualizador"
install -m644 "$HERE/apps-base.txt" "$STAGE/etc/factupos-actualizador/apps-base.txt"
# el propio deb CONFIGURA el repo APT de FactuPOS (auto-migracion de la
# flota vieja: recibe este deb por el canal de manifests y queda en apt)
install -d "$STAGE/usr/share/keyrings"
install -m644 "$HERE/factupos-repo.gpg" "$STAGE/usr/share/keyrings/factupos-repo.gpg"
install -d "$STAGE/etc/apt/sources.list.d"
install -m644 "$HERE/factupos.list" "$STAGE/etc/apt/sources.list.d/factupos.list"
install -d "$STAGE/DEBIAN"
sed "s/__VERSION__/$VERSION/" "$HERE/installer/debian/control" > "$STAGE/DEBIAN/control"
install -m755 "$HERE/installer/debian/postinst" "$STAGE/DEBIAN/postinst"
echo "/etc/factupos-actualizador/apps-base.txt" > "$STAGE/DEBIAN/conffiles"
chmod 755 "$STAGE"; mkdir -p "$OUT"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT/${PKG}_${VERSION}_all.deb" >/dev/null
echo "OK -> $OUT/${PKG}_${VERSION}_all.deb"
