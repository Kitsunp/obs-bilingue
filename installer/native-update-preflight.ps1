param([string]$PluginRoot)
$ErrorActionPreference = 'Stop'

function Test-NativeUpdateRoot([string]$Root) {
    if (!$Root) { return $false }
    $captionMetadata = Join-Path $Root 'data\runtime.json'
    $captionFlat = Join-Path $Root 'obs-bilingue.dll'
    $captionLegacy = Join-Path $Root 'bin\64bit\obs-bilingue.dll'
    return ((Test-Path -LiteralPath $captionMetadata -PathType Leaf) -and
        ((Test-Path -LiteralPath $captionFlat -PathType Leaf) -or
         (Test-Path -LiteralPath $captionLegacy -PathType Leaf)))
}

function Invoke-NativeUpdatePreflight([string]$Root) {
    if ([IntPtr]::Size -ne 8) { return 40 }
    # Never close OBS, pause an output or replace a loaded module.
    if (Get-Process obs64 -ErrorAction SilentlyContinue) { return 20 }
    if (!(Test-NativeUpdateRoot $Root)) { return 30 }
    return 0
}

if ($MyInvocation.InvocationName -ne '.') {
    if ([IntPtr]::Size -ne 8) {
        $captionNativeShell = Join-Path $env:WINDIR 'Sysnative\WindowsPowerShell\v1.0\powershell.exe'
        if (!(Test-Path -LiteralPath $captionNativeShell)) { exit 40 }
        & $captionNativeShell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $PSCommandPath -PluginRoot $PluginRoot
        exit $LASTEXITCODE
    }
    exit (Invoke-NativeUpdatePreflight $PluginRoot)
}
