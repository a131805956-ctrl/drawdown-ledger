from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from drawdown_lab.analysis.cashflows import (
    ContributionEvent,
    ContributionSchedule,
    bonus,
    override,
)
from drawdown_lab.analysis.strategy import StrategyConfig, ThresholdTier, simulate_strategy
from drawdown_lab.data.models import MarketFrame
from drawdown_lab.domain.money import quantize_money
from hypothesis import given, settings
from hypothesis import strategies as st


def _frame(prices: list[int]) -> MarketFrame:
    index = pd.date_range("2020-01-01", periods=len(prices), freq="B")
    return MarketFrame(
        pd.DataFrame(
            {
                "raw_open": prices,
                "raw_high": prices,
                "raw_low": prices,
                "raw_close": prices,
                "price_open": prices,
                "price_high": prices,
                "price_low": prices,
                "price_close": prices,
                "adj_close": prices,
                "dividend_raw": 0.0,
                "split_ratio": 1.0,
            },
            index=index,
        )
    )


@settings(max_examples=80, deadline=None)
@given(
    prices=st.lists(st.integers(min_value=1, max_value=500), min_size=2, max_size=40),
    initial_cash=st.integers(min_value=0, max_value=10_000_000),
)
def test_generated_paths_never_create_negative_cash_or_shares(
    prices: list[int],
    initial_cash: int,
) -> None:
    frame = _frame(prices)
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal(initial_cash),
        tiers=(
            ThresholdTier(Decimal("0.10"), Decimal("0.25")),
            ThresholdTier(Decimal("0.20"), Decimal("0.50")),
            ThresholdTier(Decimal("0.40"), Decimal("1")),
        ),
    )

    result = simulate_strategy(config, frame, frame)

    assert result.cash >= 0
    assert result.shares >= 0
    assert all(point.cash >= 0 and point.shares >= 0 for point in result.equity_curve)


@settings(max_examples=80, deadline=None)
@given(
    prices=st.lists(st.integers(min_value=1, max_value=500), min_size=2, max_size=40),
    initial_cash=st.integers(min_value=0, max_value=10_000_000),
)
def test_zero_cost_generated_paths_preserve_cash_and_share_accounting(
    prices: list[int],
    initial_cash: int,
) -> None:
    frame = _frame(prices)
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal(initial_cash),
        tiers=(
            ThresholdTier(Decimal("0.10"), Decimal("0.25")),
            ThresholdTier(Decimal("0.20"), Decimal("0.50")),
            ThresholdTier(Decimal("0.40"), Decimal("1")),
        ),
    )

    result = simulate_strategy(config, frame, frame)

    spent = sum((trade.cash_spent for trade in result.trades), start=Decimal("0"))
    bought = sum((trade.shares_bought for trade in result.trades), start=Decimal("0"))
    assert result.cash + spent == config.initial_cash
    assert result.shares == bought
    assert all(
        point.value == quantize_money(point.cash + point.shares * point.close)
        for point in result.equity_curve
    )


@settings(max_examples=60, deadline=None)
@given(
    prices=st.lists(st.integers(min_value=1, max_value=500), min_size=2, max_size=24),
    initial_cash=st.integers(min_value=0, max_value=1_000_000),
    monthly=st.integers(min_value=0, max_value=10_000),
    one_time=st.integers(min_value=0, max_value=50_000),
    interest_bps=st.integers(min_value=0, max_value=1_000),
    fixed_fee=st.integers(min_value=0, max_value=100),
    fee_bps=st.integers(min_value=0, max_value=500),
)
def test_generated_events_rates_and_fees_never_make_balances_negative(
    prices: list[int],
    initial_cash: int,
    monthly: int,
    one_time: int,
    interest_bps: int,
    fixed_fee: int,
    fee_bps: int,
) -> None:
    frame = _frame(prices)
    schedule = ContributionSchedule(
        monthly=Decimal(monthly),
        events=(bonus("2020-01", Decimal(one_time)),),
    )
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal(initial_cash),
        tiers=(ThresholdTier(Decimal("0.20"), Decimal("1")),),
        contributions=schedule,
        cash_interest_rate=Decimal(interest_bps) / Decimal("10000"),
        fixed_fee=Decimal(fixed_fee),
        fee_rate=Decimal(fee_bps) / Decimal("10000"),
    )

    result = simulate_strategy(config, frame, frame)

    assert result.cash >= 0
    assert result.shares >= 0
    assert all(point.cash >= 0 and point.shares >= 0 for point in result.equity_curve)


@pytest.mark.parametrize(
    ("monthly", "events"),
    [
        (Decimal("-1"), ()),
        (Decimal("1"), (bonus("2030-01", Decimal("-1")),)),
        (Decimal("1"), (override("2030-01", Decimal("-1")),)),
    ],
)
def test_negative_monthly_set_and_one_time_amounts_are_rejected(
    monthly: Decimal,
    events: tuple[ContributionEvent, ...],
) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ContributionSchedule(monthly=monthly, events=events)


def test_negative_cash_interest_is_rejected() -> None:
    with pytest.raises(ValueError, match="interest"):
        StrategyConfig(
            start=date(2030, 1, 1),
            initial_cash=Decimal("100"),
            tiers=(),
            cash_interest_rate=Decimal("-0.01"),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"initial_cash": Decimal("-1")},
        {"initial_shares": Decimal("-1")},
        {"fixed_fee": Decimal("-1")},
        {"fee_rate": Decimal("-0.01")},
        {"slippage": Decimal("-0.01")},
    ],
)
def test_negative_balances_and_execution_costs_are_rejected(
    overrides: dict[str, Decimal],
) -> None:
    values = {
        "start": date(2030, 1, 1),
        "initial_cash": Decimal("100"),
        "tiers": (),
        **overrides,
    }
    with pytest.raises(ValueError, match="non-negative"):
        StrategyConfig(**values)


@pytest.mark.parametrize(
    ("depth", "fraction"),
    [
        (Decimal("0"), Decimal("0.50")),
        (Decimal("-0.20"), Decimal("0.50")),
        (Decimal("1.01"), Decimal("0.50")),
        (Decimal("0.20"), Decimal("0")),
        (Decimal("0.20"), Decimal("-0.50")),
        (Decimal("0.20"), Decimal("1.01")),
    ],
)
def test_invalid_threshold_depths_and_cash_fractions_are_rejected(
    depth: Decimal,
    fraction: Decimal,
) -> None:
    with pytest.raises(ValueError, match="positive ratio"):
        ThresholdTier(depth, fraction)
