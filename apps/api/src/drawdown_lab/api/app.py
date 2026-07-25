from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from drawdown_lab.api.routes import create_router
from drawdown_lab.api.schemas import ErrorResponse, ValidationIssue
from drawdown_lab.data.catalog import DataCatalog
from drawdown_lab.data.update import UpdateCoordinator
from drawdown_lab.storage.database import Database
from drawdown_lab.storage.jobs import JobService, JobStore


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    data_root: Path | None = None
    max_job_workers: int = 1
    job_batch_size: int = 25
    job_lease_seconds: float = 60.0
    update_coordinator: UpdateCoordinator | None = None


def create_app(settings: Settings) -> FastAPI:
    database = Database(settings.database_path)
    job_store = JobStore(database)
    data_root = settings.data_root or settings.database_path.parent / "data"
    data_catalog = DataCatalog(data_root)
    job_service = JobService(
        job_store,
        data_catalog,
        max_workers=settings.max_job_workers,
        batch_size=settings.job_batch_size,
        lease_seconds=settings.job_lease_seconds,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        job_service.reconcile()
        yield
        job_service.shutdown()

    app = FastAPI(
        title="Drawdown Ledger API",
        version="1.0",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.job_store = job_store
    app.state.job_service = job_service
    app.state.data_catalog = data_catalog

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _: object,
        error: RequestValidationError,
    ) -> JSONResponse:
        def input_json(value: object) -> str:
            try:
                return json.dumps(
                    value,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                )
            except (TypeError, ValueError):
                return json.dumps(str(value), ensure_ascii=False)

        details = tuple(
            ValidationIssue(
                type=str(item["type"]),
                loc=tuple(item["loc"]),
                msg=str(item["msg"]),
                input_json=(
                    input_json(item["input"]) if "input" in item else None
                ),
            )
            for item in error.errors()
        )
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(detail=details).model_dump(mode="json"),
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(_: object, error: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=ErrorResponse(detail=str(error.detail)).model_dump(mode="json"),
            headers=error.headers,
        )
    app.include_router(
        create_router(
            job_store=job_store,
            job_service=job_service,
            data_catalog=data_catalog,
            update_coordinator=settings.update_coordinator,
        )
    )
    return app
