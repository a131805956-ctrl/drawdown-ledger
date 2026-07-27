from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal, cast

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status

from drawdown_lab.analysis.chart_series import (
    ChartSeries,
    actual_chart_series,
    scale_chart_series,
    synthetic_chart_series,
)
from drawdown_lab.analysis.episodes import classify_episodes
from drawdown_lab.analysis.evidence import analyze_evidence
from drawdown_lab.analysis.leverage import (
    default_synthetic_model_parameters,
    synthetic_daily_reset_nav,
)
from drawdown_lab.analysis.strategy import StrategyResult, simulate_strategy
from drawdown_lab.api.schemas import (
    ChartPointResponse,
    ChartSeriesResponse,
    DataCoverageResponse,
    DataHealthResponse,
    DataUpdateFailureResponse,
    DataUpdateRequest,
    DataUpdateResponse,
    EpisodeTraceResponse,
    ErrorResponse,
    EvidenceAnalyzeRequest,
    EvidenceAnalyzeResponse,
    ForwardReturnResponse,
    HorizonStatisticsResponse,
    InstrumentListResponse,
    InstrumentResponse,
    JobResponse,
    MarketOverviewResponse,
    MarketSeriesResponse,
    ModelAssumptionsResponse,
    OptimizationAcceptedResponse,
    OptimizationCreateRequest,
    PerformanceResponse,
    PortfolioPointResponse,
    ReportExportRequest,
    ReportExportResponse,
    ReportListResponse,
    ReportResponse,
    ResultListResponse,
    ResultResponse,
    StrategyBacktestRequest,
    StrategyBacktestResponse,
    TradeResponse,
)
from drawdown_lab.data.catalog import DataCatalog, DataIntegrityError
from drawdown_lab.data.cutoff import policy_cutoff
from drawdown_lab.data.models import MarketFrame
from drawdown_lab.data.update import DataUpdateError, UpdateCoordinator
from drawdown_lab.domain.instruments import (
    INSTRUMENT_FAMILIES,
    Instrument,
    InstrumentFamilyMismatchError,
    InstrumentFamilyNotFoundError,
    market_symbol_roles,
    prototype_proxy_symbol,
    resolve_family_instrument,
)
from drawdown_lab.reports.render import ReportExporter
from drawdown_lab.storage.jobs import (
    InvalidJobTransitionError,
    JobNotFoundError,
    JobService,
    JobStore,
)

MAX_MARKET_SERIES_RANGE_DAYS = 366 * 50
MAX_MARKET_SERIES_POINTS = 15_000


@dataclass(frozen=True, slots=True)
class TrustedMarketFrames:
    target: Instrument
    prototype_symbol: str
    prototype_source: Literal["benchmark", "proxy"]
    prototype: MarketFrame
    traded: MarketFrame


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
    ) -> TrustedMarketFrames:
        try:
            family, target = resolve_family_instrument(family_id, target_symbol)
        except InstrumentFamilyNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except InstrumentFamilyMismatchError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        prototype_symbol = family.benchmark_symbol
        prototype_source: Literal["benchmark", "proxy"] = "benchmark"
        prototype = data_catalog.read(prototype_symbol)
        proxy_symbol = prototype_proxy_symbol(family)
        if prototype is None and proxy_symbol != prototype_symbol:
            prototype_symbol = proxy_symbol
            prototype_source = "proxy"
            prototype = data_catalog.read(prototype_symbol)
        traded = data_catalog.read(target.symbol)
        if prototype is None:
            candidates = tuple(
                dict.fromkeys((family.benchmark_symbol, proxy_symbol))
            )
            raise HTTPException(
                status_code=404,
                detail=(
                    "Trusted cache is missing prototype series: "
                    f"{', '.join(candidates)}"
                ),
            )
        if traded is None:
            raise HTTPException(
                status_code=404,
                detail=f"Trusted cache is missing {target.symbol}",
            )
        return TrustedMarketFrames(
            target=target,
            prototype_symbol=prototype_symbol,
            prototype_source=prototype_source,
            prototype=prototype,
            traded=traded,
        )

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
        symbols = market_symbol_roles()
        coverage = tuple(
            DataCoverageResponse(
                symbol=symbol,
                roles=roles,
                cached=data_catalog.read(symbol) is not None,
                actual_last_session=data_catalog.actual_last_session(symbol),
                policy_cutoff=data_catalog.policy_cutoff(symbol),
            )
            for symbol, roles in symbols.items()
        )
        return DataHealthResponse(
            status=(
                "ready"
                if coverage and all(item.cached for item in coverage)
                else "incomplete"
            ),
            coverage=coverage,
        )

    @router.post("/data/update", response_model=DataUpdateResponse)
    def data_update(request: DataUpdateRequest) -> DataUpdateResponse:
        if update_coordinator is None:
            return DataUpdateResponse(
                status="not_configured",
                cutoff=None,
                request_count=0,
                refreshed_symbols=(),
                failures=(),
                message="No market-data provider is configured.",
            )
        try:
            summary = update_coordinator.ensure_current(request.as_of)
        except DataUpdateError as error:
            return DataUpdateResponse(
                status="failed",
                cutoff=policy_cutoff(request.as_of),
                request_count=0,
                refreshed_symbols=(),
                failures=(
                    DataUpdateFailureResponse(
                        symbol="__batch__",
                        message=str(error).strip() or type(error).__name__,
                    ),
                ),
                message="Data update failed.",
            )
        return DataUpdateResponse(
            status=summary.status,
            cutoff=summary.cutoff,
            request_count=summary.request_count,
            refreshed_symbols=summary.refreshed_symbols,
            failures=tuple(
                DataUpdateFailureResponse(
                    symbol=failure.symbol,
                    message=failure.message,
                )
                for failure in summary.failures
            ),
        )

    @router.post("/evidence/analyze", response_model=EvidenceAnalyzeResponse)
    def evidence_analyze(request: EvidenceAnalyzeRequest) -> EvidenceAnalyzeResponse:
        trusted = trusted_frames(request.family_id, request.target_symbol)
        target = trusted.target
        try:
            report = analyze_evidence(
                request.to_domain(),
                trusted.prototype,
                trusted.traded,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        classified = {
            (episode.threshold, episode.cycle_id, episode.signal_date): episode
            for episode in classify_episodes(
                trusted.prototype,
                (request.threshold,),
            )
        }
        return EvidenceAnalyzeResponse(
            family_id=request.family_id,
            prototype_symbol=trusted.prototype_symbol,
            prototype_source=trusted.prototype_source,
            target_symbol=target.symbol,
            prototype_actual_last_session=data_catalog.actual_last_session(
                trusted.prototype_symbol
            ),
            prototype_policy_cutoff=data_catalog.policy_cutoff(
                trusted.prototype_symbol
            ),
            target_actual_last_session=data_catalog.actual_last_session(target.symbol),
            target_policy_cutoff=data_catalog.policy_cutoff(target.symbol),
            n_day=report.n_day,
            n_episode=report.n_episode,
            n_executed_episode=report.n_executed_episode,
            daily_statistics=tuple(
                HorizonStatisticsResponse(**asdict(row)) for row in report.daily_statistics
            ),
            episode_statistics=tuple(
                HorizonStatisticsResponse(**asdict(row)) for row in report.episode_statistics
            ),
            episodes=tuple(
                EpisodeTraceResponse(
                    threshold=row.threshold,
                    cycle_id=row.cycle_id,
                    peak_date=classified[(row.threshold, row.cycle_id, row.signal_date)].peak_date,
                    peak_price=classified[
                        (row.threshold, row.cycle_id, row.signal_date)
                    ].peak_price,
                    signal_date=row.signal_date,
                    signal_price=classified[
                        (row.threshold, row.cycle_id, row.signal_date)
                    ].signal_price,
                    signal_drawdown=classified[
                        (row.threshold, row.cycle_id, row.signal_date)
                    ].drawdown,
                    entry_date=row.entry_date,
                    entry_price=row.entry_price,
                    recovery_date=classified[
                        (row.threshold, row.cycle_id, row.signal_date)
                    ].recovery_date,
                    recovery_sessions=row.recovery_sessions,
                    v_recovered=row.v_recovered,
                    mae=row.mae,
                    mfe=row.mfe,
                    forward_returns=tuple(
                        ForwardReturnResponse(**asdict(forward)) for forward in row.forward_returns
                    ),
                )
                for row in report.episodes
            ),
        )

    @router.post("/strategies/backtest", response_model=StrategyBacktestResponse)
    def strategy_backtest(request: StrategyBacktestRequest) -> StrategyBacktestResponse:
        trusted = trusted_frames(request.family_id, request.target_symbol)
        target = trusted.target
        try:
            result = simulate_strategy(
                request.to_domain(),
                trusted.prototype,
                trusted.traded,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        metrics = (
            PerformanceResponse(**asdict(result.metrics)) if result.metrics is not None else None
        )
        return StrategyBacktestResponse(
            family_id=request.family_id,
            prototype_symbol=trusted.prototype_symbol,
            prototype_source=trusted.prototype_source,
            target_symbol=target.symbol,
            prototype_actual_last_session=data_catalog.actual_last_session(
                trusted.prototype_symbol
            ),
            prototype_policy_cutoff=data_catalog.policy_cutoff(
                trusted.prototype_symbol
            ),
            target_actual_last_session=data_catalog.actual_last_session(target.symbol),
            target_policy_cutoff=data_catalog.policy_cutoff(target.symbol),
            name=result.name,
            ending_cash=result.ending_cash,
            ending_shares=result.ending_shares,
            trade_count=len(result.trades),
            dividend_income=result.dividend_income,
            contribution_total=result.contribution_total,
            interest_income=result.interest_income,
            total_fees=result.total_fees,
            pending_thresholds=result.pending_thresholds,
            missed_thresholds=result.missed_thresholds,
            trades=tuple(TradeResponse(**asdict(trade)) for trade in result.trades),
            equity_curve=_portfolio_points(result),
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
            family, target = resolve_family_instrument(
                request.family_id,
                request.target_symbol,
            )
        except InstrumentFamilyNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except InstrumentFamilyMismatchError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        prototype_symbol = (
            family.benchmark_symbol
            if data_catalog.read(family.benchmark_symbol) is not None
            else prototype_proxy_symbol(family)
        )
        try:
            domain_request = request.to_domain(
                prototype_symbol=prototype_symbol,
                target_leverage=target.leverage,
            )
        except ValueError as error:
            job_store.record_rejection(
                kind="optimization",
                request_payload=request.model_dump(mode="json"),
                reason=str(error),
            )
            raise HTTPException(status_code=422, detail=str(error)) from error
        trusted = trusted_frames(request.family_id, request.target_symbol)
        if trusted.prototype_symbol != domain_request.prototype_symbol:
            domain_request = replace(
                domain_request,
                prototype_symbol=trusted.prototype_symbol,
            )
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
        instruments_count = sum(len(family.instruments) for family in INSTRUMENT_FAMILIES)
        return MarketOverviewResponse(
            instrument_count=instruments_count,
            cached_symbols=data_catalog.symbols(),
            formal_result_count=job_store.result_count(),
        )

    @router.get("/market/series", response_model=MarketSeriesResponse)
    def market_series(
        family_id: str,
        target_symbol: str,
        start: date | None = None,
        end: date | None = None,
        history_mode: Literal[
            "target_inception", "prototype_earliest", "custom"
        ] = "target_inception",
        include_synthetic: bool = False,
        annual_expense_ratio: float | None = Query(default=None, ge=0.0, le=1.0),
        annual_management_fee: float | None = Query(default=None, ge=0.0, le=1.0),
        daily_financing_drag: float | None = Query(default=None, ge=0.0, le=1.0),
        daily_roll_drag: float | None = Query(default=None, ge=0.0, le=1.0),
        daily_transaction_drag: float | None = Query(default=None, ge=0.0, le=1.0),
        max_points: int = Query(
            default=MAX_MARKET_SERIES_POINTS,
            ge=1,
            le=MAX_MARKET_SERIES_POINTS,
        ),
    ) -> MarketSeriesResponse:
        trusted = trusted_frames(family_id, target_symbol)
        target = trusted.target
        prototype_first = cast(pd.Timestamp, trusted.prototype.data.index[0]).date()
        target_first = cast(pd.Timestamp, trusted.traded.data.index[0]).date()
        if history_mode == "custom" and start is None:
            raise HTTPException(
                status_code=422,
                detail="Custom history mode requires a start date",
            )
        effective_start: date | None
        response_history_mode = history_mode
        if history_mode == "prototype_earliest":
            effective_start = prototype_first if start is None else start
        elif history_mode == "custom":
            effective_start = start
        else:
            # Supplying start retains the original API's date-filter behavior;
            # otherwise the ETF's first trusted session is the default.
            effective_start = target_first if start is None else start
            if start is not None:
                response_history_mode = "custom"
        if effective_start is not None and end is not None and end < effective_start:
            raise HTTPException(status_code=422, detail="End date cannot precede start date")
        if start is not None and end is not None and end < start:
            raise HTTPException(status_code=422, detail="End date cannot precede start date")
        if (
            effective_start is not None
            and end is not None
            and (end - effective_start).days > MAX_MARKET_SERIES_RANGE_DAYS
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Requested market-series date range exceeds "
                    f"{MAX_MARKET_SERIES_RANGE_DAYS} days"
                ),
            )
        handoff_session = cast(
            pd.Timestamp,
            trusted.traded.data.index[0],
        ).date()
        prototype_series = actual_chart_series(
            trusted.prototype,
            start=effective_start,
            end=end,
        )
        actual_series = actual_chart_series(
            trusted.traded,
            start=effective_start,
            end=end,
        )
        synthetic_end = handoff_session - timedelta(days=1)
        if end is not None:
            synthetic_end = min(synthetic_end, end)
        default_management_fee, default_financing, default_roll, default_transaction = (
            default_synthetic_model_parameters(float(target.leverage))
        )
        management_fee = (
            annual_management_fee
            if annual_management_fee is not None
            else (
                annual_expense_ratio
                if annual_expense_ratio is not None
                else default_management_fee
            )
        )
        financing_drag = (
            default_financing
            if daily_financing_drag is None
            else daily_financing_drag
        )
        roll_drag = default_roll if daily_roll_drag is None else daily_roll_drag
        transaction_drag = (
            default_transaction
            if daily_transaction_drag is None
            else daily_transaction_drag
        )
        synthetic_model = None
        join_scale: float | None = None
        stress_series = None
        if include_synthetic and target.leverage > 1:
            model_data = trusted.prototype.data.copy()
            if effective_start is not None:
                model_data = model_data.loc[model_data.index >= pd.Timestamp(effective_start)]
            model_data = model_data.loc[
                model_data.index <= pd.Timestamp(handoff_session)
            ]
            if not model_data.empty:
                from drawdown_lab.data.models import MarketFrame

                synthetic_model = synthetic_daily_reset_nav(
                    MarketFrame(model_data),
                    float(target.leverage),
                    annual_management_fee=management_fee,
                    daily_financing_drag=financing_drag,
                    daily_roll_drag=roll_drag,
                    daily_transaction_drag=transaction_drag,
                )
                join_timestamp = pd.Timestamp(handoff_session)
                join_nav = synthetic_model.nav.get(join_timestamp)
                first_actual_close = (
                    float(
                        cast(
                            float,
                            trusted.traded.data.loc[join_timestamp, "price_close"],
                        )
                    )
                    if join_timestamp in trusted.traded.data.index
                    else None
                )
                if join_nav is not None and float(join_nav) > 0 and first_actual_close is not None:
                    join_scale = first_actual_close / float(join_nav)
                stress_series = synthetic_chart_series(
                    MarketFrame(model_data),
                    float(target.leverage),
                    annual_management_fee=management_fee,
                    daily_financing_drag=financing_drag,
                    daily_roll_drag=roll_drag,
                    daily_transaction_drag=transaction_drag,
                    start=effective_start,
                    end=synthetic_end,
                )
                if join_scale is not None:
                    stress_series = scale_chart_series(stress_series, join_scale)
        point_counts = (
            len(prototype_series.points),
            len(actual_series.points),
            len(stress_series.points) if stress_series is not None else 0,
        )
        if any(count > max_points for count in point_counts):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Selected range exceeds the {max_points} points-per-series limit; "
                    "narrow the start and end dates"
                ),
            )
        return MarketSeriesResponse(
            family_id=family_id,
            prototype_symbol=trusted.prototype_symbol,
            prototype_source=trusted.prototype_source,
            target_symbol=target.symbol,
            handoff_session=handoff_session if target.leverage > 1 else None,
            history_mode=response_history_mode,
            history_start=effective_start,
            history_end=end,
            join_session=handoff_session if target.leverage > 1 else None,
            model_assumptions=(
                ModelAssumptionsResponse(
                    method="daily_rebalance",
                    leverage=float(target.leverage),
                    initial_nav=synthetic_model.initial_nav,
                    annual_management_fee=synthetic_model.assumptions.annual_management_fee,
                    daily_financing_drag=synthetic_model.assumptions.daily_financing_drag,
                    daily_roll_drag=synthetic_model.assumptions.daily_roll_drag,
                    daily_transaction_drag=synthetic_model.assumptions.daily_transaction_drag,
                    sessions_per_year=synthetic_model.assumptions.sessions_per_year,
                    join_scale=join_scale,
                )
                if synthetic_model is not None
                else None
            ),
            prototype=_chart_response(
                symbol=trusted.prototype_symbol,
                leverage=1.0,
                currency=target.currency,
                series=prototype_series,
                catalog=data_catalog,
            ),
            actual=_chart_response(
                symbol=target.symbol,
                leverage=float(target.leverage),
                currency=target.currency,
                series=actual_series,
                catalog=data_catalog,
            ),
            synthetic=(
                _chart_response(
                    symbol=f"{target.symbol}-synthetic-{target.leverage}x",
                    leverage=float(target.leverage),
                    currency=None,
                    series=stress_series,
                    catalog=data_catalog,
                    lineage_symbol=trusted.prototype_symbol,
                )
                if stress_series is not None
                else None
            ),
        )

    @router.get("/results", response_model=ResultListResponse)
    def list_results() -> ResultListResponse:
        return ResultListResponse(
            results=tuple(ResultResponse.from_record(record) for record in job_store.list_results())
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
            reports=tuple(ReportResponse.from_record(record) for record in job_store.list_reports())
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


def _chart_response(
    *,
    symbol: str,
    leverage: float,
    currency: str | None,
    series: ChartSeries,
    catalog: DataCatalog,
    lineage_symbol: str | None = None,
) -> ChartSeriesResponse:
    coverage_symbol = lineage_symbol or symbol
    return ChartSeriesResponse(
        symbol=symbol,
        source_kind=series.source_kind,
        unit=series.unit,
        leverage=leverage,
        currency=currency,
        actual_last_session=catalog.actual_last_session(coverage_symbol),
        policy_cutoff=catalog.policy_cutoff(coverage_symbol),
        points=tuple(ChartPointResponse(**asdict(point)) for point in series.points),
    )


def _portfolio_points(result: StrategyResult) -> tuple[PortfolioPointResponse, ...]:
    opening_investment = (
        -result.external_cashflows[0].amount if result.external_cashflows else Decimal("0")
    )
    net_contributions = opening_investment
    points: list[PortfolioPointResponse] = []
    for point in result.equity_curve:
        net_contributions += point.external_flow
        points.append(
            PortfolioPointResponse(
                **asdict(point),
                net_contributions=net_contributions,
                profit_loss=point.value - net_contributions,
            )
        )
    return tuple(points)
