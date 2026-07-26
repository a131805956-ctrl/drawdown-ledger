[CmdletBinding()]
param(
    [string]$Target = '127.0.0.1:8787',
    [string]$PublicPath = '/drawdown-ledger',
    [switch]$ReplaceExisting,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($MyInvocation.InvocationName -ne '.') {
    $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $statePath = Join-Path $projectRoot '.runtime\funnel-state.json'
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
    }
}
