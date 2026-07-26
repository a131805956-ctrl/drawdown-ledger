from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import drawdown_lab.data.catalog as catalog_module
import pandas as pd
import pytest
from drawdown_lab.data.catalog import DataCatalog
from drawdown_lab.data.models import MarketFrame
from drawdown_lab.data.update import DataUpdateError, UpdateCoordinator
from drawdown_lab.domain.instruments import INSTRUMENT_FAMILIES


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


class MetadataFailingCatalog(DataCatalog):
    fail_metadata_commit = False

    def _commit_metadata(
        self,
        symbol: str,
        actual_last_session: date,
        completed_cutoff: date,
        *,
        provider: str,
        fetched_at: datetime,
        sha256: str,
    ) -> None:
        if self.fail_metadata_commit:
            raise RuntimeError("metadata database is unavailable")
        super()._commit_metadata(
            symbol,
            actual_last_session,
            completed_cutoff,
            provider=provider,
            fetched_at=fetched_at,
            sha256=sha256,
        )


def seeded_catalog(tmp_path: Path, coverage_end: date) -> DataCatalog:
    catalog = DataCatalog(tmp_path)
    catalog.store("QQQ", market_frame_through(coverage_end.isoformat()))
    return catalog


def test_current_cache_performs_no_provider_request(tmp_path: Path) -> None:
    provider = RecordingProvider(frame=market_frame_through("2026-07-31"))
    catalog = seeded_catalog(tmp_path, coverage_end=date(2026, 7, 31))

    result = UpdateCoordinator(provider, catalog, symbols=("QQQ",)).ensure_current(
        date(2026, 8, 15)
    )

    assert result.request_count == 0
    assert provider.calls == []


def test_legacy_current_cache_migration_backfills_verifiable_lineage(
    tmp_path: Path,
) -> None:
    market_dir = tmp_path / "market"
    market_dir.mkdir(parents=True)
    parquet_path = market_dir / "QQQ.parquet"
    market_frame_through("2026-07-31").data.to_parquet(parquet_path)
    with sqlite3.connect(tmp_path / "catalog.sqlite") as connection:
        connection.execute(
            """
            CREATE TABLE market_coverage (
                symbol TEXT PRIMARY KEY,
                coverage_end TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO market_coverage (symbol, coverage_end, updated_at)
            VALUES ('QQQ', '2026-07-31', '2026-08-01T00:45:00+00:00')
            """
        )

    catalog = DataCatalog(tmp_path)
    provider = RecordingProvider(market_frame_through("2026-07-31"))
    result = UpdateCoordinator(provider, catalog, symbols=("QQQ",)).ensure_current(
        date(2026, 8, 15)
    )
    snapshot = catalog.snapshot("QQQ")

    assert result.request_count == 0
    assert provider.calls == []
    assert snapshot.provider == "legacy-local-cache"
    assert snapshot.fetched_at == datetime(2026, 8, 1, 0, 45, tzinfo=UTC)
    assert snapshot.sha256 == hashlib.sha256(parquet_path.read_bytes()).hexdigest()


def test_failed_refresh_keeps_last_valid_parquet(tmp_path: Path) -> None:
    catalog = seeded_catalog(tmp_path, coverage_end=date(2026, 7, 30))
    original = catalog.path_for("QQQ")
    original_bytes = original.read_bytes()

    with pytest.raises(DataUpdateError):
        UpdateCoordinator(FailingProvider(), catalog, symbols=("QQQ",)).ensure_current(
            date(2026, 8, 15)
        )

    assert original_bytes == catalog.path_for("QQQ").read_bytes()


def test_refreshes_with_five_cached_session_overlap(tmp_path: Path) -> None:
    catalog = seeded_catalog(tmp_path, coverage_end=date(2026, 7, 30))
    provider = RecordingProvider(market_frame_through("2026-07-31", start="2026-07-24"))

    result = UpdateCoordinator(provider, catalog, symbols=("QQQ",)).ensure_current(
        date(2026, 8, 15)
    )

    assert provider.calls == [("QQQ", date(2026, 7, 24), date(2026, 7, 31))]
    assert result.request_count == 1
    assert catalog.coverage_end("QQQ") == date(2026, 7, 31)
    assert catalog.snapshot("QQQ").provider.endswith("RecordingProvider")


def test_invalid_refresh_does_not_replace_cache(tmp_path: Path) -> None:
    catalog = seeded_catalog(tmp_path, coverage_end=date(2026, 7, 30))
    original_bytes = catalog.path_for("QQQ").read_bytes()
    invalid = market_frame_through("2026-07-31", start="2026-07-24").data.drop(
        columns=["split_ratio"]
    )

    with pytest.raises(DataUpdateError, match="split_ratio"):
        UpdateCoordinator(
            RecordingProvider(MarketFrame(invalid)), catalog, symbols=("QQQ",)
        ).ensure_current(date(2026, 8, 15))

    assert original_bytes == catalog.path_for("QQQ").read_bytes()


def test_saturday_cutoff_is_complete_when_actual_last_session_is_friday(tmp_path: Path) -> None:
    catalog = DataCatalog(tmp_path)
    provider = RecordingProvider(market_frame_through("2026-02-27", start="2026-02-17"))
    coordinator = UpdateCoordinator(provider, catalog, symbols=("QQQ",))

    first = coordinator.ensure_current(date(2026, 3, 1))
    second = coordinator.ensure_current(date(2026, 3, 1))

    assert first.request_count == 1
    assert catalog.policy_cutoff("QQQ") == date(2026, 2, 28)
    assert catalog.actual_last_session("QQQ") == date(2026, 2, 27)
    assert second.request_count == 0
    assert len(provider.calls) == 1


def test_metadata_failure_restores_exact_prior_parquet_bytes(tmp_path: Path) -> None:
    catalog = MetadataFailingCatalog(tmp_path)
    catalog.store("QQQ", market_frame_through("2026-07-30"))
    original_bytes = catalog.path_for("QQQ").read_bytes()
    catalog.fail_metadata_commit = True

    with pytest.raises(RuntimeError, match="metadata database"):
        catalog.store("QQQ", market_frame_through("2026-07-31"))

    assert catalog.path_for("QQQ").read_bytes() == original_bytes
    assert catalog.coverage_end("QQQ") == date(2026, 7, 30)


def test_failed_original_to_backup_move_leaves_prior_parquet_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = DataCatalog(tmp_path)
    catalog.store("QQQ", market_frame_through("2026-07-30"))
    path = catalog.path_for("QQQ")
    original_bytes = path.read_bytes()
    original_replace = catalog_module.os.replace

    def fail_original_backup_move(source: Path, destination: Path) -> None:
        if source == path:
            raise PermissionError("original cache is locked")
        original_replace(source, destination)

    monkeypatch.setattr(catalog_module.os, "replace", fail_original_backup_move)

    with pytest.raises(PermissionError, match="cache is locked"):
        catalog.store("QQQ", market_frame_through("2026-07-31"))

    assert path.read_bytes() == original_bytes
    assert catalog.coverage_end("QQQ") == date(2026, 7, 30)


def test_blank_catalog_uses_all_approved_registry_symbols(tmp_path: Path) -> None:
    provider = RecordingProvider(market_frame_through("2026-07-31"))

    result = UpdateCoordinator(provider, DataCatalog(tmp_path)).ensure_current(date(2026, 8, 15))

    approved = {item.symbol for family in INSTRUMENT_FAMILIES for item in family.instruments}
    assert result.request_count == len(approved)
    assert {symbol for symbol, _, _ in provider.calls} == approved


def test_catalog_snapshot_binds_provider_fetch_time_cutoff_and_file_hash(
    tmp_path: Path,
) -> None:
    catalog = DataCatalog(tmp_path)
    fetched_at = datetime(2026, 8, 1, 1, 30, tzinfo=UTC)
    catalog.store(
        "QQQ",
        market_frame_through("2026-07-31"),
        completed_cutoff=date(2026, 7, 31),
        provider="fixture-provider",
        fetched_at=fetched_at,
    )

    snapshot = catalog.snapshot("QQQ")

    assert snapshot.symbol == "QQQ"
    assert snapshot.provider == "fixture-provider"
    assert snapshot.fetched_at == fetched_at
    assert snapshot.policy_cutoff == date(2026, 7, 31)
    assert snapshot.actual_last_session == date(2026, 7, 31)
    assert snapshot.sha256 == hashlib.sha256(catalog.path_for("QQQ").read_bytes()).hexdigest()


def test_catalog_snapshot_rejects_parquet_tampering(tmp_path: Path) -> None:
    catalog = DataCatalog(tmp_path)
    catalog.store(
        "QQQ",
        market_frame_through("2026-07-31"),
        provider="fixture-provider",
    )
    with catalog.path_for("QQQ").open("ab") as stream:
        stream.write(b"tampered")

    with pytest.raises(RuntimeError, match="hash"):
        catalog.snapshot("QQQ")
