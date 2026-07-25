from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from drawdown_lab.reports.privacy import privacy_scan


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (r'{"note":"C:\Users\someone\private"}', "absolute_local_path"),
        ('{"note":"/etc/drawdown/private.json"}', "absolute_local_path"),
        ('{"api_key":"sk-proj-not-a-real-secret"}', "secret"),
        ('{"source":"reports/private/strategy-17.json"}', "private_path"),
        ('{"strategy_name":"personal retirement plan"}', "private_field"),
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


def test_clean_relative_report_bundle_is_allowed(tmp_path: Path) -> None:
    bundle = tmp_path / "export-safe"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "export_id": "export-safe",
                "result_id": "result-safe",
                "data_hashes": {"QQQ": "a" * 64},
                "limitations": ["Historical research only."],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (bundle / "events.csv").write_text(
        "signal_date,threshold\n2020-03-12,-0.2\n",
        encoding="utf-8",
    )

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
