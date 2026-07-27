from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest
from drawdown_lab.analysis.leverage import (
    default_synthetic_model_parameters,
    synthetic_daily_reset_nav,
)
from drawdown_lab.data.models import MarketFrame
from drawdown_lab.optimization import evaluator as evaluator_module
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


def test_synthetic_stress_frame_uses_daily_friction_defaults() -> None:
    prototype = _frame((100, 110, 100))
    stressed = evaluator_module._synthetic_market_frame(
        prototype,
        leverage=3,
        annual_expense_ratio=0.0095,
    )
    management, financing, roll, transaction = default_synthetic_model_parameters(3)
    expected = synthetic_daily_reset_nav(
        prototype,
        3,
        annual_management_fee=management,
        daily_financing_drag=financing,
        daily_roll_drag=roll,
        daily_transaction_drag=transaction,
    )
    assert stressed.data["price_close"].tolist() == pytest.approx(
        expected.nav.tolist()
    )


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
        walk_forward=WalkForwardSettings(
            n_splits=2,
            test_size_sessions=8,
            minimum_train_independent_episodes=0,
            minimum_test_independent_episodes=1,
        ),
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

    assert checkpoints == [
        (1, 8),
        (2, 8),
        (3, 8),
        (4, 8),
        (5, 8),
        (6, 8),
        (7, 8),
        (8, 8),
    ]


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


def test_walk_forward_simulates_and_persists_both_train_and_test_ranges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, date, date]] = []
    real_simulate = evaluator_module.simulate_strategy

    def recording_simulate(*args: object, **kwargs: object) -> object:
        config = args[0]
        calls.append((config.name, config.start, config.end))
        return real_simulate(*args, **kwargs)

    monkeypatch.setattr(evaluator_module, "simulate_strategy", recording_simulate)

    result = optimize_market_history(
        _request(),
        _frame(PROTOTYPE_PRICES),
        _frame(RISING_TARGET),
    )

    assert len(calls) == 8
    assert sum("-train" in name for name, _, _ in calls) == 4
    assert sum("-test" in name for name, _, _ in calls) == 4
    folds = result.candidates[0].fold_evaluations
    assert [
        (
            fold.train_independent_episode_count,
            fold.test_independent_episode_count,
        )
        for fold in folds
    ] == [
        (0, 1),
        (1, 1),
    ]
    assert all(fold.train_end < fold.test_start for fold in folds)
    assert all(fold.train_start <= fold.train_end for fold in folds)
    assert all(fold.test_start <= fold.test_end for fold in folds)


def test_future_only_changes_oos_but_not_prior_training_selection() -> None:
    request = _request()
    prototype = _frame(PROTOTYPE_PRICES)
    original = optimize_market_history(request, prototype, _frame(RISING_TARGET))
    future_changed_prices = (*RISING_TARGET[:16], *FALLING_TARGET[16:])
    future_changed = optimize_market_history(
        request,
        prototype,
        _frame(future_changed_prices),
    )

    for original_candidate, changed_candidate in zip(
        original.candidates,
        future_changed.candidates,
        strict=True,
    ):
        original_fold = original_candidate.fold_evaluations[1]
        changed_fold = changed_candidate.fold_evaluations[1]
        assert original_fold.train_xirr == changed_fold.train_xirr
        assert original_fold.training_selected == changed_fold.training_selected
    assert (
        original.candidates[1].fold_evaluations[1].test_xirr
        != future_changed.candidates[1].fold_evaluations[1].test_xirr
    )


def test_each_fold_must_meet_configured_train_and_test_episode_minimums() -> None:
    request = replace(
        _request(),
        walk_forward=WalkForwardSettings(
            n_splits=2,
            test_size_sessions=8,
            minimum_train_independent_episodes=1,
            minimum_test_independent_episodes=1,
        ),
    )

    result = optimize_market_history(
        request,
        _frame(PROTOTYPE_PRICES),
        _frame(RISING_TARGET),
    )

    assert result.mode == "exploration_only"
    assert result.recommendations == ()
    assert all(candidate.walk_forward_eligible is False for candidate in result.candidates)
