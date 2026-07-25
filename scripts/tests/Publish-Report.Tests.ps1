$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$PublishScript = Join-Path $RepositoryRoot 'scripts\Publish-Report.ps1'
$PrivacyScript = Join-Path $RepositoryRoot 'scripts\Test-PublishedPrivacy.ps1'
$PythonExecutable = (Get-Command python -ErrorAction Stop).Source

Describe 'Privacy-gated static report publication' {
    BeforeEach {
        $PrivateRoot = Join-Path $TestDrive 'private'
        $PublishedRoot = Join-Path $TestDrive 'published'
        New-Item -ItemType Directory -Path $PrivateRoot -Force | Out-Null
    }

    It 'rejects export IDs containing path traversal' {
        {
            & $PublishScript `
                -ExportId '..\outside' `
                -PrivateRoot $PrivateRoot `
                -PublishedRoot $PublishedRoot `
                -PythonExecutable $PythonExecutable
        } | Should Throw

        Test-Path (Join-Path $TestDrive 'outside') | Should Be $false
    }

    It 'blocks a bundle containing an absolute local path' {
        $ExportId = 'export-blocked'
        $Source = Join-Path $PrivateRoot $ExportId
        New-Item -ItemType Directory -Path $Source -Force | Out-Null
        @{
            export_id = $ExportId
            result_id = 'result-blocked'
            schema_version = '1.0'
        } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Source 'manifest.json') -Encoding UTF8
        '{"note":"C:\\Users\\someone\\private"}' |
            Set-Content -LiteralPath (Join-Path $Source 'report.json') -Encoding UTF8

        {
            & $PublishScript `
                -ExportId $ExportId `
                -PrivateRoot $PrivateRoot `
                -PublishedRoot $PublishedRoot `
                -PythonExecutable $PythonExecutable
        } | Should Throw

        Test-Path (Join-Path $PublishedRoot $ExportId) | Should Be $false
    }

    It 'copies only the explicit export ID after a successful privacy scan' {
        foreach ($ExportId in @('export-safe-01', 'export-safe-02')) {
            $Source = Join-Path $PrivateRoot $ExportId
            New-Item -ItemType Directory -Path $Source -Force | Out-Null
            @{
                export_id = $ExportId
                result_id = "result-$ExportId"
                schema_version = '1.0'
            } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Source 'manifest.json') -Encoding UTF8
            '{"summary":"fixed public-safe research fixture"}' |
                Set-Content -LiteralPath (Join-Path $Source 'report.json') -Encoding UTF8
        }

        $Result = & $PublishScript `
            -ExportId 'export-safe-01' `
            -PrivateRoot $PrivateRoot `
            -PublishedRoot $PublishedRoot `
            -PythonExecutable $PythonExecutable

        $Result.ExportId | Should Be 'export-safe-01'
        Test-Path (Join-Path $PublishedRoot 'export-safe-01\manifest.json') |
            Should Be $true
        Test-Path (Join-Path $PublishedRoot 'export-safe-02') | Should Be $false
        {
            & $PrivacyScript `
                -Path (Join-Path $PublishedRoot 'export-safe-01') `
                -PythonExecutable $PythonExecutable
        } | Should Not Throw
    }
}
