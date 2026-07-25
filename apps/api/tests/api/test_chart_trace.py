from __future__ import annotations

from pathlib import Path

from drawdown_lab.api.app import Settings, create_app
from fastapi.testclient import TestClient

from apps.api.tests.api.test_trusted_optimizer import _seed


def _client(tmp_path: Path) -> TestClient:
    data_root = tmp_path / "data"
    _seed(data_root)
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
    with _client(tmp_path) as client:
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
    assert payload["schema_version"] == "1.0"
    assert payload["family_id"] == "nasdaq-100"
    assert payload["prototype"]["symbol"] == "QQQ"
    assert payload["prototype"]["source_kind"] == "actual"
    assert payload["prototype"]["unit"] == "price"
    assert payload["actual"]["symbol"] == "TQQQ"
    assert payload["actual"]["source_kind"] == "actual"
    assert payload["actual"]["unit"] == "price"
    assert payload["actual"]["points"][0]["close"] == 100.0
    assert payload["synthetic"]["source_kind"] == "synthetic"
    assert payload["synthetic"]["unit"] == "index"
    assert payload["synthetic"]["leverage"] == 3.0
    assert payload["synthetic"]["points"][0]["close"] == 100.0
    assert payload["synthetic"]["points"][9]["close"] != payload["actual"]["points"][9]["close"]
    assert payload["prototype"]["points"][9]["drawdown"] < -0.20
    assert payload["prototype"]["policy_cutoff"] == "2020-02-03"
    assert payload["actual"]["actual_last_session"] == "2020-02-03"


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
    assert len(payload["trades"]) == payload["trade_count"] == 2
    assert payload["trades"][0]["kind"] == "buy"
    assert payload["trades"][0]["signal_date"] < payload["trades"][0]["date"]
    assert payload["trades"][0]["threshold"] == "0.20"
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
