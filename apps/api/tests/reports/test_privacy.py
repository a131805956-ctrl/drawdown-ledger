from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from drawdown_lab.reports.privacy import privacy_scan


def _write_export_bundle(
    root: Path,
    *,
    report_text: str | None = None,
    parameters: dict[str, object] | None = None,
    report_schema_version: str = "1.0",
) -> Path:
    result_id = "result-safe"
    result_document = {
        "candidates": [],
        "recommendations": [],
        "schema_version": "1.0",
        "summary": "public-safe",
    }
    persisted_parameters = parameters or {"family_id": "nasdaq-100"}
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
        "parameters": persisted_parameters,
        "parameters_sha256": hashlib.sha256(
            json.dumps(
                persisted_parameters,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "policy_cutoff": "2026-07-31",
        "result_sha256": hashlib.sha256(
            json.dumps(
                result_document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "timezone": "UTC",
    }
    seed = {
        "candidates": [],
        "disclaimer": "historical research only",
        "formats": ["json"],
        "lineage": lineage,
        "recommendations": [],
        "result": result_document,
        "result_id": result_id,
        "schema_version": report_schema_version,
        "stored_schema_version": report_schema_version,
        "title": "Optimization research result",
    }
    canonical_seed = (
        json.dumps(
            seed,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    identity_seed = {
        "artifact_sha256": {
            "report.json": hashlib.sha256(canonical_seed).hexdigest()
        },
        "report": seed,
    }
    export_id = (
        "export-"
        + hashlib.sha256(
            (
                json.dumps(
                    identity_seed,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
        ).hexdigest()[:24]
    )
    if report_text is None:
        report_text = json.dumps(
            {**seed, "export_id": export_id},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
    bundle = root / export_id
    bundle.mkdir()
    report = bundle / "report.json"
    report.write_text(report_text, encoding="utf-8")
    report_bytes = report.read_bytes()
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
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    return bundle


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (r'{"note":"C:\Users\someone\private"}', "absolute_local_path"),
        ('{"note":"/etc/drawdown/private.json"}', "absolute_local_path"),
        ('{"source":"/private.json"}', "absolute_local_path"),
        ('{"source":"file:///private.json"}', "absolute_local_path"),
        ('{"source":"file:/private.json"}', "absolute_local_path"),
        ('{"source":"/usr/local/share/private-data.json"}', "absolute_local_path"),
        ('{"source":"//server/share/private-data.json"}', "absolute_local_path"),
        ('{"api_key":"sk-proj-not-a-real-secret"}', "secret"),
        ('{"source":"reports/private/strategy-17.json"}', "private_path"),
        ('{"strategy_name":"personal retirement plan"}', "private_field"),
        ('{"name":"personal retirement plan"}', "private_field"),
        ('{"na\\u006de":"personal retirement plan"}', "private_field"),
        ('{"api\\u005fkey":"redacted"}', "secret"),
        ('{"token":"sk-\\u0070roj-abcdefgh"}', "secret"),
        ('{"full_name":"Alice Smith"}', "private_field"),
        ('{"fullName":"Alice Smith"}', "private_field"),
        ('{"refresh_token":"redacted"}', "secret"),
        ('{"authToken":"redacted"}', "secret"),
        ('{"session-token":"redacted"}', "secret"),
        ('{"title":"<script>alert(1)</script>"}', "active_content"),
        ('{"formula":"=HYPERLINK(\\"https://example.test\\")"}', "unsafe_formula"),
    ],
)
def test_unsafe_publication_payloads_are_blocked(
    tmp_path: Path,
    payload: str,
    expected_code: str,
) -> None:
    report = tmp_path / "report.json"
    report.write_text(payload, encoding="utf-8")

    result = privacy_scan(report)

    assert result.allowed is False
    assert expected_code in {finding.code for finding in result.findings}
    assert "sk-proj-not-a-real-secret" not in repr(result)


def test_private_strategy_field_in_csv_blocks_publication(tmp_path: Path) -> None:
    report = tmp_path / "trades.csv"
    report.write_text(
        "entry_date,strategy_name\n2020-03-13,personal retirement plan\n",
        encoding="utf-8",
    )

    result = privacy_scan(report)

    assert result.allowed is False
    assert "private_field" in {finding.code for finding in result.findings}


@pytest.mark.parametrize(
    ("header", "expected_code"),
    [
        ("full_name", "private_field"),
        ("fullName", "private_field"),
        ("refresh_token", "secret"),
        ("authToken", "secret"),
        ("session-token", "secret"),
    ],
)
def test_normalized_private_csv_headers_fail_closed(
    tmp_path: Path,
    header: str,
    expected_code: str,
) -> None:
    report = tmp_path / "report.csv"
    report.write_text(f"{header},score\nredacted,1\n", encoding="utf-8")

    result = privacy_scan(report)

    assert result.allowed is False
    assert expected_code in {finding.code for finding in result.findings}


def test_complete_bundle_with_full_name_parameter_fails_closed(
    tmp_path: Path,
) -> None:
    bundle = _write_export_bundle(
        tmp_path,
        parameters={
            "family_id": "nasdaq-100",
            "full_name": "Alice Smith",
        },
    )

    result = privacy_scan(bundle)

    assert result.allowed is False
    assert "private_field" in {finding.code for finding in result.findings}


def test_clean_relative_report_bundle_is_allowed(tmp_path: Path) -> None:
    bundle = _write_export_bundle(tmp_path)

    result = privacy_scan(bundle)

    assert result.allowed is True
    assert result.findings == ()


def test_private_relative_artifact_path_blocks_publication(tmp_path: Path) -> None:
    private_artifact = tmp_path / "strategies" / "private" / "retirement.json"
    private_artifact.parent.mkdir(parents=True)
    private_artifact.write_text('{"summary":"redacted"}', encoding="utf-8")

    result = privacy_scan(tmp_path)

    assert result.allowed is False
    assert "private_path" in {finding.code for finding in result.findings}


def test_empty_directory_fails_closed(tmp_path: Path) -> None:
    result = privacy_scan(tmp_path)

    assert result.allowed is False
    assert "missing_manifest" in {finding.code for finding in result.findings}


def test_unsupported_artifact_type_fails_closed(tmp_path: Path) -> None:
    bundle = _write_export_bundle(tmp_path)
    (bundle / "strategy.yaml").write_text(
        "name: personal retirement plan\n",
        encoding="utf-8",
    )

    result = privacy_scan(bundle)

    assert result.allowed is False
    assert "unsupported_artifact" in {finding.code for finding in result.findings}


def test_undeclared_empty_directory_fails_closed(tmp_path: Path) -> None:
    bundle = _write_export_bundle(tmp_path)
    (bundle / "undeclared").mkdir()

    result = privacy_scan(bundle)

    assert result.allowed is False
    assert "unexpected_directory" in {
        finding.code for finding in result.findings
    }


@pytest.mark.parametrize(
    ("name", "relative_path", "media_type"),
    [
        ("candidates_csv", "candidates.csv", "text/csv; charset=utf-8"),
        ("html", "report.html", "text/html; charset=utf-8"),
    ],
)
def test_zero_byte_declared_artifact_fails_closed(
    tmp_path: Path,
    name: str,
    relative_path: str,
    media_type: str,
) -> None:
    bundle = _write_export_bundle(tmp_path)
    artifact = bundle / relative_path
    artifact.write_bytes(b"")
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][name] = {
        "media_type": media_type,
        "relative_path": relative_path,
        "sha256": hashlib.sha256(b"").hexdigest(),
        "size_bytes": 0,
    }
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )

    result = privacy_scan(bundle)

    assert result.allowed is False
    assert "empty_artifact" in {finding.code for finding in result.findings}


def test_binary_content_fails_closed_even_when_manifest_hash_matches(
    tmp_path: Path,
) -> None:
    bundle = _write_export_bundle(tmp_path)
    report = bundle / "report.json"
    report.write_bytes(b"\xff\xfe\xfd")
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["json"]["sha256"] = hashlib.sha256(
        report.read_bytes()
    ).hexdigest()
    manifest["artifacts"]["json"]["size_bytes"] = report.stat().st_size
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )

    result = privacy_scan(bundle)

    assert result.allowed is False
    assert "binary_file" in {finding.code for finding in result.findings}


def test_manifest_exact_set_hash_and_size_are_enforced(tmp_path: Path) -> None:
    bundle = _write_export_bundle(tmp_path)
    report = bundle / "report.json"
    report.write_text('{"summary":"tampered but scanner-safe"}', encoding="utf-8")
    (bundle / "extra.json").write_text('{"summary":"extra"}', encoding="utf-8")

    result = privacy_scan(bundle)
    codes = {finding.code for finding in result.findings}

    assert result.allowed is False
    assert {"artifact_set_mismatch", "artifact_hash_mismatch"} <= codes


def test_report_identifiers_must_match_manifest(tmp_path: Path) -> None:
    bundle = _write_export_bundle(
        tmp_path,
        report_text=(
            '{"export_id":"export-other","result_id":"result-other",'
            '"summary":"scanner-safe"}'
        ),
    )

    result = privacy_scan(bundle)

    assert result.allowed is False
    assert "artifact_identifier_mismatch" in {
        finding.code for finding in result.findings
    }


def test_report_content_and_export_id_are_bound_to_manifest(
    tmp_path: Path,
) -> None:
    bundle = _write_export_bundle(tmp_path)
    report_path = bundle / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["formats"] = ["json"]
    report["lineage"] = {"engine_version": "invented"}
    report["result"] = {"summary": "invented result"}
    report["schema_version"] = "1.0"
    report_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["json"]["sha256"] = hashlib.sha256(
        report_path.read_bytes()
    ).hexdigest()
    manifest["artifacts"]["json"]["size_bytes"] = report_path.stat().st_size
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )

    result = privacy_scan(bundle)

    assert result.allowed is False
    assert {
        "artifact_lineage_mismatch",
        "result_hash_mismatch",
        "export_id_mismatch",
    } <= {finding.code for finding in result.findings}


def test_unknown_manifest_fields_fail_closed(tmp_path: Path) -> None:
    bundle = _write_export_bundle(tmp_path)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["private_metadata"] = {"owner": "somebody"}
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )

    result = privacy_scan(bundle)

    assert result.allowed is False
    assert "invalid_manifest" in {finding.code for finding in result.findings}


def test_coordinated_unsupported_report_schema_rewrite_fails_closed(
    tmp_path: Path,
) -> None:
    bundle = _write_export_bundle(
        tmp_path,
        report_schema_version="9.9",
    )

    result = privacy_scan(bundle)

    assert result.allowed is False
    assert "invalid_report_schema" in {
        finding.code for finding in result.findings
    }


def test_manifest_requires_complete_bound_lineage(tmp_path: Path) -> None:
    bundle = _write_export_bundle(tmp_path)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["lineage"]["data_lineage"]
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )

    result = privacy_scan(bundle)

    assert result.allowed is False
    assert "invalid_lineage" in {finding.code for finding in result.findings}


def test_root_symlink_fails_closed_without_following_target(tmp_path: Path) -> None:
    target = _write_export_bundle(tmp_path)
    link = tmp_path / "export-link"
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")

    result = privacy_scan(link)

    assert result.allowed is False
    assert result.scanned_files == 0
    assert "symlink" in {finding.code for finding in result.findings}


def test_fixed_demo_is_versioned_non_live_and_matches_manifest_hash() -> None:
    repository_root = Path(__file__).parents[4]
    demo_root = repository_root / "apps" / "web" / "public" / "demo"
    manifest = json.loads(
        (demo_root / "manifest.json").read_text(encoding="utf-8")
    )
    evidence_path = demo_root / manifest["evidence_file"]
    evidence_bytes = evidence_path.read_bytes()
    evidence = json.loads(evidence_bytes)

    assert manifest["schema_version"] == "1.0"
    assert manifest["demo_version"] == "2026-07-31-v1"
    assert manifest["fixed_data_date"] == "2026-07-31"
    assert manifest["live"] is False
    assert manifest["evidence_sha256"] == hashlib.sha256(evidence_bytes).hexdigest()
    assert evidence["symbol"] == "QQQ"
    assert evidence["data_classification"] == "illustrative_synthetic_fixture"
    assert evidence["fixed_data_date"] == "2026-07-31"
    assert evidence["sample_warning"]
    assert privacy_scan(demo_root).allowed is True
