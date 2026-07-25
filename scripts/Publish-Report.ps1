[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ExportId,

    [string]$PrivateRoot,

    [string]$PublishedRoot,

    [string]$PythonExecutable = 'python'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-FullDirectoryPath {
    param([Parameter(Mandatory = $true)][string]$Value)
    return [IO.Path]::GetFullPath($Value).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
}

function Test-IsChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Parent
    )
    $Prefix = $Parent + [IO.Path]::DirectorySeparatorChar
    return $Candidate.StartsWith(
        $Prefix,
        [StringComparison]::OrdinalIgnoreCase
    )
}

if (
    $ExportId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$' -or
    $ExportId.Contains('..')
) {
    throw 'ExportId contains unsafe characters.'
}

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($PrivateRoot)) {
    $PrivateRoot = Join-Path $RepositoryRoot 'reports\private'
}
if ([string]::IsNullOrWhiteSpace($PublishedRoot)) {
    $PublishedRoot = Join-Path $RepositoryRoot 'reports\published'
}

$ResolvedPrivateRoot = Get-FullDirectoryPath (
    (Resolve-Path -LiteralPath $PrivateRoot -ErrorAction Stop).Path
)
$SourceCandidate = Join-Path $ResolvedPrivateRoot $ExportId
$ResolvedSource = Get-FullDirectoryPath (
    (Resolve-Path -LiteralPath $SourceCandidate -ErrorAction Stop).Path
)
if (-not (Test-IsChildPath -Candidate $ResolvedSource -Parent $ResolvedPrivateRoot)) {
    throw 'Resolved export source escapes the private report root.'
}
if (-not (Test-Path -LiteralPath $ResolvedSource -PathType Container)) {
    throw "Export bundle does not exist: $ExportId"
}

$ManifestPath = Join-Path $ResolvedSource 'manifest.json'
if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
    throw "Export bundle is missing manifest.json: $ExportId"
}
try {
    $Manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath $ManifestPath |
        ConvertFrom-Json -ErrorAction Stop
}
catch {
    throw "Export bundle has an invalid manifest: $ExportId"
}
if ([string]$Manifest.export_id -cne $ExportId) {
    throw 'Manifest export_id does not match the explicit ExportId.'
}

$PrivacyScript = Join-Path $PSScriptRoot 'Test-PublishedPrivacy.ps1'
& $PrivacyScript -Path $ResolvedSource -PythonExecutable $PythonExecutable |
    Out-Null

$ResolvedPublishedRoot = Get-FullDirectoryPath $PublishedRoot
if (-not (Test-Path -LiteralPath $ResolvedPublishedRoot)) {
    New-Item -ItemType Directory -Path $ResolvedPublishedRoot -Force |
        Out-Null
}
$ResolvedPublishedRoot = Get-FullDirectoryPath (
    (Resolve-Path -LiteralPath $ResolvedPublishedRoot -ErrorAction Stop).Path
)
$Destination = Get-FullDirectoryPath (
    (Join-Path $ResolvedPublishedRoot $ExportId)
)
if (-not (Test-IsChildPath -Candidate $Destination -Parent $ResolvedPublishedRoot)) {
    throw 'Resolved publication destination escapes the published report root.'
}
if (Test-Path -LiteralPath $Destination) {
    throw "Published export already exists: $ExportId"
}

$TemporaryName = '.publish-' + $ExportId + '-' + [Guid]::NewGuid().ToString('N')
$TemporaryDirectory = Get-FullDirectoryPath (
    (Join-Path $ResolvedPublishedRoot $TemporaryName)
)
if (-not (
    Test-IsChildPath -Candidate $TemporaryDirectory -Parent $ResolvedPublishedRoot
)) {
    throw 'Temporary publication path escapes the published report root.'
}

try {
    New-Item -ItemType Directory -Path $TemporaryDirectory -ErrorAction Stop |
        Out-Null
    Get-ChildItem -LiteralPath $ResolvedSource -Force |
        Copy-Item -Destination $TemporaryDirectory -Recurse -Force -ErrorAction Stop
    & $PrivacyScript -Path $TemporaryDirectory -PythonExecutable $PythonExecutable |
        Out-Null
    Move-Item -LiteralPath $TemporaryDirectory -Destination $Destination -ErrorAction Stop
}
catch {
    if (
        (Test-Path -LiteralPath $TemporaryDirectory) -and
        (Test-IsChildPath `
            -Candidate $TemporaryDirectory `
            -Parent $ResolvedPublishedRoot)
    ) {
        Remove-Item -LiteralPath $TemporaryDirectory -Recurse -Force
    }
    throw
}

$PublishedFileCount = @(
    Get-ChildItem -LiteralPath $Destination -File -Recurse -Force
).Count
[pscustomobject]@{
    ExportId = $ExportId
    FileCount = $PublishedFileCount
}
