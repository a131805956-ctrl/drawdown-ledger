[CmdletBinding()]
param(
    [string]$DestinationRoot,
    [string]$Name,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-ProjectRelativePath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,

        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/') +
        [IO.Path]::DirectorySeparatorChar
    $fullPath = [IO.Path]::GetFullPath($Path)
    if (-not $fullPath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Backup source is outside the project root: $fullPath"
    }
    return $fullPath.Substring($root.Length).Replace('\', '/')
}

function Get-DrawdownProjectPython {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $candidates = @(
        (Join-Path $ProjectRoot '.venv\Scripts\python.exe'),
        (Join-Path $ProjectRoot '.venv\Scripts\python.cmd'),
        (Join-Path $ProjectRoot '.venv\Scripts\python.ps1'),
        (Join-Path $ProjectRoot '.venv\bin\python')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return [IO.Path]::GetFullPath($candidate)
        }
    }
    throw (
        "Project virtualenv Python was not found under '{0}\.venv'. " +
        'Run scripts\Start.ps1 before backup or restore.'
    ) -f ([IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/'))
}

function Test-DrawdownDataArtifact {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [ValidateSet('sqlite', 'parquet')]
        [string]$Kind,

        [Parameter(Mandatory = $true)]
        [string]$PythonPath
    )

    if ($Kind -eq 'sqlite') {
        $validation = @'
import sqlite3
import sys
with sqlite3.connect(sys.argv[1]) as connection:
    result = connection.execute('PRAGMA quick_check').fetchone()
if result is None or result[0] != 'ok':
    raise SystemExit(f'SQLite quick_check failed: {result}')
'@
    }
    else {
        $validation = @'
import sys
import pyarrow.parquet as parquet
parquet.read_metadata(sys.argv[1])
'@
    }
    & $PythonPath -c $validation $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Backup validation failed for $Kind artifact '$Path'."
    }
}

function Copy-SqliteSnapshot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,

        [Parameter(Mandatory = $true)]
        [string]$Destination,

        [Parameter(Mandatory = $true)]
        [string]$PythonPath
    )

    $backupScript = @'
import sqlite3
import sys
source = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True)
destination = sqlite3.connect(sys.argv[2])
try:
    source.backup(destination)
finally:
    destination.close()
    source.close()
'@
    & $PythonPath -c $backupScript $Source $Destination
    if ($LASTEXITCODE -ne 0) {
        throw "SQLite backup failed for '$Source'."
    }
}

function New-DrawdownBackup {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,

        [Parameter(Mandatory = $true)]
        [string]$DestinationRoot,

        [Parameter(Mandatory = $true)]
        [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
        [string]$Name
    )

    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/')
    $destination = [IO.Path]::GetFullPath($DestinationRoot).TrimEnd('\', '/')
    $pythonPath = Get-DrawdownProjectPython -ProjectRoot $project
    if (-not (Test-Path -LiteralPath $destination)) {
        New-Item -ItemType Directory -Path $destination -Force | Out-Null
    }
    $finalPath = Join-Path $destination $Name
    if (Test-Path -LiteralPath $finalPath) {
        throw "Backup already exists: $finalPath"
    }
    $stagingPath = Join-Path $destination (
        '.{0}.{1}.tmp' -f $Name, [guid]::NewGuid().ToString('N')
    )
    New-Item -ItemType Directory -Path $stagingPath | Out-Null

    try {
        $sourceFiles = @()
        foreach ($relativeRoot in @('.runtime', 'data')) {
            $sourceRoot = Join-Path $project $relativeRoot
            if (-not (Test-Path -LiteralPath $sourceRoot)) {
                continue
            }
            $sourceFiles += Get-ChildItem -LiteralPath $sourceRoot -Recurse -File |
                Where-Object {
                    $_.Extension.ToLowerInvariant() -in @(
                        '.sqlite', '.sqlite3', '.db', '.parquet'
                    )
                }
        }
        if ($sourceFiles.Count -eq 0) {
            throw 'No SQLite or Parquet artifacts were found to back up.'
        }

        $manifestFiles = @()
        foreach ($sourceFile in @($sourceFiles | Sort-Object FullName)) {
            $relativePath = Get-ProjectRelativePath `
                -ProjectRoot $project `
                -Path $sourceFile.FullName
            $backupFile = Join-Path $stagingPath $relativePath
            $backupDirectory = Split-Path -Parent $backupFile
            if (-not (Test-Path -LiteralPath $backupDirectory)) {
                New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
            }
            $kind = if ($sourceFile.Extension -eq '.parquet') {
                'parquet'
            }
            else {
                'sqlite'
            }
            if ($kind -eq 'sqlite') {
                Copy-SqliteSnapshot `
                    -Source $sourceFile.FullName `
                    -Destination $backupFile `
                    -PythonPath $pythonPath
            }
            else {
                Copy-Item -LiteralPath $sourceFile.FullName -Destination $backupFile
            }
            Test-DrawdownDataArtifact `
                -Path $backupFile `
                -Kind $kind `
                -PythonPath $pythonPath
            $backedUpFile = Get-Item -LiteralPath $backupFile
            $manifestFiles += [ordered]@{
                path = $relativePath
                kind = $kind
                size = $backedUpFile.Length
                sha256 = (Get-FileHash -LiteralPath $backupFile -Algorithm SHA256).Hash
            }
        }

        $manifest = [ordered]@{
            schema_version = 1
            created_at = [DateTimeOffset]::UtcNow.ToString('o')
            files = $manifestFiles
        }
        [IO.File]::WriteAllText(
            (Join-Path $stagingPath 'manifest.json'),
            ($manifest | ConvertTo-Json -Depth 10),
            (New-Object Text.UTF8Encoding($false))
        )
        Move-Item -LiteralPath $stagingPath -Destination $finalPath
        return $finalPath
    }
    catch {
        if (Test-Path -LiteralPath $stagingPath) {
            Remove-Item -LiteralPath $stagingPath -Recurse -Force
        }
        throw
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    if ([string]::IsNullOrWhiteSpace($DestinationRoot)) {
        $DestinationRoot = Join-Path $projectRoot 'backups'
    }
    if ([string]::IsNullOrWhiteSpace($Name)) {
        $Name = 'drawdown-{0}' -f (Get-Date -Format 'yyyyMMdd-HHmmss')
    }
    if ($DryRun) {
        [pscustomobject]@{
            Action = 'backup'
            Destination = Join-Path $DestinationRoot $Name
        }
    }
    else {
        New-DrawdownBackup `
            -ProjectRoot $projectRoot `
            -DestinationRoot $DestinationRoot `
            -Name $Name
    }
}
