# SUNMI Print Bridge

APK Android liviana para SUNMI V2 que corre un servidor HTTP en `localhost:8765`.
Permite que Chrome (o cualquier navegador) envie tiquetes a la impresora termica interna via AIDL.

## Endpoints

| Metodo | Ruta | Body | Respuesta |
|--------|------|------|-----------|
| GET | `/ping` | - | `{"ok":true,"printer":"SUNMI V2","status":"ready"}` |
| POST | `/print` | `{"text":"tiquete..."}` | `{"ok":true,"message":"Impreso"}` |
| GET | `/status` | - | `{"ok":true,"connected":true,"paper":true}` |

## Compilar

1. Abrir en Android Studio
2. Build > Build Bundle(s) / APK(s) > Build APK
3. El APK se genera en `app/build/outputs/apk/debug/`

## Instalar en SUNMI V2

```bash
adb install app-debug.apk
```

## Caracteristicas

- Foreground Service (no lo mata Android)
- Auto-start al encender (BOOT_COMPLETED)
- NanoHTTPD como servidor HTTP (~50KB)
- SUNMI AIDL para impresion directa (no usa Bluetooth)
- CORS habilitado para fetch desde Chrome
