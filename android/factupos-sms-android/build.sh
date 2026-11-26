#!/bin/bash
# Compila el APK de FactuposSMS y lo publica en la zona de descargas centralizada
# (2026-06-19): soportereal.com/software/factupos-app/android/.
set -e
export JAVA_HOME=/home/factupos/jdk-17.0.12
export ANDROID_HOME=/home/factupos/android-sdk
export PATH="$JAVA_HOME/bin:$PATH"

cd /var/www/_proyectos/apps/android/factupos-sms-android
./gradlew --no-daemon assembleDebug

APK=app/build/outputs/apk/debug/app-debug.apk
DEST=/var/www/soportereal.com/software/factupos-app/android/FactuPOS-SMS-Android.apk
cp "$APK" "$DEST"
chmod 644 "$DEST"

# #3035 — la app lee este JSON para saber si hay versión nueva y ofrecer instalarla.
# Mismo formato que el de Soporte Remoto. Sale de build.gradle: una sola fuente para el número.
VCODE=$(grep -oP 'versionCode\s+\K[0-9]+' app/build.gradle)
VNAME=$(grep -oP 'versionName\s+"\K[^"]+' app/build.gradle)
JSON=/var/www/soportereal.com/software/factupos-app/android/Factupos-SMS_version.json
printf '{\n  "version": "%s",\n  "versionCode": %s,\n  "downloadUrl": "https://soportereal.com/software/factupos-app/android/FactuPOS-SMS-Android.apk"\n}\n' "$VNAME" "$VCODE" > "$JSON"
chmod 644 "$JSON"

echo "OK - APK $VNAME (versionCode $VCODE) recompilado y publicado ($(stat -c %s "$APK") bytes)"
