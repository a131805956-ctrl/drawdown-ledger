from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import numpy as np

from drawdown_lab.analysis.drawdown import analyze_threshold
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
    entry_date: date
    entry_price: Decimal
    forward_returns: tuple[ForwardReturn, ...]
    mae: float
    mfe: float
    recovery_sessions: int | None
    v_recovered: bool

    def total_return(self, horizon_sessions: int) -> float | None:
        for result in self.forward_returns:
            if result.horizon_sessions == horizon_sessions:
                return result.total_return
        raise KeyError(f"Horizon {horizon_sessions} was not requested")


@dataclass(frozen=True, slots=True)
class HorizonStatistics:
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
    n_day: int
    n_episode: int
    episodes: tuple[EpisodeEvidence, ...]
    horizon_statistics: tuple[HorizonStatistics, ...]

    @property
    def n_executed_episode(self) -> int:
        return len(self.episodes)


def _summarize_horizons(
    request: EvidenceRequest,
    episodes: tuple[EpisodeEvidence, ...],
    rng: np.random.Generator,
) -> tuple[HorizonStatistics, ...]:
    summaries: list[HorizonStatistics] = []
    for horizon in request.horizons:
        values = [
            value
            for episode in episodes
            if (value := episode.total_return(horizon)) is not None
        ]
        if not values:
            summaries.append(
                HorizonStatistics(
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
    threshold_analysis = analyze_threshold(prototype, request.threshold)
    classified = classify_episodes(prototype, (request.threshold,))
    observations: list[EpisodeEvidence] = []
    max_horizon = max(request.horizons)

    for episode in classified:
        entry = first_later_valid_entry(traded.data, episode.signal_date)
        if entry is None:
            continue
        forward_returns = calculate_forward_returns(traded.data, entry, request.horizons)
        mae, mfe = adjusted_excursions(traded.data, entry, max_horizon)
        observations.append(
            EpisodeEvidence(
                threshold=episode.threshold,
                cycle_id=episode.cycle_id,
                signal_date=episode.signal_date,
                entry_date=entry.entry_date,
                entry_price=entry.adjusted_open,
                forward_returns=forward_returns,
                mae=mae,
                mfe=mfe,
                recovery_sessions=episode.recovery_sessions,
                v_recovered=episode.v_recovered,
            )
        )

    episode_evidence = tuple(observations)
    generator = rng if rng is not None else np.random.default_rng(request.bootstrap_seed)
    return EvidenceReport(
        request=request,
        n_day=threshold_analysis.n_day,
        n_episode=threshold_analysis.n_episode,
        episodes=episode_evidence,
        horizon_statistics=_summarize_horizons(request, episode_evidence, generator),
    )
