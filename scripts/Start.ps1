[CmdletBinding()]
param(
    [int]$ApiPort = 8787,
    [switch]$SkipInstall,
    [switch]$SkipBuild,
    [switch]$SkipDataUpdate,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($MyInvocation.InvocationName -ne '.') {
    $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $runtimeRoot = Join-Path $projectRoot '.runtime'
    $statePath = Join-Path $runtimeRoot 'api-process.json'
    $factory = 'drawdown_lab.runtime:create_runtime_app'
    if ($DryRun) {
        [pscustomobject]@{
            Action = 'start'
            Host = '127.0.0.1'
            Port = $ApiPort
            Factory = $factory
            ServesWebDist = $true
            WillUpdateData = -not $SkipDataUpdate
        }
        return
    }

    Import-Module (Join-Path $PSScriptRoot 'lib\ProcessState.psm1') -Force
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    $venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not $SkipInstall) {
        if (-not (Test-Path -LiteralPath $venvPython)) {
            & python -m venv (Join-Path $projectRoot '.venv')
            if ($LASTEXITCODE -ne 0) {
                throw 'Unable to create the Python virtual environment.'
            }
        }
        & $venvPython -m pip install --disable-pip-version-check $projectRoot
        if ($LASTEXITCODE -ne 0) {
            throw 'Unable to install the API environment.'
        }
    }
    elseif (-not (Test-Path -LiteralPath $venvPython)) {
        $venvPython = (Get-Command python -ErrorAction Stop).Source
    }

    $webRoot = Join-Path $projectRoot 'apps\web'
    if (-not $SkipBuild -and (Test-Path -LiteralPath (Join-Path $webRoot 'package.json'))) {
        if (Test-Path -LiteralPath (Join-Path $webRoot 'package-lock.json')) {
            & npm --prefix $webRoot ci
        }
        else {
            & npm --prefix $webRoot install
        }
        if ($LASTEXITCODE -ne 0) {
            throw 'Unable to install the Web environment.'
        }
        & npm --prefix $webRoot run build
        if ($LASTEXITCODE -ne 0) {
            throw 'Unable to build the Web application.'
        }
    }

    $argumentList = @(
        '-m uvicorn'
        $factory
        '--factory'
        '--host 127.0.0.1'
        "--port $ApiPort"
        ('--app-dir "{0}"' -f (Join-Path $projectRoot 'apps\api\src'))
    ) -join ' '
    $previousProjectRoot = [Environment]::GetEnvironmentVariable(
        'DRAWDOWN_PROJECT_ROOT',
        'Process'
    )
    try {
        $env:DRAWDOWN_PROJECT_ROOT = $projectRoot
        $process = Start-ProjectProcess `
            -FilePath $venvPython `
            -ArgumentList $argumentList `
            -WorkingDirectory $projectRoot `
            -StatePath $statePath `
            -ProjectRoot $projectRoot `
            -CommandMarker $factory `
            -ServiceName 'api'
    }
    finally {
        if ($null -eq $previousProjectRoot) {
            Remove-Item Env:DRAWDOWN_PROJECT_ROOT -ErrorAction SilentlyContinue
        }
        else {
            $env:DRAWDOWN_PROJECT_ROOT = $previousProjectRoot
        }
    }

    $healthUri = "http://127.0.0.1:$ApiPort/api/v1/data/health"
    $healthy = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            Invoke-RestMethod -Uri $healthUri -Method Get -TimeoutSec 2 | Out-Null
            $healthy = $true
            break
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $healthy) {
        Stop-ProjectProcess `
            -StatePath $statePath `
            -ExpectedProjectRoot $projectRoot `
            -ExpectedCommandMarker $factory |
            Out-Null
        throw "API did not become healthy at $healthUri."
    }

    $updateSummary = $null
    if (-not $SkipDataUpdate) {
        $updateSummary = & (Join-Path $PSScriptRoot 'Update-Data.ps1') `
            -ApiBaseUrl "http://127.0.0.1:$ApiPort"
    }
    [pscustomobject]@{
        Status = 'running'
        ProcessId = $process.Id
        LocalUrl = "http://127.0.0.1:$ApiPort/"
        DataStatus = if ($null -eq $updateSummary) {
            'skipped'
        }
        else {
            $updateSummary.Status
        }
    }
}
