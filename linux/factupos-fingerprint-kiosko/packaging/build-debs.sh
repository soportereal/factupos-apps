#!/bin/bash
# Construye los dos .deb de huella FactuPOS con sus nombres publicados:
#   Factupos-FingerPrint-Servicio_<ver>_amd64.deb   (servicio Python + systemd)
#   Factupos-FingerPrint-Kiosko_<ver>_all.deb        (kiosko Java)
# Uso:  bash packaging/build-debs.sh [--publicar]
#   --publicar  copia los .deb al staging web soportereal.com/software/factupos-app/linux
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist"
WEB="/var/www/soportereal.com/software/factupos-app/linux"
mkdir -p "$OUT"

command -v dpkg-deb >/dev/null || { echo "ERROR: falta dpkg-deb"; exit 1; }

# --- versiones desde los control ---
SVER=$(awk -F': ' '/^Version:/{print $2}' "$ROOT/packaging/deb-root/DEBIAN/control")
# La version del kiosko sale de Main.java, que es donde vive de verdad
# (APP_VERSION, lo que muestra la app en pantalla). Antes se leia del control
# del .deb, escrito a mano: el 24-jul-2026 el jar iba en 1.8.6 y el paquete
# seguia diciendo 1.8.5 -> la tienda ofrecia una version y se instalaba otra.
# Ahora el control se GENERA a partir del codigo y no pueden diverger.
KVER=$(grep -m1 -oP '(?<=APP_VERSION = ")[0-9.]+' "$ROOT/kiosk-java/src/com/factupos/kiosk/Main.java")
[ -n "$KVER" ] || { echo "ERROR: no se pudo leer APP_VERSION de Main.java"; exit 1; }
sed -i "s|^Version: .*|Version: $KVER|" "$ROOT/packaging/kiosk-deb-root/DEBIAN/control"
echo "$KVER" > "$ROOT/packaging/kiosk-deb-root/opt/factupos-fingerprint-kiosko/version"

# --- 1) compilar el jar del kiosko y copiarlo al deb-root ---
echo "[build] compilando jar del kiosko..."
bash "$ROOT/kiosk-java/build.sh"
cp -f "$ROOT/kiosk-java/build/FactuposKioskoHuella.jar" \
      "$ROOT/packaging/kiosk-deb-root/opt/factupos-fingerprint-kiosko/FactuposKioskoHuella.jar"
# archivo 'version' = baseline del .deb (lo usa run.sh para decidir si correr el jar del auto-update)
echo "$KVER" > "$ROOT/packaging/kiosk-deb-root/opt/factupos-fingerprint-kiosko/version"

# --- 1b) limpiar artefactos que no deben ir en el .deb ---
find "$ROOT/packaging/deb-root" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$ROOT/packaging/deb-root" -name '*.pyc' -delete 2>/dev/null || true

# --- 2) permisos correctos de los DEBIAN/* ---
chmod 0755 "$ROOT"/packaging/deb-root/DEBIAN/{postinst,prerm,postrm} 2>/dev/null || true
chmod 0755 "$ROOT/packaging/deb-root/opt/factupos-fingerprint-servicio/estado.sh" 2>/dev/null || true
chmod 0755 "$ROOT"/packaging/kiosk-deb-root/DEBIAN/{postinst,postrm} 2>/dev/null || true
chmod 0440 "$ROOT/packaging/kiosk-deb-root/etc/sudoers.d/factupos-fingerprint-kiosko" 2>/dev/null || true
chmod 0755 "$ROOT/packaging/kiosk-deb-root/opt/factupos-fingerprint-kiosko/run.sh" \
           "$ROOT/packaging/kiosk-deb-root/opt/factupos-fingerprint-kiosko/desinstalar.sh" \
           "$ROOT/packaging/kiosk-deb-root/opt/factupos-fingerprint-kiosko/desinstalar-root.sh" \
           "$ROOT/packaging/kiosk-deb-root/usr/bin/factupos-fingerprint-kiosko" 2>/dev/null || true

# --- 3) construir los .deb ---
# NOMBRE FIJO (sin version): el auto-update siempre descarga el mismo nombre.
# La version vive dentro del paquete (control) y en el *_version.json.
SVC_DEB="$OUT/Factupos-FingerPrint-Servicio.deb"
KIO_DEB="$OUT/Factupos-FingerPrint-Kiosko.deb"
echo "[build] empaquetando servicio -> $SVC_DEB"
dpkg-deb --build --root-owner-group "$ROOT/packaging/deb-root" "$SVC_DEB"
echo "[build] empaquetando kiosko   -> $KIO_DEB"
dpkg-deb --build --root-owner-group "$ROOT/packaging/kiosk-deb-root" "$KIO_DEB"

# --- 3b) construir el .deb COMBINADO (servicio + kiosko en UN solo instalador) ---
# La version NO se escribe a mano: sale de lo que el paquete lleva adentro, con el formato
#   <version del kiosko>+svc<version del servicio>     ej: 1.8.3+svc2.5.2
# Asi el numero se mueve solo cuando cambia cualquiera de los dos, y de un vistazo se sabe
# que trae adentro. (Antes estaba quemado en "1.0.0" y no cambiaba nunca -> imposible
# distinguir dos combinados distintos.)
CMB_VER="${KVER}+svc${SVER}"
CMB_DEB="$OUT/Factupos-FingerPrint.deb"
CMB="$OUT/combined-root"
echo "[build] armando combinado -> $CMB_DEB"
rm -rf "$CMB"; mkdir -p "$CMB/DEBIAN"
# payloads de ambos paquetes (todo MENOS el DEBIAN de cada uno)
( cd "$ROOT/packaging/deb-root"       && tar --exclude=./DEBIAN -cf - . ) | ( cd "$CMB" && tar -xf - )
( cd "$ROOT/packaging/kiosk-deb-root" && tar --exclude=./DEBIAN -cf - . ) | ( cd "$CMB" && tar -xf - )
# control: Architecture amd64 (libfprint nativo); REEMPLAZA a los paquetes sueltos
cat > "$CMB/DEBIAN/control" <<CTL
Package: factupos-fingerprint
Version: $CMB_VER
Section: utils
Priority: optional
Architecture: amd64
Depends: python3 (>= 3.10), python3-gi, gir1.2-fprint-2.0, libfprint-2-2, python3-pil, openssl, default-jre | java11-runtime | openjdk-17-jre | openjdk-21-jre
Recommends: curl, zenity, policykit-1 | polkit
Conflicts: factupos-fingerprint-servicio, factupos-fingerprint-kiosko
Replaces: factupos-fingerprint-servicio, factupos-fingerprint-kiosko
Maintainer: FactuPOS Dev <dev@factupos.com>
Description: FactuPOS FingerPrint (servicio $SVER + kiosko $KVER)
 Instalador unico de huella digital FactuPOS para Linux: servicio del lector
 (Python + libfprint, systemd) y kiosko de marcaje (Java/Swing). Se instalan y
 desinstalan JUNTOS. Cada componente se auto-actualiza por su cuenta.
CTL
# postinst = cuerpo del servicio + cuerpo del kiosko (best-effort, sin set -e para
# que un paso que falle no aborte el resto del instalador)
{ echo '#!/bin/bash'
  echo '# ===== SERVICIO ====='; grep -vE '^#!|^set -e$|^exit 0$' "$ROOT/packaging/deb-root/DEBIAN/postinst"
  echo '# ===== KIOSKO ====='; grep -vE '^#!|^set -e$|^exit 0$' "$ROOT/packaging/kiosk-deb-root/DEBIAN/postinst"
  echo 'exit 0'; } > "$CMB/DEBIAN/postinst"
# prerm = parar/deshabilitar el servicio
cp "$ROOT/packaging/deb-root/DEBIAN/prerm" "$CMB/DEBIAN/prerm"
# postrm = limpieza del servicio + del kiosko
{ echo '#!/bin/bash'
  grep -vE '^#!|^set -e$|^exit 0$' "$ROOT/packaging/deb-root/DEBIAN/postrm"
  grep -vE '^#!|^set -e$|^exit 0$' "$ROOT/packaging/kiosk-deb-root/DEBIAN/postrm"
  echo 'exit 0'; } > "$CMB/DEBIAN/postrm"
chmod 0755 "$CMB/DEBIAN/postinst" "$CMB/DEBIAN/prerm" "$CMB/DEBIAN/postrm"
chmod 0440 "$CMB/etc/sudoers.d/factupos-fingerprint-kiosko" 2>/dev/null || true
dpkg-deb --build --root-owner-group "$CMB" "$CMB_DEB"

echo ""
echo "[build] OK:"
ls -la "$SVC_DEB" "$KIO_DEB" "$CMB_DEB"

# --- 4) publicar (opcional) ---
if [ "$1" = "--publicar" ]; then
    echo "[build] publicando en $WEB ..."
    cp -f "$SVC_DEB" "$KIO_DEB" "$CMB_DEB" "$WEB/"
    # crudos que descargan los auto-updates (nombre fijo)
    cp -f "$ROOT/packaging/deb-root/opt/factupos-fingerprint-servicio/fingerprint_service.py" "$WEB/fingerprint_service.py"
    cp -f "$ROOT/kiosk-java/build/FactuposKioskoHuella.jar" "$WEB/FactuposKioskoHuella.jar"
    # manifiestos de versión (auto-generados desde el control)
    # Nombre NUEVO = nombre de la app. Se genera tambien el nombre VIEJO como
    # ALIAS temporal para las instalaciones que aun leen la URL anterior.
    cat > "$WEB/Factupos-FingerPrint-Servicio_version.json" <<JSON
{
  "version": "$SVER",
  "py": "https://soportereal.com/software/factupos-app/linux/fingerprint_service.py",
  "deb": "https://soportereal.com/software/factupos-app/linux/Factupos-FingerPrint-Servicio.deb"
}
JSON
    cp -f "$WEB/Factupos-FingerPrint-Servicio_version.json" "$WEB/factupos-fingerprint-servicio_version.json"
    cat > "$WEB/Factupos-FingerPrint-Kiosko_version.json" <<JSON
{
  "version": "$KVER",
  "jar": "https://soportereal.com/software/factupos-app/linux/FactuposKioskoHuella.jar",
  "deb": "https://soportereal.com/software/factupos-app/linux/Factupos-FingerPrint-Kiosko.deb"
}
JSON
    cp -f "$WEB/Factupos-FingerPrint-Kiosko_version.json" "$WEB/factupos-fingerprint-kiosko_version.json"
    # limpiar .deb viejos (nombres anteriores + cualquier variante versionada)
    rm -f "$WEB/factupos-fingerprint_"*.deb "$WEB/factupos-kiosko-huella_"*.deb \
          "$WEB/Factupos-FingerPrint-Servicio_"*.deb "$WEB/Factupos-FingerPrint-Kiosko_"*.deb 2>/dev/null || true
    echo "[build] publicado (v servicio=$SVER, v kiosko=$KVER). Recorda: bash /var/www/deploy.sh para prod."
fi
