from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import certifi
import pandas as pd
from drawdown_lab.data import yahoo as yahoo_module
from drawdown_lab.data.yahoo import YahooFinanceProvider, market_frame_from_yahoo_history


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


def test_yahoo_provider_uses_ascii_ca_bundle_when_project_path_is_unicode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "憑證" / "cacert.pem"
    source.parent.mkdir()
    source.write_bytes(b"trusted test certificate")
    cache_root = tmp_path / "ascii-cache"
    assert str(cache_root).isascii()

    monkeypatch.setattr(certifi, "where", lambda: str(source))
    monkeypatch.setenv("LOCALAPPDATA", str(cache_root))
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    observed_bundle: dict[str, Path] = {}

    class InspectingTicker:
        def __init__(self, symbol: str) -> None:
            assert symbol == "0050.TW"

        def history(self, **_: object) -> pd.DataFrame:
            configured = Path(os.environ["CURL_CA_BUNDLE"])
            observed_bundle["path"] = configured
            assert str(configured).isascii()
            assert configured.read_bytes() == source.read_bytes()
            return pd.DataFrame(
                {
                    "Open": [100.0],
                    "High": [101.0],
                    "Low": [99.0],
                    "Close": [100.0],
                    "Adj Close": [100.0],
                    "Dividends": [0.0],
                    "Stock Splits": [0.0],
                },
                index=pd.DatetimeIndex(["2026-06-30"], name="Date"),
            )

    monkeypatch.setattr(yahoo_module.yf, "Ticker", InspectingTicker)

    result = YahooFinanceProvider().fetch(
        "0050.TW",
        date(2026, 6, 1),
        date(2026, 6, 30),
    )

    assert len(result.data) == 1
    assert observed_bundle["path"] == cache_root / "DrawdownLedger" / "cacert.pem"
