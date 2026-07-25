from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from drawdown_lab.analysis.evidence import EvidenceRequest
from drawdown_lab.analysis.strategy import StrategyConfig, ThresholdTier
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
from drawdown_lab.storage.jobs import JobRecord, ReportRecord, ResultRecord

SCHEMA_VERSION: Literal["1.0"] = "1.0"
PositiveRatio = Annotated[Decimal, Field(gt=0, le=1)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]
UnitDecimal = Annotated[Decimal, Field(ge=0, le=1)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class EvidenceAnalyzeRequest(VersionedModel):
    family_id: str = Field(min_length=1)
    target_symbol: str = Field(min_length=1)
    threshold: float = Field(gt=0.0, le=1.0)
    horizons: tuple[int, ...] = (21, 63, 126, 252, 756, 1260)

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


class EvidenceAnalyzeResponse(VersionedModel):
    n_day: int
    n_episode: int
    n_executed_episode: int
    daily_statistics: tuple[HorizonStatisticsResponse, ...]
    episode_statistics: tuple[HorizonStatisticsResponse, ...]


class StrategyTierInput(ApiModel):
    depth: PositiveRatio
    cash_fraction: PositiveRatio


class StrategyBacktestRequest(VersionedModel):
    family_id: str = Field(min_length=1)
    target_symbol: str = Field(min_length=1)
    start: date
    end: date
    initial_cash: NonNegativeDecimal
    initial_shares: NonNegativeDecimal = Decimal("0")
    tiers: tuple[StrategyTierInput, ...] = Field(min_length=1)
    monthly_contribution: NonNegativeDecimal = Decimal("0")
    annual_contribution_growth: Decimal = Field(default=Decimal("0"), gt=-1)
    contribution_day: int = Field(default=1, ge=1, le=31)
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
                contribution_day=self.contribution_day,
            )
            if self.monthly_contribution > 0
            else None
        )
        return StrategyConfig(
            start=self.start,
            end=self.end,
            initial_cash=self.initial_cash,
            initial_shares=self.initial_shares,
            tiers=tuple(
                ThresholdTier(tier.depth, tier.cash_fraction) for tier in self.tiers
            ),
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


class StrategyBacktestResponse(VersionedModel):
    name: str
    ending_cash: Decimal
    ending_shares: Decimal
    trade_count: int
    pending_thresholds: tuple[Decimal, ...]
    missed_thresholds: tuple[Decimal, ...]
    metrics: PerformanceResponse | None


class ProfileConstraintsInput(ApiModel):
    worst_5_floor: float
    max_early_depletion_rate: float
    max_longest_trap_days: int

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
    annual_contribution_growth: Decimal = Field(default=Decimal("0"), gt=-1)
    contribution_day: int = Field(default=1, ge=1, le=31)
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
        if (
            self.maximum_basis_points - self.minimum_basis_points
        ) % self.step_basis_points:
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

    def to_domain(self) -> WalkForwardSettings:
        return WalkForwardSettings(
            n_splits=self.n_splits,
            minimum_train_sessions=self.minimum_train_sessions,
            test_size_sessions=self.test_size_sessions,
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


class ResultResponse(VersionedModel):
    id: str
    job_id: str
    kind: str
    payload: OptimizationResultPayload
    created_at: str

    @classmethod
    def from_record(cls, record: ResultRecord) -> ResultResponse:
        schema_version = cast(Literal["1.0"], record.schema_version)
        return cls(
            schema_version=schema_version,
            id=record.id,
            job_id=record.job_id,
            kind=record.kind,
            payload=OptimizationResultPayload.model_validate(record.payload),
            created_at=record.created_at,
        )


class ResultListResponse(VersionedModel):
    results: tuple[ResultResponse, ...]


class ReportContentResponse(ApiModel):
    status: Literal["not_yet_exported"]
    message: str
    result_id: str
    optimization: OptimizationResultPayload


class ReportResponse(VersionedModel):
    id: str
    result_id: str | None
    title: str
    export_status: Literal["not_yet_exported", "exported"]
    content: ReportContentResponse
    created_at: str

    @classmethod
    def from_record(cls, record: ReportRecord) -> ReportResponse:
        schema_version = cast(Literal["1.0"], record.schema_version)
        export_status = cast(
            Literal["not_yet_exported", "exported"],
            record.export_status,
        )
        return cls(
            schema_version=schema_version,
            id=record.id,
            result_id=record.result_id,
            title=record.title,
            export_status=export_status,
            content=ReportContentResponse.model_validate(record.content),
            created_at=record.created_at,
        )


class ReportListResponse(VersionedModel):
    reports: tuple[ReportResponse, ...]


class ErrorResponse(VersionedModel):
    detail: str
