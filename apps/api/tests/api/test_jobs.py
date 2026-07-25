from __future__ import annotations

import time
from pathlib import Path

from drawdown_lab.api.app import Settings, create_app
from fastapi.testclient import TestClient


def _candidate(index: int) -> dict[str, object]:
    base = index * 10
    return {
        "ratios": [base, base + 10, base + 20, base + 30],
        "fold_oos_xirr": [0.08 + index / 1000, 0.09 + index / 1000],
        "worst_5_return": -0.12,
        "early_depletion_rate": 0.05,
        "longest_trap_days": 300,
    }


def _payload(candidate_count: int = 4) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "minimum_independent_episodes": 5,
        "independent_episode_count": 8,
        "candidates": [_candidate(index) for index in range(candidate_count)],
        "synthetic_stress": [],
    }


def _wait_for_status(
    client: TestClient,
    job_id: str,
    terminal: set[str],
    *,
    timeout: float = 5.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200
        row = response.json()
        if row["status"] in terminal:
            return row
        time.sleep(0.005)
    raise AssertionError(f"job {job_id} did not reach {terminal}")


def test_completed_optimization_persists_result_and_typed_report(tmp_path: Path) -> None:
    database_path = tmp_path / "drawdown.sqlite"
    settings = Settings(database_path=database_path, data_root=tmp_path / "data")
    with TestClient(create_app(settings)) as client:
        accepted = client.post("/api/v1/optimizations", json=_payload()).json()
        completed = _wait_for_status(client, accepted["job_id"], {"completed", "failed"})

        assert completed["status"] == "completed"
        assert completed["result_id"] is not None
        result = client.get(f"/api/v1/results/{completed['result_id']}").json()
        reports = client.get("/api/v1/reports").json()
        assert result["payload"]["mode"] == "formal"
        assert reports["reports"][0]["export_status"] == "not_yet_exported"

    with TestClient(create_app(settings)) as reopened:
        persisted = reopened.get(f"/api/v1/jobs/{accepted['job_id']}").json()
        assert persisted["status"] == "completed"
        assert reopened.get(f"/api/v1/results/{completed['result_id']}").status_code == 200


def test_cancelled_job_never_publishes_partial_formal_result(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            database_path=tmp_path / "drawdown.sqlite",
            data_root=tmp_path / "data",
            job_batch_size=1,
            job_batch_delay_seconds=0.03,
        )
    )
    with TestClient(app) as client:
        accepted = client.post("/api/v1/optimizations", json=_payload(40)).json()
        job_id = accepted["job_id"]
        _wait_for_status(client, job_id, {"running", "completed"})

        cancellation = client.post(f"/api/v1/jobs/{job_id}/cancel")
        assert cancellation.status_code == 202
        cancelled = _wait_for_status(client, job_id, {"cancelled", "completed"})

        assert cancelled["status"] == "cancelled"
        assert cancelled["result_id"] is None
        assert client.get("/api/v1/results").json()["results"] == []
        assert app.state.job_store.result_count_for_job(job_id) == 0


def test_insufficient_events_complete_as_exploration_only_without_recommendations(
    tmp_path: Path,
) -> None:
    with TestClient(
        create_app(
            Settings(
                database_path=tmp_path / "drawdown.sqlite",
                data_root=tmp_path / "data",
            )
        )
    ) as client:
        payload = _payload(2)
        payload["independent_episode_count"] = 3
        accepted = client.post("/api/v1/optimizations", json=payload).json()
        completed = _wait_for_status(client, accepted["job_id"], {"completed", "failed"})
        result = client.get(f"/api/v1/results/{completed['result_id']}").json()

    assert result["payload"]["mode"] == "exploration_only"
    assert result["payload"]["recommendations"] == []
    assert all(not row["recommendation_labels"] for row in result["payload"]["candidates"])
