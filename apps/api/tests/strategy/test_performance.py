from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from drawdown_lab.analysis.baselines import build_baselines
from drawdown_lab.analysis.cashflows import CashFlow
from drawdown_lab.analysis.performance import (
    expected_shortfall_5,
    longest_underwater_days,
    max_drawdown,
    time_weighted_return,
    xirr,
)
from drawdown_lab.analysis.strategy import StrategyConfig, ThresholdTier, simulate_strategy
from drawdown_lab.data.models import MarketFrame


def _frame(closes: list[float], opens: list[float] | None = None) -> MarketFrame:
    index = pd.date_range("2020-01-01", periods=len(closes), freq="B")
    raw_open = opens or closes
    return MarketFrame(
        pd.DataFrame(
            {
                "raw_open": raw_open,
                "raw_high": closes,
                "raw_low": closes,
                "raw_close": closes,
                "price_open": closes,
                "price_high": closes,
                "price_low": closes,
                "price_close": closes,
                "adj_close": closes,
                "dividend_raw": 0.0,
                "split_ratio": 1.0,
            },
            index=index,
        )
    )


def test_xirr_uses_actual_day_dates() -> None:
    result = xirr(
        (
            CashFlow(date(2020, 1, 1), Decimal("-1000")),
            CashFlow(date(2021, 1, 1), Decimal("1100")),
        )
    )

    assert result == pytest.approx(0.0997136, abs=1e-6)


def test_xirr_requires_both_cashflow_signs() -> None:
    with pytest.raises(ValueError, match="positive and negative"):
        xirr((CashFlow(date(2020, 1, 1), Decimal("-1000")),))


def test_initial_shares_are_included_in_opening_xirr_market_value() -> None:
    frame = _frame([100, 110])
    frame.data.index = pd.DatetimeIndex(["2020-01-01", "2021-01-01"])
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal("0"),
        initial_shares=Decimal("10"),
        tiers=(),
    )

    result = simulate_strategy(config, frame, frame)

    assert result.external_cashflows[0] == CashFlow(
        date(2020, 1, 1),
        Decimal("-1000.00"),
    )
    assert result.metrics.xirr == pytest.approx(0.0997136, abs=1e-6)


def test_time_weighted_return_removes_external_cashflows() -> None:
    values = [Decimal("100"), Decimal("210"), Decimal("231")]
    external_flows = [Decimal("0"), Decimal("100"), Decimal("0")]

    assert time_weighted_return(values, external_flows) == pytest.approx(0.21)


def test_path_risk_metrics_use_peak_relative_values_and_actual_dates() -> None:
    values = [100.0, 80.0, 120.0, 90.0]
    dates = [
        date(2020, 1, 1),
        date(2020, 1, 2),
        date(2020, 1, 4),
        date(2020, 1, 10),
    ]

    assert max_drawdown(values) == pytest.approx(0.25)
    assert expected_shortfall_5([0.10, -0.20, 0.05, -0.10]) == pytest.approx(-0.20)
    assert longest_underwater_days(values, dates) == 6


def test_underwater_recovery_equality_records_full_calendar_interval() -> None:
    assert longest_underwater_days(
        [100.0, 80.0, 100.0],
        [date(2020, 1, 1), date(2020, 1, 10), date(2020, 1, 20)],
    ) == 19


def test_result_reports_cash_depletion_and_deepest_missed_tier() -> None:
    frame = _frame([100, 65, 60])
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal("1000"),
        tiers=(
            ThresholdTier(Decimal("0.20"), Decimal("1")),
            ThresholdTier(Decimal("0.30"), Decimal("1")),
        ),
    )

    result = simulate_strategy(config, frame, frame)

    assert result.metrics.cash_depletion_date == date(2020, 1, 3)
    assert result.metrics.deepest_tier_missed == Decimal("0.30")
    assert result.metrics.es5 == result.metrics.expected_shortfall_5
    assert result.metrics.underwater_duration == result.metrics.longest_underwater_days


def test_fee_and_slippage_stay_inside_tier_cash_allocation() -> None:
    frame = _frame([100, 79, 50])
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal("1000"),
        tiers=(ThresholdTier(Decimal("0.20"), Decimal("1")),),
        fixed_fee=Decimal("10"),
        slippage=Decimal("0.02"),
    )

    result = simulate_strategy(config, frame, frame)

    assert result.cash == Decimal("0.00")
    assert result.total_fees == Decimal("10.00")
    assert result.trades[0].execution_price == Decimal("51.00")
    assert result.shares == pytest.approx(Decimal("990") / Decimal("51"))


def test_build_baselines_returns_four_named_comparable_results() -> None:
    frame = _frame([100, 90, 80, 110])
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal("1200"),
        tiers=(ThresholdTier(Decimal("0.20"), Decimal("0.50")),),
    )

    results = build_baselines(config, frame, frame)

    assert tuple(result.name for result in results) == (
        "DCA",
        "cash",
        "simple-threshold",
        "buy-and-hold",
    )
    assert all(result.metrics is not None for result in results)


def test_baselines_apply_distinct_cash_dca_threshold_and_lump_sum_rules() -> None:
    dates = pd.DatetimeIndex(["2020-01-02", "2020-02-03", "2020-03-02"])
    frame = _frame([100, 79, 50], opens=[10, 20, 50])
    frame.data.index = dates
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal("1200"),
        tiers=(ThresholdTier(Decimal("0.20"), Decimal("0.50")),),
    )

    dca, cash, simple, buy_and_hold = build_baselines(config, frame, frame)

    assert (dca.cash, dca.shares) == (Decimal("900.00"), Decimal("17"))
    assert (cash.cash, cash.shares) == (Decimal("1200.00"), Decimal("0"))
    assert (simple.cash, simple.shares) == (Decimal("0.00"), Decimal("24"))
    assert (buy_and_hold.cash, buy_and_hold.shares) == (Decimal("0.00"), Decimal("120"))
