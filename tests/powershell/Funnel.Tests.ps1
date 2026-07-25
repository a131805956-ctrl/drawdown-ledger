$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$ModulePath = Join-Path $ProjectRoot 'scripts\lib\FunnelState.psm1'

Describe 'Funnel state module contract' {
    It 'exports the safe Funnel lifecycle commands' {
        Test-Path -LiteralPath $ModulePath | Should Be $true
        Import-Module $ModulePath -Force

        Get-Command Open-DrawdownFunnel -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Restore-DrawdownFunnel -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Get-FunnelStatus -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Set-FunnelTarget -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Set-FunnelConfiguration -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command ConvertFrom-FunnelStatusJson -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Invoke-TailscaleCommand -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
        Get-Command Get-FunnelRestoreCommands -ErrorAction SilentlyContinue |
            Should Not BeNullOrEmpty
    }
}

Describe 'Funnel replacement safety' {
    It 'does not replace another Funnel without ReplaceExisting' {
        Mock Get-FunnelStatus {
            @{
                Occupied = $true
                Target = '127.0.0.1:4174'
                PublicUrl = 'https://existing.example/eng-vocabulary'
                RawJson = '{"existing":true}'
            }
        } -ModuleName FunnelState
        Mock Set-FunnelTarget {} -ModuleName FunnelState

        $caught = $null
        try {
            Open-DrawdownFunnel `
                -Target '127.0.0.1:8787' `
                -StatePath (Join-Path $TestDrive 'funnel-state.json')
        }
        catch {
            $caught = $_
        }

        $caught | Should Not BeNullOrEmpty
        $caught.Exception.Message | Should Match 'already routes'

        Assert-MockCalled Set-FunnelTarget 0 -ModuleName FunnelState -Scope It
    }

    It 'is idempotent when Funnel already targets this project' {
        Mock Get-FunnelStatus {
            @{
                Occupied = $true
                Target = '127.0.0.1:8787'
                PublicUrl = 'https://drawdown.example'
                RawJson = '{"drawdown":true}'
            }
        } -ModuleName FunnelState
        Mock Set-FunnelTarget {} -ModuleName FunnelState

        $result = Open-DrawdownFunnel `
            -Target '127.0.0.1:8787' `
            -StatePath (Join-Path $TestDrive 'same-target.json')

        $result.Target | Should Be '127.0.0.1:8787'
        Assert-MockCalled Set-FunnelTarget 0 -ModuleName FunnelState
        Test-Path -LiteralPath (Join-Path $TestDrive 'same-target.json') |
            Should Be $false
    }

    It 'snapshots the complete occupied Funnel before explicit replacement' {
        $rawStatus = '{"Web":{"host:443":{"Handlers":{"/one":{"Proxy":"http://127.0.0.1:4174/"},"/two":{"Proxy":"http://127.0.0.1:4175/"}}}}}'
        Mock Get-FunnelStatus {
            @{
                Occupied = $true
                Target = '127.0.0.1:4174'
                PublicUrl = 'https://host/one'
                RawJson = '{"Web":{"host:443":{"Handlers":{"/one":{"Proxy":"http://127.0.0.1:4174/"},"/two":{"Proxy":"http://127.0.0.1:4175/"}}}}}'
            }
        } -ModuleName FunnelState
        Mock Set-FunnelTarget {} -ModuleName FunnelState
        $statePath = Join-Path $TestDrive 'replace-state.json'

        $result = Open-DrawdownFunnel `
            -Target '127.0.0.1:8787' `
            -StatePath $statePath `
            -ReplaceExisting

        $result.ContainsKey('PublicUrl') | Should Be $true
        $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $saved.schema_version | Should Be 1
        $saved.replacement_target | Should Be '127.0.0.1:8787'
        $saved.previous_raw_json | Should Be $rawStatus
        Assert-MockCalled Set-FunnelTarget 1 -ModuleName FunnelState -ParameterFilter {
            $Target -eq '127.0.0.1:8787'
        }
    }

    It 'snapshots an empty Funnel before opening this project' {
        Mock Get-FunnelStatus {
            @{
                Occupied = $false
                Target = $null
                PublicUrl = $null
                RawJson = '{"Web":{}}'
            }
        } -ModuleName FunnelState
        Mock Set-FunnelTarget {} -ModuleName FunnelState
        $statePath = Join-Path $TestDrive 'empty-state.json'

        Open-DrawdownFunnel `
            -Target '127.0.0.1:8787' `
            -StatePath $statePath

        $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $saved.previous_raw_json | Should Be '{"Web":{}}'
        Assert-MockCalled Set-FunnelTarget 1 -ModuleName FunnelState -ParameterFilter {
            $Target -eq '127.0.0.1:8787'
        }
    }

    It 'rolls back the previous route if switching the target fails' {
        Mock Get-FunnelStatus {
            @{
                Occupied = $true
                Target = '127.0.0.1:4174'
                PublicUrl = 'https://host/one'
                RawJson = '{"Web":{"host:443":{"Handlers":{"/one":{"Proxy":"http://127.0.0.1:4174/"}}}}}'
            }
        } -ModuleName FunnelState
        Mock Set-FunnelTarget { throw 'switch failed' } -ModuleName FunnelState
        Mock Set-FunnelConfiguration {} -ModuleName FunnelState
        $statePath = Join-Path $TestDrive 'rollback-state.json'

        { Open-DrawdownFunnel `
            -Target '127.0.0.1:8787' `
            -StatePath $statePath `
            -ReplaceExisting
        } | Should Throw

        Assert-MockCalled Set-FunnelConfiguration 1 -ModuleName FunnelState -ParameterFilter {
            $RawJson -match '127.0.0.1:4174'
        }
        Test-Path -LiteralPath $statePath | Should Be $false
    }

    It 'never overwrites an unresolved Funnel snapshot' {
        Mock Get-FunnelStatus {
            @{
                Occupied = $true
                Target = '127.0.0.1:9999'
                PublicUrl = 'https://host/unknown'
                RawJson = '{"new":"status"}'
            }
        } -ModuleName FunnelState
        Mock Set-FunnelTarget {} -ModuleName FunnelState
        $statePath = Join-Path $TestDrive 'unresolved-state.json'
        [IO.File]::WriteAllText($statePath, '{"original":true}')

        { Open-DrawdownFunnel `
            -Target '127.0.0.1:8787' `
            -StatePath $statePath `
            -ReplaceExisting
        } | Should Throw

        (Get-Content -LiteralPath $statePath -Raw) | Should Be '{"original":true}'
        Assert-MockCalled Set-FunnelTarget 0 -ModuleName FunnelState -Scope It
    }

    It 'adds the dedicated path while preserving the current two unrelated handlers' {
        Mock Get-FunnelStatus {
            @{
                Occupied = $true
                Target = '127.0.0.1:4174'
                PublicUrl = 'https://desktop-loi23mp.tail9c076e.ts.net/eng-vocabulary'
                Routes = @(
                    @{
                        Path = '/eng-vocabulary'
                        Target = '127.0.0.1:4174'
                        PublicUrl = 'https://desktop-loi23mp.tail9c076e.ts.net/eng-vocabulary'
                    },
                    @{
                        Path = '/leverage-etf'
                        Target = '127.0.0.1:4175/leverage-etf'
                        PublicUrl = 'https://desktop-loi23mp.tail9c076e.ts.net/leverage-etf'
                    }
                )
                RawJson = '{"TCP":{"443":{"HTTPS":true}},"Web":{"desktop-loi23mp.tail9c076e.ts.net:443":{"Handlers":{"/eng-vocabulary":{"Proxy":"http://127.0.0.1:4174/"},"/leverage-etf":{"Proxy":"http://127.0.0.1:4175/leverage-etf/"}}}},"AllowFunnel":{"desktop-loi23mp.tail9c076e.ts.net:443":true}}'
            }
        } -ModuleName FunnelState
        Mock Set-FunnelTarget {} -ModuleName FunnelState
        $statePath = Join-Path $TestDrive 'dedicated-path.json'

        Open-DrawdownFunnel `
            -Target '127.0.0.1:8787' `
            -PublicPath '/drawdown-ledger' `
            -StatePath $statePath

        Assert-MockCalled Set-FunnelTarget 1 -ModuleName FunnelState -Scope It -ParameterFilter {
            $Target -eq '127.0.0.1:8787' -and $PublicPath -eq '/drawdown-ledger'
        }
        $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $saved.previous_raw_json | Should Match '/eng-vocabulary'
        $saved.previous_raw_json | Should Match '/leverage-etf'
    }
}

Describe 'Funnel restoration' {
    It 'restores the exact saved configuration and removes the snapshot' {
        $rawStatus = '{"Web":{"host:443":{"Handlers":{"/one":{"Proxy":"http://127.0.0.1:4174/"},"/two":{"Proxy":"http://127.0.0.1:4175/"}}}}}'
        $statePath = Join-Path $TestDrive 'restore-state.json'
        [IO.File]::WriteAllText(
            $statePath,
            (@{
                schema_version = 1
                replacement_target = '127.0.0.1:8787'
                previous_raw_json = $rawStatus
            } | ConvertTo-Json),
            (New-Object Text.UTF8Encoding($false))
        )
        Mock Set-FunnelConfiguration {} -ModuleName FunnelState

        Restore-DrawdownFunnel -StatePath $statePath

        Assert-MockCalled Set-FunnelConfiguration 1 -ModuleName FunnelState -ParameterFilter {
            $RawJson -eq '{"Web":{"host:443":{"Handlers":{"/one":{"Proxy":"http://127.0.0.1:4174/"},"/two":{"Proxy":"http://127.0.0.1:4175/"}}}}}'
        }
        Test-Path -LiteralPath $statePath | Should Be $false
    }

    It 'is idempotent when no snapshot exists' {
        Mock Set-FunnelConfiguration {} -ModuleName FunnelState

        $result = Restore-DrawdownFunnel `
            -StatePath (Join-Path $TestDrive 'missing-state.json')

        $result | Should Be $false
        Assert-MockCalled Set-FunnelConfiguration 0 -ModuleName FunnelState -Scope It
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

    It 'builds a complete reset and restore command sequence' {
        $rawJson = '{"Web":{"host.ts.net:443":{"Handlers":{"/one":{"Proxy":"http://127.0.0.1:4174/"},"/two":{"Proxy":"http://127.0.0.1:4175/two/"}}}}}'

        $commands = @(Get-FunnelRestoreCommands -RawJson $rawJson)

        $commands.Count | Should Be 3
        ($commands[0].Arguments -join ' ') | Should Be 'funnel reset'
        ($commands[1].Arguments -join ' ') |
            Should Be 'funnel --bg --yes --https 443 --set-path /one http://127.0.0.1:4174/'
        ($commands[2].Arguments -join ' ') |
            Should Be 'funnel --bg --yes --https 443 --set-path /two http://127.0.0.1:4175/two/'
    }
}

Describe 'Tailscale Funnel mutations' {
    It 'adds the project path without resetting unrelated routes' {
        Mock Invoke-TailscaleCommand {} -ModuleName FunnelState

        Set-FunnelTarget `
            -Target '127.0.0.1:8787' `
            -PublicPath '/drawdown-ledger'

        Assert-MockCalled Invoke-TailscaleCommand 1 -ModuleName FunnelState -ParameterFilter {
            $Arguments -join ' ' -eq 'funnel --bg --yes --https 443 --set-path /drawdown-ledger 127.0.0.1:8787'
        }
        Assert-MockCalled Invoke-TailscaleCommand 1 -ModuleName FunnelState -Scope It
    }

    It 'replays every saved route after a reset' {
        Mock Invoke-TailscaleCommand {} -ModuleName FunnelState
        $rawJson = '{"Web":{"host.ts.net:443":{"Handlers":{"/one":{"Proxy":"http://127.0.0.1:4174/"},"/two":{"Proxy":"http://127.0.0.1:4175/two/"}}}}}'

        Set-FunnelConfiguration -RawJson $rawJson

        Assert-MockCalled Invoke-TailscaleCommand 3 -ModuleName FunnelState
        Assert-MockCalled Invoke-TailscaleCommand 1 -ModuleName FunnelState -ParameterFilter {
            $Arguments -join ' ' -eq 'funnel --bg --yes --https 443 --set-path /two http://127.0.0.1:4175/two/'
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
