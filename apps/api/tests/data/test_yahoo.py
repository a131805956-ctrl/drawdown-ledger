from __future__ import annotations

import pandas as pd

from drawdown_lab.data.yahoo import market_frame_from_yahoo_history


def test_yahoo_mapping_preserves_raw_actions_and_uses_split_only_price_adjustment() -> None:
    history = pd.DataFrame(
        {
            "Open": [100.0, 52.0],
            "High": [110.0, 56.0],
            "Low": [90.0, 50.0],
            "Close": [100.0, 54.0],
            "Adj Close": [99.0, 54.0],
            "Dividends": [1.0, 0.0],
            "Stock Splits": [0.0, 2.0],
        },
        index=pd.DatetimeIndex(["2026-07-30", "2026-07-31"], name="Date"),
    )

    result = market_frame_from_yahoo_history(history).data

    assert result.loc[pd.Timestamp("2026-07-30"), "raw_close"] == 100.0
    assert result.loc[pd.Timestamp("2026-07-30"), "dividend_raw"] == 1.0
    assert result.loc[pd.Timestamp("2026-07-31"), "split_ratio"] == 2.0
    assert result.loc[pd.Timestamp("2026-07-30"), "price_close"] == 50.0
    assert result.loc[pd.Timestamp("2026-07-30"), "adj_close"] == 99.0


def test_yahoo_mapping_keeps_actions_when_history_index_has_timezone() -> None:
    history = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [110.0],
            "Low": [90.0],
            "Close": [100.0],
            "Adj Close": [99.0],
            "Dividends": [1.0],
            "Stock Splits": [0.0],
        },
        index=pd.DatetimeIndex(["2026-07-30 00:00:00"], tz="America/New_York"),
    )

    result = market_frame_from_yahoo_history(history).data

    assert result.loc[pd.Timestamp("2026-07-30"), "dividend_raw"] == 1.0
    assert result.loc[pd.Timestamp("2026-07-30"), "split_ratio"] == 1.0
