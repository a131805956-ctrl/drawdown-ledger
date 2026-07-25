from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from drawdown_lab.data.catalog import DataCatalog
from drawdown_lab.data.models import MarketFrame
from drawdown_lab.data.update import DataUpdateError, UpdateCoordinator


def market_frame_through(end: str, *, start: str = "2026-07-21") -> MarketFrame:
    index = pd.date_range(start, end, freq="B", name="session")
    raw_close = pd.Series(range(100, 100 + len(index)), index=index, dtype="float64")
    data = pd.DataFrame(index=index)
    for column, offset in (("open", -0.5), ("high", 0.5), ("low", -1.0), ("close", 0.0)):
        data[f"raw_{column}"] = raw_close + offset
        data[f"price_{column}"] = raw_close + offset
    data["adj_close"] = raw_close
    data["dividend_raw"] = 0.0
    data["split_ratio"] = 1.0
    return MarketFrame(data)


class RecordingProvider:
    def __init__(self, frame: MarketFrame) -> None:
        self.frame = frame
        self.calls: list[tuple[str, date, date]] = []

    def fetch(self, symbol: str, start: date, end: date) -> MarketFrame:
        self.calls.append((symbol, start, end))
        return self.frame


class FailingProvider:
    def fetch(self, symbol: str, start: date, end: date) -> MarketFrame:
        raise RuntimeError("Yahoo is unavailable")


def seeded_catalog(tmp_path: Path, coverage_end: date) -> DataCatalog:
    catalog = DataCatalog(tmp_path)
    catalog.store("QQQ", market_frame_through(coverage_end.isoformat()))
    return catalog


def test_current_cache_performs_no_provider_request(tmp_path: Path) -> None:
    provider = RecordingProvider(frame=market_frame_through("2026-07-31"))
    catalog = seeded_catalog(tmp_path, coverage_end=date(2026, 7, 31))

    result = UpdateCoordinator(provider, catalog).ensure_current(date(2026, 8, 15))

    assert result.request_count == 0
    assert provider.calls == []


def test_failed_refresh_keeps_last_valid_parquet(tmp_path: Path) -> None:
    catalog = seeded_catalog(tmp_path, coverage_end=date(2026, 7, 30))
    original = catalog.path_for("QQQ")
    original_bytes = original.read_bytes()

    with pytest.raises(DataUpdateError):
        UpdateCoordinator(FailingProvider(), catalog).ensure_current(date(2026, 8, 15))

    assert original_bytes == catalog.path_for("QQQ").read_bytes()


def test_refreshes_with_five_cached_session_overlap(tmp_path: Path) -> None:
    catalog = seeded_catalog(tmp_path, coverage_end=date(2026, 7, 30))
    provider = RecordingProvider(market_frame_through("2026-07-31", start="2026-07-24"))

    result = UpdateCoordinator(provider, catalog).ensure_current(date(2026, 8, 15))

    assert provider.calls == [("QQQ", date(2026, 7, 24), date(2026, 7, 31))]
    assert result.request_count == 1
    assert catalog.coverage_end("QQQ") == date(2026, 7, 31)


def test_invalid_refresh_does_not_replace_cache(tmp_path: Path) -> None:
    catalog = seeded_catalog(tmp_path, coverage_end=date(2026, 7, 30))
    original_bytes = catalog.path_for("QQQ").read_bytes()
    invalid = market_frame_through("2026-07-31", start="2026-07-24").data.drop(
        columns=["split_ratio"]
    )

    with pytest.raises(DataUpdateError, match="split_ratio"):
        UpdateCoordinator(RecordingProvider(MarketFrame(invalid)), catalog).ensure_current(
            date(2026, 8, 15)
        )

    assert original_bytes == catalog.path_for("QQQ").read_bytes()
