; ============================================================================
;  FactuPOS Biometria (Huella Digital) — Instalador (Inno Setup 6)
;  App C#/.NET para lector DigitalPersona U.are.U 4500. Incluye:
;    - FactuposFpServicio.exe : servicio local HTTPS 127.0.0.1:52181 (el que
;      habla con el lector). AL ARRANCAR, el servicio LANZA SOLO al kiosko.
;    - FactuposKiosko.exe     : app de marcaje de asistencia.
;
;  Este instalador EMPAQUETA los binarios YA COMPILADOS (no compila C#). El
;  workflow fingerprint.yml baja el ZIP v1.0.3 publicado, lo extrae a fp\ y
;  compila este .iss. Solo x64.
;
;  Que hace:
;    - Instala todo en "Archivos de programa\factupos-fingerprint".
;    - Autostart OCULTO al iniciar sesion (wscript + iniciar_oculto.vbs, que
;      arranca el servicio en segundo plano; el servicio abre el kiosko).
;    - icacls Modify en la carpeta: el servicio escribe prints\, logs\, certs\
;      y lee/guarda config.json / token.conf sin pedir UAC.
;
;  PRERREQUISITO (no lo instala esto): el driver DigitalPersona del lector.
; ============================================================================

#define MyAppName "FactuPOS Biometria"
#define MyAppId "factupos-fingerprint"
#define MyAppVersion "1.0.3"
#define MyAppPublisher "Soporte Real SRL"
#define MyAppURL "https://soportereal.com"
#define MyAppSvc "FactuposFpServicio.exe"
#define MyAppKiosk "FactuposKiosko.exe"
#define MyAppVbs "iniciar_oculto.vbs"

[Setup]
AppId={{5E9A1C73-2D84-4F60-B7A1-8C3F2E914D60}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppId}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Factupos-Fingerprint-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppKiosk}

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "startmenu"; Description: "Crear accesos directos en el menu Inicio"; GroupDescription: "Accesos directos:"

[Dirs]
; Carpetas de datos del servicio (con permiso de escritura via icacls abajo).
Name: "{app}\logs"
Name: "{app}\prints"
Name: "{app}\certs"

[Files]
; Binarios ya compilados + recursos, extraidos del ZIP por el workflow (carpeta fp\).
Source: "fp\{#MyAppSvc}";   DestDir: "{app}"; Flags: ignoreversion
Source: "fp\{#MyAppKiosk}"; DestDir: "{app}"; Flags: ignoreversion
Source: "fp\{#MyAppVbs}";   DestDir: "{app}"; Flags: ignoreversion
Source: "fp\version.txt";   DestDir: "{app}"; Flags: ignoreversion
Source: "fp\certs\*";       DestDir: "{app}\certs"; Flags: ignoreversion recursesubdirs createallsubdirs
; config.json / token.conf = config del equipo (token, dispositivo_id): NO
; sobrescribir si ya existen (preserva la config en reinstalaciones).
Source: "fp\config.json";   DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "fp\token.conf";    DestDir: "{app}"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName} (Marcaje)"; Filename: "wscript.exe"; Parameters: """{app}\{#MyAppVbs}"""; WorkingDir: "{app}"; Tasks: startmenu
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenu

[Registry]
; Autostart OCULTO al iniciar sesion: wscript lanza el .vbs (sin ventana negra),
; el .vbs arranca el servicio en 2do plano y el servicio abre el kiosko.
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "{#MyAppName}"; \
    ValueData: "wscript.exe ""{app}\{#MyAppVbs}"""; \
    Flags: uninsdeletevalue

[Run]
; Permiso Modify al grupo Usuarios (SID *S-1-5-32-545) sobre la carpeta:
; el servicio escribe prints/logs/certs y guarda config sin pedir UAC.
Filename: "{sys}\icacls.exe"; Parameters: """{app}"" /grant *S-1-5-32-545:(OI)(CI)M /T"; \
    Flags: runhidden waituntilterminated; StatusMsg: "Configurando permisos..."

; Arrancar ahora (oculto). El servicio levanta el kiosko.
Filename: "wscript.exe"; Parameters: """{app}\{#MyAppVbs}"""; WorkingDir: "{app}"; \
    Description: "Iniciar {#MyAppName} ahora"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#MyAppSvc}"; \
    Flags: runhidden; RunOnceId: "KillFpSvc"
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#MyAppKiosk}"; \
    Flags: runhidden; RunOnceId: "KillFpKiosk"
