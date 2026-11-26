# FactuPOS · Gestión de Impresoras (`factupos-printer-inst`) — antes «Instalador de Impresoras»

Asistente **gráfico** (GTK3) para instalar impresoras **USB** y **Serial** (tickets
ESC/POS, ej. **Epson TM-U220** vía adaptador USB-Serie PL2303) como **cola RAW** en
CUPS — sin tocar la terminal. Es el "modo fácil" del script `configurar-tmu220.sh`.

## Qué hace
**Pantalla de inicio — «Impresoras de este equipo»** (1.2.0, #2831): lista las colas de
CUPS (`lpstat`, sin root) con su conexión (USB / Serial / Red / Directo), si es la
predeterminada y si está detenida. Cada una tiene:
- **Prueba**: manda una página por la cola (`lp`, `-o raw` si la cola es RAW).
- **Predeterminada**: `helper.py default` → `lpadmin -d`.
- **Desinstalar** (pide confirmación): `helper.py remove` → `lpadmin -x`. Se da por
  hecha solo si la impresora ya no aparece en `lpstat`.

🪤 El auto-update de la app cambia solo el `.py` del usuario; `helper.py` (root) se
renueva con el `.deb`. Si el helper instalado es anterior a 1.2.0 y no conoce
`remove`/`default`, la app cae a `/usr/sbin/lpadmin` directo (un usuario del grupo
`lpadmin` puede por el socket local de CUPS). Desde 1.2.0 el paquete trae su propio
revisor (`_comun/autoupdate.sh`, timer cada hora), así el helper también se pone al día.

**Impresoras «De la red»** (1.3.1): las colas `implicitclass://` las crea **cups-browsed**
solo, por cada impresora que otro equipo comparte. Borrarlas con `lpadmin -x` no sirve
(vuelven a los segundos, visto en la .18). `helper.py remove` les agrega a
`/etc/cups/cups-browsed.conf` la línea `BrowseFilter NOT EXACT name <cola> # factupos-printer-inst: oculta`,
reinicia cups-browsed y recién ahí borra la cola. Abajo de la lista quedan en «Impresoras
de la red ocultas» con **Volver a mostrar** (`helper.py unhide`); `helper.py hidden` las lista.

**Red (1.3.0)** — tercera opción del asistente: recorre la /24 de cada placa (puertos 9100,
631, 515, 445; 128 hilos, ~5 s) y ofrece: impresoras directas por IP (`socket://ip:9100`),
impresoras IPP (`ipp://ip/ipp/print`), lo que comparte otro equipo por CUPS (página
`/printers/` del 631 → `ipp://ip:631/printers/<cola>`; 🪤 CUPS escribe `<A HREF=` en
mayúsculas) y equipos Windows (`smbclient -L -N -g`; si no lista, se escribe el nombre
compartido + usuario/clave → `smb://usuario:clave@ip/recurso`, la clave nunca se muestra).
También se puede agregar una IP a mano. «¿Qué imprime?»: tiquetes → cola RAW · hojas →
`-m everywhere`. La prueba directa (9100) va por socket, sin CUPS.

**Impresora PDF (1.4.5, #3494)**: botón **«+ Impresora PDF»**. Nombre (sugiere `PDF`, `PDF_2`…)
+ casilla «predeterminada» → `helper.py pdf-add --name X [--default]` → cola `cups-pdf:/` con el PPD
`/usr/share/ppd/cups-pdf/CUPS-PDF_opt.ppd`, papel de `paperconf` (Letter si no hay). Lo impreso queda
como PDF en **`~/PDF` del usuario que imprime** (`Out ${HOME}/PDF` de `/etc/cups/cups-pdf.conf`). Su
tarjeta trae **«Abrir carpeta»** (`xdg-open ~/PDF`) y la prueba avisa dónde quedó el archivo.
🪤 `printer-driver-cups-pdf` va en **Suggests, no en Depends**: su postinst crea SOLO una cola «PDF»
(y la deja predeterminada si no hay otra) — con Depends aparecería en todos los equipos al
actualizar. El helper lo instala (`apt-get install`) la primera vez y **borra la cola automática**
que nadie pidió. Helper anterior a 1.4.5 → «Falta actualizar un componente» + «Actualizar ahora».
**Virtual con destino PDF (1.4.6)**: si «Imprime en» es una impresora PDF, `vport.py` limpia los
códigos ESC/POS de lo que llega al COM (`escpos_a_texto`: ESC/GS/FS/DLE, imágenes, códigos de barras;
PC850 o Windows-1252 según los bytes) y lo manda como **texto** (`-o cpi=12 -o lpi=7`). Lo del
navegador (ya convertido a PostScript por el PPD de CUPS-PDF) va crudo. 🪤 vport corre como **root**:
el trabajo va con `lp -U <usuario>` (el que creó la virtual, `PKEXEC_UID` → `usuario` del `.json`;
si falta, el de la sesión gráfica de `who`), si no el PDF queda en `/root/PDF`. Título con fecha y
hora: cups-pdf nombra el archivo por el título y pisaría el anterior.

**Impresoras virtuales — puerto COM (1.4.0, #3420)**: botón **«+ Impresora virtual»**. Se le
pone **el nombre que se quiera**, se elige un **puerto COM** (COM1…COM32, solo los libres) y
**la impresora ya instalada** en la que imprime (USB, serial, red, cualquiera). Los programas
imprimen en ese COM como si hubiera una impresora serial conectada.
- `helper.py vport-add --nombre --cola --com` escribe `/etc/factupos-printer-inst/vport/COM<n>.json`
  y prende `factupos-vport@<n>.service` → `vport.py <n>` abre un pseudo-terminal y lo deja en
  **`/dev/ttyCOM<n>`** (permiso 0666). `vport-remove --com` lo apaga y borra la configuración.
- Lo que llega se junta y, tras **0,8 s sin datos**, sale como **un** trabajo crudo
  (`lp -d <cola> -o raw -t <nombre>`): un tiquete no se parte aunque el programa cierre y
  reabra el puerto. Probado con pyserial: sin flujo, `dsrdtr`, `rtscts`, `xonxoff`.
- **Wine**: si existe `~/.wine`, la casilla «programas de Windows» crea
  `~/.wine/dosdevices/com<n>` → `/dev/ttyCOM<n>` (del usuario, sin root).
- La lista muestra la sección «Impresoras virtuales (puerto COM)» con **Prueba** (escribe en
  el COM, como un programa) y **Quitar**; insignias «Detenida» (no existe el puerto) e
  «Impresora no instalada» (se desinstaló la de destino).
- 🔑 Necesita el `.deb` 1.4.0 (vport.py + la unidad systemd son de root): con el helper
  viejo la app avisa «falta actualizar un componente» y no llama nada.
- 🪤 `helper.py` corre todo con `LC_ALL=C`: en español `lpstat` dice «dispositivo para» y
  `vport-add` creía que la impresora no existía (visto en la prueba como root, #3420).
- **1.4.1 — el navegador la ve**: cada virtual queda además como **impresora del sistema con su
  nombre** (`-D <nombre>`, cola = nombre limpio) apuntando a `socket://127.0.0.1:(19100+n)`, donde
  escucha el mismo `vport.py` (cada conexión = un trabajo). 🪤 No se usa `serial:/dev/ttyCOMn`:
  AppArmor de cupsd solo deja `/dev/ttyS*` y `/dev/ttyUSB*`, y el COM virtual es `/dev/pts/N`
  («Unable to open serial port: Permission denied»). Destino con controlador → sin `-o raw`
  (el PDF del navegador lo convierte la impresora real); destino RAW → `-o raw`.
  `helper.py vport-sync` (lo corre el postinst) le agrega la cola a las virtuales de la 1.4.0.
  Se rechaza como destino otra virtual (círculo) y un nombre que ya usa otra impresora.
- **1.4.2 — «Actualizar ahora»**: la pantalla se pone al día sola (auto-update del `.py`) pero el
  paquete (helper, vport.py) puede ir atrasado; entonces la virtual sale con «El navegador no la ve»
  y el botón **Actualizar ahora**: arranca `factupos-apps-op@instalar-factupos-printer-inst`
  (FactuPOS Apps, sin clave, polkit 51) o, si no está la Tienda, `pkexec systemctl start
  factupos-printer-inst-autoupdate` (pide clave), y luego `helper.py vport-sync`. También está en el
  aviso «Falta actualizar un componente». Pensado para PCs fuera de la red.
- **1.4.3 — botón Imprimir gris en Chrome**: con la cola *raw* Chrome no tiene tamaños de papel y deja
  «Imprimir» deshabilitado. Ahora la cola de la virtual lleva **el mismo PPD que la real**
  (`lpadmin -P /etc/cups/ppd/<real>.ppd`): el trabajo sale preparado para ella y `vport.py` lo pasa
  con `-o raw` (se convierte UNA vez). Si la real es *raw*, la virtual también (y la real tampoco se
  puede usar desde Chrome). 🪤 «Generic Text-Only» NO sirve: Debian no trae filtro PDF→texto.
  `vport-sync` pasa las virtuales viejas al PPD. Marca `fp-helper: vport-ppd` en helper.py: sin ella
  la tarjeta dice «Falta actualizar» y ofrece «Actualizar ahora».
- **1.4.4 — driver «FactuPOS térmica» (en el spooler)**: PPD `/usr/share/ppd/factupos/factupos-termica.ppd`
  (rollo 80/58 mm, 203 ppp, 1 bit negro) + filtro `/usr/lib/cups/filter/rastertofactupos`
  (`cupsFilter2: vnd.cups-raster -> vnd.cups-raw`). Cadena en Debian/Mint: PDF → pdftopdf →
  gstoraster → raster → nuestro filtro → ESC/POS (GS v 0 en tiras de 256 filas, recorta el blanco,
  avance + corte `GS V A 3`). La virtual lo usa si la real es *raw*; el asistente ofrece «¿Desde dónde
  va a imprimir?» (FactuPOS Print = RAW · navegador = driver) en USB/serial y una 3.ª opción en Red →
  la MISMA impresora se instala dos veces con distinto nombre (como en Windows).
  🪤 pdftoraster rellena con 1 los bits de sobra si el ancho no es múltiplo de 8 (58 mm = 383 puntos):
  se apagan, si no no recortaba nada. El .11 tiene cups-filters 2 (filtro «universal», otras reglas).
- La pantalla reconoce la cola de cada virtual por su **puerto** (`19100+n`), no por lo anotado en el `.json`.
- Registro: `journalctl -u factupos-vport@<n>`.

**Asistente «+ Instalar impresora»** (4 pasos con indicador arriba):
1. Detecta el adaptador serial (`/dev/ttyUSB*`, `/dev/ttyACM*`) o impresoras USB.
2. **Barrido de velocidad (baud)**: imprime una prueba a 9600/19200/38400… para
   descubrir cuál es la correcta (la legible).
3. Impresión de prueba con la velocidad/flujo elegidos.
4. Crea la cola **RAW** en CUPS (`lpadmin -m raw`); la casilla «Dejarla como
   predeterminada» decide `--no-default`. El nombre se limpia (sin espacios, `/`, `#`,
   comillas); si ya existe una con ese nombre, avisa que se reemplaza. Al terminar ofrece
   imprimir una página de prueba por la cola recién creada.

El detalle técnico (salida de los comandos) va plegado abajo, en «Detalle técnico».

## Estructura
```
printer-inst/
  factupos-printer-inst.py     GUI (GTK3 + pyserial). Sin pycups.
  helper.py                    Helper privilegiado (root vía pkexec): lpadmin/lpinfo, vport-add/remove.
  vport.py                     Impresora virtual: COM virtual -> cola CUPS (#3420, un servicio por COM).
  systemd/factupos-vport@.service  La unidad de cada COM virtual.
  factupos-printer-inst.desktop Lanzador del menú.
  polkit/49-*.rules            Permite al admin correr el helper sin clave.
  installer/
    build-deb.sh               Arma el .deb (arch: all).
    debian/control, postinst   Metadatos del paquete.
```

## Build local
```bash
factupos-printer-inst/installer/build-deb.sh          # versión = la del .py
# -> installer/Output/factupos-printer-inst_X.Y.Z_all.deb
```
En CI lo arma `.github/workflows/printer-inst.yml` (artifact `factupos-printer-inst-deb`).

## Publicación
Pool APT con **nombre fijo** `apt/pool/Factupos-Printer-Inst.deb` →
`apt/actualizar-repo.sh` → `apt/publicar.py --aplicar` (genera manifiesto y `.py` del
auto-update). No usar `_comun/publicar-app.sh` (deja copia versionada).

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
