[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Backup.ps1')

function Resolve-DrawdownArtifactRelativePath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [ValidateSet('sqlite', 'parquet')]
        [string]$Kind
    )

    if ([string]::IsNullOrWhiteSpace($Path) -or [IO.Path]::IsPathRooted($Path)) {
        throw "Unsafe path in backup manifest: $Path"
    }
    $segments = @($Path -split '[\\/]')
    if (
        $Path.Contains(':') -or
        $segments.Count -lt 2 -or
        @($segments | Where-Object {
            [string]::IsNullOrWhiteSpace($_) -or $_ -in @('.', '..')
        }).Count -gt 0
    ) {
        throw "Unsafe path in backup manifest: $Path"
    }
    $allowedRoot = $segments[0].ToLowerInvariant()
    if ($allowedRoot -notin @('.runtime', 'data')) {
        throw (
            "Backup artifacts may only restore under '.runtime' or 'data': $Path"
        )
    }
    $extension = [IO.Path]::GetExtension($segments[-1]).ToLowerInvariant()
    $validExtension = if ($Kind -eq 'parquet') {
        $extension -eq '.parquet'
    }
    else {
        $extension -in @('.sqlite', '.sqlite3', '.db')
    }
    if (-not $validExtension) {
        throw "Artifact extension does not match kind '$Kind': $Path"
    }
    return $segments -join [IO.Path]::DirectorySeparatorChar
}

function Assert-NoDrawdownReparsePoint {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,

        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Purpose
    )

    $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $candidate = [IO.Path]::GetFullPath($Path)
    $prefix = $rootPath + [IO.Path]::DirectorySeparatorChar
    if (
        -not $candidate.Equals($rootPath, [StringComparison]::OrdinalIgnoreCase) -and
        -not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "$Purpose path escapes its trusted root: $candidate"
    }

    $relative = if ($candidate.Equals(
        $rootPath,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        ''
    }
    else {
        $candidate.Substring($prefix.Length)
    }
    $current = $rootPath
    foreach ($segment in @($relative -split '[\\/]')) {
        if ([string]::IsNullOrEmpty($segment)) {
            continue
        }
        $current = Join-Path $current $segment
        if (-not (Test-Path -LiteralPath $current)) {
            break
        }
        $item = Get-Item -LiteralPath $current -Force
        if (
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
            $null -ne $item.PSObject.Properties['LinkType'] -and
            -not [string]::IsNullOrWhiteSpace([string]$item.LinkType)
        ) {
            throw "$Purpose path contains a reparse point: $current"
        }
    }
}

function Read-DrawdownBackupManifest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$BackupPath,

        [Parameter(Mandatory = $true)]
        [string]$PythonPath
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

    $seenPaths = New-Object 'Collections.Generic.HashSet[string]' (
        [StringComparer]::OrdinalIgnoreCase
    )
    foreach ($entry in $manifest.files) {
        $kind = [string]$entry.kind
        if ($kind -notin @('sqlite', 'parquet')) {
            throw "Unsupported artifact kind in backup manifest: $($entry.kind)"
        }
        $relativePath = Resolve-DrawdownArtifactRelativePath `
            -Path ([string]$entry.path) `
            -Kind $kind
        if (-not $seenPaths.Add($relativePath)) {
            throw "Duplicate artifact path in backup manifest: $relativePath"
        }
        $source = Join-Path $BackupPath $relativePath
        Assert-NoDrawdownReparsePoint `
            -Root $BackupPath `
            -Path $source `
            -Purpose 'Backup source'
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Backup artifact is missing: $relativePath"
        }
        if ((Get-Item -LiteralPath $source).Length -ne [long]$entry.size) {
            throw "Backup size mismatch: $relativePath"
        }
        $actualHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
        if ($actualHash -ne [string]$entry.sha256) {
            throw "Backup checksum mismatch: $relativePath"
        }
        Test-DrawdownDataArtifact `
            -Path $source `
            -Kind $kind `
            -PythonPath $PythonPath
        $entry | Add-Member `
            -NotePropertyName normalized_path `
            -NotePropertyValue $relativePath `
            -Force
    }
    return $manifest
}

function New-DrawdownRestorePlan {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,

        [Parameter(Mandatory = $true)]
        [string]$BackupPath,

        [Parameter(Mandatory = $true)]
        [object]$Manifest
    )

    $plan = @()
    foreach ($entry in $Manifest.files) {
        $relativePath = [string]$entry.normalized_path
        $source = [IO.Path]::GetFullPath((Join-Path $BackupPath $relativePath))
        $target = [IO.Path]::GetFullPath((Join-Path $ProjectRoot $relativePath))
        Assert-NoDrawdownReparsePoint `
            -Root $ProjectRoot `
            -Path $target `
            -Purpose 'Restore target'
        $plan += [pscustomobject]@{
            RelativePath = $relativePath
            Source = $source
            Target = $target
            Kind = [string]$entry.kind
            ExpectedHash = [string]$entry.sha256
        }
    }
    return $plan
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
    $pythonPath = Get-DrawdownProjectPython -ProjectRoot $project
    $processState = Join-Path $project '.runtime\api-process.json'
    if (Test-Path -LiteralPath $processState) {
        throw (
            'A managed runtime state is present. Run scripts\Stop.ps1 before restore.'
        )
    }
    $manifest = Read-DrawdownBackupManifest `
        -BackupPath $backup `
        -PythonPath $pythonPath
    $plan = @(
        New-DrawdownRestorePlan `
            -ProjectRoot $project `
            -BackupPath $backup `
            -Manifest $manifest
    )
    $transaction = @()

    try {
        foreach ($planned in $plan) {
            $target = $planned.Target
            $targetDirectory = Split-Path -Parent $target
            $token = [guid]::NewGuid().ToString('N')
            $staging = Join-Path $targetDirectory (
                '.{0}.{1}.restore.tmp' -f (Split-Path -Leaf $target), $token
            )
            $rollback = Join-Path $targetDirectory (
                '.{0}.{1}.rollback' -f (Split-Path -Leaf $target), $token
            )
            $transaction += [pscustomobject]@{
                Target = $target
                Source = $planned.Source
                Staging = $staging
                Rollback = $rollback
                Kind = $planned.Kind
                RelativePath = $planned.RelativePath
                ExpectedHash = $planned.ExpectedHash
                HadTarget = Test-Path -LiteralPath $target
                Installed = $false
            }
        }

        foreach ($item in $transaction) {
            $targetDirectory = Split-Path -Parent $item.Target
            if (-not (Test-Path -LiteralPath $targetDirectory)) {
                New-Item -ItemType Directory -Path $targetDirectory -Force | Out-Null
            }
            Copy-Item -LiteralPath $item.Source -Destination $item.Staging
            Test-DrawdownDataArtifact `
                -Path $item.Staging `
                -Kind $item.Kind `
                -PythonPath $pythonPath
            $stagedHash = (
                Get-FileHash -LiteralPath $item.Staging -Algorithm SHA256
            ).Hash
            if ($stagedHash -ne $item.ExpectedHash) {
                throw "Staged restore checksum mismatch: $($item.RelativePath)"
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
        $pythonPath = Get-DrawdownProjectPython -ProjectRoot $projectRoot
        $manifest = Read-DrawdownBackupManifest `
            -BackupPath $BackupPath `
            -PythonPath $pythonPath
        New-DrawdownRestorePlan `
            -ProjectRoot $projectRoot `
            -BackupPath $BackupPath `
            -Manifest $manifest |
            Out-Null
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
