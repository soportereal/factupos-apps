; ============================================================================
;  Aplicaciones FactuPOS — Instalador (Inno Setup 6)   (idea del dueño, 25-nov-2026, sale del #3907)
;  Una app de Windows para descargar e instalar las demás apps de FactuPOS sin
;  pasar por el navegador.
;
;  - Se instala SIN permiso de administrador, en la carpeta del usuario
;    ({localappdata}\Programs\Aplicaciones FactuPOS): así la app se puede
;    actualizar sola sin pedir permiso. Lo que pide administrador son los
;    instaladores de las otras apps, y esos lo piden ellos mismos.
;  - Deja accesos en el Escritorio y en el menú Inicio.
;  - Al actualizarse sola corre en /SILENT y se vuelve a abrir (ver [Run]).
;
;  Se COMPILA solo en GitHub Actions — .github/workflows/aplicaciones.yml.
; ============================================================================

#define MyAppName "Aplicaciones FactuPOS"
#define MyAppVersion "1.0.3"
#define MyAppPublisher "Soporte Real SRL"
#define MyAppURL "https://soportereal.com"
#define MyAppExeName "Aplicaciones-FactuPOS.exe"

[Setup]
AppId={{7E2B9C41-3D58-4F0A-9B6E-21A4C8D5F903}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=Aplicaciones-FactuPOS-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=aplicaciones.ico
CloseApplications=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
; Instalación normal: casilla «Abrir ahora» al terminar.
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent
; Actualización silenciosa (la lanza la propia app): se reabre sola.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent

[Code]
// 1.0.3: la app se actualiza sola lanzando este instalador y cerrándose. Antes el instalador
// arrancaba mientras la app todavía no había terminado de cerrarse y no podía reemplazar el .exe.
// La app tiene abierto el candado "FactuPOS-Aplicaciones-Abierta" (MUTEX) mientras corre:
// acá se espera hasta 20 s a que lo suelte antes de copiar nada.
// Las versiones 1.0.0-1.0.2 no tienen ese candado: para ellas se espera a que el .exe se pueda
// RENOMBRAR (si está en uso, Windows no deja). Se renombra y se devuelve a su nombre enseguida.
function ExeLibre(): Boolean;
var
  exe, tmp: String;
begin
  exe := ExpandConstant('{localappdata}\Programs\{#MyAppName}\{#MyAppExeName}');
  tmp := exe + '.prueba';
  if not FileExists(exe) then
  begin
    Result := True;
    exit;
  end;
  Result := RenameFile(exe, tmp);
  if Result then
    RenameFile(tmp, exe);
end;

function InitializeSetup(): Boolean;
var
  i: Integer;
begin
  i := 0;
  while (CheckForMutexes('FactuPOS-Aplicaciones-Abierta') or not ExeLibre()) and (i < 40) do
  begin
    Sleep(500);
    i := i + 1;
  end;
  Result := True;
end;
