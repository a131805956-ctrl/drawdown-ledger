from __future__ import annotations

from dataclasses import dataclass, replace
from math import fsum, isfinite
from statistics import median
from typing import Literal

from drawdown_lab.optimization.pareto import pareto_membership

ProfileName = Literal["conservative", "balanced", "aggressive"]
OptimizationMode = Literal["formal", "exploration_only"]


def _validate_ratios(ratios: tuple[int, ...]) -> None:
    if not ratios:
        raise ValueError("A candidate must contain at least one allocation ratio")
    if any(isinstance(value, bool) or value < 0 or value > 10_000 for value in ratios):
        raise ValueError("Allocation ratios must be integer basis points from 0 through 10000")


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """Actual-history out-of-sample measurements for one parameter vector."""

    ratios: tuple[int, ...]
    fold_oos_xirr: tuple[float, ...]
    worst_5_return: float
    early_depletion_rate: float
    longest_trap_days: int

    def __post_init__(self) -> None:
        _validate_ratios(self.ratios)
        if not self.fold_oos_xirr or not all(isfinite(value) for value in self.fold_oos_xirr):
            raise ValueError("Candidate requires finite out-of-sample fold XIRRs")
        if not isfinite(self.worst_5_return):
            raise ValueError("Worst-five-percent return must be finite")
        if not 0.0 <= self.early_depletion_rate <= 1.0:
            raise ValueError("Early depletion rate must be between zero and one")
        if self.longest_trap_days < 0:
            raise ValueError("Longest trap duration cannot be negative")

    @property
    def oos_xirr(self) -> float:
        return fsum(self.fold_oos_xirr) / len(self.fold_oos_xirr)


@dataclass(frozen=True, slots=True)
class SyntheticStress:
    ratios: tuple[int, ...]
    passed: bool

    def __post_init__(self) -> None:
        _validate_ratios(self.ratios)


@dataclass(frozen=True, slots=True)
class AnalysisFrames:
    """Precomputed actual OOS scores plus separately labelled synthetic stress outcomes."""

    actual_candidates: tuple[CandidateScore, ...]
    independent_episode_count: int
    synthetic_stress: tuple[SyntheticStress, ...] = ()

    def __post_init__(self) -> None:
        if not self.actual_candidates:
            raise ValueError("At least one actual-history candidate is required")
        ratios = tuple(candidate.ratios for candidate in self.actual_candidates)
        if len(set(ratios)) != len(ratios):
            raise ValueError("Actual-history candidate ratios must be unique")
        if self.independent_episode_count < 0:
            raise ValueError("Independent episode count cannot be negative")
        synthetic_ratios = tuple(stress.ratios for stress in self.synthetic_stress)
        if len(set(synthetic_ratios)) != len(synthetic_ratios):
            raise ValueError("Synthetic stress ratios must be unique")


@dataclass(frozen=True, slots=True)
class ProfileConstraints:
    worst_5_floor: float
    max_early_depletion_rate: float
    max_longest_trap_days: int

    def accepts(self, candidate: CandidateScore) -> bool:
        return (
            candidate.worst_5_return >= self.worst_5_floor
            and candidate.early_depletion_rate <= self.max_early_depletion_rate
            and candidate.longest_trap_days <= self.max_longest_trap_days
        )


@dataclass(frozen=True, slots=True)
class OptimizationRequest:
    minimum_independent_episodes: int = 5
    neighbor_radius_basis_points: int = 1_000
    isolated_peak_penalty: float = 1.25
    conservative: ProfileConstraints = ProfileConstraints(-0.10, 0.10, 504)
    balanced: ProfileConstraints = ProfileConstraints(-0.20, 0.25, 756)
    aggressive: ProfileConstraints = ProfileConstraints(-0.40, 0.50, 1_260)

    def __post_init__(self) -> None:
        if self.minimum_independent_episodes <= 0:
            raise ValueError("Independent episode minimum must be positive")
        if self.neighbor_radius_basis_points <= 0:
            raise ValueError("Neighbor radius must be positive")
        if self.isolated_peak_penalty < 0.0:
            raise ValueError("Isolated peak penalty cannot be negative")


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    ratios: tuple[int, ...]
    oos_xirr: float
    stability_score: float
    stability_adjusted_xirr: float
    neighbor_count: int
    worst_5_return: float
    early_depletion_rate: float
    longest_trap_days: int
    synthetic_stress_pass: bool | None
    pareto_member: bool
    recommendation_labels: tuple[ProfileName, ...] = ()


@dataclass(frozen=True, slots=True)
class Recommendation:
    profile: ProfileName
    ratios: tuple[int, ...]
    oos_xirr: float
    stability_adjusted_xirr: float


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    mode: OptimizationMode
    independent_episode_count: int
    candidates: tuple[ScoredCandidate, ...]
    recommendations: tuple[Recommendation, ...]


def _is_neighbor(
    left: tuple[int, ...],
    right: tuple[int, ...],
    radius: int,
) -> bool:
    return len(left) == len(right) and 0 < sum(
        abs(left_value - right_value)
        for left_value, right_value in zip(left, right, strict=True)
    ) <= radius


def _score_candidates(
    candidates: tuple[CandidateScore, ...],
    request: OptimizationRequest,
    synthetic_stress: tuple[SyntheticStress, ...] = (),
) -> tuple[ScoredCandidate, ...]:
    stress_by_ratio = {stress.ratios: stress.passed for stress in synthetic_stress}
    pareto_flags = pareto_membership(candidates)
    scored: list[ScoredCandidate] = []
    for candidate, is_pareto in zip(candidates, pareto_flags, strict=True):
        neighbors = tuple(
            other
            for other in candidates
            if _is_neighbor(
                candidate.ratios,
                other.ratios,
                request.neighbor_radius_basis_points,
            )
        )
        if neighbors:
            neighbor_score = float(median(other.oos_xirr for other in neighbors))
        elif len(candidates) > 1:
            nearest_distance = min(
                sum(
                    abs(left - right)
                    for left, right in zip(candidate.ratios, other.ratios, strict=True)
                )
                for other in candidates
                if other is not candidate
            )
            nearest = tuple(
                other
                for other in candidates
                if other is not candidate
                and sum(
                    abs(left - right)
                    for left, right in zip(candidate.ratios, other.ratios, strict=True)
                )
                == nearest_distance
            )
            neighbor_score = float(median(other.oos_xirr for other in nearest))
        else:
            neighbor_score = candidate.oos_xirr
        isolated_excess = max(0.0, candidate.oos_xirr - neighbor_score)
        scored.append(
            ScoredCandidate(
                ratios=candidate.ratios,
                oos_xirr=candidate.oos_xirr,
                stability_score=neighbor_score,
                stability_adjusted_xirr=(
                    candidate.oos_xirr - request.isolated_peak_penalty * isolated_excess
                ),
                neighbor_count=len(neighbors),
                worst_5_return=candidate.worst_5_return,
                early_depletion_rate=candidate.early_depletion_rate,
                longest_trap_days=candidate.longest_trap_days,
                synthetic_stress_pass=stress_by_ratio.get(candidate.ratios),
                pareto_member=is_pareto,
            )
        )
    return tuple(scored)


def _choose_for_profile(
    actual: tuple[CandidateScore, ...],
    scored: tuple[ScoredCandidate, ...],
    constraints: ProfileConstraints,
) -> ScoredCandidate | None:
    eligible_ratios = {candidate.ratios for candidate in actual if constraints.accepts(candidate)}
    eligible = tuple(row for row in scored if row.ratios in eligible_ratios)
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda row: (
            row.stability_adjusted_xirr,
            row.neighbor_count,
            row.worst_5_return,
            -row.early_depletion_rate,
            -row.longest_trap_days,
            tuple(-value for value in row.ratios),
        ),
    )


def choose_balanced_candidate(
    candidates: tuple[CandidateScore, ...],
    request: OptimizationRequest | None = None,
) -> ScoredCandidate | None:
    effective_request = request or OptimizationRequest()
    scored = _score_candidates(candidates, effective_request)
    return _choose_for_profile(candidates, scored, effective_request.balanced)


def optimize(
    request: OptimizationRequest,
    frames: AnalysisFrames,
) -> OptimizationResult:
    """Rank actual-history OOS candidates; synthetic history is stress-only metadata."""

    scored = _score_candidates(frames.actual_candidates, request, frames.synthetic_stress)
    if frames.independent_episode_count < request.minimum_independent_episodes:
        return OptimizationResult(
            mode="exploration_only",
            independent_episode_count=frames.independent_episode_count,
            candidates=scored,
            recommendations=(),
        )

    selections: list[tuple[ProfileName, ScoredCandidate]] = []
    profile_constraints: tuple[tuple[ProfileName, ProfileConstraints], ...] = (
        ("conservative", request.conservative),
        ("balanced", request.balanced),
        ("aggressive", request.aggressive),
    )
    for profile, constraints in profile_constraints:
        candidate = _choose_for_profile(frames.actual_candidates, scored, constraints)
        if candidate is not None:
            selections.append((profile, candidate))

    labels_by_ratios: dict[tuple[int, ...], list[ProfileName]] = {}
    recommendations: list[Recommendation] = []
    for profile, candidate in selections:
        labels_by_ratios.setdefault(candidate.ratios, []).append(profile)
        recommendations.append(
            Recommendation(
                profile=profile,
                ratios=candidate.ratios,
                oos_xirr=candidate.oos_xirr,
                stability_adjusted_xirr=candidate.stability_adjusted_xirr,
            )
        )
    labelled = tuple(
        replace(
            candidate,
            recommendation_labels=tuple(labels_by_ratios.get(candidate.ratios, ())),
        )
        for candidate in scored
    )
    return OptimizationResult(
        mode="formal",
        independent_episode_count=frames.independent_episode_count,
        candidates=labelled,
        recommendations=tuple(recommendations),
    )
