; The Windows installer, built by Inno Setup 6 out of the bundle PyInstaller wrote.
;
; Not run by hand: make_release.ps1 compiles it with the version and the bundle on the command line,
;
;     ISCC.exe /DAppVersion=0.1.0 /DBundleDir=<bundle> /O<output dir> firmauy-desktop.iss
;
; so this file holds no version of its own for anything to fall out of step with.
;
; Per user and without administrator rights by default, into %LOCALAPPDATA%\Programs, which is
; where the Linux install.sh goes too (~/.local, no root). Installing for every account is still
; there, on the first page or with /ALLUSERS, and then it goes to Program Files.

#ifndef AppVersion
  #error Falta /DAppVersion=x.y.z: make_release.ps1 lo pasa leyendo __version__.
#endif
#ifndef BundleDir
  #error Falta /DBundleDir=<directorio del bundle de PyInstaller>.
#endif

; The identity every platform shares: settings.APP_ID, the Linux desktop entry and the macOS
; bundle identifier. Here it is the installer's AppId, which names the uninstall entry and is what
; makes the next version an upgrade of this one rather than a second copy, and the AppUserModelID
; of the shortcut, which the running window sets on itself so the two are one taskbar button.
; Never change it: a new AppId is a different application to Windows.
#define AppIdentity "com.firmauy.firmauydesktop"
#define AppName "FirmaUY Desktop"
#define AppExe "firmauy-desktop.exe"
#define Repo "https://github.com/carlosplanchon/firmauy-desktop"

[Setup]
AppId={#AppIdentity}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
AppPublisherURL={#Repo}
AppSupportURL={#Repo}/issues
AppUpdatesURL={#Repo}/releases
AppCopyright=Copyright 2026 Carlos Andrés Planchón Prestes. Apache-2.0.
AppComments=Proyecto independiente, sin afiliación con AGESIC.
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription=Instalador de {#AppName}

PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto

; x64 only: the bundle is a 64-bit Python, and it is also why the PKCS#11 module it can load is the
; 64-bit gclib.dll. Windows 10 is the floor Python 3.14 itself sets.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

; An open copy holds its own files, and replacing a running bundle half way is how an upgrade
; leaves a mix of two versions. The Restart Manager asks it to close first.
CloseApplications=yes
RestartApplications=no

SetupIconFile=..\..\src\firmauy_desktop\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputBaseFilename=firmauy-desktop-{#AppVersion}-windows-x86_64-setup

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

; An upgrade replaces the bundle rather than merging into it, as install.sh does on Linux. Without
; this, a library the new version no longer ships stays behind in _internal, where the frozen
; interpreter can still find it. Nothing of the person's lives there: settings are in the registry
; and the activity record in %LOCALAPPDATA%.
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

; No file association, for the reason the Linux entry has no MimeType: the app opens no document
; handed to it on the command line, so "Abrir con" would start an empty window and drop the file.
[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppIdentity}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppIdentity}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Uninstalling removes what was installed and nothing else. The settings
; (HKCU\Software\firmauy\FirmaUY Desktop) and the activity record are the person's, and stay, which
; is what uninstall.sh does on Linux and what the README says.
