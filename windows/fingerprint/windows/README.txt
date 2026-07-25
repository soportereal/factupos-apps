============================================
 FactuPOS - Lector de Huella Digital
 Servicio para Windows v1.0
============================================

REQUISITOS:
- Windows 10/11 64-bit
- .NET Framework 4.x (ya incluido en Windows)
- Google Chrome o Microsoft Edge
- Lector Digital Persona U.are.U 4500 conectado por USB

ESTRUCTURA DE ARCHIVOS:
  instalar.bat          - Instalador (ejecutar como Admin)
  reiniciar_servicio.bat - Reiniciar el servicio
  src/
    FingerprintService.cs - Codigo fuente del servicio
  sdk/                    - DLLs del SDK DigitalPersona (copiar aqui)
    DPFPDevNET.dll
    DPFPShrNET.dll
    DPFPEngNET.dll
    DPFPVerNET.dll
    DPFPGuiNET.dll
  drivers/                - Driver del lector (opcional)
    dpinst64.exe

ANTES DE INSTALAR:

1. Copie los DLLs del SDK a la carpeta sdk/
   Los DLLs estan en: One Touch SDK/.NET/Bin/
   Copiar: DPFPDevNET.dll, DPFPShrNET.dll, DPFPEngNET.dll,
           DPFPVerNET.dll, DPFPGuiNET.dll

2. Conecte el lector U.are.U 4500 al puerto USB

3. Ejecute "instalar.bat" como Administrador
   (Click derecho > Ejecutar como administrador)

   El instalador:
   - Compila el servicio con csc.exe (incluido en Windows)
   - Genera certificado SSL autofirmado (10 anios)
   - Registra tarea programada para inicio automatico
   - Inicia el servicio

4. Abra Chrome y vaya a:
   https://127.0.0.1:52181/status
   Acepte el certificado. Debe ver: {"ok":true,"connected":true}

5. Ya puede usar "Marcar con huella" en FactuPOS

API ENDPOINTS:
  GET  /status              - Estado del servicio y lector
  GET  /get_connection      - Info de conexion
  GET  /prints              - Lista usuarios registrados
  POST /fingerprint/identify - Identificar huella (poner dedo)
  POST /fingerprint/enroll   - Registrar huella (4 toques)
       Body: {"user_id":"xxx","finger":"right_index"}
  DELETE /prints/:user_id   - Eliminar huellas de usuario

INSTALACION:
  C:\FactuPOS\FingerprintService\
    FingerprintService.exe  - Ejecutable compilado
    prints/                 - Templates biometricos
    cert.pfx                - Certificado SSL
    *.dll                   - DLLs del SDK

SOLUCION DE PROBLEMAS:

- Si no compila:
  Verifique que existe C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe
  Si no existe, instale .NET Framework 4.8 de Microsoft.

- Si el lector no se detecta:
  1. Verifique el LED del lector
  2. Pruebe otro puerto USB
  3. Administrador de Dispositivos > Biometric devices

- Si Chrome dice "No se puede conectar":
  1. Ejecute reiniciar_servicio.bat
  2. Verifique en Administrador de Tareas que FingerprintService.exe este corriendo

- Si el certificado no se acepta:
  1. Vaya a https://127.0.0.1:52181/status
  2. Click en "Avanzado" > "Continuar a 127.0.0.1"

SOPORTE:
  info@soportereal.com
