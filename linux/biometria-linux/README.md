# FactuPOS Biometría — Linux (servicio + kiosko Java)

Equivalente Linux del kiosko de huella de Windows. Dos piezas:

```
┌──────────────────────────────┐        ┌─────────────────────────────────┐
│ SERVICIO (Python + libfprint) │  HTTP  │ KIOSKO (Java/Swing, consume API) │
│ /opt/factupos-fingerprint-servicio       │ <───── │ /opt/factupos-fingerprint-kiosko      │
│ habla con el lector, matching  │        │ UI fullscreen, marca, registro   │
│ https://127.0.0.1:52181        │        │                                  │
└──────────────────────────────┘        └─────────────────────────────────┘
        (factupos-fingerprint-servicio .deb)              (este proyecto, kiosk-java)
                                                        │
                                                        ▼  APIs *_vb6.php (sin login)
                                                  https://<empresa>.invefacon.net
```

El **servicio** lee el lector y hace el matching (no cambia el lenguaje: sigue en Python
porque habla con `libfprint`). El **kiosko** es un cliente Java que solo consume HTTP:
identifica con el servicio local y registra la marca contra las APIs web.

---

## 1. Servicio Python — `factupos-fingerprint-servicio` **v2.2.0**

`packaging/deb-root/` es el árbol del `.deb`. Cambios v2.2.0 (necesarios para el kiosko):

| Endpoint nuevo | Para qué |
|----------------|----------|
| `POST /prints/clear`  | El kiosko vacía la cache antes de re-sincronizar |
| `POST /prints/import` | El kiosko carga las huellas desde la BD (base64) |
| `GET  /fingerprint/enroll/progress` | Barra de progreso del registro (toque N de M) |
| `POST /fingerprint/enroll/cancel`   | Cancelar el registro |
| `POST /fingerprint/enroll` (cambio) | Ahora devuelve `template_b64` + `serial` para guardar en BD |

Construir el `.deb` (se hace en cualquier Linux con `dpkg-deb`):

```bash
cd packaging
chmod 755 deb-root/DEBIAN/postinst deb-root/DEBIAN/prerm deb-root/DEBIAN/postrm
dpkg-deb --build deb-root factupos-fingerprint-servicio_2.2.0_amd64.deb
```

Instalar en la PC del lector:

```bash
sudo dpkg -i factupos-fingerprint-servicio_2.2.0_amd64.deb
sudo apt-get -f install          # dependencias (python3-gi, libfprint, etc.)
# aceptar el cert en Chrome: https://127.0.0.1:52181/status
systemctl status factupos-fingerprint-servicio
```

> El `.deb` ya está publicado en `https://factupos.com/downloads/factupos-fingerprint-servicio_2.2.0_amd64.deb`.

---

## 2. Kiosko Java — `kiosk-java/`

Cliente Swing, **sin dependencias externas** (solo el JDK). Estructura:

```
kiosk-java/
├── src/com/factupos/kiosk/
│   ├── Main.java          arranque, carga config
│   ├── Config.java        config.json + token.conf
│   ├── Json.java          parser/serializador JSON propio
│   ├── Http.java          HttpClient (TLS inseguro para 127.0.0.1)
│   ├── Api.java           APIs *_vb6.php con failover + token/db
│   ├── FpClient.java      cliente del servicio local
│   ├── KioskFrame.java    UI + worker loop + diálogos
│   ├── Sound.java         beeps
│   └── Log.java           logs
├── build.sh               compila a build/FactuposKioskoHuella.jar
├── run.sh                 lo ejecuta
├── config.json            ejemplo (plataforma=linux)
└── factupos-fingerprint-kiosko.desktop   autostart
```

### Compilar y correr (en la PC Linux, requiere JDK 11+)

```bash
sudo apt install default-jdk          # una sola vez
cd kiosk-java
./build.sh                            # genera build/FactuposKioskoHuella.jar
./run.sh
```

### Configuración

- Generá el **token** en la web: FactuPOS → Biometría → Configurar Kiosko → «Generar token»
  y descargá el `token.conf` (o pegalo en el botón ⚙ Config del kiosko).
- Poné el `token.conf` en la misma carpeta del jar. Alternativa legacy: campo `"db"` en `config.json`.
- `api_base`: lista con failover. Usar los dominios de la empresa (ej. `invefacon.net`), **no**
  `factupos.com` (desde internet apunta a otra IP).

### Autostart (modo reloj marcador)

```bash
sudo mkdir -p /opt/factupos-fingerprint-kiosko
sudo cp -r build config.json run.sh /opt/factupos-fingerprint-kiosko/
cp factupos-fingerprint-kiosko.desktop ~/.config/autostart/   # arranca con la sesión
```

---

## Flujo (idéntico al kiosk.py de Windows)

```
arranque → huellas_listar_vb6.php → /prints/clear + /prints/import (cache local)
loop     → /fingerprint/identify → match → marca_registrar_vb6.php → ENTRADA/SALIDA
"Registrar huella" → empleados_listar_vb6.php → /fingerprint/enroll (N toques, con progreso)
                   → huella_registrar_vb6.php (guarda en BD) → re-sync → marca
```

## Diferencias con Windows

| | Windows | Linux |
|--|---------|-------|
| Servicio | Python + DigitalPersona (ctypes) | Python + libfprint |
| Kiosko | Python/Tkinter (`kiosk.py`) | **Java/Swing** (este proyecto) |
| Template | `.fpt`, 4 toques, `plataforma=windows` | `.fpr`, 5 toques, `plataforma=linux` |

Los templates **no** son intercambiables entre plataformas: cada empleado se registra en la suya.

## Pendiente / notas

- **No compilado/probado en el server** (no hay JDK ahí). Compilar y probar en la PC del lector.
- El kiosko Java usa `plataforma=linux` → la BD `HuellaUsuario` debe tener huellas de esa plataforma
  (registralas desde este kiosko). Requiere migraciones `20260511104641` (HuellaUsuario) y
  `20260511104642` (KioskoToken) aplicadas en la empresa.
