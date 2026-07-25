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
# --- Esperar a que exista la bandeja del sistema ANTES de arrancar Java ---
#
# Java pregunta UNA sola vez si hay bandeja y se queda con esa respuesta: en
# OpenJDK 21 (el que corre en campo) SystemTray.isSupported() nunca se vuelve a
# evaluar. El kiosko arranca con la sesion, ANTES que factupos-panel, asi que la
# respuesta era "no hay" para siempre -- medido en la .18: 318 preguntas en media
# hora, todas false, mientras un Java arrancado en ese mismo momento, en la misma
# pantalla, SI la veia. Por eso reintentar DENTRO del programa no sirve de nada:
# lo que hay que hacer es no arrancar hasta que la bandeja este.
#
# Sin bandeja, el kiosko no puede esconderse: se queda ocupando un lugar en la
# barra de tareas todo el dia (cae al modo "minimizar" en vez de "ocultar").
#
# La espera tiene tope: si no aparece, se arranca igual. Un kiosko que no marca
# es mucho peor que un kiosko sin icono en la bandeja.
esperar_bandeja() {
    [ -n "$DISPLAY" ] || return 0            # sin sesion grafica no hay nada que esperar
    command -v python3 >/dev/null 2>&1 || return 0
    python3 - <<'PY' 2>/dev/null
import sys, time
try:
    from Xlib.display import Display
except Exception:
    sys.exit(0)          # sin python3-xlib: no esperamos, arrancamos igual
try:
    d = Display()
    sel = d.intern_atom("_NET_SYSTEM_TRAY_S%d" % d.get_default_screen())
except Exception:
    sys.exit(0)
for _ in range(90):      # hasta 90 s, mirando cada segundo
    try:
        if d.get_selection_owner(sel) is not None:
            sys.exit(0)
    except Exception:
        sys.exit(0)
    time.sleep(1)
PY
}
esperar_bandeja
exec java -jar "$JAR" "$@"
