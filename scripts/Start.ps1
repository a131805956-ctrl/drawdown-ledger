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

function Invoke-StartupDataUpdate {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$UpdateAction
    )

    try {
        $summary = & $UpdateAction
        return [pscustomobject]@{
            Status = [string]$summary.Status
            Degraded = $false
            ExitPolicy = 'continue-running'
            Message = 'Data update completed.'
            Summary = $summary
        }
    }
    catch {
        return [pscustomobject]@{
            Status = 'stale-cache'
            Degraded = $true
            ExitPolicy = 'continue-running'
            Message = 'Data update failed; continuing with the existing cache.'
            Summary = $null
        }
    }
}

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
            PublicAccessProtected = $true
        }
        return
    }

    Import-Module (Join-Path $PSScriptRoot 'lib\ProcessState.psm1') -Force
    Import-Module (Join-Path $PSScriptRoot 'lib\PublicAccess.psm1') -Force
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    $credentialPath = Join-Path $runtimeRoot 'public-access.json'
    $credential = New-DrawdownPublicCredential -Path $credentialPath
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
    $previousPublicUsername = [Environment]::GetEnvironmentVariable(
        'DRAWDOWN_PUBLIC_USERNAME',
        'Process'
    )
    $previousPublicPassword = [Environment]::GetEnvironmentVariable(
        'DRAWDOWN_PUBLIC_PASSWORD',
        'Process'
    )
    try {
        $env:DRAWDOWN_PROJECT_ROOT = $projectRoot
        $env:DRAWDOWN_PUBLIC_USERNAME = $credential.Username
        $env:DRAWDOWN_PUBLIC_PASSWORD = $credential.Password
        $process = Start-ProjectProcess `
            -FilePath $venvPython `
            -ArgumentList $argumentList `
            -WorkingDirectory $projectRoot `
            -StatePath $statePath `
            -ProjectRoot $projectRoot `
            -CommandMarker $factory `
            -ServiceName 'api' `
            -Port $ApiPort
    }
    finally {
        if ($null -eq $previousProjectRoot) {
            Remove-Item Env:DRAWDOWN_PROJECT_ROOT -ErrorAction SilentlyContinue
        }
        else {
            $env:DRAWDOWN_PROJECT_ROOT = $previousProjectRoot
        }
        if ($null -eq $previousPublicUsername) {
            Remove-Item Env:DRAWDOWN_PUBLIC_USERNAME -ErrorAction SilentlyContinue
        }
        else {
            $env:DRAWDOWN_PUBLIC_USERNAME = $previousPublicUsername
        }
        if ($null -eq $previousPublicPassword) {
            Remove-Item Env:DRAWDOWN_PUBLIC_PASSWORD -ErrorAction SilentlyContinue
        }
        else {
            $env:DRAWDOWN_PUBLIC_PASSWORD = $previousPublicPassword
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

    $updateResult = [pscustomobject]@{
        Status = 'skipped'
        Degraded = $false
        ExitPolicy = 'continue-running'
        Message = 'Data update skipped.'
        Summary = $null
    }
    if (-not $SkipDataUpdate) {
        $updateResult = Invoke-StartupDataUpdate -UpdateAction {
            & (Join-Path $PSScriptRoot 'Update-Data.ps1') `
                -ApiBaseUrl "http://127.0.0.1:$ApiPort"
        }
    }
    [pscustomobject]@{
        Status = if ($updateResult.Degraded) {
            'running-degraded'
        }
        else {
            'running'
        }
        ProcessId = $process.Id
        LocalUrl = "http://127.0.0.1:$ApiPort/"
        PublicAccessUsername = $credential.Username
        PublicAccessCredentialFile = $credential.Path
        DataStatus = $updateResult.Status
        ExitPolicy = $updateResult.ExitPolicy
        DataMessage = $updateResult.Message
    }
}
