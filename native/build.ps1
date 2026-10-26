param(
    [Parameter(Mandatory=$true)][string]$Zig,
    [Parameter(Mandatory=$true)][string]$ObsHeaders,
    [switch]$DebugSymbols
)
$ErrorActionPreference = 'Stop'
$captionRoot = Split-Path -Parent $PSScriptRoot
$captionBuild = Join-Path $captionRoot 'build'
$captionDebugFlags = @()
if ($DebugSymbols) { $captionDebugFlags = @('-g') }
New-Item -ItemType Directory -Force -Path $captionBuild | Out-Null
@'
#pragma once
#define OBS_DATA_PATH "data"
#define OBS_PLUGIN_PATH "obs-plugins"
#define OBS_PLUGIN_DESTINATION "obs-plugins/64bit"
#define OBS_RELEASE_CANDIDATE 0
#define OBS_BETA 0
'@ | Set-Content -LiteralPath (Join-Path $captionBuild 'obsconfig.h') -Encoding utf8
& $Zig dlltool -m i386:x86-64 -d (Join-Path $PSScriptRoot 'obs.def') -l (Join-Path $captionBuild 'obs.lib')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear la libreria de importacion OBS' }
& $Zig cc -shared -O2 @captionDebugFlags "-ffile-prefix-map=$captionRoot=." "-ffile-prefix-map=$ObsHeaders=obs-headers" -Wall -Wextra -Werror -std=c11 -target x86_64-windows-gnu `
    "-I$ObsHeaders" "-I$captionBuild" (Join-Path $PSScriptRoot 'plugin.c') `
    (Join-Path $PSScriptRoot 'subtitle-source.c') `
    (Join-Path $PSScriptRoot 'program-audio.c') `
    (Join-Path $PSScriptRoot 'scene-audio.c') `
    (Join-Path $PSScriptRoot 'routing-controls.c') `
    (Join-Path $PSScriptRoot 'source-audio.c') `
    (Join-Path $PSScriptRoot 'source-choice.c') `
    (Join-Path $PSScriptRoot 'engine-runtime.c') (Join-Path $PSScriptRoot 'language-rules.c') `
    (Join-Path $PSScriptRoot 'style-preview.c') `
    (Join-Path $captionBuild 'obs.lib') -lws2_32 -lshell32 -luser32 -lole32 `
    -o (Join-Path $captionBuild 'obs-bilingue.dll')
if ($LASTEXITCODE -ne 0) { throw 'Fallo la compilacion del plugin' }
Write-Host 'Plugin compilado: build\obs-bilingue.dll'
& $Zig cc -O2 @captionDebugFlags "-ffile-prefix-map=$captionRoot=." "-ffile-prefix-map=$ObsHeaders=obs-headers" -Wall -Wextra -Werror -Wno-deprecated-declarations -std=c11 -target x86_64-windows-gnu `
    "-I$ObsHeaders" "-I$captionBuild" (Join-Path $PSScriptRoot 'obs-test-host.c') `
    (Join-Path $PSScriptRoot 'routing-test.c') `
    (Join-Path $PSScriptRoot 'source-audio-test.c') `
    (Join-Path $captionBuild 'obs.lib') -o (Join-Path $captionBuild 'obs-test-host.exe')
if ($LASTEXITCODE -ne 0) { throw 'Fallo la compilacion del host de pruebas OBS' }
$captionData = Join-Path $captionBuild 'data'
New-Item -ItemType Directory -Force -Path $captionData | Out-Null
Copy-Item -LiteralPath (Join-Path $captionRoot 'web\preview.html') -Destination (Join-Path $captionData 'preview.html') -Force
$captionRuntime = @{ root = $captionRoot; python = (Join-Path $captionRoot '.venv\Scripts\pythonw.exe') } | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $captionData 'runtime.json'), $captionRuntime, [System.Text.UTF8Encoding]::new($false))
