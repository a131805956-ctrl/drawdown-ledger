from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from drawdown_lab.analysis.episodes import classify_episodes
from drawdown_lab.data.models import MarketFrame, validate_market_frame


@dataclass(frozen=True, slots=True)
class ThresholdAnalysis:
    threshold: float
    n_day: int
    n_episode: int


def drawdown_series(close: pd.Series) -> pd.Series:
    """Calculate close-to-running-maximum drawdown as a non-positive ratio."""

    numeric = close.astype(float)
    result: pd.Series = numeric / numeric.cummax() - 1.0
    return result


def analyze_threshold(frame: MarketFrame, threshold: float) -> ThresholdAnalysis:
    """Count daily observations separately from independent ATH-cycle triggers."""

    if threshold <= 0.0 or threshold > 1.0:
        raise ValueError("Drawdown threshold must be a positive ratio no greater than 1")
    validate_market_frame(frame)
    close = frame.data["price_close"].astype(float)
    qualifying_days = close <= close.cummax() * (1.0 - threshold)
    episodes = classify_episodes(frame, (threshold,))
    return ThresholdAnalysis(
        threshold=threshold,
        n_day=int(qualifying_days.sum()),
        n_episode=len(episodes),
    )
