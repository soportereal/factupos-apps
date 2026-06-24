; ============================================================================
;  FactuPOS Print — Instalador (Inno Setup 6)
;  Cliente de impresion: conecta por WebSocket a print.invefacon.com:9300,
;  recibe los trabajos de impresion y los manda a la impresora.
;
;  Que hace este instalador:
;    - Instala factupos-print.exe en "Archivos de programa\factupos-print".
;    - Lo configura para ARRANCAR AUTOMATICAMENTE al iniciar Windows, OCULTO
;      en la bandeja del sistema (flag --hidden) — sin checkbox en la interfaz.
;    - Le da permiso "Modify" a la carpeta de instalacion (icacls) para que el
;      AUTO-UPDATE silencioso (swap del .exe por WebSocket) y el guardado de
;      config.json/log funcionen SIN pedir UAC en cada actualizacion.
;
;  Se COMPILA solo en GitHub Actions (windows-latest) — ver
;  .github/workflows/build.yml. No requiere Windows local.
;
;  Nota: trae el .exe x64 y el x86; instala el que corresponde a la
;  arquitectura de Windows, siempre con el nombre fijo factupos-print.exe
;  (asi el autostart y el auto-update referencian un solo nombre).
; ============================================================================

#define MyAppName "FactuPOS Print"
#define MyAppId "factupos-print"
#define MyAppVersion "4.46"
#define MyAppPublisher "Soporte Real SRL"
#define MyAppURL "https://soportereal.com"
#define MyAppExeName "factupos-print.exe"

[Setup]
AppId={{C3F1A7D2-6B49-4E8A-AF15-9D7C2E640B83}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppId}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=factupos-print-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "startmenu"; Description: "Crear acceso directo en el menu Inicio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
; Los .exe los genera PyInstaller (matriz x64 + x86) ANTES de compilar este
; instalador; el workflow los copia junto a este .iss. Se instala SOLO el que
; corresponde a la arquitectura, renombrado al nombre fijo factupos-print.exe.
Source: "FactuPOS_Print.exe";     DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion; Check: Is64BitInstallMode
Source: "FactuPOS_Print-x86.exe"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion; Check: not Is64BitInstallMode

; SumatraPDF (visor portable usado por el modo DataReport para imprimir el PDF
; de forma silenciosa: SumatraPDF.exe -print-to "imp" -silent). La app lo busca
; primero en su propia carpeta {app}. El binario distribuido es x64 → se incluye
; SOLO en el instalador de 64-bit (en 32-bit no correria y solo infla el paquete).
Source: "SumatraPDF.exe"; DestDir: "{app}"; Flags: ignoreversion; Check: Is64BitInstallMode

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: startmenu
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenu

[Registry]
; Autostart para TODOS los usuarios al iniciar sesion Windows, OCULTO (--hidden).
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#MyAppName}"; \
    ValueData: """{app}\{#MyAppExeName}"" --hidden"; \
    Flags: uninsdeletevalue

[Run]
; Dar permiso de Modify al grupo Usuarios (SID *S-1-5-32-545, independiente del
; idioma) sobre la carpeta de instalacion. Necesario para que el auto-update
; pueda reemplazar el .exe y para guardar config.json/print_client.log alli.
Filename: "{sys}\icacls.exe"; Parameters: """{app}"" /grant *S-1-5-32-545:(OI)(CI)M /T"; \
    Flags: runhidden waituntilterminated; StatusMsg: "Configurando permisos de actualizacion..."

; Arrancar ahora (oculto en la bandeja), al terminar la instalacion.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--hidden"; \
    Description: "Iniciar {#MyAppName} ahora"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; Cerrar el proceso antes de desinstalar (si esta corriendo).
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#MyAppExeName}"; \
    Flags: runhidden; RunOnceId: "KillFactuposPrint"
