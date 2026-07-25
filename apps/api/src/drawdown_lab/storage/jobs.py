from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Any
from uuid import uuid4

from drawdown_lab.data.catalog import DataCatalog
from drawdown_lab.optimization.evaluator import (
    HistoricalOptimizationRequest,
    OptimizationCancelled,
    historical_request_from_payload,
    historical_request_to_payload,
    optimize_market_history,
)
from drawdown_lab.storage.database import Database

SCHEMA_VERSION = "1.0"


def deterministic_json(value: object) -> str:
    def default(item: object) -> str:
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        if isinstance(item, Decimal):
            return str(item)
        if isinstance(item, Enum):
            return str(item.value)
        raise TypeError(f"Object of type {type(item).__name__} is not JSON serializable")

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        default=default,
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


class JobNotFoundError(KeyError):
    pass


class InvalidJobTransitionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: str
    kind: str
    status: JobStatus
    request_json: str
    progress: int
    total: int
    cancellation_requested: bool
    result_id: str | None
    error: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


@dataclass(frozen=True, slots=True)
class ResultRecord:
    id: str
    job_id: str
    kind: str
    schema_version: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True, slots=True)
class ReportRecord:
    id: str
    result_id: str | None
    title: str
    export_status: str
    schema_version: str
    content: dict[str, Any]
    created_at: str


def _job_from_row(row: Any) -> JobRecord:
    return JobRecord(
        id=str(row["id"]),
        kind=str(row["kind"]),
        status=JobStatus(row["status"]),
        request_json=str(row["request_json"]),
        progress=int(row["progress"]),
        total=int(row["total"]),
        cancellation_requested=bool(row["cancellation_requested"]),
        result_id=str(row["result_id"]) if row["result_id"] is not None else None,
        error=str(row["error"]) if row["error"] is not None else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        completed_at=(
            str(row["completed_at"]) if row["completed_at"] is not None else None
        ),
    )


class JobStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        *,
        kind: str,
        request_payload: object,
        total: int,
    ) -> JobRecord:
        job_id = uuid4().hex
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, kind, status, request_json, progress, total,
                    cancellation_requested, created_at, updated_at
                ) VALUES (?, ?, 'queued', ?, 0, ?, 0, ?, ?)
                """,
                (
                    job_id,
                    kind,
                    deterministic_json(request_payload),
                    total,
                    timestamp,
                    timestamp,
                ),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> JobRecord:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        return _job_from_row(row)

    def start(self, job_id: str) -> JobRecord:
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'running', updated_at = ?
                WHERE id = ? AND status = 'queued' AND cancellation_requested = 0
                """,
                (timestamp, job_id),
            )
        return self.get(job_id)

    def request_cancel(self, job_id: str) -> JobRecord:
        timestamp = _now()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise JobNotFoundError(job_id)
            status = JobStatus(row["status"])
            if status in TERMINAL_STATUSES:
                raise InvalidJobTransitionError(
                    f"Cannot cancel a terminal {status.value} job"
                )
            connection.execute(
                """
                UPDATE jobs
                SET status = 'cancelling', cancellation_requested = 1, updated_at = ?
                WHERE id = ?
                """,
                (timestamp, job_id),
            )
        return self.get(job_id)

    def should_cancel(self, job_id: str) -> bool:
        record = self.get(job_id)
        return record.cancellation_requested or record.status is JobStatus.CANCELLING

    def update_progress(self, job_id: str, progress: int) -> JobRecord:
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET progress = MIN(?, total), updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (progress, timestamp, job_id),
            )
        return self.get(job_id)

    def mark_cancelled(self, job_id: str) -> JobRecord:
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'cancelled', cancellation_requested = 1,
                    result_id = NULL, updated_at = ?, completed_at = ?
                WHERE id = ? AND status IN ('queued', 'running', 'cancelling')
                """,
                (timestamp, timestamp, job_id),
            )
        return self.get(job_id)

    def fail(self, job_id: str, error: str) -> JobRecord:
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, cancellation_requested FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise JobNotFoundError(job_id)
            if bool(row["cancellation_requested"]) or row["status"] == "cancelling":
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'cancelled', error = NULL, result_id = NULL,
                        updated_at = ?, completed_at = ?
                    WHERE id = ?
                    """,
                    (timestamp, timestamp, job_id),
                )
            elif row["status"] == "running":
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'failed', error = ?, updated_at = ?, completed_at = ?
                    WHERE id = ?
                    """,
                    (error, timestamp, timestamp, job_id),
                )
        return self.get(job_id)

    def reconcile_active(self) -> tuple[JobRecord, ...]:
        """Cancel interrupted cancellations and safely requeue interrupted work."""

        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE jobs
                SET status = 'cancelled', result_id = NULL,
                    updated_at = ?, completed_at = ?
                WHERE status = 'cancelling' OR cancellation_requested = 1
                """,
                (timestamp, timestamp),
            )
            connection.execute(
                """
                UPDATE jobs
                SET status = 'queued', progress = 0, updated_at = ?
                WHERE status = 'running' AND cancellation_requested = 0
                """,
                (timestamp,),
            )
            rows = connection.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at, id"
            ).fetchall()
        return tuple(_job_from_row(row) for row in rows)

    def complete_with_result(
        self,
        job_id: str,
        *,
        kind: str,
        payload: dict[str, Any],
    ) -> JobRecord:
        """Atomically publish a complete result or honor a pending cancellation."""

        timestamp = _now()
        result_id = uuid4().hex
        report_id = uuid4().hex
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, cancellation_requested, total FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise JobNotFoundError(job_id)
            if bool(row["cancellation_requested"]) or row["status"] == "cancelling":
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'cancelled', result_id = NULL,
                        updated_at = ?, completed_at = ?
                    WHERE id = ?
                    """,
                    (timestamp, timestamp, job_id),
                )
            elif row["status"] != "running":
                raise InvalidJobTransitionError(
                    f"Cannot complete a {row['status']} job"
                )
            else:
                connection.execute(
                    """
                    INSERT INTO results (
                        id, job_id, kind, schema_version, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result_id,
                        job_id,
                        kind,
                        SCHEMA_VERSION,
                        deterministic_json(payload),
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO reports (
                        id, result_id, title, export_status,
                        schema_version, content_json, created_at
                    ) VALUES (?, ?, ?, 'not_yet_exported', ?, ?, ?)
                    """,
                    (
                        report_id,
                        result_id,
                        f"Optimization result {result_id}",
                        SCHEMA_VERSION,
                        deterministic_json(
                            {
                                "message": "Report has not yet been exported.",
                                "status": "not_yet_exported",
                                "result_id": result_id,
                                "optimization": payload,
                            }
                        ),
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'succeeded', progress = total, result_id = ?,
                        updated_at = ?, completed_at = ?
                    WHERE id = ?
                    """,
                    (result_id, timestamp, timestamp, job_id),
                )
        return self.get(job_id)

    def result_count_for_job(self, job_id: str) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM results WHERE job_id = ?", (job_id,)
            ).fetchone()
        return int(row["count"])

    def result_count(self) -> int:
        with self.database.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM results").fetchone()
        return int(row["count"])

    def list_results(self) -> tuple[ResultRecord, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM results ORDER BY created_at DESC, id"
            ).fetchall()
        return tuple(self._result_from_row(row) for row in rows)

    def get_result(self, result_id: str) -> ResultRecord:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM results WHERE id = ?", (result_id,)
            ).fetchone()
        if row is None:
            raise KeyError(result_id)
        return self._result_from_row(row)

    def list_reports(self) -> tuple[ReportRecord, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reports ORDER BY created_at DESC, id"
            ).fetchall()
        return tuple(self._report_from_row(row) for row in rows)

    def get_report(self, report_id: str) -> ReportRecord:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM reports WHERE id = ?", (report_id,)
            ).fetchone()
        if row is None:
            raise KeyError(report_id)
        return self._report_from_row(row)

    @staticmethod
    def _result_from_row(row: Any) -> ResultRecord:
        return ResultRecord(
            id=str(row["id"]),
            job_id=str(row["job_id"]),
            kind=str(row["kind"]),
            schema_version=str(row["schema_version"]),
            payload=json.loads(row["payload_json"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _report_from_row(row: Any) -> ReportRecord:
        return ReportRecord(
            id=str(row["id"]),
            result_id=str(row["result_id"]) if row["result_id"] is not None else None,
            title=str(row["title"]),
            export_status=str(row["export_status"]),
            schema_version=str(row["schema_version"]),
            content=json.loads(row["content_json"]),
            created_at=str(row["created_at"]),
        )


class JobService:
    """Run optimizations in deterministic batches with cancellation checkpoints."""

    def __init__(
        self,
        store: JobStore,
        data_catalog: DataCatalog,
        *,
        max_workers: int = 1,
        batch_size: int = 25,
    ) -> None:
        if max_workers <= 0 or batch_size <= 0:
            raise ValueError("Job executor settings must be positive")
        self.store = store
        self.data_catalog = data_catalog
        self.batch_size = batch_size
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="drawdown-optimizer",
        )

    def submit(
        self,
        request: HistoricalOptimizationRequest,
    ) -> JobRecord:
        persisted = {
            "schema_version": SCHEMA_VERSION,
            "request": historical_request_to_payload(request),
        }
        vector_count = len(request.ratio_search.vectors(len(request.depths)))
        total = vector_count * request.walk_forward.n_splits
        if request.synthetic_stress.enabled:
            total += vector_count
        job = self.store.create(
            kind="optimization",
            request_payload=persisted,
            total=total,
        )
        self.executor.submit(self._run, job.id, request)
        return job

    def reconcile(self) -> None:
        for job in self.store.reconcile_active():
            try:
                persisted = json.loads(job.request_json)
                request = historical_request_from_payload(persisted["request"])
            except Exception as error:
                self.store.start(job.id)
                self.store.fail(
                    job.id,
                    f"PersistedRequestError: {error}",
                )
                continue
            self.executor.submit(self._run, job.id, request)

    def _run(
        self,
        job_id: str,
        request: HistoricalOptimizationRequest,
    ) -> None:
        try:
            record = self.store.start(job_id)
            if record.status is JobStatus.CANCELLING or record.cancellation_requested:
                self.store.mark_cancelled(job_id)
                return
            prototype = self.data_catalog.read(request.prototype_symbol)
            traded = self.data_catalog.read(request.target_symbol)
            if prototype is None or traded is None:
                raise RuntimeError("Trusted market cache disappeared before evaluation")

            def on_batch(completed: int, _: int) -> bool:
                self.store.update_progress(job_id, completed)
                return not self.store.should_cancel(job_id)

            result = optimize_market_history(
                request,
                prototype,
                traded,
                evaluation_batch_size=self.batch_size,
                on_batch=on_batch,
            )
            self.store.complete_with_result(
                job_id,
                kind="optimization",
                payload=asdict(result),
            )
        except OptimizationCancelled:
            self.store.mark_cancelled(job_id)
        except Exception as error:
            try:
                if self.store.should_cancel(job_id):
                    self.store.mark_cancelled(job_id)
                else:
                    self.store.fail(job_id, f"{type(error).__name__}: {error}")
            except Exception:
                return

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)
