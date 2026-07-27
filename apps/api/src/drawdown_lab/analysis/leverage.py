from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, cast

import pandas as pd

from drawdown_lab.data.models import MarketFrame, validate_market_frame

SourceKind = Literal["actual", "synthetic"]


@dataclass(frozen=True, slots=True)
class SyntheticModelAssumptions:
    """Reproducible assumptions used to construct a synthetic ETF path."""

    method: Literal["daily_rebalance"]
    leverage: float
    initial_nav: float
    annual_management_fee: float
    daily_financing_drag: float
    daily_roll_drag: float
    daily_transaction_drag: float
    sessions_per_year: int


def default_synthetic_model_parameters(
    leverage: float,
) -> tuple[float, float, float, float]:
    """Return conservative, transparent defaults for a leveraged ETF proxy.

    The values are deliberately modest approximations rather than a claim
    about a particular fund's prospectus: management is annualized at 0.95%,
    while financing, roll and rebalancing friction scale with leverage on a
    daily basis.  Callers can override every value explicitly.
    """

    if leverage <= 1.0:
        return (0.0, 0.0, 0.0, 0.0)
    scale = leverage
    return (
        0.0095,
        0.00003 * scale,
        0.00001 * scale,
        0.000005 * scale,
    )


@dataclass(frozen=True, slots=True)
class SyntheticSeries:
    nav: pd.Series
    leverage: float
    initial_nav: float
    annual_expense_ratio: float
    assumptions: SyntheticModelAssumptions
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
    annual_management_fee: float | None = None,
    daily_financing_drag: float = 0.0,
    daily_roll_drag: float = 0.0,
    daily_transaction_drag: float = 0.0,
    sessions_per_year: int = 252,
) -> SyntheticSeries:
    """Build an index-unit path with daily leverage reset and explicit drags.

    ``annual_expense_ratio`` remains a compatibility alias for the new
    ``annual_management_fee`` parameter.  Daily financing, roll and
    transaction costs are modeled as additive return drags on every session;
    this keeps the assumptions transparent and prevents a long synthetic
    history from silently assuming a frictionless leveraged product.
    """

    validate_market_frame(prototype)
    if leverage <= 0.0:
        raise ValueError("Leverage must be positive")
    if initial_nav <= 0.0:
        raise ValueError("Initial NAV must be positive")
    management_fee = (
        annual_expense_ratio
        if annual_management_fee is None
        else annual_management_fee
    )
    if management_fee < 0.0:
        raise ValueError("Annual management fee cannot be negative")
    for name, value in (
        ("daily financing drag", daily_financing_drag),
        ("daily roll drag", daily_roll_drag),
        ("daily transaction drag", daily_transaction_drag),
    ):
        if value < 0.0:
            raise ValueError(f"{name.capitalize()} cannot be negative")
    if sessions_per_year <= 0:
        raise ValueError("Sessions per year must be positive")

    returns = prototype.data["price_close"].astype(float).pct_change()
    daily_fee = (
        management_fee / sessions_per_year
        + daily_financing_drag
        + daily_roll_drag
        + daily_transaction_drag
    )
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
        annual_expense_ratio=management_fee,
        assumptions=SyntheticModelAssumptions(
            method="daily_rebalance",
            leverage=leverage,
            initial_nav=initial_nav,
            annual_management_fee=management_fee,
            daily_financing_drag=daily_financing_drag,
            daily_roll_drag=daily_roll_drag,
            daily_transaction_drag=daily_transaction_drag,
            sessions_per_year=sessions_per_year,
        ),
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
