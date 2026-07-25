from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any, Literal, cast

import pandas as pd

from drawdown_lab.analysis.cashflows import ContributionEvent, ContributionSchedule
from drawdown_lab.analysis.episodes import classify_episodes
from drawdown_lab.analysis.leverage import synthetic_daily_reset_nav
from drawdown_lab.analysis.strategy import (
    DividendPolicy,
    StrategyConfig,
    ThresholdTier,
    simulate_strategy,
)
from drawdown_lab.data.models import MarketFrame, validate_market_frame
from drawdown_lab.domain.money import as_decimal, quantize_money
from drawdown_lab.optimization.grid import count_ratio_grid, generate_ratio_grid
from drawdown_lab.optimization.scoring import (
    AnalysisFrames,
    CandidateScore,
    OptimizationProvenance,
    OptimizationRequest,
    OptimizationResult,
    SyntheticStress,
    SyntheticStressSummary,
    WalkForwardFoldEvaluation,
    optimize,
)
from drawdown_lab.optimization.walk_forward import expanding_window_splits

BatchCallback = Callable[[int, int], bool]


class OptimizationCancelled(RuntimeError):
    """A formal optimization stopped at an evaluation batch boundary."""


@dataclass(frozen=True, slots=True)
class StrategyTemplate:
    start: date
    end: date
    initial_cash: Decimal
    initial_shares: Decimal = Decimal("0")
    monthly_contribution: Decimal = Decimal("0")
    annual_contribution_growth: Decimal = Decimal("0")
    contribution_day: int = 1
    contribution_events: tuple[ContributionEvent, ...] = ()
    cash_interest_rate: Decimal = Decimal("0")
    dividend_policy: DividendPolicy | str = DividendPolicy.CASH
    fixed_fee: Decimal = Decimal("0")
    fee_rate: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        object.__setattr__(self, "initial_cash", quantize_money(self.initial_cash))
        object.__setattr__(self, "initial_shares", as_decimal(self.initial_shares))
        object.__setattr__(
            self,
            "monthly_contribution",
            quantize_money(self.monthly_contribution),
        )
        object.__setattr__(
            self,
            "annual_contribution_growth",
            as_decimal(self.annual_contribution_growth),
        )
        object.__setattr__(
            self,
            "cash_interest_rate",
            as_decimal(self.cash_interest_rate),
        )
        object.__setattr__(
            self,
            "contribution_events",
            tuple(self.contribution_events),
        )
        object.__setattr__(self, "fixed_fee", quantize_money(self.fixed_fee))
        object.__setattr__(self, "fee_rate", as_decimal(self.fee_rate))
        object.__setattr__(self, "slippage", as_decimal(self.slippage))
        object.__setattr__(self, "dividend_policy", DividendPolicy(self.dividend_policy))
        if self.end < self.start:
            raise ValueError("End date cannot precede start date")
        if self.initial_cash < 0 or self.initial_shares < 0:
            raise ValueError("Initial balances cannot be negative")
        if self.monthly_contribution < 0 or self.annual_contribution_growth <= -1:
            raise ValueError("Contribution inputs are invalid")
        if not 1 <= self.contribution_day <= 31:
            raise ValueError("Contribution day must be between 1 and 31")
        if (
            self.cash_interest_rate < 0
            or self.fixed_fee < 0
            or self.fee_rate < 0
            or self.slippage < 0
        ):
            raise ValueError("Interest, fees, and slippage cannot be negative")
        ContributionSchedule(
            monthly=self.monthly_contribution,
            annual_growth=self.annual_contribution_growth,
            start=self.start,
            events=self.contribution_events,
            contribution_day=self.contribution_day,
        )


@dataclass(frozen=True, slots=True)
class RatioSearch:
    minimum_basis_points: int = 0
    maximum_basis_points: int = 10_000
    step_basis_points: int = 1_000
    monotone: bool = True

    def candidate_count(self, levels: int) -> int:
        return count_ratio_grid(
            levels=levels,
            minimum_basis_points=self.minimum_basis_points,
            maximum_basis_points=self.maximum_basis_points,
            step_basis_points=self.step_basis_points,
            monotone=self.monotone,
        )

    def iter_vectors(self, levels: int) -> Iterator[tuple[int, ...]]:
        return generate_ratio_grid(
            levels=levels,
            minimum_basis_points=self.minimum_basis_points,
            maximum_basis_points=self.maximum_basis_points,
            step_basis_points=self.step_basis_points,
            monotone=self.monotone,
        )


@dataclass(frozen=True, slots=True)
class WalkForwardSettings:
    n_splits: int = 3
    minimum_train_sessions: int | None = None
    test_size_sessions: int | None = None
    minimum_train_independent_episodes: int = 1
    minimum_test_independent_episodes: int = 1

    def __post_init__(self) -> None:
        if self.n_splits <= 0:
            raise ValueError("Walk-forward split count must be positive")
        if self.minimum_train_sessions is not None and self.minimum_train_sessions <= 0:
            raise ValueError("Minimum train sessions must be positive")
        if self.test_size_sessions is not None and self.test_size_sessions <= 0:
            raise ValueError("Test sessions must be positive")
        if (
            self.minimum_train_independent_episodes < 0
            or self.minimum_test_independent_episodes < 0
        ):
            raise ValueError("Walk-forward episode minimums cannot be negative")


@dataclass(frozen=True, slots=True)
class SyntheticStressSettings:
    enabled: bool = False
    annual_expense_ratio: float = 0.0
    max_portfolio_drawdown: float = 1.0
    max_longest_trap_days: int = 100_000

    def __post_init__(self) -> None:
        if self.annual_expense_ratio < 0.0:
            raise ValueError("Synthetic expense ratio cannot be negative")
        if not 0.0 <= self.max_portfolio_drawdown <= 1.0:
            raise ValueError("Synthetic drawdown limit must be between zero and one")
        if self.max_longest_trap_days < 0:
            raise ValueError("Synthetic trap limit cannot be negative")


@dataclass(frozen=True, slots=True)
class HistoricalOptimizationRequest:
    family_id: str
    prototype_symbol: str
    target_symbol: str
    target_leverage: int
    strategy: StrategyTemplate
    depths: tuple[Decimal, ...]
    ratio_search: RatioSearch
    walk_forward: WalkForwardSettings
    scoring: OptimizationRequest
    synthetic_stress: SyntheticStressSettings = SyntheticStressSettings()
    max_depth_levels: int = 8
    max_candidates: int = 14_641

    def __post_init__(self) -> None:
        normalized_depths = tuple(sorted(as_decimal(depth) for depth in self.depths))
        object.__setattr__(self, "depths", normalized_depths)
        if not self.family_id or not self.prototype_symbol or not self.target_symbol:
            raise ValueError("Optimization provenance symbols are required")
        if self.target_leverage <= 0:
            raise ValueError("Target leverage must be positive")
        if (
            not normalized_depths
            or len(set(normalized_depths)) != len(normalized_depths)
            or any(depth <= 0 or depth > 1 for depth in normalized_depths)
        ):
            raise ValueError("Depths must be unique positive ratios no greater than one")
        if self.max_depth_levels <= 0 or len(normalized_depths) > self.max_depth_levels:
            raise ValueError(
                f"Depth count {len(normalized_depths)} exceeds maximum {self.max_depth_levels}"
            )
        if self.max_candidates <= 0:
            raise ValueError("Maximum candidate count must be positive")
        candidate_count = self.ratio_search.candidate_count(len(normalized_depths))
        if candidate_count > self.max_candidates:
            raise ValueError(
                f"Candidate count {candidate_count} exceeds maximum {self.max_candidates}"
            )


def _profile_payload(profile: object) -> dict[str, object]:
    constraints = cast(Any, profile)
    return {
        "worst_5_floor": constraints.worst_5_floor,
        "max_early_depletion_rate": constraints.max_early_depletion_rate,
        "max_longest_trap_days": constraints.max_longest_trap_days,
    }


def historical_request_to_payload(
    request: HistoricalOptimizationRequest,
) -> dict[str, Any]:
    """Serialize every formal input needed to safely replay an optimization."""

    strategy = request.strategy
    return {
        "family_id": request.family_id,
        "prototype_symbol": request.prototype_symbol,
        "target_symbol": request.target_symbol,
        "target_leverage": request.target_leverage,
        "max_depth_levels": request.max_depth_levels,
        "max_candidates": request.max_candidates,
        "strategy": {
            "start": strategy.start.isoformat(),
            "end": strategy.end.isoformat(),
            "initial_cash": str(strategy.initial_cash),
            "initial_shares": str(strategy.initial_shares),
            "monthly_contribution": str(strategy.monthly_contribution),
            "annual_contribution_growth": str(strategy.annual_contribution_growth),
            "contribution_day": strategy.contribution_day,
            "contribution_events": [
                {
                    "month": event.month.isoformat(),
                    "kind": event.kind,
                    "amount": str(event.amount),
                }
                for event in strategy.contribution_events
            ],
            "cash_interest_rate": str(strategy.cash_interest_rate),
            "dividend_policy": DividendPolicy(strategy.dividend_policy).value,
            "fixed_fee": str(strategy.fixed_fee),
            "fee_rate": str(strategy.fee_rate),
            "slippage": str(strategy.slippage),
        },
        "depths": [str(depth) for depth in request.depths],
        "ratio_search": {
            "minimum_basis_points": request.ratio_search.minimum_basis_points,
            "maximum_basis_points": request.ratio_search.maximum_basis_points,
            "step_basis_points": request.ratio_search.step_basis_points,
            "monotone": request.ratio_search.monotone,
        },
        "walk_forward": {
            "n_splits": request.walk_forward.n_splits,
            "minimum_train_sessions": request.walk_forward.minimum_train_sessions,
            "test_size_sessions": request.walk_forward.test_size_sessions,
            "minimum_train_independent_episodes": (
                request.walk_forward.minimum_train_independent_episodes
            ),
            "minimum_test_independent_episodes": (
                request.walk_forward.minimum_test_independent_episodes
            ),
        },
        "scoring": {
            "minimum_independent_episodes": request.scoring.minimum_independent_episodes,
            "neighbor_radius_basis_points": request.scoring.neighbor_radius_basis_points,
            "isolated_peak_penalty": request.scoring.isolated_peak_penalty,
            "conservative": _profile_payload(request.scoring.conservative),
            "balanced": _profile_payload(request.scoring.balanced),
            "aggressive": _profile_payload(request.scoring.aggressive),
        },
        "synthetic_stress": {
            "enabled": request.synthetic_stress.enabled,
            "annual_expense_ratio": request.synthetic_stress.annual_expense_ratio,
            "max_portfolio_drawdown": request.synthetic_stress.max_portfolio_drawdown,
            "max_longest_trap_days": request.synthetic_stress.max_longest_trap_days,
        },
    }


def historical_request_from_payload(
    payload: dict[str, Any],
) -> HistoricalOptimizationRequest:
    """Reconstruct a validated domain request from persisted deterministic JSON."""

    from drawdown_lab.optimization.scoring import ProfileConstraints

    strategy = cast(dict[str, Any], payload["strategy"])
    contribution_events = cast(
        list[dict[str, Any]],
        strategy.get("contribution_events", []),
    )
    ratio_search = cast(dict[str, Any], payload["ratio_search"])
    walk_forward = cast(dict[str, Any], payload["walk_forward"])
    scoring = cast(dict[str, Any], payload["scoring"])
    synthetic = cast(dict[str, Any], payload["synthetic_stress"])

    def profile(name: str) -> ProfileConstraints:
        values = cast(dict[str, Any], scoring[name])
        return ProfileConstraints(
            worst_5_floor=float(values["worst_5_floor"]),
            max_early_depletion_rate=float(values["max_early_depletion_rate"]),
            max_longest_trap_days=int(values["max_longest_trap_days"]),
        )

    return HistoricalOptimizationRequest(
        family_id=str(payload["family_id"]),
        prototype_symbol=str(payload["prototype_symbol"]),
        target_symbol=str(payload["target_symbol"]),
        target_leverage=int(payload["target_leverage"]),
        max_depth_levels=int(payload.get("max_depth_levels", 8)),
        max_candidates=int(payload.get("max_candidates", 14_641)),
        strategy=StrategyTemplate(
            start=date.fromisoformat(str(strategy["start"])),
            end=date.fromisoformat(str(strategy["end"])),
            initial_cash=Decimal(str(strategy["initial_cash"])),
            initial_shares=Decimal(str(strategy["initial_shares"])),
            monthly_contribution=Decimal(str(strategy["monthly_contribution"])),
            annual_contribution_growth=Decimal(str(strategy["annual_contribution_growth"])),
            contribution_day=int(strategy["contribution_day"]),
            contribution_events=tuple(
                ContributionEvent(
                    month=date.fromisoformat(str(event["month"])).replace(day=1),
                    kind=cast(
                        Literal["bonus", "override", "pause", "resume"],
                        str(event["kind"]),
                    ),
                    amount=quantize_money(Decimal(str(event.get("amount", "0")))),
                )
                for event in contribution_events
            ),
            cash_interest_rate=Decimal(str(strategy["cash_interest_rate"])),
            dividend_policy=str(strategy["dividend_policy"]),
            fixed_fee=Decimal(str(strategy["fixed_fee"])),
            fee_rate=Decimal(str(strategy["fee_rate"])),
            slippage=Decimal(str(strategy["slippage"])),
        ),
        depths=tuple(Decimal(str(value)) for value in payload["depths"]),
        ratio_search=RatioSearch(
            minimum_basis_points=int(ratio_search["minimum_basis_points"]),
            maximum_basis_points=int(ratio_search["maximum_basis_points"]),
            step_basis_points=int(ratio_search["step_basis_points"]),
            monotone=bool(ratio_search["monotone"]),
        ),
        walk_forward=WalkForwardSettings(
            n_splits=int(walk_forward["n_splits"]),
            minimum_train_sessions=(
                int(walk_forward["minimum_train_sessions"])
                if walk_forward["minimum_train_sessions"] is not None
                else None
            ),
            test_size_sessions=(
                int(walk_forward["test_size_sessions"])
                if walk_forward["test_size_sessions"] is not None
                else None
            ),
            minimum_train_independent_episodes=int(
                walk_forward.get("minimum_train_independent_episodes", 1)
            ),
            minimum_test_independent_episodes=int(
                walk_forward.get("minimum_test_independent_episodes", 1)
            ),
        ),
        scoring=OptimizationRequest(
            minimum_independent_episodes=int(scoring["minimum_independent_episodes"]),
            neighbor_radius_basis_points=int(scoring["neighbor_radius_basis_points"]),
            isolated_peak_penalty=float(scoring["isolated_peak_penalty"]),
            conservative=profile("conservative"),
            balanced=profile("balanced"),
            aggressive=profile("aggressive"),
        ),
        synthetic_stress=SyntheticStressSettings(
            enabled=bool(synthetic["enabled"]),
            annual_expense_ratio=float(synthetic["annual_expense_ratio"]),
            max_portfolio_drawdown=float(synthetic["max_portfolio_drawdown"]),
            max_longest_trap_days=int(synthetic["max_longest_trap_days"]),
        ),
    )


def _dates_in_range(frame: MarketFrame, start: date, end: date) -> tuple[date, ...]:
    dates = tuple(
        cast(pd.Timestamp, timestamp).date()
        for timestamp in frame.data.loc[pd.Timestamp(start) : pd.Timestamp(end)].index
    )
    if not dates:
        raise ValueError("No trusted sessions exist inside the requested date range")
    return dates


def _strategy_config(
    request: HistoricalOptimizationRequest,
    ratios: tuple[int, ...],
    *,
    start: date,
    end: date,
    name: str,
) -> StrategyConfig:
    tiers = tuple(
        ThresholdTier(depth, Decimal(ratio) / Decimal(10_000))
        for depth, ratio in zip(request.depths, ratios, strict=True)
        if ratio > 0
    )
    template = request.strategy
    contributions = (
        ContributionSchedule(
            monthly=template.monthly_contribution,
            annual_growth=template.annual_contribution_growth,
            start=template.start,
            events=template.contribution_events,
            contribution_day=template.contribution_day,
        )
        if template.monthly_contribution > 0 or template.contribution_events
        else None
    )
    return StrategyConfig(
        start=start,
        end=end,
        initial_cash=template.initial_cash,
        initial_shares=template.initial_shares,
        tiers=tiers,
        contributions=contributions,
        cash_interest_rate=template.cash_interest_rate,
        dividend_policy=template.dividend_policy,
        fixed_fee=template.fixed_fee,
        fee_rate=template.fee_rate,
        slippage=template.slippage,
        name=name,
    )


def _synthetic_market_frame(
    prototype: MarketFrame,
    *,
    leverage: int,
    annual_expense_ratio: float,
) -> MarketFrame:
    synthetic = synthetic_daily_reset_nav(
        prototype,
        leverage,
        annual_expense_ratio=annual_expense_ratio,
    )
    values = synthetic.nav.astype(float)
    data = pd.DataFrame(
        {
            "raw_open": values,
            "raw_high": values,
            "raw_low": values,
            "raw_close": values,
            "price_open": values,
            "price_high": values,
            "price_low": values,
            "price_close": values,
            "adj_close": values,
            "dividend_raw": 0.0,
            "split_ratio": 1.0,
        },
        index=values.index,
    )
    return MarketFrame(data)


def _checkpoint(
    completed: int,
    total: int,
    *,
    batch_size: int,
    on_batch: BatchCallback | None,
) -> None:
    if on_batch is None:
        return
    if completed % batch_size == 0 or completed == total:
        if not on_batch(completed, total):
            raise OptimizationCancelled("Optimization cancelled at evaluation boundary")


def optimize_market_history(
    request: HistoricalOptimizationRequest,
    prototype: MarketFrame,
    traded: MarketFrame,
    *,
    evaluation_batch_size: int = 25,
    on_batch: BatchCallback | None = None,
) -> OptimizationResult:
    """Generate and evaluate every parameter vector against trusted market history."""

    if evaluation_batch_size <= 0:
        raise ValueError("Evaluation batch size must be positive")
    validate_market_frame(prototype)
    validate_market_frame(traded)
    dates = _dates_in_range(
        traded,
        request.strategy.start,
        request.strategy.end,
    )
    splits = expanding_window_splits(
        dates,
        n_splits=request.walk_forward.n_splits,
        min_train_size=request.walk_forward.minimum_train_sessions,
        test_size=request.walk_forward.test_size_sessions,
    )
    vector_count = request.ratio_search.candidate_count(len(request.depths))
    synthetic_frame = (
        _synthetic_market_frame(
            prototype,
            leverage=request.target_leverage,
            annual_expense_ratio=request.synthetic_stress.annual_expense_ratio,
        )
        if request.synthetic_stress.enabled
        else None
    )
    total = vector_count * len(splits) * 2 + (vector_count if synthetic_frame is not None else 0)
    completed = 0
    actual_candidates: list[CandidateScore] = []
    synthetic_rows: list[SyntheticStress] = []
    episode_frame = MarketFrame(
        prototype.data.loc[
            pd.Timestamp(request.strategy.start) : pd.Timestamp(request.strategy.end)
        ].copy()
    )
    episodes = classify_episodes(episode_frame, (float(min(request.depths)),))

    def episode_count(start: date, end: date) -> int:
        return sum(start <= episode.signal_date <= end for episode in episodes)

    for ratios in request.ratio_search.iter_vectors(len(request.depths)):
        fold_xirr: list[float] = []
        fold_worst_tail: list[float] = []
        fold_depletion: list[float] = []
        fold_trap_days: list[int] = []
        fold_evaluations: list[WalkForwardFoldEvaluation] = []
        walk_forward_eligible = True
        for split_number, split in enumerate(splits, start=1):
            train_start = dates[min(split.train_indices)]
            train_end = dates[max(split.train_indices)]
            test_start = dates[min(split.test_indices)]
            test_end = dates[max(split.test_indices)]
            train_episode_count = episode_count(train_start, train_end)
            test_episode_count = episode_count(test_start, test_end)
            walk_forward_eligible = walk_forward_eligible and (
                train_episode_count >= request.walk_forward.minimum_train_independent_episodes
                and test_episode_count >= request.walk_forward.minimum_test_independent_episodes
            )
            train_result = simulate_strategy(
                _strategy_config(
                    request,
                    ratios,
                    start=train_start,
                    end=train_end,
                    name=f"candidate-{ratios}-fold-{split_number}-train",
                ),
                prototype,
                traded,
            )
            if train_result.metrics is None:
                raise RuntimeError("Strategy simulation did not produce performance metrics")
            train_metrics = train_result.metrics
            train_xirr = train_metrics.xirr if train_metrics.xirr is not None else train_metrics.twr
            completed += 1
            _checkpoint(
                completed,
                total,
                batch_size=evaluation_batch_size,
                on_batch=on_batch,
            )
            test_result = simulate_strategy(
                _strategy_config(
                    request,
                    ratios,
                    start=test_start,
                    end=test_end,
                    name=f"candidate-{ratios}-fold-{split_number}-test",
                ),
                prototype,
                traded,
            )
            if test_result.metrics is None:
                raise RuntimeError("Strategy simulation did not produce performance metrics")
            test_metrics = test_result.metrics
            test_xirr = test_metrics.xirr if test_metrics.xirr is not None else test_metrics.twr
            fold_xirr.append(test_xirr)
            fold_worst_tail.append(test_metrics.expected_shortfall_5)
            fold_depletion.append(1.0 if test_metrics.cash_depletion_date is not None else 0.0)
            fold_trap_days.append(test_metrics.longest_underwater_days)
            fold_evaluations.append(
                WalkForwardFoldEvaluation(
                    fold_number=split_number,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    train_independent_episode_count=train_episode_count,
                    test_independent_episode_count=test_episode_count,
                    train_xirr=train_xirr,
                    test_xirr=test_xirr,
                )
            )
            completed += 1
            _checkpoint(
                completed,
                total,
                batch_size=evaluation_batch_size,
                on_batch=on_batch,
            )
        actual_candidates.append(
            CandidateScore(
                ratios=ratios,
                fold_oos_xirr=tuple(fold_xirr),
                worst_5_return=min(fold_worst_tail),
                early_depletion_rate=sum(fold_depletion) / len(fold_depletion),
                longest_trap_days=max(fold_trap_days),
                fold_evaluations=tuple(fold_evaluations),
                walk_forward_eligible=walk_forward_eligible,
            )
        )

        if synthetic_frame is not None:
            synthetic_result = simulate_strategy(
                _strategy_config(
                    request,
                    ratios,
                    start=request.strategy.start,
                    end=request.strategy.end,
                    name=f"synthetic-stress-{ratios}",
                ),
                prototype,
                synthetic_frame,
            )
            if synthetic_result.metrics is None:
                raise RuntimeError("Synthetic stress did not produce performance metrics")
            synthetic_rows.append(
                SyntheticStress(
                    ratios=ratios,
                    passed=(
                        synthetic_result.metrics.max_drawdown
                        <= request.synthetic_stress.max_portfolio_drawdown
                        and synthetic_result.metrics.longest_underwater_days
                        <= request.synthetic_stress.max_longest_trap_days
                        and synthetic_result.metrics.cash_depletion_date is None
                    ),
                )
            )
            completed += 1
            _checkpoint(
                completed,
                total,
                batch_size=evaluation_batch_size,
                on_batch=on_batch,
            )

    for fold_index in range(len(splits)):
        eligible = tuple(
            candidate for candidate in actual_candidates if candidate.walk_forward_eligible
        )
        if not eligible:
            break
        selected = max(
            eligible,
            key=lambda candidate: (
                candidate.fold_evaluations[fold_index].train_xirr,
                tuple(-ratio for ratio in candidate.ratios),
            ),
        )
        actual_candidates = [
            replace(
                candidate,
                fold_evaluations=tuple(
                    replace(
                        fold,
                        training_selected=(
                            fold_index == index and candidate.ratios == selected.ratios
                        ),
                    )
                    if fold_index == index
                    else fold
                    for index, fold in enumerate(candidate.fold_evaluations)
                ),
            )
            for candidate in actual_candidates
        ]

    independent_episode_count = len(episodes)
    ranked = optimize(
        request.scoring,
        AnalysisFrames(
            actual_candidates=tuple(actual_candidates),
            independent_episode_count=independent_episode_count,
            synthetic_stress=tuple(synthetic_rows),
        ),
    )
    return replace(
        ranked,
        exploration_only=ranked.mode == "exploration_only",
        provenance=OptimizationProvenance(
            family_id=request.family_id,
            prototype_symbol=request.prototype_symbol,
            target_symbol=request.target_symbol,
            strategy_start=request.strategy.start,
            strategy_end=request.strategy.end,
            walk_forward_splits=len(splits),
        ),
        synthetic_stress=SyntheticStressSummary(
            requested=request.synthetic_stress.enabled,
            evaluated_candidates=len(synthetic_rows),
            passed_candidates=sum(row.passed for row in synthetic_rows),
        ),
    )
