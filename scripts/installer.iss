; Instalador Windows para Maker -> ELEGOO (Inno Setup 6)
#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\MakerElegoo"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{9D2C8A5A-7B12-4A4E-8F7E-2E31D94D4B01}
AppName=Maker -> ELEGOO
AppVersion={#AppVersion}
AppPublisher=brenohs244
AppPublisherURL=https://github.com/brenohs244/3mf-translator
AppSupportURL=https://github.com/brenohs244/3mf-translator/issues
AppUpdatesURL=https://github.com/brenohs244/3mf-translator/releases
DefaultDirName={localappdata}\Programs\MakerElegoo
DefaultGroupName=Maker ELEGOO
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=MakerElegoo-Setup-v{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
CloseApplicationsFilter=MakerElegoo.exe
RestartApplications=no
UninstallDisplayName=Maker -> ELEGOO ({#AppVersion})

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Limpa arquivos antigos do --internal quando atualizar versão
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Maker ELEGOO"; Filename: "{app}\MakerElegoo.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Maker ELEGOO"; Filename: "{app}\MakerElegoo.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\MakerElegoo.exe"; Description: "{cm:LaunchProgram,Maker -> ELEGOO}"; Flags: nowait postinstall skipifsilent
