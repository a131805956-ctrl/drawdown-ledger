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
    $webPropertyValue = $configuration.PSObject.Properties['Web']
    if ($null -ne $webPropertyValue -and $null -ne $webPropertyValue.Value) {
        foreach ($webProperty in @(
            $webPropertyValue.Value.PSObject.Properties |
                Sort-Object Name
        )) {
            $hostAndPort = $webProperty.Name
            $host = $hostAndPort
            $httpsPort = 443
            if ($hostAndPort -match '^(?<host>.+):(?<port>[0-9]+)$') {
                $host = $Matches.host
                $httpsPort = [int]$Matches.port
            }

            $handlersProperty = $webProperty.Value.PSObject.Properties['Handlers']
            if ($null -eq $handlersProperty -or $null -eq $handlersProperty.Value) {
                continue
            }
            foreach ($handlerProperty in @(
                $handlersProperty.Value.PSObject.Properties |
                    Sort-Object Name
            )) {
                $proxyProperty = $handlerProperty.Value.PSObject.Properties['Proxy']
                $proxy = if ($null -eq $proxyProperty) {
                    ''
                }
                else {
                    [string]$proxyProperty.Value
                }
                $handlerKind = if ([string]::IsNullOrWhiteSpace($proxy)) {
                    'unsupported'
                }
                else {
                    'proxy'
                }
                $target = if ($handlerKind -eq 'proxy') {
                    ($proxy -replace '^[A-Za-z+]+://', '').TrimEnd('/')
                }
                else {
                    ''
                }
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
                    HandlerKind = $handlerKind
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

function Get-FunnelStatusRoutes {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$Status
    )

    if ($Status -is [Collections.IDictionary]) {
        if ($Status.Contains('Routes')) {
            return @($Status['Routes'])
        }
        return @()
    }
    $routesProperty = $Status.PSObject.Properties['Routes']
    if ($null -eq $routesProperty) {
        return @()
    }
    return @($routesProperty.Value)
}

function Get-FunnelRouteProperty {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$Route,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if ($Route -is [Collections.IDictionary]) {
        if ($Route.Contains($Name)) {
            return $Route[$Name]
        }
        return $null
    }
    $property = $Route.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function ConvertTo-FunnelTargetIdentity {
    [CmdletBinding()]
    param(
        [AllowNull()]
        [string]$Target
    )

    if ([string]::IsNullOrWhiteSpace($Target)) {
        return ''
    }
    return ($Target -replace '^[A-Za-z+]+://', '').TrimEnd('/')
}

function Assert-SafePreviousFunnelRoute {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$Route,

        [Parameter(Mandatory = $true)]
        [string]$ExpectedPublicPath,

        [Parameter(Mandatory = $true)]
        [int]$ExpectedHttpsPort
    )

    $errorMessage = (
        'Invalid Funnel previous route snapshot; refusing to mutate Funnel.'
    )
    $path = [string](Get-FunnelRouteProperty -Route $Route -Name 'path')
    if (
        $ExpectedPublicPath -ne '/drawdown-ledger' -or
        $path -ne $ExpectedPublicPath
    ) {
        throw $errorMessage
    }

    $httpsPort = 0
    $httpsPortValue = Get-FunnelRouteProperty `
        -Route $Route `
        -Name 'https_port'
    if (
        -not [int]::TryParse([string]$httpsPortValue, [ref]$httpsPort) -or
        $httpsPort -ne 443 -or
        $httpsPort -ne $ExpectedHttpsPort
    ) {
        throw $errorMessage
    }

    $proxy = [string](Get-FunnelRouteProperty -Route $Route -Name 'proxy')
    $target = [string](Get-FunnelRouteProperty -Route $Route -Name 'target')
    if (
        $proxy -notmatch
            '(?i)^http://127\.0\.0\.1:(?<port>[0-9]{1,5})/?$'
    ) {
        throw $errorMessage
    }
    $proxyPort = 0
    if (
        -not [int]::TryParse($Matches.port, [ref]$proxyPort) -or
        $proxyPort -lt 1 -or
        $proxyPort -gt 65535
    ) {
        throw $errorMessage
    }

    $proxyIdentity = ConvertTo-FunnelTargetIdentity -Target $proxy
    $targetIdentity = ConvertTo-FunnelTargetIdentity -Target $target
    if (
        $target -notmatch '^127\.0\.0\.1:[0-9]{1,5}$' -or
        -not $targetIdentity.Equals(
            $proxyIdentity,
            [StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw $errorMessage
    }

    return [pscustomobject]@{
        Path = $path
        HttpsPort = $httpsPort
        Target = $proxy
    }
}

function Find-FunnelRoute {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$Status,

        [Parameter(Mandatory = $true)]
        [string]$PublicPath
    )

    return Get-FunnelStatusRoutes -Status $Status |
        Where-Object {
            [string](Get-FunnelRouteProperty -Route $_ -Name 'Path') -eq $PublicPath
        } |
        Select-Object -First 1
}

function Set-FunnelTarget {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Target,

        [string]$PublicPath = '/',

        [ValidateRange(1, 65535)]
        [int]$HttpsPort = 443
    )

    $arguments = @('funnel', '--bg', '--yes')
    if ($PublicPath -ne '/' -or $HttpsPort -ne 443) {
        $arguments += @('--https', [string]$HttpsPort)
    }
    if ($PublicPath -ne '/') {
        $arguments += @('--set-path', $PublicPath)
    }
    $arguments += $Target
    Invoke-TailscaleCommand -Arguments $arguments | Out-Null
}

function Remove-FunnelTarget {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$PublicPath,

        [ValidateRange(1, 65535)]
        [int]$HttpsPort = 443
    )

    $arguments = @(
        'funnel', '--yes', '--https', [string]$HttpsPort
    )
    if ($PublicPath -ne '/') {
        $arguments += @('--set-path', $PublicPath)
    }
    $arguments += 'off'
    Invoke-TailscaleCommand -Arguments $arguments | Out-Null
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

    $routes = @(Get-FunnelStatusRoutes -Status $status)
    $matchingRoute = Find-FunnelRoute -Status $status -PublicPath $PublicPath
    if ($routes.Count -gt 0) {
        $pathOccupied = $null -ne $matchingRoute
        $currentTarget = if ($pathOccupied) {
            Get-FunnelRouteProperty -Route $matchingRoute -Name 'Target'
        }
        else {
            $null
        }
        $currentPublicUrl = if ($pathOccupied) {
            Get-FunnelRouteProperty -Route $matchingRoute -Name 'PublicUrl'
        }
        else {
            $null
        }
    }
    else {
        $pathOccupied = [bool]$status.Occupied
        $currentTarget = $status.Target
        $currentPublicUrl = $status.PublicUrl
    }

    $requestedIdentity = ConvertTo-FunnelTargetIdentity -Target $Target
    $currentIdentity = ConvertTo-FunnelTargetIdentity -Target ([string]$currentTarget)
    if ($pathOccupied -and [string]::IsNullOrWhiteSpace($currentIdentity)) {
        throw (
            "Tailscale Funnel path '$PublicPath' uses an unsupported handler; " +
            'refusing to overwrite it.'
        )
    }
    if (
        $pathOccupied -and
        $currentIdentity -ne $requestedIdentity -and
        -not $ReplaceExisting
    ) {
        throw (
            "Tailscale Funnel already routes {0} to {1}. " +
            'Use -ReplaceExisting to switch recoverably.'
        ) -f $currentPublicUrl, $currentTarget
    }

    if ($pathOccupied -and $currentIdentity -eq $requestedIdentity) {
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
        $previousRoute = if ($pathOccupied) {
            [ordered]@{
                path = $PublicPath
                target = [string]$currentTarget
                proxy = [string](
                    Get-FunnelRouteProperty -Route $matchingRoute -Name 'Proxy'
                )
                https_port = [int](
                    Get-FunnelRouteProperty -Route $matchingRoute -Name 'HttpsPort'
                )
            }
        }
        else {
            $null
        }
        if (
            $null -ne $previousRoute -and
            $previousRoute.https_port -le 0
        ) {
            $previousRoute.https_port = 443
        }
        Write-AtomicJson -Path $StatePath -Value ([ordered]@{
            schema_version = 2
            replacement_target = $Target
            public_path = $PublicPath
            https_port = 443
            previous_route = $previousRoute
        })
        try {
            Set-FunnelTarget `
                -Target $Target `
                -PublicPath $PublicPath `
                -HttpsPort 443
        }
        catch {
            $originalError = $_
            try {
                $rollbackStatus = Get-FunnelStatus
                $rollbackRoute = Find-FunnelRoute `
                    -Status $rollbackStatus `
                    -PublicPath $PublicPath
                $rollbackIdentity = if ($null -eq $rollbackRoute) {
                    ''
                }
                else {
                    ConvertTo-FunnelTargetIdentity -Target (
                        [string](Get-FunnelRouteProperty `
                            -Route $rollbackRoute `
                            -Name 'Target')
                    )
                }
                if ($rollbackIdentity -eq $requestedIdentity) {
                    if ($null -eq $previousRoute) {
                        Remove-FunnelTarget `
                            -PublicPath $PublicPath `
                            -HttpsPort 443
                    }
                    else {
                        $rollbackTarget = if (
                            [string]::IsNullOrWhiteSpace($previousRoute.proxy)
                        ) {
                            $previousRoute.target
                        }
                        else {
                            $previousRoute.proxy
                        }
                        Set-FunnelTarget `
                            -Target $rollbackTarget `
                            -PublicPath $PublicPath `
                            -HttpsPort $previousRoute.https_port
                    }
                }
                Remove-Item -LiteralPath $StatePath -Force
            }
            catch {
                throw (
                    "Funnel update failed and safe rollback could not be completed. " +
                    "Recovery state remains at '$StatePath'."
                )
            }
            throw $originalError
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
        [string]$StatePath,

        [string]$ExpectedPublicPath = '/drawdown-ledger',

        [string]$ExpectedTarget = '127.0.0.1:8787'
    )

    if (-not (Test-Path -LiteralPath $StatePath)) {
        return $false
    }

    $saved = Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($saved.schema_version -ne 2) {
        throw "Invalid Funnel state snapshot: $StatePath"
    }
    $publicPath = [string]$saved.public_path
    $replacementIdentity = ConvertTo-FunnelTargetIdentity `
        -Target ([string]$saved.replacement_target)
    if (
        [string]::IsNullOrWhiteSpace($publicPath) -or
        [string]::IsNullOrWhiteSpace($replacementIdentity)
    ) {
        throw "Invalid Funnel state snapshot: $StatePath"
    }
    if (-not $ExpectedPublicPath.StartsWith('/')) {
        $ExpectedPublicPath = "/$ExpectedPublicPath"
    }
    if ($ExpectedPublicPath.Length -gt 1) {
        $ExpectedPublicPath = $ExpectedPublicPath.TrimEnd('/')
    }
    $projectPublicPath = '/drawdown-ledger'
    $expectedIdentity = ConvertTo-FunnelTargetIdentity -Target $ExpectedTarget
    if (
        $ExpectedPublicPath -ne $projectPublicPath -or
        $publicPath -ne $projectPublicPath -or
        $publicPath -ne $ExpectedPublicPath -or
        $replacementIdentity -ne $expectedIdentity
    ) {
        throw (
            "Funnel ownership snapshot does not match the expected project path " +
            "and target: $StatePath"
        )
    }
    $httpsPort = [int]$saved.https_port
    if ($httpsPort -ne 443) {
        throw "Invalid Funnel state snapshot: $StatePath"
    }
    $validatedPreviousRoute = $null
    if ($null -ne $saved.previous_route) {
        $validatedPreviousRoute = Assert-SafePreviousFunnelRoute `
            -Route $saved.previous_route `
            -ExpectedPublicPath $publicPath `
            -ExpectedHttpsPort $httpsPort
    }

    $status = Get-FunnelStatus
    $currentRoute = Find-FunnelRoute -Status $status -PublicPath $publicPath
    if ($null -eq $currentRoute) {
        if ($null -ne $saved.previous_route) {
            throw (
                "Funnel path '$publicPath' is missing; refusing to restore an " +
                'older route without ownership proof.'
            )
        }
        Remove-Item -LiteralPath $StatePath -Force
        return $false
    }
    $currentIdentity = ConvertTo-FunnelTargetIdentity -Target (
        [string](Get-FunnelRouteProperty -Route $currentRoute -Name 'Target')
    )
    if ($currentIdentity -ne $replacementIdentity) {
        throw (
            "Funnel path '$publicPath' is no longer project-owned; " +
            'refusing to mutate it.'
        )
    }

    if ($null -eq $saved.previous_route) {
        Remove-FunnelTarget -PublicPath $publicPath -HttpsPort $httpsPort
    }
    else {
        Set-FunnelTarget `
            -Target $validatedPreviousRoute.Target `
            -PublicPath $validatedPreviousRoute.Path `
            -HttpsPort $validatedPreviousRoute.HttpsPort
    }
    Remove-Item -LiteralPath $StatePath -Force
    return $true
}

Export-ModuleMember -Function @(
    'Get-FunnelStatus'
    'ConvertFrom-FunnelStatusJson'
    'Invoke-TailscaleCommand'
    'Set-FunnelTarget'
    'Remove-FunnelTarget'
    'Open-DrawdownFunnel'
    'Restore-DrawdownFunnel'
)
