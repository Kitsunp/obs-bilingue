#ifndef NativeDll
  #error Define NativeDll with the compiled plugin DLL
#endif
#ifndef NativeHash
  #error Define NativeHash with the compiled DLL SHA256
#endif
#define Version "0.4.2"

[Setup]
AppId={{64F92710-4094-4AC3-A8BF-FDDC056AE566}
AppName=OBS Bilingüe - actualización de audio
AppVersion={#Version}
AppPublisher=OBS Bilingüe contributors
AppPublisherURL=https://github.com/Kitsunp/obs-bilingue
DefaultDirName={commonappdata}\obs-studio\plugins\obs-bilingue
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
DisableWelcomePage=yes
ShowLanguageDialog=no
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=OBS-Bilingue-{#Version}-Windows-x64-Update
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
Uninstallable=no
CreateUninstallRegKey=no
SetupLogging=no

[Languages]
Name: spanish; MessagesFile: compiler:Languages\Spanish.isl
Name: english; MessagesFile: compiler:Default.isl

[Files]
Source: "native-update-preflight.ps1"; Flags: dontcopy
Source: "{#NativeDll}"; DestDir: "{app}"; Flags: ignoreversion; Check: NeedNativeDll('obs-bilingue.dll')
Source: "{#NativeDll}"; DestDir: "{app}\bin\64bit"; Flags: ignoreversion; Check: NeedNativeDll('bin\64bit\obs-bilingue.dll')

[Code]
var PostInstallFailed: Boolean;

function NeedNativeDll(const RelativePath: String): Boolean;
var FileName: String;
begin
  FileName := AddBackslash(ExpandConstant('{app}')) + RelativePath;
  Result := not FileExists(FileName);
  if not Result then
    Result := CompareText(GetSHA256OfFile(FileName), '{#NativeHash}') <> 0;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  Result := '';
  ExtractTemporaryFile('native-update-preflight.ps1');
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\native-update-preflight.ps1') +
    '" -PluginRoot "' + ExpandConstant('{app}') + '"', '', SW_HIDE, ewWaitUntilTerminated, Code) then begin
    Result := 'No se pudo comprobar la instalación. No se actualizaron archivos.';
    Exit;
  end;
  case Code of
    0: Result := '';
    20: Result := 'Cierra OBS antes de actualizar. El actualizador no cierra OBS ni interrumpe emisiones automáticamente.';
    30: Result := 'Selecciona la carpeta de una instalación existente de OBS Bilingüe. Esta actualización solo contiene el plugin nativo.';
    40: Result := 'Se requiere Windows x64.';
  else
    Result := 'La comprobación falló. No se actualizaron archivos.';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    PostInstallFailed := True;
    if (CompareText(GetSHA256OfFile(ExpandConstant('{app}\obs-bilingue.dll')), '{#NativeHash}') <> 0) or
       (CompareText(GetSHA256OfFile(ExpandConstant('{app}\bin\64bit\obs-bilingue.dll')), '{#NativeHash}') <> 0) then
      RaiseException('No se pudo verificar el plugin actualizado. Repite la actualización con OBS cerrado.');
    PostInstallFailed := False;
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  if PostInstallFailed then Result := 90 else Result := 0;
end;

procedure InitializeWizard;
begin
  WizardForm.FinishedLabel.Caption := 'Plugin actualizado. Abre OBS y, en las propiedades de la fuente de subtítulos, elige «Mezcla del directo de OBS (escenas, microfono y escritorio)» para capturar el audio de las escenas.';
end;
