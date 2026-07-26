[CmdletBinding()]
param(
    [string]$ApiBaseUrl = 'http://127.0.0.1:8787',
    [datetime]$AsOf = (Get-Date),
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-DrawdownDataUpdate {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ApiBaseUrl,

        [Parameter(Mandatory = $true)]
        [datetime]$AsOf
    )

    $body = [ordered]@{
        schema_version = '1.0'
        as_of = $AsOf.ToString('yyyy-MM-dd')
    } | ConvertTo-Json -Compress
    $response = Invoke-RestMethod `
        -Uri ("{0}/api/v1/data/update" -f $ApiBaseUrl.TrimEnd('/')) `
        -Method Post `
        -ContentType 'application/json; charset=utf-8' `
        -Body $body
    $failures = @($response.failures)
    return [pscustomobject]@{
        SchemaVersion = [string]$response.schema_version
        Status = [string]$response.status
        Cutoff = $response.cutoff
        RequestCount = [int]$response.request_count
        RefreshedSymbols = @($response.refreshed_symbols)
        FailureCount = $failures.Count
        FailedSymbols = @(
            $failures | ForEach-Object { [string]$_.symbol }
        )
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    if ($DryRun) {
        [pscustomobject]@{
            Action = 'data-update'
            Uri = (
                '{0}/api/v1/data/update' -f $ApiBaseUrl.TrimEnd('/')
            )
            AsOf = $AsOf.ToString('yyyy-MM-dd')
        }
    }
    else {
        Invoke-DrawdownDataUpdate -ApiBaseUrl $ApiBaseUrl -AsOf $AsOf
    }
}
