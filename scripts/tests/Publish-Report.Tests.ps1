$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$PublishScript = Join-Path $RepositoryRoot 'scripts\Publish-Report.ps1'
$PrivacyScript = Join-Path $RepositoryRoot 'scripts\Test-PublishedPrivacy.ps1'
$PythonExecutable = (Get-Command python -ErrorAction Stop).Source

function New-TestExportBundle {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ExportId,
        [string]$ResultId = 'result-safe'
    )

    $Generator = @'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
label = sys.argv[2]
result_id = sys.argv[3]
result = {
    "candidates": [],
    "fixture_label": label,
    "recommendations": [],
    "schema_version": "1.0",
    "summary": "fixed public-safe research fixture",
}
result_bytes = json.dumps(
    result,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
lineage = {
    "actual_session_cutoff": "2026-07-31",
    "analysis_boundary": {
        "formal_result": "actual",
        "synthetic_stress": "not_requested",
    },
    "assumptions": ["next-open execution"],
    "code_state": "injected",
    "data_hashes": {"QQQ": "a" * 64},
    "data_lineage": {
        "QQQ": {
            "actual_session_cutoff": "2026-07-31",
            "classification": "actual",
            "fetched_at": "2026-08-01T00:45:00+00:00",
            "policy_cutoff": "2026-07-31",
            "provider": "fixture-provider",
            "sha256": "a" * 64,
        }
    },
    "engine_version": "0.1.0",
    "generated_at": "2026-08-01T01:30:00+00:00",
    "git_commit": "0123456789abcdef0123456789abcdef01234567",
    "limitations": ["historical research only"],
    "parameters": {"family_id": "nasdaq-100"},
    "parameters_sha256": hashlib.sha256(
        json.dumps(
            {"family_id": "nasdaq-100"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest(),
    "policy_cutoff": "2026-07-31",
    "result_sha256": hashlib.sha256(result_bytes).hexdigest(),
    "timezone": "UTC",
}
seed = {
    "candidates": [],
    "disclaimer": "historical research only",
    "formats": ["json"],
    "lineage": lineage,
    "recommendations": [],
    "result": result,
    "result_id": result_id,
    "schema_version": "1.0",
    "stored_schema_version": "1.0",
    "title": "Optimization research result",
}
seed_bytes = (
    json.dumps(seed, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
).encode("utf-8")
identity_seed = {
    "artifact_sha256": {
        "report.json": hashlib.sha256(seed_bytes).hexdigest(),
    },
    "report": seed,
}
identity_bytes = (
    json.dumps(identity_seed, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
).encode("utf-8")
export_id = "export-" + hashlib.sha256(identity_bytes).hexdigest()[:24]
report_bytes = (
    json.dumps(
        {**seed, "export_id": export_id},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    + "\n"
).encode("utf-8")
source = root / export_id
source.mkdir(parents=True)
(source / "report.json").write_bytes(report_bytes)
manifest = {
    "artifacts": {
        "json": {
            "media_type": "application/json",
            "relative_path": "report.json",
            "sha256": hashlib.sha256(report_bytes).hexdigest(),
            "size_bytes": len(report_bytes),
        }
    },
    "export_id": export_id,
    "lineage": lineage,
    "result_id": result_id,
    "schema_version": "1.0",
}
(source / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps({"ExportId": export_id, "Source": str(source)}))
'@
    $GeneratorPath = Join-Path $Root '.fixture-generator.py'
    Set-Content `
        -LiteralPath $GeneratorPath `
        -Value $Generator `
        -Encoding UTF8
    try {
        $Generated = & $PythonExecutable `
            $GeneratorPath `
            $Root `
            $ExportId `
            $ResultId
    }
    finally {
        Remove-Item -LiteralPath $GeneratorPath -Force -ErrorAction SilentlyContinue
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'Unable to create the privacy-gate test fixture.'
    }
    return ($Generated | ConvertFrom-Json)
}

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
        $Bundle = New-TestExportBundle `
            -Root $PrivateRoot `
            -ExportId 'blocked'
        $ExportId = $Bundle.ExportId
        $Source = $Bundle.Source
        $ReportPath = Join-Path $Source 'report.json'
        ('{"export_id":"' + $ExportId + '","result_id":"result-safe",' +
            '"note":"C:\\Users\\someone\\private"}') |
            Set-Content -LiteralPath $ReportPath -Encoding UTF8
        $ManifestPath = Join-Path $Source 'manifest.json'
        $Manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath $ManifestPath |
            ConvertFrom-Json
        $Manifest.artifacts.json.sha256 = (
            Get-FileHash -LiteralPath $ReportPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        $Manifest.artifacts.json.size_bytes = (Get-Item -LiteralPath $ReportPath).Length
        $Manifest | ConvertTo-Json -Depth 12 |
            Set-Content -LiteralPath $ManifestPath -Encoding UTF8

        {
            & $PublishScript `
                -ExportId $ExportId `
                -PrivateRoot $PrivateRoot `
                -PublishedRoot $PublishedRoot `
                -PythonExecutable $PythonExecutable
        } | Should Throw

        Test-Path (Join-Path $PublishedRoot $ExportId) | Should Be $false
    }

    It 'copies only the explicit validated export ID' {
        $First = New-TestExportBundle `
            -Root $PrivateRoot `
            -ExportId 'safe-01'
        $Second = New-TestExportBundle `
            -Root $PrivateRoot `
            -ExportId 'safe-02'

        $Result = & $PublishScript `
            -ExportId $First.ExportId `
            -PrivateRoot $PrivateRoot `
            -PublishedRoot $PublishedRoot `
            -PythonExecutable $PythonExecutable

        $Result.ExportId | Should Be $First.ExportId
        Test-Path (
            Join-Path $PublishedRoot ($First.ExportId + '\manifest.json')
        ) |
            Should Be $true
        Test-Path (Join-Path $PublishedRoot $Second.ExportId) | Should Be $false
        {
            & $PrivacyScript `
                -Path (Join-Path $PublishedRoot $First.ExportId) `
                -PythonExecutable $PythonExecutable
        } | Should Not Throw
    }

    It 'rejects an artifact whose SHA-256 or size no longer matches' {
        $Bundle = New-TestExportBundle `
            -Root $PrivateRoot `
            -ExportId 'tampered'
        $ExportId = $Bundle.ExportId
        $Source = $Bundle.Source
        ('{"export_id":"' + $ExportId + '","result_id":"result-safe",' +
            '"summary":"tampered"}') |
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

    It 'rejects missing or extra files outside the exact artifact set' {
        $Bundle = New-TestExportBundle `
            -Root $PrivateRoot `
            -ExportId 'extra'
        $ExportId = $Bundle.ExportId
        $Source = $Bundle.Source
        '{"summary":"not declared"}' |
            Set-Content -LiteralPath (Join-Path $Source 'extra.json') -Encoding UTF8

        {
            & $PublishScript `
                -ExportId $ExportId `
                -PrivateRoot $PrivateRoot `
                -PublishedRoot $PublishedRoot `
                -PythonExecutable $PythonExecutable
        } | Should Throw

        Test-Path (Join-Path $PublishedRoot $ExportId) | Should Be $false
    }

    It 'rejects invalid schema and result identifiers' {
        $Bundle = New-TestExportBundle `
            -Root $PrivateRoot `
            -ExportId 'invalid-manifest'
        $ExportId = $Bundle.ExportId
        $Source = $Bundle.Source
        $ManifestPath = Join-Path $Source 'manifest.json'
        $Manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath $ManifestPath |
            ConvertFrom-Json
        $Manifest.schema_version = '0.9'
        $Manifest.result_id = '..\private-result'
        $Manifest | ConvertTo-Json -Depth 12 |
            Set-Content -LiteralPath $ManifestPath -Encoding UTF8

        {
            & $PublishScript `
                -ExportId $ExportId `
                -PrivateRoot $PrivateRoot `
                -PublishedRoot $PublishedRoot `
                -PythonExecutable $PythonExecutable
        } | Should Throw
    }

    It 'rejects a source bundle that is a junction outside the private root' {
        $ExportId = 'export-junction'
        $OutsideRoot = Join-Path $TestDrive 'outside-bundle'
        New-Item -ItemType Directory -Path $OutsideRoot -Force | Out-Null
        $OutsideSource = Join-Path $OutsideRoot $ExportId
        New-Item -ItemType Directory -Path $OutsideSource -Force | Out-Null
        $Link = Join-Path $PrivateRoot $ExportId
        New-Item -ItemType Junction -Path $Link -Target $OutsideSource |
            Out-Null

        {
            & $PublishScript `
                -ExportId $ExportId `
                -PrivateRoot $PrivateRoot `
                -PublishedRoot $PublishedRoot `
                -PythonExecutable $PythonExecutable
        } | Should Throw 'Export source contains a symlink, junction, or reparse point.'

        Test-Path (Join-Path $PublishedRoot $ExportId) | Should Be $false
    }

    It 'rejects a private root whose ancestor chain contains a junction' {
        $ActualPrivateRoot = Join-Path $TestDrive 'actual-private'
        New-Item -ItemType Directory -Path $ActualPrivateRoot -Force | Out-Null
        $Bundle = New-TestExportBundle `
            -Root $ActualPrivateRoot `
            -ExportId 'root-junction'
        $ExportId = $Bundle.ExportId
        $LinkedPrivateRoot = Join-Path $TestDrive 'linked-private'
        New-Item -ItemType Junction `
            -Path $LinkedPrivateRoot `
            -Target $ActualPrivateRoot |
            Out-Null

        {
            & $PublishScript `
                -ExportId $ExportId `
                -PrivateRoot $LinkedPrivateRoot `
                -PublishedRoot $PublishedRoot `
                -PythonExecutable $PythonExecutable
        } | Should Throw 'Private report root contains a symlink, junction, or reparse point.'
    }

    It 'rejects a manifest reparse point before reading its outside target' {
        $Bundle = New-TestExportBundle `
            -Root $PrivateRoot `
            -ExportId 'manifest-link'
        $ExportId = $Bundle.ExportId
        $Source = $Bundle.Source
        $OutsideManifest = Join-Path $TestDrive 'outside-manifest'
        New-Item -ItemType Directory -Path $OutsideManifest -Force | Out-Null
        '{"export_id":"outside-value"}' | Set-Content -LiteralPath (
            Join-Path $OutsideManifest 'payload.json'
        ) -Encoding UTF8
        Remove-Item -LiteralPath (Join-Path $Source 'manifest.json') -Force
        New-Item -ItemType Junction `
            -Path (Join-Path $Source 'manifest.json') `
            -Target $OutsideManifest |
            Out-Null

        {
            & $PublishScript `
                -ExportId $ExportId `
                -PrivateRoot $PrivateRoot `
                -PublishedRoot $PublishedRoot `
                -PythonExecutable $PythonExecutable
        } | Should Throw 'Export source manifest contains a symlink, junction, or reparse point.'

        Test-Path (Join-Path $PublishedRoot $ExportId) | Should Be $false
    }
}
