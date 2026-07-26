from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from math import isfinite
from typing import cast

import pandas as pd


@dataclass(frozen=True, slots=True)
class ForwardReturn:
    horizon_sessions: int
    exit_date: date | None
    total_return: float | None


@dataclass(frozen=True, slots=True)
class Entry:
    position: int
    entry_date: date
    adjusted_open: Decimal


def adjusted_open(row: pd.Series) -> Decimal | None:
    """Convert a raw traded open to the adjusted-close basis for total returns."""

    raw_open = float(row["raw_open"])
    raw_close = float(row["raw_close"])
    adj_close = float(row["adj_close"])
    if (
        not all(isfinite(value) for value in (raw_open, raw_close, adj_close))
        or raw_open <= 0.0
        or raw_close <= 0.0
        or adj_close <= 0.0
    ):
        return None
    return (
        Decimal(str(raw_open)) * Decimal(str(adj_close)) / Decimal(str(raw_close))
    ).normalize()


def first_later_valid_entry(data: pd.DataFrame, signal_date: date) -> Entry | None:
    signal_timestamp = pd.Timestamp(signal_date)
    position = int(data.index.searchsorted(signal_timestamp, side="right"))
    while position < len(data):
        price = adjusted_open(data.iloc[position])
        if price is not None:
            session_timestamp = cast(pd.Timestamp, data.index[position])
            return Entry(
                position=position,
                entry_date=session_timestamp.date(),
                adjusted_open=price,
            )
        position += 1
    return None


def calculate_forward_returns(
    data: pd.DataFrame,
    entry: Entry,
    horizons: tuple[int, ...],
) -> tuple[ForwardReturn, ...]:
    entry_price = float(entry.adjusted_open)
    results: list[ForwardReturn] = []
    for horizon in horizons:
        exit_position = entry.position + horizon
        if exit_position >= len(data):
            results.append(
                ForwardReturn(
                    horizon_sessions=horizon,
                    exit_date=None,
                    total_return=None,
                )
            )
            continue
        exit_row = data.iloc[exit_position]
        exit_price = float(exit_row["adj_close"])
        exit_timestamp = pd.Timestamp(data.index[exit_position])
        results.append(
            ForwardReturn(
                horizon_sessions=horizon,
                exit_date=exit_timestamp.date(),
                total_return=exit_price / entry_price - 1.0,
            )
        )
    return tuple(results)


def adjusted_excursions(
    data: pd.DataFrame,
    entry: Entry,
    horizon_sessions: int,
) -> tuple[float, float]:
    """Return MAE/MFE from adjusted intraday lows/highs through the horizon."""

    stop = min(entry.position + horizon_sessions + 1, len(data))
    window = data.iloc[entry.position:stop]
    adjustment = window["adj_close"].astype(float) / window["raw_close"].astype(float)
    adjusted_lows = window["raw_low"].astype(float) * adjustment
    adjusted_highs = window["raw_high"].astype(float) * adjustment
    entry_price = float(entry.adjusted_open)
    mae = float(adjusted_lows.min()) / entry_price - 1.0
    mfe = float(adjusted_highs.max()) / entry_price - 1.0
    return mae, mfe
