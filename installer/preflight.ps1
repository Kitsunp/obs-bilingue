param([string]$PluginRoot)
$ErrorActionPreference = 'Stop'

function Test-CudaVersion([int]$Version) { return $Version -ge 13000 }

function Invoke-Preflight([string]$Root) {
    if ([IntPtr]::Size -ne 8) { return 40 }
    if (Get-Process obs64 -ErrorAction SilentlyContinue) { return 20 }
    if ($Root) {
        $captionPython = [System.IO.Path]::GetFullPath((Join-Path $Root 'data\app\python')) + '\'
        $captionProcesses = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'"
        foreach ($captionProcess in $captionProcesses) {
            if ($captionProcess.ExecutablePath -and
                $captionProcess.ExecutablePath.StartsWith($captionPython, [StringComparison]::OrdinalIgnoreCase)) {
                return 21
            }
        }
    }
    try {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CaptionCudaProbe {
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("nvcuda.dll", CallingConvention=CallingConvention.Winapi)]
    public static extern int cuDriverGetVersion(out int version);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("nvcuda.dll", CallingConvention=CallingConvention.Winapi)]
    public static extern int cuInit(uint flags);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("nvcuda.dll", CallingConvention=CallingConvention.Winapi)]
    public static extern int cuDeviceGetCount(out int count);
}
'@
        $captionVersion = 0
        if ([CaptionCudaProbe]::cuDriverGetVersion([ref]$captionVersion) -ne 0) { return 10 }
        if (!(Test-CudaVersion $captionVersion)) { return 11 }
        if ([CaptionCudaProbe]::cuInit(0) -ne 0) { return 12 }
        $captionCount = 0
        if ([CaptionCudaProbe]::cuDeviceGetCount([ref]$captionCount) -ne 0 -or $captionCount -lt 1) { return 12 }
        return 0
    } catch { return 10 }
}

# Dot-sourcing defines the functions without probing or changing the machine.
if ($MyInvocation.InvocationName -ne '.') {
    if ([IntPtr]::Size -ne 8) {
        $captionNativeShell = Join-Path $env:WINDIR 'Sysnative\WindowsPowerShell\v1.0\powershell.exe'
        if (!(Test-Path -LiteralPath $captionNativeShell)) { exit 40 }
        & $captionNativeShell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $PSCommandPath -PluginRoot $PluginRoot
        exit $LASTEXITCODE
    }
    exit (Invoke-Preflight $PluginRoot)
}
