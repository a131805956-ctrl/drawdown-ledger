[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Backup.ps1')

function Read-DrawdownBackupManifest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$BackupPath
    )

    $manifestPath = Join-Path $BackupPath 'manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Backup manifest is missing: $manifestPath"
    }
    $manifest = Get-Content `
        -LiteralPath $manifestPath `
        -Raw `
        -Encoding UTF8 |
        ConvertFrom-Json
    if ($manifest.schema_version -ne 1 -or @($manifest.files).Count -eq 0) {
        throw "Unsupported or empty backup manifest: $manifestPath"
    }

    foreach ($entry in $manifest.files) {
        $relativePath = [string]$entry.path
        if (
            [IO.Path]::IsPathRooted($relativePath) -or
            $relativePath -split '[\\/]' -contains '..'
        ) {
            throw "Unsafe path in backup manifest: $relativePath"
        }
        if ([string]$entry.kind -notin @('sqlite', 'parquet')) {
            throw "Unsupported artifact kind in backup manifest: $($entry.kind)"
        }
        $source = Join-Path $BackupPath $relativePath
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Backup artifact is missing: $relativePath"
        }
        $actualHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
        if ($actualHash -ne [string]$entry.sha256) {
            throw "Backup checksum mismatch: $relativePath"
        }
        Test-DrawdownDataArtifact -Path $source -Kind ([string]$entry.kind)
    }
    return $manifest
}

function Restore-DrawdownBackup {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,

        [Parameter(Mandatory = $true)]
        [string]$BackupPath
    )

    $project = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/')
    $backup = [IO.Path]::GetFullPath($BackupPath).TrimEnd('\', '/')
    $processState = Join-Path $project '.runtime\api-process.json'
    if (Test-Path -LiteralPath $processState) {
        throw (
            'A managed runtime state is present. Run scripts\Stop.ps1 before restore.'
        )
    }
    $manifest = Read-DrawdownBackupManifest -BackupPath $backup
    $transaction = @()

    try {
        foreach ($entry in $manifest.files) {
            $relativePath = [string]$entry.path
            $source = Join-Path $backup $relativePath
            $target = Join-Path $project $relativePath
            $targetDirectory = Split-Path -Parent $target
            if (-not (Test-Path -LiteralPath $targetDirectory)) {
                New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
            }
            $token = [guid]::NewGuid().ToString('N')
            $staging = Join-Path $targetDirectory (
                '.{0}.{1}.restore.tmp' -f (Split-Path -Leaf $target), $token
            )
            $rollback = Join-Path $targetDirectory (
                '.{0}.{1}.rollback' -f (Split-Path -Leaf $target), $token
            )
            Copy-Item -LiteralPath $source -Destination $staging
            Test-DrawdownDataArtifact -Path $staging -Kind ([string]$entry.kind)
            $stagedHash = (Get-FileHash -LiteralPath $staging -Algorithm SHA256).Hash
            if ($stagedHash -ne [string]$entry.sha256) {
                throw "Staged restore checksum mismatch: $relativePath"
            }
            $transaction += [pscustomobject]@{
                Target = $target
                Staging = $staging
                Rollback = $rollback
                ExpectedHash = [string]$entry.sha256
                HadTarget = Test-Path -LiteralPath $target
                Installed = $false
            }
        }

        foreach ($item in $transaction) {
            if ($item.HadTarget) {
                Move-Item -LiteralPath $item.Target -Destination $item.Rollback
            }
            Move-Item -LiteralPath $item.Staging -Destination $item.Target
            $item.Installed = $true
            $installedHash = (
                Get-FileHash -LiteralPath $item.Target -Algorithm SHA256
            ).Hash
            if ($installedHash -ne $item.ExpectedHash) {
                throw "Installed restore checksum mismatch: $($item.Target)"
            }
        }
    }
    catch {
        for ($index = $transaction.Count - 1; $index -ge 0; $index--) {
            $item = $transaction[$index]
            if ($item.Installed -and (Test-Path -LiteralPath $item.Target)) {
                Remove-Item -LiteralPath $item.Target -Force
            }
            if (Test-Path -LiteralPath $item.Rollback) {
                Move-Item -LiteralPath $item.Rollback -Destination $item.Target -Force
            }
            if (Test-Path -LiteralPath $item.Staging) {
                Remove-Item -LiteralPath $item.Staging -Force
            }
        }
        throw
    }

    foreach ($item in $transaction) {
        if (Test-Path -LiteralPath $item.Rollback) {
            Remove-Item -LiteralPath $item.Rollback -Force
        }
    }
    return [pscustomobject]@{
        Restored = $transaction.Count
        BackupPath = $backup
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    if ($DryRun) {
        $manifest = Read-DrawdownBackupManifest -BackupPath $BackupPath
        [pscustomobject]@{
            Action = 'restore'
            BackupPath = [IO.Path]::GetFullPath($BackupPath)
            ArtifactCount = @($manifest.files).Count
        }
    }
    else {
        Restore-DrawdownBackup `
            -ProjectRoot $projectRoot `
            -BackupPath $BackupPath
    }
}
