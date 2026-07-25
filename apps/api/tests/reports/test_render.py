from __future__ import annotations

import inspect
import json
import tomllib
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from drawdown_lab.reports import export_report as public_export_report
from drawdown_lab.reports.models import ReportProvenance
from drawdown_lab.reports.render import export_report
from drawdown_lab.storage.database import Database
from drawdown_lab.storage.jobs import JobStore


def _provenance() -> ReportProvenance:
    return ReportProvenance(
        engine_version="0.1.0",
        git_commit="0123456789abcdef0123456789abcdef01234567",
        data_hashes={"QQQ": "a" * 64, "^NDX": "b" * 64},
        policy_cutoff=date(2026, 7, 31),
        actual_session_cutoff=date(2026, 7, 31),
        generated_at=datetime(
            2026,
            8,
            1,
            9,
            30,
            tzinfo=timezone(timedelta(hours=8)),
        ),
        timezone="Asia/Taipei",
        assumptions=(
            "Signals are observed at the close and execute no earlier than the next open.",
        ),
        limitations=(
            "Historical research is not a guarantee of future performance.",
        ),
    )


def _stored_results(database_path: Path) -> JobStore:
    database = Database(database_path)
    payload = {
        "events": [
            {
                "cycle_id": 1,
                "entry_date": "2020-03-13",
                "signal_date": "2020-03-12",
                "threshold": -0.20,
            }
        ],
        "parameters": {"threshold": -0.20},
        "schema_version": "1.0",
        "summary": {"n_day": 12, "n_episode": 3},
        "trades": [
            {
                "cash_spent": "25000.00",
                "entry_date": "2020-03-13",
                "symbol": "QQQ",
            }
        ],
    }
    timestamp = "2026-08-01T01:30:00+00:00"
    raw_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                id, kind, status, request_json, progress, total,
                cancellation_requested, result_id, created_at, updated_at,
                completed_at
            ) VALUES (
                'job-qqq-001', 'optimization', 'succeeded', '{}', 1, 1,
                0, 'result-qqq-001', ?, ?, ?
            )
            """,
            (timestamp, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO results (
                id, job_id, kind, schema_version, payload_json, created_at
            ) VALUES (
                'result-qqq-001', 'job-qqq-001', 'optimization', '1.0', ?, ?
            )
            """,
            (raw_json, timestamp),
        )
    return JobStore(database)


def _export(root: Path):
    store = _stored_results(root.parent / f"{root.name}.sqlite")
    return export_report(
        "result-qqq-001",
        output_root=root,
        provenance=_provenance(),
        result_source=store,
    )


def test_export_accepts_only_a_trusted_stored_result_id(tmp_path: Path) -> None:
    assert public_export_report is export_report
    parameters = inspect.signature(export_report).parameters
    assert "result" not in parameters
    assert "events" not in parameters
    assert "trades" not in parameters
    assert parameters["output_root"].default == Path("reports/private")
    store = _stored_results(tmp_path / "drawdown.sqlite")

    manifest = export_report(
        "result-qqq-001",
        output_root=tmp_path / "private",
        provenance=_provenance(),
        result_source=store,
    )

    report = json.loads((manifest.directory / "report.json").read_text("utf-8"))
    assert report["result"]["summary"] == {"n_day": 12, "n_episode": 3}
    with pytest.raises(KeyError):
        export_report(
            "result-caller-invented",
            output_root=tmp_path / "private",
            provenance=_provenance(),
            result_source=store,
        )


def test_report_template_is_packaged_for_non_editable_installs() -> None:
    repository_root = Path(__file__).parents[4]
    configuration = tomllib.loads(
        (repository_root / "pyproject.toml").read_text(encoding="utf-8")
    )

    force_include = configuration["tool"]["hatch"]["build"]["targets"]["wheel"][
        "force-include"
    ]
    assert force_include["apps/api/templates/report.html.j2"] == (
        "drawdown_lab/templates/report.html.j2"
    )


def test_report_contains_immutable_data_and_engine_lineage(tmp_path: Path) -> None:
    provenance = _provenance()
    manifest = _export(tmp_path / "private")

    assert manifest.engine_version == "0.1.0"
    assert manifest.git_commit == "0123456789abcdef0123456789abcdef01234567"
    assert manifest.data_hashes["QQQ"] == "a" * 64
    assert manifest.policy_cutoff == date(2026, 7, 31)
    assert manifest.actual_session_cutoff == date(2026, 7, 31)
    assert manifest.assumptions == provenance.assumptions
    assert manifest.limitations == provenance.limitations

    with pytest.raises(TypeError):
        provenance.data_hashes["QQQ"] = "c" * 64  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        manifest.engine_version = "changed"  # type: ignore[misc]


def test_html_json_and_csv_exports_are_byte_deterministic(tmp_path: Path) -> None:
    first = _export(tmp_path / "first")
    second = _export(tmp_path / "second")

    assert first.export_id == second.export_id
    assert set(first.artifacts) == {
        "events_csv",
        "html",
        "json",
        "trades_csv",
    }
    for name, artifact in first.artifacts.items():
        first_bytes = (first.directory / artifact.relative_path).read_bytes()
        second_bytes = (
            second.directory / second.artifacts[name].relative_path
        ).read_bytes()
        assert first_bytes == second_bytes
        assert artifact.sha256 == second.artifacts[name].sha256

    report = json.loads((first.directory / "report.json").read_text(encoding="utf-8"))
    assert report["lineage"] == {
        "actual_session_cutoff": "2026-07-31",
        "assumptions": [
            "Signals are observed at the close and execute no earlier than the next open."
        ],
        "data_hashes": {"QQQ": "a" * 64, "^NDX": "b" * 64},
        "engine_version": "0.1.0",
        "generated_at": "2026-08-01T09:30:00+08:00",
        "git_commit": "0123456789abcdef0123456789abcdef01234567",
        "limitations": [
            "Historical research is not a guarantee of future performance."
        ],
        "policy_cutoff": "2026-07-31",
        "timezone": "Asia/Taipei",
    }
    html = (first.directory / "report.html").read_text(encoding="utf-8")
    assert "Optimization research result" in html
    assert "2026-07-31" in html
    assert "Historical research is not a guarantee" in html
    assert (
        first.directory / "events.csv"
    ).read_text(encoding="utf-8").splitlines() == [
        "cycle_id,entry_date,signal_date,threshold",
        "1,2020-03-13,2020-03-12,-0.2",
    ]


def test_export_rejects_missing_lineage_and_unsupported_formats(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="data hash"):
        ReportProvenance(
            engine_version="0.1.0",
            git_commit="0123456789abcdef0123456789abcdef01234567",
            data_hashes={},
            policy_cutoff=date(2026, 7, 31),
            actual_session_cutoff=date(2026, 7, 31),
            generated_at=datetime(2026, 8, 1, tzinfo=UTC),
            timezone="UTC",
            assumptions=("next-open execution",),
            limitations=("historical-only",),
        )

    with pytest.raises(ValueError, match="Unsupported report format"):
        store = _stored_results(tmp_path / "drawdown.sqlite")
        export_report(
            "result-qqq-001",
            formats=("pdf",),
            output_root=tmp_path,
            provenance=_provenance(),
            result_source=store,
        )
