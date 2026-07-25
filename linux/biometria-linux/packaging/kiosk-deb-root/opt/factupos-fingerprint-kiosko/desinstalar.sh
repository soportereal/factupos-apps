#!/bin/bash
# Desinstalador GUI de FactuPOS FingerPrint (servicio + kiosko).
# Corre como USUARIO normal: confirma, eleva con pkexec y avisa el resultado.
# La parte root corre desde una COPIA en /tmp para no autoborrarse al hacer apt remove.

ROOT_SRC="/opt/factupos-fingerprint-kiosko/desinstalar-root.sh"

ask()  { command -v zenity >/dev/null 2>&1 && zenity --question --title="Desinstalar FactuPOS FingerPrint" --width=380 --text="$1"; }
info() { command -v zenity >/dev/null 2>&1 && zenity --info  --title="FactuPOS FingerPrint" --width=380 --text="$1" 2>/dev/null; }
err()  { command -v zenity >/dev/null 2>&1 && zenity --error --title="FactuPOS FingerPrint" --width=380 --text="$1" 2>/dev/null; }

# Confirmacion (si no hay zenity, sigue sin preguntar)
if command -v zenity >/dev/null 2>&1; then
    ask "¿Seguro que querés desinstalar FactuPOS FingerPrint?\n\nSe quitará el servicio del lector y el kiosko de marcaje." || exit 0
fi

TMP="$(mktemp /tmp/fp-desinstalar.XXXXXX.sh)"
cp "$ROOT_SRC" "$TMP" && chmod +x "$TMP"

pkexec "$TMP"
RC=$?
rm -f "$TMP" 2>/dev/null

if [ $RC -eq 0 ]; then
    info "FactuPOS FingerPrint fue desinstalado correctamente."
else
    err "No se pudo desinstalar (código $RC).\nProbá desde una terminal:\n  sudo apt remove factupos-fingerprint-kiosko factupos-fingerprint-servicio"
fi
