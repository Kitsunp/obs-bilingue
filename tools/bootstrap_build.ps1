param([switch]$WithoutInstaller)
$ErrorActionPreference = 'Stop'
$captionRoot = Split-Path -Parent $PSScriptRoot
$captionTools = Join-Path $captionRoot '.build\tools'
New-Item -ItemType Directory -Force -Path $captionTools | Out-Null

function Get-CheckedFile([string]$Url, [string]$Path, [string]$Sha256) {
    if ((Test-Path -LiteralPath $Path) -and
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower() -eq $Sha256) { return }
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Path
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower() -ne $Sha256) {
        throw 'Build-tool download checksum mismatch'
    }
}

$captionZigZip = Join-Path $captionTools 'zig.zip'
Get-CheckedFile 'https://ziglang.org/download/0.15.2/zig-x86_64-windows-0.15.2.zip' $captionZigZip `
    '3a0ed1e8799a2f8ce2a6e6290a9ff22e6906f8227865911fb7ddedc3cc14cb0c'
$captionZig = Join-Path $captionTools 'zig-x86_64-windows-0.15.2\zig.exe'
if (!(Test-Path -LiteralPath $captionZig)) { Expand-Archive -LiteralPath $captionZigZip -DestinationPath $captionTools }
$captionObs = Join-Path $captionTools 'obs-studio'
$captionObsCommit = 'ba2f32bdf791005443988a4955e963663e16b1ed'
if (!(Test-Path -LiteralPath (Join-Path $captionObs '.git'))) {
    git init $captionObs
    if ($LASTEXITCODE) { throw 'Cannot initialize OBS header checkout' }
    git -C $captionObs remote add origin https://github.com/obsproject/obs-studio.git
    git -C $captionObs sparse-checkout init --cone
    git -C $captionObs sparse-checkout set libobs
    git -C $captionObs fetch --depth 1 origin $captionObsCommit
    if ($LASTEXITCODE) { throw 'Cannot fetch pinned OBS headers' }
    git -C $captionObs checkout --detach FETCH_HEAD
    if ($LASTEXITCODE) { throw 'Cannot check out pinned OBS headers' }
}
if ((git -C $captionObs rev-parse HEAD) -ne $captionObsCommit) { throw 'Unexpected OBS header revision' }
& (Join-Path $captionRoot 'native\build.ps1') -Zig $captionZig -ObsHeaders (Join-Path $captionObs 'libobs')
if ($WithoutInstaller) { return }

$captionInnoSetup = Join-Path $captionTools 'innosetup-6.7.3.exe'
Get-CheckedFile 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe' $captionInnoSetup `
    '9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732'
$captionSignature = Get-AuthenticodeSignature -LiteralPath $captionInnoSetup
if ($captionSignature.Status -ne 'Valid' -or $captionSignature.SignerCertificate.Subject -notlike '*Pyrsys*') {
    throw 'Inno Setup publisher verification failed'
}
$captionInno = Join-Path $captionTools 'inno'
if (!(Test-Path -LiteralPath (Join-Path $captionInno 'ISCC.exe'))) {
    $captionProcess = Start-Process -FilePath $captionInnoSetup -WindowStyle Hidden -PassThru -Wait `
        -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', ('/DIR="' + $captionInno + '"'))
    if ($captionProcess.ExitCode) { throw 'Inno Setup preparation failed' }
}
uv python install 3.12.14
if ($LASTEXITCODE) { throw 'Python preparation failed' }
$captionPython = (uv python find 3.12.14).Trim()
& $captionPython (Join-Path $PSScriptRoot 'build_installer.py') --python-root (Split-Path -Parent $captionPython)
if ($LASTEXITCODE) { throw 'Offline payload build failed' }
& (Join-Path $captionInno 'ISCC.exe') ('/DPayload=' + (Join-Path $captionRoot '.build\payload')) `
    (Join-Path $captionRoot 'installer\obs-bilingue.iss')
if ($LASTEXITCODE) { throw 'Installer compilation failed' }
$captionInstaller = Get-Item -LiteralPath (Join-Path $captionRoot 'dist\OBS-Bilingue-0.4.0-Windows-x64-Setup.exe')
if ($captionInstaller.Length -ge 2147483648) { throw 'Installer exceeds GitHub release asset limit' }
$captionDigest = (Get-FileHash -LiteralPath $captionInstaller.FullName -Algorithm SHA256).Hash.ToLower()
[System.IO.File]::WriteAllText((Join-Path $captionRoot 'dist\SHA256SUMS.txt'),
    ($captionDigest + '  ' + $captionInstaller.Name + "`n"), [System.Text.UTF8Encoding]::new($false))
