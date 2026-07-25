from __future__ import annotations

from drawdown_lab.optimization.scoring import (
    AnalysisFrames,
    CandidateScore,
    OptimizationRequest,
    ProfileConstraints,
    SyntheticStress,
    choose_balanced_candidate,
    optimize,
)


def _candidate(
    ratios: tuple[int, ...],
    xirr: float,
    *,
    worst_5: float = -0.12,
    depletion: float = 0.05,
    trap_days: int = 300,
) -> CandidateScore:
    return CandidateScore(
        ratios=ratios,
        fold_oos_xirr=(xirr - 0.005, xirr + 0.005),
        worst_5_return=worst_5,
        early_depletion_rate=depletion,
        longest_trap_days=trap_days,
    )


def test_isolated_peak_loses_to_stable_neighbor_plateau() -> None:
    spike = _candidate((1000, 2000, 3000, 4000), 0.23)
    plateau = _candidate((2000, 3000, 4000, 5000), 0.18)
    neighbors = (
        _candidate((2000, 3000, 4000, 4000), 0.18),
        _candidate((2000, 3000, 4000, 6000), 0.18),
        _candidate((2000, 3000, 5000, 5000), 0.18),
    )

    result = choose_balanced_candidate((spike, plateau, *neighbors))

    assert result is not None
    assert result.ratios == (2000, 3000, 4000, 5000)
    assert result.stability_adjusted_xirr > next(
        row.stability_adjusted_xirr
        for row in optimize(
            OptimizationRequest(minimum_independent_episodes=1),
            AnalysisFrames((spike, plateau, *neighbors), independent_episode_count=8),
        ).candidates
        if row.ratios == spike.ratios
    )


def test_balanced_profile_applies_risk_constraints_before_maximizing_oos_xirr() -> None:
    risky = _candidate(
        (1000, 2000, 3000, 4000),
        0.30,
        worst_5=-0.50,
        depletion=0.60,
        trap_days=1400,
    )
    eligible = _candidate((2000, 3000, 4000, 5000), 0.12)
    request = OptimizationRequest(
        minimum_independent_episodes=1,
        balanced=ProfileConstraints(
            worst_5_floor=-0.20,
            max_early_depletion_rate=0.20,
            max_longest_trap_days=800,
        ),
    )

    result = optimize(
        request,
        AnalysisFrames((risky, eligible), independent_episode_count=8),
    )

    balanced = next(row for row in result.recommendations if row.profile == "balanced")
    assert balanced.ratios == eligible.ratios


def test_too_few_independent_episodes_is_exploration_only_without_labels() -> None:
    frames = AnalysisFrames(
        (_candidate((2000, 3000, 4000, 5000), 0.15),),
        independent_episode_count=3,
    )

    result = optimize(OptimizationRequest(minimum_independent_episodes=5), frames)

    assert result.mode == "exploration_only"
    assert result.recommendations == ()
    assert all(candidate.recommendation_labels == () for candidate in result.candidates)


def test_synthetic_history_is_a_separate_stress_flag_and_never_improves_oos_score() -> None:
    actual = (_candidate((2000, 3000, 4000, 5000), 0.15),)
    failed = optimize(
        OptimizationRequest(minimum_independent_episodes=1),
        AnalysisFrames(
            actual,
            independent_episode_count=8,
            synthetic_stress=(SyntheticStress(actual[0].ratios, passed=False),),
        ),
    )
    passed = optimize(
        OptimizationRequest(minimum_independent_episodes=1),
        AnalysisFrames(
            actual,
            independent_episode_count=8,
            synthetic_stress=(SyntheticStress(actual[0].ratios, passed=True),),
        ),
    )

    assert failed.candidates[0].oos_xirr == passed.candidates[0].oos_xirr
    assert (
        failed.candidates[0].stability_adjusted_xirr
        == passed.candidates[0].stability_adjusted_xirr
    )
    assert failed.candidates[0].synthetic_stress_pass is False
    assert passed.candidates[0].synthetic_stress_pass is True


def test_optimizer_exposes_pareto_membership_and_separate_profile_labels() -> None:
    candidates = (
        _candidate(
            (1000, 2000, 3000, 4000),
            0.08,
            worst_5=-0.05,
            depletion=0.0,
            trap_days=100,
        ),
        _candidate(
            (2000, 3000, 4000, 5000),
            0.14,
            worst_5=-0.12,
            depletion=0.1,
            trap_days=300,
        ),
        _candidate(
            (3000, 4000, 5000, 6000),
            0.18,
            worst_5=-0.30,
            depletion=0.3,
            trap_days=900,
        ),
        _candidate(
            (4000, 5000, 6000, 7000),
            0.04,
            worst_5=-0.40,
            depletion=0.5,
            trap_days=1200,
        ),
    )

    result = optimize(
        OptimizationRequest(minimum_independent_episodes=1),
        AnalysisFrames(candidates, independent_episode_count=10),
    )

    assert {row.profile for row in result.recommendations} == {
        "conservative",
        "balanced",
        "aggressive",
    }
    assert any(row.pareto_member for row in result.candidates)
    assert next(
        row for row in result.candidates if row.ratios == (4000, 5000, 6000, 7000)
    ).pareto_member is False
