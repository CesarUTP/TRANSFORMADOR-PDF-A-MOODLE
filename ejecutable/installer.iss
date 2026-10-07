; installer.iss — Instalador de Windows para "Cátedra"
;
; Se compila con Inno Setup (gratis): https://jrsoftware.org/isdl.php
;   ISCC.exe installer.iss
;
; Requiere que antes exista dist\Catedra\ generado por build.py
; (PyInstaller) — build_windows.bat hace ambos pasos en orden automáticamente.

#define MyAppName "Cátedra"
#define MyAppVersion "2.6"
#define MyAppPublisher "César González y Vicente Urriola"
#define MyAppExeName "Catedra.exe"

[Setup]
AppId={{F53E25B8-4044-4973-BC3B-D89355E4CD34}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=Output
OutputBaseFilename=Catedra_Setup
SetupIconFile=assets\Icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el Escritorio"; GroupDescription: "Accesos directos adicionales:"

[Files]
Source: "dist\Catedra\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Hasta la 2.3 la app se llamaba «Conversor a Moodle XML» (ConvertidorMoodle.exe). Si se instala sobre esa versión
; (el AppId es el mismo, así que Windows lo trata como una actualización) se quitan el .exe y los accesos directos
; viejos para que no queden dos íconos, uno apuntando a un programa que ya no se actualiza.
Type: files; Name: "{app}\ConvertidorMoodle.exe"
Type: files; Name: "{autodesktop}\Conversor a Moodle XML.lnk"
Type: filesandordirs; Name: "{autoprograms}\Conversor a Moodle XML"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
// Al desinstalar: el historial de conversiones, la clave de la API de Gemini
// (clave.dat) y los registros viven en %LOCALAPPDATA%\ConversorMoodleXML (el nombre de la
// carpeta no cambió al renombrar la app, para no perder los datos de nadie), no
// en la carpeta del programa, así que desinstalar no los tocaba y una
// reinstalación volvía a encontrar la clave. Se pregunta; la respuesta por
// defecto es NO (conservarlos), y en una desinstalación silenciosa no se
// borra nada.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Datos: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Datos := ExpandConstant('{localappdata}\ConversorMoodleXML');
    if DirExists(Datos) and not UninstallSilent() then
      if MsgBox('¿Borrar también tus datos de Cátedra?' + #13#10 + #13#10 +
                '• El historial de conversiones' + #13#10 +
                '• Tu API de Gemini guardada' + #13#10 + #13#10 +
                'Si vas a reinstalar la aplicación y quieres conservarlos, elige «No».',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Datos, True, True, True);
  end;
end;
