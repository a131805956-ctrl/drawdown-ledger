from __future__ import annotations

from pathlib import Path

from drawdown_lab.api.app import Settings, create_app
from fastapi.testclient import TestClient


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_path=tmp_path / "drawdown.sqlite",
                data_root=tmp_path / "data",
            )
        )
    )


def test_openapi_exposes_complete_versioned_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        schema = client.get("/openapi.json").json()

    expected_paths = {
        "/api/v1/instruments",
        "/api/v1/data/health",
        "/api/v1/data/update",
        "/api/v1/evidence/analyze",
        "/api/v1/strategies/backtest",
        "/api/v1/optimizations",
        "/api/v1/jobs/{job_id}",
        "/api/v1/jobs/{job_id}/cancel",
        "/api/v1/market/overview",
        "/api/v1/results",
        "/api/v1/results/{result_id}",
        "/api/v1/reports",
        "/api/v1/reports/{report_id}",
    }
    assert expected_paths <= set(schema["paths"])
    assert schema["info"]["version"] == "1.0"


def test_responses_are_schema_versioned_and_json_is_deterministic(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first = client.get("/api/v1/instruments")
        second = client.get("/api/v1/instruments")
        health = client.get("/api/v1/data/health")
        overview = client.get("/api/v1/market/overview")

    assert first.status_code == 200
    assert first.content == second.content
    assert first.json()["schema_version"] == "1.0"
    assert health.json()["schema_version"] == "1.0"
    assert overview.json()["schema_version"] == "1.0"


def test_unconfigured_data_update_is_typed_and_never_calls_yahoo(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/v1/data/update",
            json={"schema_version": "1.0", "as_of": "2026-07-26"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1.0",
        "status": "not_configured",
        "cutoff": None,
        "request_count": 0,
        "refreshed_symbols": [],
        "message": "No market-data provider is configured.",
    }


def test_settings_default_data_root_is_usable_for_app_factory(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(database_path=tmp_path / "drawdown.sqlite"))) as client:
        response = client.get("/api/v1/instruments")

    assert response.status_code == 200
    assert (tmp_path / "data" / "catalog.sqlite").exists()


def test_openapi_advertises_versioned_error_model_for_custom_4xx(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        schema = client.get("/openapi.json").json()

    optimization = schema["paths"]["/api/v1/optimizations"]["post"]["responses"]
    cancel = schema["paths"]["/api/v1/jobs/{job_id}/cancel"]["post"]["responses"]
    assert optimization["404"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ErrorResponse"
    )
    assert optimization["422"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ErrorResponse"
    )
    assert cancel["409"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ErrorResponse"
    )
    issue = schema["components"]["schemas"]["ValidationIssue"]
    assert issue["additionalProperties"] is False
