; installer.iss — Instalador de Windows para "Conversor a Moodle XML"
;
; Se compila con Inno Setup (gratis): https://jrsoftware.org/isdl.php
;   ISCC.exe installer.iss
;
; Requiere que antes exista dist\ConvertidorMoodle\ generado por build.py
; (PyInstaller) — build_windows.bat hace ambos pasos en orden automáticamente.

#define MyAppName "Conversor a Moodle XML"
#define MyAppVersion "1.3.0"
#define MyAppPublisher "César González y Vicente Urriola"
#define MyAppExeName "ConvertidorMoodle.exe"

[Setup]
AppId={{F53E25B8-4044-4973-BC3B-D89355E4CD34}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=Output
OutputBaseFilename=ConversorMoodleXML_Setup
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
Source: "dist\ConvertidorMoodle\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
// Al desinstalar: el historial de conversiones, la clave de la API de Gemini
// (clave.dat) y los registros viven en %LOCALAPPDATA%\ConversorMoodleXML, no
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
      if MsgBox('¿Borrar también tus datos del Conversor a Moodle XML?' + #13#10 + #13#10 +
                '• El historial de conversiones' + #13#10 +
                '• Tu API de Gemini guardada' + #13#10 + #13#10 +
                'Si vas a reinstalar la aplicación y quieres conservarlos, elige «No».',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Datos, True, True, True);
  end;
end;
