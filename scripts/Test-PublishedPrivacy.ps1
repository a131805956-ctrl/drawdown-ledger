[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Path,

    [string]$PythonExecutable = 'python'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ResolvedPath = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$SourceRoot = Join-Path $RepositoryRoot 'apps\api\src'
if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
    throw 'Unable to locate the Drawdown Lab Python source directory.'
}

$PreviousPythonPath = $env:PYTHONPATH
try {
    if ([string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
        $env:PYTHONPATH = $SourceRoot
    }
    else {
        $env:PYTHONPATH = $SourceRoot + [IO.Path]::PathSeparator + $PreviousPythonPath
    }

    $ScanOutput = @(
        & $PythonExecutable -m drawdown_lab.reports.privacy $ResolvedPath 2>&1
    )
    $ScanExitCode = $LASTEXITCODE
}
finally {
    if ($null -eq $PreviousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $PreviousPythonPath
    }
}

$SummaryText = ($ScanOutput | Select-Object -Last 1 | Out-String).Trim()
if ($ScanExitCode -ne 0) {
    if ([string]::IsNullOrWhiteSpace($SummaryText)) {
        $SummaryText = '{"allowed":false,"findings":[{"code":"scanner_failed"}]}'
    }
    throw "Privacy scan blocked publication: $SummaryText"
}

try {
    $Summary = $SummaryText | ConvertFrom-Json -ErrorAction Stop
}
catch {
    throw 'Privacy scanner returned an invalid response.'
}
if ($Summary.allowed -ne $true) {
    throw 'Privacy scanner did not explicitly allow publication.'
}

[pscustomobject]@{
    Allowed = $true
    ScannedFiles = [int]$Summary.scanned_files
}
