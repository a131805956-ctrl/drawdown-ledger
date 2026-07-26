from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import certifi
import pandas as pd
import yfinance as yf

from drawdown_lab.data.models import MarketFrame


def _configure_curl_ca_bundle() -> None:
    if os.environ.get("CURL_CA_BUNDLE"):
        return

    source = Path(certifi.where()).resolve()
    if str(source).isascii():
        return

    destination: Path | None = None
    for root in (os.environ.get("LOCALAPPDATA"), tempfile.gettempdir()):
        if not root:
            continue
        candidate = Path(root).resolve() / "DrawdownLedger" / "cacert.pem"
        if str(candidate).isascii():
            destination = candidate
            break
    if destination is None:
        raise RuntimeError(
            "Yahoo TLS requires an ASCII-safe LOCALAPPDATA or temporary directory."
        )

    source_bytes = source.read_bytes()
    if not destination.is_file() or destination.read_bytes() != source_bytes:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".cacert-{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(source_bytes)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    os.environ["CURL_CA_BUNDLE"] = str(destination)


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
        _configure_curl_ca_bundle()
        history = yf.Ticker(symbol).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            actions=True,
        )
        return market_frame_from_yahoo_history(history)
