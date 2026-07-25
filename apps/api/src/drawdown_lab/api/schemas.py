from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal, cast

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from drawdown_lab.analysis.evidence import EvidenceRequest
from drawdown_lab.analysis.strategy import StrategyConfig, ThresholdTier
from drawdown_lab.data.models import MarketFrame
from drawdown_lab.optimization.scoring import (
    AnalysisFrames,
    CandidateScore,
    OptimizationRequest,
    ProfileConstraints,
    SyntheticStress,
)
from drawdown_lab.storage.jobs import JobRecord, ReportRecord, ResultRecord

SCHEMA_VERSION: Literal["1.0"] = "1.0"


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


class MarketBar(ApiModel):
    date: date
    raw_open: float
    raw_high: float
    raw_low: float
    raw_close: float
    price_open: float
    price_high: float
    price_low: float
    price_close: float
    adj_close: float
    dividend_raw: float = 0.0
    split_ratio: float = 1.0


class MarketFramePayload(ApiModel):
    bars: tuple[MarketBar, ...] = Field(min_length=1)

    def to_domain(self) -> MarketFrame:
        rows = [bar.model_dump() for bar in self.bars]
        frame = pd.DataFrame(rows)
        frame.index = pd.DatetimeIndex(frame.pop("date"))
        return MarketFrame(frame)


class EvidenceAnalyzeRequest(VersionedModel):
    threshold: float
    horizons: tuple[int, ...] = (21, 63, 126, 252, 756, 1260)
    prototype: MarketFramePayload
    traded: MarketFramePayload

    def to_domain(self) -> tuple[EvidenceRequest, MarketFrame, MarketFrame]:
        return (
            EvidenceRequest(threshold=self.threshold, horizons=self.horizons),
            self.prototype.to_domain(),
            self.traded.to_domain(),
        )


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
    depth: Decimal
    cash_fraction: Decimal


class StrategyBacktestRequest(VersionedModel):
    start: date
    end: date | None = None
    initial_cash: Decimal
    tiers: tuple[StrategyTierInput, ...] = Field(min_length=1)
    prototype: MarketFramePayload
    traded: MarketFramePayload
    name: str = "cash-pool"

    def to_domain(self) -> tuple[StrategyConfig, MarketFrame, MarketFrame]:
        return (
            StrategyConfig(
                start=self.start,
                end=self.end,
                initial_cash=self.initial_cash,
                tiers=tuple(
                    ThresholdTier(tier.depth, tier.cash_fraction) for tier in self.tiers
                ),
                name=self.name,
            ),
            self.prototype.to_domain(),
            self.traded.to_domain(),
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


class OptimizationCandidateInput(ApiModel):
    ratios: tuple[int, ...] = Field(min_length=1)
    fold_oos_xirr: tuple[float, ...] = Field(min_length=1)
    worst_5_return: float
    early_depletion_rate: float
    longest_trap_days: int

    def to_domain(self) -> CandidateScore:
        return CandidateScore(
            ratios=self.ratios,
            fold_oos_xirr=self.fold_oos_xirr,
            worst_5_return=self.worst_5_return,
            early_depletion_rate=self.early_depletion_rate,
            longest_trap_days=self.longest_trap_days,
        )


class SyntheticStressInput(ApiModel):
    ratios: tuple[int, ...] = Field(min_length=1)
    passed: bool

    def to_domain(self) -> SyntheticStress:
        return SyntheticStress(self.ratios, self.passed)


class OptimizationCreateRequest(VersionedModel):
    candidates: tuple[OptimizationCandidateInput, ...] = Field(min_length=1)
    independent_episode_count: int = Field(ge=0)
    synthetic_stress: tuple[SyntheticStressInput, ...] = ()
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

    def to_domain(self) -> tuple[OptimizationRequest, AnalysisFrames]:
        return (
            OptimizationRequest(
                minimum_independent_episodes=self.minimum_independent_episodes,
                neighbor_radius_basis_points=self.neighbor_radius_basis_points,
                isolated_peak_penalty=self.isolated_peak_penalty,
                conservative=self.conservative.to_domain(),
                balanced=self.balanced.to_domain(),
                aggressive=self.aggressive.to_domain(),
            ),
            AnalysisFrames(
                actual_candidates=tuple(
                    candidate.to_domain() for candidate in self.candidates
                ),
                independent_episode_count=self.independent_episode_count,
                synthetic_stress=tuple(
                    stress.to_domain() for stress in self.synthetic_stress
                ),
            ),
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
        "completed",
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


class ResultResponse(VersionedModel):
    id: str
    job_id: str
    kind: str
    payload: dict[str, Any]
    created_at: str

    @classmethod
    def from_record(cls, record: ResultRecord) -> ResultResponse:
        schema_version = cast(Literal["1.0"], record.schema_version)
        return cls(
            schema_version=schema_version,
            id=record.id,
            job_id=record.job_id,
            kind=record.kind,
            payload=record.payload,
            created_at=record.created_at,
        )


class ResultListResponse(VersionedModel):
    results: tuple[ResultResponse, ...]


class ReportResponse(VersionedModel):
    id: str
    result_id: str | None
    title: str
    export_status: Literal["not_yet_exported", "exported"]
    content: dict[str, Any]
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
            content=record.content,
            created_at=record.created_at,
        )


class ReportListResponse(VersionedModel):
    reports: tuple[ReportResponse, ...]


class ErrorResponse(VersionedModel):
    detail: str
