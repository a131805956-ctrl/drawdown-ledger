from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from drawdown_lab.data.models import MarketFrame
from drawdown_lab.optimization.evaluator import (
    HistoricalOptimizationRequest,
    OptimizationCancelled,
    RatioSearch,
    StrategyTemplate,
    SyntheticStressSettings,
    WalkForwardSettings,
    optimize_market_history,
)
from drawdown_lab.optimization.scoring import OptimizationRequest, ProfileConstraints


def _frame(prices: tuple[float, ...]) -> MarketFrame:
    index = pd.bdate_range("2020-01-01", periods=len(prices))
    values = pd.Series(prices, index=index, dtype=float)
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
        index=index,
    )
    return MarketFrame(data)


PROTOTYPE_PRICES = (
    100,
    101,
    102,
    103,
    104,
    105,
    106,
    107,
    108,
    80,
    85,
    90,
    95,
    100,
    105,
    109,
    110,
    80,
    85,
    90,
    95,
    100,
    105,
    111,
)
RISING_TARGET = (
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    90,
    80,
    90,
    100,
    110,
    120,
    130,
    100,
    90,
    80,
    90,
    100,
    110,
    120,
    130,
)
FALLING_TARGET = (
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    100,
    90,
    100,
    90,
    80,
    70,
    60,
    50,
    100,
    90,
    100,
    90,
    80,
    70,
    60,
    50,
)


def _request() -> HistoricalOptimizationRequest:
    broad = ProfileConstraints(-1.0, 1.0, 10_000)
    return HistoricalOptimizationRequest(
        family_id="nasdaq-100",
        prototype_symbol="QQQ",
        target_symbol="TQQQ",
        target_leverage=3,
        strategy=StrategyTemplate(
            start=date(2020, 1, 1),
            end=date(2020, 2, 3),
            initial_cash=Decimal("1000"),
        ),
        depths=(Decimal("0.20"),),
        ratio_search=RatioSearch(
            minimum_basis_points=0,
            maximum_basis_points=10_000,
            step_basis_points=10_000,
            monotone=True,
        ),
        walk_forward=WalkForwardSettings(n_splits=2, test_size_sessions=8),
        scoring=OptimizationRequest(
            minimum_independent_episodes=1,
            isolated_peak_penalty=0.0,
            conservative=broad,
            balanced=broad,
            aggressive=broad,
        ),
    )


def _balanced_ratios(result: object) -> tuple[int, ...]:
    recommendations = getattr(result, "recommendations")
    return next(row.ratios for row in recommendations if row.profile == "balanced")


def test_real_market_path_changes_simulator_backed_recommendation() -> None:
    request = _request()
    prototype = _frame(PROTOTYPE_PRICES)

    rising = optimize_market_history(request, prototype, _frame(RISING_TARGET))
    falling = optimize_market_history(request, prototype, _frame(FALLING_TARGET))

    assert _balanced_ratios(rising) == (10_000,)
    assert _balanced_ratios(falling) == (0,)
    assert rising.independent_episode_count == 2
    assert falling.independent_episode_count == 2
    assert rising.candidates[1].fold_oos_xirr != falling.candidates[1].fold_oos_xirr


def test_progress_checkpoints_follow_actual_candidate_fold_simulations() -> None:
    checkpoints: list[tuple[int, int]] = []

    optimize_market_history(
        _request(),
        _frame(PROTOTYPE_PRICES),
        _frame(RISING_TARGET),
        evaluation_batch_size=1,
        on_batch=lambda completed, total: checkpoints.append((completed, total)) or True,
    )

    assert checkpoints == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_cancellation_stops_at_real_evaluation_batch_without_result() -> None:
    checkpoints: list[int] = []

    def cancel_after_two(completed: int, _: int) -> bool:
        checkpoints.append(completed)
        return completed < 2

    with pytest.raises(OptimizationCancelled):
        optimize_market_history(
            _request(),
            _frame(PROTOTYPE_PRICES),
            _frame(RISING_TARGET),
            evaluation_batch_size=1,
            on_batch=cancel_after_two,
        )

    assert checkpoints == [1, 2]


def test_synthetic_stress_is_evaluated_separately_without_changing_ranking() -> None:
    request = _request()
    prototype = _frame(PROTOTYPE_PRICES)
    target = _frame(RISING_TARGET)

    actual_only = optimize_market_history(request, prototype, target)
    stressed = optimize_market_history(
        replace(
            request,
            synthetic_stress=SyntheticStressSettings(
                enabled=True,
                max_portfolio_drawdown=1.0,
            ),
        ),
        prototype,
        target,
    )

    assert stressed.recommendations == actual_only.recommendations
    assert stressed.synthetic_stress.requested is True
    assert stressed.synthetic_stress.evaluated_candidates == 2
    assert all(row.synthetic_stress_pass is not None for row in stressed.candidates)
