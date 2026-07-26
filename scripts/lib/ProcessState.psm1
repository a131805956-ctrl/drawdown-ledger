Set-StrictMode -Version Latest

function Test-ProjectCommandLine {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandLine,

        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,

        [Parameter(Mandatory = $true)]
        [string]$CommandMarker
    )

    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }

    $normalizedRoot = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/')
    $rootPattern = '(?i)(^|[\s"'']){0}(?=[\\/]|[\s"'']|$)' -f (
        [regex]::Escape($normalizedRoot)
    )
    return (
        $CommandLine -match $rootPattern -and
        $CommandLine.IndexOf(
            $CommandMarker,
            [StringComparison]::OrdinalIgnoreCase
        ) -ge 0
    )
}

function Get-ProcessState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$StatePath
    )

    if (-not (Test-Path -LiteralPath $StatePath)) {
        return $null
    }
    $state = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($state.schema_version -notin @(1, 2)) {
        throw "Unsupported process state schema in '$StatePath'."
    }
    return $state
}

function Test-ProcessStateOwnership {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$State,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedProjectRoot,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedCommandMarker
    )

    $savedRoot = [IO.Path]::GetFullPath([string]$State.project_root).TrimEnd('\', '/')
    $expectedRoot = [IO.Path]::GetFullPath($ExpectedProjectRoot).TrimEnd('\', '/')
    return (
        $savedRoot.Equals($expectedRoot, [StringComparison]::OrdinalIgnoreCase) -and
        ([string]$State.command_marker).Equals(
            $ExpectedCommandMarker,
            [StringComparison]::OrdinalIgnoreCase
        )
    )
}

function Save-ProcessState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$StatePath,

        [Parameter(Mandatory = $true)]
        [int]$Id,

        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,

        [Parameter(Mandatory = $true)]
        [string]$CommandMarker,

        [Parameter(Mandatory = $true)]
        [string]$ServiceName,

        [string]$ArgumentList = '',

        [ValidateRange(0, 65535)]
        [int]$Port = 0
    )

    $directory = Split-Path -Parent $StatePath
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $temporaryPath = Join-Path $directory (
        '.{0}.{1}.tmp' -f (Split-Path -Leaf $StatePath), [guid]::NewGuid().ToString('N')
    )
    try {
        $state = [ordered]@{
            schema_version = 2
            pid = $Id
            project_root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/')
            command_marker = $CommandMarker
            service_name = $ServiceName
            argument_list = $ArgumentList
            port = $Port
            created_at = [DateTimeOffset]::UtcNow.ToString('o')
        }
        [IO.File]::WriteAllText(
            $temporaryPath,
            ($state | ConvertTo-Json),
            (New-Object Text.UTF8Encoding($false))
        )
        Move-Item -LiteralPath $temporaryPath -Destination $StatePath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Test-ProcessStateLaunchConfiguration {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$State,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedArgumentList,

        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 65535)]
        [int]$ExpectedPort
    )

    $argumentsProperty = $State.PSObject.Properties['argument_list']
    $portProperty = $State.PSObject.Properties['port']
    if ($null -eq $argumentsProperty -or $null -eq $portProperty) {
        return $false
    }
    return (
        ([string]$argumentsProperty.Value).Equals(
            $ExpectedArgumentList,
            [StringComparison]::Ordinal
        ) -and
        [int]$portProperty.Value -eq $ExpectedPort
    )
}

function Start-ProjectProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,

        [Parameter(Mandatory = $true)]
        [string]$ArgumentList,

        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,

        [Parameter(Mandatory = $true)]
        [string]$StatePath,

        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,

        [Parameter(Mandatory = $true)]
        [string]$CommandMarker,

        [Parameter(Mandatory = $true)]
        [string]$ServiceName,

        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 65535)]
        [int]$Port
    )

    $state = Get-ProcessState -StatePath $StatePath
    if ($null -ne $state) {
        if (-not (Test-ProcessStateOwnership `
            -State $state `
            -ExpectedProjectRoot $ProjectRoot `
            -ExpectedCommandMarker $CommandMarker
        )) {
            throw "Process state does not belong to this project: $StatePath"
        }
        if (Test-ProjectProcess `
            -Id ([int]$state.pid) `
            -ProjectRoot ([string]$state.project_root) `
            -CommandMarker ([string]$state.command_marker)
        ) {
            if (-not (Test-ProcessStateLaunchConfiguration `
                -State $state `
                -ExpectedArgumentList $ArgumentList `
                -ExpectedPort $Port
            )) {
                throw (
                    'A project-owned process is already running with a different ' +
                    'launch configuration. Stop it explicitly before changing ports ' +
                    'or startup arguments.'
                )
            }
            return Get-Process -Id ([int]$state.pid)
        }

        $recordedProcess = Get-Process `
            -Id ([int]$state.pid) `
            -ErrorAction SilentlyContinue
        if ($null -ne $recordedProcess) {
            throw (
                "State file '{0}' points to PID {1}, which is not project-owned." -f
                $StatePath, $state.pid
            )
        }
        Remove-Item -LiteralPath $StatePath -Force
    }

    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Milliseconds 150
    $process.Refresh()
    if ($process.HasExited) {
        throw "$ServiceName exited during startup with code $($process.ExitCode)."
    }
    if (-not (Test-ProjectProcess `
        -Id $process.Id `
        -ProjectRoot $ProjectRoot `
        -CommandMarker $CommandMarker
    )) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Started $ServiceName process failed project ownership validation."
    }

    Save-ProcessState `
        -StatePath $StatePath `
        -Id $process.Id `
        -ProjectRoot $ProjectRoot `
        -CommandMarker $CommandMarker `
        -ServiceName $ServiceName `
        -ArgumentList $ArgumentList `
        -Port $Port
    return $process
}

function Test-ProjectProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [int]$Id,

        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,

        [Parameter(Mandatory = $true)]
        [string]$CommandMarker
    )

    try {
        $process = Get-CimInstance `
            -ClassName Win32_Process `
            -Filter ("ProcessId = {0}" -f $Id) `
            -ErrorAction Stop
    }
    catch {
        return $false
    }
    if ($null -eq $process) {
        return $false
    }
    return Test-ProjectCommandLine `
        -CommandLine ([string]$process.CommandLine) `
        -ProjectRoot $ProjectRoot `
        -CommandMarker $CommandMarker
}

function Stop-ProjectProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$StatePath,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedProjectRoot,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedCommandMarker
    )

    $state = Get-ProcessState -StatePath $StatePath
    if ($null -eq $state) {
        return $false
    }
    if (-not (Test-ProcessStateOwnership `
        -State $state `
        -ExpectedProjectRoot $ExpectedProjectRoot `
        -ExpectedCommandMarker $ExpectedCommandMarker
    )) {
        throw "Process state does not belong to this project: $StatePath"
    }

    $process = Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        Remove-Item -LiteralPath $StatePath -Force
        return $false
    }

    $owned = Test-ProjectProcess `
        -Id ([int]$state.pid) `
        -ProjectRoot ([string]$state.project_root) `
        -CommandMarker ([string]$state.command_marker)
    if (-not $owned) {
        throw (
            "PID {0} does not belong to this project; refusing to stop it." -f
            $state.pid
        )
    }

    Stop-Process -Id ([int]$state.pid) -Force
    $process.WaitForExit(5000) | Out-Null
    Remove-Item -LiteralPath $StatePath -Force
    return $true
}

Export-ModuleMember -Function @(
    'Test-ProjectCommandLine'
    'Get-ProcessState'
    'Save-ProcessState'
    'Test-ProcessStateLaunchConfiguration'
    'Start-ProjectProcess'
    'Test-ProjectProcess'
    'Stop-ProjectProcess'
)
