from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from drawdown_lab.data.models import MarketFrame


def market_frame_from_yahoo_history(history: pd.DataFrame) -> MarketFrame:
    """Map Yahoo history while keeping split-only prices separate from total-return close."""
    if history.empty:
        raise ValueError("Yahoo returned no daily history")
    required = {"Open", "High", "Low", "Close", "Adj Close"}
    missing = required.difference(history.columns)
    if missing:
        raise ValueError(f"Yahoo history is missing columns: {', '.join(sorted(missing))}")

    result = pd.DataFrame(index=pd.DatetimeIndex(history.index).tz_localize(None).normalize())
    for source, destination in (
        ("Open", "raw_open"),
        ("High", "raw_high"),
        ("Low", "raw_low"),
        ("Close", "raw_close"),
    ):
        result[destination] = history[source].astype(float).to_numpy()
    result["adj_close"] = history["Adj Close"].astype(float).to_numpy()
    result["dividend_raw"] = (
        history["Dividends"].astype(float).to_numpy() if "Dividends" in history else 0.0
    )
    split_events = (
        history["Stock Splits"].astype(float).to_numpy() if "Stock Splits" in history else 0.0
    )
    result["split_ratio"] = pd.Series(split_events, index=result.index).replace(0.0, 1.0)

    future_split_factor = (
        result["split_ratio"].iloc[::-1].cumprod().iloc[::-1] / result["split_ratio"]
    )
    for field in ("open", "high", "low", "close"):
        result[f"price_{field}"] = result[f"raw_{field}"] / future_split_factor
    result.index.name = "session"
    return MarketFrame(result)


class YahooFinanceProvider:
    """Yahoo Finance implementation of the market-data provider protocol."""

    provider_name = "yahoo-finance"

    def fetch(self, symbol: str, start: date, end: date) -> MarketFrame:
        history = yf.Ticker(symbol).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            actions=True,
        )
        return market_frame_from_yahoo_history(history)
