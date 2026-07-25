from __future__ import annotations

from datetime import date, timedelta

import pytest
from drawdown_lab.optimization.walk_forward import expanding_window_splits


def test_walk_forward_splits_are_chronological_expanding_windows() -> None:
    dates = tuple(date(2020, 1, 1) + timedelta(days=offset) for offset in range(12))

    splits = expanding_window_splits(dates, n_splits=3)

    assert [len(split.train_indices) for split in splits] == [3, 6, 9]
    assert [len(split.test_indices) for split in splits] == [3, 3, 3]
    assert all(
        max(dates[index] for index in split.train_indices)
        < min(dates[index] for index in split.test_indices)
        for split in splits
    )
    assert splits == expanding_window_splits(dates, n_splits=3)


def test_walk_forward_never_reorders_or_randomizes_observations() -> None:
    dates = (date(2020, 1, 2), date(2020, 1, 1), date(2020, 1, 3))

    with pytest.raises(ValueError, match="strictly increasing"):
        expanding_window_splits(dates, n_splits=1)


def test_walk_forward_rejects_too_few_observations() -> None:
    with pytest.raises(ValueError, match="enough observations"):
        expanding_window_splits((date(2020, 1, 1),), n_splits=1)
