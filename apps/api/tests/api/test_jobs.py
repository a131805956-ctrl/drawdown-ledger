from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event, Lock, Thread

import pytest
from drawdown_lab.api.app import Settings, create_app
from drawdown_lab.api.schemas import OptimizationCreateRequest
from drawdown_lab.optimization.evaluator import (
    historical_request_from_payload,
    historical_request_to_payload,
)
from drawdown_lab.storage import jobs as jobs_module
from drawdown_lab.storage.database import Database
from drawdown_lab.storage.jobs import (
    InvalidJobTransitionError,
    JobStatus,
    JobStore,
)
from fastapi.testclient import TestClient

from apps.api.tests.api.test_trusted_optimizer import _request, _seed


def _wait(
    client: TestClient,
    job_id: str,
    terminal: set[str] = {"succeeded", "failed", "cancelled"},
) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        row = client.get(f"/api/v1/jobs/{job_id}").json()
        if row["status"] in terminal:
            return row
        time.sleep(0.005)
    raise AssertionError(f"job {job_id} did not terminate")


def _domain_request() -> object:
    request = OptimizationCreateRequest.model_validate(_request())
    return request.to_domain(prototype_symbol="QQQ", target_leverage=3)


def test_historical_request_json_round_trip_is_complete_and_reconstructable() -> None:
    request = _domain_request()

    persisted = historical_request_to_payload(request)
    restored = historical_request_from_payload(json.loads(json.dumps(persisted)))

    assert restored == request
    assert persisted["family_id"] == "nasdaq-100"
    assert persisted["target_symbol"] == "TQQQ"
    assert persisted["strategy"]["initial_cash"] == "1000.00"
    assert persisted["walk_forward"]["n_splits"] == 2


@pytest.mark.parametrize("prior_status", ["queued", "running"])
def test_app_restart_recovers_persisted_available_job(
    tmp_path: Path,
    prior_status: str,
) -> None:
    settings = Settings(
        database_path=tmp_path / "drawdown.sqlite",
        data_root=tmp_path / "data",
    )
    assert settings.data_root is not None
    _seed(settings.data_root)
    store = JobStore(Database(settings.database_path))
    request = _domain_request()
    job = store.create(
        kind="optimization",
        request_payload={
            "schema_version": "1.0",
            "request": historical_request_to_payload(request),
        },
        total=4,
    )
    if prior_status == "running":
        store.start(job.id, worker_id="dead-worker", lease_seconds=30)
        with store.database.connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET lease_expires_at = ?
                WHERE id = ?
                """,
                (
                    (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                    job.id,
                ),
            )

    with TestClient(create_app(settings)) as client:
        terminal = _wait(client, job.id)

    assert terminal["status"] == "succeeded"
    assert terminal["progress"] == 4
    assert terminal["result_id"] is not None


def test_reconciliation_never_reclaims_a_live_running_lease(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "drawdown.sqlite",
        data_root=tmp_path / "data",
    )
    store = JobStore(Database(settings.database_path))
    job = store.create(kind="optimization", request_payload={}, total=1)
    running = store.start(
        job.id,
        worker_id="live-worker",
        lease_seconds=120,
    )

    with TestClient(create_app(settings)):
        observed = store.get(job.id)

    assert running.lease_owner == "live-worker"
    assert observed.status is JobStatus.RUNNING
    assert observed.lease_owner == "live-worker"


def test_two_app_instances_claim_one_persisted_job_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        database_path=tmp_path / "drawdown.sqlite",
        data_root=tmp_path / "data",
        job_batch_size=1,
    )
    assert settings.data_root is not None
    _seed(settings.data_root)
    store = JobStore(Database(settings.database_path))
    request = _domain_request()
    job = store.create(
        kind="optimization",
        request_payload={
            "schema_version": "1.0",
            "request": historical_request_to_payload(request),
        },
        total=4,
    )
    evaluator_entered = Event()
    release_evaluator = Event()
    call_lock = Lock()
    call_count = 0
    real_optimize = jobs_module.optimize_market_history

    def counted_optimize(*args: object, **kwargs: object) -> object:
        nonlocal call_count
        with call_lock:
            call_count += 1
            evaluator_entered.set()
        assert release_evaluator.wait(timeout=5)
        return real_optimize(*args, **kwargs)

    monkeypatch.setattr(jobs_module, "optimize_market_history", counted_optimize)
    first = TestClient(create_app(settings))
    second = TestClient(create_app(settings))
    try:
        first.__enter__()
        assert evaluator_entered.wait(timeout=5)
        second.__enter__()
        release_evaluator.set()
        terminal = _wait(first, job.id)
    finally:
        release_evaluator.set()
        second.__exit__(None, None, None)
        first.__exit__(None, None, None)

    assert terminal["status"] == "succeeded"
    assert call_count == 1
    assert store.result_count_for_job(job.id) == 1


def test_expired_worker_cannot_publish_after_another_worker_reclaims_job(
    tmp_path: Path,
) -> None:
    store = JobStore(Database(tmp_path / "reclaim.sqlite"))
    job = store.create(kind="optimization", request_payload={}, total=1)
    store.start(job.id, worker_id="old-worker", lease_seconds=30)
    with store.database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET lease_expires_at = ? WHERE id = ?",
            (
                (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                job.id,
            ),
        )

    reclaimed = store.claim(
        job.id,
        worker_id="new-worker",
        lease_seconds=30,
    )
    assert reclaimed is not None
    assert reclaimed.lease_owner == "new-worker"
    with pytest.raises(InvalidJobTransitionError, match="Cannot complete"):
        store.complete_with_result(
            job.id,
            kind="optimization",
            payload={"worker": "old"},
            worker_id="old-worker",
        )

    terminal = store.complete_with_result(
        job.id,
        kind="optimization",
        payload={"worker": "new"},
        worker_id="new-worker",
    )
    assert terminal.status is JobStatus.SUCCEEDED
    assert store.get_result(terminal.result_id or "").payload == {"worker": "new"}


def test_progress_heartbeat_renews_only_the_claiming_workers_lease(
    tmp_path: Path,
) -> None:
    store = JobStore(Database(tmp_path / "heartbeat.sqlite"))
    job = store.create(kind="optimization", request_payload={}, total=2)
    running = store.start(job.id, worker_id="owner", lease_seconds=1)
    assert running.lease_expires_at is not None

    heartbeat = store.update_progress(
        job.id,
        1,
        worker_id="owner",
        lease_seconds=120,
    )

    assert heartbeat.progress == 1
    assert heartbeat.lease_owner == "owner"
    assert heartbeat.lease_expires_at is not None
    assert heartbeat.lease_expires_at > running.lease_expires_at
    with pytest.raises(InvalidJobTransitionError, match="Cannot update"):
        store.update_progress(
            job.id,
            2,
            worker_id="intruder",
            lease_seconds=120,
        )


def test_app_restart_turns_cancelling_job_into_cancelled_without_result(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=tmp_path / "drawdown.sqlite",
        data_root=tmp_path / "data",
    )
    store = JobStore(Database(settings.database_path))
    request = _domain_request()
    job = store.create(
        kind="optimization",
        request_payload={
            "schema_version": "1.0",
            "request": historical_request_to_payload(request),
        },
        total=4,
    )
    store.request_cancel(job.id)

    with TestClient(create_app(settings)) as client:
        reconciled = client.get(f"/api/v1/jobs/{job.id}").json()

    assert reconciled["status"] == "cancelled"
    assert reconciled["result_id"] is None
    assert store.result_count_for_job(job.id) == 0


def test_cancel_request_wins_atomic_fail_race(tmp_path: Path) -> None:
    store = JobStore(Database(tmp_path / "drawdown.sqlite"))
    job = store.create(kind="optimization", request_payload={}, total=1)
    store.start(job.id)
    store.request_cancel(job.id)

    terminal = store.fail(job.id, "worker failed during cancellation")

    assert terminal.status is JobStatus.CANCELLED
    assert terminal.error is None


def test_cancelling_an_unclaimed_queued_job_is_immediately_terminal(
    tmp_path: Path,
) -> None:
    store = JobStore(Database(tmp_path / "queued-cancel.sqlite"))
    job = store.create(kind="optimization", request_payload={}, total=1)

    terminal = store.request_cancel(job.id)

    assert terminal.status is JobStatus.CANCELLED
    assert terminal.completed_at is not None
    assert terminal.result_id is None


@pytest.mark.parametrize("worker_terminal", ["complete", "fail"])
def test_cancel_and_worker_terminal_transition_are_atomic(
    tmp_path: Path,
    worker_terminal: str,
) -> None:
    """A barrier-started race must end in one coherent terminal state."""

    store = JobStore(Database(tmp_path / f"{worker_terminal}.sqlite"))
    barrier = Barrier(3)
    errors: list[Exception] = []
    job = store.create(kind="optimization", request_payload={}, total=1)
    store.start(job.id)

    def cancel() -> None:
        try:
            barrier.wait()
            store.request_cancel(job.id)
        except Exception as error:
            errors.append(error)

    def finish() -> None:
        try:
            barrier.wait()
            if worker_terminal == "complete":
                store.complete_with_result(
                    job.id,
                    kind="optimization",
                    payload={"schema_version": "1.0"},
                )
            else:
                store.fail(job.id, "worker failed")
        except Exception as error:
            errors.append(error)

    cancel_thread = Thread(target=cancel)
    finish_thread = Thread(target=finish)
    cancel_thread.start()
    finish_thread.start()
    barrier.wait()
    cancel_thread.join()
    finish_thread.join()

    terminal = store.get(job.id)
    assert terminal.status in {
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }
    if terminal.status is JobStatus.SUCCEEDED:
        assert worker_terminal == "complete"
        assert terminal.result_id is not None
        assert store.result_count_for_job(job.id) == 1
    else:
        assert terminal.result_id is None
        assert store.result_count_for_job(job.id) == 0
    assert all(
        error.__class__.__name__ == "InvalidJobTransitionError" for error in errors
    )


def test_reconciliation_removes_results_and_reports_from_non_succeeded_jobs(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "contradiction.sqlite")
    store = JobStore(database)
    job = store.create(kind="optimization", request_payload={}, total=1)
    store.start(job.id)
    succeeded = store.complete_with_result(
        job.id,
        kind="optimization",
        payload={"schema_version": "1.0"},
    )
    assert succeeded.result_id is not None
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE jobs
            SET status = 'cancelled', result_id = NULL, cancellation_requested = 1
            WHERE id = ?
            """,
            (job.id,),
        )

    store.reconcile_active()

    with database.connect() as connection:
        result_count = connection.execute(
            "SELECT COUNT(*) FROM results WHERE job_id = ?",
            (job.id,),
        ).fetchone()[0]
        report_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM reports
            WHERE result_id = ?
            """,
            (succeeded.result_id,),
        ).fetchone()[0]
    assert result_count == 0
    assert report_count == 0


def test_version_one_completed_job_migrates_to_succeeded(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN (
                        'queued', 'running', 'cancelling',
                        'completed', 'failed', 'cancelled'
                    )
                ),
                request_json TEXT NOT NULL,
                progress INTEGER NOT NULL,
                total INTEGER NOT NULL,
                cancellation_requested INTEGER NOT NULL,
                result_id TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO jobs VALUES (
                'legacy-job', 'optimization', 'completed', '{}',
                1, 1, 0, 'result-1', NULL,
                '2020-01-01T00:00:00Z', '2020-01-01T00:00:00Z',
                '2020-01-01T00:00:00Z'
            )
            """
        )

    record = JobStore(Database(path)).get("legacy-job")

    assert record.status is JobStatus.SUCCEEDED


def test_cancelled_real_job_never_publishes_partial_formal_result(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "drawdown.sqlite",
        data_root=tmp_path / "data",
        job_batch_size=1,
    )
    assert settings.data_root is not None
    _seed(settings.data_root)
    payload = _request()
    payload["ratio_search"] = {
        "minimum_basis_points": 0,
        "maximum_basis_points": 10000,
        "step_basis_points": 100,
        "monotone": True,
    }
    app = create_app(settings)
    with TestClient(app) as client:
        accepted = client.post("/api/v1/optimizations", json=payload).json()
        cancellation = client.post(f"/api/v1/jobs/{accepted['job_id']}/cancel")
        terminal = _wait(client, accepted["job_id"])

        assert cancellation.status_code == 202
        assert terminal["status"] == "cancelled"
        assert terminal["result_id"] is None
        assert client.get("/api/v1/results").json()["results"] == []
        assert app.state.job_store.result_count_for_job(accepted["job_id"]) == 0


def test_insufficient_events_succeeds_as_exploration_only(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "drawdown.sqlite",
        data_root=tmp_path / "data",
    )
    assert settings.data_root is not None
    _seed(settings.data_root)
    payload = _request()
    payload["minimum_independent_episodes"] = 5
    with TestClient(create_app(settings)) as client:
        accepted = client.post("/api/v1/optimizations", json=payload).json()
        terminal = _wait(client, accepted["job_id"])
        result = client.get(f"/api/v1/results/{terminal['result_id']}").json()

    assert terminal["status"] == "succeeded"
    assert result["payload"]["mode"] == "exploration_only"
    assert result["payload"]["recommendations"] == []
