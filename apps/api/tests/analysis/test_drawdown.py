from __future__ import annotations

import pandas as pd
import pytest
from drawdown_lab.analysis.drawdown import analyze_threshold, drawdown_series
from drawdown_lab.data.models import MarketFrame


def _frame_from_closes(closes: list[float]) -> MarketFrame:
    index = pd.date_range("2020-01-02", periods=len(closes), freq="B")
    close = pd.Series(closes, index=index, dtype=float)
    data = pd.DataFrame(
        {
            "raw_open": close,
            "raw_high": close,
            "raw_low": close,
            "raw_close": close,
            "price_open": close,
            "price_high": close,
            "price_low": close,
            "price_close": close,
            "adj_close": close,
            "dividend_raw": 0.0,
            "split_ratio": 1.0,
        },
        index=index,
    )
    return MarketFrame(data)


def test_drawdown_is_relative_to_running_all_time_high() -> None:
    close = pd.Series([100.0, 80.0, 120.0, 90.0])

    result = drawdown_series(close)

    assert result.tolist() == pytest.approx([0.0, -0.20, 0.0, -0.25])


def test_overlapping_days_are_not_independent_episodes() -> None:
    frame = _frame_from_closes([100, 80, 75, 85, 101, 79, 102])

    report = analyze_threshold(frame, threshold=0.20)

    assert report.n_day == 3
    assert report.n_episode == 2


def test_threshold_depth_is_a_positive_ratio() -> None:
    frame = _frame_from_closes([100, 80])

    with pytest.raises(ValueError, match="positive ratio"):
        analyze_threshold(frame, threshold=-0.20)
