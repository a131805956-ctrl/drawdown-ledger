from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1


class Database:
    """Small connection factory with an idempotent SQLite schema migration."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN (
                            'queued', 'running', 'cancelling',
                            'completed', 'failed', 'cancelled'
                        )
                    ),
                    request_json TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress >= 0),
                    total INTEGER NOT NULL CHECK (total >= 0),
                    cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK (
                        cancellation_requested IN (0, 1)
                    ),
                    result_id TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS results (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id),
                    kind TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY,
                    result_id TEXT REFERENCES results(id),
                    title TEXT NOT NULL,
                    export_status TEXT NOT NULL CHECK (
                        export_status IN ('not_yet_exported', 'exported')
                    ),
                    schema_version TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs(created_at, id);
                CREATE INDEX IF NOT EXISTS results_created_at_idx ON results(created_at, id);
                CREATE INDEX IF NOT EXISTS reports_created_at_idx ON reports(created_at, id);
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO schema_migrations (version, applied_at)
                VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (SCHEMA_VERSION,),
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
