from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from drawdown_lab.api.app import Settings, create_app
from drawdown_lab.data.catalog import DataCatalog
from drawdown_lab.data.provider import MarketDataProvider
from drawdown_lab.data.update import UpdateCoordinator
from drawdown_lab.data.yahoo import YahooFinanceProvider


class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        normalized_path = str(scope.get("path", path)).lstrip("/")
        api_path = normalized_path == "api" or normalized_path.startswith("api/")
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or api_path:
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and not api_path:
            return await super().get_response("index.html", scope)
        return response


def create_runtime_app(
    *,
    project_root: Path | None = None,
    provider: MarketDataProvider | None = None,
) -> FastAPI:
    root = (
        project_root
        if project_root is not None
        else Path(os.environ["DRAWDOWN_PROJECT_ROOT"])
    ).resolve()
    data_root = root / "data"
    coordinator = UpdateCoordinator(
        provider or YahooFinanceProvider(),
        DataCatalog(data_root),
    )
    app = create_app(
        Settings(
            database_path=root / ".runtime" / "drawdown.sqlite",
            data_root=data_root,
            update_coordinator=coordinator,
        )
    )
    web_dist = root / "apps" / "web" / "dist"
    if (web_dist / "index.html").is_file():
        app.mount("/", SpaStaticFiles(directory=web_dist, html=True), name="spa")
    return app
