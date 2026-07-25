from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class WalkForwardSplit:
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]

    @property
    def train(self) -> tuple[int, ...]:
        return self.train_indices

    @property
    def test(self) -> tuple[int, ...]:
        return self.test_indices


def expanding_window_splits(
    dates: Sequence[date],
    *,
    n_splits: int = 3,
    min_train_size: int | None = None,
    test_size: int | None = None,
) -> tuple[WalkForwardSplit, ...]:
    """Build chronological expanding windows without any randomized operation."""

    if n_splits <= 0:
        raise ValueError("Number of splits must be positive")
    ordered_dates = tuple(dates)
    if any(left >= right for left, right in zip(ordered_dates, ordered_dates[1:])):
        raise ValueError("Walk-forward dates must be strictly increasing")

    observation_count = len(ordered_dates)
    if test_size is not None and test_size <= 0:
        raise ValueError("Test size must be positive")
    if min_train_size is not None and min_train_size <= 0:
        raise ValueError("Minimum train size must be positive")

    effective_test_size = test_size or observation_count // (n_splits + 1)
    if effective_test_size <= 0:
        raise ValueError("Walk-forward requires enough observations for every split")
    effective_train_size = min_train_size or observation_count - n_splits * effective_test_size
    required = effective_train_size + n_splits * effective_test_size
    if effective_train_size <= 0 or required > observation_count:
        raise ValueError("Walk-forward requires enough observations for every split")

    splits: list[WalkForwardSplit] = []
    for split_number in range(n_splits):
        test_start = effective_train_size + split_number * effective_test_size
        test_end = test_start + effective_test_size
        split = WalkForwardSplit(
            train_indices=tuple(range(test_start)),
            test_indices=tuple(range(test_start, test_end)),
        )
        if not split.train_indices or not split.test_indices:
            raise ValueError("Walk-forward splits require non-empty train and test windows")
        if max(split.train_indices) >= min(split.test_indices):
            raise RuntimeError("Walk-forward chronology invariant was violated")
        splits.append(split)
    return tuple(splits)


walk_forward_splits = expanding_window_splits
chronological_splits = expanding_window_splits
