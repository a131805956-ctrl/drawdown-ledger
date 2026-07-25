from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from drawdown_lab.api.app import Settings, create_app
from fastapi.testclient import TestClient


def _bars(prices: tuple[float, ...]) -> list[dict[str, object]]:
    start = date(2020, 1, 1)
    return [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "raw_open": price,
            "raw_high": price,
            "raw_low": price,
            "raw_close": price,
            "price_open": price,
            "price_high": price,
            "price_low": price,
            "price_close": price,
            "adj_close": price,
            "dividend_raw": 0.0,
            "split_ratio": 1.0,
        }
        for index, price in enumerate(prices)
    ]


def test_fixed_market_fixture_drives_evidence_and_strategy_routes(tmp_path: Path) -> None:
    prototype = {"bars": _bars((100.0, 85.0, 90.0, 101.0))}
    traded = {"bars": _bars((10.0, 9.0, 9.5, 11.0))}
    with TestClient(create_app(Settings(database_path=tmp_path / "drawdown.sqlite"))) as client:
        evidence = client.post(
            "/api/v1/evidence/analyze",
            json={
                "schema_version": "1.0",
                "threshold": 0.10,
                "horizons": [1],
                "prototype": prototype,
                "traded": traded,
            },
        )
        strategy = client.post(
            "/api/v1/strategies/backtest",
            json={
                "schema_version": "1.0",
                "start": "2020-01-01",
                "end": "2020-01-04",
                "initial_cash": "1000",
                "tiers": [{"depth": "0.10", "cash_fraction": "0.50"}],
                "prototype": prototype,
                "traded": traded,
            },
        )

    assert evidence.status_code == 200
    assert evidence.json()["n_episode"] == 1
    assert evidence.json()["n_executed_episode"] == 1
    assert strategy.status_code == 200
    assert strategy.json()["trade_count"] == 1
    assert strategy.json()["schema_version"] == "1.0"
