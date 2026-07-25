# FactuPOS Panel

Barra de tareas con **comportamiento tipo Windows** para FactuPOS OS (LMDE 7 / Cinnamon, X11).
Íconos propios de FactuPOS, comportamiento clásico de barra de tareas.

## Qué hace
- **Botón Inicio** → menú **Programas / Utilidades** + Apagar / Reiniciar / Cerrar sesión.
- **Programas abiertos** visibles como botones (Wnck): clic = enfocar/minimizar, clic
  derecho = Minimizar / Maximizar / Cerrar.
- **Red / WiFi** (indicador + abre el configurador de red).
- **Reloj con fecha**.
- **Mostrar el escritorio** (extremo derecho).
- **Clic derecho en la barra** → Administrador de tareas · Mostrar escritorio ·
  Mover la barra a otro monitor · Barra arriba/abajo · Config · Cerrar panel.
- **Ctrl+Shift+Esc** → Administrador de tareas (atajo igual que Windows).
- **Multi-monitor**: elige en qué pantalla va.

## Dependencias
`python3 python3-gi gir1.2-gtk-3.0 gir1.2-wnck-3.0 python3-xlib network-manager`
(recomendado: `gnome-system-monitor` para el Administrador de tareas)

## Probar sin instalar
```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-wnck-3.0 python3-xlib gnome-system-monitor
python3 factupos-panel.py --list-monitors        # ver los monitores
python3 factupos-panel.py --monitor 1            # arrancar en el monitor 1
python3 factupos-panel.py --edge top --monitor 2 # arriba, en el monitor 2
```
> En Cinnamon ya hay un panel propio: para no superponerse, probalo con
> `--edge top` o quitá/auto-oculta el panel de Cinnamon (clic derecho en el
> panel → *Configurar* / *Quitar panel*).

## Construir el .deb
```bash
./installer/build-deb.sh 1.0.0
sudo apt install ./installer/Output/factupos-panel_1.0.0_all.deb
```
El .deb instala autostart en `/etc/xdg/autostart`, así arranca solo al iniciar sesión.

## Personalizar el menú Inicio
Crear `/etc/factupos-panel/menu.json` (mismo formato que `DEFAULT_MENU` en el
script): `{ "Programas": [["Etiqueta","comando","icono"], ...], "Utilidades": [...] }`.

## Opciones
| Opción | Descripción |
|---|---|
| `--monitor N` | Monitor donde va (0,1,2...). Por defecto el primario. |
| `--edge bottom\|top` | Borde de la pantalla. Por defecto abajo. |
| `--height N` | Alto en px (44 por defecto). |
| `--list-monitors` | Lista los monitores y sale. |
