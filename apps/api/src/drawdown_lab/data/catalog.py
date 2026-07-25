from __future__ import annotations

import os
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from drawdown_lab.data.models import MarketFrame


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
            connection.execute(
                """
                UPDATE market_coverage
                SET actual_last_session = COALESCE(actual_last_session, coverage_end),
                    policy_cutoff = COALESCE(policy_cutoff, coverage_end)
                """
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

    def store(
        self, symbol: str, frame: MarketFrame, *, completed_cutoff: date | None = None
    ) -> None:
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
            if had_existing_file:
                os.replace(path, backup_path)
                backup_created = True
            os.replace(temporary_path, path)
            new_file_installed = True
            self._commit_metadata(symbol, actual_last_session, policy_cutoff)
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
        self, symbol: str, actual_last_session: date, completed_cutoff: date
    ) -> None:
        updated_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO market_coverage (
                    symbol, coverage_end, actual_last_session, policy_cutoff, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    coverage_end = excluded.actual_last_session,
                    actual_last_session = excluded.actual_last_session,
                    policy_cutoff = excluded.policy_cutoff,
                    updated_at = excluded.updated_at
                """,
                (
                    symbol,
                    actual_last_session.isoformat(),
                    actual_last_session.isoformat(),
                    completed_cutoff.isoformat(),
                    updated_at,
                ),
            )
