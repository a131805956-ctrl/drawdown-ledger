from __future__ import annotations

import base64
import ipaddress
import os
import secrets
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from drawdown_lab.api.app import Settings, create_app
from drawdown_lab.data.catalog import DataCatalog
from drawdown_lab.data.provider import MarketDataProvider
from drawdown_lab.data.update import UpdateCoordinator
from drawdown_lab.data.yahoo import YahooFinanceProvider

PUBLIC_MOUNT_PATH = "/drawdown-ledger"
PUBLIC_USERNAME_ENV = "DRAWDOWN_PUBLIC_USERNAME"
PUBLIC_PASSWORD_ENV = "DRAWDOWN_PUBLIC_PASSWORD"


class PublicAccessMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        username: str,
        password: str,
    ) -> None:
        self.app = app
        credential = base64.b64encode(
            f"{username}:{password}".encode()
        ).decode("ascii")
        self.expected_authorization = f"Basic {credential}"

    @staticmethod
    def _is_loopback(scope: Scope) -> bool:
        client = scope.get("client")
        if not isinstance(client, (tuple, list)) or not client:
            return False
        try:
            return ipaddress.ip_address(str(client[0])).is_loopback
        except ValueError:
            return False

    def _is_authorized(self, scope: Scope) -> bool:
        for raw_name, raw_value in scope.get("headers", ()):
            if raw_name.lower() != b"authorization":
                continue
            try:
                supplied = raw_value.decode("ascii")
            except UnicodeDecodeError:
                return False
            return secrets.compare_digest(
                supplied,
                self.expected_authorization,
            )
        return False

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if (
            scope["type"] not in {"http", "websocket"}
            or self._is_loopback(scope)
            or self._is_authorized(scope)
        ):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return
        response = Response(
            "Authentication required.",
            status_code=401,
            media_type="text/plain",
            headers={
                "WWW-Authenticate": 'Basic realm="Drawdown Ledger", charset="UTF-8"',
                "Cache-Control": "no-store",
            },
        )
        await response(scope, receive, send)


class PublicMountMiddleware:
    def __init__(self, app: ASGIApp, *, mount_path: str) -> None:
        self.app = app
        self.mount_path = mount_path

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        if path == self.mount_path:
            stripped_path = "/"
        elif path.startswith(f"{self.mount_path}/"):
            stripped_path = path[len(self.mount_path) :]
        else:
            await self.app(scope, receive, send)
            return
        mounted_scope = dict(scope)
        mounted_scope["path"] = stripped_path
        mounted_scope["raw_path"] = stripped_path.encode("utf-8")
        mounted_scope["root_path"] = (
            f"{str(scope.get('root_path', '')).rstrip('/')}"
            f"{self.mount_path}"
        )
        await self.app(mounted_scope, receive, send)


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
    app.add_middleware(
        PublicMountMiddleware,
        mount_path=PUBLIC_MOUNT_PATH,
    )
    public_username = os.environ.get(PUBLIC_USERNAME_ENV)
    public_password = os.environ.get(PUBLIC_PASSWORD_ENV)
    if (public_username is None) != (public_password is None):
        raise RuntimeError(
            f"{PUBLIC_USERNAME_ENV} and {PUBLIC_PASSWORD_ENV} must be configured together"
        )
    if public_username is not None and public_password is not None:
        if not public_username or not public_password:
            raise RuntimeError("Public access credentials cannot be empty")
        app.add_middleware(
            PublicAccessMiddleware,
            username=public_username,
            password=public_password,
        )
    web_dist = root / "apps" / "web" / "dist"
    if (web_dist / "index.html").is_file():
        app.mount("/", SpaStaticFiles(directory=web_dist, html=True), name="spa")
    return app
