from __future__ import annotations

import pytest
from drawdown_lab.optimization.grid import (
    count_ratio_grid,
    generate_grid,
    generate_monotone_grid,
    generate_ratio_grid,
)


def test_default_monotone_four_tier_grid_has_1001_basis_point_vectors() -> None:
    grid = list(generate_monotone_grid())

    assert len(grid) == 1001
    assert grid[:3] == [(0, 0, 0, 0), (0, 0, 0, 1000), (0, 0, 0, 2000)]
    assert grid[-1] == (10000, 10000, 10000, 10000)
    assert all(all(0 <= value <= 10000 for value in vector) for vector in grid)


def test_unrestricted_four_tier_grid_has_14641_deterministic_vectors() -> None:
    first = list(generate_grid(levels=4, step=10, monotone=False))
    second = list(generate_grid(levels=4, step=10, monotone=False))

    assert len(first) == 14641
    assert first == second
    assert first[1] == (0, 0, 0, 1000)
    assert first[-1] == (10000, 10000, 10000, 10000)


@pytest.mark.parametrize(
    ("levels", "step"),
    [(0, 10), (4, 0), (4, 7), (4, 101)],
)
def test_grid_rejects_invalid_dimensions_or_percentage_step(levels: int, step: int) -> None:
    with pytest.raises(ValueError):
        list(generate_grid(levels=levels, step=step))


def test_basis_point_range_grid_is_generated_internally_with_exact_bounds() -> None:
    assert list(
        generate_ratio_grid(
            levels=2,
            minimum_basis_points=2000,
            maximum_basis_points=6000,
            step_basis_points=2000,
            monotone=True,
        )
    ) == [
        (2000, 2000),
        (2000, 4000),
        (2000, 6000),
        (4000, 4000),
        (4000, 6000),
        (6000, 6000),
    ]


def test_candidate_count_uses_closed_form_without_enumerating_pathological_grid() -> None:
    assert count_ratio_grid(
        levels=4,
        minimum_basis_points=0,
        maximum_basis_points=10_000,
        step_basis_points=1_000,
        monotone=True,
    ) == 1001
    assert count_ratio_grid(
        levels=4,
        minimum_basis_points=0,
        maximum_basis_points=10_000,
        step_basis_points=1_000,
        monotone=False,
    ) == 14641
    assert count_ratio_grid(
        levels=4,
        minimum_basis_points=0,
        maximum_basis_points=10_000,
        step_basis_points=1,
        monotone=False,
    ) == 10_004_000_600_040_001
