from __future__ import annotations

import hashlib
import io
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from drawdown_lab.data.models import MarketFrame


class DataIntegrityError(RuntimeError):
    """Cached bytes no longer match their committed catalog lineage."""


@dataclass(frozen=True, slots=True)
class DataSnapshot:
    symbol: str
    provider: str
    fetched_at: datetime
    sha256: str
    actual_last_session: date
    policy_cutoff: date


class DataCatalog:
    """Parquet market-data cache with SQLite coverage metadata."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.market_dir = root / "market"
        self.database_path = root / "catalog.sqlite"
        self.market_dir.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS market_coverage (
                    symbol TEXT PRIMARY KEY,
                    coverage_end TEXT NOT NULL,
                    actual_last_session TEXT,
                    policy_cutoff TEXT,
                    provider TEXT,
                    fetched_at TEXT,
                    sha256 TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(market_coverage)").fetchall()
            }
            if "actual_last_session" not in columns:
                connection.execute(
                    "ALTER TABLE market_coverage ADD COLUMN actual_last_session TEXT"
                )
            if "policy_cutoff" not in columns:
                connection.execute("ALTER TABLE market_coverage ADD COLUMN policy_cutoff TEXT")
            if "provider" not in columns:
                connection.execute("ALTER TABLE market_coverage ADD COLUMN provider TEXT")
            if "fetched_at" not in columns:
                connection.execute("ALTER TABLE market_coverage ADD COLUMN fetched_at TEXT")
            if "sha256" not in columns:
                connection.execute("ALTER TABLE market_coverage ADD COLUMN sha256 TEXT")
            connection.execute(
                """
                UPDATE market_coverage
                SET actual_last_session = COALESCE(actual_last_session, coverage_end),
                    policy_cutoff = COALESCE(policy_cutoff, coverage_end),
                    provider = COALESCE(provider, 'legacy-local-cache'),
                    fetched_at = COALESCE(fetched_at, updated_at)
                """
            )
            legacy_rows = connection.execute(
                """
                SELECT symbol
                FROM market_coverage
                WHERE provider = 'legacy-local-cache'
                  AND (sha256 IS NULL OR length(trim(sha256)) <> 64)
                """
            ).fetchall()
            for (symbol,) in legacy_rows:
                path = self.path_for(str(symbol))
                if path.is_file():
                    connection.execute(
                        """
                        UPDATE market_coverage
                        SET sha256 = ?
                        WHERE symbol = ?
                          AND provider = 'legacy-local-cache'
                        """,
                        (hashlib.sha256(path.read_bytes()).hexdigest(), symbol),
                    )

    def path_for(self, symbol: str) -> Path:
        return self.market_dir / f"{symbol.replace('/', '_')}.parquet"

    def symbols(self) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT symbol FROM market_coverage ORDER BY symbol"
            ).fetchall()
        return tuple(row[0] for row in rows)

    def coverage_end(self, symbol: str) -> date | None:
        return self.actual_last_session(symbol)

    def actual_last_session(self, symbol: str) -> date | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT actual_last_session FROM market_coverage WHERE symbol = ?", (symbol,)
            ).fetchone()
        return date.fromisoformat(row[0]) if row is not None else None

    def policy_cutoff(self, symbol: str) -> date | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT policy_cutoff FROM market_coverage WHERE symbol = ?", (symbol,)
            ).fetchone()
        return date.fromisoformat(row[0]) if row is not None else None

    def is_complete_through(self, symbol: str, cutoff: date) -> bool:
        completed_cutoff = self.policy_cutoff(symbol)
        return completed_cutoff is not None and completed_cutoff >= cutoff

    def read(self, symbol: str) -> MarketFrame | None:
        path = self.path_for(symbol)
        if not path.exists():
            return None
        return MarketFrame(pd.read_parquet(path))

    def read_verified(self, symbol: str) -> tuple[MarketFrame, DataSnapshot]:
        """Parse and identify the exact same immutable byte snapshot."""

        path = self.path_for(symbol)
        row = self._snapshot_row(symbol)
        if row is None or not path.is_file():
            raise KeyError(symbol)
        content = path.read_bytes()
        snapshot = self._snapshot_from_bytes(symbol, row, content)
        try:
            frame = MarketFrame(pd.read_parquet(io.BytesIO(content)))
        except Exception as error:
            raise DataIntegrityError(
                f"Catalog bytes cannot be parsed for {symbol}"
            ) from error
        return frame, snapshot

    def snapshot(self, symbol: str) -> DataSnapshot:
        path = self.path_for(symbol)
        row = self._snapshot_row(symbol)
        if row is None or not path.is_file():
            raise KeyError(symbol)
        return self._snapshot_from_bytes(symbol, row, path.read_bytes())

    def _snapshot_row(self, symbol: str) -> tuple[object, ...] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT actual_last_session, policy_cutoff, provider, fetched_at, sha256
                FROM market_coverage
                WHERE symbol = ?
                """,
                (symbol,),
            ).fetchone()
        return tuple(row) if row is not None else None

    @staticmethod
    def _snapshot_from_bytes(
        symbol: str,
        row: tuple[object, ...],
        content: bytes,
    ) -> DataSnapshot:
        provider = str(row[2] or "").strip()
        fetched_at_text = str(row[3] or "").strip()
        expected_hash = str(row[4] or "").strip().lower()
        if not provider or not fetched_at_text or len(expected_hash) != 64:
            raise DataIntegrityError(f"Catalog lineage is incomplete for {symbol}")
        fetched_at = datetime.fromisoformat(fetched_at_text)
        if fetched_at.utcoffset() is None:
            raise DataIntegrityError(f"Catalog fetch time is not timezone-aware for {symbol}")
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != expected_hash:
            raise DataIntegrityError(f"Catalog hash mismatch for {symbol}")
        return DataSnapshot(
            symbol=symbol,
            provider=provider,
            fetched_at=fetched_at,
            sha256=actual_hash,
            actual_last_session=date.fromisoformat(str(row[0])),
            policy_cutoff=date.fromisoformat(str(row[1])),
        )

    def store(
        self,
        symbol: str,
        frame: MarketFrame,
        *,
        completed_cutoff: date | None = None,
        provider: str = "local-cache",
        fetched_at: datetime | None = None,
    ) -> None:
        normalized_provider = provider.strip()
        if not normalized_provider:
            raise ValueError("provider is required")
        normalized_fetched_at = fetched_at or datetime.now(UTC)
        if normalized_fetched_at.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")
        path = self.path_for(symbol)
        temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        backup_path = path.with_name(f".{path.name}.{uuid4().hex}.backup")
        actual_last_session = frame.data.index[-1].date()
        policy_cutoff = completed_cutoff or actual_last_session
        had_existing_file = path.exists()
        backup_created = False
        new_file_installed = False
        try:
            frame.data.to_parquet(temporary_path)
            digest = hashlib.sha256(temporary_path.read_bytes()).hexdigest()
            if had_existing_file:
                os.replace(path, backup_path)
                backup_created = True
            os.replace(temporary_path, path)
            new_file_installed = True
            self._commit_metadata(
                symbol,
                actual_last_session,
                policy_cutoff,
                provider=normalized_provider,
                fetched_at=normalized_fetched_at,
                sha256=digest,
            )
        except Exception:
            if new_file_installed and path.exists():
                path.unlink()
            if backup_created and backup_path.exists():
                os.replace(backup_path, path)
            raise
        else:
            if backup_created and backup_path.exists():
                backup_path.unlink()
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

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
        updated_at = fetched_at.isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO market_coverage (
                    symbol, coverage_end, actual_last_session, policy_cutoff,
                    provider, fetched_at, sha256, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    coverage_end = excluded.actual_last_session,
                    actual_last_session = excluded.actual_last_session,
                    policy_cutoff = excluded.policy_cutoff,
                    provider = excluded.provider,
                    fetched_at = excluded.fetched_at,
                    sha256 = excluded.sha256,
                    updated_at = excluded.updated_at
                """,
                (
                    symbol,
                    actual_last_session.isoformat(),
                    actual_last_session.isoformat(),
                    completed_cutoff.isoformat(),
                    provider,
                    fetched_at.isoformat(),
                    sha256,
                    updated_at,
                ),
            )
