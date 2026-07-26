from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path

import drawdown_lab.reports as reports
import pandas as pd
import pytest
from drawdown_lab.data.catalog import DataCatalog
from drawdown_lab.data.models import MarketFrame
from drawdown_lab.reports.privacy import privacy_scan
from drawdown_lab.storage.database import Database
from drawdown_lab.storage.jobs import JobStore

RESULT_ID = "result-qqq-001"
RESULT_CREATED_AT = "2026-08-01T01:30:00+00:00"
FETCHED_AT = datetime(2026, 8, 1, 0, 45, tzinfo=UTC)


def _frame(symbol_offset: float) -> MarketFrame:
    index = pd.date_range("2026-07-29", "2026-07-31", freq="B", name="session")
    close = pd.Series(
        [100.0 + symbol_offset, 101.0 + symbol_offset, 102.0 + symbol_offset],
        index=index,
    )
    data = pd.DataFrame(index=index)
    for field, offset in (
        ("open", -0.5),
        ("high", 0.5),
        ("low", -1.0),
        ("close", 0.0),
    ):
        data[f"raw_{field}"] = close + offset
        data[f"price_{field}"] = close + offset
    data["adj_close"] = close
    data["dividend_raw"] = 0.0
    data["split_ratio"] = 1.0
    return MarketFrame(data)


def _job_request() -> dict[str, object]:
    return {
        "family_id": "nasdaq-100",
        "prototype_symbol": "QQQ",
        "target_symbol": "TQQQ",
        "depths": ["0.20", "0.30"],
        "strategy_template": {
            "name": "private retirement plan",
            "monthly_contribution": "25000.00",
        },
        "walk_forward": {"n_splits": 2},
    }


def _stored_results(database_path: Path, catalog: DataCatalog) -> JobStore:
    database = Database(database_path)
    payload = {
        "mode": "formal",
        "candidates": [
            {
                "early_depletion_rate": 0.0,
                "fold_oos_xirr": [0.08, 0.09],
                "longest_trap_days": 90,
                "oos_xirr": 0.085,
                "pareto_member": True,
                "ratios": [10000, 8000],
                "stability_adjusted_xirr": 0.08,
                "stability_score": 0.95,
                "synthetic_stress_pass": None,
                "worst_5_return": -0.25,
            }
        ],
        "provenance": {
            "family_id": "nasdaq-100",
            "prototype_symbol": "QQQ",
            "ratio_unit": "basis_points",
            "source_kind": "actual",
            "strategy_end": "2026-07-31",
            "strategy_start": "2020-01-01",
            "target_symbol": "TQQQ",
            "walk_forward_splits": 2,
        },
        "schema_version": "1.0",
        "summary": {"n_day": 12, "n_episode": 3},
        "recommendations": [
            {
                "oos_xirr": 0.085,
                "profile": "balanced",
                "ratios": [10000, 8000],
                "stability_adjusted_xirr": 0.08,
            }
        ],
        "synthetic_stress": {
            "evaluated_candidates": 0,
            "passed_candidates": 0,
            "requested": False,
        },
    }
    parameters = _job_request()
    request_json = json.dumps(
        {"request": parameters, "schema_version": "1.0"},
        ensure_ascii=False,
        sort_keys=True,
    )
    raw_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    commit = subprocess.run(
        ["git", "-C", str(_repository_root()), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    lineage_json = json.dumps(
        {
            "code_state": "injected",
            "data_lineage": {
                symbol: {
                    "actual_session_cutoff": snapshot.actual_last_session.isoformat(),
                    "classification": "actual",
                    "fetched_at": snapshot.fetched_at.isoformat(),
                    "policy_cutoff": snapshot.policy_cutoff.isoformat(),
                    "provider": snapshot.provider,
                    "sha256": snapshot.sha256,
                }
                for symbol in ("QQQ", "TQQQ")
                for snapshot in (catalog.snapshot(symbol),)
            },
            "engine_version": "0.1.0",
            "generated_at": RESULT_CREATED_AT,
            "git_commit": commit,
            "parameters": parameters,
            "parameters_sha256": hashlib.sha256(
                json.dumps(
                    parameters,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "result_sha256": hashlib.sha256(raw_json.encode("utf-8")).hexdigest(),
            "schema_version": "1.0",
            "timezone": "UTC",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                id, kind, status, request_json, progress, total,
                cancellation_requested, result_id, created_at, updated_at,
                completed_at
            ) VALUES (
                'job-qqq-001', 'optimization', 'succeeded', ?, 1, 1,
                0, ?, ?, ?, ?
            )
            """,
            (
                request_json,
                RESULT_ID,
                RESULT_CREATED_AT,
                RESULT_CREATED_AT,
                RESULT_CREATED_AT,
            ),
        )
        connection.execute(
            """
            INSERT INTO results (
                id, job_id, kind, schema_version, payload_json,
                lineage_json, created_at
            ) VALUES (?, 'job-qqq-001', 'optimization', '1.0', ?, ?, ?)
            """,
            (RESULT_ID, raw_json, lineage_json, RESULT_CREATED_AT),
        )
    return JobStore(database)


def _catalog(root: Path) -> DataCatalog:
    catalog = DataCatalog(root)
    for symbol, offset in (("QQQ", 0.0), ("TQQQ", 10.0)):
        catalog.store(
            symbol,
            _frame(offset),
            completed_cutoff=date(2026, 7, 31),
            provider="fixture-provider",
            fetched_at=FETCHED_AT,
        )
    return catalog


def _repository_root() -> Path:
    return Path(__file__).parents[4]


def _exporter(tmp_path: Path, output_name: str = "private"):
    exporter_type = getattr(reports, "ReportExporter", None)
    assert exporter_type is not None, "ReportExporter application service is required"
    catalog = _catalog(tmp_path / f"{output_name}-data")
    return exporter_type(
        job_store=_stored_results(
            tmp_path / f"{output_name}.sqlite",
            catalog,
        ),
        output_root=tmp_path / output_name,
    )


def _bundle_bytes(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_public_export_boundary_accepts_only_persisted_id_and_formats(
    tmp_path: Path,
) -> None:
    exporter = _exporter(tmp_path)
    assert tuple(inspect.signature(exporter.export_report).parameters) == (
        "result_id",
        "formats",
    )

    manifest = exporter.export_report(RESULT_ID, ("json",))

    assert manifest.result_id == RESULT_ID
    with pytest.raises(KeyError):
        exporter.export_report("result-never-persisted")
    with pytest.raises(TypeError):
        exporter.export_report(  # type: ignore[call-arg]
            RESULT_ID,
            result_source=object(),
        )
    with pytest.raises(TypeError):
        exporter.export_report(  # type: ignore[call-arg]
            RESULT_ID,
            provenance={"git_commit": "deadbeef"},
        )


def test_report_derives_complete_lineage_from_store_catalog_and_git(
    tmp_path: Path,
) -> None:
    exporter = _exporter(tmp_path)
    manifest = exporter.export_report(RESULT_ID)
    document = json.loads((manifest.directory / "report.json").read_text("utf-8"))
    lineage = document["lineage"]
    expected_git_commit = subprocess.run(
        ["git", "-C", str(_repository_root()), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert lineage["engine_version"] == "0.1.0"
    assert lineage["git_commit"] == expected_git_commit
    assert lineage["code_state"] == "injected"
    assert lineage["policy_cutoff"] == "2026-07-31"
    assert lineage["actual_session_cutoff"] == "2026-07-31"
    assert lineage["generated_at"] == RESULT_CREATED_AT
    assert lineage["parameters"] == _job_request()
    assert lineage["parameters_sha256"] == hashlib.sha256(
        json.dumps(
            _job_request(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert lineage["analysis_boundary"] == {
        "formal_result": "actual",
        "synthetic_stress": "not_requested",
    }
    assert lineage["result_sha256"] == hashlib.sha256(
        exporter.job_store.get_result(RESULT_ID).raw_json.encode("utf-8")
    ).hexdigest()
    assert set(lineage["data_lineage"]) == {"QQQ", "TQQQ"}
    catalog = DataCatalog(tmp_path / "private-data")
    for symbol in ("QQQ", "TQQQ"):
        snapshot = catalog.snapshot(symbol)
        assert lineage["data_hashes"][symbol] == snapshot.sha256
        assert lineage["data_lineage"][symbol] == {
            "actual_session_cutoff": "2026-07-31",
            "classification": "actual",
            "fetched_at": FETCHED_AT.isoformat(),
            "policy_cutoff": "2026-07-31",
            "provider": "fixture-provider",
            "sha256": snapshot.sha256,
        }
    html = (manifest.directory / "report.html").read_text(encoding="utf-8")
    assert "fixture-provider" in html
    assert FETCHED_AT.isoformat() in html
    assert "private retirement plan" in html
    assert "not_requested" in html
    with pytest.raises(TypeError):
        manifest.provenance.parameters["family_id"] = "caller-change"  # type: ignore[index]
    with pytest.raises(TypeError):
        manifest.provenance.parameters["strategy_template"]["name"] = "caller-change"  # type: ignore[index]


def test_report_keeps_result_time_lineage_after_catalog_refresh(
    tmp_path: Path,
) -> None:
    exporter = _exporter(tmp_path)
    catalog = DataCatalog(tmp_path / "private-data")
    original = {
        symbol: catalog.snapshot(symbol)
        for symbol in ("QQQ", "TQQQ")
    }
    refreshed_at = datetime(2026, 8, 2, 0, 45, tzinfo=UTC)
    for symbol, offset in (("QQQ", 100.0), ("TQQQ", 110.0)):
        catalog.store(
            symbol,
            _frame(offset),
            completed_cutoff=date(2026, 8, 1),
            provider="later-provider",
            fetched_at=refreshed_at,
        )

    manifest = exporter.export_report(RESULT_ID)
    lineage = manifest.provenance.as_dict()["data_lineage"]

    assert isinstance(lineage, dict)
    for symbol in ("QQQ", "TQQQ"):
        assert lineage[symbol]["provider"] == original[symbol].provider
        assert lineage[symbol]["fetched_at"] == original[symbol].fetched_at.isoformat()
        assert lineage[symbol]["sha256"] == original[symbol].sha256
        assert lineage[symbol]["policy_cutoff"] == original[
            symbol
        ].policy_cutoff.isoformat()


def test_report_fails_closed_if_job_parameters_change_after_result(
    tmp_path: Path,
) -> None:
    exporter = _exporter(tmp_path)
    job = exporter.job_store.get("job-qqq-001")
    mutated = json.loads(job.request_json)
    mutated["request"]["family_id"] = "sp-500"
    with exporter.job_store.database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET request_json = ? WHERE id = ?",
            (json.dumps(mutated, sort_keys=True), job.id),
        )

    with pytest.raises(RuntimeError, match="parameters"):
        exporter.export_report(RESULT_ID)


def test_html_json_csv_and_manifest_are_byte_deterministic(tmp_path: Path) -> None:
    first = _exporter(tmp_path, "first").export_report(RESULT_ID)
    second = _exporter(tmp_path, "second").export_report(RESULT_ID)

    assert first.export_id == second.export_id
    assert _bundle_bytes(first.directory) == _bundle_bytes(second.directory)
    assert set(first.artifacts) == {
        "candidates_csv",
        "html",
        "json",
        "recommendations_csv",
    }
    assert (
        first.directory / "candidates.csv"
    ).read_text(encoding="utf-8").splitlines() == [
        (
            "early_depletion_rate,fold_oos_xirr,longest_trap_days,oos_xirr,"
            "pareto_member,ratios,stability_adjusted_xirr,stability_score,"
            "synthetic_stress_pass,worst_5_return"
        ),
        (
            '0.0,"[0.08,0.09]",90,0.085,true,"[10000,8000]",'
            "0.08,0.95,,-0.25"
        ),
    ]


def test_csv_artifacts_export_optimization_rows_instead_of_blank_files(
    tmp_path: Path,
) -> None:
    manifest = _exporter(tmp_path).export_report(RESULT_ID, ("csv",))

    assert set(manifest.artifacts) == {
        "candidates_csv",
        "json",
        "recommendations_csv",
    }
    candidates = (manifest.directory / "candidates.csv").read_text("utf-8")
    recommendations = (manifest.directory / "recommendations.csv").read_text(
        "utf-8"
    )
    assert "stability_adjusted_xirr" in candidates
    assert "balanced" in recommendations
    assert candidates.strip()
    assert recommendations.strip()


def test_export_fails_closed_if_persisted_result_no_longer_matches_lineage(
    tmp_path: Path,
) -> None:
    exporter = _exporter(tmp_path)
    with exporter.job_store.database.connect() as connection:
        raw = connection.execute(
            "SELECT lineage_json FROM results WHERE id = ?",
            (RESULT_ID,),
        ).fetchone()[0]
        lineage = json.loads(raw)
        lineage["result_sha256"] = "0" * 64
        connection.execute(
            "UPDATE results SET lineage_json = ? WHERE id = ?",
            (json.dumps(lineage, sort_keys=True), RESULT_ID),
        )

    with pytest.raises(RuntimeError, match="hash"):
        exporter.export_report(RESULT_ID)


def test_existing_content_addressed_bundle_is_immutable(tmp_path: Path) -> None:
    exporter = _exporter(tmp_path)
    manifest = exporter.export_report(RESULT_ID)
    (manifest.directory / "extra.json").write_text(
        '{"summary":"unexpected"}',
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError, match="collision"):
        exporter.export_report(RESULT_ID)


def test_content_addressed_export_id_binds_rendered_html_bytes(
    tmp_path: Path,
) -> None:
    manifest = _exporter(tmp_path).export_report(RESULT_ID)
    html_path = manifest.directory / "report.html"
    html_path.write_text(
        "<!doctype html><html><body>different scanner-safe report</body></html>",
        encoding="utf-8",
    )
    manifest_path = manifest.directory / "manifest.json"
    manifest_document = json.loads(manifest_path.read_text("utf-8"))
    manifest_document["artifacts"]["html"]["sha256"] = hashlib.sha256(
        html_path.read_bytes()
    ).hexdigest()
    manifest_document["artifacts"]["html"]["size_bytes"] = html_path.stat().st_size
    manifest_path.write_text(
        json.dumps(manifest_document, sort_keys=True),
        encoding="utf-8",
    )

    result = privacy_scan(manifest.directory)

    assert result.allowed is False
    assert "export_id_mismatch" in {finding.code for finding in result.findings}


def test_report_template_is_packaged_for_non_editable_installs() -> None:
    configuration = tomllib.loads(
        (_repository_root() / "pyproject.toml").read_text(encoding="utf-8")
    )
    force_include = configuration["tool"]["hatch"]["build"]["targets"]["wheel"][
        "force-include"
    ]
    assert force_include["apps/api/templates/report.html.j2"] == (
        "drawdown_lab/templates/report.html.j2"
    )
