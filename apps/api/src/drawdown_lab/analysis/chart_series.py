from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, cast

import pandas as pd

from drawdown_lab.analysis.leverage import synthetic_daily_reset_nav
from drawdown_lab.data.models import MarketFrame, validate_market_frame


@dataclass(frozen=True, slots=True)
class ChartPoint:
    session: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    total_return_close: float
    normalized_total_return: float
    drawdown: float


@dataclass(frozen=True, slots=True)
class ChartSeries:
    source_kind: Literal["actual", "synthetic"]
    unit: Literal["price", "index"]
    points: tuple[ChartPoint, ...]


def _date(value: object) -> date:
    return cast(pd.Timestamp, value).date()


def _selected(data: pd.DataFrame, start: date | None, end: date | None) -> pd.DataFrame:
    selected = data
    if start is not None:
        selected = selected.loc[selected.index >= pd.Timestamp(start)]
    if end is not None:
        selected = selected.loc[selected.index <= pd.Timestamp(end)]
    return selected


def actual_chart_series(
    frame: MarketFrame,
    *,
    start: date | None = None,
    end: date | None = None,
) -> ChartSeries:
    """Return split-adjusted price bars with total-return and underwater context."""

    validate_market_frame(frame)
    data = frame.data.copy()
    price_close = data["price_close"].astype(float)
    data["drawdown"] = price_close / price_close.cummax() - 1.0
    selected = _selected(data, start, end).copy()
    if not selected.empty:
        total_return = selected["adj_close"].astype(float)
        selected["normalized_total_return"] = (
            total_return / float(total_return.iloc[0]) * 100.0
        )
    return ChartSeries(
        source_kind="actual",
        unit="price",
        points=tuple(
            ChartPoint(
                session=_date(timestamp),
                open=float(row["price_open"]),
                high=float(row["price_high"]),
                low=float(row["price_low"]),
                close=float(row["price_close"]),
                total_return_close=float(row["adj_close"]),
                normalized_total_return=float(row["normalized_total_return"]),
                drawdown=float(row["drawdown"]),
            )
            for timestamp, row in selected.iterrows()
        ),
    )


def synthetic_chart_series(
    prototype: MarketFrame,
    leverage: float,
    *,
    annual_expense_ratio: float = 0.0,
    start: date | None = None,
    end: date | None = None,
) -> ChartSeries:
    """Return a clearly separated daily-reset stress index, never a market price."""

    synthetic = synthetic_daily_reset_nav(
        prototype,
        leverage,
        annual_expense_ratio=annual_expense_ratio,
    )
    values = synthetic.nav.astype(float)
    frame = pd.DataFrame(index=values.index)
    frame["close"] = values
    frame["drawdown"] = values / values.cummax() - 1.0
    selected = _selected(frame, start, end).copy()
    if not selected.empty:
        selected_values = selected["close"].astype(float)
        selected["normalized_total_return"] = (
            selected_values / float(selected_values.iloc[0]) * 100.0
        )
    return ChartSeries(
        source_kind="synthetic",
        unit="index",
        points=tuple(
            ChartPoint(
                session=_date(timestamp),
                open=None,
                high=None,
                low=None,
                close=float(row["close"]),
                total_return_close=float(row["close"]),
                normalized_total_return=float(row["normalized_total_return"]),
                drawdown=float(row["drawdown"]),
            )
            for timestamp, row in selected.iterrows()
        ),
    )
