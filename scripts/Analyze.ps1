[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Config,
    [ValidateSet('evidence', 'backtest', 'optimization')]
    [string]$Endpoint = 'optimization',
    [string]$ApiBaseUrl = 'http://127.0.0.1:8787',
    [string]$OutFile,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-OptionalProperty {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object]$Value,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $property = $Value.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function Invoke-DrawdownAnalysis {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ConfigPath,

        [Parameter(Mandatory = $true)]
        [ValidateSet('evidence', 'backtest', 'optimization')]
        [string]$Endpoint,

        [Parameter(Mandatory = $true)]
        [string]$ApiBaseUrl,

        [Parameter(Mandatory = $true)]
        [string]$OutFile
    )

    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        throw "Analysis config does not exist: $ConfigPath"
    }
    $requestJson = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8
    $requestJson | ConvertFrom-Json | Out-Null
    $apiPath = @{
        evidence = '/api/v1/evidence/analyze'
        backtest = '/api/v1/strategies/backtest'
        optimization = '/api/v1/optimizations'
    }[$Endpoint]
    $response = Invoke-RestMethod `
        -Uri ("{0}{1}" -f $ApiBaseUrl.TrimEnd('/'), $apiPath) `
        -Method Post `
        -ContentType 'application/json; charset=utf-8' `
        -Body $requestJson

    $outputPath = [IO.Path]::GetFullPath($OutFile)
    $outputDirectory = Split-Path -Parent $outputPath
    if (-not (Test-Path -LiteralPath $outputDirectory)) {
        New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    }
    $temporaryPath = Join-Path $outputDirectory (
        '.{0}.{1}.tmp' -f (Split-Path -Leaf $outputPath),
        [guid]::NewGuid().ToString('N')
    )
    try {
        [IO.File]::WriteAllText(
            $temporaryPath,
            ($response | ConvertTo-Json -Depth 100),
            (New-Object Text.UTF8Encoding($false))
        )
        Move-Item -LiteralPath $temporaryPath -Destination $outputPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }

    return [pscustomobject]@{
        SchemaVersion = Get-OptionalProperty -Value $response -Name 'schema_version'
        Endpoint = $Endpoint
        Status = Get-OptionalProperty -Value $response -Name 'status'
        JobId = Get-OptionalProperty -Value $response -Name 'job_id'
        ResultFile = $outputPath
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    if ([string]::IsNullOrWhiteSpace($OutFile)) {
        $OutFile = Join-Path $projectRoot '.runtime\analysis-response.json'
    }
    if ($DryRun) {
        [pscustomobject]@{
            Action = 'analyze'
            Endpoint = $Endpoint
            ConfigFile = [IO.Path]::GetFullPath($Config)
            ResultFile = [IO.Path]::GetFullPath($OutFile)
        }
    }
    else {
        Invoke-DrawdownAnalysis `
            -ConfigPath $Config `
            -Endpoint $Endpoint `
            -ApiBaseUrl $ApiBaseUrl `
            -OutFile $OutFile
    }
}
