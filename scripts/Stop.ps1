[CmdletBinding()]
param(
    [switch]$KeepFunnel,
    [string]$FunnelTarget = '127.0.0.1:8787',
    [string]$PublicPath = '/drawdown-ledger',
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($MyInvocation.InvocationName -ne '.') {
    $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $processState = Join-Path $projectRoot '.runtime\api-process.json'
    $funnelState = Join-Path $projectRoot '.runtime\funnel-state.json'
    if ($DryRun) {
        [pscustomobject]@{
            Action = 'stop'
            RestoreFunnel = -not $KeepFunnel
            FunnelTarget = $FunnelTarget
            PublicPath = $PublicPath
            MutatesProcesses = $false
            ProcessState = $processState
            FunnelState = $funnelState
        }
        return
    }

    Import-Module (Join-Path $PSScriptRoot 'lib\ProcessState.psm1') -Force
    Import-Module (Join-Path $PSScriptRoot 'lib\FunnelState.psm1') -Force
    $stopped = Stop-ProjectProcess `
        -StatePath $processState `
        -ExpectedProjectRoot $projectRoot `
        -ExpectedCommandMarker 'drawdown_lab.runtime:create_runtime_app'
    $restored = $false
    if (-not $KeepFunnel) {
        $restored = Restore-DrawdownFunnel `
            -StatePath $funnelState `
            -ExpectedPublicPath $PublicPath `
            -ExpectedTarget $FunnelTarget
    }
    [pscustomobject]@{
        Status = 'stopped'
        ProcessStopped = [bool]$stopped
        FunnelRestored = [bool]$restored
    }
}
