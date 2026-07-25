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
