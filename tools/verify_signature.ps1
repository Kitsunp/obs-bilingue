param(
    [string]$Path,
    [string]$ExpectedPublisher = 'SignPath Foundation',
    [string]$ExpectedProduct,
    [string]$ExpectedVersion
)
$ErrorActionPreference = 'Stop'

function Assert-SigningPolicy($Signature, [string]$Publisher) {
    if ($Signature.Status -ne 'Valid' -or !$Signature.SignerCertificate) {
        throw 'A trusted, valid Authenticode signature is required. Unsigned files are not signed releases.'
    }
    if ($Signature.SignatureType -ne 'Authenticode') {
        throw 'The release must contain an embedded Authenticode signature.'
    }
    $certificate = $Signature.SignerCertificate
    $actual = $certificate.GetNameInfo([Security.Cryptography.X509Certificates.X509NameType]::SimpleName, $false)
    if (!$Publisher -or ![string]::Equals($actual, $Publisher, [StringComparison]::OrdinalIgnoreCase)) {
        # Do not leak the unexpected identity into a public CI log.
        throw 'Unexpected publisher. Review the signing certificate before publishing.'
    }
    if ($certificate.GetNameInfo([Security.Cryptography.X509Certificates.X509NameType]::EmailName, $false)) {
        throw 'Signer certificate metadata requires maintainer review before publication.'
    }
    $usage = @($certificate.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.37' } |
        ForEach-Object { $_.EnhancedKeyUsages } | ForEach-Object { $_.Value })
    if ($usage -notcontains '1.3.6.1.5.5.7.3.3') {
        throw 'The publisher certificate must explicitly permit code signing.'
    }
    if (!$Signature.TimeStamperCertificate) {
        throw 'The signed release requires a trusted timestamp.'
    }
}

function Test-ReleaseSignature([string]$File, [string]$Publisher, [string]$Product, [string]$Version) {
    # Use this PowerShell installation's Windows verifier, including under PS 5.1
    # launched from PS 7 with an inherited module search path.
    Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1')
    $item = Get-Item -LiteralPath $File
    $signature = Microsoft.PowerShell.Security\Get-AuthenticodeSignature -LiteralPath $item.FullName
    Assert-SigningPolicy $signature $Publisher
    if ($Product -and $item.VersionInfo.ProductName.Trim() -ne $Product) {
        throw 'Unexpected product metadata in signed release.'
    }
    if ($Version -and $item.VersionInfo.ProductVersion.Trim() -ne $Version) {
        throw 'Unexpected product version in signed release.'
    }
    # The report contains no full subject, account email, local path or raw certificate.
    [pscustomobject]@{ file = $item.Name; status = 'Valid'; publisher = $Publisher; timestamped = $true }
}

# Dot-sourcing loads only policy functions; never searches certificate/key stores.
if ($MyInvocation.InvocationName -ne '.') {
    try {
        Test-ReleaseSignature $Path $ExpectedPublisher $ExpectedProduct $ExpectedVersion | ConvertTo-Json -Compress
        exit 0
    } catch {
        Write-Error $_.Exception.Message -ErrorAction Continue
        exit 1
    }
}
