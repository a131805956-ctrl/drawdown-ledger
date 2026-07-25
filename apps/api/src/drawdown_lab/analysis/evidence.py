from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol, cast

import numpy as np
import pandas as pd

from drawdown_lab.analysis.episodes import classify_episodes
from drawdown_lab.analysis.forward_returns import (
    ForwardReturn,
    adjusted_excursions,
    calculate_forward_returns,
    first_later_valid_entry,
)
from drawdown_lab.analysis.risk import block_bootstrap_interval, expected_shortfall_5
from drawdown_lab.data.models import MarketFrame, validate_market_frame
from drawdown_lab.domain.instruments import Instrument

DEFAULT_HORIZON_SESSIONS = (21, 63, 126, 252, 756, 1260)
DAILY_OVERLAP_WARNING = (
    "Daily cohort observations overlap and are non-independent; "
    "confidence intervals use chronological block bootstrap."
)

SampleKind = Literal["daily_overlapping", "independent_episodes"]


@dataclass(frozen=True, slots=True)
class EvidenceRequest:
    threshold: float
    horizons: tuple[int, ...] = DEFAULT_HORIZON_SESSIONS
    instrument: Instrument | None = None
    bootstrap_iterations: int = 1_000
    bootstrap_block_size: int = 3
    bootstrap_seed: int = 7749
    confidence: float = 0.95

    def __post_init__(self) -> None:
        if self.threshold <= 0.0 or self.threshold > 1.0:
            raise ValueError("Evidence threshold must be a positive ratio no greater than 1")
        if not self.horizons or any(horizon <= 0 for horizon in self.horizons):
            raise ValueError("Evidence horizons must be positive session counts")
        if len(set(self.horizons)) != len(self.horizons):
            raise ValueError("Evidence horizons must be unique")
        if self.bootstrap_iterations <= 0 or self.bootstrap_block_size <= 0:
            raise ValueError("Bootstrap iterations and block size must be positive")
        if not 0.0 < self.confidence < 1.0:
            raise ValueError("Confidence must be between zero and one")


@dataclass(frozen=True, slots=True)
class EpisodeEvidence:
    threshold: float
    cycle_id: int
    signal_date: date
    entry_date: date | None
    entry_price: Decimal | None
    forward_returns: tuple[ForwardReturn, ...]
    mae: float | None
    mfe: float | None
    recovery_sessions: int | None
    v_recovered: bool

    def total_return(self, horizon_sessions: int) -> float | None:
        for result in self.forward_returns:
            if result.horizon_sessions == horizon_sessions:
                return result.total_return
        raise KeyError(f"Horizon {horizon_sessions} was not requested")


@dataclass(frozen=True, slots=True)
class DailyObservation:
    threshold: float
    signal_date: date
    entry_date: date | None
    entry_price: Decimal | None
    forward_returns: tuple[ForwardReturn, ...]
    mae: float | None
    mfe: float | None

    def total_return(self, horizon_sessions: int) -> float | None:
        for result in self.forward_returns:
            if result.horizon_sessions == horizon_sessions:
                return result.total_return
        raise KeyError(f"Horizon {horizon_sessions} was not requested")


@dataclass(frozen=True, slots=True)
class HorizonStatistics:
    sample_kind: SampleKind
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


@dataclass(frozen=True, slots=True)
class EvidenceReport:
    request: EvidenceRequest
    daily_observations: tuple[DailyObservation, ...]
    episodes: tuple[EpisodeEvidence, ...]
    daily_statistics: tuple[HorizonStatistics, ...]
    episode_statistics: tuple[HorizonStatistics, ...]

    @property
    def n_day(self) -> int:
        return len(self.daily_observations)

    @property
    def n_episode(self) -> int:
        return len(self.episodes)

    @property
    def n_executed_episode(self) -> int:
        return sum(episode.entry_date is not None for episode in self.episodes)

    @property
    def horizon_statistics(self) -> tuple[HorizonStatistics, ...]:
        """Backward-compatible name for independent episode statistics."""

        return self.episode_statistics


class _ReturnObservation(Protocol):
    def total_return(self, horizon_sessions: int) -> float | None: ...


def _summarize_horizons(
    request: EvidenceRequest,
    rows: tuple[_ReturnObservation, ...],
    rng: np.random.Generator,
    *,
    sample_kind: SampleKind,
) -> tuple[HorizonStatistics, ...]:
    summaries: list[HorizonStatistics] = []
    independent = sample_kind == "independent_episodes"
    overlap_warning = None if independent else DAILY_OVERLAP_WARNING
    for horizon in request.horizons:
        values = [
            value
            for row in rows
            if (value := row.total_return(horizon)) is not None
        ]
        if not values:
            summaries.append(
                HorizonStatistics(
                    sample_kind=sample_kind,
                    independent=independent,
                    overlap_warning=overlap_warning,
                    horizon_sessions=horizon,
                    n=0,
                    mean_total_return=None,
                    median_total_return=None,
                    win_rate=None,
                    expected_shortfall_5=None,
                    confidence_lower=None,
                    confidence_upper=None,
                )
            )
            continue
        interval = block_bootstrap_interval(
            values,
            rng=rng,
            block_size=request.bootstrap_block_size,
            iterations=request.bootstrap_iterations,
            confidence=request.confidence,
        )
        observations = np.asarray(values, dtype=float)
        summaries.append(
            HorizonStatistics(
                sample_kind=sample_kind,
                independent=independent,
                overlap_warning=overlap_warning,
                horizon_sessions=horizon,
                n=len(values),
                mean_total_return=float(observations.mean()),
                median_total_return=float(np.median(observations)),
                win_rate=float((observations > 0.0).mean()),
                expected_shortfall_5=expected_shortfall_5(values),
                confidence_lower=interval.lower,
                confidence_upper=interval.upper,
            )
        )
    return tuple(summaries)


def _empty_forward_returns(horizons: tuple[int, ...]) -> tuple[ForwardReturn, ...]:
    return tuple(
        ForwardReturn(horizon_sessions=horizon, exit_date=None, total_return=None)
        for horizon in horizons
    )


def _execution_metrics(
    traded: MarketFrame,
    signal_date: date,
    request: EvidenceRequest,
) -> tuple[
    date | None,
    Decimal | None,
    tuple[ForwardReturn, ...],
    float | None,
    float | None,
]:
    entry = first_later_valid_entry(traded.data, signal_date)
    if entry is None:
        return None, None, _empty_forward_returns(request.horizons), None, None
    forward_returns = calculate_forward_returns(traded.data, entry, request.horizons)
    mae, mfe = adjusted_excursions(traded.data, entry, max(request.horizons))
    return entry.entry_date, entry.adjusted_open, forward_returns, mae, mfe


def _daily_signal_dates(prototype: MarketFrame, threshold: float) -> tuple[date, ...]:
    close = prototype.data["price_close"].astype(float)
    qualifying = close <= close.cummax() * (1.0 - threshold)
    return tuple(
        cast(pd.Timestamp, timestamp).date()
        for timestamp in close.index[qualifying]
    )


def analyze_evidence(
    request: EvidenceRequest,
    prototype: MarketFrame,
    traded: MarketFrame,
    *,
    rng: np.random.Generator | None = None,
) -> EvidenceReport:
    """Analyze independent prototype drawdown episodes against traded ETF returns."""

    validate_market_frame(prototype)
    validate_market_frame(traded)
    classified = classify_episodes(prototype, (request.threshold,))
    daily_observations: list[DailyObservation] = []
    episode_observations: list[EpisodeEvidence] = []

    for signal_date in _daily_signal_dates(prototype, request.threshold):
        entry_date, entry_price, forward_returns, mae, mfe = _execution_metrics(
            traded,
            signal_date,
            request,
        )
        daily_observations.append(
            DailyObservation(
                threshold=request.threshold,
                signal_date=signal_date,
                entry_date=entry_date,
                entry_price=entry_price,
                forward_returns=forward_returns,
                mae=mae,
                mfe=mfe,
            )
        )

    for episode in classified:
        entry_date, entry_price, forward_returns, mae, mfe = _execution_metrics(
            traded,
            episode.signal_date,
            request,
        )
        episode_observations.append(
            EpisodeEvidence(
                threshold=episode.threshold,
                cycle_id=episode.cycle_id,
                signal_date=episode.signal_date,
                entry_date=entry_date,
                entry_price=entry_price,
                forward_returns=forward_returns,
                mae=mae,
                mfe=mfe,
                recovery_sessions=episode.recovery_sessions,
                v_recovered=episode.v_recovered,
            )
        )

    daily_evidence = tuple(daily_observations)
    episode_evidence = tuple(episode_observations)
    generator = rng if rng is not None else np.random.default_rng(request.bootstrap_seed)
    return EvidenceReport(
        request=request,
        daily_observations=daily_evidence,
        episodes=episode_evidence,
        daily_statistics=_summarize_horizons(
            request,
            daily_evidence,
            generator,
            sample_kind="daily_overlapping",
        ),
        episode_statistics=_summarize_horizons(
            request,
            episode_evidence,
            generator,
            sample_kind="independent_episodes",
        ),
    )
