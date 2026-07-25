from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from drawdown_lab.analysis.cashflows import ContributionEvent
from drawdown_lab.api.app import Settings, create_app
from drawdown_lab.api.schemas import OptimizationCreateRequest
from drawdown_lab.optimization.evaluator import (
    _strategy_config,
    historical_request_from_payload,
    historical_request_to_payload,
)
from fastapi.testclient import TestClient

from apps.api.tests.api.test_trusted_optimizer import _request, _seed


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


def _strategy_payload(events: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "family_id": "nasdaq-100",
        "target_symbol": "TQQQ",
        "start": "2020-01-01",
        "end": "2020-02-03",
        "initial_cash": "1000",
        "monthly_contribution": "100",
        "contribution_day": 1,
        "contribution_events": events,
        "tiers": [{"depth": "0.90", "cash_fraction": "0.50"}],
    }


def test_backtest_accepts_override_and_bonus_events_by_effective_month(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/v1/strategies/backtest",
            json=_strategy_payload(
                [
                    {"month": "2020-01-20", "kind": "bonus", "amount": "50"},
                    {"month": "2020-02-15", "kind": "override", "amount": "200"},
                ]
            ),
        )

    assert response.status_code == 200
    assert response.json()["trade_count"] == 0
    assert response.json()["ending_cash"] == "1350.00"


def test_backtest_pause_suppresses_month_until_resume(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/v1/strategies/backtest",
            json=_strategy_payload(
                [
                    {"month": "2020-02-01", "kind": "pause"},
                    {"month": "2020-03-01", "kind": "resume"},
                ]
            ),
        )

    assert response.status_code == 200
    assert response.json()["ending_cash"] == "1100.00"


@pytest.mark.parametrize(
    "event",
    [
        {"month": "2020-02-01", "kind": "pause", "amount": "1"},
        {"month": "2020-02-01", "kind": "resume", "amount": "1"},
        {"month": "2020-02-01", "kind": "bonus", "amount": "-1"},
    ],
)
def test_event_contract_rejects_invalid_amount_semantics(
    tmp_path: Path,
    event: dict[str, object],
) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/v1/strategies/backtest",
            json=_strategy_payload([event]),
        )

    assert response.status_code == 422
    assert response.json()["schema_version"] == "1.0"


def test_optimizer_events_round_trip_through_persisted_request() -> None:
    payload = _request()
    strategy = dict(payload["strategy"])
    strategy["contribution_events"] = [
        {"month": "2020-01-19", "kind": "override", "amount": "250"},
        {"month": "2020-02-01", "kind": "bonus", "amount": "500"},
        {"month": "2020-03-01", "kind": "pause", "amount": "0"},
        {"month": "2020-04-01", "kind": "resume", "amount": "0"},
    ]
    payload["strategy"] = strategy

    request = OptimizationCreateRequest.model_validate(payload).to_domain(
        prototype_symbol="QQQ",
        target_leverage=3,
    )
    stored = historical_request_to_payload(request)
    restored = historical_request_from_payload(stored)

    assert restored.strategy.contribution_events == (
        ContributionEvent(date(2020, 1, 1), "override", Decimal("250.00")),
        ContributionEvent(date(2020, 2, 1), "bonus", Decimal("500.00")),
        ContributionEvent(date(2020, 3, 1), "pause", Decimal("0.00")),
        ContributionEvent(date(2020, 4, 1), "resume", Decimal("0.00")),
    )
    assert historical_request_to_payload(restored) == stored


def test_legacy_optimizer_payload_without_events_remains_replayable() -> None:
    request = OptimizationCreateRequest.model_validate(_request()).to_domain(
        prototype_symbol="QQQ",
        target_leverage=3,
    )
    stored = historical_request_to_payload(request)
    stored["strategy"].pop("contribution_events")

    restored = historical_request_from_payload(stored)

    assert restored.strategy.contribution_events == ()


def test_persisted_optimizer_event_kind_is_revalidated() -> None:
    request = OptimizationCreateRequest.model_validate(_request()).to_domain(
        prototype_symbol="QQQ",
        target_leverage=3,
    )
    stored = historical_request_to_payload(request)
    stored["strategy"]["contribution_events"] = [
        {"month": "2020-02-01", "kind": "unknown", "amount": "0"}
    ]

    with pytest.raises(ValueError, match="Unknown contribution event kind"):
        historical_request_from_payload(stored)


def test_walk_forward_windows_preserve_original_salary_timeline() -> None:
    request = OptimizationCreateRequest.model_validate(_request()).to_domain(
        prototype_symbol="QQQ",
        target_leverage=3,
    )
    template = replace(
        request.strategy,
        start=date(2020, 1, 1),
        end=date(2022, 1, 31),
        monthly_contribution=Decimal("100"),
        annual_contribution_growth=Decimal("0.10"),
        contribution_events=(ContributionEvent(date(2021, 1, 1), "override", Decimal("200")),),
    )
    config = _strategy_config(
        replace(request, strategy=template),
        (10_000,),
        start=date(2022, 1, 1),
        end=date(2022, 1, 31),
        name="fold",
    )

    assert config.contributions is not None
    assert config.contributions.start == date(2020, 1, 1)
    flows = config.contributions.due_cashflows(
        date(2022, 1, 31),
        plan_start=date(2022, 1, 1),
    )
    assert len(flows) == 1
    assert flows[0].date == date(2022, 1, 1)
    assert flows[0].amount == Decimal("242.00")


def test_openapi_exposes_typed_contribution_events(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        schema = client.get("/openapi.json").json()

    event = schema["components"]["schemas"]["ContributionEventInput"]
    assert event["additionalProperties"] is False
    assert set(event["properties"]["kind"]["enum"]) == {
        "bonus",
        "override",
        "pause",
        "resume",
    }
