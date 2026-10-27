; Unsigned Inno Setup installer for the PyInstaller bundle.
; Compiled by windows/build-windows.sh.
;
; Defines (passed by ISCC):
;   AppVersion    - dotted version, example: 4.0.2
;   VersionLabel  - release label, example: v4.0.2 or ci12
;   RepoRoot      - repository root, no trailing backslash
;   BundleDir     - the PyInstaller output folder holding TVHplayer.exe
;   OutputDir     - where the installer goes
;   IconFile      - the .ico file

[Setup]
; Keep this AppId: Windows recognises updates and uninstalls by it.
AppId={{DF9C0275-D701-4B01-B063-24AE0BCDC83C}
AppName=TVHplayer
AppVersion={#AppVersion}
AppVerName=TVHplayer {#AppVersion}
AppPublisher=mFat
AppPublisherURL=https://github.com/mfat/tvhplayer
AppSupportURL=https://github.com/mfat/tvhplayer/issues
AppUpdatesURL=https://github.com/mfat/tvhplayer/releases
DefaultDirName={autopf}\TVHplayer
DefaultGroupName=TVHplayer
DisableProgramGroupPage=yes
LicenseFile={#RepoRoot}\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=tvhplayer-{#VersionLabel}-windows-x86_64-setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\TVHplayer.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Installs for the current user without asking for administrator rights; the
; dialog offers an install for all users.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
ChangesAssociations=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RepoRoot}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

; A new version replaces the program files; settings and logs stay in AppData.
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\TVHplayer"; Filename: "{app}\TVHplayer.exe"
Name: "{autodesktop}\TVHplayer"; Filename: "{app}\TVHplayer.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TVHplayer.exe"; Description: "Launch TVHplayer"; Flags: nowait postinstall skipifsilent
