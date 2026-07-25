#!/bin/bash
# Parte PRIVILEGIADA del desinstalador (se ejecuta con pkexec/root).
# Quita el kiosko Y el servicio de huella. Se ejecuta desde una COPIA en /tmp
# (la lanza desinstalar.sh) para no autoborrarse a mitad del apt remove.
set +e

echo "[desinstalar] deteniendo servicio y kiosko..."
systemctl stop factupos-fingerprint-servicio.service 2>/dev/null
systemctl disable factupos-fingerprint-servicio.service 2>/dev/null
pkill -f FactuposKioskoHuella.jar 2>/dev/null

echo "[desinstalar] quitando paquetes..."
# Funciona tanto para el .deb COMBINADO (factupos-fingerprint) como para los sueltos.
# Solo intenta quitar los que estén realmente instalados (apt falla si nombra uno ausente).
PKGS=""
for p in factupos-fingerprint factupos-fingerprint-kiosko factupos-fingerprint-servicio; do
    dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" && PKGS="$PKGS $p"
done
RC=0
if [ -n "$PKGS" ]; then
    if command -v apt-get >/dev/null 2>&1; then
        DEBIAN_FRONTEND=noninteractive apt-get remove --purge -y $PKGS
    else
        dpkg --purge $PKGS
    fi
    RC=$?
fi

# limpieza extra por si quedaron restos
rm -f /home/*/Desktop/factupos-fingerprint-kiosko.desktop \
      /home/*/Escritorio/factupos-fingerprint-kiosko.desktop \
      /root/Desktop/factupos-fingerprint-kiosko.desktop 2>/dev/null

echo "[desinstalar] terminado (rc=$RC)"
exit $RC
