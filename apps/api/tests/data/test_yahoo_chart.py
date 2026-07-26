from __future__ import annotations

import json
from datetime import UTC, date, datetime
from email.message import Message
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pandas as pd
from drawdown_lab.data.yahoo import YahooFinanceProvider


def _timestamp(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, 14, 30, tzinfo=UTC).timestamp())


def _chart_payload() -> bytes:
    first = _timestamp(2022, 1, 12)
    second = _timestamp(2022, 1, 13)
    return json.dumps(
        {
            "chart": {
                "error": None,
                "result": [
                    {
                        "meta": {
                            "symbol": "TQQQ",
                            "exchangeTimezoneName": "America/New_York",
                        },
                        "timestamp": [first, second],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [37.0, 34.0],
                                    "high": [39.0, 36.0],
                                    "low": [36.0, 33.0],
                                    "close": [38.0, 35.0],
                                }
                            ],
                            "adjclose": [{"adjclose": [37.5, 35.0]}],
                        },
                        "events": {
                            "dividends": {
                                str(first): {
                                    "amount": 0.2,
                                    "date": first,
                                }
                            },
                            "splits": {
                                str(second): {
                                    "date": second,
                                    "numerator": 2.0,
                                    "denominator": 1.0,
                                    "splitRatio": "2:1",
                                }
                            },
                        },
                    }
                ],
            }
        }
    ).encode()


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.headers: Message = Message()
        self.status = 200

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_chart_provider_uses_one_direct_request_and_maps_split_adjusted_data() -> None:
    observed: dict[str, Any] = {}

    def opener(request: Request, *, timeout: float) -> _Response:
        observed["url"] = request.full_url
        observed["user_agent"] = request.get_header("User-agent")
        observed["timeout"] = timeout
        return _Response(_chart_payload())

    frame = YahooFinanceProvider(
        opener=opener,
        sleeper=lambda _: None,
        max_attempts=1,
        min_interval_seconds=0,
    ).fetch("TQQQ", date(2022, 1, 12), date(2022, 1, 13))

    request_url = urlparse(str(observed["url"]))
    query = parse_qs(request_url.query)
    assert request_url.netloc == "query1.finance.yahoo.com"
    assert request_url.path.endswith("/TQQQ")
    assert query["interval"] == ["1d"]
    assert query["events"] == ["div,splits"]
    assert query["includeAdjustedClose"] == ["true"]
    assert datetime.fromtimestamp(int(query["period1"][0]), UTC).date() == date(
        2022, 1, 12
    )
    assert datetime.fromtimestamp(int(query["period2"][0]), UTC).date() == date(
        2022, 1, 14
    )
    assert observed["user_agent"]
    assert observed["timeout"] == 30.0

    data = frame.data
    first = pd.Timestamp("2022-01-12")
    second = pd.Timestamp("2022-01-13")
    assert data.index.tolist() == [first, second]
    assert data.loc[first, "price_close"] == 38.0
    assert data.loc[first, "raw_close"] == 76.0
    assert data.loc[first, "dividend_raw"] == 0.4
    assert data.loc[second, "price_close"] == 35.0
    assert data.loc[second, "raw_close"] == 35.0
    assert data.loc[second, "split_ratio"] == 2.0
    assert data.loc[first, "adj_close"] == 37.5


def test_chart_provider_retries_a_rate_limit_using_retry_after() -> None:
    attempts = 0
    sleeps: list[float] = []

    def opener(request: Request, *, timeout: float) -> _Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            headers = Message()
            headers["Retry-After"] = "2"
            raise HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                headers,
                None,
            )
        return _Response(_chart_payload())

    result = YahooFinanceProvider(
        opener=opener,
        sleeper=sleeps.append,
        max_attempts=2,
        min_interval_seconds=0,
    ).fetch("TQQQ", date(2022, 1, 12), date(2022, 1, 13))

    assert len(result.data) == 2
    assert attempts == 2
    assert sleeps == [2.0]


def test_chart_provider_percent_encodes_index_symbols() -> None:
    observed_url = ""

    def opener(request: Request, *, timeout: float) -> _Response:
        nonlocal observed_url
        observed_url = request.full_url
        return _Response(_chart_payload())

    YahooFinanceProvider(
        opener=opener,
        sleeper=lambda _: None,
        max_attempts=1,
        min_interval_seconds=0,
    ).fetch("^NDX", date(2022, 1, 12), date(2022, 1, 13))

    assert "/%5ENDX?" in observed_url
