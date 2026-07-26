from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from drawdown_lab.analysis.cashflows import ContributionEvent, ContributionSchedule
from drawdown_lab.api.app import Settings, create_app
from drawdown_lab.api.schemas import (
    OptimizationCreateRequest,
    StrategyBacktestRequest,
)
from drawdown_lab.optimization.evaluator import (
    _strategy_config,
    historical_request_from_payload,
    historical_request_to_payload,
)
from fastapi.testclient import TestClient

from apps.api.tests.api.test_trusted_optimizer import _request, _seed


def _client(
    tmp_path: Path,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    data_root = tmp_path / "data"
    _seed(data_root)
    return TestClient(
        create_app(
            Settings(
                database_path=tmp_path / "drawdown.sqlite",
                data_root=data_root,
            )
        ),
        raise_server_exceptions=raise_server_exceptions,
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


def test_domain_event_date_is_canonical_before_optimizer_persistence() -> None:
    request = OptimizationCreateRequest.model_validate(_request()).to_domain(
        prototype_symbol="QQQ",
        target_leverage=3,
    )
    request = replace(
        request,
        strategy=replace(
            request.strategy,
            contribution_events=(
                ContributionEvent(date(2020, 1, 19), "bonus", Decimal("50")),
            ),
        ),
    )

    stored = historical_request_to_payload(request)
    restored = historical_request_from_payload(stored)

    assert request.strategy.contribution_events[0].month == date(2020, 1, 1)
    assert stored["strategy"]["contribution_events"][0]["month"] == "2020-01-01"
    assert restored == request
    assert historical_request_to_payload(restored) == stored


def test_same_month_duplicate_control_event_is_rejected_after_canonicalization() -> None:
    with pytest.raises(ValueError, match="Duplicate override event for 2020-01"):
        ContributionSchedule(
            monthly=Decimal("100"),
            start=date(2020, 1, 1),
            events=(
                ContributionEvent(date(2020, 1, 5), "override", Decimal("150")),
                ContributionEvent(date(2020, 1, 20), "override", Decimal("200")),
            ),
        )


def test_same_month_pause_resume_conflict_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="pause and resume events conflict for 2020-02",
    ):
        ContributionSchedule(
            monthly=Decimal("100"),
            start=date(2020, 1, 1),
            events=(
                ContributionEvent(date(2020, 2, 7), "resume"),
                ContributionEvent(date(2020, 2, 20), "pause"),
            ),
        )


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (
            {"month": "2020-01-25", "kind": "override", "amount": "200"},
            (Decimal("200.00"),),
        ),
        (
            {"month": "2020-01-25", "kind": "pause"},
            (),
        ),
    ],
)
def test_start_month_control_event_affects_future_contributions_after_midmonth_start(
    event: dict[str, object],
    expected: tuple[Decimal, ...],
) -> None:
    request = StrategyBacktestRequest.model_validate(
        {
            "schema_version": "1.0",
            "family_id": "nasdaq-100",
            "target_symbol": "TQQQ",
            "start": "2020-01-20",
            "end": "2020-02-01",
            "initial_cash": "0",
            "monthly_contribution": "100",
            "contribution_day": 1,
            "contribution_events": [event],
            "tiers": [{"depth": "0.20", "cash_fraction": "0.50"}],
        }
    )

    schedule = request.to_domain().contributions

    assert schedule is not None
    flows = schedule.due_cashflows(date(2020, 2, 1), plan_start=request.start)
    assert tuple(flow.amount for flow in flows) == expected


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


@pytest.mark.parametrize("kind", ["pause", "resume"])
def test_persisted_pause_resume_amount_semantics_are_revalidated(kind: str) -> None:
    request = OptimizationCreateRequest.model_validate(_request()).to_domain(
        prototype_symbol="QQQ",
        target_leverage=3,
    )
    stored = historical_request_to_payload(request)
    stored["strategy"]["contribution_events"] = [
        {"month": "2020-02-01", "kind": kind, "amount": "0.01"}
    ]

    with pytest.raises(ValueError, match=f"{kind} events cannot include an amount"):
        historical_request_from_payload(stored)


@pytest.mark.parametrize("kind", ["bonus", "override"])
def test_persisted_cash_event_requires_amount(kind: str) -> None:
    request = OptimizationCreateRequest.model_validate(_request()).to_domain(
        prototype_symbol="QQQ",
        target_leverage=3,
    )
    stored = historical_request_to_payload(request)
    stored["strategy"]["contribution_events"] = [
        {"month": "2020-02-01", "kind": kind}
    ]

    with pytest.raises(ValueError, match=f"{kind} events require an amount"):
        historical_request_from_payload(stored)


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("1e1000000"),
        Decimal("1000000000000000000"),
    ],
)
def test_domain_rejects_unsafe_contribution_event_amount(amount: Decimal) -> None:
    with pytest.raises(ValueError, match="safe maximum"):
        ContributionEvent(date(2020, 1, 1), "bonus", amount)


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
    assert event["discriminator"]["propertyName"] == "kind"
    assert set(event["discriminator"]["mapping"]) == {
        "bonus",
        "override",
        "pause",
        "resume",
    }
    assert len(event["oneOf"]) == 4

    components = schema["components"]["schemas"]
    bonus_event = components["BonusContributionEventInput"]
    pause_event = components["PauseContributionEventInput"]
    assert bonus_event["additionalProperties"] is False
    assert set(bonus_event["required"]) == {"month", "kind", "amount"}
    assert "normalized to the first day" in bonus_event["properties"]["month"]["description"]
    assert pause_event["additionalProperties"] is False
    numeric_amount = next(
        option
        for option in pause_event["properties"]["amount"]["anyOf"]
        if option.get("type") == "number"
    )
    assert numeric_amount["minimum"] == 0
    assert numeric_amount["maximum"] == 0


@pytest.mark.parametrize(
    "field",
    [
        "initial_cash",
        "initial_shares",
        "monthly_contribution",
        "annual_contribution_growth",
        "cash_interest_rate",
        "fixed_fee",
    ],
)
def test_backtest_rejects_unsafe_decimal_magnitudes(
    tmp_path: Path,
    field: str,
) -> None:
    payload: dict[str, Any] = _strategy_payload([])
    payload[field] = "1e1000000"

    with _client(tmp_path, raise_server_exceptions=False) as client:
        response = client.post("/api/v1/strategies/backtest", json=payload)

    assert response.status_code == 422
    assert response.json()["schema_version"] == "1.0"


@pytest.mark.parametrize("amount", ["1e1000000", "1000000000000000000"])
def test_event_amount_outside_safe_domain_returns_422_for_both_endpoints(
    tmp_path: Path,
    amount: str,
) -> None:
    backtest = _strategy_payload(
        [{"month": "2020-01-01", "kind": "bonus", "amount": amount}]
    )
    optimization = _request()
    strategy = dict(optimization["strategy"])
    strategy["contribution_events"] = [
        {"month": "2020-01-01", "kind": "bonus", "amount": amount}
    ]
    optimization["strategy"] = strategy

    with _client(tmp_path, raise_server_exceptions=False) as client:
        backtest_response = client.post("/api/v1/strategies/backtest", json=backtest)
        optimization_response = client.post("/api/v1/optimizations", json=optimization)

    assert backtest_response.status_code == 422
    assert optimization_response.status_code == 422
