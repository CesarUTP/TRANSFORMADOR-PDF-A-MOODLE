; installer.iss — Instalador de Windows para "Conversor a Moodle XML"
;
; Se compila con Inno Setup (gratis): https://jrsoftware.org/isdl.php
;   ISCC.exe installer.iss
;
; Requiere que antes exista dist\ConvertidorMoodle\ generado por build.py
; (PyInstaller) — build_windows.bat hace ambos pasos en orden automáticamente.

#define MyAppName "Conversor a Moodle XML"
#define MyAppVersion "1.0.0"
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
