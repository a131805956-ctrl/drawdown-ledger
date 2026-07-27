from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from drawdown_lab.analysis.leverage import synthetic_daily_reset_nav
from drawdown_lab.api.app import Settings, create_app
from drawdown_lab.data.catalog import DataCatalog
from drawdown_lab.data.models import MarketFrame
from fastapi.testclient import TestClient

from apps.api.tests.api.test_trusted_optimizer import _seed


def _client(tmp_path: Path, *, target_start_offset: int = 0) -> TestClient:
    data_root = tmp_path / "data"
    _seed(data_root)
    if target_start_offset:
        catalog = DataCatalog(data_root)
        target = catalog.read("TQQQ")
        assert target is not None
        catalog.store(
            "TQQQ",
            MarketFrame(target.data.iloc[target_start_offset:].copy()),
        )
    return TestClient(
        create_app(
            Settings(
                database_path=tmp_path / "drawdown.sqlite",
                data_root=data_root,
            )
        )
    )


def test_market_series_keeps_actual_prices_and_synthetic_index_separate(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, target_start_offset=10) as client:
        response = client.get(
            "/api/v1/market/series",
            params={
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "history_mode": "prototype_earliest",
                "include_synthetic": "true",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "1.0"
    assert payload["family_id"] == "nasdaq-100"
    assert payload["prototype"]["symbol"] == "QQQ"
    assert payload["prototype"]["source_kind"] == "actual"
    assert payload["prototype"]["unit"] == "price"
    assert payload["actual"]["symbol"] == "TQQQ"
    assert payload["actual"]["source_kind"] == "actual"
    assert payload["actual"]["unit"] == "price"
    assert payload["synthetic"]["source_kind"] == "synthetic"
    assert payload["synthetic"]["unit"] == "index"
    assert payload["synthetic"]["leverage"] == 3.0
    assert payload["synthetic"]["points"][0]["close"] > 0
    assert payload["model_assumptions"]["join_scale"] > 0
    assert payload["handoff_session"] == payload["actual"]["points"][0]["session"]
    assert payload["synthetic"]["points"][-1]["session"] < payload["handoff_session"]
    assert {
        point["session"] for point in payload["synthetic"]["points"]
    }.isdisjoint(point["session"] for point in payload["actual"]["points"])
    assert payload["prototype"]["points"][9]["drawdown"] < -0.20
    assert payload["prototype"]["policy_cutoff"] == "2020-02-03"
    assert payload["actual"]["actual_last_session"] == "2020-02-03"


def test_market_series_exposes_joined_daily_rebalance_model_and_history_mode(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, target_start_offset=10) as client:
        response = client.get(
            "/api/v1/market/series",
            params={
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "history_mode": "prototype_earliest",
                "include_synthetic": "true",
                "annual_management_fee": "0.01",
                "daily_financing_drag": "0.0001",
                "daily_roll_drag": "0.0002",
                "daily_transaction_drag": "0.0003",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["history_mode"] == "prototype_earliest"
    assert payload["history_start"] == "2020-01-01"
    assert payload["join_session"] == payload["actual"]["points"][0]["session"]
    assumptions = payload["model_assumptions"]
    assert assumptions["method"] == "daily_rebalance"
    assert assumptions["annual_management_fee"] == 0.01
    assert assumptions["daily_financing_drag"] == 0.0001
    assert assumptions["daily_roll_drag"] == 0.0002
    assert assumptions["daily_transaction_drag"] == 0.0003
    synthetic = payload["synthetic"]["points"]
    actual = payload["actual"]["points"]
    assert synthetic[-1]["session"] < payload["join_session"]
    assert assumptions["join_scale"] > 0
    assert synthetic[-1]["close"] > 0
    assert actual[0]["close"] > 0


def test_market_series_defaults_to_target_etf_inception(tmp_path: Path) -> None:
    with _client(tmp_path, target_start_offset=10) as client:
        response = client.get(
            "/api/v1/market/series",
            params={
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "include_synthetic": "true",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["history_mode"] == "target_inception"
    assert payload["history_start"] == payload["join_session"]
    assert payload["actual"]["points"][0]["session"] == payload["join_session"]
    assert payload["synthetic"]["points"] == []


def test_market_series_uses_nonzero_product_cost_defaults_for_leverage(
    tmp_path: Path,
) -> None:
    with _client(tmp_path, target_start_offset=10) as client:
        response = client.get(
            "/api/v1/market/series",
            params={
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "history_mode": "prototype_earliest",
                "include_synthetic": "true",
            },
        )

    assert response.status_code == 200
    assumptions = response.json()["model_assumptions"]
    assert assumptions["annual_management_fee"] > 0
    assert assumptions["daily_financing_drag"] > 0
    assert assumptions["daily_roll_drag"] > 0
    assert assumptions["daily_transaction_drag"] > 0


def test_market_series_scaled_synthetic_bridge_matches_actual_join_return(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _seed(data_root)
    catalog = DataCatalog(data_root)
    target = catalog.read("TQQQ")
    assert target is not None
    catalog.store("TQQQ", MarketFrame(target.data.iloc[10:].copy()))
    with TestClient(
        create_app(
            Settings(
                database_path=tmp_path / "drawdown.sqlite",
                data_root=data_root,
            )
        )
    ) as client:
        response = client.get(
            "/api/v1/market/series",
            params={
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "history_mode": "prototype_earliest",
                "include_synthetic": "true",
                "annual_management_fee": "0.01",
                "daily_financing_drag": "0.0001",
                "daily_roll_drag": "0.0002",
                "daily_transaction_drag": "0.0003",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    prototype = catalog.read("QQQ")
    assert prototype is not None
    model = synthetic_daily_reset_nav(
        prototype,
        3.0,
        annual_management_fee=0.01,
        daily_financing_drag=0.0001,
        daily_roll_drag=0.0002,
        daily_transaction_drag=0.0003,
    )
    actual_points = payload["actual"]["points"]
    synthetic_points = payload["synthetic"]["points"]
    assert synthetic_points[-1]["session"] == "2020-01-14"
    assert actual_points[0]["session"] == "2020-01-15"
    expected_join_ratio = float(model.nav.iloc[10] / model.nav.iloc[9])
    observed_join_ratio = float(
        actual_points[0]["close"] / synthetic_points[-1]["close"]
    )
    assert observed_join_ratio == pytest.approx(expected_join_ratio)


def test_market_series_filters_dates_and_rejects_family_mismatch(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        filtered = client.get(
            "/api/v1/market/series",
            params={
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "start": "2020-01-13",
                "end": "2020-01-15",
            },
        )
        mismatch = client.get(
            "/api/v1/market/series",
            params={
                "family_id": "nasdaq-100",
                "target_symbol": "UPRO",
            },
        )
        reversed_range = client.get(
            "/api/v1/market/series",
            params={
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "start": "2020-01-15",
                "end": "2020-01-13",
            },
        )

    assert filtered.status_code == 200
    assert [row["session"] for row in filtered.json()["prototype"]["points"]] == [
        "2020-01-13",
        "2020-01-14",
        "2020-01-15",
    ]
    assert filtered.json()["synthetic"] is None
    assert mismatch.status_code == 422
    assert mismatch.json()["schema_version"] == "1.0"
    assert reversed_range.status_code == 422
    assert reversed_range.json()["schema_version"] == "1.0"


def test_market_series_rejects_excessive_date_ranges_and_point_counts(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        wide_range = client.get(
            "/api/v1/market/series",
            params={
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "start": "1960-01-01",
                "end": "2020-02-03",
            },
        )
        too_many_points = client.get(
            "/api/v1/market/series",
            params={
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "max_points": 5,
            },
        )

    assert wide_range.status_code == 422
    assert wide_range.json()["schema_version"] == "1.0"
    assert "range" in wide_range.json()["detail"].lower()
    assert too_many_points.status_code == 422
    assert too_many_points.json()["schema_version"] == "1.0"
    assert "points" in too_many_points.json()["detail"].lower()


def test_evidence_rejects_excessive_horizon_payloads(tmp_path: Path) -> None:
    def request(horizons: list[int]) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "family_id": "nasdaq-100",
            "target_symbol": "TQQQ",
            "threshold": 0.20,
            "horizons": horizons,
        }

    with _client(tmp_path) as client:
        too_many = client.post(
            "/api/v1/evidence/analyze",
            json=request(list(range(1, 18))),
        )
        too_long = client.post(
            "/api/v1/evidence/analyze",
            json=request([2521]),
        )

    assert too_many.status_code == 422
    assert too_many.json()["schema_version"] == "1.0"
    assert too_long.status_code == 422
    assert too_long.json()["schema_version"] == "1.0"


def test_evidence_response_exposes_independent_episode_trace(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/v1/evidence/analyze",
            json={
                "schema_version": "1.0",
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "threshold": 0.20,
                "horizons": [1, 5],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["family_id"] == "nasdaq-100"
    assert payload["prototype_symbol"] == "QQQ"
    assert payload["target_symbol"] == "TQQQ"
    assert payload["source_label"] == "trusted_local_cache"
    assert payload["source_kind"] == "actual"
    assert payload["prototype_actual_last_session"] == "2020-02-03"
    assert payload["prototype_policy_cutoff"] == "2020-02-03"
    assert payload["target_actual_last_session"] == "2020-02-03"
    assert payload["target_policy_cutoff"] == "2020-02-03"
    assert len(payload["episodes"]) == payload["n_episode"] == 2
    first = payload["episodes"][0]
    assert first["peak_date"] == "2020-01-13"
    assert first["signal_date"] == "2020-01-14"
    assert first["entry_date"] == "2020-01-15"
    assert first["entry_date"] > first["signal_date"]
    assert first["signal_drawdown"] < -0.20
    assert first["forward_returns"][0]["horizon_sessions"] == 1
    assert {"mae", "mfe", "recovery_date", "recovery_sessions", "v_recovered"} <= set(first)


def test_strategy_response_exposes_cash_curve_and_buy_markers(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/v1/strategies/backtest",
            json={
                "schema_version": "1.0",
                "family_id": "nasdaq-100",
                "target_symbol": "TQQQ",
                "start": "2020-01-01",
                "end": "2020-02-03",
                "initial_cash": "1000",
                "monthly_contribution": "100",
                "tiers": [{"depth": "0.20", "cash_fraction": "0.50"}],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["family_id"] == "nasdaq-100"
    assert payload["prototype_symbol"] == "QQQ"
    assert payload["target_symbol"] == "TQQQ"
    assert payload["source_label"] == "trusted_local_cache"
    assert payload["source_kind"] == "actual"
    assert payload["prototype_actual_last_session"] == "2020-02-03"
    assert payload["prototype_policy_cutoff"] == "2020-02-03"
    assert payload["target_actual_last_session"] == "2020-02-03"
    assert payload["target_policy_cutoff"] == "2020-02-03"
    assert len(payload["trades"]) == payload["trade_count"] == 2
    first_trade = payload["trades"][0]
    assert first_trade["kind"] == "buy"
    assert first_trade["signal_date"] < first_trade["date"]
    assert first_trade["threshold"] == "0.20"
    assert Decimal(first_trade["prototype_drawdown"]) < Decimal("-0.20")
    assert Decimal(first_trade["target_drawdown"]) < Decimal("0")
    assert first_trade["post_trade_cash"] == "550.00"
    assert first_trade["marker_profit_loss"] == "0.00"
    assert len(payload["equity_curve"]) == 24
    assert {"date", "cash", "shares", "close", "value", "external_flow"} <= set(
        payload["equity_curve"][0]
    )
    assert {"net_contributions", "profit_loss"} <= set(payload["equity_curve"][-1])
    assert payload["contribution_total"] == "200.00"
    assert payload["dividend_income"] == "0.00"
    assert payload["total_fees"] == "0.00"


def test_openapi_documents_chart_trace_models(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        schema = client.get("/openapi.json").json()

    market_response = schema["paths"]["/api/v1/market/series"]["get"]["responses"]["200"]
    assert market_response["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MarketSeriesResponse"
    )
    assert schema["components"]["schemas"]["MarketSeriesResponse"]["additionalProperties"] is False
    assert schema["components"]["schemas"]["TradeResponse"]["additionalProperties"] is False
    assert set(
        schema["components"]["schemas"]["TradeResponse"]["properties"]["kind"]["enum"]
    ) == {"buy", "reinvest", "dca", "buy-and-hold"}
