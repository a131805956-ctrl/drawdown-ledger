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
    blocks_per_sample = ceil(sample_size / effective_block_size)
    starts = rng.integers(
        0,
        sample_size,
        size=(iterations, blocks_per_sample),
    )
    offsets = np.arange(effective_block_size, dtype=np.int64)
    indices = (starts[..., np.newaxis] + offsets) % sample_size
    samples = observations[indices].reshape(iterations, -1)[:, :sample_size]
    estimates = samples.mean(axis=1)

    tail = (1.0 - confidence) / 2.0
    lower, upper = np.quantile(estimates, (tail, 1.0 - tail))
    return BootstrapInterval(lower=float(lower), upper=float(upper))
