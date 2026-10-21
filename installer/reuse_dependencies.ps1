param([string]$Manifest, [string]$PluginRoot, [string]$StagingRoot, [string]$Report,
      [switch]$Translation)
$ErrorActionPreference = 'Stop'

function Get-LocalDirectory([string]$Directory) {
    if ($Directory -and [IO.Path]::IsPathRooted($Directory) -and !$Directory.StartsWith('\\')) {
        try { return [IO.Path]::GetFullPath($Directory) } catch { }
    }
}

function Get-PythonRoots {
    # PEP 514 registrations and explicit PATH entries only; no disk/profile search.
    foreach ($hive in @('HKCU:\Software\Python', 'HKLM:\Software\Python')) {
        foreach ($company in Get-ChildItem -LiteralPath $hive -ErrorAction SilentlyContinue) {
            foreach ($tag in Get-ChildItem -LiteralPath $company.PSPath -ErrorAction SilentlyContinue) {
                $key = Get-Item -LiteralPath ($tag.PSPath + '\InstallPath') -ErrorAction SilentlyContinue
                if ($key) { Get-LocalDirectory ($key.GetValue('')) }
            }
        }
    }
    foreach ($directory in $env:PATH.Split(';')) {
        $local = Get-LocalDirectory $directory
        if ($local -and (Test-Path -LiteralPath (Join-Path $local 'python.exe') -PathType Leaf)) {
            if ((Split-Path -Leaf $local) -eq 'Scripts') { Split-Path -Parent $local } else { $local }
        }
    }
}

function Get-NativeRoots {
    Get-LocalDirectory (Join-Path $env:WINDIR 'System32')
    foreach ($variable in Get-ChildItem Env:CUDA_PATH*) {
        $local = Get-LocalDirectory $variable.Value
        if ($local) {
            Join-Path $local 'bin'
            Join-Path $local 'bin\x64'
        }
    }
    foreach ($directory in $env:PATH.Split(';')) { Get-LocalDirectory $directory }
}

function Test-ExpectedFile([string]$Path, [string]$Expected) {
    if (!(Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try {
        $stream = [IO.File]::OpenRead($Path)
        $hasher = [Security.Cryptography.SHA256]::Create()
        try {
            return ([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-', '') -eq $Expected
        } finally { $stream.Dispose(); $hasher.Dispose() }
    } catch { return $false }
}

function Invoke-Reuse {
    $app = [IO.Path]::GetFullPath((Join-Path $PluginRoot 'data\app'))
    $pythonRoots = @(Get-PythonRoots | Select-Object -Unique)
    $nativeRoots = @(Get-NativeRoots | Select-Object -Unique)
    $inventory = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
    $lines = [Collections.Generic.List[string]]::new()
    $lines.Add('[groups]')
    $copied = 0
    $kept = 0
    foreach ($group in $inventory.groups) {
        if ($group.id -notmatch '^[a-zA-Z0-9.-]+$') { throw 'Invalid dependency component' }
        if ($group.component -eq 'translation' -and !$Translation) { continue }
        $missing = $false
        foreach ($property in $group.files.PSObject.Properties) {
            $relative = $property.Name.Replace('/', '\')
            # Inventory is embedded in the installer; still validate before any write.
            if ([IO.Path]::IsPathRooted($relative) -or $relative.Split('\') -contains '..') {
                throw 'Invalid dependency destination'
            }
            $expected = $property.Value.sha256
            if (Test-ExpectedFile (Join-Path $app $relative) $expected) { $kept++; continue }
            $stage = Join-Path (Join-Path $StagingRoot $group.id) $relative
            $candidates = @()
            if ($relative.StartsWith('python\')) {
                $suffix = $relative.Substring(7)
                $candidates = @($pythonRoots | ForEach-Object { Join-Path $_ $suffix })
            } elseif ($relative.EndsWith('.dll')) {
                $candidates = @($nativeRoots | ForEach-Object { Join-Path $_ (Split-Path -Leaf $relative) })
                # Reuse the same verified library from the other installed engine.
                $candidates += Join-Path $app ('runtime\nemo\bin\' + (Split-Path -Leaf $relative))
                $candidates += Join-Path $app ('runtime\llama\' + (Split-Path -Leaf $relative))
            }
            $found = $false
            foreach ($candidate in $candidates) {
                if (Test-ExpectedFile $candidate $expected) {
                    [IO.Directory]::CreateDirectory((Split-Path -Parent $stage)) | Out-Null
                    [IO.File]::Copy($candidate, $stage, $true)
                    $copied++; $found = $true; break
                }
            }
            if (!$found) { $missing = $true }
        }
        $lines.Add($group.id + '=' + [int]$missing)
    }
    $lines.Add('[summary]')
    $lines.Add('kept=' + $kept)
    $lines.Add('reused=' + $copied)
    [IO.File]::WriteAllLines($Report, $lines, [Text.UTF8Encoding]::new($false))
}

# Tests dot-source the functions and supply isolated candidates, never change registry.
if ($MyInvocation.InvocationName -ne '.') { Invoke-Reuse }
