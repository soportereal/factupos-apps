; Instalador de Factupos-IA (Windows) — Inno Setup.
; Compilar por arquitectura:  ISCC.exe /DARCH=x64 factupos-ia.iss   (y /DARCH=x86)
#ifndef ARCH
  #define ARCH "x64"
#endif

#define MyAppName "Factupos-IA"
#define MyAppId "factupos-ia"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Soporte Real SRL"
#define MyAppURL "https://soportereal.com"
#define MyAppExeName "factupos-ia.exe"

[Setup]
AppId={{3F8C1A92-7B4D-4E11-9C2A-6D5E0F1A2B3C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppId}
DisableProgramGroupPage=yes
OutputDir=Output
; x64 (única arquitectura) -> nombre limpio Factupos-IA.exe; x86 conserva sufijo.
#if ARCH == "x64"
OutputBaseFilename=Factupos-IA
#else
OutputBaseFilename=Factupos-IA-{#ARCH}
#endif
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin
#if ARCH == "x64"
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; Flags: unchecked

[Files]
#if ARCH == "x64"
  Source: "Factupos-IA.exe"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
#else
  Source: "Factupos-IA-x86.exe"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
#endif

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Permiso "Modify" al grupo Usuarios (SID S-1-5-32-545) -> el auto-update reemplaza el .exe sin pedir UAC
Filename: "{sys}\icacls.exe"; Parameters: """{app}"" /grant *S-1-5-32-545:(OI)(CI)M /T"; \
    Flags: runhidden waituntilterminated; StatusMsg: "Configurando permisos de actualizacion..."
; Abrir al terminar
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillFactuposIA"
