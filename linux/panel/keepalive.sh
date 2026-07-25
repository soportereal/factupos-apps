#!/bin/sh
# FactuPOS Panel keepalive: si el panel se cae, lo relanza (un POS no debe quedar
# sin barra). Backoff anti crash-loop: tras varios cierres rápidos, espera más.
#
# INSTANCIA ÚNICA (flock): se puede llamar desde varios lados a la vez
# (autostart XDG, sesión XFCE, xinitrc) sin que salgan barras duplicadas —
# solo la primera toma el lock y corre; las demás salen enseguida.
LOCK="${XDG_RUNTIME_DIR:-/tmp}/factupos-panel.lock"
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK" 2>/dev/null || exec 9>/tmp/factupos-panel.lock
    flock -n 9 || exit 0   # ya hay un keepalive corriendo -> salir
fi

n=0; t0=$(date +%s)
while true; do
    /usr/bin/factupos-panel --monitor all
    now=$(date +%s); [ $((now - t0)) -gt 30 ] && { n=0; t0=$now; }; n=$((n+1))
    [ "$n" -ge 5 ] && sleep 10 || sleep 2
done
