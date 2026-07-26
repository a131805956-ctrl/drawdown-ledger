Set-StrictMode -Version Latest

function Resolve-DrawdownProjectPython {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,

        [AllowNull()]
        [AllowEmptyString()]
        [string]$PythonExecutable
    )

    if (-not [string]::IsNullOrWhiteSpace($PythonExecutable)) {
        if (Test-Path -LiteralPath $PythonExecutable -PathType Leaf) {
            return [IO.Path]::GetFullPath($PythonExecutable)
        }
        $command = Get-Command `
            -Name $PythonExecutable `
            -ErrorAction Stop |
            Select-Object -First 1
        if (
            $command.CommandType -notin @(
                [Management.Automation.CommandTypes]::Application,
                [Management.Automation.CommandTypes]::ExternalScript
            )
        ) {
            throw "Python executable is not an application or script: $PythonExecutable"
        }
        return [IO.Path]::GetFullPath([string]$command.Source)
    }

    $candidates = @(
        (Join-Path $ProjectRoot '.venv\Scripts\python.exe'),
        (Join-Path $ProjectRoot '.venv\Scripts\python.cmd'),
        (Join-Path $ProjectRoot '.venv\Scripts\python.ps1'),
        (Join-Path $ProjectRoot '.venv\bin\python')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return [IO.Path]::GetFullPath($candidate)
        }
    }
    throw (
        "Project virtualenv Python was not found under '{0}\.venv'. " +
        'Run scripts\Start.ps1 or pass -PythonExecutable explicitly.'
    ) -f ([IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/'))
}

Export-ModuleMember -Function 'Resolve-DrawdownProjectPython'
