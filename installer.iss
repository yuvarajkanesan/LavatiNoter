; Inno Setup script - run build.bat first (it produces dist\LavatiNoter\).
; The installer carries Lavati Softwares branding (wizard artwork, publisher); the app itself uses LavatiNoter's own icon.
#define AppName "LavatiNoter"
#define AppExe "LavatiNoter.exe"
#define AppGuid "{7B1F4E2A-5C93-4D68-A1E7-92D0C46B83F5}"
; build.bat passes the real version (/DAppVersion=...); the other defines let tools\make_test_installers.ps1 build
; throw-away "older" and "newer" installers for the upgrade / downgrade tests
#ifndef AppVersion
  #define AppVersion "0.2"
#endif
#ifndef PayloadDir
  #define PayloadDir "dist\LavatiNoter"
#endif
#ifndef OutName
  #define OutName "LavatiNoter-Setup"
#endif
#ifndef OutDir
  #define OutDir "dist"
#endif

[Setup]
AppId={{7B1F4E2A-5C93-4D68-A1E7-92D0C46B83F5}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Lavati Softwares
AppCopyright=Copyright (c) 2026 Lavati Softwares (MIT License)
LicenseFile=installer\EULA.txt
#ifdef Sign
SignTool=lavatisign $f
SignedUninstaller=yes
#endif
VersionInfoCompany=Lavati Softwares
VersionInfoDescription=LavatiNoter Setup
VersionInfoProductName=LavatiNoter
WizardSizePercent=115
DisableProgramGroupPage=yes
AllowNoIcons=yes
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=assets\lavatinoter.ico
OutputDir={#OutDir}
OutputBaseFilename={#OutName}
Compression=lzma2/ultra64
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
SolidCompression=yes
WizardStyle=modern
WizardImageFile=installer\wizard-large.bmp
WizardSmallImageFile=installer\wizard-small.bmp
InfoBeforeFile=installer\welcome.txt
DisableWelcomePage=no
DisableReadyPage=no
ShowLanguageDialog=no
SetupMutex=LavatiNoterSetupMutex
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
DirExistsWarning=no
UsePreviousTasks=yes
UninstallDisplayName={#AppName}
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Messages]
WelcomeLabel1=Welcome to LavatiNoter
WelcomeLabel2=This will install LavatiNoter {#AppVersion} on your computer.%n%nIt is recommended that you close other applications before continuing.
FinishedHeadingLabel=LavatiNoter is ready
FinishedLabel=Setup has finished installing LavatiNoter. Start it from the Start menu or the desktop shortcut.

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "contextmenu"; Description: "Add ""Edit with LavatiNoter"" to the Explorer right-click menu"; GroupDescription: "Integration:"
Name: "openwith"; Description: "List LavatiNoter in ""Open with"" for text, code and log files"; GroupDescription: "Integration:"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "installer\THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "installer\EULA.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Explorer right-click entry for every file, and for folders (opens the folder as the workspace); both removed on uninstall
Root: HKCU; Subkey: "Software\Classes\*\shell\LavatiNoter"; ValueType: string; ValueName: ""; ValueData: "Edit with {#AppName}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\LavatiNoter"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe}"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\LavatiNoter\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\LavatiNoter"; ValueType: string; ValueName: ""; ValueData: "Open folder in {#AppName}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\LavatiNoter"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe}"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\LavatiNoter\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: contextmenu
; "Open with" list: a ProgID plus an OpenWithProgids entry per extension (the default program is never changed)
Root: HKCU; Subkey: "Software\Classes\LavatiNoter.File"; ValueType: string; ValueName: ""; ValueData: "{#AppName} document"; Flags: uninsdeletekey; Tasks: openwith
Root: HKCU; Subkey: "Software\Classes\LavatiNoter.File\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: openwith
Root: HKCU; Subkey: "Software\Classes\LavatiNoter.File\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: openwith
#define ExtReg(Ext) "Root: HKCU; Subkey: ""Software\Classes\." + Ext + "\OpenWithProgids""; ValueType: string; ValueName: ""LavatiNoter.File""; ValueData: """"; Flags: uninsdeletevalue; Tasks: openwith"
#emit ExtReg("txt")
#emit ExtReg("log")
#emit ExtReg("md")
#emit ExtReg("json")
#emit ExtReg("xml")
#emit ExtReg("yaml")
#emit ExtReg("yml")
#emit ExtReg("ini")
#emit ExtReg("cfg")
#emit ExtReg("csv")
#emit ExtReg("py")
#emit ExtReg("js")
#emit ExtReg("ts")
#emit ExtReg("css")
#emit ExtReg("html")
#emit ExtReg("sql")
#emit ExtReg("bat")
#emit ExtReg("ps1")
#emit ExtReg("sh")
#emit ExtReg("ts")
#emit ExtReg("tsx")
#emit ExtReg("jsx")
#emit ExtReg("java")
#emit ExtReg("cs")
#emit ExtReg("c")
#emit ExtReg("cpp")
#emit ExtReg("h")
#emit ExtReg("go")
#emit ExtReg("rs")
#emit ExtReg("php")
#emit ExtReg("rb")
#emit ExtReg("lua")
#emit ExtReg("toml")
#emit ExtReg("diff")
#emit ExtReg("patch")
#emit ExtReg("kt")
#emit ExtReg("swift")
#emit ExtReg("scss")
#emit ExtReg("vue")

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[InstallDelete]
; a clean update: remove files of the previous version that the new one no longer ships
; (the uninstaller, unins000.*, is left alone: it is replaced at the end of the install)
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\LavatiNoter*.exe"
Type: files; Name: "{app}\*.txt"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  KeepData: Boolean;

const
  UninstKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#AppGuid}_is1';

procedure DeleteTree(const Path: String);
begin
  if DirExists(Path) then DelTree(Path, True, True, True);
end;

function HasParam(const Name: String): Boolean;
var
  i: Integer;
begin
  Result := False;
  for i := 1 to ParamCount do
    if CompareText(ParamStr(i), Name) = 0 then Result := True;
end;

{ Stops every process that runs from the install folder (LavatiNoter.exe) and nothing else:
  other copies of LavatiNoter elsewhere on the computer are left alone. }
procedure StopProcessesIn(const Dir: String);
var
  Code: Integer;
  Folder, Params: String;
begin
  Folder := Dir;
  StringChangeEx(Folder, '''', '''''', True);                      { a ' in the path must be doubled inside a PowerShell string }
  Params := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$d = ''' + Folder + '\''; ' +
    'Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($d, [StringComparison]::OrdinalIgnoreCase) -and $_.Name -notlike ''unins*'' } | ' +
    'ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params, '', SW_HIDE, ewWaitUntilTerminated, Code) then
    Exec(ExpandConstant('{cmd}'), '/c taskkill /F /IM {#AppExe}', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(400);                                                     { let Windows release the file locks }
end;

{ --- versions: refuse to replace a newer install with an older one by accident --- }
function VersionPart(var S: String): Integer;
var
  P: Integer;
begin
  P := Pos('.', S);
  if P = 0 then
  begin
    Result := StrToIntDef(S, 0);
    S := '';
  end else
  begin
    Result := StrToIntDef(Copy(S, 1, P - 1), 0);
    S := Copy(S, P + 1, Length(S));
  end;
end;

function CompareVersions(A, B: String): Integer;
var
  i, X, Y: Integer;
begin
  Result := 0;
  for i := 1 to 4 do
  begin
    X := VersionPart(A);
    Y := VersionPart(B);
    if X <> Y then
    begin
      if X > Y then Result := 1 else Result := -1;
      Exit;
    end;
  end;
end;

function InstalledVersion(): String;
begin
  Result := '';
  if not RegQueryStringValue(HKCU, UninstKey, 'DisplayVersion', Result) then
    if not RegQueryStringValue(HKLM, UninstKey, 'DisplayVersion', Result) then
      Result := '';
end;

function InitializeSetup(): Boolean;
var
  Old: String;
begin
  Result := True;
  Old := InstalledVersion();
  if (Old <> '') and (CompareVersions(Old, '{#AppVersion}') > 0) then
  begin
    if WizardSilent then
      Result := HasParam('/ALLOWDOWNGRADE')                       { silent: refuse unless explicitly allowed (exit code 6) }
    else
      Result := MsgBox('LavatiNoter ' + Old + ' is already installed. It is newer than this setup (' + '{#AppVersion}' + ').' + #13#10 + #13#10 +
        'Install the older version anyway? Your settings are kept.',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  end;
end;

{ Windows asks a running LavatiNoter to close first (CloseApplications); this removes whatever is still running from
  the folder so the files can be replaced. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if DirExists(ExpandConstant('{app}')) then
    StopProcessesIn(ExpandConstant('{app}'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if not KeepData then
      DeleteTree(ExpandConstant('{userappdata}\LavatiNoter'));
    { the uninstaller lives inside the install folder, so remove it a moment after it exits.
      Only our own files go, and rmdir without /s only removes the folder when it is empty, so a
      shared folder chosen at install time is never wiped. }
    Exec(ExpandConstant('{cmd}'), '/c ping 127.0.0.1 -n 3 >nul & del /q "' + ExpandConstant('{app}') + '\unins*.*" & rmdir "' + ExpandConstant('{app}') + '"', '', SW_HIDE, ewNoWait, Code);
  end;
end;

{ Your settings and unsaved-work backups are kept unless you say otherwise:
  interactive uninstall asks (default: keep); a silent uninstall keeps them unless started with /REMOVEDATA. }
function InitializeUninstall(): Boolean;
begin
  StopProcessesIn(ExpandConstant('{app}'));                         { a running copy keeps its files locked }
  if UninstallSilent then
    KeepData := not HasParam('/REMOVEDATA')
  else
    KeepData := MsgBox('Keep your settings and the backup of your unsaved documents?' + #13#10 + #13#10 +
      'Yes (recommended) keeps them for a future install. No removes all LavatiNoter data from this computer.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON1) = IDYES;
  Result := True;
end;
