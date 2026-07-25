from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
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


def _lease_deadline(lease_seconds: float) -> str:
    if lease_seconds <= 0:
        raise ValueError("Lease duration must be positive")
    return (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()


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
    lease_owner: str | None
    lease_expires_at: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


@dataclass(frozen=True, slots=True)
class ResultRecord:
    id: str
    job_id: str
    kind: str
    schema_version: str
    payload: object
    raw_json: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ReportRecord:
    id: str
    result_id: str | None
    title: str
    export_status: str
    schema_version: str
    content: object
    raw_json: str
    created_at: str


@dataclass(frozen=True, slots=True)
class RejectionRecord:
    id: str
    kind: str
    request_json: str
    reason: str
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
        lease_owner=(
            str(row["lease_owner"]) if row["lease_owner"] is not None else None
        ),
        lease_expires_at=(
            str(row["lease_expires_at"])
            if row["lease_expires_at"] is not None
            else None
        ),
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

    def record_rejection(
        self,
        *,
        kind: str,
        request_payload: object,
        reason: str,
    ) -> RejectionRecord:
        rejection = RejectionRecord(
            id=uuid4().hex,
            kind=kind,
            request_json=deterministic_json(request_payload),
            reason=reason,
            created_at=_now(),
        )
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO request_rejections (
                    id, kind, request_json, reason, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    rejection.id,
                    rejection.kind,
                    rejection.request_json,
                    rejection.reason,
                    rejection.created_at,
                ),
            )
        return rejection

    def latest_rejection(self) -> RejectionRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM request_rejections
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return RejectionRecord(
            id=str(row["id"]),
            kind=str(row["kind"]),
            request_json=str(row["request_json"]),
            reason=str(row["reason"]),
            created_at=str(row["created_at"]),
        )

    def get(self, job_id: str) -> JobRecord:
        with self.database.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        return _job_from_row(row)

    def claim(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: float,
    ) -> JobRecord | None:
        if not worker_id:
            raise ValueError("Worker id must not be empty")
        timestamp = _now()
        lease_expires_at = _lease_deadline(lease_seconds)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'running', lease_owner = ?, lease_expires_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND cancellation_requested = 0
                  AND (
                      status = 'queued'
                      OR (
                          status = 'running'
                          AND (
                              lease_expires_at IS NULL
                              OR lease_expires_at <= ?
                          )
                      )
                  )
                """,
                (
                    worker_id,
                    lease_expires_at,
                    timestamp,
                    job_id,
                    timestamp,
                ),
            )
            if cursor.rowcount == 0:
                row = connection.execute(
                    "SELECT id FROM jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                if row is None:
                    raise JobNotFoundError(job_id)
                return None
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        return _job_from_row(row)

    def start(
        self,
        job_id: str,
        *,
        worker_id: str = "manual-worker",
        lease_seconds: float = 30.0,
    ) -> JobRecord:
        claimed = self.claim(
            job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
        if claimed is None:
            with self.database.connect() as connection:
                self._raise_transition_error(connection, job_id, "start")
        assert claimed is not None
        return claimed

    def request_cancel(self, job_id: str) -> JobRecord:
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = CASE
                        WHEN status = 'queued' THEN 'cancelled'
                        ELSE 'cancelling'
                    END,
                    cancellation_requested = 1,
                    lease_owner = CASE
                        WHEN status = 'queued' THEN NULL
                        ELSE lease_owner
                    END,
                    lease_expires_at = CASE
                        WHEN status = 'queued' THEN NULL
                        ELSE lease_expires_at
                    END,
                    updated_at = ?,
                    completed_at = CASE
                        WHEN status = 'queued' THEN ?
                        ELSE completed_at
                    END
                WHERE id = ?
                  AND status IN ('queued', 'running')
                  AND cancellation_requested = 0
                """,
                (timestamp, timestamp, job_id),
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT status FROM jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                if row is None:
                    raise JobNotFoundError(job_id)
                status = JobStatus(row["status"])
                if status is not JobStatus.CANCELLING:
                    raise InvalidJobTransitionError(
                        f"Cannot cancel a {status.value} job"
                    )
            self._delete_job_artifacts(connection, job_id)
        return self.get(job_id)

    def should_cancel(self, job_id: str) -> bool:
        record = self.get(job_id)
        return record.cancellation_requested or record.status is JobStatus.CANCELLING

    def update_progress(
        self,
        job_id: str,
        progress: int,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 30.0,
    ) -> JobRecord:
        timestamp = _now()
        lease_expires_at = _lease_deadline(lease_seconds)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE jobs
                SET progress = MIN(?, total), updated_at = ?,
                    lease_expires_at = ?
                WHERE id = ? AND status = 'running'
                  AND (? IS NULL OR lease_owner = ?)
                """,
                (
                    progress,
                    timestamp,
                    lease_expires_at,
                    job_id,
                    worker_id,
                    worker_id,
                ),
            )
            if cursor.rowcount != 1:
                self._raise_transition_error(connection, job_id, "update")
        return self.get(job_id)

    def mark_cancelled(
        self,
        job_id: str,
        *,
        worker_id: str | None = None,
    ) -> JobRecord:
        timestamp = _now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'cancelled', cancellation_requested = 1,
                    result_id = NULL, error = NULL,
                    lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = ?, completed_at = ?
                WHERE id = ? AND status IN ('queued', 'running', 'cancelling')
                  AND (? IS NULL OR lease_owner = ?)
                """,
                (timestamp, timestamp, job_id, worker_id, worker_id),
            )
            if cursor.rowcount != 1:
                self._raise_transition_error(connection, job_id, "cancel")
            self._delete_job_artifacts(connection, job_id)
        return self.get(job_id)

    def fail(
        self,
        job_id: str,
        error: str,
        *,
        worker_id: str | None = None,
    ) -> JobRecord:
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
                cursor = connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'cancelled', error = NULL, result_id = NULL,
                        lease_owner = NULL, lease_expires_at = NULL,
                        updated_at = ?, completed_at = ?
                    WHERE id = ?
                      AND status IN ('running', 'cancelling')
                      AND (? IS NULL OR lease_owner = ?)
                    """,
                    (timestamp, timestamp, job_id, worker_id, worker_id),
                )
                if cursor.rowcount != 1:
                    self._raise_transition_error(connection, job_id, "fail")
                self._delete_job_artifacts(connection, job_id)
            elif row["status"] == "running":
                cursor = connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'failed', error = ?,
                        lease_owner = NULL, lease_expires_at = NULL,
                        updated_at = ?, completed_at = ?
                    WHERE id = ?
                      AND status = 'running'
                      AND cancellation_requested = 0
                      AND (? IS NULL OR lease_owner = ?)
                    """,
                    (
                        error,
                        timestamp,
                        timestamp,
                        job_id,
                        worker_id,
                        worker_id,
                    ),
                )
                if cursor.rowcount != 1:
                    self._raise_transition_error(connection, job_id, "fail")
                self._delete_job_artifacts(connection, job_id)
            else:
                raise InvalidJobTransitionError(
                    f"Cannot fail a {row['status']} job"
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
                SET status = 'cancelled', result_id = NULL, error = NULL,
                    lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = ?, completed_at = ?
                WHERE status = 'cancelling' OR cancellation_requested = 1
                """,
                (timestamp, timestamp),
            )
            self._delete_contradictory_artifacts(connection)
            rows = connection.execute(
                """
                SELECT *
                FROM jobs
                WHERE status = 'queued'
                   OR (
                       status = 'running'
                       AND cancellation_requested = 0
                       AND (
                           lease_expires_at IS NULL
                           OR lease_expires_at <= ?
                       )
                   )
                ORDER BY created_at, id
                """,
                (timestamp,),
            ).fetchall()
        return tuple(_job_from_row(row) for row in rows)

    def complete_with_result(
        self,
        job_id: str,
        *,
        kind: str,
        payload: dict[str, Any],
        worker_id: str | None = None,
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
                cursor = connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'cancelled', result_id = NULL,
                        error = NULL, lease_owner = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?, completed_at = ?
                    WHERE id = ?
                      AND status IN ('running', 'cancelling')
                      AND (? IS NULL OR lease_owner = ?)
                    """,
                    (timestamp, timestamp, job_id, worker_id, worker_id),
                )
                if cursor.rowcount != 1:
                    self._raise_transition_error(connection, job_id, "complete")
                self._delete_job_artifacts(connection, job_id)
            elif row["status"] != "running":
                raise InvalidJobTransitionError(
                    f"Cannot complete a {row['status']} job"
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE jobs
                    SET status = 'succeeded', progress = total, result_id = ?,
                        error = NULL, lease_owner = NULL,
                        lease_expires_at = NULL,
                        updated_at = ?, completed_at = ?
                    WHERE id = ?
                      AND status = 'running'
                      AND cancellation_requested = 0
                      AND (? IS NULL OR lease_owner = ?)
                    """,
                    (
                        result_id,
                        timestamp,
                        timestamp,
                        job_id,
                        worker_id,
                        worker_id,
                    ),
                )
                if cursor.rowcount != 1:
                    self._raise_transition_error(connection, job_id, "complete")
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
        return self.get(job_id)

    @staticmethod
    def _raise_transition_error(
        connection: Any,
        job_id: str,
        action: str,
    ) -> None:
        row = connection.execute(
            "SELECT status FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        raise InvalidJobTransitionError(
            f"Cannot {action} a {row['status']} job"
        )

    @staticmethod
    def _delete_job_artifacts(connection: Any, job_id: str) -> None:
        connection.execute(
            """
            DELETE FROM reports
            WHERE result_id IN (
                SELECT id FROM results WHERE job_id = ?
            )
            """,
            (job_id,),
        )
        connection.execute(
            "DELETE FROM results WHERE job_id = ?",
            (job_id,),
        )

    @staticmethod
    def _delete_contradictory_artifacts(connection: Any) -> None:
        connection.execute(
            """
            DELETE FROM reports
            WHERE result_id IN (
                SELECT results.id
                FROM results
                JOIN jobs ON jobs.id = results.job_id
                WHERE jobs.status <> 'succeeded'
                   OR jobs.result_id IS NULL
                   OR jobs.result_id <> results.id
            )
            """
        )
        connection.execute(
            """
            DELETE FROM results
            WHERE id IN (
                SELECT results.id
                FROM results
                JOIN jobs ON jobs.id = results.job_id
                WHERE jobs.status <> 'succeeded'
                   OR jobs.result_id IS NULL
                   OR jobs.result_id <> results.id
            )
            """
        )

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
        raw_json = str(row["payload_json"])
        return ResultRecord(
            id=str(row["id"]),
            job_id=str(row["job_id"]),
            kind=str(row["kind"]),
            schema_version=str(row["schema_version"]),
            payload=json.loads(raw_json),
            raw_json=raw_json,
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _report_from_row(row: Any) -> ReportRecord:
        raw_json = str(row["content_json"])
        return ReportRecord(
            id=str(row["id"]),
            result_id=str(row["result_id"]) if row["result_id"] is not None else None,
            title=str(row["title"]),
            export_status=str(row["export_status"]),
            schema_version=str(row["schema_version"]),
            content=json.loads(raw_json),
            raw_json=raw_json,
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
        lease_seconds: float = 60.0,
    ) -> None:
        if max_workers <= 0 or batch_size <= 0 or lease_seconds <= 0:
            raise ValueError("Job executor settings must be positive")
        self.store = store
        self.data_catalog = data_catalog
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds
        self.worker_id = uuid4().hex
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
        vector_count = request.ratio_search.candidate_count(len(request.depths))
        total = vector_count * request.walk_forward.n_splits * 2
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
                claimed = self.store.claim(
                    job.id,
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds,
                )
                if claimed is not None:
                    self.store.fail(
                        job.id,
                        f"PersistedRequestError: {error}",
                        worker_id=self.worker_id,
                    )
                continue
            self.executor.submit(self._run, job.id, request)

    def _run(
        self,
        job_id: str,
        request: HistoricalOptimizationRequest,
    ) -> None:
        try:
            record = self.store.claim(
                job_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if record is None:
                return
            if record.status is JobStatus.CANCELLING or record.cancellation_requested:
                self.store.mark_cancelled(job_id, worker_id=self.worker_id)
                return
            prototype = self.data_catalog.read(request.prototype_symbol)
            traded = self.data_catalog.read(request.target_symbol)
            if prototype is None or traded is None:
                raise RuntimeError("Trusted market cache disappeared before evaluation")

            def on_batch(completed: int, _: int) -> bool:
                self.store.update_progress(
                    job_id,
                    completed,
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds,
                )
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
                worker_id=self.worker_id,
            )
        except OptimizationCancelled:
            self.store.mark_cancelled(job_id, worker_id=self.worker_id)
        except Exception as error:
            try:
                if self.store.should_cancel(job_id):
                    self.store.mark_cancelled(job_id, worker_id=self.worker_id)
                else:
                    self.store.fail(
                        job_id,
                        f"{type(error).__name__}: {error}",
                        worker_id=self.worker_id,
                    )
            except Exception:
                return

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)
