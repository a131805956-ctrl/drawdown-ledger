from __future__ import annotations

from collections.abc import Iterator
from itertools import combinations_with_replacement, product
from math import comb

BASIS_POINTS_PER_PERCENT = 100
MAX_RATIO_BASIS_POINTS = 10_000


def _basis_point_values(step: int) -> range:
    if step <= 0 or step > 100 or 100 % step:
        raise ValueError("Step must be a positive percentage-point divisor of 100")
    return range(
        0,
        MAX_RATIO_BASIS_POINTS + 1,
        step * BASIS_POINTS_PER_PERCENT,
    )


def generate_grid(
    *,
    levels: int = 4,
    step: int = 10,
    monotone: bool = True,
) -> Iterator[tuple[int, ...]]:
    """Yield deterministic allocation ratios represented as integer basis points."""

    if levels <= 0:
        raise ValueError("Levels must be positive")
    values = _basis_point_values(step)
    vectors = (
        combinations_with_replacement(values, levels)
        if monotone
        else product(values, repeat=levels)
    )
    yield from vectors


def generate_monotone_grid(
    levels: int = 4,
    step: int = 10,
) -> Iterator[tuple[int, ...]]:
    yield from generate_grid(levels=levels, step=step, monotone=True)


def generate_ratio_grid(
    *,
    levels: int,
    minimum_basis_points: int,
    maximum_basis_points: int,
    step_basis_points: int,
    monotone: bool,
) -> Iterator[tuple[int, ...]]:
    """Yield a bounded basis-point search space without caller-supplied candidates."""

    _ratio_value_count(
        levels=levels,
        minimum_basis_points=minimum_basis_points,
        maximum_basis_points=maximum_basis_points,
        step_basis_points=step_basis_points,
    )
    values = range(
        minimum_basis_points,
        maximum_basis_points + 1,
        step_basis_points,
    )
    vectors = (
        combinations_with_replacement(values, levels)
        if monotone
        else product(values, repeat=levels)
    )
    yield from vectors


def _ratio_value_count(
    *,
    levels: int,
    minimum_basis_points: int,
    maximum_basis_points: int,
    step_basis_points: int,
) -> int:
    if levels <= 0:
        raise ValueError("Levels must be positive")
    if not 0 <= minimum_basis_points <= maximum_basis_points <= MAX_RATIO_BASIS_POINTS:
        raise ValueError("Ratio bounds must be ordered basis points from 0 through 10000")
    if step_basis_points <= 0:
        raise ValueError("Ratio step must be positive")
    if (maximum_basis_points - minimum_basis_points) % step_basis_points:
        raise ValueError("Ratio range must be exactly divisible by the basis-point step")
    return (
        (maximum_basis_points - minimum_basis_points) // step_basis_points
    ) + 1


def count_ratio_grid(
    *,
    levels: int,
    minimum_basis_points: int,
    maximum_basis_points: int,
    step_basis_points: int,
    monotone: bool,
) -> int:
    """Return the exact candidate count in constant space without enumeration."""

    value_count = _ratio_value_count(
        levels=levels,
        minimum_basis_points=minimum_basis_points,
        maximum_basis_points=maximum_basis_points,
        step_basis_points=step_basis_points,
    )
    return (
        comb(value_count + levels - 1, levels)
        if monotone
        else value_count**levels
    )
