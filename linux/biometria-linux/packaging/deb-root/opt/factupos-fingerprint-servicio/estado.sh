#!/bin/bash
# Muestra (con zenity) si el servicio de huella FactuPOS está ACTIVO y permite
# reiniciarlo/arrancarlo. Lanzado desde el icono "Estado del Servicio de Huella".
SVC="factupos-fingerprint-servicio"
URL="https://127.0.0.1:52181/status"

active=$(systemctl is-active "$SVC" 2>/dev/null)
json=$(curl -sk --max-time 3 "$URL" 2>/dev/null)

# parseo simple sin jq
ver=$(printf '%s' "$json" | sed -n 's/.*"version": *"\([^"]*\)".*/\1/p')
fpok="?"
printf '%s' "$json" | grep -q '"fprint_ok": *true'  && fpok="sí, lector listo"
printf '%s' "$json" | grep -q '"fprint_ok": *false' && fpok="NO — falta libfprint (sudo apt install gir1.2-fprint-2.0 libfprint-2-2)"

if [ "$active" = "active" ] && [ -n "$json" ]; then
    titulo="✅ Servicio ACTIVO"
    cuerpo="✅ El servicio está CORRIENDO y responde.\n\nVersión: ${ver:-?}\nLector (libfprint): ${fpok}\nURL: ${URL}"
    oklabel="Reiniciar servicio"; accion="restart"
elif [ "$active" = "active" ]; then
    titulo="⚠ Activo pero sin responder"
    cuerpo="⚠ El servicio figura activo pero NO responde en el puerto 52181.\nProbá reiniciarlo."
    oklabel="Reiniciar servicio"; accion="restart"
else
    titulo="❌ Servicio DETENIDO"
    cuerpo="❌ El servicio NO está corriendo (estado: ${active:-desconocido}).\n¿Arrancarlo?"
    oklabel="Arrancar servicio"; accion="start"
fi

if command -v zenity >/dev/null 2>&1; then
    if zenity --question --title="Estado · FactuPOS FingerPrint Servicio" --width=420 \
              --ok-label="$oklabel" --cancel-label="Cerrar" --text="$cuerpo"; then
        pkexec systemctl "$accion" "$SVC" \
            && zenity --info --width=360 --title="FactuPOS FingerPrint" --text="Servicio: $accion ejecutado." \
            || zenity --error --width=360 --title="FactuPOS FingerPrint" --text="No se pudo $accion el servicio."
    fi
else
    printf '%b\n' "$titulo\n$cuerpo"
fi
