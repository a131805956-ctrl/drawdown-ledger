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

function Normalize-ProjectCommandLine {
    [CmdletBinding()]
    param(
        [AllowNull()]
        [string]$CommandLine
    )

    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return ''
    }
    return [regex]::Replace($CommandLine.Trim(), '\s+', ' ')
}

function Resolve-ProjectExecutablePath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath
    )

    if ([string]::IsNullOrWhiteSpace($FilePath)) {
        throw 'The process executable path cannot be empty.'
    }
    $candidate = $FilePath
    if (-not [IO.Path]::IsPathRooted($candidate)) {
        $command = Get-Command `
            -Name $candidate `
            -CommandType Application `
            -ErrorAction Stop |
            Select-Object -First 1
        $candidate = [string]$command.Source
    }
    $item = Get-Item -LiteralPath $candidate -ErrorAction Stop
    if ($item.PSIsContainer) {
        throw "The process executable is not a file: $FilePath"
    }
    return [IO.Path]::GetFullPath($item.FullName)
}

function ConvertTo-ProcessStartTimeUtc {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProcessStartTimeUtc
    )

    $parsed = [datetime]::MinValue
    $valid = [datetime]::TryParse(
        $ProcessStartTimeUtc,
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::RoundtripKind,
        [ref]$parsed
    )
    if (-not $valid) {
        throw 'The process creation identity is not a valid timestamp.'
    }
    return $parsed.ToUniversalTime().ToString('o')
}

function Get-ProjectProcessIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [int]$Id
    )

    try {
        $managedProcess = Get-Process -Id $Id -ErrorAction Stop
        $null = $managedProcess.Handle
        $managedProcess.Refresh()
        $process = Get-CimInstance `
            -ClassName Win32_Process `
            -Filter ("ProcessId = {0}" -f $Id) `
            -ErrorAction Stop
    }
    catch {
        return $null
    }
    if (
        $null -eq $process -or
        [string]::IsNullOrWhiteSpace([string]$process.ExecutablePath)
    ) {
        return $null
    }
    try {
        $executablePath = [IO.Path]::GetFullPath(
            [string]$process.ExecutablePath
        )
        $processStartTimeUtc = $managedProcess.
            StartTime.
            ToUniversalTime().
            ToString('o')
    }
    catch {
        return $null
    }
    return [pscustomobject]@{
        ExecutablePath = $executablePath
        ProcessStartTimeUtc = $processStartTimeUtc
        CommandLine = [string]$process.CommandLine
    }
}

function Test-ProjectLaunchArguments {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandLine,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$ExpectedArgumentList,

        [Parameter(Mandatory = $true)]
        [int]$ExpectedPort
    )

    if ($ExpectedPort -lt 1 -or $ExpectedPort -gt 65535) {
        return $false
    }
    $normalizedCommandLine = Normalize-ProjectCommandLine -CommandLine $CommandLine
    $normalizedArguments = Normalize-ProjectCommandLine `
        -CommandLine $ExpectedArgumentList
    if (
        [string]::IsNullOrWhiteSpace($normalizedCommandLine) -or
        [string]::IsNullOrWhiteSpace($normalizedArguments)
    ) {
        return $false
    }

    $portMatches = [regex]::Matches(
        $normalizedArguments,
        '(?i)(?:^|\s)--port(?:\s+|=)(?<value>\S+)'
    )
    if ($portMatches.Count -ne 1) {
        return $false
    }
    $portToken = $portMatches[0].Groups['value'].Value.Trim(
        [char[]]@('"', "'")
    )
    $parsedPort = 0
    if (
        -not [int]::TryParse($portToken, [ref]$parsedPort) -or
        $parsedPort -ne $ExpectedPort
    ) {
        return $false
    }

    if (-not $normalizedCommandLine.EndsWith(
        $normalizedArguments,
        [StringComparison]::Ordinal
    )) {
        return $false
    }
    $argumentStart = $normalizedCommandLine.Length - $normalizedArguments.Length
    if (
        $argumentStart -le 0 -or
        -not [char]::IsWhiteSpace(
            $normalizedCommandLine[$argumentStart - 1]
        )
    ) {
        return $false
    }
    $executablePrefix = $normalizedCommandLine.Substring(
        0,
        $argumentStart
    ).Trim()
    return $executablePrefix -match '^(?:"[^"]+"|''[^'']+''|\S+)$'
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
    if ($state.schema_version -notin @(1, 2, 3)) {
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
        [int]$Port = 0,

        [string]$ExecutablePath = '',

        [string]$ProcessStartTimeUtc = ''
    )

    $hasExecutablePath = -not [string]::IsNullOrWhiteSpace($ExecutablePath)
    $hasStartTime = -not [string]::IsNullOrWhiteSpace($ProcessStartTimeUtc)
    if ($hasExecutablePath -xor $hasStartTime) {
        throw (
            'ExecutablePath and ProcessStartTimeUtc must either both be supplied ' +
            'or both be omitted.'
        )
    }
    if (-not $hasExecutablePath) {
        $identity = Get-ProjectProcessIdentity -Id $Id
        if ($null -ne $identity) {
            $ExecutablePath = $identity.ExecutablePath
            $ProcessStartTimeUtc = $identity.ProcessStartTimeUtc
        }
        elseif ($null -ne (Get-Process -Id $Id -ErrorAction SilentlyContinue)) {
            throw "Unable to read the creation identity for live PID $Id."
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($ExecutablePath)) {
        $ExecutablePath = Resolve-ProjectExecutablePath -FilePath $ExecutablePath
        $ProcessStartTimeUtc = ConvertTo-ProcessStartTimeUtc `
            -ProcessStartTimeUtc $ProcessStartTimeUtc
    }

    $directory = Split-Path -Parent $StatePath
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $temporaryPath = Join-Path $directory (
        '.{0}.{1}.tmp' -f (Split-Path -Leaf $StatePath), [guid]::NewGuid().ToString('N')
    )
    try {
        $state = [ordered]@{
            schema_version = 3
            pid = $Id
            project_root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/')
            command_marker = $CommandMarker
            service_name = $ServiceName
            argument_list = $ArgumentList
            port = $Port
            executable_path = $ExecutablePath
            process_start_time_utc = $ProcessStartTimeUtc
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

    $canonicalFilePath = Resolve-ProjectExecutablePath -FilePath $FilePath
    $state = Get-ProcessState -StatePath $StatePath
    if ($null -ne $state) {
        if (-not (Test-ProcessStateOwnership `
            -State $state `
            -ExpectedProjectRoot $ProjectRoot `
            -ExpectedCommandMarker $CommandMarker
        )) {
            throw "Process state does not belong to this project: $StatePath"
        }
        $argumentsProperty = $state.PSObject.Properties['argument_list']
        $portProperty = $state.PSObject.Properties['port']
        $savedArgumentList = if ($null -eq $argumentsProperty) {
            ''
        }
        else {
            [string]$argumentsProperty.Value
        }
        $savedPort = 0
        if ($null -ne $portProperty) {
            [int]::TryParse(
                [string]$portProperty.Value,
                [ref]$savedPort
            ) | Out-Null
        }
        $executableProperty = $state.PSObject.Properties['executable_path']
        $startTimeProperty = $state.PSObject.Properties['process_start_time_utc']
        $savedExecutablePath = if ($null -eq $executableProperty) {
            ''
        }
        else {
            [string]$executableProperty.Value
        }
        $savedProcessStartTimeUtc = if ($null -eq $startTimeProperty) {
            ''
        }
        else {
            [string]$startTimeProperty.Value
        }
        $recordedProcess = Get-Process `
            -Id ([int]$state.pid) `
            -ErrorAction SilentlyContinue
        if ($null -eq $recordedProcess) {
            Remove-Item -LiteralPath $StatePath -Force
        }
        else {
            try {
                $null = $recordedProcess.Handle
            }
            catch {
                throw (
                    "Unable to acquire PID {0} safely; refusing to reuse it." -f
                    $state.pid
                )
            }
        }
        if (
            $null -ne $recordedProcess -and
            (Test-ProjectProcess `
            -Id ([int]$state.pid) `
            -ProjectRoot ([string]$state.project_root) `
            -CommandMarker ([string]$state.command_marker) `
            -ExpectedArgumentList $savedArgumentList `
            -ExpectedPort $savedPort `
            -ExpectedExecutablePath $savedExecutablePath `
            -ExpectedProcessStartTimeUtc $savedProcessStartTimeUtc)
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
            if (
                [string]::IsNullOrWhiteSpace($savedExecutablePath) -or
                -not ([IO.Path]::GetFullPath($savedExecutablePath)).Equals(
                    $canonicalFilePath,
                    [StringComparison]::OrdinalIgnoreCase
                )
            ) {
                throw (
                    'A project-owned process is already running with a different ' +
                    'executable. Stop it explicitly before changing executables.'
                )
            }
            return $recordedProcess
        }

        if ($null -ne $recordedProcess) {
            throw (
                "State file '{0}' points to PID {1}, which is not project-owned." -f
                $StatePath, $state.pid
            )
        }
    }

    $process = Start-Process `
        -FilePath $canonicalFilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Milliseconds 150
    $process.Refresh()
    if ($process.HasExited) {
        throw "$ServiceName exited during startup with code $($process.ExitCode)."
    }
    $startedIdentity = Get-ProjectProcessIdentity -Id $process.Id
    if ($null -eq $startedIdentity) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Started $ServiceName process has no verifiable creation identity."
    }
    if (-not (Test-ProjectProcess `
        -Id $process.Id `
        -ProjectRoot $ProjectRoot `
        -CommandMarker $CommandMarker `
        -ExpectedArgumentList $ArgumentList `
        -ExpectedPort $Port `
        -ExpectedExecutablePath $canonicalFilePath `
        -ExpectedProcessStartTimeUtc $startedIdentity.ProcessStartTimeUtc
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
        -Port $Port `
        -ExecutablePath $startedIdentity.ExecutablePath `
        -ProcessStartTimeUtc $startedIdentity.ProcessStartTimeUtc
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
        [string]$CommandMarker,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$ExpectedArgumentList,

        [Parameter(Mandatory = $true)]
        [int]$ExpectedPort,

        [AllowEmptyString()]
        [string]$ExpectedExecutablePath = '',

        [AllowEmptyString()]
        [string]$ExpectedProcessStartTimeUtc = ''
    )

    $identity = Get-ProjectProcessIdentity -Id $Id
    if ($null -eq $identity) {
        return $false
    }
    $commandLineOwned = (
        (Test-ProjectCommandLine `
            -CommandLine $identity.CommandLine `
            -ProjectRoot $ProjectRoot `
            -CommandMarker $CommandMarker) -and
        (Test-ProjectLaunchArguments `
            -CommandLine $identity.CommandLine `
            -ExpectedArgumentList $ExpectedArgumentList `
            -ExpectedPort $ExpectedPort)
    )
    if (-not $commandLineOwned) {
        return $false
    }
    $hasExpectedExecutable = -not [string]::IsNullOrWhiteSpace(
        $ExpectedExecutablePath
    )
    $hasExpectedStartTime = -not [string]::IsNullOrWhiteSpace(
        $ExpectedProcessStartTimeUtc
    )
    if (-not $hasExpectedExecutable -or -not $hasExpectedStartTime) {
        return $false
    }
    try {
        $expectedExecutable = [IO.Path]::GetFullPath(
            $ExpectedExecutablePath
        )
        $expectedStartTime = ConvertTo-ProcessStartTimeUtc `
            -ProcessStartTimeUtc $ExpectedProcessStartTimeUtc
    }
    catch {
        return $false
    }
    return (
        $identity.ExecutablePath.Equals(
            $expectedExecutable,
            [StringComparison]::OrdinalIgnoreCase
        ) -and
        $identity.ProcessStartTimeUtc.Equals(
            $expectedStartTime,
            [StringComparison]::Ordinal
        )
    )
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
    try {
        $null = $process.Handle
    }
    catch {
        throw (
            "Unable to acquire PID {0} safely; refusing to stop it." -f
            $state.pid
        )
    }

    $argumentsProperty = $state.PSObject.Properties['argument_list']
    $portProperty = $state.PSObject.Properties['port']
    $savedArgumentList = if ($null -eq $argumentsProperty) {
        ''
    }
    else {
        [string]$argumentsProperty.Value
    }
    $savedPort = 0
    if ($null -ne $portProperty) {
        [int]::TryParse(
            [string]$portProperty.Value,
            [ref]$savedPort
        ) | Out-Null
    }
    $executableProperty = $state.PSObject.Properties['executable_path']
    $startTimeProperty = $state.PSObject.Properties['process_start_time_utc']
    $savedExecutablePath = if ($null -eq $executableProperty) {
        ''
    }
    else {
        [string]$executableProperty.Value
    }
    $savedProcessStartTimeUtc = if ($null -eq $startTimeProperty) {
        ''
    }
    else {
        [string]$startTimeProperty.Value
    }
    $owned = Test-ProjectProcess `
        -Id ([int]$state.pid) `
        -ProjectRoot ([string]$state.project_root) `
        -CommandMarker ([string]$state.command_marker) `
        -ExpectedArgumentList $savedArgumentList `
        -ExpectedPort $savedPort `
        -ExpectedExecutablePath $savedExecutablePath `
        -ExpectedProcessStartTimeUtc $savedProcessStartTimeUtc
    if (-not $owned) {
        throw (
            "PID {0} does not belong to this project; refusing to stop it." -f
            $state.pid
        )
    }

    Stop-Process -InputObject $process -Force
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
