Set-StrictMode -Version Latest

function Read-DrawdownPublicCredential {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Public access credential does not exist: $Path"
    }
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw 'Public access credential cannot be a link or reparse point.'
    }
    try {
        $credential = Get-Content `
            -LiteralPath $item.FullName `
            -Raw `
            -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw 'Public access credential is not valid JSON.'
    }
    if (
        [int]$credential.schema_version -ne 1 -or
        [string]$credential.username -cne 'drawdown' -or
        [string]$credential.password -notmatch '^[A-Za-z0-9_-]{32,128}$'
    ) {
        throw 'Public access credential has an invalid schema or value.'
    }
    return [pscustomobject]@{
        Username = [string]$credential.username
        Password = [string]$credential.password
        Path = [IO.Path]::GetFullPath($item.FullName)
    }
}

function New-DrawdownPublicCredential {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (Test-Path -LiteralPath $Path) {
        return Read-DrawdownPublicCredential -Path $Path
    }
    $directory = Split-Path -Parent ([IO.Path]::GetFullPath($Path))
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force |
            Out-Null
    }
    $bytes = New-Object byte[] 32
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    $password = [Convert]::ToBase64String($bytes).
        TrimEnd('=').
        Replace('+', '-').
        Replace('/', '_')
    $document = [ordered]@{
        schema_version = 1
        username = 'drawdown'
        password = $password
        created_at = [DateTimeOffset]::UtcNow.ToString('o')
    }
    $temporary = Join-Path $directory (
        '.{0}.{1}.tmp' -f (
            Split-Path -Leaf $Path
        ), [guid]::NewGuid().ToString('N')
    )
    try {
        [IO.File]::WriteAllText(
            $temporary,
            ($document | ConvertTo-Json),
            (New-Object Text.UTF8Encoding($false))
        )
        Move-Item -LiteralPath $temporary -Destination $Path -ErrorAction Stop
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
    return Read-DrawdownPublicCredential -Path $Path
}

Export-ModuleMember -Function @(
    'Read-DrawdownPublicCredential'
    'New-DrawdownPublicCredential'
)
