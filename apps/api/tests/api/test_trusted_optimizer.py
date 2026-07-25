from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
from drawdown_lab.api.app import Settings, create_app
from drawdown_lab.data.catalog import DataCatalog
from drawdown_lab.data.models import MarketFrame
from fastapi.testclient import TestClient

from apps.api.tests.optimization.test_evaluator import PROTOTYPE_PRICES, RISING_TARGET


def _frame(prices: tuple[float, ...]) -> MarketFrame:
    index = pd.bdate_range("2020-01-01", periods=len(prices))
    values = pd.Series(prices, index=index, dtype=float)
    return MarketFrame(
        pd.DataFrame(
            {
                "raw_open": values,
                "raw_high": values,
                "raw_low": values,
                "raw_close": values,
                "price_open": values,
                "price_high": values,
                "price_low": values,
                "price_close": values,
                "adj_close": values,
                "dividend_raw": 0.0,
                "split_ratio": 1.0,
            },
            index=index,
        )
    )


def _seed(data_root: Path, *, include_target: bool = True) -> None:
    catalog = DataCatalog(data_root)
    catalog.store("QQQ", _frame(PROTOTYPE_PRICES))
    if include_target:
        catalog.store("TQQQ", _frame(RISING_TARGET))


def _request() -> dict[str, object]:
    broad = {
        "worst_5_floor": -1.0,
        "max_early_depletion_rate": 1.0,
        "max_longest_trap_days": 10000,
    }
    return {
        "schema_version": "1.0",
        "family_id": "nasdaq-100",
        "target_symbol": "TQQQ",
        "strategy": {
            "start": "2020-01-01",
            "end": "2020-02-03",
            "initial_cash": "1000",
        },
        "depths": ["0.20"],
        "ratio_search": {
            "minimum_basis_points": 0,
            "maximum_basis_points": 10000,
            "step_basis_points": 10000,
            "monotone": True,
        },
        "walk_forward": {"n_splits": 2, "test_size_sessions": 8},
        "minimum_independent_episodes": 1,
        "isolated_peak_penalty": 0.0,
        "conservative": broad,
        "balanced": broad,
        "aggressive": broad,
        "synthetic_stress": {"enabled": False},
    }


def _wait(client: TestClient, job_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        row = client.get(f"/api/v1/jobs/{job_id}").json()
        if row["status"] in {"succeeded", "failed", "cancelled"}:
            return row
        time.sleep(0.005)
    raise AssertionError("optimization did not terminate")


def test_optimizer_uses_trusted_cached_symbols_and_internal_simulations(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    _seed(data_root)
    with TestClient(
        create_app(
            Settings(
                database_path=tmp_path / "drawdown.sqlite",
                data_root=data_root,
                job_batch_size=1,
            )
        )
    ) as client:
        accepted = client.post("/api/v1/optimizations", json=_request())
        assert accepted.status_code == 202
        job = _wait(client, accepted.json()["job_id"])
        result = client.get(f"/api/v1/results/{job['result_id']}").json()

    assert job["status"] == "succeeded"
    assert job["progress"] == 4
    assert job["total"] == 4
    assert result["payload"]["independent_episode_count"] == 2
    assert next(
        row["ratios"]
        for row in result["payload"]["recommendations"]
        if row["profile"] == "balanced"
    ) == [10000]


def test_optimizer_rejects_fabricated_candidate_scores_and_counts(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _seed(data_root)
    payload = _request()
    payload["candidates"] = [
        {
            "ratios": [10000],
            "fold_oos_xirr": [99.0],
            "worst_5_return": 99.0,
            "early_depletion_rate": 0.0,
            "longest_trap_days": 0,
        }
    ]
    payload["independent_episode_count"] = 999

    with TestClient(
        create_app(Settings(database_path=tmp_path / "db.sqlite", data_root=data_root))
    ) as client:
        response = client.post("/api/v1/optimizations", json=payload)

    assert response.status_code == 422
    assert response.json()["schema_version"] == "1.0"


def test_optimizer_rejects_family_symbol_mismatch_with_typed_error(tmp_path: Path) -> None:
    payload = _request()
    payload["target_symbol"] = "UPRO"

    with TestClient(
        create_app(Settings(database_path=tmp_path / "db.sqlite", data_root=tmp_path / "data"))
    ) as client:
        response = client.post("/api/v1/optimizations", json=payload)

    assert response.status_code == 422
    assert response.json()["schema_version"] == "1.0"
    assert "family" in response.json()["detail"].lower()


def test_optimizer_reports_missing_trusted_cache_as_typed_404(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    _seed(data_root, include_target=False)

    with TestClient(
        create_app(Settings(database_path=tmp_path / "db.sqlite", data_root=data_root))
    ) as client:
        response = client.post("/api/v1/optimizations", json=_request())

    assert response.status_code == 404
    assert response.json()["schema_version"] == "1.0"
    assert "TQQQ" in response.json()["detail"]
