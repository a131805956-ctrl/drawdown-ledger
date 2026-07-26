from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from email.message import Message
from threading import Lock
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from drawdown_lab.data.models import MarketFrame

YAHOO_CHART_ORIGIN = "https://query1.finance.yahoo.com"
YAHOO_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 DrawdownLedger/0.1"
)


class YahooChartError(RuntimeError):
    """Yahoo's documented chart-shaped response was unavailable or invalid."""


class _UrlResponse(Protocol):
    status: int
    headers: Message

    def __enter__(self) -> _UrlResponse: ...

    def __exit__(self, *args: object) -> object: ...

    def read(self) -> bytes: ...


class _Opener(Protocol):
    def __call__(
        self,
        request: Request,
        *,
        timeout: float,
    ) -> _UrlResponse: ...


def _safe_timezone(value: object) -> ZoneInfo:
    if isinstance(value, str) and value:
        try:
            return ZoneInfo(value)
        except ZoneInfoNotFoundError:
            pass
    return ZoneInfo("UTC")


def _session_date(timestamp: object, timezone: ZoneInfo) -> date:
    if not isinstance(timestamp, int | float):
        raise YahooChartError("Yahoo chart contains a non-numeric timestamp.")
    return datetime.fromtimestamp(timestamp, UTC).astimezone(timezone).date()


def _number(value: object, *, field: str) -> float:
    if not isinstance(value, int | float):
        raise YahooChartError(f"Yahoo chart contains an invalid {field} value.")
    result = float(value)
    if not pd.notna(result):
        raise YahooChartError(f"Yahoo chart contains an invalid {field} value.")
    return result


def _event_rows(
    raw_events: object,
    *,
    timezone: ZoneInfo,
) -> list[tuple[date, Mapping[str, object]]]:
    if not isinstance(raw_events, Mapping):
        return []
    result: list[tuple[date, Mapping[str, object]]] = []
    for raw_event in raw_events.values():
        if not isinstance(raw_event, Mapping):
            continue
        event_timestamp = raw_event.get("date")
        try:
            session = _session_date(event_timestamp, timezone)
        except YahooChartError:
            continue
        result.append((session, cast(Mapping[str, object], raw_event)))
    return result


def _split_ratio(event: Mapping[str, object]) -> float:
    numerator = event.get("numerator")
    denominator = event.get("denominator")
    if isinstance(numerator, int | float) and isinstance(
        denominator, int | float
    ):
        denominator_value = float(denominator)
        if denominator_value > 0:
            ratio = float(numerator) / denominator_value
            if ratio > 0:
                return ratio
    raw_ratio = event.get("splitRatio")
    if isinstance(raw_ratio, str) and ":" in raw_ratio:
        raw_numerator, raw_denominator = raw_ratio.split(":", maxsplit=1)
        try:
            ratio = float(raw_numerator) / float(raw_denominator)
        except (ValueError, ZeroDivisionError):
            ratio = 0.0
        if ratio > 0:
            return ratio
    raise YahooChartError("Yahoo chart contains an invalid stock-split event.")


def market_frame_from_yahoo_chart(result: Mapping[str, object]) -> MarketFrame:
    """Map Yahoo Chart v8 data into auditable raw and adjusted price columns.

    Yahoo's chart OHLC values are already adjusted for later stock splits.
    ``price_*`` therefore uses the chart values directly for drawdown signals,
    while ``raw_*`` reverses later splits so share accounting can apply each
    split exactly once on its event date.
    """

    meta = result.get("meta")
    timezone = _safe_timezone(
        meta.get("exchangeTimezoneName") if isinstance(meta, Mapping) else None
    )
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    if not isinstance(timestamps, list) or not isinstance(indicators, Mapping):
        raise YahooChartError("Yahoo returned no daily chart history.")
    raw_quotes = indicators.get("quote")
    raw_adjusted = indicators.get("adjclose")
    if (
        not isinstance(raw_quotes, list)
        or not raw_quotes
        or not isinstance(raw_quotes[0], Mapping)
        or not isinstance(raw_adjusted, list)
        or not raw_adjusted
        or not isinstance(raw_adjusted[0], Mapping)
    ):
        raise YahooChartError("Yahoo chart is missing quote or adjusted-close data.")
    quotes = cast(Mapping[str, object], raw_quotes[0])
    adjusted = cast(Mapping[str, object], raw_adjusted[0])
    columns: dict[str, list[object]] = {}
    for field in ("open", "high", "low", "close"):
        values = quotes.get(field)
        if not isinstance(values, list) or len(values) != len(timestamps):
            raise YahooChartError(f"Yahoo chart is missing {field} values.")
        columns[field] = values
    adjusted_values = adjusted.get("adjclose")
    if not isinstance(adjusted_values, list) or len(adjusted_values) != len(
        timestamps
    ):
        raise YahooChartError("Yahoo chart is missing adjusted-close values.")

    rows: list[dict[str, object]] = []
    for index, timestamp in enumerate(timestamps):
        values = {
            field: columns[field][index]
            for field in ("open", "high", "low", "close")
        }
        values["adj_close"] = adjusted_values[index]
        if any(value is None for value in values.values()):
            continue
        session = _session_date(timestamp, timezone)
        rows.append(
            {
                "session": pd.Timestamp(session),
                **{
                    f"price_{field}": _number(values[field], field=field)
                    for field in ("open", "high", "low", "close")
                },
                "adj_close": _number(
                    values["adj_close"],
                    field="adjusted close",
                ),
            }
        )
    if not rows:
        raise YahooChartError("Yahoo returned no complete daily chart rows.")

    data = (
        pd.DataFrame(rows)
        .set_index("session")
        .loc[lambda frame: ~frame.index.duplicated(keep="last")]
        .sort_index()
    )
    data.index = pd.DatetimeIndex(data.index, name="session")
    data["split_ratio"] = 1.0
    data["dividend_raw"] = 0.0
    events = result.get("events")
    if isinstance(events, Mapping):
        for session, event in _event_rows(
            events.get("splits"),
            timezone=timezone,
        ):
            timestamp = pd.Timestamp(session)
            if timestamp in data.index:
                data.loc[timestamp, "split_ratio"] = _split_ratio(event)
        adjusted_dividends: dict[pd.Timestamp, float] = {}
        for session, event in _event_rows(
            events.get("dividends"),
            timezone=timezone,
        ):
            timestamp = pd.Timestamp(session)
            amount = event.get("amount")
            if timestamp in data.index and isinstance(amount, int | float):
                adjusted_dividends[timestamp] = float(amount)
    else:
        adjusted_dividends = {}

    future_split_factor = (
        data["split_ratio"].iloc[::-1].cumprod().iloc[::-1]
        / data["split_ratio"]
    )
    for field in ("open", "high", "low", "close"):
        data[f"raw_{field}"] = data[f"price_{field}"] * future_split_factor
    for timestamp, adjusted_amount in adjusted_dividends.items():
        data.loc[timestamp, "dividend_raw"] = (
            adjusted_amount * future_split_factor.loc[timestamp]
        )
    ordered = data.loc[
        :,
        (
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
        ),
    ]
    return MarketFrame(ordered)


def market_frame_from_yahoo_history(history: pd.DataFrame) -> MarketFrame:
    """Compatibility mapper for a split-adjusted Yahoo-style history table."""

    if history.empty:
        raise ValueError("Yahoo returned no daily history")
    required = {"Open", "High", "Low", "Close", "Adj Close"}
    missing = required.difference(history.columns)
    if missing:
        raise ValueError(
            f"Yahoo history is missing columns: {', '.join(sorted(missing))}"
        )
    data = pd.DataFrame(
        index=pd.DatetimeIndex(history.index).tz_localize(None).normalize()
    )
    for source, destination in (
        ("Open", "price_open"),
        ("High", "price_high"),
        ("Low", "price_low"),
        ("Close", "price_close"),
    ):
        data[destination] = history[source].astype(float).to_numpy()
    data["adj_close"] = history["Adj Close"].astype(float).to_numpy()
    adjusted_dividends = (
        history["Dividends"].astype(float).to_numpy()
        if "Dividends" in history
        else 0.0
    )
    split_events = (
        history["Stock Splits"].astype(float).to_numpy()
        if "Stock Splits" in history
        else 0.0
    )
    data["split_ratio"] = pd.Series(
        split_events,
        index=data.index,
    ).replace(0.0, 1.0)
    future_split_factor = (
        data["split_ratio"].iloc[::-1].cumprod().iloc[::-1]
        / data["split_ratio"]
    )
    for field in ("open", "high", "low", "close"):
        data[f"raw_{field}"] = data[f"price_{field}"] * future_split_factor
    data["dividend_raw"] = (
        pd.Series(adjusted_dividends, index=data.index)
        * future_split_factor
    )
    data.index.name = "session"
    return MarketFrame(data)


class YahooFinanceProvider:
    """Rate-limited Yahoo Chart v8 market-data provider."""

    provider_name = "yahoo-finance-chart-v8"

    def __init__(
        self,
        *,
        opener: _Opener | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        max_attempts: int = 3,
        min_interval_seconds: float = 0.25,
        timeout_seconds: float = 30.0,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if min_interval_seconds < 0:
            raise ValueError("min_interval_seconds cannot be negative")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._opener = opener or cast(_Opener, urlopen)
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._max_attempts = max_attempts
        self._min_interval_seconds = min_interval_seconds
        self._timeout_seconds = timeout_seconds
        self._request_lock = Lock()
        self._last_request_started: float | None = None

    def _wait_for_request_slot(self) -> None:
        with self._request_lock:
            now = self._monotonic()
            if self._last_request_started is not None:
                remaining = (
                    self._last_request_started
                    + self._min_interval_seconds
                    - now
                )
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._monotonic()
            self._last_request_started = now

    @staticmethod
    def _retry_delay(headers: Message | Mapping[str, str], attempt: int) -> float:
        raw_retry_after = headers.get("Retry-After")
        if isinstance(raw_retry_after, str):
            try:
                return min(30.0, max(0.0, float(raw_retry_after)))
            except ValueError:
                pass
        return min(8.0, float(2**attempt))

    def _request(self, request: Request, *, symbol: str) -> bytes:
        for attempt in range(self._max_attempts):
            self._wait_for_request_slot()
            try:
                with self._opener(
                    request,
                    timeout=self._timeout_seconds,
                ) as response:
                    return response.read()
            except HTTPError as error:
                retryable = error.code == 429 or 500 <= error.code < 600
                if retryable and attempt + 1 < self._max_attempts:
                    self._sleeper(
                        self._retry_delay(error.headers, attempt)
                    )
                    continue
                raise YahooChartError(
                    f"Yahoo chart request for {symbol} failed with HTTP {error.code}."
                ) from error
            except URLError as error:
                if attempt + 1 < self._max_attempts:
                    self._sleeper(float(2**attempt))
                    continue
                raise YahooChartError(
                    f"Yahoo chart request for {symbol} failed: {error.reason}"
                ) from error
        raise YahooChartError(f"Yahoo chart request for {symbol} failed.")

    def fetch(self, symbol: str, start: date, end: date) -> MarketFrame:
        if end < start:
            raise ValueError("Yahoo fetch end cannot precede start")
        parameters = urlencode(
            {
                "period1": int(
                    datetime.combine(
                        start,
                        datetime.min.time(),
                        tzinfo=UTC,
                    ).timestamp()
                ),
                "period2": int(
                    datetime.combine(
                        end + timedelta(days=1),
                        datetime.min.time(),
                        tzinfo=UTC,
                    ).timestamp()
                ),
                "interval": "1d",
                "events": "div,splits",
                "includeAdjustedClose": "true",
            }
        )
        url = (
            f"{YAHOO_CHART_ORIGIN}/v8/finance/chart/"
            f"{quote(symbol, safe='')}?{parameters}"
        )
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": YAHOO_USER_AGENT,
            },
        )
        raw_payload = self._request(request, symbol=symbol)
        try:
            payload = json.loads(raw_payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise YahooChartError(
                f"Yahoo chart returned invalid JSON for {symbol}."
            ) from error
        if not isinstance(payload, Mapping):
            raise YahooChartError(
                f"Yahoo chart returned an invalid document for {symbol}."
            )
        chart = payload.get("chart")
        if not isinstance(chart, Mapping):
            raise YahooChartError(
                f"Yahoo chart response is missing chart data for {symbol}."
            )
        chart_error = chart.get("error")
        if chart_error is not None:
            description = (
                chart_error.get("description")
                if isinstance(chart_error, Mapping)
                else None
            )
            message = (
                str(description)
                if isinstance(description, str) and description
                else "unknown chart error"
            )
            raise YahooChartError(f"Yahoo rejected {symbol}: {message}")
        results = chart.get("result")
        if not isinstance(results, list) or not results:
            raise YahooChartError(
                f"Yahoo returned no daily chart history for {symbol}."
            )
        result = results[0]
        if not isinstance(result, Mapping):
            raise YahooChartError(
                f"Yahoo returned invalid daily chart history for {symbol}."
            )
        return market_frame_from_yahoo_chart(
            cast(Mapping[str, object], result)
        )
