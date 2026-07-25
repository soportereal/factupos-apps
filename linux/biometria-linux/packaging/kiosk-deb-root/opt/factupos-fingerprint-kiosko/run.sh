#!/bin/bash
# Lanzador del kiosko de huella FactuPOS.
# La config (config.json, token.conf, logs) se guarda en ~/.config/factupos-fingerprint-kiosko/
# Auto-update: si el .jar bajado por la app (~/.local/share) es de versión MAYOR que el
# del .deb (/opt), se corre ese. Así la app se actualiza sola sin root.
LOCAL_DIR="$HOME/.local/share/factupos-fingerprint-kiosko"
LOCAL_JAR="$LOCAL_DIR/FactuposKioskoHuella.jar"
OPT_JAR="/opt/factupos-fingerprint-kiosko/FactuposKioskoHuella.jar"
JAR="$OPT_JAR"
if [ -f "$LOCAL_JAR" ] && [ -f "$LOCAL_DIR/version" ]; then
    LV="$(cat "$LOCAL_DIR/version" 2>/dev/null)"
    OV="$(cat /opt/factupos-fingerprint-kiosko/version 2>/dev/null || echo 0.0.0)"
    NEW="$(printf '%s\n%s\n' "$OV" "$LV" | sort -V | tail -1)"
    [ "$NEW" = "$LV" ] && [ "$LV" != "$OV" ] && JAR="$LOCAL_JAR"
fi
exec java -jar "$JAR" "$@"
