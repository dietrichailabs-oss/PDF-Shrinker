#define MyAppName "PDF Shrinker"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "Dietrich AI Labs"
#define MyAppExeName "PDF_Shrinker.exe"
#define MyProjectDir SourcePath

[Setup]
AppId={{E805CE8A-5BFD-4DB9-B0F4-9CA58FA0CF96}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion=1.0.1.0
VersionInfoProductVersion=1.0.1.0
VersionInfoProductName={#MyAppName}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Local PDF compression utility
DefaultDirName={userdesktop}\Marks Apps\PDF Shrinker
DefaultGroupName=Marks Apps\PDF Shrinker
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#MyProjectDir}\Release
OutputBaseFilename=PDF_Shrinker_Setup_1.0.1
SetupIconFile={#MyProjectDir}\pdf_shrinker.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
CreateUninstallRegKey=yes
Uninstallable=yes

[Files]
Source: "{#MyProjectDir}\dist\PDF_Shrinker.exe"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\PDF Shrinker"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Comment: "Compress PDF files"
Name: "{group}\PDF Shrinker"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\Uninstall PDF Shrinker"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch PDF Shrinker"; Flags: nowait postinstall skipifsilent
