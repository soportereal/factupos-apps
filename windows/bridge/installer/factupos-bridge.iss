; ============================================================================
;  FactuPOS Print Bridge — Instalador (Inno Setup 6)
;  Servidor HTTP local (127.0.0.1:8765) que imprime por puerto COM Bluetooth.
;  Es una app de BANDEJA (tray-only): no tiene ventana, ya corre "oculta".
;
;  Que hace este instalador:
;    - Instala factupos-bridge.exe en "Archivos de programa\factupos-bridge".
;    - Lo configura para ARRANCAR AUTOMATICAMENTE al iniciar Windows (tray).
;    - Le da permiso "Modify" a la carpeta (icacls) para que el AUTO-UPDATE
;      (swap del .exe) y el guardado de bridge_config.json/bridge.log funcionen
;      SIN pedir UAC.
;
;  Se COMPILA solo en GitHub Actions (windows-latest) — ver bridge.yml.
;  UN instalador POR ARQUITECTURA:
;     ISCC.exe /DARCH=x64 installer\factupos-bridge.iss  -> Factupos-Bridge-x64.exe
;     ISCC.exe /DARCH=x86 installer\factupos-bridge.iss  -> Factupos-Bridge-x86.exe
; ============================================================================

#ifndef ARCH
  #define ARCH "x64"
#endif

#define MyAppName "FactuPOS Print Bridge"
#define MyAppId "factupos-bridge"
#define MyAppVersion "1.2"
#define MyAppPublisher "Soporte Real SRL"
#define MyAppURL "https://soportereal.com"
#define MyAppExeName "factupos-bridge.exe"

[Setup]
AppId={{8B2D4F61-9A3C-4E7D-B1F8-2C5A7E093D14}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppId}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Factupos-Bridge-{#ARCH}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
#if ARCH == "x64"
  ArchitecturesAllowed=x64compatible
  ArchitecturesInstallIn64BitMode=x64compatible
#endif

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "startmenu"; Description: "Crear acceso directo en el menu Inicio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
; El .exe del Bridge de la arquitectura correspondiente (lo genera PyInstaller;
; el workflow lo copia junto a este .iss), con el nombre fijo factupos-bridge.exe.
#if ARCH == "x64"
Source: "FactuposPrintBridge.exe"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
#else
Source: "FactuposPrintBridge-x86.exe"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: startmenu
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenu

[Registry]
; Autostart para TODOS los usuarios al iniciar sesion Windows (tray-only).
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#MyAppName}"; \
    ValueData: """{app}\{#MyAppExeName}"""; \
    Flags: uninsdeletevalue

[Run]
; Permiso Modify al grupo Usuarios (SID *S-1-5-32-545, independiente del idioma)
; sobre la carpeta: necesario para auto-update y guardar config/log.
Filename: "{sys}\icacls.exe"; Parameters: """{app}"" /grant *S-1-5-32-545:(OI)(CI)M /T"; \
    Flags: runhidden waituntilterminated; StatusMsg: "Configurando permisos de actualizacion..."

; Arrancar ahora (queda en la bandeja), al terminar la instalacion.
Filename: "{app}\{#MyAppExeName}"; \
    Description: "Iniciar {#MyAppName} ahora"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; Cerrar el proceso antes de desinstalar (si esta corriendo).
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#MyAppExeName}"; \
    Flags: runhidden; RunOnceId: "KillFactuposBridge"
