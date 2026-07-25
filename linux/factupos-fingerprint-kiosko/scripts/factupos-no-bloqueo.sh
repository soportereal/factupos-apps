#!/bin/bash
# ============================================================================
# FactuPOS Kiosko — Desactivar bloqueo de pantalla / salvapantallas / suspensión
# ============================================================================
# Para una PC de marcaje desatendida: evita que la pantalla se bloquee y pida
# contraseña al pasar un tiempo inactiva. Cubre Linux Mint (Cinnamon), GNOME,
# MATE, XFCE/light-locker y X11 (apagado de monitor / DPMS).
#
# USO (como el usuario del escritorio, NO root):
#   bash factupos-no-bloqueo.sh
#
# Se vuelve a aplicar solo en cada inicio de sesión (deja un autostart).
# ============================================================================

echo "[FactuPOS] Desactivando bloqueo de pantalla / salvapantallas / suspensión..."

# ---- Cinnamon (Linux Mint) ----
gsettings set org.cinnamon.desktop.screensaver lock-enabled false                     2>/dev/null
gsettings set org.cinnamon.desktop.screensaver idle-activation-enabled false          2>/dev/null
gsettings set org.cinnamon.desktop.session idle-delay 0                                2>/dev/null
gsettings set org.cinnamon.settings-daemon.plugins.power sleep-display-ac 0            2>/dev/null
gsettings set org.cinnamon.settings-daemon.plugins.power sleep-display-battery 0       2>/dev/null
gsettings set org.cinnamon.settings-daemon.plugins.power sleep-inactive-ac-timeout 0   2>/dev/null
gsettings set org.cinnamon.settings-daemon.plugins.power sleep-inactive-battery-timeout 0 2>/dev/null
gsettings set org.cinnamon.settings-daemon.plugins.power lock-on-suspend false         2>/dev/null

# ---- GNOME ----
gsettings set org.gnome.desktop.screensaver lock-enabled false                         2>/dev/null
gsettings set org.gnome.desktop.screensaver idle-activation-enabled false              2>/dev/null
gsettings set org.gnome.desktop.session idle-delay 0                                    2>/dev/null
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'  2>/dev/null
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing' 2>/dev/null

# ---- MATE ----
gsettings set org.mate.screensaver lock-enabled false                                  2>/dev/null
gsettings set org.mate.screensaver idle-activation-enabled false                       2>/dev/null

# ---- light-locker (bloqueador típico en XFCE/Mint) ----
pkill light-locker 2>/dev/null
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/light-locker.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=light-locker
Hidden=true
X-GNOME-Autostart-enabled=false
EOF

# ---- X11: apagar salvapantalla y DPMS (apagado del monitor) ----
if [ -n "$DISPLAY" ]; then
  xset s off       2>/dev/null
  xset s noblank   2>/dev/null
  xset -dpms       2>/dev/null
fi

# ---- Auto-aplicar en cada inicio de sesión ----
DEST="$HOME/.local/bin/factupos-no-bloqueo.sh"
mkdir -p "$HOME/.local/bin"
cp -f "$0" "$DEST" 2>/dev/null && chmod +x "$DEST"
cat > "$HOME/.config/autostart/factupos-no-bloqueo.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=FactuPOS No Bloqueo
Comment=Mantiene la pantalla activa para el kiosko de marcaje
Exec=$DEST
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

echo "[FactuPOS] Listo. La pantalla ya no se bloqueará por inactividad."
echo "          Se aplicará solo en cada inicio de sesión."
echo ""
echo "  (Opcional) Para que el EQUIPO nunca suspenda a nivel sistema, ejecutá UNA vez con sudo:"
echo "     sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target"
