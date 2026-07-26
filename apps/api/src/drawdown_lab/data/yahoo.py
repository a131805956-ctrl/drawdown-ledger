from __future__ import annotations

import os
from datetime import date, timedelta
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

import certifi
import pandas as pd

from drawdown_lab.data.models import MarketFrame


class _Ticker(Protocol):
    def history(self, **kwargs: object) -> pd.DataFrame: ...


class _CurlSession(Protocol):
    verify: bool | str | None

    def close(self) -> None: ...


class _YFinance(Protocol):
    def Ticker(self, symbol: str, *, session: _CurlSession) -> _Ticker: ...


class _CurlRequests(Protocol):
    def Session(self, *, verify: str) -> _CurlSession: ...


def _load_yfinance() -> _YFinance:
    return cast(_YFinance, import_module("yfinance"))


def _load_curl_requests() -> _CurlRequests:
    return cast(_CurlRequests, import_module("curl_cffi.requests"))


def _resolve_curl_ca_bundle() -> Path:
    source: Path | None = None
    source_label = "certifi"
    for variable in (
        "SSL_CERT_FILE",
        "CURL_CA_BUNDLE",
        "REQUESTS_CA_BUNDLE",
    ):
        configured = os.environ.get(variable)
        if configured:
            source = Path(configured).expanduser().resolve()
            source_label = variable
            break
    if source is None:
        source = Path(certifi.where()).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"{source_label} CA bundle does not exist: {source}")
    if str(source).isascii():
        return source

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError(
            "Yahoo TLS requires an ASCII-safe LOCALAPPDATA directory."
        )
    destination = (
        Path(local_app_data).expanduser().resolve()
        / "DrawdownLedger"
        / "cacert.pem"
    )
    if not str(destination).isascii():
        raise RuntimeError(
            "Yahoo TLS requires an ASCII-safe LOCALAPPDATA directory."
        )
    if destination.parent.is_symlink() or destination.is_symlink():
        raise RuntimeError("Yahoo TLS CA cache cannot be a symbolic link.")

    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    source_bytes = source.read_bytes()
    if not destination.is_file() or destination.read_bytes() != source_bytes:
        temporary = destination.with_name(f".cacert-{uuid4().hex}.tmp")
        try:
            descriptor = os.open(
                temporary,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(source_bytes)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination


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
        ca_bundle = _resolve_curl_ca_bundle()
        curl_requests = _load_curl_requests()
        yfinance = _load_yfinance()
        session = curl_requests.Session(verify=str(ca_bundle))
        try:
            history = yfinance.Ticker(symbol, session=session).history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                auto_adjust=False,
                actions=True,
            )
        finally:
            session.close()
        return market_frame_from_yahoo_history(history)
