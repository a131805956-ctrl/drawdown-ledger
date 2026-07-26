from pathlib import Path

import pytest
from drawdown_lab.api.app import Settings, create_app
from drawdown_lab.reports.publication import (
    PublicationCollectionError,
    build_publication_index,
    validate_published_collection,
)
from fastapi.testclient import TestClient

from apps.api.tests.api.test_report_export import _wait_for_result
from apps.api.tests.api.test_trusted_optimizer import _request, _seed


def _publish_real_reports(
    tmp_path: Path,
    requested_formats: tuple[tuple[str, ...], ...],
    *,
    collection_name: str = "published",
) -> tuple[Path, ...]:
    data_root = tmp_path / "data"
    report_root = tmp_path / collection_name
    _seed(data_root)
    application = create_app(
        Settings(
            database_path=tmp_path / f"{collection_name}.sqlite",
            data_root=data_root,
            report_output_root=report_root,
            engine_version="0.1.0",
            git_commit="0123456789abcdef0123456789abcdef01234567",
        )
    )
    bundles: list[Path] = []
    with TestClient(application) as client:
        accepted = client.post("/api/v1/optimizations", json=_request())
        assert accepted.status_code == 202
        result_id = _wait_for_result(client, accepted.json()["job_id"])
        for formats in requested_formats:
            response = client.post(
                "/api/v1/reports/export",
                json={
                    "schema_version": "1.0",
                    "result_id": result_id,
                    "formats": list(formats),
                },
            )
            assert response.status_code == 201
            bundles.append(report_root / response.json()["export_id"])
    return tuple(bundles)


def test_publication_collection_validates_each_bundle_and_builds_links(
    tmp_path: Path,
) -> None:
    html_bundle, json_bundle = _publish_real_reports(
        tmp_path,
        (("html", "json"), ("json",)),
    )
    output = tmp_path / "site" / "reports" / "index.html"

    reports = build_publication_index(
        tmp_path / "published",
        output,
    )

    assert [report.export_id for report in reports] == sorted(
        [html_bundle.name, json_bundle.name],
    )
    document = output.read_text(encoding="utf-8")
    assert (
        f"published/{html_bundle.name}/report.html"
        in document
    )
    assert (
        f"published/{json_bundle.name}/report.json"
        in document
    )
    assert str(tmp_path) not in document


def test_missing_collection_builds_an_explicit_empty_index(
    tmp_path: Path,
) -> None:
    output = tmp_path / "site" / "reports" / "index.html"

    reports = build_publication_index(tmp_path / "missing", output)

    assert reports == ()
    assert "目前沒有已公開報告" in output.read_text(encoding="utf-8")


def test_collection_rejects_unexpected_root_files(tmp_path: Path) -> None:
    collection = tmp_path / "published"
    collection.mkdir()
    (collection / "notes.txt").write_text("not a bundle", encoding="utf-8")

    with pytest.raises(
        PublicationCollectionError,
        match="unexpected collection entry",
    ):
        validate_published_collection(collection)


def test_collection_rejects_a_bundle_that_fails_privacy_scan(
    tmp_path: Path,
) -> None:
    (bundle,) = _publish_real_reports(tmp_path, (("json",),))
    report = bundle / "report.json"
    report.write_text('{"api_key":"secret"}', encoding="utf-8")

    with pytest.raises(
        PublicationCollectionError,
        match="privacy validation failed",
    ):
        validate_published_collection(tmp_path / "published")


def test_collection_rejects_linked_bundle_directories(tmp_path: Path) -> None:
    (bundle,) = _publish_real_reports(
        tmp_path,
        (("json",),),
        collection_name="source",
    )
    collection = tmp_path / "published"
    collection.mkdir()
    link = collection / bundle.name
    try:
        link.symlink_to(bundle, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(
        PublicationCollectionError,
        match="linked collection entry",
    ):
        validate_published_collection(collection)


def test_collection_rejects_a_broken_root_link(tmp_path: Path) -> None:
    collection = tmp_path / "published"
    try:
        collection.symlink_to(
            tmp_path / "missing-target",
            target_is_directory=True,
        )
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(
        PublicationCollectionError,
        match="invalid published collection root",
    ):
        validate_published_collection(collection)
