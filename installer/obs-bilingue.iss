#ifndef Payload
  #error Define Payload with the prepared offline payload directory
#endif
#define Version "0.4.0"

[Setup]
AppId={{64F92710-4094-4AC3-A8BF-FDDC056AE566}
AppName=OBS Bilingüe
AppVersion={#Version}
AppPublisher=OBS Bilingüe contributors
AppPublisherURL=https://github.com/Kitsunp/obs-bilingue
AppSupportURL=https://github.com/Kitsunp/obs-bilingue/issues
DefaultDirName={commonappdata}\obs-studio\plugins\obs-bilingue
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableWelcomePage=yes
ShowLanguageDialog=no
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=OBS-Bilingue-{#Version}-Windows-x64-Setup
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=commandline
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=2
WizardStyle=modern
CloseApplications=no
RestartApplications=no
UninstallDisplayName=OBS Bilingüe
UninstallFilesDir={app}\uninstall
SetupLogging=no

[Languages]
Name: spanish; MessagesFile: compiler:Languages\Spanish.isl
Name: english; MessagesFile: compiler:Default.isl

[Types]
Name: full; Description: Subtítulos y traducción opcional al español
Name: compact; Description: Solo subtítulos
Name: custom; Description: Personalizada; Flags: iscustom

[Components]
Name: core; Description: Fuente OBS, motor y modelo de subtítulos; Types: full compact custom; Flags: fixed
Name: translation; Description: Modelo y runtime de traducción al español; Types: full

[Files]
Source: "preflight.ps1"; Flags: dontcopy
#include Payload + "/files.iss"
Source: "https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b/resolve/ea30d66debe3740a08b573244286791d423d6b3e/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf"; DestName: "nemotron-3.5-asr-streaming-0.6b.q8_0.gguf"; DestDir: "{app}\data\app\models\nemo-native"; Flags: external download ignoreversion; Hash: "3fc991d3badad7277c11030a7519832cddaf2057aafed6d4b25147e953a070b1"; ExternalSize: 742090464; Components: core; Check: NeedModel('models\nemo-native\nemotron-3.5-asr-streaming-0.6b.q8_0.gguf', '3fc991d3badad7277c11030a7519832cddaf2057aafed6d4b25147e953a070b1')
Source: "https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/resolve/a0c709d9fac510f2c807aa3af52872340dc37a4a/Hy-MT2-1.8B-Q4_K_M.gguf"; DestName: "Hy-MT2-1.8B-Q4_K_M.gguf"; DestDir: "{app}\data\app\models"; Flags: external download ignoreversion; Hash: "dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699"; ExternalSize: 1133080448; Components: translation; Check: NeedModel('models\Hy-MT2-1.8B-Q4_K_M.gguf', 'dc5f44fcf1fa496ee7ad725982c0c8c553a4de00259b53af84c4b89fb0c06699')

[UninstallDelete]
Type: files; Name: "{app}\data\runtime.json"
Type: files; Name: "{app}\data\app\config.json"

[Code]
var KeepFiles, ReplaceFiles: TStringList;
    PostInstallFailed: Boolean;

procedure InitializeWizard;
begin
  KeepFiles := TStringList.Create;
  ReplaceFiles := TStringList.Create;
end;

function NeedTargetFile(const RelativePath, ExpectedHash: String): Boolean;
var FileName, Key: String;
begin
  if ExpectedHash = '' then RaiseException('Falta el checksum de un archivo del paquete.');
  Key := RelativePath + '@' + ExpectedHash;
  if KeepFiles.IndexOf(Key) >= 0 then begin
    Result := False;
    Exit;
  end;
  if ReplaceFiles.IndexOf(Key) >= 0 then begin
    Result := True;
    Exit;
  end;
  FileName := AddBackslash(ExpandConstant('{app}')) + RelativePath;
  Result := not FileExists(FileName);
  if not Result then
    Result := CompareText(GetSHA256OfFile(FileName), ExpectedHash) <> 0;
  if Result then ReplaceFiles.Add(Key) else KeepFiles.Add(Key);
end;

function NeedModel(const RelativePath, ExpectedHash: String): Boolean;
begin
  Result := NeedTargetFile('data\app\' + RelativePath, ExpectedHash);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  Result := '';
  ExtractTemporaryFile('preflight.ps1');
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\preflight.ps1') +
    '" -PluginRoot "' + ExpandConstant('{app}') + '"', '', SW_HIDE, ewWaitUntilTerminated, Code) then begin
    Result := 'No se pudo comprobar la compatibilidad. No se instalaron archivos del plugin.';
    Exit;
  end;
  case Code of
    0: Result := '';
    20, 21: Result := 'Cierra OBS y espera a que termine el motor del plugin antes de instalar. No se cerraran procesos automaticamente.';
    40: Result := 'Se requiere Windows x64 para este paquete.';
  else
    Result := 'Se requiere una GPU NVIDIA y un controlador compatible con CUDA 13 o superior. El instalador no cambia el controlador ni CUDA del sistema.';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer;
begin
  if CurStep = ssPostInstall then begin
    WizardForm.StatusLabel.Caption := 'Verificando archivos y configurando el motor local...';
    PostInstallFailed := True;
    if not Exec(ExpandConstant('{app}\data\app\python\python.exe'),
      '-B "' + ExpandConstant('{app}\data\app\configure_install.py') + '" --plugin-root "' + ExpandConstant('{app}') + '"',
      ExpandConstant('{app}\data\app'), SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
      RaiseException('La verificación del motor falló. Reinstala el paquete antes de usar la fuente.');
    PostInstallFailed := False;
  end;
end;

function GetCustomSetupExitCode: Integer;
begin
  if PostInstallFailed then Result := 90 else Result := 0;
end;
