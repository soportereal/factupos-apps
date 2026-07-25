# Instalación del Kiosko de Huella — PC Linux del cliente

Procedimiento para dejar una PC Linux marcando asistencia por huella.

## Requisitos
- PC con **Linux Debian / Ubuntu / Linux Mint** (64 bits) y entorno de escritorio.
- Lector de huella **DigitalPersona U.are.U 4500** (USB `05ba:000a`) conectado.
- Conexión a internet (para bajar dependencias).
- Un **token** del kiosko generado en la web (ver Paso 5).

---

## Paso 1 — Descargar los 2 instaladores

Desde FactuPOS web (en cualquier PC):
**Menú → Aplicaciones → Huella Digital** y descargá:

1. **Huella Digital Linux (servicio)** → `factupos-fingerprint-servicio_2.2.0_amd64.deb`
2. **Kiosko Huella Linux (app)** → `factupos-fingerprint-kiosko_1.0.0_all.deb`

Pasalos a la PC del lector (USB, red, o descargalos directo en esa PC).

---

## Paso 2 — Instalar el SERVICIO del lector

Abrí una terminal en la carpeta donde están los `.deb`:

```bash
sudo dpkg -i factupos-fingerprint-servicio_2.2.0_amd64.deb
sudo apt-get -f install -y        # instala libfprint y dependencias
```

Verificá que quedó corriendo:

```bash
systemctl status factupos-fingerprint-servicio        # debe decir "active (running)"
curl -sk https://127.0.0.1:52181/status     # debe devolver un JSON con "version":"2.2.0"
```

> Si el lector está enchufado, el log (`journalctl -u factupos-fingerprint-servicio -f`) debe mostrar
> el nombre del dispositivo y "stages".

---

## Paso 3 — Aceptar el certificado en Chrome

El servicio usa HTTPS con certificado autofirmado. Una sola vez:

1. Abrí **Chrome** en esa PC.
2. Andá a: `https://127.0.0.1:52181/status`
3. "Configuración avanzada" → "Continuar a 127.0.0.1 (no seguro)".
4. Debe verse el JSON de estado. (Esto autoriza al navegador y al kiosko a hablar con el servicio.)

---

## Paso 4 — Instalar la APP kiosko

```bash
sudo dpkg -i factupos-fingerprint-kiosko_1.0.0_all.deb
sudo apt-get -f install -y        # instala Java (default-jre) automáticamente
```

Al terminar queda:
- Un ícono **"FactuPOS Kiosko Huella"** en el **Escritorio** y en el menú de aplicaciones.
- El comando `factupos-fingerprint-kiosko` en la terminal.

---

## Paso 5 — Generar el token (en la web, una vez por PC)

1. Entrá a FactuPOS web con un usuario con permiso.
2. **Menú → Biometría → Configurar Kiosko**.
3. Botón **"Generar token"** → se crea un token `empresa~xxxxxxxx`.
4. Copialo (o descargá el `token.conf`).

> El token identifica la empresa. Es el mismo formato que el kiosko de Windows.

---

## Paso 6 — Configurar el token en la app

1. Abrí **"FactuPOS Kiosko Huella"** (doble clic en el ícono del Escritorio).
2. La primera vez abre solo el diálogo de configuración. Si no, tocá el botón **⚙ Config**.
3. Pegá el **token** en el campo "Token".
4. (Opcional) Ajustá el "Identificador del puesto" (ej. `KIOSKO-RECEPCION`).
5. Revisá las URLs del servidor (`api_base`): poné el dominio de la empresa
   (ej. `https://empresa.invefacon.net, https://empresa.invefacon.com`).
6. **Guardar**. El kiosko se conecta y empieza a esperar dedos.

---

## Paso 7 — Registrar huellas y probar

1. En el kiosko, botón **"✋ Registrar huella"**.
2. Elegí el empleado y el dedo → **"Iniciar registro"**.
3. Poné el dedo en el lector las veces que pida (5 toques en Linux).
4. Al terminar, registra la marca automáticamente (ENTRADA).
5. Probá marcar: poné el dedo → debe reconocer y mostrar ENTRADA / SALIDA con un beep.

---

## (Opcional) Que arranque sola al prender la PC (modo reloj)

```bash
mkdir -p ~/.config/autostart
cp /usr/share/applications/factupos-fingerprint-kiosko.desktop ~/.config/autostart/
```

Para pantalla completa: abrí el kiosko y pulsá **Esc** (alterna), o poné
`"fullscreen": true` en `~/.config/factupos-fingerprint-kiosko/config.json`.
Salir: **F10**.

---

## Solución de problemas

| Síntoma | Causa / solución |
|---------|------------------|
| "El servicio local de huella no está corriendo" | `systemctl restart factupos-fingerprint-servicio`. Ver `journalctl -u factupos-fingerprint-servicio -f`. |
| El lector no se detecta | Revisá el cable/puerto USB. `lsusb` debe mostrar `05ba:000a`. Reconectá y reiniciá el servicio. |
| El servicio no toma el lector / "device busy" | Otro proceso lo tiene. Deshabilitá fprintd: `sudo systemctl mask --now fprintd` y reiniciá el servicio. |
| Chrome / el kiosko no conecta a 127.0.0.1:52181 | Repetí el Paso 3 (aceptar el certificado). |
| "Falta migración HuellaUsuario" | Aplicar en la empresa las migraciones `20260511104641` (HuellaUsuario) y `20260511104642` (KioskoToken) desde `migraciones.php`. |
| No reconoce la huella | Registrala en **esta** PC (Linux). Los templates de Windows (.fpt) NO sirven en Linux (.fpr) y viceversa. |
| No abre la app | Verificá Java: `java -version`. Si falta: `sudo apt install default-jre`. |

## Desinstalar

```bash
sudo apt remove factupos-fingerprint-kiosko factupos-fingerprint-servicio
```

## Dónde queda cada cosa
- Servicio: `/opt/factupos-fingerprint-servicio/` · templates `.fpr` en `/opt/factupos-fingerprint-servicio/prints/`
- App: `/opt/factupos-fingerprint-kiosko/` · config del usuario en `~/.config/factupos-fingerprint-kiosko/`
  (`config.json`, `token.conf`, `logs/`)
