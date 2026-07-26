from __future__ import annotations

from pathlib import Path

from drawdown_lab.api.app import Settings, create_app
from drawdown_lab.data.catalog import DataCatalog
from fastapi.testclient import TestClient

from apps.api.tests.api.test_trusted_optimizer import _frame, _seed
from apps.api.tests.api.test_trusted_optimizer import _request as optimization_request
from apps.api.tests.optimization.test_evaluator import PROTOTYPE_PRICES, RISING_TARGET


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "drawdown.sqlite",
        data_root=tmp_path / "data",
    )


def test_cached_symbols_drive_evidence_and_strategy_routes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert settings.data_root is not None
    _seed(settings.data_root)
    with TestClient(create_app(settings)) as client:
        evidence = client.post(
            "/api/v1/evidence/analyze",
            json={
                "schema_version": "1.0",
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "threshold": 0.20,
                "horizons": [1],
            },
        )
        strategy = client.post(
            "/api/v1/strategies/backtest",
            json={
                "schema_version": "1.0",
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "start": "2020-01-01",
                "end": "2020-02-03",
                "initial_cash": "1000",
                "tiers": [{"depth": "0.20", "cash_fraction": "0.50"}],
            },
        )

    assert evidence.status_code == 200
    assert evidence.json()["n_episode"] == 2
    assert evidence.json()["n_executed_episode"] == 2
    assert strategy.status_code == 200
    assert strategy.json()["trade_count"] == 2
    assert strategy.json()["schema_version"] == "1.0"


def test_taiwan_weighted_routes_use_hidden_twii_prototype(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert settings.data_root is not None
    catalog = DataCatalog(settings.data_root)
    catalog.store("^TWII", _frame(PROTOTYPE_PRICES))
    catalog.store("00685L.TW", _frame(RISING_TARGET))

    with TestClient(create_app(settings)) as client:
        evidence = client.post(
            "/api/v1/evidence/analyze",
            json={
                "schema_version": "1.0",
                "family_id": "taiwan-weighted",
                "target_symbol": "00685L.TW",
                "threshold": 0.20,
                "horizons": [1],
            },
        )

    assert evidence.status_code == 200
    assert evidence.json()["n_episode"] == 2


def test_formal_routes_reject_caller_supplied_market_frames(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert settings.data_root is not None
    _seed(settings.data_root)
    fake_frame = {
        "bars": [
            {
                "date": "2020-01-01",
                "raw_open": 1,
                "raw_high": 1,
                "raw_low": 1,
                "raw_close": 1,
                "price_open": 1,
                "price_high": 1,
                "price_low": 1,
                "price_close": 1,
                "adj_close": 1,
                "dividend_raw": 0,
                "split_ratio": 1,
            }
        ]
    }
    with TestClient(create_app(settings)) as client:
        evidence = client.post(
            "/api/v1/evidence/analyze",
            json={
                "schema_version": "1.0",
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "threshold": 0.20,
                "horizons": [1],
                "prototype": fake_frame,
                "traded": fake_frame,
            },
        )

    assert evidence.status_code == 422
    assert evidence.json()["schema_version"] == "1.0"


def test_invalid_formal_parameters_return_typed_422_not_500(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert settings.data_root is not None
    _seed(settings.data_root)
    invalid_payloads = (
        {
            "schema_version": "1.0",
            "family_id": "nasdaq-100",
            "target_symbol": "TQQQ",
            "start": "2020-02-03",
            "end": "2020-01-01",
            "initial_cash": "1000",
            "tiers": [{"depth": "0.20", "cash_fraction": "0.50"}],
        },
        {
            "schema_version": "1.0",
            "family_id": "nasdaq-100",
            "target_symbol": "TQQQ",
            "start": "2020-01-01",
            "end": "2020-02-03",
            "initial_cash": "1000",
            "fixed_fee": "-1",
            "tiers": [{"depth": "0.20", "cash_fraction": "0.50"}],
        },
        {
            "schema_version": "1.0",
            "family_id": "nasdaq-100",
            "target_symbol": "TQQQ",
            "start": "2020-01-01",
            "end": "2020-02-03",
            "initial_cash": "1000",
            "fee_rate": "1.01",
            "tiers": [{"depth": "0.20", "cash_fraction": "0"}],
        },
    )
    with TestClient(create_app(settings)) as client:
        responses = [
            client.post("/api/v1/strategies/backtest", json=payload)
            for payload in invalid_payloads
        ]
        invalid_evidence = client.post(
            "/api/v1/evidence/analyze",
            json={
                "schema_version": "1.0",
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "threshold": 0,
                "horizons": [0, 1, 1],
            },
        )

    assert all(response.status_code == 422 for response in (*responses, invalid_evidence))
    assert all(
        response.json()["schema_version"] == "1.0"
        for response in (*responses, invalid_evidence)
    )


def test_formal_routes_type_family_mismatch_and_missing_cache(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        mismatch = client.post(
            "/api/v1/evidence/analyze",
            json={
                "schema_version": "1.0",
                "family_id": "nasdaq-100",
                "target_symbol": "UPRO",
                "threshold": 0.20,
                "horizons": [1],
            },
        )
        missing = client.post(
            "/api/v1/strategies/backtest",
            json={
                "schema_version": "1.0",
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "start": "2020-01-01",
                "end": "2020-02-03",
                "initial_cash": "1000",
                "tiers": [{"depth": "0.20", "cash_fraction": "0.50"}],
            },
        )

    assert mismatch.status_code == 422
    assert mismatch.json()["schema_version"] == "1.0"
    assert missing.status_code == 404
    assert missing.json()["schema_version"] == "1.0"


def test_optimizer_schema_rejects_reversed_dates_and_invalid_search(tmp_path: Path) -> None:
    payload = optimization_request()
    strategy = dict(payload["strategy"])
    strategy["start"] = "2020-02-03"
    strategy["end"] = "2020-01-01"
    payload["strategy"] = strategy
    ratio_search = dict(payload["ratio_search"])
    ratio_search["step_basis_points"] = 3000
    payload["ratio_search"] = ratio_search

    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.post("/api/v1/optimizations", json=payload)

    assert response.status_code == 422
    assert response.json()["schema_version"] == "1.0"
