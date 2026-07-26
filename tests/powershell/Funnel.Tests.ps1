$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$ModulePath = Join-Path $ProjectRoot 'scripts\lib\FunnelState.psm1'
Import-Module $ModulePath -Force

function Write-TestFunnelState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [AllowNull()]
        [object]$PreviousRoute = $null
    )

    [IO.File]::WriteAllText(
        $Path,
        (@{
            schema_version = 2
            replacement_target = '127.0.0.1:8787'
            public_path = '/drawdown-ledger'
            https_port = 443
            previous_route = $PreviousRoute
        } | ConvertTo-Json -Depth 10),
        (New-Object Text.UTF8Encoding($false))
    )
}

Describe 'Funnel state module contract' {
    It 'exports only path-scoped Funnel lifecycle mutations' {
        Get-Command Open-DrawdownFunnel -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Restore-DrawdownFunnel -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Get-FunnelStatus -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Set-FunnelTarget -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Remove-FunnelTarget -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command ConvertFrom-FunnelStatusJson -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Invoke-TailscaleCommand -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Set-FunnelConfiguration -ErrorAction SilentlyContinue |
            Should BeNullOrEmpty
        Get-Command Get-FunnelRestoreCommands -ErrorAction SilentlyContinue |
            Should BeNullOrEmpty
    }
}

Describe 'Funnel path acquisition' {
    It 'does not replace another target at the dedicated path without consent' {
        Mock Get-FunnelStatus {
            @{
                Occupied = $true
                Routes = @(
                    @{
                        Path = '/drawdown-ledger'
                        Target = '127.0.0.1:4174'
                        PublicUrl = 'https://host/drawdown-ledger'
                        HttpsPort = 443
                    }
                )
                RawJson = '{"occupied":true}'
            }
        } -ModuleName FunnelState
        Mock Set-FunnelTarget {} -ModuleName FunnelState

        {
            Open-DrawdownFunnel `
                -Target '127.0.0.1:8787' `
                -PublicPath '/drawdown-ledger' `
                -StatePath (Join-Path $TestDrive 'collision.json')
        } | Should Throw

        Assert-MockCalled Set-FunnelTarget 0 -ModuleName FunnelState -Scope It
    }

    It 'does not overwrite an unsupported handler at the dedicated path' {
        $status = ConvertFrom-FunnelStatusJson -RawJson @'
{"TCP":{"443":{"HTTPS":true}},"Web":{"host.ts.net:443":{"Handlers":{"/drawdown-ledger":{"Text":"owned elsewhere"},"/other":{"Proxy":"http://127.0.0.1:4174/"}}}}}
'@
        $unsupportedRoutes = @(
            $status.Routes |
                Where-Object { $_.Path -eq '/drawdown-ledger' }
        )
        $unsupportedRoutes.Count | Should Be 1
        if ($unsupportedRoutes.Count -ne 1) {
            return
        }
        $global:DrawdownUnsupportedStatus = $status
        Mock Get-FunnelStatus {
            $global:DrawdownUnsupportedStatus
        } -ModuleName FunnelState
        Mock Set-FunnelTarget {} -ModuleName FunnelState
        $caught = $null

        try {
            try {
                Open-DrawdownFunnel `
                    -Target '127.0.0.1:8787' `
                    -PublicPath '/drawdown-ledger' `
                    -StatePath (Join-Path $TestDrive 'unsupported.json')
            }
            catch {
                $caught = $_
            }
        }
        finally {
            Remove-Variable `
                -Name DrawdownUnsupportedStatus `
                -Scope Global `
                -ErrorAction SilentlyContinue
        }

        $caught | Should Not BeNullOrEmpty
        $caught.Exception.Message | Should Match 'unsupported handler'
        Assert-MockCalled Set-FunnelTarget 0 -ModuleName FunnelState -Scope It
    }

    It 'is idempotent when the dedicated path already targets this project' {
        Mock Get-FunnelStatus {
            @{
                Occupied = $true
                Routes = @(
                    @{
                        Path = '/drawdown-ledger'
                        Target = '127.0.0.1:8787'
                        PublicUrl = 'https://host/drawdown-ledger'
                        HttpsPort = 443
                    }
                )
                RawJson = '{"owned":true}'
            }
        } -ModuleName FunnelState
        Mock Set-FunnelTarget {} -ModuleName FunnelState
        $statePath = Join-Path $TestDrive 'same-target.json'

        $result = Open-DrawdownFunnel `
            -Target '127.0.0.1:8787' `
            -PublicPath '/drawdown-ledger' `
            -StatePath $statePath

        $result.Target | Should Be '127.0.0.1:8787'
        Assert-MockCalled Set-FunnelTarget 0 -ModuleName FunnelState -Scope It
        Test-Path -LiteralPath $statePath | Should Be $false
    }

    It 'records path ownership without snapshotting unrelated routes' {
        Mock Get-FunnelStatus {
            @{
                Occupied = $true
                Routes = @(
                    @{
                        Path = '/eng-vocabulary'
                        Target = '127.0.0.1:4174'
                        HttpsPort = 443
                    },
                    @{
                        Path = '/leverage-etf'
                        Target = '127.0.0.1:4175/leverage-etf'
                        HttpsPort = 443
                    }
                )
                RawJson = '{"unrelated":true}'
            }
        } -ModuleName FunnelState
        Mock Set-FunnelTarget {} -ModuleName FunnelState
        $statePath = Join-Path $TestDrive 'dedicated-path.json'

        Open-DrawdownFunnel `
            -Target '127.0.0.1:8787' `
            -PublicPath '/drawdown-ledger' `
            -StatePath $statePath

        $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $saved.schema_version | Should Be 2
        $saved.public_path | Should Be '/drawdown-ledger'
        $saved.replacement_target | Should Be '127.0.0.1:8787'
        $saved.previous_route | Should BeNullOrEmpty
        $saved.PSObject.Properties['previous_raw_json'] | Should BeNullOrEmpty
        Assert-MockCalled Set-FunnelTarget 1 -ModuleName FunnelState -Scope It -ParameterFilter {
            $Target -eq '127.0.0.1:8787' -and
            $PublicPath -eq '/drawdown-ledger'
        }
    }

    It 'records only the previous route when replacement is explicit' {
        Mock Get-FunnelStatus {
            @{
                Occupied = $true
                Routes = @(
                    @{
                        Path = '/drawdown-ledger'
                        Target = '127.0.0.1:4174'
                        Proxy = 'http://127.0.0.1:4174/'
                        HttpsPort = 443
                    },
                    @{
                        Path = '/added-later'
                        Target = '127.0.0.1:9900'
                        HttpsPort = 443
                    }
                )
                RawJson = '{"routes":true}'
            }
        } -ModuleName FunnelState
        Mock Set-FunnelTarget {} -ModuleName FunnelState
        $statePath = Join-Path $TestDrive 'replace.json'

        Open-DrawdownFunnel `
            -Target '127.0.0.1:8787' `
            -PublicPath '/drawdown-ledger' `
            -StatePath $statePath `
            -ReplaceExisting

        $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $saved.previous_route.path | Should Be '/drawdown-ledger'
        $saved.previous_route.target | Should Be '127.0.0.1:4174'
        $saved.previous_route.proxy | Should Be 'http://127.0.0.1:4174/'
        ($saved | ConvertTo-Json -Depth 10) | Should Not Match 'added-later'
    }

    It 'never overwrites an unresolved ownership state' {
        Mock Get-FunnelStatus {
            @{
                Occupied = $false
                Routes = @()
                RawJson = '{}'
            }
        } -ModuleName FunnelState
        Mock Set-FunnelTarget {} -ModuleName FunnelState
        $statePath = Join-Path $TestDrive 'unresolved.json'
        [IO.File]::WriteAllText($statePath, '{"original":true}')

        {
            Open-DrawdownFunnel `
                -Target '127.0.0.1:8787' `
                -PublicPath '/drawdown-ledger' `
                -StatePath $statePath
        } | Should Throw

        (Get-Content -LiteralPath $statePath -Raw) | Should Be '{"original":true}'
        Assert-MockCalled Set-FunnelTarget 0 -ModuleName FunnelState -Scope It
    }
}

Describe 'Path-owned Funnel cleanup' {
    BeforeEach {
        $script:OwnedStatePath = Join-Path $TestDrive (
            'owned-{0}.json' -f [guid]::NewGuid().ToString('N')
        )
        Write-TestFunnelState -Path $script:OwnedStatePath
        Mock Invoke-TailscaleCommand {} -ModuleName FunnelState
    }

    It 'removes only its owned path and preserves a concurrently added route' {
        Mock Get-FunnelStatus {
            @{
                Occupied = $true
                Routes = @(
                    @{
                        Path = '/drawdown-ledger'
                        Target = '127.0.0.1:8787'
                        HttpsPort = 443
                    },
                    @{
                        Path = '/added-later'
                        Target = '127.0.0.1:9900'
                        HttpsPort = 443
                    }
                )
                RawJson = '{"concurrent":true}'
            }
        } -ModuleName FunnelState

        Restore-DrawdownFunnel -StatePath $script:OwnedStatePath |
            Should Be $true

        Assert-MockCalled Invoke-TailscaleCommand 1 -ModuleName FunnelState -Scope It
        Assert-MockCalled Invoke-TailscaleCommand 1 -ModuleName FunnelState -Scope It -ParameterFilter {
            $Arguments -join ' ' -eq (
                'funnel --yes --https 443 --set-path /drawdown-ledger off'
            )
        }
        Test-Path -LiteralPath $script:OwnedStatePath | Should Be $false
    }

    It 'refuses cleanup when the current path is no longer project-owned' {
        Mock Get-FunnelStatus {
            @{
                Occupied = $true
                Routes = @(
                    @{
                        Path = '/drawdown-ledger'
                        Target = '127.0.0.1:9999'
                        HttpsPort = 443
                    }
                )
                RawJson = '{"replaced":true}'
            }
        } -ModuleName FunnelState
        $caught = $null

        try {
            Restore-DrawdownFunnel -StatePath $script:OwnedStatePath
        }
        catch {
            $caught = $_
        }

        $caught | Should Not BeNullOrEmpty
        $caught.Exception.Message | Should Match 'no longer project-owned'
        Assert-MockCalled Invoke-TailscaleCommand 0 -ModuleName FunnelState -Scope It
        Test-Path -LiteralPath $script:OwnedStatePath | Should Be $true
    }

    It 'rejects a tampered snapshot that names a different public path' {
        [IO.File]::WriteAllText(
            $script:OwnedStatePath,
            (@{
                schema_version = 2
                replacement_target = '127.0.0.1:4174'
                public_path = '/eng-vocabulary'
                https_port = 443
                previous_route = $null
            } | ConvertTo-Json -Depth 10),
            (New-Object Text.UTF8Encoding($false))
        )
        Mock Get-FunnelStatus {
            @{
                Occupied = $true
                Routes = @(
                    @{
                        Path = '/eng-vocabulary'
                        Target = '127.0.0.1:4174'
                        HttpsPort = 443
                    }
                )
                RawJson = '{"existing":true}'
            }
        } -ModuleName FunnelState

        $caught = $null
        try {
            Restore-DrawdownFunnel `
                -StatePath $script:OwnedStatePath `
                -ExpectedPublicPath '/drawdown-ledger' `
                -ExpectedTarget '127.0.0.1:8787'
        }
        catch {
            $caught = $_
        }

        $caught | Should Not BeNullOrEmpty
        $caught.Exception.Message | Should Match 'ownership snapshot'
        Assert-MockCalled Get-FunnelStatus 0 -ModuleName FunnelState -Scope It
        Assert-MockCalled Invoke-TailscaleCommand 0 -ModuleName FunnelState -Scope It
        Test-Path -LiteralPath $script:OwnedStatePath | Should Be $true
    }

    It 'restores only the explicitly replaced path' {
        $previous = @{
            path = '/drawdown-ledger'
            target = '127.0.0.1:4174'
            proxy = 'http://127.0.0.1:4174/'
            https_port = 443
        }
        Write-TestFunnelState `
            -Path $script:OwnedStatePath `
            -PreviousRoute $previous
        Mock Get-FunnelStatus {
            @{
                Occupied = $true
                Routes = @(
                    @{
                        Path = '/drawdown-ledger'
                        Target = '127.0.0.1:8787'
                        HttpsPort = 443
                    },
                    @{
                        Path = '/added-later'
                        Target = '127.0.0.1:9900'
                        HttpsPort = 443
                    }
                )
                RawJson = '{"concurrent":true}'
            }
        } -ModuleName FunnelState
        Mock Set-FunnelTarget {} -ModuleName FunnelState

        Restore-DrawdownFunnel -StatePath $script:OwnedStatePath |
            Should Be $true

        Assert-MockCalled Set-FunnelTarget 1 -ModuleName FunnelState -Scope It -ParameterFilter {
            $Target -eq 'http://127.0.0.1:4174/' -and
            $PublicPath -eq '/drawdown-ledger' -and
            $HttpsPort -eq 443
        }
        Assert-MockCalled Invoke-TailscaleCommand 0 -ModuleName FunnelState -Scope It
    }

    It 'is idempotent when no ownership state exists' {
        $missing = Join-Path $TestDrive 'missing-state.json'
        Mock Get-FunnelStatus {} -ModuleName FunnelState

        Restore-DrawdownFunnel -StatePath $missing |
            Should Be $false

        Assert-MockCalled Get-FunnelStatus 0 -ModuleName FunnelState -Scope It
        Assert-MockCalled Invoke-TailscaleCommand 0 -ModuleName FunnelState -Scope It
    }
}

Describe 'Tailscale status parsing' {
    It 'reads every existing proxy route without mutating Funnel' {
        $rawJson = @'
{"TCP":{"443":{"HTTPS":true}},"Web":{"host.ts.net:443":{"Handlers":{"/one":{"Proxy":"http://127.0.0.1:4174/"},"/two":{"Proxy":"http://127.0.0.1:4175/two/"}}}},"AllowFunnel":{"host.ts.net:443":true}}
'@

        $status = ConvertFrom-FunnelStatusJson -RawJson $rawJson

        $status.Occupied | Should Be $true
        $status.Routes.Count | Should Be 2
        $status.Target | Should Be '127.0.0.1:4174'
        $status.PublicUrl | Should Be 'https://host.ts.net/one'
    }

    It 'parses an omitted Web map as an unoccupied Funnel' {
        $status = ConvertFrom-FunnelStatusJson -RawJson '{}'

        $status.Occupied | Should Be $false
        @($status.Routes).Count | Should Be 0
        $status.Target | Should BeNullOrEmpty
        $status.RawJson | Should Be '{}'
    }
}

Describe 'Tailscale Funnel mutations' {
    BeforeEach {
        Mock Invoke-TailscaleCommand {} -ModuleName FunnelState
    }

    It 'adds only the dedicated project path' {
        Set-FunnelTarget `
            -Target '127.0.0.1:8787' `
            -PublicPath '/drawdown-ledger'

        Assert-MockCalled Invoke-TailscaleCommand 1 -ModuleName FunnelState -Scope It -ParameterFilter {
            $Arguments -join ' ' -eq (
                'funnel --bg --yes --https 443 --set-path ' +
                '/drawdown-ledger 127.0.0.1:8787'
            )
        }
    }

    It 'removes only the dedicated project path without reset' {
        Remove-FunnelTarget -PublicPath '/drawdown-ledger' -HttpsPort 443

        Assert-MockCalled Invoke-TailscaleCommand 1 -ModuleName FunnelState -Scope It -ParameterFilter {
            $Arguments -join ' ' -eq (
                'funnel --yes --https 443 --set-path /drawdown-ledger off'
            )
        }
        Assert-MockCalled Invoke-TailscaleCommand 0 -ModuleName FunnelState -Scope It -ParameterFilter {
            $Arguments -contains 'reset'
        }
    }
}

Describe 'Tailscale command runner' {
    It 'passes arguments to the selected executable' {
        $fakeTailscale = Join-Path $TestDrive 'fake-tailscale.cmd'
        [IO.File]::WriteAllText(
            $fakeTailscale,
            "@echo off`r`necho %*`r`nexit /b 0`r`n",
            [Text.Encoding]::ASCII
        )

        $output = Invoke-TailscaleCommand `
            -Executable $fakeTailscale `
            -Arguments @('funnel', 'status', '--json')

        ($output -join ' ') | Should Match 'funnel status --json'
    }
}
