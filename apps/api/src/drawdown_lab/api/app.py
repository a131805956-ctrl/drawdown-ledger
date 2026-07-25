from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from drawdown_lab.api.routes import create_router
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
    job_batch_delay_seconds: float = 0.0
    update_coordinator: UpdateCoordinator | None = None


def create_app(settings: Settings) -> FastAPI:
    database = Database(settings.database_path)
    job_store = JobStore(database)
    job_service = JobService(
        job_store,
        max_workers=settings.max_job_workers,
        batch_size=settings.job_batch_size,
        batch_delay_seconds=settings.job_batch_delay_seconds,
    )
    data_root = settings.data_root or settings.database_path.parent / "data"
    data_catalog = DataCatalog(data_root)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
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
    app.include_router(
        create_router(
            job_store=job_store,
            job_service=job_service,
            data_catalog=data_catalog,
            update_coordinator=settings.update_coordinator,
        )
    )
    return app
