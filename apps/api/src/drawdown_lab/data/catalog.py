from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timezone
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
                    updated_at TEXT NOT NULL
                )
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
        with self._connect() as connection:
            row = connection.execute(
                "SELECT coverage_end FROM market_coverage WHERE symbol = ?", (symbol,)
            ).fetchone()
        return date.fromisoformat(row[0]) if row is not None else None

    def read(self, symbol: str) -> MarketFrame | None:
        path = self.path_for(symbol)
        if not path.exists():
            return None
        return MarketFrame(pd.read_parquet(path))

    def store(self, symbol: str, frame: MarketFrame) -> None:
        path = self.path_for(symbol)
        temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            frame.data.to_parquet(temporary_path)
            os.replace(temporary_path, path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

        coverage_end = frame.data.index[-1].date().isoformat()
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO market_coverage (symbol, coverage_end, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    coverage_end = excluded.coverage_end,
                    updated_at = excluded.updated_at
                """,
                (symbol, coverage_end, updated_at),
            )
