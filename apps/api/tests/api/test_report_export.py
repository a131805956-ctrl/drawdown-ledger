from __future__ import annotations

import hashlib
import time
from pathlib import Path

import drawdown_lab.reports.render as report_render
import pytest
from drawdown_lab.api.app import Settings, create_app
from drawdown_lab.reports.privacy import privacy_scan
from fastapi.testclient import TestClient

from apps.api.tests.api.test_trusted_optimizer import _request, _seed
from apps.api.tests.reports.test_render import (
    RESULT_ID,
    _catalog,
    _repository_root,
    _stored_results,
)


def _client(tmp_path: Path) -> TestClient:
    database_path = tmp_path / "drawdown.sqlite"
    data_root = tmp_path / "data"
    catalog = _catalog(data_root)
    _stored_results(database_path, catalog)
    return TestClient(
        create_app(
            Settings(
                database_path=database_path,
                data_root=data_root,
                report_output_root=tmp_path / "reports" / "private",
                repository_root=_repository_root(),
            )
        )
    )


def _wait_for_result(client: TestClient, job_id: str) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] == "succeeded":
            return str(job["result_id"])
        if job["status"] in {"failed", "cancelled"}:
            raise AssertionError(f"optimization ended as {job['status']}")
        time.sleep(0.005)
    raise AssertionError("optimization did not finish")


def test_post_report_export_accepts_only_result_id_and_formats(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/v1/reports/export",
            json={
                "schema_version": "1.0",
                "result_id": RESULT_ID,
                "formats": ["json"],
            },
        )
        injected = client.post(
            "/api/v1/reports/export",
            json={
                "schema_version": "1.0",
                "result_id": RESULT_ID,
                "formats": ["json"],
                "result": {"summary": {"invented": True}},
                "provenance": {"git_commit": "deadbeef"},
                "output_root": "reports/published",
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["schema_version"] == "1.0"
    assert payload["result_id"] == RESULT_ID
    assert set(payload["artifacts"]) == {"json"}
    assert "directory" not in payload
    assert (
        tmp_path
        / "reports"
        / "private"
        / payload["export_id"]
        / "manifest.json"
    ).is_file()
    assert injected.status_code == 422


def test_successful_export_persists_typed_content_and_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    request = {
        "schema_version": "1.0",
        "result_id": RESULT_ID,
        "formats": ["html", "json", "csv"],
    }
    with _client(tmp_path) as client:
        first = client.post("/api/v1/reports/export", json=request)
        report_after_first = client.get("/api/v1/reports").json()["reports"][0]
        second = client.post("/api/v1/reports/export", json=request)
        report_after_second = client.get(
            f"/api/v1/reports/{report_after_first['id']}"
        ).json()

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json() == first.json()
    assert report_after_first == report_after_second
    assert report_after_first["export_status"] == "exported"
    assert report_after_first["content"] == {
        "status": "exported",
        "message": "Report export is ready.",
        "result_id": RESULT_ID,
        "export_id": first.json()["export_id"],
        "artifacts": first.json()["artifacts"],
        "lineage": first.json()["lineage"],
        "optimization": report_after_first["content"]["optimization"],
    }
    assert report_after_first["content"]["optimization"]["schema_version"] == "1.0"


def test_failed_export_does_not_claim_persisted_report_is_exported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path)

    def fail_render(*_: object, **__: object) -> object:
        raise OSError("simulated render failure")

    monkeypatch.setattr(report_render, "_render_report", fail_render)
    with client:
        with pytest.raises(OSError, match="simulated render failure"):
            client.post(
                "/api/v1/reports/export",
                json={
                    "schema_version": "1.0",
                    "result_id": RESULT_ID,
                    "formats": ["json"],
                },
            )
        report = client.get("/api/v1/reports").json()["reports"][0]

    assert report["export_status"] == "not_yet_exported"
    assert report["content"]["status"] == "not_yet_exported"
    assert "export_id" not in report["content"]


def test_post_report_export_fails_closed_for_unknown_id_and_empty_formats(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        missing = client.post(
            "/api/v1/reports/export",
            json={
                "schema_version": "1.0",
                "result_id": "result-never-persisted",
                "formats": ["json"],
            },
        )
        empty = client.post(
            "/api/v1/reports/export",
            json={
                "schema_version": "1.0",
                "result_id": RESULT_ID,
                "formats": [],
            },
        )

    assert missing.status_code == 404
    assert missing.json()["detail"] == "Result not found"
    assert empty.status_code == 422


def test_post_report_export_reports_missing_result_time_lineage_as_conflict(
    tmp_path: Path,
) -> None:
    with _client(tmp_path) as client:
        with client.app.state.job_store.database.connect() as connection:
            connection.execute(
                "UPDATE results SET lineage_json = NULL WHERE id = ?",
                (RESULT_ID,),
            )
        response = client.post(
            "/api/v1/reports/export",
            json={
                "schema_version": "1.0",
                "result_id": RESULT_ID,
                "formats": ["json"],
            },
        )

    assert response.status_code == 409
    assert "result lineage" in response.json()["detail"].lower()


def test_packaged_runtime_accepts_injected_build_identity(tmp_path: Path) -> None:
    application = create_app(
        Settings(
            database_path=tmp_path / "packaged.sqlite",
            data_root=tmp_path / "data",
            report_output_root=tmp_path / "reports",
            repository_root=tmp_path / "not-a-source-checkout",
            engine_version="0.1.0",
            git_commit="0123456789abcdef0123456789abcdef01234567",
        )
    )

    with TestClient(application) as client:
        response = client.get("/api/v1/instruments")

    assert response.status_code == 200


def test_real_optimization_export_uses_persisted_lineage_and_is_publishable(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    report_root = tmp_path / "reports" / "private"
    _seed(data_root)
    application = create_app(
        Settings(
            database_path=tmp_path / "real.sqlite",
            data_root=data_root,
            report_output_root=report_root,
            engine_version="0.1.0",
            git_commit="0123456789abcdef0123456789abcdef01234567",
        )
    )
    with TestClient(application) as client:
        accepted = client.post("/api/v1/optimizations", json=_request()).json()
        result_id = _wait_for_result(client, accepted["job_id"])
        stored = application.state.job_store.get_result(result_id)
        assert isinstance(stored.lineage, dict)
        original_hash = stored.lineage["data_lineage"]["QQQ"]["sha256"]
        assert original_hash == hashlib.sha256(
            application.state.data_catalog.path_for("QQQ").read_bytes()
        ).hexdigest()
        with application.state.data_catalog.path_for("QQQ").open("ab") as stream:
            stream.write(b"later-catalog-tamper")

        response = client.post(
            "/api/v1/reports/export",
            json={
                "schema_version": "1.0",
                "result_id": result_id,
                "formats": ["html", "json", "csv"],
            },
        )

    assert response.status_code == 201
    bundle = report_root / response.json()["export_id"]
    assert response.json()["lineage"]["data_hashes"]["QQQ"] == original_hash
    assert (bundle / "candidates.csv").read_text("utf-8").strip()
    assert (bundle / "recommendations.csv").read_text("utf-8").strip()
    assert privacy_scan(bundle).allowed is True
