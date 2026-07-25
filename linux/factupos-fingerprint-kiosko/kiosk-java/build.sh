#!/bin/bash
# Compila el kiosko Java a un JAR ejecutable. Solo necesita un JDK 11+ (javac/jar).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$DIR/src"
OUT="$DIR/build/classes"
JAR="$DIR/build/FactuposKioskoHuella.jar"

command -v javac >/dev/null || { echo "ERROR: falta el JDK (javac). Instala: sudo apt install default-jdk"; exit 1; }

echo "[build] limpiando..."
rm -rf "$DIR/build"
mkdir -p "$OUT"

echo "[build] compilando (--release 11)..."
find "$SRC" -name '*.java' > "$DIR/build/sources.txt"
javac --release 11 -encoding UTF-8 -d "$OUT" @"$DIR/build/sources.txt"

echo "[build] empaquetando jar..."
printf 'Main-Class: com.factupos.kiosk.Main\n' > "$DIR/build/MANIFEST.MF"
jar cfm "$JAR" "$DIR/build/MANIFEST.MF" -C "$OUT" .

echo "[build] OK -> $JAR"
echo "[build] Ejecutar:  java -jar \"$JAR\"   (o ./run.sh)"
