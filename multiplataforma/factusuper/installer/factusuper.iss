; ============================================================================
;  FactuSuper (app nativa) — Instalador de Windows (Inno Setup 6) · caso #3957
;  Se publica en la lista de «Aplicaciones FactuPOS» (soportereal.com/descarga/catalogo.php).
;
;  - Sin permiso de administrador, en la carpeta del usuario
;    ({localappdata}\Programs\FactuSuper): se podrá actualizar sola sin pedir permiso.
;  - Flutter en Windows = SOLO 64 bits y Windows 10 o más nuevo: en otro equipo el
;    instalador lo dice claro y no instala nada.
;  - La configuración (llave) y los datos bajados NO están acá: viven en la carpeta de
;    datos de la app, así que reinstalar o actualizar no pide la llave de nuevo.
;
;  Se COMPILA solo en GitHub Actions — .github/workflows/factusuper.yml
;  (la versión llega con /DMyAppVersion=… desde el pubspec.yaml).
; ============================================================================

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppName "FactuSuper"
#define MyAppPublisher "Soporte Real SRL"
#define MyAppURL "https://soportereal.com"
#define MyAppExeName "factusuper.exe"

[Setup]
AppId={{3957F5A1-6C2E-4B8D-9A17-0E5D4C3B2A91}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=Output
OutputBaseFilename=FactuSuper-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\windows\runner\resources\app_icon.ico
CloseApplications=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
; La carpeta Release completa de Flutter (exe + DLLs + data\), copiada acá por el workflow.
Source: "app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent
