#!/bin/bash
# Compila el APK de FactuposSMS y lo publica en la zona de descargas centralizada
# (2026-06-19): soportereal.com/software/factupos-app/android/.
set -e
export JAVA_HOME=/home/factupos/jdk-17.0.12
export ANDROID_HOME=/home/factupos/android-sdk
export PATH="$JAVA_HOME/bin:$PATH"

cd /var/www/_proyectos/factupos-sms-android
./gradlew --no-daemon assembleDebug

APK=app/build/outputs/apk/debug/app-debug.apk
DEST=/var/www/soportereal.com/software/factupos-app/android/FactuPOS-SMS-Android.apk
cp "$APK" "$DEST"
chmod 644 "$DEST"

echo "OK - APK recompilado y publicado ($(stat -c %s "$APK") bytes)"
