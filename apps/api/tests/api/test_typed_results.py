from __future__ import annotations

import json
import time
from pathlib import Path

from drawdown_lab.api.app import Settings, create_app
from drawdown_lab.storage.database import Database
from fastapi.testclient import TestClient

from apps.api.tests.api.test_trusted_optimizer import _request, _seed


def _wait(client: TestClient, job_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        row = client.get(f"/api/v1/jobs/{job_id}").json()
        if row["status"] in {"succeeded", "failed", "cancelled"}:
            return row
        time.sleep(0.005)
    raise AssertionError("job did not terminate")


def test_openapi_advertises_explicit_formal_result_and_report_models(
    tmp_path: Path,
) -> None:
    with TestClient(
        create_app(Settings(database_path=tmp_path / "drawdown.sqlite"))
    ) as client:
        schema = client.get("/openapi.json").json()

    result_schema = schema["components"]["schemas"]["ResultResponse"]
    report_schema = schema["components"]["schemas"]["ReportResponse"]
    result_payload_refs = {
        item["$ref"].rsplit("/", 1)[-1]
        for item in result_schema["properties"]["payload"]["anyOf"]
    }
    report_content_refs = {
        item["$ref"].rsplit("/", 1)[-1]
        for item in report_schema["properties"]["content"]["anyOf"]
    }
    assert result_payload_refs == {
        "OptimizationResultPayload",
        "LegacyOptimizationPayload",
    }
    assert report_content_refs == {
        "ReportContentResponse",
        "LegacyReportContent",
    }
    candidate = schema["components"]["schemas"]["OptimizationCandidateResponse"]
    assert {
        "ratios",
        "fold_oos_xirr",
        "oos_xirr",
        "worst_5_return",
        "early_depletion_rate",
        "longest_trap_days",
        "stability_score",
        "stability_adjusted_xirr",
        "pareto_member",
        "synthetic_stress_pass",
    } <= set(candidate["properties"])
    assert candidate["additionalProperties"] is False


def test_persisted_formal_result_has_typed_provenance_and_synthetic_summary(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=tmp_path / "drawdown.sqlite",
        data_root=tmp_path / "data",
    )
    assert settings.data_root is not None
    _seed(settings.data_root)
    with TestClient(create_app(settings)) as client:
        accepted = client.post("/api/v1/optimizations", json=_request()).json()
        terminal = _wait(client, accepted["job_id"])
        result = client.get(f"/api/v1/results/{terminal['result_id']}").json()
        report = client.get("/api/v1/reports").json()["reports"][0]

    payload = result["payload"]
    assert payload["schema_version"] == "1.0"
    assert payload["exploration_only"] is False
    assert payload["provenance"] == {
        "family_id": "nasdaq-100",
        "prototype_symbol": "QQQ",
        "target_symbol": "TQQQ",
        "source_kind": "actual",
        "strategy_start": "2020-01-01",
        "strategy_end": "2020-02-03",
        "walk_forward_splits": 2,
        "ratio_unit": "basis_points",
    }
    assert payload["synthetic_stress"] == {
        "requested": False,
        "evaluated_candidates": 0,
        "passed_candidates": 0,
    }
    assert len(payload["candidates"][0]["fold_oos_xirr"]) == 2
    assert report["content"]["status"] == "not_yet_exported"
    assert report["content"]["optimization"]["provenance"] == payload["provenance"]


def test_legacy_json_string_result_and_report_rows_remain_listable_and_readable(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "drawdown.sqlite"
    database = Database(database_path)
    timestamp = "2020-01-01T00:00:00+00:00"
    legacy_result_json = json.dumps("legacy-result-string")
    legacy_report_json = json.dumps("legacy-report-string")
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                id, kind, status, request_json, progress, total,
                cancellation_requested, result_id, created_at, updated_at,
                completed_at
            ) VALUES (
                'legacy-job', 'optimization', 'succeeded', '{}', 1, 1,
                0, 'legacy-result', ?, ?, ?
            )
            """,
            (timestamp, timestamp, timestamp),
        )
        connection.execute(
            """
            INSERT INTO results (
                id, job_id, kind, schema_version, payload_json, created_at
            ) VALUES (
                'legacy-result', 'legacy-job', 'optimization', '0.9', ?, ?
            )
            """,
            (legacy_result_json, timestamp),
        )
        connection.execute(
            """
            INSERT INTO reports (
                id, result_id, title, export_status,
                schema_version, content_json, created_at
            ) VALUES (
                'legacy-report', 'legacy-result', 'Legacy',
                'not_yet_exported', '0.9', ?, ?
            )
            """,
            (legacy_report_json, timestamp),
        )

    with TestClient(create_app(Settings(database_path=database_path))) as client:
        result_list = client.get("/api/v1/results")
        result_detail = client.get("/api/v1/results/legacy-result")
        report_list = client.get("/api/v1/reports")
        report_detail = client.get("/api/v1/reports/legacy-report")

    assert result_list.status_code == 200
    assert result_detail.status_code == 200
    assert report_list.status_code == 200
    assert report_detail.status_code == 200
    assert result_detail.json()["payload"] == {
        "payload_type": "legacy",
        "stored_schema_version": "0.9",
        "raw_json": legacy_result_json,
    }
    assert result_list.json()["results"][0]["payload"] == result_detail.json()["payload"]
    assert report_detail.json()["content"] == {
        "content_type": "legacy",
        "stored_schema_version": "0.9",
        "raw_json": legacy_report_json,
    }
    assert report_list.json()["reports"][0]["content"] == report_detail.json()["content"]
