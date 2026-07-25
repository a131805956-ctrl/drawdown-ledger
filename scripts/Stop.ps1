[CmdletBinding()]
param(
    [switch]$KeepFunnel,
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
        $restored = Restore-DrawdownFunnel -StatePath $funnelState
    }
    [pscustomobject]@{
        Status = 'stopped'
        ProcessStopped = [bool]$stopped
        FunnelRestored = [bool]$restored
    }
}
