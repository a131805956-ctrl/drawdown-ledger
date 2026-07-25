from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from math import ceil

from drawdown_lab.analysis.cashflows import CashFlow


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    xirr: float | None
    twr: float
    max_drawdown: float
    expected_shortfall_5: float
    longest_underwater_days: int
    cash_depletion_date: date | None
    deepest_tier_missed: Decimal | None

    @property
    def es5(self) -> float:
        return self.expected_shortfall_5

    @property
    def underwater_duration(self) -> int:
        return self.longest_underwater_days


def xirr(cashflows: Sequence[CashFlow]) -> float:
    if not cashflows:
        raise ValueError("XIRR requires at least one cash flow")
    amounts = tuple(float(flow.amount) for flow in cashflows)
    if not any(amount > 0 for amount in amounts) or not any(amount < 0 for amount in amounts):
        raise ValueError("XIRR requires both positive and negative cash flows")

    origin = min(flow.date for flow in cashflows)
    years = tuple((flow.date - origin).days / 365.0 for flow in cashflows)

    def npv(rate: float) -> float:
        total = 0.0
        for amount, year in zip(amounts, years, strict=True):
            total += amount / ((1.0 + rate) ** year)
        return total

    low = -0.999999999
    high = 1.0
    low_value = npv(low)
    high_value = npv(high)
    while low_value * high_value > 0.0 and high < 1_000_000.0:
        high *= 2.0
        high_value = npv(high)
    if low_value * high_value > 0.0:
        raise ValueError("XIRR could not bracket a solution")

    for _ in range(200):
        middle = (low + high) / 2.0
        middle_value = npv(middle)
        if abs(middle_value) < 1e-10:
            return middle
        if low_value * middle_value <= 0.0:
            high = middle
        else:
            low = middle
            low_value = middle_value
    return (low + high) / 2.0


def time_weighted_return(
    values: Sequence[Decimal | float],
    external_flows: Sequence[Decimal | float],
) -> float:
    if len(values) != len(external_flows):
        raise ValueError("Values and external flows must have equal length")
    if not values:
        raise ValueError("Time-weighted return requires at least one value")
    compounded = 1.0
    for previous, current, flow in zip(
        values[:-1], values[1:], external_flows[1:], strict=True
    ):
        previous_value = float(previous)
        if previous_value == 0.0:
            continue
        compounded *= (float(current) - float(flow)) / previous_value
    return compounded - 1.0


def max_drawdown(values: Sequence[Decimal | float]) -> float:
    if not values:
        raise ValueError("Max drawdown requires at least one value")
    peak = float(values[0])
    maximum = 0.0
    for value in values:
        numeric = float(value)
        peak = max(peak, numeric)
        if peak > 0.0:
            maximum = max(maximum, 1.0 - numeric / peak)
    return maximum


def expected_shortfall_5(values: Sequence[Decimal | float]) -> float:
    if not values:
        raise ValueError("Expected shortfall requires at least one return")
    tail_size = max(1, ceil(len(values) * 0.05))
    return sum(sorted(float(value) for value in values)[:tail_size]) / tail_size


def longest_underwater_days(
    values: Sequence[Decimal | float],
    dates: Sequence[date],
) -> int:
    if len(values) != len(dates):
        raise ValueError("Values and dates must have equal length")
    if not values:
        return 0
    peak = float(values[0])
    peak_date = dates[0]
    longest = 0
    for value, current_date in zip(values[1:], dates[1:], strict=True):
        numeric = float(value)
        if numeric >= peak:
            peak = numeric
            peak_date = current_date
        else:
            longest = max(longest, (current_date - peak_date).days)
    return longest


def calculate_performance(
    *,
    values: Sequence[Decimal],
    dates: Sequence[date],
    cash_values: Sequence[Decimal],
    external_flows: Sequence[Decimal],
    cashflows: Sequence[CashFlow],
    missed_thresholds: Sequence[Decimal],
) -> PerformanceMetrics:
    returns: list[float] = []
    for previous, current, flow in zip(
        values[:-1], values[1:], external_flows[1:], strict=True
    ):
        if previous:
            returns.append((float(current) - float(flow)) / float(previous) - 1.0)
    depletion = next(
        (current_date for current_date, cash in zip(dates, cash_values, strict=True) if cash <= 0),
        None,
    )
    try:
        money_weighted = xirr(cashflows)
    except ValueError:
        money_weighted = None
    return PerformanceMetrics(
        xirr=money_weighted,
        twr=time_weighted_return(values, external_flows),
        max_drawdown=max_drawdown(values),
        expected_shortfall_5=expected_shortfall_5(returns) if returns else 0.0,
        longest_underwater_days=longest_underwater_days(values, dates),
        cash_depletion_date=depletion,
        deepest_tier_missed=max(missed_thresholds, default=None),
    )
