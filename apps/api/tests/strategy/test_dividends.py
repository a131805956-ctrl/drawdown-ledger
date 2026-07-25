from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from drawdown_lab.analysis.strategy import DividendPolicy, StrategyConfig, simulate_strategy
from drawdown_lab.data.models import MarketFrame, validate_market_frame


def _action_frame(
    *,
    opens: list[float],
    dividends: list[float],
    splits: list[float] | None = None,
    adjusted: list[float] | None = None,
) -> MarketFrame:
    index = pd.date_range("2020-01-01", periods=len(opens), freq="B")
    split_values = splits or [1.0] * len(opens)
    adjusted_values = adjusted or opens
    return MarketFrame(
        pd.DataFrame(
            {
                "raw_open": opens,
                "raw_high": opens,
                "raw_low": opens,
                "raw_close": opens,
                "price_open": adjusted_values,
                "price_high": adjusted_values,
                "price_low": adjusted_values,
                "price_close": adjusted_values,
                "adj_close": adjusted_values,
                "dividend_raw": dividends,
                "split_ratio": split_values,
            },
            index=index,
        )
    )


@pytest.mark.parametrize(
    ("policy", "expected_cash", "expected_shares"),
    [
        (DividendPolicy.CASH, Decimal("1020.00"), Decimal("10")),
        (DividendPolicy.REINVEST, Decimal("1000.00"), Decimal("12")),
    ],
)
def test_dividend_routes_once(
    policy: DividendPolicy,
    expected_cash: Decimal,
    expected_shares: Decimal,
) -> None:
    frame = _action_frame(opens=[10, 10], dividends=[2, 0])
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal("1000"),
        initial_shares=Decimal("10"),
        tiers=(),
        dividend_policy=policy,
    )

    result = simulate_strategy(config, frame, frame)

    assert result.cash == expected_cash
    assert result.shares == expected_shares
    assert result.dividend_income == Decimal("20.00")


def test_reinvestment_uses_raw_open_and_never_adjusted_close_again() -> None:
    frame = _action_frame(
        opens=[10, 10],
        dividends=[2, 0],
        adjusted=[5, 5],
    )
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal("1000"),
        initial_shares=Decimal("10"),
        tiers=(),
        dividend_policy="reinvest",
    )

    result = simulate_strategy(config, frame, frame)

    assert result.shares == Decimal("12")
    assert result.cash == Decimal("1000.00")


def test_split_adjusts_raw_shares_exactly_once() -> None:
    frame = _action_frame(
        opens=[10, 5, 5],
        dividends=[0, 0, 0],
        splits=[1, 2, 1],
        adjusted=[5, 5, 5],
    )
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal("0"),
        initial_shares=Decimal("10"),
        tiers=(),
    )

    result = simulate_strategy(config, frame, frame)

    assert result.shares == Decimal("20")
    assert result.equity_curve[-1].value == Decimal("100.00")


def test_reinvestment_waits_through_invalid_raw_open() -> None:
    frame = _action_frame(opens=[10, 0, 5], dividends=[2, 0, 0])
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal("0"),
        initial_shares=Decimal("10"),
        tiers=(),
        dividend_policy="reinvest",
    )

    result = simulate_strategy(config, frame, frame)

    assert result.shares == Decimal("14")
    assert result.cash == Decimal("0.00")


def test_negative_raw_dividend_is_rejected_before_strategy_accounting() -> None:
    frame = _action_frame(opens=[10, 10], dividends=[-0.01, 0])

    with pytest.raises(ValueError, match="dividend_raw"):
        validate_market_frame(frame)
