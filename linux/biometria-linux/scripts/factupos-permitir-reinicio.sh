#!/bin/bash
# ============================================================================
# FactuPOS — Permitir reiniciar el servicio de huella SIN contraseña
# ============================================================================
# Crea la regla sudoers para que el kiosko reinicie/detenga el servicio
# factupos-fingerprint-servicio sin pedir clave. Detecta solo la ruta real de systemctl.
#
# USO (una vez):   sudo bash factupos-permitir-reinicio.sh
# ============================================================================

if [ "$(id -u)" -ne 0 ]; then
    echo "Tenés que correrlo con sudo:   sudo bash $0"
    exit 1
fi

# Ruta real de systemctl + las dos típicas, todas cubiertas.
SC="$(command -v systemctl 2>/dev/null)"
[ -z "$SC" ] && SC="/usr/bin/systemctl"

F=/etc/sudoers.d/factupos-fingerprint-kiosko
{
  echo "# FactuPOS kiosko — reinicio del servicio de huella sin clave (generado $(date '+%Y-%m-%d %H:%M'))"
  printf 'ALL ALL=(root) NOPASSWD:'
  first=1
  for bin in "$SC" /usr/bin/systemctl /bin/systemctl /usr/sbin/systemctl; do
    for act in restart stop start status; do
      [ $first -eq 1 ] && first=0 || printf ','
      printf ' %s %s factupos-fingerprint-servicio' "$bin" "$act"
    done
  done
  echo ""
} > "$F"

chown root:root "$F"
chmod 0440 "$F"

if ! visudo -cf "$F" >/dev/null 2>&1; then
    echo "✗ ERROR: el sudoers quedó inválido. No se aplicó."
    rm -f "$F"
    exit 1
fi

echo "systemctl detectado en: $SC"
echo "Regla creada en: $F"
echo ""

# Probar como el usuario real (no como root)
U="${SUDO_USER:-$(logname 2>/dev/null)}"
if [ -n "$U" ] && [ "$U" != "root" ]; then
    if sudo -u "$U" sudo -n systemctl restart factupos-fingerprint-servicio 2>/dev/null; then
        echo "==================================================="
        echo "  ✓ LISTO: el usuario '$U' reinicia el servicio SIN CLAVE"
        echo "==================================================="
    else
        echo "==================================================="
        echo "  ✗ AÚN pide clave para el usuario '$U'."
        echo "  Pasale esto a soporte:"
        echo "     cat /etc/sudoers | grep -n includedir"
        echo "     sudo -l -U $U | grep -i fingerprint"
        echo "==================================================="
    fi
else
    echo "Probá como el usuario del kiosko:  sudo -n systemctl restart factupos-fingerprint-servicio"
fi
