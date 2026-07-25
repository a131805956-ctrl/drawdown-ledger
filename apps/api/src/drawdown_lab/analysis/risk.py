from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import ceil

import numpy as np


@dataclass(frozen=True, slots=True)
class BootstrapInterval:
    lower: float
    upper: float


def expected_shortfall_5(values: Iterable[float]) -> float:
    observations = np.asarray(tuple(values), dtype=float)
    if observations.size == 0:
        raise ValueError("Expected shortfall requires at least one observation")
    tail_size = max(1, ceil(observations.size * 0.05))
    return float(np.sort(observations)[:tail_size].mean())


def block_bootstrap_interval(
    values: Iterable[float],
    *,
    rng: np.random.Generator,
    block_size: int,
    iterations: int,
    confidence: float = 0.95,
) -> BootstrapInterval:
    """Estimate a mean interval by resampling contiguous circular event blocks."""

    observations = np.asarray(tuple(values), dtype=float)
    if observations.size == 0:
        raise ValueError("Block bootstrap requires at least one observation")
    if block_size <= 0:
        raise ValueError("Block size must be positive")
    if iterations <= 0:
        raise ValueError("Bootstrap iterations must be positive")
    if not 0.0 < confidence < 1.0:
        raise ValueError("Confidence must be between zero and one")

    sample_size = observations.size
    effective_block_size = min(block_size, sample_size)
    estimates = np.empty(iterations, dtype=float)
    for iteration in range(iterations):
        sample: list[float] = []
        while len(sample) < sample_size:
            start = int(rng.integers(0, sample_size))
            sample.extend(
                float(observations[(start + offset) % sample_size])
                for offset in range(effective_block_size)
            )
        estimates[iteration] = float(np.mean(sample[:sample_size]))

    tail = (1.0 - confidence) / 2.0
    lower, upper = np.quantile(estimates, (tail, 1.0 - tail))
    return BootstrapInterval(lower=float(lower), upper=float(upper))
