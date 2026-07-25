# FactuposSMS (Android — Java/Gradle)

App Android nativa (Java + Gradle, mismo método que **FactuposBridge**) que **recibe los
SMS entrantes en tiempo real** (`BroadcastReceiver` SMS_RECEIVED) y los **reenvía por HTTP
POST** a un endpoint del servidor, que los inserta en `dbcontrol."PagosSinpe"` (PostgreSQL
en 192.168.7.10). Sirve para capturar **pagos SINPE** usando un teléfono normal (que sí
recibe MT, a diferencia del datacard Huawei E1556).

## Estructura
```
factupos-sms-android/
├── settings.gradle / build.gradle / gradle.properties / local.properties
├── gradlew + gradle/wrapper/         (Gradle 8.2, reusado del bridge)
└── app/
    ├── build.gradle                  (AGP 8.2.0, compileSdk 34, minSdk 23, sin deps externas)
    ├── proguard-rules.pro
    └── src/main/
        ├── AndroidManifest.xml       (permisos SMS, receiver, servicio foreground, boot)
        └── java/com/factupos/sms/
            ├── MainActivity.java      (UI: endpoint, token, SIM + botón de prueba)
            ├── SmsReceiver.java       (recibe SMS, arma texto, filtra SIM, reenvía)
            ├── Poster.java            (HTTP POST x-www-form-urlencoded)
            ├── ForwardService.java    (foreground service: mantiene vivo el proceso)
            ├── BootReceiver.java      (auto-start al encender)
            └── Config.java            (SharedPreferences)
```

## Configuración (en la app)
El usuario **solo configura el Nombre de la empresa**. El **endpoint** y el **token** son
**internos** (constantes `Config.ENDPOINT` / `Config.TOKEN`, no se escriben en la app).
Captura todas las SIM por defecto.

## Qué envía al servidor (POST x-www-form-urlencoded)
`token` (interno, + header `X-Factupos-Token`), `empresa` (configurable),
`fecha` (YYYY-MM-DD HH:MM:SS), `origen` (remitente), `mensaje` (texto),
`sub_id` (SIM por la que entró — dual-SIM).

## Compilar el APK (en el .11 — toolchain presente)
SDK en `/home/factupos/android-sdk`, JDK 17 en `/home/factupos/jdk-17.0.12`.
```bash
cd /var/www/_proyectos/factupos-sms-android
export JAVA_HOME=/home/factupos/jdk-17.0.12
export ANDROID_HOME=/home/factupos/android-sdk
./gradlew assembleDebug          # APK debug en app/build/outputs/apk/debug/
# release firmado: ./gradlew assembleRelease (configurar signingConfig + keystore)
```
Copiar el APK resultante a `factupos.com/downloads/FactuPOS-SMS-Android.apk`.

## Instalar en el teléfono
1. Instalar el APK (permitir orígenes desconocidos).
2. Abrir FactuposSMS y conceder permisos de **SMS**.
3. Escribir el **Nombre de la empresa** (único campo configurable).
4. "Enviar prueba al servidor" para validar; luego "Guardar e iniciar servicio".
5. **Desactivar optimización de batería** para la app y dejar el teléfono enchufado.

## Pendiente
- Endpoint server-side (`api_sinpe_inbound.php` o servicio en .10) que valide el token e
  inserte en `"PagosSinpe"` (Postgres .10).
