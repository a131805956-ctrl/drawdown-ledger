from __future__ import annotations

import datetime as dt
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    ValidationError,
    model_validator,
)

from drawdown_lab.analysis.cashflows import ContributionEvent
from drawdown_lab.analysis.evidence import EvidenceRequest
from drawdown_lab.analysis.strategy import StrategyConfig, ThresholdTier
from drawdown_lab.domain.money import MAX_SAFE_DECIMAL
from drawdown_lab.optimization.evaluator import (
    HistoricalOptimizationRequest,
    RatioSearch,
    StrategyTemplate,
    SyntheticStressSettings,
    WalkForwardSettings,
)
from drawdown_lab.optimization.scoring import (
    OptimizationRequest,
    ProfileConstraints,
)
from drawdown_lab.reports.models import ExportManifest
from drawdown_lab.storage.jobs import JobRecord, ReportRecord, ResultRecord

SCHEMA_VERSION: Literal["1.0"] = "1.0"
PositiveRatio = Annotated[Decimal, Field(gt=0, le=1)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0, le=MAX_SAFE_DECIMAL)]
ContributionGrowth = Annotated[Decimal, Field(gt=-1, le=MAX_SAFE_DECIMAL)]
UnitDecimal = Annotated[Decimal, Field(ge=0, le=1)]
HorizonSessions = Annotated[int, Field(gt=0, le=2520)]
ZeroDecimal = Annotated[Decimal, Field(ge=0, le=0)]
CanonicalMonth = Annotated[
    date,
    Field(
        description=(
            "Calendar-month event. Any valid date is normalized to the first day "
            "of that month."
        )
    ),
]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class VersionedModel(ApiModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class InstrumentResponse(ApiModel):
    symbol: str
    name: str
    family_id: str
    leverage: int
    prototype_symbol: str
    currency: str
    timezone: str
    inception: date | None


class InstrumentListResponse(VersionedModel):
    instruments: tuple[InstrumentResponse, ...]


class DataCoverageResponse(ApiModel):
    symbol: str
    roles: tuple[Literal["tradable", "prototype", "prototype_proxy"], ...]
    cached: bool
    actual_last_session: date | None
    policy_cutoff: date | None


class DataHealthResponse(VersionedModel):
    status: Literal["healthy"]
    coverage: tuple[DataCoverageResponse, ...]


class DataUpdateRequest(VersionedModel):
    as_of: date


class DataUpdateResponse(VersionedModel):
    status: Literal["completed", "not_configured"]
    cutoff: date | None
    request_count: int
    refreshed_symbols: tuple[str, ...]
    message: str | None = None


class MarketOverviewResponse(VersionedModel):
    instrument_count: int
    cached_symbols: tuple[str, ...]
    formal_result_count: int


class ChartPointResponse(ApiModel):
    session: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    total_return_close: float
    normalized_total_return: float
    drawdown: float


class ChartSeriesResponse(ApiModel):
    symbol: str
    source_kind: Literal["actual", "synthetic"]
    unit: Literal["price", "index"]
    leverage: float
    currency: str | None
    actual_last_session: date | None
    policy_cutoff: date | None
    points: tuple[ChartPointResponse, ...]


class MarketSeriesResponse(VersionedModel):
    family_id: str
    prototype_symbol: str
    prototype_source: Literal["benchmark", "proxy"]
    target_symbol: str
    source_label: Literal["trusted_local_cache"] = "trusted_local_cache"
    handoff_session: date | None
    prototype: ChartSeriesResponse
    actual: ChartSeriesResponse
    synthetic: ChartSeriesResponse | None


class EvidenceAnalyzeRequest(VersionedModel):
    family_id: str = Field(min_length=1)
    target_symbol: str = Field(min_length=1)
    threshold: float = Field(gt=0.0, le=1.0)
    horizons: tuple[HorizonSessions, ...] = Field(
        default=(21, 63, 126, 252, 756, 1260),
        min_length=1,
        max_length=16,
    )

    @model_validator(mode="after")
    def validate_horizons(self) -> Self:
        if not self.horizons or any(horizon <= 0 for horizon in self.horizons):
            raise ValueError("Evidence horizons must be positive")
        if len(set(self.horizons)) != len(self.horizons):
            raise ValueError("Evidence horizons must be unique")
        return self

    def to_domain(self) -> EvidenceRequest:
        return EvidenceRequest(threshold=self.threshold, horizons=self.horizons)


class HorizonStatisticsResponse(ApiModel):
    sample_kind: str
    independent: bool
    overlap_warning: str | None
    horizon_sessions: int
    n: int
    mean_total_return: float | None
    median_total_return: float | None
    win_rate: float | None
    expected_shortfall_5: float | None
    confidence_lower: float | None
    confidence_upper: float | None


class ForwardReturnResponse(ApiModel):
    horizon_sessions: int
    exit_date: date | None
    total_return: float | None


class EpisodeTraceResponse(ApiModel):
    threshold: float
    cycle_id: int
    peak_date: date
    peak_price: float
    signal_date: date
    signal_price: float
    signal_drawdown: float
    entry_date: date | None
    entry_price: Decimal | None
    recovery_date: date | None
    recovery_sessions: int | None
    v_recovered: bool
    mae: float | None
    mfe: float | None
    forward_returns: tuple[ForwardReturnResponse, ...]


class EvidenceAnalyzeResponse(VersionedModel):
    family_id: str
    prototype_symbol: str
    prototype_source: Literal["benchmark", "proxy"]
    target_symbol: str
    source_label: Literal["trusted_local_cache"] = "trusted_local_cache"
    source_kind: Literal["actual"] = "actual"
    prototype_actual_last_session: date | None
    prototype_policy_cutoff: date | None
    target_actual_last_session: date | None
    target_policy_cutoff: date | None
    n_day: int
    n_episode: int
    n_executed_episode: int
    daily_statistics: tuple[HorizonStatisticsResponse, ...]
    episode_statistics: tuple[HorizonStatisticsResponse, ...]
    episodes: tuple[EpisodeTraceResponse, ...]


class StrategyTierInput(ApiModel):
    depth: PositiveRatio
    cash_fraction: PositiveRatio


class BonusContributionEventInput(ApiModel):
    month: CanonicalMonth
    kind: Literal["bonus"]
    amount: NonNegativeDecimal

    def to_domain(self) -> ContributionEvent:
        return ContributionEvent(
            month=self.month,
            kind=self.kind,
            amount=self.amount,
        )


class OverrideContributionEventInput(ApiModel):
    month: CanonicalMonth
    kind: Literal["override"]
    amount: NonNegativeDecimal

    def to_domain(self) -> ContributionEvent:
        return ContributionEvent(
            month=self.month,
            kind=self.kind,
            amount=self.amount,
        )


class PauseContributionEventInput(ApiModel):
    month: CanonicalMonth
    kind: Literal["pause"]
    amount: ZeroDecimal = Decimal("0")

    def to_domain(self) -> ContributionEvent:
        return ContributionEvent(
            month=self.month,
            kind=self.kind,
            amount=self.amount,
        )


class ResumeContributionEventInput(ApiModel):
    month: CanonicalMonth
    kind: Literal["resume"]
    amount: ZeroDecimal = Decimal("0")

    def to_domain(self) -> ContributionEvent:
        return ContributionEvent(
            month=self.month,
            kind=self.kind,
            amount=self.amount,
        )


ContributionEventVariant = Annotated[
    BonusContributionEventInput
    | OverrideContributionEventInput
    | PauseContributionEventInput
    | ResumeContributionEventInput,
    Field(discriminator="kind"),
]


class ContributionEventInput(RootModel[ContributionEventVariant]):
    def to_domain(self) -> ContributionEvent:
        return self.root.to_domain()


class StrategyBacktestRequest(VersionedModel):
    family_id: str = Field(min_length=1)
    target_symbol: str = Field(min_length=1)
    start: date
    end: date
    initial_cash: NonNegativeDecimal
    initial_shares: NonNegativeDecimal = Decimal("0")
    tiers: tuple[StrategyTierInput, ...] = Field(min_length=1)
    monthly_contribution: NonNegativeDecimal = Decimal("0")
    annual_contribution_growth: ContributionGrowth = Decimal("0")
    contribution_day: int = Field(default=1, ge=1, le=31)
    contribution_events: tuple[ContributionEventInput, ...] = ()
    cash_interest_rate: NonNegativeDecimal = Decimal("0")
    dividend_policy: Literal["cash", "reinvest"] = "cash"
    fixed_fee: NonNegativeDecimal = Decimal("0")
    fee_rate: UnitDecimal = Decimal("0")
    slippage: UnitDecimal = Decimal("0")
    name: str = "cash-pool"

    @model_validator(mode="after")
    def validate_strategy(self) -> Self:
        if self.end < self.start:
            raise ValueError("End date cannot precede start date")
        depths = tuple(tier.depth for tier in self.tiers)
        if len(set(depths)) != len(depths):
            raise ValueError("Tier depths must be unique")
        return self

    def to_domain(self) -> StrategyConfig:
        from drawdown_lab.analysis.cashflows import ContributionSchedule

        contributions = (
            ContributionSchedule(
                monthly=self.monthly_contribution,
                annual_growth=self.annual_contribution_growth,
                start=self.start,
                events=tuple(event.to_domain() for event in self.contribution_events),
                contribution_day=self.contribution_day,
            )
            if self.monthly_contribution > 0 or self.contribution_events
            else None
        )
        return StrategyConfig(
            start=self.start,
            end=self.end,
            initial_cash=self.initial_cash,
            initial_shares=self.initial_shares,
            tiers=tuple(ThresholdTier(tier.depth, tier.cash_fraction) for tier in self.tiers),
            contributions=contributions,
            cash_interest_rate=self.cash_interest_rate,
            dividend_policy=self.dividend_policy,
            fixed_fee=self.fixed_fee,
            fee_rate=self.fee_rate,
            slippage=self.slippage,
            name=self.name,
        )


class PerformanceResponse(ApiModel):
    xirr: float | None
    twr: float
    max_drawdown: float
    expected_shortfall_5: float
    longest_underwater_days: int
    cash_depletion_date: date | None
    deepest_tier_missed: Decimal | None


class TradeResponse(ApiModel):
    date: dt.date
    signal_date: dt.date
    threshold: Decimal | None
    cash_spent: Decimal
    shares_bought: Decimal
    raw_price: Decimal
    execution_price: Decimal
    fee: Decimal
    prototype_drawdown: Decimal | None
    target_drawdown: Decimal | None
    post_trade_cash: Decimal
    marker_profit_loss: Decimal
    kind: Literal["buy", "reinvest", "dca", "buy-and-hold"]


class PortfolioPointResponse(ApiModel):
    date: date
    cash: Decimal
    shares: Decimal
    close: Decimal
    value: Decimal
    external_flow: Decimal
    net_contributions: Decimal
    profit_loss: Decimal


class StrategyBacktestResponse(VersionedModel):
    family_id: str
    prototype_symbol: str
    prototype_source: Literal["benchmark", "proxy"]
    target_symbol: str
    source_label: Literal["trusted_local_cache"] = "trusted_local_cache"
    source_kind: Literal["actual"] = "actual"
    prototype_actual_last_session: date | None
    prototype_policy_cutoff: date | None
    target_actual_last_session: date | None
    target_policy_cutoff: date | None
    name: str
    ending_cash: Decimal
    ending_shares: Decimal
    trade_count: int
    dividend_income: Decimal
    contribution_total: Decimal
    interest_income: Decimal
    total_fees: Decimal
    pending_thresholds: tuple[Decimal, ...]
    missed_thresholds: tuple[Decimal, ...]
    trades: tuple[TradeResponse, ...]
    equity_curve: tuple[PortfolioPointResponse, ...]
    metrics: PerformanceResponse | None


class ProfileConstraintsInput(ApiModel):
    worst_5_floor: float
    max_early_depletion_rate: float = Field(ge=0.0, le=1.0)
    max_longest_trap_days: int = Field(ge=0)

    def to_domain(self) -> ProfileConstraints:
        return ProfileConstraints(
            worst_5_floor=self.worst_5_floor,
            max_early_depletion_rate=self.max_early_depletion_rate,
            max_longest_trap_days=self.max_longest_trap_days,
        )


class StrategyTemplateInput(ApiModel):
    start: date
    end: date
    initial_cash: NonNegativeDecimal
    initial_shares: NonNegativeDecimal = Decimal("0")
    monthly_contribution: NonNegativeDecimal = Decimal("0")
    annual_contribution_growth: ContributionGrowth = Decimal("0")
    contribution_day: int = Field(default=1, ge=1, le=31)
    contribution_events: tuple[ContributionEventInput, ...] = ()
    cash_interest_rate: NonNegativeDecimal = Decimal("0")
    dividend_policy: Literal["cash", "reinvest"] = "cash"
    fixed_fee: NonNegativeDecimal = Decimal("0")
    fee_rate: UnitDecimal = Decimal("0")
    slippage: UnitDecimal = Decimal("0")

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.end < self.start:
            raise ValueError("End date cannot precede start date")
        return self

    def to_domain(self) -> StrategyTemplate:
        return StrategyTemplate(
            start=self.start,
            end=self.end,
            initial_cash=self.initial_cash,
            initial_shares=self.initial_shares,
            monthly_contribution=self.monthly_contribution,
            annual_contribution_growth=self.annual_contribution_growth,
            contribution_day=self.contribution_day,
            contribution_events=tuple(event.to_domain() for event in self.contribution_events),
            cash_interest_rate=self.cash_interest_rate,
            dividend_policy=self.dividend_policy,
            fixed_fee=self.fixed_fee,
            fee_rate=self.fee_rate,
            slippage=self.slippage,
        )


class RatioSearchInput(ApiModel):
    minimum_basis_points: int = Field(default=0, ge=0, le=10_000)
    maximum_basis_points: int = Field(default=10_000, ge=0, le=10_000)
    step_basis_points: int = Field(default=1_000, gt=0, le=10_000)
    monotone: bool = True

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.maximum_basis_points < self.minimum_basis_points:
            raise ValueError("Maximum ratio must not be less than minimum ratio")
        if (self.maximum_basis_points - self.minimum_basis_points) % self.step_basis_points:
            raise ValueError("Ratio range must be divisible by step")
        return self

    def to_domain(self) -> RatioSearch:
        return RatioSearch(
            minimum_basis_points=self.minimum_basis_points,
            maximum_basis_points=self.maximum_basis_points,
            step_basis_points=self.step_basis_points,
            monotone=self.monotone,
        )


class WalkForwardInput(ApiModel):
    n_splits: int = Field(default=3, gt=0)
    minimum_train_sessions: int | None = Field(default=None, gt=0)
    test_size_sessions: int | None = Field(default=None, gt=0)
    minimum_train_independent_episodes: int = Field(default=1, ge=0)
    minimum_test_independent_episodes: int = Field(default=1, ge=0)

    def to_domain(self) -> WalkForwardSettings:
        return WalkForwardSettings(
            n_splits=self.n_splits,
            minimum_train_sessions=self.minimum_train_sessions,
            test_size_sessions=self.test_size_sessions,
            minimum_train_independent_episodes=(self.minimum_train_independent_episodes),
            minimum_test_independent_episodes=self.minimum_test_independent_episodes,
        )


class SyntheticStressRequest(ApiModel):
    enabled: bool = False
    annual_expense_ratio: float = Field(default=0.0, ge=0.0)
    max_portfolio_drawdown: float = Field(default=1.0, ge=0.0, le=1.0)
    max_longest_trap_days: int = Field(default=100_000, ge=0)

    def to_domain(self) -> SyntheticStressSettings:
        return SyntheticStressSettings(
            enabled=self.enabled,
            annual_expense_ratio=self.annual_expense_ratio,
            max_portfolio_drawdown=self.max_portfolio_drawdown,
            max_longest_trap_days=self.max_longest_trap_days,
        )


class OptimizationCreateRequest(VersionedModel):
    family_id: str = Field(min_length=1)
    target_symbol: str = Field(min_length=1)
    strategy: StrategyTemplateInput
    depths: tuple[PositiveRatio, ...] = Field(min_length=1)
    ratio_search: RatioSearchInput = RatioSearchInput()
    walk_forward: WalkForwardInput = WalkForwardInput()
    synthetic_stress: SyntheticStressRequest = SyntheticStressRequest()
    max_depth_levels: int = Field(default=8, ge=1, le=16)
    max_candidates: int = Field(default=14_641, ge=1, le=100_000)
    minimum_independent_episodes: int = Field(default=5, gt=0)
    neighbor_radius_basis_points: int = Field(default=1000, gt=0)
    isolated_peak_penalty: float = Field(default=1.25, ge=0.0)
    conservative: ProfileConstraintsInput = ProfileConstraintsInput(
        worst_5_floor=-0.10,
        max_early_depletion_rate=0.10,
        max_longest_trap_days=504,
    )
    balanced: ProfileConstraintsInput = ProfileConstraintsInput(
        worst_5_floor=-0.20,
        max_early_depletion_rate=0.25,
        max_longest_trap_days=756,
    )
    aggressive: ProfileConstraintsInput = ProfileConstraintsInput(
        worst_5_floor=-0.40,
        max_early_depletion_rate=0.50,
        max_longest_trap_days=1260,
    )

    @model_validator(mode="after")
    def validate_depths(self) -> Self:
        if len(set(self.depths)) != len(self.depths):
            raise ValueError("Depth ratios must be unique")
        return self

    def to_domain(
        self,
        *,
        prototype_symbol: str,
        target_leverage: int,
    ) -> HistoricalOptimizationRequest:
        return HistoricalOptimizationRequest(
            family_id=self.family_id,
            prototype_symbol=prototype_symbol,
            target_symbol=self.target_symbol,
            target_leverage=target_leverage,
            max_depth_levels=self.max_depth_levels,
            max_candidates=self.max_candidates,
            strategy=self.strategy.to_domain(),
            depths=self.depths,
            ratio_search=self.ratio_search.to_domain(),
            walk_forward=self.walk_forward.to_domain(),
            scoring=OptimizationRequest(
                minimum_independent_episodes=self.minimum_independent_episodes,
                neighbor_radius_basis_points=self.neighbor_radius_basis_points,
                isolated_peak_penalty=self.isolated_peak_penalty,
                conservative=self.conservative.to_domain(),
                balanced=self.balanced.to_domain(),
                aggressive=self.aggressive.to_domain(),
            ),
            synthetic_stress=self.synthetic_stress.to_domain(),
        )


class OptimizationAcceptedResponse(VersionedModel):
    job_id: str
    status: Literal["queued", "running", "cancelling"]


class JobResponse(VersionedModel):
    id: str
    kind: str
    status: Literal[
        "queued",
        "running",
        "cancelling",
        "succeeded",
        "failed",
        "cancelled",
    ]
    progress: int
    total: int
    cancellation_requested: bool
    result_id: str | None
    error: str | None
    created_at: str
    updated_at: str
    completed_at: str | None

    @classmethod
    def from_record(cls, record: JobRecord) -> JobResponse:
        return cls(
            id=record.id,
            kind=record.kind,
            status=record.status.value,
            progress=record.progress,
            total=record.total,
            cancellation_requested=record.cancellation_requested,
            result_id=record.result_id,
            error=record.error,
            created_at=record.created_at,
            updated_at=record.updated_at,
            completed_at=record.completed_at,
        )


class OptimizationProvenanceResponse(ApiModel):
    family_id: str
    prototype_symbol: str
    target_symbol: str
    source_kind: Literal["actual"]
    strategy_start: date
    strategy_end: date
    walk_forward_splits: int
    ratio_unit: Literal["basis_points"]


class SyntheticStressSummaryResponse(ApiModel):
    requested: bool
    evaluated_candidates: int
    passed_candidates: int


class WalkForwardFoldEvaluationResponse(ApiModel):
    fold_number: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    train_independent_episode_count: int
    test_independent_episode_count: int
    train_xirr: float
    test_xirr: float
    training_selected: bool


class OptimizationCandidateResponse(ApiModel):
    ratios: tuple[int, ...]
    fold_oos_xirr: tuple[float, ...]
    oos_xirr: float
    stability_score: float
    stability_adjusted_xirr: float
    neighbor_count: int
    worst_5_return: float
    early_depletion_rate: float
    longest_trap_days: int
    synthetic_stress_pass: bool | None
    pareto_member: bool
    fold_evaluations: tuple[WalkForwardFoldEvaluationResponse, ...]
    walk_forward_eligible: bool
    recommendation_labels: tuple[
        Literal["conservative", "balanced", "aggressive"],
        ...,
    ]


class RecommendationResponse(ApiModel):
    profile: Literal["conservative", "balanced", "aggressive"]
    ratios: tuple[int, ...]
    oos_xirr: float
    stability_adjusted_xirr: float


class OptimizationResultPayload(VersionedModel):
    mode: Literal["formal", "exploration_only"]
    exploration_only: bool
    independent_episode_count: int
    provenance: OptimizationProvenanceResponse
    candidates: tuple[OptimizationCandidateResponse, ...]
    recommendations: tuple[RecommendationResponse, ...]
    synthetic_stress: SyntheticStressSummaryResponse


class LegacyOptimizationPayload(ApiModel):
    payload_type: Literal["legacy"] = "legacy"
    stored_schema_version: str
    raw_json: str


class ResultResponse(VersionedModel):
    id: str
    job_id: str
    kind: str
    payload: OptimizationResultPayload | LegacyOptimizationPayload
    created_at: str

    @classmethod
    def from_record(cls, record: ResultRecord) -> ResultResponse:
        if record.schema_version != SCHEMA_VERSION:
            payload: OptimizationResultPayload | LegacyOptimizationPayload = (
                LegacyOptimizationPayload(
                    stored_schema_version=record.schema_version,
                    raw_json=record.raw_json,
                )
            )
        else:
            try:
                payload = OptimizationResultPayload.model_validate(record.payload)
            except ValidationError:
                payload = LegacyOptimizationPayload(
                    stored_schema_version=record.schema_version,
                    raw_json=record.raw_json,
                )
        return cls(
            schema_version=SCHEMA_VERSION,
            id=record.id,
            job_id=record.job_id,
            kind=record.kind,
            payload=payload,
            created_at=record.created_at,
        )


class ResultListResponse(VersionedModel):
    results: tuple[ResultResponse, ...]


ReportFormat = Literal["html", "json", "csv"]


class ReportExportRequest(VersionedModel):
    result_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    formats: tuple[ReportFormat, ...] = Field(
        default=("html", "json", "csv"),
        description=(
            "Requested views. A canonical JSON artifact is always included "
            "to make every bundle independently verifiable."
        ),
    )

    @model_validator(mode="after")
    def validate_export(self) -> Self:
        if ".." in self.result_id:
            raise ValueError("result_id contains unsafe characters")
        if not self.formats:
            raise ValueError("At least one report format is required")
        if len(set(self.formats)) != len(self.formats):
            raise ValueError("Report formats must be unique")
        return self


class ReportArtifactResponse(ApiModel):
    relative_path: str
    media_type: str
    sha256: str
    size_bytes: int


class ReportDataLineageResponse(ApiModel):
    provider: str
    fetched_at: datetime
    sha256: str
    policy_cutoff: date
    actual_session_cutoff: date
    classification: Literal["actual", "synthetic"]


class ReportLineageResponse(ApiModel):
    engine_version: str
    git_commit: str
    code_state: Literal["clean", "dirty", "injected"]
    data_hashes: dict[str, str]
    data_lineage: dict[str, ReportDataLineageResponse]
    policy_cutoff: date
    actual_session_cutoff: date
    result_sha256: str
    generated_at: datetime
    timezone: str
    parameters: dict[str, object]
    parameters_sha256: str
    analysis_boundary: dict[str, str]
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]


class ReportExportResponse(VersionedModel):
    export_id: str
    result_id: str
    artifacts: dict[str, ReportArtifactResponse]
    lineage: ReportLineageResponse

    @classmethod
    def from_manifest(cls, manifest: ExportManifest) -> ReportExportResponse:
        return cls(
            export_id=manifest.export_id,
            result_id=manifest.result_id,
            artifacts={
                name: ReportArtifactResponse(
                    relative_path=artifact.relative_path,
                    media_type=artifact.media_type,
                    sha256=artifact.sha256,
                    size_bytes=artifact.size_bytes,
                )
                for name, artifact in manifest.artifacts.items()
            },
            lineage=ReportLineageResponse.model_validate(
                manifest.provenance.as_dict()
            ),
        )


class ReportContentResponse(ApiModel):
    status: Literal["not_yet_exported"]
    message: str
    result_id: str
    optimization: OptimizationResultPayload


class ExportedReportContentResponse(ApiModel):
    status: Literal["exported"]
    message: str
    result_id: str
    export_id: str
    artifacts: dict[str, ReportArtifactResponse]
    lineage: ReportLineageResponse
    optimization: OptimizationResultPayload


class LegacyReportContent(ApiModel):
    content_type: Literal["legacy"] = "legacy"
    stored_schema_version: str
    raw_json: str


class ReportResponse(VersionedModel):
    id: str
    result_id: str | None
    title: str
    export_status: Literal["not_yet_exported", "exported"]
    content: (
        ReportContentResponse
        | ExportedReportContentResponse
        | LegacyReportContent
    )
    created_at: str

    @classmethod
    def from_record(cls, record: ReportRecord) -> ReportResponse:
        export_status = cast(
            Literal["not_yet_exported", "exported"],
            record.export_status,
        )
        if record.schema_version != SCHEMA_VERSION:
            content: (
                ReportContentResponse
                | ExportedReportContentResponse
                | LegacyReportContent
            ) = LegacyReportContent(
                stored_schema_version=record.schema_version,
                raw_json=record.raw_json,
            )
        else:
            try:
                if record.export_status == "exported":
                    content = ExportedReportContentResponse.model_validate(
                        record.content
                    )
                else:
                    content = ReportContentResponse.model_validate(record.content)
            except ValidationError:
                content = LegacyReportContent(
                    stored_schema_version=record.schema_version,
                    raw_json=record.raw_json,
                )
        return cls(
            schema_version=SCHEMA_VERSION,
            id=record.id,
            result_id=record.result_id,
            title=record.title,
            export_status=export_status,
            content=content,
            created_at=record.created_at,
        )


class ReportListResponse(VersionedModel):
    reports: tuple[ReportResponse, ...]


class ValidationIssue(ApiModel):
    type: str
    loc: tuple[str | int, ...]
    msg: str
    input_json: str | None = None


class ErrorResponse(VersionedModel):
    detail: str | tuple[ValidationIssue, ...]
