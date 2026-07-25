; ============================================================================
;  FactuposBackup — Instalador (Inno Setup 6)
;  App residente en bandeja que respalda TODAS las BD de un SQL Server a ZIP,
;  diariamente a la hora configurada. Trae:
;    - FactuposBackup.exe    : GUI + bandeja (configurar, programar, ejecutar).
;    - FactuposBackupCLI.exe : version consola (opcional, para tareas).
;
;  A diferencia de Print/Bridge, la app YA gestiona lo suyo:
;    - Auto-update propio (config auto_update_enabled + factupos_backup_version.json).
;    - Toggles "Iniciar con Windows" / "Iniciar minimizado" (autostart) y la
;      programacion diaria del respaldo. Por eso ESTE instalador NO fuerza
;      autostart: instala, da permisos y lanza la GUI para que el admin la
;      configure (servidor / usuario / clave) y active el inicio desde ahi.
;
;  PRERREQUISITO (no lo instala esto): Microsoft ODBC Driver 17/18 for SQL Server.
;
;  Solo x64. Se compila en GitHub Actions (backup.yml -> job installer).
; ============================================================================

#define MyAppName "FactuposBackup"
#define MyAppId "factupos-backup"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "Soporte Real SRL"
#define MyAppURL "https://soportereal.com"
#define MyAppExe "FactuposBackup.exe"
#define MyAppCli "FactuposBackupCLI.exe"

[Setup]
AppId={{A1F6C284-7B30-4D95-9E2C-6F8B1A4470E5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppId}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Factupos-Backup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExe}

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el Escritorio"; Flags: unchecked

[Files]
; Los .exe los genera el job build (PyInstaller); el workflow los copia junto
; al .iss. config.example.json + LEEME.txt vienen del repo (carpeta backup/).
Source: "{#MyAppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MyAppCli}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LEEME.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme
; config del equipo (servidor/clave): NO sobrescribir si ya existe.
Source: "..\config.example.json"; DestDir: "{app}"; DestName: "config.json"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; Permiso Modify al grupo Usuarios (SID *S-1-5-32-545) sobre la carpeta: la app
; guarda config.json, logs y el respaldo, y se auto-actualiza, sin pedir UAC.
Filename: "{sys}\icacls.exe"; Parameters: """{app}"" /grant *S-1-5-32-545:(OI)(CI)M /T"; \
    Flags: runhidden waituntilterminated; StatusMsg: "Configurando permisos..."

; Lanzar la GUI al terminar para que el admin configure el servidor SQL.
Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; \
    Description: "Abrir {#MyAppName} para configurar"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#MyAppExe}"; \
    Flags: runhidden; RunOnceId: "KillBackupGui"
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#MyAppCli}"; \
    Flags: runhidden; RunOnceId: "KillBackupCli"
