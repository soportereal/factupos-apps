# FactuPOS · Instalador de Impresoras (`factupos-printer-inst`)

Asistente **gráfico** (GTK3) para instalar impresoras **USB** y **Serial** (tickets
ESC/POS, ej. **Epson TM-U220** vía adaptador USB-Serie PL2303) como **cola RAW** en
CUPS — sin tocar la terminal. Es el "modo fácil" del script `configurar-tmu220.sh`.

## Qué hace
1. Detecta el adaptador serial (`/dev/ttyUSB*`, `/dev/ttyACM*`) o impresoras USB.
2. **Barrido de velocidad (baud)**: imprime una prueba a 9600/19200/38400… para
   descubrir cuál es la correcta (la legible).
3. Impresión de prueba con la velocidad/flujo elegidos.
4. Crea la cola **RAW** en CUPS (`lpadmin -m raw`) y la deja por defecto.

## Estructura
```
printer-inst/
  factupos-printer-inst.py     GUI (GTK3 + pyserial). Sin pycups.
  helper.py                    Helper privilegiado (root vía pkexec): lpadmin/lpinfo.
  factupos-printer-inst.desktop Lanzador del menú.
  polkit/49-*.rules            Permite al admin correr el helper sin clave.
  installer/
    build-deb.sh               Arma el .deb (arch: all).
    debian/control, postinst   Metadatos del paquete.
```

## Build local
```bash
printer-inst/installer/build-deb.sh 1.0.0
# -> printer-inst/installer/Output/factupos-printer-inst_1.0.0_all.deb
```
En CI lo arma `.github/workflows/printer-inst.yml` (artifact `factupos-printer-inst-deb`).

## Publicación
El `.deb` final se publica en
`soportereal.com/software/factupos-app/linux/factupos-printer-inst_X.Y.Z_all.deb`
(misma carpeta que los demás .deb de Linux).

## Dependencias (runtime)
`python3`, `python3-gi`, `gir1.2-gtk-3.0`, `python3-serial`, `cups`, `cups-client`,
`pkexec`. El usuario debe estar en el grupo **`dialout`** para el puerto serie
(`sudo usermod -aG dialout $USER`).

## Notas técnicas
- La TM-U220 imprime **ESC/POS crudo** → cola **RAW** (no "Generic Text-Only",
  que mutilaría los comandos).
- Flujo serie por defecto **`dtrdsr`** (DIP de fábrica de la TM-U220); seleccionable
  `none`/`rtscts`/`xonxoff`.
- El baud lo fijan los DIP switches de la impresora (autotest: apagar, mantener
  FEED y encender).
