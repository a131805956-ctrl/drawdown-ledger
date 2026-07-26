from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status

from drawdown_lab.analysis.evidence import analyze_evidence
from drawdown_lab.analysis.strategy import simulate_strategy
from drawdown_lab.api.schemas import (
    DataCoverageResponse,
    DataHealthResponse,
    DataUpdateRequest,
    DataUpdateResponse,
    ErrorResponse,
    EvidenceAnalyzeRequest,
    EvidenceAnalyzeResponse,
    HorizonStatisticsResponse,
    InstrumentListResponse,
    InstrumentResponse,
    JobResponse,
    MarketOverviewResponse,
    OptimizationAcceptedResponse,
    OptimizationCreateRequest,
    PerformanceResponse,
    ReportExportRequest,
    ReportExportResponse,
    ReportListResponse,
    ReportResponse,
    ResultListResponse,
    ResultResponse,
    StrategyBacktestRequest,
    StrategyBacktestResponse,
)
from drawdown_lab.data.catalog import DataCatalog, DataIntegrityError
from drawdown_lab.data.models import MarketFrame
from drawdown_lab.data.update import UpdateCoordinator
from drawdown_lab.domain.instruments import (
    INSTRUMENT_FAMILIES,
    InstrumentFamilyMismatchError,
    InstrumentFamilyNotFoundError,
    resolve_family_instrument,
)
from drawdown_lab.reports.render import ReportExporter
from drawdown_lab.storage.jobs import (
    InvalidJobTransitionError,
    JobNotFoundError,
    JobService,
    JobStore,
)


def create_router(
    *,
    job_store: JobStore,
    job_service: JobService,
    data_catalog: DataCatalog,
    update_coordinator: UpdateCoordinator | None,
    report_exporter: ReportExporter,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1",
        responses={
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
    )

    def trusted_frames(
        family_id: str,
        target_symbol: str,
    ) -> tuple[MarketFrame, MarketFrame]:
        try:
            _, target = resolve_family_instrument(family_id, target_symbol)
        except InstrumentFamilyNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except InstrumentFamilyMismatchError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        prototype = data_catalog.read(target.prototype_symbol)
        traded = data_catalog.read(target.symbol)
        if prototype is None:
            raise HTTPException(
                status_code=404,
                detail=f"Trusted cache is missing {target.prototype_symbol}",
            )
        if traded is None:
            raise HTTPException(
                status_code=404,
                detail=f"Trusted cache is missing {target.symbol}",
            )
        return prototype, traded

    @router.get("/instruments", response_model=InstrumentListResponse)
    def instruments() -> InstrumentListResponse:
        rows = tuple(
            InstrumentResponse(**asdict(instrument))
            for family in INSTRUMENT_FAMILIES
            for instrument in family.instruments
        )
        return InstrumentListResponse(instruments=rows)

    @router.get("/data/health", response_model=DataHealthResponse)
    def data_health() -> DataHealthResponse:
        symbols = tuple(
            instrument.symbol
            for family in INSTRUMENT_FAMILIES
            for instrument in family.instruments
        )
        return DataHealthResponse(
            status="healthy",
            coverage=tuple(
                DataCoverageResponse(
                    symbol=symbol,
                    cached=data_catalog.read(symbol) is not None,
                    actual_last_session=data_catalog.actual_last_session(symbol),
                    policy_cutoff=data_catalog.policy_cutoff(symbol),
                )
                for symbol in symbols
            ),
        )

    @router.post("/data/update", response_model=DataUpdateResponse)
    def data_update(request: DataUpdateRequest) -> DataUpdateResponse:
        if update_coordinator is None:
            return DataUpdateResponse(
                status="not_configured",
                cutoff=None,
                request_count=0,
                refreshed_symbols=(),
                message="No market-data provider is configured.",
            )
        summary = update_coordinator.ensure_current(request.as_of)
        return DataUpdateResponse(
            status="completed",
            cutoff=summary.cutoff,
            request_count=summary.request_count,
            refreshed_symbols=summary.refreshed_symbols,
        )

    @router.post("/evidence/analyze", response_model=EvidenceAnalyzeResponse)
    def evidence_analyze(request: EvidenceAnalyzeRequest) -> EvidenceAnalyzeResponse:
        prototype, traded = trusted_frames(request.family_id, request.target_symbol)
        try:
            report = analyze_evidence(request.to_domain(), prototype, traded)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return EvidenceAnalyzeResponse(
            n_day=report.n_day,
            n_episode=report.n_episode,
            n_executed_episode=report.n_executed_episode,
            daily_statistics=tuple(
                HorizonStatisticsResponse(**asdict(row))
                for row in report.daily_statistics
            ),
            episode_statistics=tuple(
                HorizonStatisticsResponse(**asdict(row))
                for row in report.episode_statistics
            ),
        )

    @router.post("/strategies/backtest", response_model=StrategyBacktestResponse)
    def strategy_backtest(request: StrategyBacktestRequest) -> StrategyBacktestResponse:
        prototype, traded = trusted_frames(request.family_id, request.target_symbol)
        try:
            result = simulate_strategy(request.to_domain(), prototype, traded)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        metrics = (
            PerformanceResponse(**asdict(result.metrics))
            if result.metrics is not None
            else None
        )
        return StrategyBacktestResponse(
            name=result.name,
            ending_cash=result.ending_cash,
            ending_shares=result.ending_shares,
            trade_count=len(result.trades),
            pending_thresholds=result.pending_thresholds,
            missed_thresholds=result.missed_thresholds,
            metrics=metrics,
        )

    @router.post(
        "/optimizations",
        response_model=OptimizationAcceptedResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_optimization(
        request: OptimizationCreateRequest,
    ) -> OptimizationAcceptedResponse:
        try:
            _, target = resolve_family_instrument(
                request.family_id,
                request.target_symbol,
            )
        except InstrumentFamilyNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except InstrumentFamilyMismatchError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            domain_request = request.to_domain(
                prototype_symbol=target.prototype_symbol,
                target_leverage=target.leverage,
            )
        except ValueError as error:
            job_store.record_rejection(
                kind="optimization",
                request_payload=request.model_dump(mode="json"),
                reason=str(error),
            )
            raise HTTPException(status_code=422, detail=str(error)) from error
        trusted_frames(request.family_id, request.target_symbol)
        job = job_service.submit(domain_request)
        return OptimizationAcceptedResponse(job_id=job.id, status="queued")

    @router.get("/jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: str) -> JobResponse:
        try:
            return JobResponse.from_record(job_store.get(job_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="Job not found") from error

    @router.post(
        "/jobs/{job_id}/cancel",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def cancel_job(job_id: str) -> JobResponse:
        try:
            return JobResponse.from_record(job_store.request_cancel(job_id))
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="Job not found") from error
        except InvalidJobTransitionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/market/overview", response_model=MarketOverviewResponse)
    def market_overview() -> MarketOverviewResponse:
        instruments_count = sum(
            len(family.instruments) for family in INSTRUMENT_FAMILIES
        )
        return MarketOverviewResponse(
            instrument_count=instruments_count,
            cached_symbols=data_catalog.symbols(),
            formal_result_count=job_store.result_count(),
        )

    @router.get("/results", response_model=ResultListResponse)
    def list_results() -> ResultListResponse:
        return ResultListResponse(
            results=tuple(
                ResultResponse.from_record(record)
                for record in job_store.list_results()
            )
        )

    @router.get("/results/{result_id}", response_model=ResultResponse)
    def get_result(result_id: str) -> ResultResponse:
        try:
            return ResultResponse.from_record(job_store.get_result(result_id))
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Result not found") from error

    @router.get("/reports", response_model=ReportListResponse)
    def list_reports() -> ReportListResponse:
        return ReportListResponse(
            reports=tuple(
                ReportResponse.from_record(record)
                for record in job_store.list_reports()
            )
        )

    @router.post(
        "/reports/export",
        response_model=ReportExportResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def export_report(request: ReportExportRequest) -> ReportExportResponse:
        try:
            manifest = report_exporter.export_report(
                request.result_id,
                request.formats,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Result not found") from error
        except DataIntegrityError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return ReportExportResponse.from_manifest(manifest)

    @router.get("/reports/{report_id}", response_model=ReportResponse)
    def get_report(report_id: str) -> ReportResponse:
        try:
            return ReportResponse.from_record(job_store.get_report(report_id))
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Report not found") from error

    return router
