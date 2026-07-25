from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest
from drawdown_lab.api.app import Settings, create_app
from drawdown_lab.api.schemas import OptimizationCreateRequest
from drawdown_lab.optimization.evaluator import (
    historical_request_from_payload,
    historical_request_to_payload,
)
from drawdown_lab.storage.database import Database
from drawdown_lab.storage.jobs import JobStatus, JobStore
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
def test_app_restart_requeues_persisted_active_job(
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
        store.start(job.id)

    with TestClient(create_app(settings)) as client:
        terminal = _wait(client, job.id)

    assert terminal["status"] == "succeeded"
    assert terminal["progress"] == 4
    assert terminal["result_id"] is not None


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
