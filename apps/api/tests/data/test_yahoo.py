from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import certifi
import pandas as pd
import pytest
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
    for variable in (
        "CURL_CA_BUNDLE",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
    ):
        monkeypatch.delenv(variable, raising=False)
    observed_bundle: dict[str, Path] = {}

    class InspectingSession:
        def __init__(self, *, verify: str) -> None:
            configured = Path(verify)
            observed_bundle["path"] = configured
            assert str(configured).isascii()
            assert configured.read_bytes() == source.read_bytes()

        def close(self) -> None:
            pass

    class InspectingTicker:
        def __init__(self, symbol: str, *, session: InspectingSession) -> None:
            assert symbol == "0050.TW"
            assert isinstance(session, InspectingSession)

        def history(self, **_: object) -> pd.DataFrame:
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

    monkeypatch.setattr(
        yahoo_module,
        "_load_yfinance",
        lambda: SimpleNamespace(Ticker=InspectingTicker),
    )
    monkeypatch.setattr(
        yahoo_module,
        "_load_curl_requests",
        lambda: SimpleNamespace(Session=InspectingSession),
        raising=False,
    )

    result = YahooFinanceProvider().fetch(
        "0050.TW",
        date(2026, 6, 1),
        date(2026, 6, 30),
    )

    assert len(result.data) == 1
    assert observed_bundle["path"] == cache_root / "DrawdownLedger" / "cacert.pem"
    assert "CURL_CA_BUNDLE" not in os.environ


def test_yahoo_injects_ascii_ca_into_real_curl_session(
    tmp_path: Path,
) -> None:
    source = tmp_path / "憑證" / "cacert.pem"
    source.parent.mkdir()
    source.write_bytes(b"trusted test certificate")
    cache_root = tmp_path / "ascii-cache"
    assert str(cache_root).isascii()
    source_root = Path(__file__).resolve().parents[2] / "src"
    script = """
import os
from pathlib import Path

import certifi

source = Path(os.environ["TEST_CERT_SOURCE"])
certifi.where = lambda: str(source)
from drawdown_lab.data import yahoo

yahoo_ca = yahoo._resolve_curl_ca_bundle()
curl_requests = yahoo._load_curl_requests()
session = curl_requests.Session(verify=str(yahoo_ca))

expected = Path(os.environ["LOCALAPPDATA"]) / "DrawdownLedger" / "cacert.pem"
if Path(session.verify) != expected:
    raise SystemExit(
        f"curl_cffi Session.verify is {session.verify!r}, expected {str(expected)!r}"
    )
session.close()
"""
    environment = os.environ.copy()
    environment["LOCALAPPDATA"] = str(cache_root)
    environment["PYTHONPATH"] = str(source_root)
    environment["TEST_CERT_SOURCE"] = str(source)
    for variable in (
        "CURL_CA_BUNDLE",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
    ):
        environment.pop(variable, None)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_yahoo_ca_override_priority_is_preserved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ssl_bundle = tmp_path / "ssl.pem"
    curl_bundle = tmp_path / "curl.pem"
    requests_bundle = tmp_path / "requests.pem"
    for path in (ssl_bundle, curl_bundle, requests_bundle):
        path.write_bytes(path.name.encode())
    monkeypatch.setenv("SSL_CERT_FILE", str(ssl_bundle))
    monkeypatch.setenv("CURL_CA_BUNDLE", str(curl_bundle))
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(requests_bundle))

    resolved = yahoo_module._resolve_curl_ca_bundle()

    assert resolved == ssl_bundle.resolve()


def test_yahoo_repairs_managed_ca_cache_before_each_request(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "憑證" / "cacert.pem"
    source.parent.mkdir()
    source.write_bytes(b"trusted source")
    cache_root = tmp_path / "ascii-cache"
    monkeypatch.setattr(certifi, "where", lambda: str(source))
    monkeypatch.setenv("LOCALAPPDATA", str(cache_root))
    for variable in (
        "CURL_CA_BUNDLE",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
    ):
        monkeypatch.delenv(variable, raising=False)

    first = yahoo_module._resolve_curl_ca_bundle()
    first.write_bytes(b"tampered cache")
    second = yahoo_module._resolve_curl_ca_bundle()

    assert first == second
    assert second.read_bytes() == source.read_bytes()


def test_yahoo_fails_closed_without_ascii_private_cache_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "憑證" / "cacert.pem"
    source.parent.mkdir()
    source.write_bytes(b"trusted source")
    monkeypatch.setattr(certifi, "where", lambda: str(source))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "使用者"))
    for variable in (
        "CURL_CA_BUNDLE",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
    ):
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(RuntimeError, match="ASCII-safe LOCALAPPDATA"):
        yahoo_module._resolve_curl_ca_bundle()
