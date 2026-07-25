from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
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
