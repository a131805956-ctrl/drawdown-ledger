from __future__ import annotations

from dataclasses import replace
from datetime import date

import pandas as pd
import pytest
from drawdown_lab.analysis.episodes import classify_episodes
from drawdown_lab.data.models import MarketFrame


def _frame_from_closes(closes: list[float]) -> MarketFrame:
    index = pd.date_range("2020-01-02", periods=len(closes), freq="B")
    close = pd.Series(closes, index=index, dtype=float)
    data = pd.DataFrame(
        {
            "raw_open": close,
            "raw_high": close,
            "raw_low": close,
            "raw_close": close,
            "price_open": close,
            "price_high": close,
            "price_low": close,
            "price_close": close,
            "adj_close": close,
            "dividend_raw": 0.0,
            "split_ratio": 1.0,
        },
        index=index,
    )
    return MarketFrame(data)


def test_gap_can_trigger_multiple_tiers_once_in_one_cycle() -> None:
    frame = _frame_from_closes([100, 65, 60, 101])

    episodes = classify_episodes(frame, (0.20, 0.30, 0.40))

    assert [(event.threshold, event.cycle_id) for event in episodes] == [
        (0.20, 1),
        (0.30, 1),
        (0.40, 1),
    ]


def test_touching_prior_peak_recovers_but_does_not_start_a_new_cycle() -> None:
    frame = _frame_from_closes([100, 80, 100, 79, 101, 80])

    episodes = classify_episodes(frame, (0.20,))

    assert [(event.cycle_id, event.signal_date) for event in episodes] == [
        (1, date(2020, 1, 3)),
        (2, date(2020, 1, 9)),
    ]
    assert episodes[0].recovery_date == date(2020, 1, 6)
    assert episodes[0].recovery_sessions == 1
    assert episodes[0].v_recovered is True


def test_v_recovery_requires_repair_within_126_sessions() -> None:
    event = classify_episodes(_frame_from_closes([100, 80]), (0.20,))[0]

    assert replace(event, recovery_sessions=126).v_recovered is True
    assert replace(event, recovery_sessions=127).v_recovered is False


@pytest.mark.parametrize("threshold", [0.0, -0.20, 1.01])
def test_episode_thresholds_must_be_positive_ratios(threshold: float) -> None:
    with pytest.raises(ValueError, match="positive ratios"):
        classify_episodes(_frame_from_closes([100, 80]), (threshold,))
