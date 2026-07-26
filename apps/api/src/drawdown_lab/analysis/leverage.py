from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, cast

import pandas as pd

from drawdown_lab.data.models import MarketFrame, validate_market_frame

SourceKind = Literal["actual", "synthetic"]


@dataclass(frozen=True, slots=True)
class SyntheticSeries:
    nav: pd.Series
    leverage: float
    initial_nav: float
    annual_expense_ratio: float
    unit: Literal["index"] = "index"
    source_kind: Literal["synthetic"] = "synthetic"


@dataclass(frozen=True, slots=True)
class LeveragedObservation:
    session_date: date
    value: float
    source_kind: SourceKind


@dataclass(frozen=True, slots=True)
class ObservationCollection:
    rows: tuple[LeveragedObservation, ...]

    @property
    def count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True)
class LeveragedHistoryReport:
    actual_statistics: ObservationCollection
    stress_statistics: ObservationCollection

    @property
    def actual_count(self) -> int:
        return self.actual_statistics.count

    @property
    def synthetic_count(self) -> int:
        return self.stress_statistics.count


def synthetic_daily_reset_nav(
    prototype: MarketFrame,
    leverage: float,
    *,
    initial_nav: float = 100.0,
    annual_expense_ratio: float = 0.0,
    sessions_per_year: int = 252,
) -> SyntheticSeries:
    """Build an index-unit stress path with leverage reset after every session."""

    validate_market_frame(prototype)
    if leverage <= 0.0:
        raise ValueError("Leverage must be positive")
    if initial_nav <= 0.0:
        raise ValueError("Initial NAV must be positive")
    if annual_expense_ratio < 0.0:
        raise ValueError("Annual expense ratio cannot be negative")
    if sessions_per_year <= 0:
        raise ValueError("Sessions per year must be positive")

    returns = prototype.data["price_close"].astype(float).pct_change()
    daily_fee = annual_expense_ratio / sessions_per_year
    values = [initial_nav]
    for daily_return in returns.iloc[1:]:
        net_return = leverage * float(daily_return) - daily_fee
        values.append(values[-1] * max(0.0, 1.0 + net_return))
    nav = pd.Series(
        values,
        index=prototype.data.index.copy(),
        name="synthetic_daily_reset_nav",
        dtype=float,
    )
    return SyntheticSeries(
        nav=nav,
        leverage=leverage,
        initial_nav=initial_nav,
        annual_expense_ratio=annual_expense_ratio,
    )


def analyze_leveraged_history(
    *,
    actual: MarketFrame,
    synthetic: SyntheticSeries,
) -> LeveragedHistoryReport:
    """Keep observed ETF prices and synthetic stress-index values disjoint."""

    validate_market_frame(actual)
    actual_rows = tuple(
        LeveragedObservation(
            session_date=cast(pd.Timestamp, timestamp).date(),
            value=float(value),
            source_kind="actual",
        )
        for timestamp, value in actual.data["adj_close"].items()
    )
    synthetic_rows = tuple(
        LeveragedObservation(
            session_date=cast(pd.Timestamp, timestamp).date(),
            value=float(value),
            source_kind="synthetic",
        )
        for timestamp, value in synthetic.nav.items()
    )
    return LeveragedHistoryReport(
        actual_statistics=ObservationCollection(rows=actual_rows),
        stress_statistics=ObservationCollection(rows=synthetic_rows),
    )
