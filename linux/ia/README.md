# Factupos-IA (app del monorepo)

Soporte remoto con IA: el técnico abre la ventana en la PC del cliente, describe
el problema y Claude diagnostica/corrige la estación ejecutando comandos locales
con confirmación. La app **no contiene la API key**: llama al proxy de la página,
que reusa la key central de la web (`config_ia.php` → `/var/www/_secrets/factupos_ia.php`).

## Estructura
```
ia/
├── factupos_ia.py            # app GTK3 (Win+Linux) · VERSION + auto-updater
├── factupos-ia.desktop       # lanzador de menú (Linux)
├── installer/
│   ├── build-deb.sh          # arma el .deb
│   ├── debian/{control,postinst}
│   └── factupos-ia.iss       # instalador Windows (Inno Setup, x64/x86)
├── manifests/
│   ├── factupos-ia_version.json   # manifest Linux (py + deb)
│   └── factupos_ia_version.json   # manifest Windows (downloadUrl)
└── README.md
```
El workflow vive en `.github/workflows/ia.yml`.

## Versionado
La versión es única: la constante `VERSION` en `factupos_ia.py`. Subir versión =
editar esa constante (y los manifests al publicar).

## Config en el cliente (token app↔proxy)
La app lee, en orden: variables de entorno (`SOPORTE_APP_TOKEN`, `SOPORTE_BASE_URL`,
`SOPORTE_MODELO`) → `%APPDATA%\Factupos-IA\config.json` (Windows) →
`~/.config/factupos-ia/config.json` (Linux) → `/etc/factupos-ia/config.json`.

`config.json` de ejemplo:
```json
{ "base_url": "https://soportereal.com/claude-proxy", "token": "<token de factupos.local/soporte_ia/token.php>" }
```

## Auto-actualización
- **Windows** (.exe): `update_loop` lee `https://factupos.com/downloads/factupos_ia_version.json`,
  descarga el .exe nuevo y lo cambia con `updater.bat`.
- **Linux** (.py): lee `https://soportereal.com/software/factupos-app/linux/factupos-ia_version.json`,
  baja el `.py` a `~/.local/share/factupos-ia/` y reinicia. El lanzador `/usr/bin/factupos-ia`
  elige siempre la versión más nueva (sistema vs local).

## Build / publicación
- **Linux:** `bash ia/installer/build-deb.sh 1.0.0` → `installer/Output/factupos-ia_1.0.0_all.deb`.
  Publicar como `Factupos-IA.deb` + `factupos_ia.py` + el manifest en
  `/var/www/soportereal.com/software/factupos-app/linux/`.
- **Windows:** lo compila el workflow (PyInstaller+GTK vía MSYS2 + Inno). Bajar los
  artefactos con `gh run download` y publicarlos en
  `/var/www/soportereal.com/software/factupos-app/windows/` (`Factupos-IA-x64.exe`
  instalador + `Factupos-IA-Windows.exe` para el auto-update), luego subir el manifest.
