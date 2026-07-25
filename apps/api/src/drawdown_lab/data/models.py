from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

REQUIRED_MARKET_COLUMNS = (
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "price_open",
    "price_high",
    "price_low",
    "price_close",
    "adj_close",
    "dividend_raw",
    "split_ratio",
)


@dataclass(slots=True)
class MarketFrame:
    """Daily market data with raw provider actions kept separate from price series."""

    data: pd.DataFrame

    def copy(self) -> MarketFrame:
        return MarketFrame(self.data.copy())


def validate_market_frame(frame: MarketFrame) -> None:
    data = frame.data
    missing = set(REQUIRED_MARKET_COLUMNS).difference(data.columns)
    if missing:
        raise ValueError(f"Market frame is missing required columns: {', '.join(sorted(missing))}")
    if not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("Market frame index must be a DatetimeIndex")
    if data.empty:
        raise ValueError("Market frame must contain at least one session")
    if not data.index.is_monotonic_increasing:
        raise ValueError("Market frame sessions must be sorted")
    if data.index.has_duplicates:
        raise ValueError("Market frame sessions must be unique")
    if data.loc[:, REQUIRED_MARKET_COLUMNS].isna().any().any():
        raise ValueError("Market frame contains null required values")
    if (data["split_ratio"] <= 0).any():
        raise ValueError("Market frame split_ratio values must be positive")


def merge_market_frames(existing: MarketFrame | None, refreshed: MarketFrame) -> MarketFrame:
    if existing is None:
        return refreshed.copy()
    combined = pd.concat((existing.data, refreshed.data))
    combined = combined.loc[~combined.index.duplicated(keep="last")].sort_index()
    return MarketFrame(combined)
