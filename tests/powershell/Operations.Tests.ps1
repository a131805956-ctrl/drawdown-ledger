$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$ModulePath = Join-Path $ProjectRoot 'scripts\lib\ProcessState.psm1'
$PublicAccessModulePath = Join-Path (
    $ProjectRoot
) 'scripts\lib\PublicAccess.psm1'

function Set-TestProcessIdentity {
    param(
        [Parameter(Mandatory = $true)]
        [string]$StatePath,

        [Parameter(Mandatory = $true)]
        [string]$ExecutablePath,

        [Parameter(Mandatory = $true)]
        [string]$ProcessStartTimeUtc
    )

    $state = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $state |
        Add-Member `
            -MemberType NoteProperty `
            -Name executable_path `
            -Value $ExecutablePath `
            -Force
    $state |
        Add-Member `
            -MemberType NoteProperty `
            -Name process_start_time_utc `
            -Value $ProcessStartTimeUtc `
            -Force
    [IO.File]::WriteAllText(
        $StatePath,
        ($state | ConvertTo-Json),
        (New-Object Text.UTF8Encoding($false))
    )
}

Describe 'Process state module contract' {
    It 'exports project-owned process lifecycle commands' {
        Test-Path -LiteralPath $ModulePath | Should Be $true
        Import-Module $ModulePath -Force

        Get-Command Test-ProjectProcess -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Stop-ProjectProcess -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Test-ProjectCommandLine -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Get-ProcessState -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Save-ProcessState -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Start-ProjectProcess -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
    }
}

Describe 'Public access credential boundary' {
    BeforeEach {
        Import-Module $PublicAccessModulePath -Force
    }

    It 'creates and reuses one strong project-local credential' {
        $path = Join-Path $TestDrive 'runtime\public-access.json'

        $first = New-DrawdownPublicCredential -Path $path
        $second = New-DrawdownPublicCredential -Path $path

        $first.Username | Should Be 'drawdown'
        $first.Password | Should Match '^[A-Za-z0-9_-]{43}$'
        $second.Password | Should Be $first.Password
        $second.Path | Should Be ([IO.Path]::GetFullPath($path))
        (Get-ChildItem `
            -LiteralPath (Split-Path -Parent $path) `
            -Filter '*.tmp').Count |
            Should Be 0
    }

    It 'rejects a malformed credential instead of weakening protection' {
        $path = Join-Path $TestDrive 'invalid-public-access.json'
        '{"schema_version":1,"username":"drawdown","password":"short"}' |
            Set-Content -LiteralPath $path -Encoding UTF8

        { Read-DrawdownPublicCredential -Path $path } |
            Should Throw
    }
}

Describe 'One-click script contract' {
    $scriptNames = @(
        'Start.ps1'
        'Update-Data.ps1'
        'Open-Funnel.ps1'
        'Backup.ps1'
        'Restore.ps1'
        'Stop.ps1'
        'Analyze.ps1'
    )

    foreach ($scriptName in $scriptNames) {
        It "provides a syntactically valid $scriptName" {
            $path = Join-Path $ProjectRoot "scripts\$scriptName"
            Test-Path -LiteralPath $path | Should Be $true
            $tokens = $null
            $errors = $null
            [Management.Automation.Language.Parser]::ParseFile(
                $path,
                [ref]$tokens,
                [ref]$errors
            ) | Out-Null
            @($errors).Count | Should Be 0
        }
    }

    It 'installs the project without an editable path hook' {
        $startScript = Get-Content `
            -LiteralPath (Join-Path $ProjectRoot 'scripts\Start.ps1') `
            -Raw

        $startScript | Should Not Match '(?m)\bpip install[^\r\n]*\s-e(?:\s|$)'
        $startScript | Should Match '(?m)\bpip install[^\r\n]*\$projectRoot'
    }
}

Describe 'Project process ownership' {
    It 'accepts only a command line containing the exact project root and marker' {
        $commandLine = @(
            'python.exe -m uvicorn drawdown_lab.runtime:create_runtime_app'
            '--factory'
            ('--app-dir "{0}\apps\api\src"' -f $ProjectRoot)
        ) -join ' '

        Test-ProjectCommandLine `
            -CommandLine $commandLine `
            -ProjectRoot $ProjectRoot `
            -CommandMarker 'drawdown_lab.runtime:create_runtime_app' |
            Should Be $true
    }

    It 'rejects a sibling path that only shares the project-root prefix' {
        $commandLine = @(
            'python.exe -m uvicorn drawdown_lab.runtime:create_runtime_app'
            ('--app-dir "{0}-other\apps\api\src"' -f $ProjectRoot)
        ) -join ' '

        Test-ProjectCommandLine `
            -CommandLine $commandLine `
            -ProjectRoot $ProjectRoot `
            -CommandMarker 'drawdown_lab.runtime:create_runtime_app' |
            Should Be $false
    }

    It 'validates a live process before it can be managed' {
        $arguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "drawdown-test-marker $ProjectRoot --port 8787" +
            '"'
        )
        $process = Start-Process `
            -FilePath powershell.exe `
            -ArgumentList $arguments `
            -WindowStyle Hidden `
            -PassThru
        try {
            Start-Sleep -Milliseconds 150
            $cimProcess = Get-CimInstance `
                -ClassName Win32_Process `
                -Filter ("ProcessId = {0}" -f $process.Id) `
                -ErrorAction Stop
            Test-ProjectProcess `
                -Id $process.Id `
                -ProjectRoot $ProjectRoot `
                -CommandMarker 'drawdown-test-marker' `
                -ExpectedArgumentList $arguments `
                -ExpectedPort 8787 `
                -ExpectedExecutablePath $cimProcess.ExecutablePath `
                -ExpectedProcessStartTimeUtc (
                    $process.StartTime.ToUniversalTime().ToString('o')
                ) |
                Should Be $true
        }
        finally {
            if (-not $process.HasExited) {
                Stop-Process -Id $process.Id -Force
            }
        }
    }
}

Describe 'Process state persistence' {
    It 'round-trips an explicit project process state file' {
        $statePath = Join-Path $TestDrive 'api.json'
        $arguments = '-m uvicorn drawdown_lab.runtime:create_runtime_app --port 8787'
        $executable = (Get-Command powershell.exe -ErrorAction Stop).Source
        $startTimeUtc = '2026-07-26T01:23:45.6789012Z'

        Save-ProcessState `
            -StatePath $statePath `
            -Id 4242 `
            -ProjectRoot $ProjectRoot `
            -CommandMarker 'drawdown_lab.runtime:create_runtime_app' `
            -ServiceName 'api' `
            -ArgumentList $arguments `
            -Port 8787 `
            -ExecutablePath $executable `
            -ProcessStartTimeUtc $startTimeUtc

        $state = Get-ProcessState -StatePath $statePath
        $state.schema_version | Should Be 3
        $state.pid | Should Be 4242
        $state.project_root | Should Be $ProjectRoot
        $state.command_marker | Should Be 'drawdown_lab.runtime:create_runtime_app'
        $state.service_name | Should Be 'api'
        $state.argument_list | Should Be $arguments
        $state.port | Should Be 8787
        $state.executable_path | Should Be $executable
        $state.process_start_time_utc | Should Be $startTimeUtc
    }
}

Describe 'Safe process stopping' {
    It 'refuses to stop a PID whose command line does not match saved ownership' {
        $arguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "actual-marker $ProjectRoot" +
            '"'
        )
        $process = Start-Process `
            -FilePath powershell.exe `
            -ArgumentList $arguments `
            -WindowStyle Hidden `
            -PassThru
        $statePath = Join-Path $TestDrive 'mismatch.json'
        try {
            Save-ProcessState `
                -StatePath $statePath `
                -Id $process.Id `
                -ProjectRoot $ProjectRoot `
                -CommandMarker 'different-marker' `
                -ServiceName 'test'

            $caught = $null
            try {
                Stop-ProjectProcess `
                    -StatePath $statePath `
                    -ExpectedProjectRoot $ProjectRoot `
                    -ExpectedCommandMarker 'different-marker'
            }
            catch {
                $caught = $_
            }

            $caught | Should Not BeNullOrEmpty
            $caught.Exception.Message | Should Match 'does not belong to this project'
            (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) |
                Should Not BeNullOrEmpty
            Test-Path -LiteralPath $statePath | Should Be $true
        }
        finally {
            if (-not $process.HasExited) {
                Stop-Process -Id $process.Id -Force
            }
        }
    }

    It 'stops and clears state only after ownership validation succeeds' {
        $arguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "managed-marker $ProjectRoot --port 8787" +
            '"'
        )
        $process = Start-Process `
            -FilePath powershell.exe `
            -ArgumentList $arguments `
            -WindowStyle Hidden `
            -PassThru
        $statePath = Join-Path $TestDrive 'managed.json'
        try {
            Save-ProcessState `
                -StatePath $statePath `
                -Id $process.Id `
                -ProjectRoot $ProjectRoot `
                -CommandMarker 'managed-marker' `
                -ServiceName 'test' `
                -ArgumentList $arguments `
                -Port 8787

            $result = Stop-ProjectProcess `
                -StatePath $statePath `
                -ExpectedProjectRoot $ProjectRoot `
                -ExpectedCommandMarker 'managed-marker'

            $result | Should Be $true
            (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) |
                Should BeNullOrEmpty
            Test-Path -LiteralPath $statePath | Should Be $false
        }
        finally {
            if (-not $process.HasExited) {
                Stop-Process -Id $process.Id -Force
            }
        }
    }

    It 'is idempotent when no process state exists' {
        Stop-ProjectProcess `
            -StatePath (Join-Path $TestDrive 'missing.json') `
            -ExpectedProjectRoot $ProjectRoot `
            -ExpectedCommandMarker 'missing-marker' |
            Should Be $false
    }

    It 'clears stale state without stopping any other process' {
        $statePath = Join-Path $TestDrive 'stale.json'
        Save-ProcessState `
            -StatePath $statePath `
            -Id 2147483000 `
            -ProjectRoot $ProjectRoot `
            -CommandMarker 'stale-marker' `
            -ServiceName 'test'

        Stop-ProjectProcess `
            -StatePath $statePath `
            -ExpectedProjectRoot $ProjectRoot `
            -ExpectedCommandMarker 'stale-marker' |
            Should Be $false
        Test-Path -LiteralPath $statePath | Should Be $false
    }

    It 'refuses to stop a PID-reused process whose real arguments differ from state' {
        $marker = 'pid-reuse-stop-marker'
        $actualArguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "$marker $ProjectRoot --port 9999 reused" +
            '"'
        )
        $savedArguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "$marker $ProjectRoot --port 8787 expected" +
            '"'
        )
        $process = Start-Process `
            -FilePath powershell.exe `
            -ArgumentList $actualArguments `
            -WindowStyle Hidden `
            -PassThru
        $statePath = Join-Path $TestDrive 'pid-reuse-stop.json'
        try {
            Start-Sleep -Milliseconds 150
            Save-ProcessState `
                -StatePath $statePath `
                -Id $process.Id `
                -ProjectRoot $ProjectRoot `
                -CommandMarker $marker `
                -ServiceName 'test' `
                -ArgumentList $savedArguments `
                -Port 8787

            {
                Stop-ProjectProcess `
                    -StatePath $statePath `
                    -ExpectedProjectRoot $ProjectRoot `
                    -ExpectedCommandMarker $marker
            } | Should Throw

            (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) |
                Should Not BeNullOrEmpty
            Test-Path -LiteralPath $statePath | Should Be $true
        }
        finally {
            $remaining = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
            if ($null -ne $remaining) {
                Stop-Process -Id $process.Id -Force
            }
        }
    }

    It 'refuses extra live arguments that are absent from saved launch state' {
        $marker = 'extra-argument-stop-marker'
        $savedArguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "$marker $ProjectRoot --port 8787" +
            '"'
        )
        $actualArguments = "-NoLogo $savedArguments"
        $process = Start-Process `
            -FilePath powershell.exe `
            -ArgumentList $actualArguments `
            -WindowStyle Hidden `
            -PassThru
        $statePath = Join-Path $TestDrive 'extra-argument-stop.json'
        try {
            Start-Sleep -Milliseconds 150
            Save-ProcessState `
                -StatePath $statePath `
                -Id $process.Id `
                -ProjectRoot $ProjectRoot `
                -CommandMarker $marker `
                -ServiceName 'test' `
                -ArgumentList $savedArguments `
                -Port 8787

            {
                Stop-ProjectProcess `
                    -StatePath $statePath `
                    -ExpectedProjectRoot $ProjectRoot `
                    -ExpectedCommandMarker $marker
            } | Should Throw

            (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) |
                Should Not BeNullOrEmpty
            Test-Path -LiteralPath $statePath | Should Be $true
        }
        finally {
            $remaining = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
            if ($null -ne $remaining) {
                Stop-Process -Id $process.Id -Force
            }
        }
    }

    It 'refuses to stop the same arguments under a different executable' {
        $marker = 'executable-mismatch-stop-marker'
        $arguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "$marker $ProjectRoot --port 8787" +
            '"'
        )
        $expectedExecutable = (
            Get-Command powershell.exe -ErrorAction Stop
        ).Source
        $alternateExecutable = (
            Join-Path $env:WINDIR `
                'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
        )
        Test-Path -LiteralPath $alternateExecutable | Should Be $true
        $process = Start-Process `
            -FilePath $alternateExecutable `
            -ArgumentList $arguments `
            -WindowStyle Hidden `
            -PassThru
        $statePath = Join-Path $TestDrive 'executable-mismatch-stop.json'
        try {
            Start-Sleep -Milliseconds 150
            Save-ProcessState `
                -StatePath $statePath `
                -Id $process.Id `
                -ProjectRoot $ProjectRoot `
                -CommandMarker $marker `
                -ServiceName 'test' `
                -ArgumentList $arguments `
                -Port 8787
            Set-TestProcessIdentity `
                -StatePath $statePath `
                -ExecutablePath $expectedExecutable `
                -ProcessStartTimeUtc (
                    $process.StartTime.ToUniversalTime().ToString('o')
                )

            {
                Stop-ProjectProcess `
                    -StatePath $statePath `
                    -ExpectedProjectRoot $ProjectRoot `
                    -ExpectedCommandMarker $marker
            } | Should Throw

            (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) |
                Should Not BeNullOrEmpty
            Test-Path -LiteralPath $statePath | Should Be $true
        }
        finally {
            $remaining = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
            if ($null -ne $remaining) {
                Stop-Process -Id $process.Id -Force
            }
        }
    }

    It 'refuses to stop a different creation identity with the same executable and arguments' {
        $marker = 'creation-mismatch-stop-marker'
        $arguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "$marker $ProjectRoot --port 8787" +
            '"'
        )
        $executable = (Get-Command powershell.exe -ErrorAction Stop).Source
        $process = Start-Process `
            -FilePath $executable `
            -ArgumentList $arguments `
            -WindowStyle Hidden `
            -PassThru
        $statePath = Join-Path $TestDrive 'creation-mismatch-stop.json'
        try {
            Start-Sleep -Milliseconds 150
            Save-ProcessState `
                -StatePath $statePath `
                -Id $process.Id `
                -ProjectRoot $ProjectRoot `
                -CommandMarker $marker `
                -ServiceName 'test' `
                -ArgumentList $arguments `
                -Port 8787
            Set-TestProcessIdentity `
                -StatePath $statePath `
                -ExecutablePath $executable `
                -ProcessStartTimeUtc (
                    $process.StartTime.
                        ToUniversalTime().
                        AddSeconds(-1).
                        ToString('o')
                )

            {
                Stop-ProjectProcess `
                    -StatePath $statePath `
                    -ExpectedProjectRoot $ProjectRoot `
                    -ExpectedCommandMarker $marker
            } | Should Throw

            (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) |
                Should Not BeNullOrEmpty
            Test-Path -LiteralPath $statePath | Should Be $true
        }
        finally {
            $remaining = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
            if ($null -ne $remaining) {
                Stop-Process -Id $process.Id -Force
            }
        }
    }

    It 'refuses to stop a live process when legacy state has no creation identity' {
        $marker = 'missing-identity-stop-marker'
        $arguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "$marker $ProjectRoot --port 8787" +
            '"'
        )
        $process = Start-Process `
            -FilePath powershell.exe `
            -ArgumentList $arguments `
            -WindowStyle Hidden `
            -PassThru
        $statePath = Join-Path $TestDrive 'missing-identity-stop.json'
        try {
            Start-Sleep -Milliseconds 150
            Save-ProcessState `
                -StatePath $statePath `
                -Id $process.Id `
                -ProjectRoot $ProjectRoot `
                -CommandMarker $marker `
                -ServiceName 'test' `
                -ArgumentList $arguments `
                -Port 8787
            $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 |
                ConvertFrom-Json
            $state.PSObject.Properties.Remove('executable_path')
            $state.PSObject.Properties.Remove('process_start_time_utc')
            [IO.File]::WriteAllText(
                $statePath,
                ($state | ConvertTo-Json),
                (New-Object Text.UTF8Encoding($false))
            )

            {
                Stop-ProjectProcess `
                    -StatePath $statePath `
                    -ExpectedProjectRoot $ProjectRoot `
                    -ExpectedCommandMarker $marker
            } | Should Throw

            (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) |
                Should Not BeNullOrEmpty
            Test-Path -LiteralPath $statePath | Should Be $true
        }
        finally {
            $remaining = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
            if ($null -ne $remaining) {
                Stop-Process -Id $process.Id -Force
            }
        }
    }
}

Describe 'Idempotent process startup' {
    It 'returns the existing owned PID instead of launching a duplicate' {
        $statePath = Join-Path $TestDrive 'start.json'
        $arguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "start-marker $ProjectRoot --port 8787" +
            '"'
        )
        $first = $null
        try {
            $first = Start-ProjectProcess `
                -FilePath powershell.exe `
                -ArgumentList $arguments `
                -WorkingDirectory $ProjectRoot `
                -StatePath $statePath `
                -ProjectRoot $ProjectRoot `
                -CommandMarker 'start-marker' `
                -ServiceName 'test' `
                -Port 8787
            $second = Start-ProjectProcess `
                -FilePath powershell.exe `
                -ArgumentList $arguments `
                -WorkingDirectory $ProjectRoot `
                -StatePath $statePath `
                -ProjectRoot $ProjectRoot `
                -CommandMarker 'start-marker' `
                -ServiceName 'test' `
                -Port 8787

            $second.Id | Should Be $first.Id
            Stop-ProjectProcess `
                -StatePath $statePath `
                -ExpectedProjectRoot $ProjectRoot `
                -ExpectedCommandMarker 'start-marker' |
                Should Be $true
        }
        finally {
            if ($null -ne $first) {
                $remaining = Get-Process -Id $first.Id -ErrorAction SilentlyContinue
                if ($null -ne $remaining) {
                    Stop-Process -Id $first.Id -Force
                }
            }
        }
    }

    It 'refuses a different launch port without reusing or stopping the live process' {
        $statePath = Join-Path $TestDrive 'different-port.json'
        $marker = 'different-port-marker'
        $firstArguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "$marker $ProjectRoot --port 8787" +
            '"'
        )
        $secondArguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "$marker $ProjectRoot --port 9999" +
            '"'
        )
        $first = $null
        try {
            $first = Start-ProjectProcess `
                -FilePath powershell.exe `
                -ArgumentList $firstArguments `
                -WorkingDirectory $ProjectRoot `
                -StatePath $statePath `
                -ProjectRoot $ProjectRoot `
                -CommandMarker $marker `
                -ServiceName 'test' `
                -Port 8787

            {
                Start-ProjectProcess `
                    -FilePath powershell.exe `
                    -ArgumentList $secondArguments `
                    -WorkingDirectory $ProjectRoot `
                    -StatePath $statePath `
                    -ProjectRoot $ProjectRoot `
                    -CommandMarker $marker `
                    -ServiceName 'test' `
                    -Port 9999
            } | Should Throw

            (Get-Process -Id $first.Id -ErrorAction SilentlyContinue) |
                Should Not BeNullOrEmpty
            $saved = Get-ProcessState -StatePath $statePath
            $saved.pid | Should Be $first.Id
            $saved.port | Should Be 8787
            $saved.argument_list | Should Be $firstArguments
        }
        finally {
            if (Test-Path -LiteralPath $statePath) {
                Stop-ProjectProcess `
                    -StatePath $statePath `
                    -ExpectedProjectRoot $ProjectRoot `
                    -ExpectedCommandMarker $marker |
                    Out-Null
            }
            if ($null -ne $first) {
                $remaining = Get-Process -Id $first.Id -ErrorAction SilentlyContinue
                if ($null -ne $remaining) {
                    Stop-Process -Id $first.Id -Force
                }
            }
        }
    }

    It 'does not reuse a PID whose real command line differs from saved launch state' {
        $statePath = Join-Path $TestDrive 'pid-reuse-start.json'
        $marker = 'pid-reuse-start-marker'
        $actualArguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "$marker $ProjectRoot --port 9999 reused" +
            '"'
        )
        $savedArguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "$marker $ProjectRoot --port 8787 expected" +
            '"'
        )
        $process = Start-Process `
            -FilePath powershell.exe `
            -ArgumentList $actualArguments `
            -WindowStyle Hidden `
            -PassThru
        try {
            Start-Sleep -Milliseconds 150
            Save-ProcessState `
                -StatePath $statePath `
                -Id $process.Id `
                -ProjectRoot $ProjectRoot `
                -CommandMarker $marker `
                -ServiceName 'test' `
                -ArgumentList $savedArguments `
                -Port 8787

            {
                Start-ProjectProcess `
                    -FilePath powershell.exe `
                    -ArgumentList $savedArguments `
                    -WorkingDirectory $ProjectRoot `
                    -StatePath $statePath `
                    -ProjectRoot $ProjectRoot `
                    -CommandMarker $marker `
                    -ServiceName 'test' `
                    -Port 8787
            } | Should Throw

            (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) |
                Should Not BeNullOrEmpty
            $saved = Get-ProcessState -StatePath $statePath
            $saved.pid | Should Be $process.Id
        }
        finally {
            $remaining = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
            if ($null -ne $remaining) {
                Stop-Process -Id $process.Id -Force
            }
        }
    }

    It 'does not reuse the same arguments under a different executable' {
        $statePath = Join-Path $TestDrive 'executable-mismatch-start.json'
        $marker = 'executable-mismatch-start-marker'
        $arguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "$marker $ProjectRoot --port 8787" +
            '"'
        )
        $expectedExecutable = (
            Get-Command powershell.exe -ErrorAction Stop
        ).Source
        $alternateExecutable = (
            Join-Path $env:WINDIR `
                'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
        )
        Test-Path -LiteralPath $alternateExecutable | Should Be $true
        $process = Start-Process `
            -FilePath $alternateExecutable `
            -ArgumentList $arguments `
            -WindowStyle Hidden `
            -PassThru
        try {
            Start-Sleep -Milliseconds 150
            Save-ProcessState `
                -StatePath $statePath `
                -Id $process.Id `
                -ProjectRoot $ProjectRoot `
                -CommandMarker $marker `
                -ServiceName 'test' `
                -ArgumentList $arguments `
                -Port 8787
            Set-TestProcessIdentity `
                -StatePath $statePath `
                -ExecutablePath $expectedExecutable `
                -ProcessStartTimeUtc (
                    $process.StartTime.ToUniversalTime().ToString('o')
                )

            {
                Start-ProjectProcess `
                    -FilePath $expectedExecutable `
                    -ArgumentList $arguments `
                    -WorkingDirectory $ProjectRoot `
                    -StatePath $statePath `
                    -ProjectRoot $ProjectRoot `
                    -CommandMarker $marker `
                    -ServiceName 'test' `
                    -Port 8787
            } | Should Throw

            (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) |
                Should Not BeNullOrEmpty
            (Get-ProcessState -StatePath $statePath).pid |
                Should Be $process.Id
        }
        finally {
            $remaining = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
            if ($null -ne $remaining) {
                Stop-Process -Id $process.Id -Force
            }
        }
    }

    It 'does not reuse a different creation identity with the same executable and arguments' {
        $statePath = Join-Path $TestDrive 'creation-mismatch-start.json'
        $marker = 'creation-mismatch-start-marker'
        $arguments = (
            '-NoProfile -Command "Start-Sleep -Seconds 30 # ' +
            "$marker $ProjectRoot --port 8787" +
            '"'
        )
        $executable = (Get-Command powershell.exe -ErrorAction Stop).Source
        $process = Start-Process `
            -FilePath $executable `
            -ArgumentList $arguments `
            -WindowStyle Hidden `
            -PassThru
        try {
            Start-Sleep -Milliseconds 150
            Save-ProcessState `
                -StatePath $statePath `
                -Id $process.Id `
                -ProjectRoot $ProjectRoot `
                -CommandMarker $marker `
                -ServiceName 'test' `
                -ArgumentList $arguments `
                -Port 8787
            Set-TestProcessIdentity `
                -StatePath $statePath `
                -ExecutablePath $executable `
                -ProcessStartTimeUtc (
                    $process.StartTime.
                        ToUniversalTime().
                        AddSeconds(-1).
                        ToString('o')
                )

            {
                Start-ProjectProcess `
                    -FilePath $executable `
                    -ArgumentList $arguments `
                    -WorkingDirectory $ProjectRoot `
                    -StatePath $statePath `
                    -ProjectRoot $ProjectRoot `
                    -CommandMarker $marker `
                    -ServiceName 'test' `
                    -Port 8787
            } | Should Throw

            (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) |
                Should Not BeNullOrEmpty
            (Get-ProcessState -StatePath $statePath).pid |
                Should Be $process.Id
        }
        finally {
            $remaining = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
            if ($null -ne $remaining) {
                Stop-Process -Id $process.Id -Force
            }
        }
    }
}

Describe 'Atomic data backup and restore' {
    BeforeEach {
        . (Join-Path $ProjectRoot 'scripts\Backup.ps1')
        . (Join-Path $ProjectRoot 'scripts\Restore.ps1') -BackupPath $TestDrive

        $caseId = [guid]::NewGuid().ToString('N')
        $script:DataProjectRoot = Join-Path $TestDrive "data-project-$caseId"
        $script:BackupRoot = Join-Path $TestDrive "backups-$caseId"
        New-Item -ItemType Directory -Path (
            Join-Path $script:DataProjectRoot '.runtime'
        ) -Force | Out-Null
        New-Item -ItemType Directory -Path (
            Join-Path $script:DataProjectRoot 'data\market'
        ) -Force | Out-Null
        $script:RealPython = (Get-Command python -ErrorAction Stop).Source
        $venvScripts = Join-Path $script:DataProjectRoot '.venv\Scripts'
        New-Item -ItemType Directory -Path $venvScripts -Force | Out-Null
        $venvPython = Join-Path $venvScripts 'python.ps1'
        [IO.File]::WriteAllText(
            $venvPython,
            (
                "param(`r`n" +
                "    [string]`$c,`r`n" +
                '    [Parameter(ValueFromRemainingArguments = $true)]' +
                "`r`n    [object[]]`$PythonArguments`r`n" +
                ")`r`n" +
                ('& "{0}" -c $c @PythonArguments' -f $script:RealPython) +
                "`r`nexit `$LASTEXITCODE`r`n"
            ),
            (New-Object Text.UTF8Encoding($false))
        )
        $env:DRAWDOWN_TEST_DATA_ROOT = $script:DataProjectRoot
        try {
            @'
import os
import sqlite3
from pathlib import Path
import pandas as pd

root = Path(os.environ["DRAWDOWN_TEST_DATA_ROOT"])
for path in (root / ".runtime" / "drawdown.sqlite", root / "data" / "catalog.sqlite"):
    with sqlite3.connect(path) as connection:
        connection.execute("create table sample(value text)")
        connection.execute("insert into sample values ('original')")
pd.DataFrame({"close": [100.0, 101.0]}).to_parquet(
    root / "data" / "market" / "QQQ.parquet"
)
'@ | & $script:RealPython -
            if ($LASTEXITCODE -ne 0) {
                throw 'Unable to create backup fixtures.'
            }
        }
        finally {
            Remove-Item Env:DRAWDOWN_TEST_DATA_ROOT
        }
    }

    It 'publishes a verified backup only after every SQLite and Parquet file is staged' {
        $backup = New-DrawdownBackup `
            -ProjectRoot $script:DataProjectRoot `
            -DestinationRoot $script:BackupRoot `
            -Name 'snapshot'

        $backup | Should Be (Join-Path $script:BackupRoot 'snapshot')
        Test-Path -LiteralPath (Join-Path $backup 'manifest.json') |
            Should Be $true
        $manifest = Get-Content `
            -LiteralPath (Join-Path $backup 'manifest.json') `
            -Raw `
            -Encoding UTF8 |
            ConvertFrom-Json
        @($manifest.files).Count | Should Be 3
        ($manifest.files.kind -join ',') | Should Match 'sqlite'
        ($manifest.files.kind -join ',') | Should Match 'parquet'
        @(Get-ChildItem -LiteralPath $script:BackupRoot -Filter '*.tmp').Count |
            Should Be 0
    }

    It 'verifies then restores every artifact through staged atomic switches' {
        $backup = New-DrawdownBackup `
            -ProjectRoot $script:DataProjectRoot `
            -DestinationRoot $script:BackupRoot `
            -Name 'restore-source'
        $runtimeDatabase = Join-Path $script:DataProjectRoot '.runtime\drawdown.sqlite'
        $bytes = [IO.File]::ReadAllBytes($runtimeDatabase)
        [IO.File]::WriteAllBytes($runtimeDatabase, $bytes[0..31])

        Restore-DrawdownBackup `
            -ProjectRoot $script:DataProjectRoot `
            -BackupPath $backup

        $manifest = Get-Content `
            -LiteralPath (Join-Path $backup 'manifest.json') `
            -Raw `
            -Encoding UTF8 |
            ConvertFrom-Json
        foreach ($entry in $manifest.files) {
            $restored = Join-Path $script:DataProjectRoot $entry.path
            (Get-FileHash -LiteralPath $restored -Algorithm SHA256).Hash |
                Should Be $entry.sha256
        }
    }

    It 'refuses to restore while a managed runtime state is present' {
        $backup = New-DrawdownBackup `
            -ProjectRoot $script:DataProjectRoot `
            -DestinationRoot $script:BackupRoot `
            -Name 'runtime-guard'
        $processState = Join-Path $script:DataProjectRoot '.runtime\api-process.json'
        [IO.File]::WriteAllText($processState, '{"schema_version":1}')
        $caught = $null

        try {
            Restore-DrawdownBackup `
                -ProjectRoot $script:DataProjectRoot `
                -BackupPath $backup
        }
        catch {
            $caught = $_
        }

        $caught | Should Not BeNullOrEmpty
        $caught.Exception.Message | Should Match 'Stop.ps1'
    }

    It 'rejects a manifest target outside the runtime and data allowlist before writing' {
        $backup = New-DrawdownBackup `
            -ProjectRoot $script:DataProjectRoot `
            -DestinationRoot $script:BackupRoot `
            -Name 'allowlist-source'
        $manifestPath = Join-Path $backup 'manifest.json'
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $entry = $manifest.files | Select-Object -First 1
        $entry.path = 'scripts/escaped.db'
        $source = Join-Path $backup $entry.path
        New-Item -ItemType Directory -Path (Split-Path -Parent $source) -Force |
            Out-Null
        Copy-Item `
            -LiteralPath (Join-Path $backup '.runtime\drawdown.sqlite') `
            -Destination $source
        $entry.sha256 = (
            Get-FileHash -LiteralPath $source -Algorithm SHA256
        ).Hash
        $entry.size = (Get-Item -LiteralPath $source).Length
        $manifest | ConvertTo-Json -Depth 10 |
            Set-Content -LiteralPath $manifestPath -Encoding UTF8

        {
            Restore-DrawdownBackup `
                -ProjectRoot $script:DataProjectRoot `
                -BackupPath $backup
        } | Should Throw

        Test-Path -LiteralPath (
            Join-Path $script:DataProjectRoot 'scripts\escaped.db'
        ) | Should Be $false
    }

    It 'rejects a junction in the restore target before touching its external file' {
        if ($env:OS -ne 'Windows_NT') {
            return
        }
        $backup = New-DrawdownBackup `
            -ProjectRoot $script:DataProjectRoot `
            -DestinationRoot $script:BackupRoot `
            -Name 'junction-source'
        $backupSource = Join-Path $backup 'data\link\escaped.db'
        New-Item -ItemType Directory -Path (Split-Path -Parent $backupSource) -Force |
            Out-Null
        Copy-Item `
            -LiteralPath (Join-Path $backup '.runtime\drawdown.sqlite') `
            -Destination $backupSource
        $manifestPath = Join-Path $backup 'manifest.json'
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $manifest.files = @(
            [pscustomobject]@{
                path = 'data/link/escaped.db'
                kind = 'sqlite'
                size = (Get-Item -LiteralPath $backupSource).Length
                sha256 = (
                    Get-FileHash -LiteralPath $backupSource -Algorithm SHA256
                ).Hash
            }
        )
        $manifest | ConvertTo-Json -Depth 10 |
            Set-Content -LiteralPath $manifestPath -Encoding UTF8

        $outside = Join-Path $TestDrive "outside-$caseId"
        New-Item -ItemType Directory -Path $outside -Force | Out-Null
        $outsideFile = Join-Path $outside 'escaped.db'
        Copy-Item `
            -LiteralPath (Join-Path $script:DataProjectRoot 'data\catalog.sqlite') `
            -Destination $outsideFile
        $beforeHash = (Get-FileHash -LiteralPath $outsideFile -Algorithm SHA256).Hash
        New-Item `
            -ItemType Junction `
            -Path (Join-Path $script:DataProjectRoot 'data\link') `
            -Target $outside |
            Out-Null

        {
            Restore-DrawdownBackup `
                -ProjectRoot $script:DataProjectRoot `
                -BackupPath $backup
        } | Should Throw

        (Get-FileHash -LiteralPath $outsideFile -Algorithm SHA256).Hash |
            Should Be $beforeHash
    }

    It 'uses the project virtualenv when PATH python cannot load Parquet support' {
        $fakeBin = Join-Path $TestDrive "fake-python-$caseId"
        New-Item -ItemType Directory -Path $fakeBin -Force | Out-Null
        [IO.File]::WriteAllText(
            (Join-Path $fakeBin 'python.cmd'),
            "@echo off`r`nexit /b 97`r`n",
            [Text.Encoding]::ASCII
        )
        $previousPath = $env:PATH
        try {
            $env:PATH = "$fakeBin;$previousPath"
            $backup = New-DrawdownBackup `
                -ProjectRoot $script:DataProjectRoot `
                -DestinationRoot $script:BackupRoot `
                -Name 'venv-python'
        }
        finally {
            $env:PATH = $previousPath
        }

        Test-Path -LiteralPath (Join-Path $backup 'manifest.json') |
            Should Be $true
    }
}

Describe 'Privacy-safe API wrappers' {
    BeforeEach {
        . (Join-Path $ProjectRoot 'scripts\Update-Data.ps1')
        . (Join-Path $ProjectRoot 'scripts\Analyze.ps1') `
            -Config (Join-Path $TestDrive 'placeholder.json')
    }

    It 'posts the versioned update contract and prints only a safe summary' {
        Mock Invoke-RestMethod {
            [pscustomobject]@{
                schema_version = '1.0'
                status = 'completed'
                cutoff = '2026-06-30'
                request_count = 2
                refreshed_symbols = @('QQQ', 'SPY')
                message = 'private-provider-detail'
                secret = 'sk-never-print'
            }
        }

        $summary = Invoke-DrawdownDataUpdate `
            -ApiBaseUrl 'http://127.0.0.1:8787' `
            -AsOf ([datetime]'2026-07-26')

        $summary.Status | Should Be 'completed'
        $summary.RequestCount | Should Be 2
        ($summary | Out-String) | Should Not Match 'private-provider-detail'
        ($summary | Out-String) | Should Not Match 'sk-never-print'
        Assert-MockCalled Invoke-RestMethod 1 -ParameterFilter {
            $Uri -eq 'http://127.0.0.1:8787/api/v1/data/update' -and
            $Method -eq 'Post' -and
            $Body -match '"schema_version":"1.0"' -and
            $Body -match '"as_of":"2026-07-26"'
        }
    }

    It 'writes the full analysis response privately but prints no config or payload' {
        $configPath = Join-Path $TestDrive 'private-analysis.json'
        [IO.File]::WriteAllText(
            $configPath,
            '{"schema_version":"1.0","name":"MY_PRIVATE_STRATEGY"}',
            (New-Object Text.UTF8Encoding($false))
        )
        $outFile = Join-Path $TestDrive 'analysis-response.json'
        Mock Invoke-RestMethod {
            [pscustomobject]@{
                schema_version = '1.0'
                job_id = 'job-safe-123'
                status = 'queued'
                payload = @{
                    strategy_name = 'MY_PRIVATE_STRATEGY'
                    secret = 'sk-never-print'
                }
            }
        }

        $summary = Invoke-DrawdownAnalysis `
            -ConfigPath $configPath `
            -Endpoint 'optimization' `
            -ApiBaseUrl 'http://127.0.0.1:8787' `
            -OutFile $outFile

        $summary.JobId | Should Be 'job-safe-123'
        Test-Path -LiteralPath $outFile | Should Be $true
        ($summary | Out-String) | Should Not Match 'MY_PRIVATE_STRATEGY'
        ($summary | Out-String) | Should Not Match 'sk-never-print'
        Assert-MockCalled Invoke-RestMethod 1 -ParameterFilter {
            $Uri -eq 'http://127.0.0.1:8787/api/v1/optimizations' -and
            $Method -eq 'Post'
        }
    }
}

Describe 'One-click lifecycle dry runs' {
    It 'plans a same-origin API and SPA runtime on loopback' {
        $plan = & (Join-Path $ProjectRoot 'scripts\Start.ps1') `
            -ApiPort 9876 `
            -SkipInstall `
            -SkipBuild `
            -DryRun

        $plan.Host | Should Be '127.0.0.1'
        $plan.Port | Should Be 9876
        $plan.Factory | Should Be 'drawdown_lab.runtime:create_runtime_app'
        $plan.WillUpdateData | Should Be $true
        $plan.PublicAccessProtected | Should Be $true
    }

    It 'plans only the dedicated Funnel path' {
        $plan = & (Join-Path $ProjectRoot 'scripts\Open-Funnel.ps1') `
            -Target '127.0.0.1:9876' `
            -DryRun

        $plan.Target | Should Be '127.0.0.1:9876'
        $plan.PublicPath | Should Be '/drawdown-ledger'
        $plan.MutatesFunnel | Should Be $false
    }

    It 'plans project-state cleanup without touching a process or Funnel' {
        $plan = & (Join-Path $ProjectRoot 'scripts\Stop.ps1') -DryRun

        $plan.Action | Should Be 'stop'
        $plan.RestoreFunnel | Should Be $true
        $plan.MutatesProcesses | Should Be $false
    }
}

Describe 'Startup data update degradation' {
    BeforeAll {
        . (Join-Path $ProjectRoot 'scripts\Start.ps1')
    }

    It 'continues with stale cache and an explicit zero-exit policy when update fails' {
        $command = Get-Command `
            Invoke-StartupDataUpdate `
            -ErrorAction SilentlyContinue
        $command | Should Not BeNullOrEmpty
        if ($null -eq $command) {
            return
        }

        $result = Invoke-StartupDataUpdate `
            -UpdateAction {
                throw 'provider unavailable'
            } `
            -WarningAction SilentlyContinue

        $result.Status | Should Be 'stale-cache'
        $result.Degraded | Should Be $true
        $result.ExitPolicy | Should Be 'continue-running'
        $result.Message |
            Should Be 'Data update failed; continuing with the existing cache.'
        ($result | Out-String) | Should Not Match 'provider unavailable'
    }
}
