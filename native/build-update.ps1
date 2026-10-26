param([Parameter(Mandatory=$true)][string]$Inno)
$ErrorActionPreference = 'Stop'
$captionRoot = Split-Path -Parent $PSScriptRoot
$captionDll = Join-Path $captionRoot 'build\obs-bilingue.dll'
if (!(Test-Path -LiteralPath $captionDll -PathType Leaf)) { throw 'Compila primero native/build.ps1' }
$captionHash = (Get-FileHash -LiteralPath $captionDll -Algorithm SHA256).Hash.ToLowerInvariant()
& $Inno "/DNativeDll=$captionDll" "/DNativeHash=$captionHash" (Join-Path $captionRoot 'installer\native-update.iss')
if ($LASTEXITCODE -ne 0) { throw 'Fallo la compilacion del actualizador nativo' }
