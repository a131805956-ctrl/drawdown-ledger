[CmdletBinding()]
param(
    [string]$Target = '127.0.0.1:8787',
    [string]$PublicPath = '/drawdown-ledger',
    [switch]$ReplaceExisting,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-DrawdownPublicEndpointProtected {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Target,

        [Parameter(Mandatory = $true)]
        [object]$Credential
    )

    if ($Target -notmatch '^127\.0\.0\.1:(?<port>[0-9]{1,5})$') {
        throw 'Funnel target must be a loopback host and port.'
    }
    $port = [int]$Matches.port
    if ($port -lt 1 -or $port -gt 65535) {
        throw 'Funnel target port is invalid.'
    }
    $probeUris = @(
        "http://$Target/api/v1/data/health"
        "http://$Target/drawdown-ledger/api/v1/data/health"
    )
    $probeHeaders = @{
        'X-Forwarded-For' = '203.0.113.10'
    }
    foreach ($uri in $probeUris) {
        $unauthorized = $false
        try {
            Invoke-WebRequest `
                -Uri $uri `
                -Method Get `
                -Headers $probeHeaders `
                -TimeoutSec 5 |
                Out-Null
        }
        catch {
            $response = $_.Exception.Response
            if ($null -ne $response -and [int]$response.StatusCode -eq 401) {
                $unauthorized = $true
            }
            else {
                throw 'Unable to verify the protected public endpoint.'
            }
        }
        if (-not $unauthorized) {
            throw 'Public endpoint is not protected; refusing to open Funnel.'
        }
    }

    $rawCredential = '{0}:{1}' -f (
        [string]$Credential.Username
    ), (
        [string]$Credential.Password
    )
    $authorization = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes($rawCredential)
    )
    $protectedHeaders = @{
        'X-Forwarded-For' = '203.0.113.10'
        Authorization = "Basic $authorization"
    }
    foreach ($uri in $probeUris) {
        $health = Invoke-RestMethod `
            -Uri $uri `
            -Method Get `
            -Headers $protectedHeaders `
            -TimeoutSec 5
        if ([string]$health.schema_version -ne '1.0') {
            throw 'Authenticated public endpoint returned an invalid health response.'
        }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $statePath = Join-Path $projectRoot '.runtime\funnel-state.json'
    $credentialPath = Join-Path $projectRoot '.runtime\public-access.json'
    if ($DryRun) {
        [pscustomobject]@{
            Action = 'open-funnel'
            Target = $Target
            PublicPath = $PublicPath
            ReplaceExisting = [bool]$ReplaceExisting
            MutatesFunnel = $false
        }
        return
    }

    Import-Module (Join-Path $PSScriptRoot 'lib\FunnelState.psm1') -Force
    Import-Module (Join-Path $PSScriptRoot 'lib\PublicAccess.psm1') -Force
    $credential = Read-DrawdownPublicCredential -Path $credentialPath
    Assert-DrawdownPublicEndpointProtected `
        -Target $Target `
        -Credential $credential
    $result = Open-DrawdownFunnel `
        -Target $Target `
        -PublicPath $PublicPath `
        -StatePath $statePath `
        -ReplaceExisting:$ReplaceExisting
    [pscustomobject]@{
        Status = 'open'
        Target = $Target
        PublicPath = $PublicPath
        PublicUrl = if ($null -ne $result.PublicUrl) {
            $result.PublicUrl
        }
        else {
            $null
        }
        Username = $credential.Username
        CredentialFile = $credential.Path
    }
}
