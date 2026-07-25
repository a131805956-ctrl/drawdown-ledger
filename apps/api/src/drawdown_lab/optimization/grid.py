from __future__ import annotations

from collections.abc import Iterator
from itertools import combinations_with_replacement, product

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
