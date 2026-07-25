#!/bin/bash
# Arranca el kiosko. config.json y token.conf se leen del mismo directorio del jar.
DIR="$(cd "$(dirname "$0")" && pwd)"
JAR="$DIR/build/FactuposKioskoHuella.jar"
[ -f "$JAR" ] || { echo "No existe $JAR — corre ./build.sh primero"; exit 1; }
exec java -jar "$JAR"
