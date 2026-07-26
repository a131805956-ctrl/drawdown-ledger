from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from drawdown_lab.api.app import Settings, create_app
from drawdown_lab.data.update import DataUpdateError
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
        "/api/v1/reports/export",
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
    assert health.json()["status"] == "incomplete"
    assert overview.json()["schema_version"] == "1.0"


def test_hidden_prototype_is_healthy_but_not_user_selectable(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        instruments = client.get("/api/v1/instruments").json()["instruments"]
        coverage = client.get("/api/v1/data/health").json()["coverage"]

    instruments_by_symbol = {row["symbol"]: row for row in instruments}
    instrument_symbols = set(instruments_by_symbol)
    coverage_by_symbol = {row["symbol"]: row for row in coverage}
    assert len(instrument_symbols) == 16
    assert "^TWII" not in instrument_symbols
    assert coverage_by_symbol["^TWII"]["roles"] == ["prototype"]
    assert coverage_by_symbol["^NDX"]["roles"] == ["prototype"]
    assert coverage_by_symbol["QQQ"]["roles"] == [
        "tradable",
        "prototype_proxy",
    ]
    assert coverage_by_symbol["006204.TW"]["roles"] == [
        "tradable",
        "prototype_proxy",
    ]
    assert instruments_by_symbol["TQQQ"]["prototype_symbol"] == "^NDX"


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
        "failures": [],
        "message": "No market-data provider is configured.",
    }


class StubUpdateCoordinator:
    def __init__(self, result: object | Exception) -> None:
        self.result = result

    def ensure_current(self, as_of: date) -> object:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_data_update_returns_typed_partial_summary(tmp_path: Path) -> None:
    coordinator = StubUpdateCoordinator(
        SimpleNamespace(
            status="partial",
            cutoff=date(2026, 7, 31),
            request_count=3,
            refreshed_symbols=("QQQ", "DIA"),
            failures=(
                SimpleNamespace(symbol="SPY", message="rate limited"),
            ),
        )
    )
    with TestClient(
        create_app(
            Settings(
                database_path=tmp_path / "drawdown.sqlite",
                data_root=tmp_path / "data",
                update_coordinator=coordinator,  # type: ignore[arg-type]
            )
        )
    ) as client:
        response = client.post(
            "/api/v1/data/update",
            json={"schema_version": "1.0", "as_of": "2026-08-01"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1.0",
        "status": "partial",
        "cutoff": "2026-07-31",
        "request_count": 3,
        "refreshed_symbols": ["QQQ", "DIA"],
        "failures": [{"symbol": "SPY", "message": "rate limited"}],
        "message": None,
    }


def test_data_update_converts_batch_error_to_typed_failed_response(
    tmp_path: Path,
) -> None:
    coordinator = StubUpdateCoordinator(DataUpdateError("provider unavailable"))
    with TestClient(
        create_app(
            Settings(
                database_path=tmp_path / "drawdown.sqlite",
                data_root=tmp_path / "data",
                update_coordinator=coordinator,  # type: ignore[arg-type]
            )
        )
    ) as client:
        response = client.post(
            "/api/v1/data/update",
            json={"schema_version": "1.0", "as_of": "2026-08-01"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["cutoff"] == "2026-07-31"
    assert response.json()["failures"] == [
        {"symbol": "__batch__", "message": "provider unavailable"}
    ]


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
