from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2


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
                            'succeeded', 'failed', 'cancelled'
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
            self._migrate_completed_status(connection)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs(created_at, id)"
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO schema_migrations (version, applied_at)
                VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (SCHEMA_VERSION,),
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @staticmethod
    def _migrate_completed_status(connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
        ).fetchone()
        if row is None or "'completed'" not in str(row["sql"]):
            return
        connection.commit()
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE jobs_new (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN (
                        'queued', 'running', 'cancelling',
                        'succeeded', 'failed', 'cancelled'
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
            INSERT INTO jobs_new (
                id, kind, status, request_json, progress, total,
                cancellation_requested, result_id, error,
                created_at, updated_at, completed_at
            )
            SELECT
                id,
                kind,
                CASE status WHEN 'completed' THEN 'succeeded' ELSE status END,
                request_json,
                progress,
                total,
                cancellation_requested,
                result_id,
                error,
                created_at,
                updated_at,
                completed_at
            FROM jobs;
            DROP TABLE jobs;
            ALTER TABLE jobs_new RENAME TO jobs;
            COMMIT;
            """
        )
        connection.execute("PRAGMA foreign_keys = ON")
