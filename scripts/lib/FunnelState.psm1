Set-StrictMode -Version Latest

function Invoke-TailscaleCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [string]$Executable = 'tailscale'
    )

    $output = & $Executable @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw (
            "Tailscale command failed with exit code {0}: {1}" -f
            $LASTEXITCODE, ($output -join [Environment]::NewLine)
        )
    }
    return $output
}

function Get-FunnelRestoreCommands {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RawJson
    )

    $configuration = $RawJson | ConvertFrom-Json
    $commands = @(
        [pscustomobject]@{ Arguments = [string[]]@('funnel', 'reset') }
    )
    if ($null -eq $configuration.Web) {
        return $commands
    }

    foreach ($webProperty in @($configuration.Web.PSObject.Properties | Sort-Object Name)) {
        $httpsPort = 443
        if ($webProperty.Name -match ':(?<port>[0-9]+)$') {
            $httpsPort = [int]$Matches.port
        }
        $handlers = $webProperty.Value.Handlers
        if ($null -eq $handlers) {
            continue
        }

        foreach ($handlerProperty in @($handlers.PSObject.Properties | Sort-Object Name)) {
            $handler = $handlerProperty.Value
            $proxy = [string]$handler.Proxy
            if ([string]::IsNullOrWhiteSpace($proxy)) {
                throw (
                    "Cannot safely restore unsupported Funnel handler '{0}'." -f
                    $handlerProperty.Name
                )
            }

            $arguments = @('funnel', '--bg', '--yes', '--https', [string]$httpsPort)
            if ($handlerProperty.Name -ne '/') {
                $arguments += @('--set-path', [string]$handlerProperty.Name)
            }
            $arguments += $proxy
            $commands += [pscustomobject]@{ Arguments = [string[]]$arguments }
        }
    }
    return $commands
}

function Write-AtomicJson {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$Value,

        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $temporaryPath = Join-Path $directory (
        '.{0}.{1}.tmp' -f (Split-Path -Leaf $Path), [guid]::NewGuid().ToString('N')
    )
    try {
        $json = $Value | ConvertTo-Json -Depth 20
        [IO.File]::WriteAllText(
            $temporaryPath,
            $json,
            (New-Object Text.UTF8Encoding($false))
        )
        Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Get-FunnelStatus {
    [CmdletBinding()]
    param()

    $output = Invoke-TailscaleCommand -Arguments @('funnel', 'status', '--json')
    $rawJson = ([string[]]$output -join [Environment]::NewLine).Trim()
    return ConvertFrom-FunnelStatusJson -RawJson $rawJson
}

function ConvertFrom-FunnelStatusJson {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RawJson
    )

    $rawJson = $RawJson.Trim()
    $configuration = $rawJson | ConvertFrom-Json
    $routes = @()
    if ($null -ne $configuration.Web) {
        foreach ($webProperty in @($configuration.Web.PSObject.Properties | Sort-Object Name)) {
            $hostAndPort = $webProperty.Name
            $host = $hostAndPort
            $httpsPort = 443
            if ($hostAndPort -match '^(?<host>.+):(?<port>[0-9]+)$') {
                $host = $Matches.host
                $httpsPort = [int]$Matches.port
            }

            $handlers = $webProperty.Value.Handlers
            if ($null -eq $handlers) {
                continue
            }
            foreach ($handlerProperty in @($handlers.PSObject.Properties | Sort-Object Name)) {
                $proxy = [string]$handlerProperty.Value.Proxy
                if ([string]::IsNullOrWhiteSpace($proxy)) {
                    continue
                }

                $target = $proxy -replace '^https?://', ''
                $target = $target.TrimEnd('/')
                $path = [string]$handlerProperty.Name
                $publicPath = if ($path -eq '/') { '' } else { $path }
                $publicPort = if ($httpsPort -eq 443) { '' } else { ":$httpsPort" }
                $routes += [pscustomobject]@{
                    Host = $host
                    HttpsPort = $httpsPort
                    Path = $path
                    Proxy = $proxy
                    Target = $target
                    PublicUrl = "https://$host$publicPort$publicPath"
                }
            }
        }
    }

    $firstRoute = $routes | Select-Object -First 1
    return [pscustomobject]@{
        Occupied = $routes.Count -gt 0
        Target = if ($null -eq $firstRoute) { $null } else { $firstRoute.Target }
        PublicUrl = if ($null -eq $firstRoute) { $null } else { $firstRoute.PublicUrl }
        Routes = @($routes)
        RawJson = $rawJson
    }
}

function Set-FunnelTarget {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Target,

        [string]$PublicPath = '/'
    )

    $arguments = @('funnel', '--bg', '--yes')
    if ($PublicPath -ne '/') {
        $arguments += @('--https', '443', '--set-path', $PublicPath)
    }
    $arguments += $Target
    Invoke-TailscaleCommand -Arguments $arguments | Out-Null
}

function Set-FunnelConfiguration {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RawJson
    )

    foreach ($command in @(Get-FunnelRestoreCommands -RawJson $RawJson)) {
        Invoke-TailscaleCommand -Arguments $command.Arguments | Out-Null
    }
}

function Open-DrawdownFunnel {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Target,

        [Parameter(Mandatory = $true)]
        [string]$StatePath,

        [string]$PublicPath = '/',

        [switch]$ReplaceExisting
    )

    $status = Get-FunnelStatus
    if (-not $PublicPath.StartsWith('/')) {
        $PublicPath = "/$PublicPath"
    }
    if ($PublicPath.Length -gt 1) {
        $PublicPath = $PublicPath.TrimEnd('/')
    }

    $routes = @()
    if ($status -is [Collections.IDictionary]) {
        if ($status.Contains('Routes')) {
            $routes = @($status['Routes'])
        }
    }
    elseif ($null -ne $status.PSObject.Properties['Routes']) {
        $routes = @($status.Routes)
    }
    $matchingRoute = $routes |
        Where-Object { $_.Path -eq $PublicPath } |
        Select-Object -First 1
    if ($routes.Count -gt 0) {
        $pathOccupied = $null -ne $matchingRoute
        $currentTarget = if ($pathOccupied) { $matchingRoute.Target } else { $null }
        $currentPublicUrl = if ($pathOccupied) { $matchingRoute.PublicUrl } else { $null }
    }
    else {
        $pathOccupied = [bool]$status.Occupied
        $currentTarget = $status.Target
        $currentPublicUrl = $status.PublicUrl
    }

    if ($pathOccupied -and $currentTarget -ne $Target -and -not $ReplaceExisting) {
        throw (
            "Tailscale Funnel already routes {0} to {1}. " +
            'Use -ReplaceExisting to switch recoverably.'
        ) -f $currentPublicUrl, $currentTarget
    }

    if ($pathOccupied -and $currentTarget -eq $Target) {
        if ($null -ne $matchingRoute) {
            return $matchingRoute
        }
        return $status
    }

    if (-not $pathOccupied -or $ReplaceExisting) {
        if (Test-Path -LiteralPath $StatePath) {
            throw (
                "A Funnel recovery snapshot already exists at '{0}'. " +
                'Restore it before opening another route.'
            ) -f $StatePath
        }
        Write-AtomicJson -Path $StatePath -Value ([ordered]@{
            schema_version = 1
            replacement_target = $Target
            public_path = $PublicPath
            previous_raw_json = [string]$status.RawJson
        })
        try {
            Set-FunnelTarget -Target $Target -PublicPath $PublicPath
        }
        catch {
            Set-FunnelConfiguration -RawJson ([string]$status.RawJson)
            Remove-Item -LiteralPath $StatePath -Force
            throw
        }
        return @{
            Occupied = $true
            Target = $Target
            PublicUrl = $null
            PublicPath = $PublicPath
            PreviousStatus = $status
        }
    }

    throw 'Funnel opening was refused.'
}

function Restore-DrawdownFunnel {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$StatePath
    )

    if (-not (Test-Path -LiteralPath $StatePath)) {
        return $false
    }

    $saved = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($saved.schema_version -ne 1 -or $null -eq $saved.previous_raw_json) {
        throw "Invalid Funnel state snapshot: $StatePath"
    }

    Set-FunnelConfiguration -RawJson ([string]$saved.previous_raw_json)
    Remove-Item -LiteralPath $StatePath -Force
    return $true
}

Export-ModuleMember -Function @(
    'Get-FunnelStatus'
    'ConvertFrom-FunnelStatusJson'
    'Invoke-TailscaleCommand'
    'Get-FunnelRestoreCommands'
    'Set-FunnelTarget'
    'Set-FunnelConfiguration'
    'Open-DrawdownFunnel'
    'Restore-DrawdownFunnel'
)
