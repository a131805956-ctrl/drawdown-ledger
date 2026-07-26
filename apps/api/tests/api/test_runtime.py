import importlib.util
from datetime import date
from pathlib import Path

from drawdown_lab.data.models import MarketFrame
from fastapi.testclient import TestClient


class NeverFetchProvider:
    def fetch(self, symbol: str, start: date, end: date) -> MarketFrame:
        raise AssertionError("runtime construction must not fetch market data")


def test_runtime_factory_uses_project_local_default_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    assert importlib.util.find_spec("drawdown_lab.runtime") is not None
    from drawdown_lab.runtime import create_runtime_app

    monkeypatch.setenv("DRAWDOWN_PROJECT_ROOT", str(tmp_path))

    app = create_runtime_app()

    assert app.state.settings.database_path == tmp_path / ".runtime" / "drawdown.sqlite"
    assert app.state.settings.data_root == tmp_path / "data"


def test_runtime_factory_configures_the_real_update_coordinator(tmp_path: Path) -> None:
    from drawdown_lab.runtime import create_runtime_app

    provider = NeverFetchProvider()
    app = create_runtime_app(project_root=tmp_path, provider=provider)

    assert app.state.settings.update_coordinator is not None
    assert app.state.settings.update_coordinator.provider is provider


def test_runtime_serves_built_spa_and_preserves_api_routes(tmp_path: Path) -> None:
    from drawdown_lab.runtime import create_runtime_app

    dist = tmp_path / "apps" / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<h1>Drawdown Ledger</h1>", encoding="utf-8")
    app = create_runtime_app(project_root=tmp_path, provider=NeverFetchProvider())

    with TestClient(app) as client:
        root = client.get("/")
        client_route = client.get("/strategy-lab")
        instruments = client.get("/api/v1/instruments")
        missing_api = client.get("/api/v1/does-not-exist")

    assert root.status_code == 200
    assert client_route.status_code == 200
    assert "Drawdown Ledger" in client_route.text
    assert instruments.status_code == 200
    assert instruments.json()["schema_version"] == "1.0"
    assert missing_api.status_code == 404
    assert "Drawdown Ledger" not in missing_api.text


def test_runtime_accepts_the_owned_public_mount_without_escaping_it(
    tmp_path: Path,
) -> None:
    from drawdown_lab.runtime import create_runtime_app

    dist = tmp_path / "apps" / "web" / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<script src="/drawdown-ledger/assets/app.js"></script>'
        "<h1>Drawdown Ledger</h1>",
        encoding="utf-8",
    )
    (assets / "app.js").write_text("globalThis.mounted = true;", encoding="utf-8")
    app = create_runtime_app(project_root=tmp_path, provider=NeverFetchProvider())

    with TestClient(app) as client:
        mounted_root = client.get("/drawdown-ledger/")
        mounted_route = client.get("/drawdown-ledger/evidence")
        mounted_asset = client.get("/drawdown-ledger/assets/app.js")
        mounted_api = client.get("/drawdown-ledger/api/v1/instruments")
        missing_mounted_api = client.get(
            "/drawdown-ledger/api/v1/does-not-exist",
        )

    assert mounted_root.status_code == 200
    assert mounted_route.status_code == 200
    assert "Drawdown Ledger" in mounted_route.text
    assert mounted_asset.status_code == 200
    assert mounted_asset.text == "globalThis.mounted = true;"
    assert "javascript" in mounted_asset.headers["content-type"]
    assert mounted_api.status_code == 200
    assert mounted_api.json()["schema_version"] == "1.0"
    assert missing_mounted_api.status_code == 404
    assert "Drawdown Ledger" not in missing_mounted_api.text


def test_public_mount_requires_basic_auth_for_non_loopback_clients(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from drawdown_lab.runtime import create_runtime_app

    monkeypatch.setenv("DRAWDOWN_PUBLIC_USERNAME", "drawdown")
    monkeypatch.setenv(
        "DRAWDOWN_PUBLIC_PASSWORD",
        "correct-horse-battery-staple",
    )
    app = create_runtime_app(project_root=tmp_path, provider=NeverFetchProvider())

    with TestClient(app) as client:
        denied_root = client.get("/")
        denied = client.get("/drawdown-ledger/api/v1/instruments")
        wrong = client.get(
            "/drawdown-ledger/api/v1/instruments",
            auth=("drawdown", "wrong"),
        )
        allowed = client.get(
            "/drawdown-ledger/api/v1/instruments",
            auth=("drawdown", "correct-horse-battery-staple"),
        )
        stripped_allowed = client.get(
            "/api/v1/instruments",
            auth=("drawdown", "correct-horse-battery-staple"),
        )

    assert denied_root.status_code == 401
    assert denied.status_code == 401
    assert denied.headers["www-authenticate"].startswith("Basic ")
    assert denied.headers["cache-control"] == "no-store"
    assert wrong.status_code == 401
    assert allowed.status_code == 200
    assert stripped_allowed.status_code == 200


def test_public_mount_allows_direct_loopback_without_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from drawdown_lab.runtime import create_runtime_app

    monkeypatch.setenv("DRAWDOWN_PUBLIC_USERNAME", "drawdown")
    monkeypatch.setenv(
        "DRAWDOWN_PUBLIC_PASSWORD",
        "correct-horse-battery-staple",
    )
    app = create_runtime_app(project_root=tmp_path, provider=NeverFetchProvider())

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get("/drawdown-ledger/api/v1/instruments")

    assert response.status_code == 200


def test_runtime_rejects_partial_public_access_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from drawdown_lab.runtime import create_runtime_app

    monkeypatch.setenv("DRAWDOWN_PUBLIC_USERNAME", "drawdown")
    monkeypatch.delenv("DRAWDOWN_PUBLIC_PASSWORD", raising=False)

    try:
        create_runtime_app(project_root=tmp_path, provider=NeverFetchProvider())
    except RuntimeError as error:
        assert "must be configured together" in str(error)
    else:
        raise AssertionError("partial public access configuration must fail closed")
