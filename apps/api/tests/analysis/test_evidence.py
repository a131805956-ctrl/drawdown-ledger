from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from drawdown_lab.analysis.evidence import (
    DEFAULT_HORIZON_SESSIONS,
    EvidenceRequest,
    analyze_evidence,
)
from drawdown_lab.analysis.risk import block_bootstrap_interval, expected_shortfall_5
from drawdown_lab.data.models import MarketFrame


def _market_frame(
    closes: list[float],
    *,
    raw_opens: list[float] | None = None,
    raw_highs: list[float] | None = None,
    raw_lows: list[float] | None = None,
    raw_closes: list[float] | None = None,
    adjusted_closes: list[float] | None = None,
) -> MarketFrame:
    index = pd.date_range("2020-03-11", periods=len(closes), freq="B")
    raw_close = raw_closes or closes
    adj_close = adjusted_closes or closes
    data = pd.DataFrame(
        {
            "raw_open": raw_opens or closes,
            "raw_high": raw_highs or raw_close,
            "raw_low": raw_lows or raw_close,
            "raw_close": raw_close,
            "price_open": raw_opens or closes,
            "price_high": raw_highs or raw_close,
            "price_low": raw_lows or raw_close,
            "price_close": closes,
            "adj_close": adj_close,
            "dividend_raw": 0.0,
            "split_ratio": 1.0,
        },
        index=index,
    )
    return MarketFrame(data)


def test_evidence_defaults_use_required_session_horizons() -> None:
    assert DEFAULT_HORIZON_SESSIONS == (21, 63, 126, 252, 756, 1260)
    assert EvidenceRequest(threshold=0.20).horizons == DEFAULT_HORIZON_SESSIONS


def test_signal_executes_first_later_valid_raw_open_and_uses_adjusted_open() -> None:
    prototype = _market_frame([100, 80, 85, 90, 100, 101])
    traded = _market_frame(
        [10, 10, 10, 10, 10, 10],
        raw_opens=[10, 10, 0, 8, 10, 10],
        raw_highs=[10, 10, 10, 9, 11, 10],
        raw_lows=[10, 10, 10, 7, 8, 7],
        raw_closes=[10, 10, 10, 10, 10, 10],
        adjusted_closes=[10, 10, 10, 12, 12, 8],
    )

    report = analyze_evidence(
        EvidenceRequest(threshold=0.20, horizons=(1, 2), bootstrap_iterations=50),
        prototype,
        traded,
    )

    observation = report.episodes[0]
    assert observation.signal_date.isoformat() == "2020-03-12"
    assert observation.entry_date.isoformat() == "2020-03-16"
    assert observation.entry_price == Decimal("9.6")
    assert observation.total_return(1) == pytest.approx(0.25)
    assert observation.total_return(2) == pytest.approx(-1 / 6)
    assert observation.mae == pytest.approx(-5 / 12)
    assert observation.mfe == pytest.approx(0.375)
    assert observation.recovery_sessions == 3
    assert observation.v_recovered is True


def test_daily_cohort_count_does_not_inflate_episode_statistics() -> None:
    prototype = _market_frame([100, 80, 75, 70, 110, 100])
    traded = _market_frame([100, 90, 80, 70, 110, 100])

    report = analyze_evidence(
        EvidenceRequest(threshold=0.20, horizons=(1,), bootstrap_iterations=20),
        prototype,
        traded,
    )

    assert report.n_day == 3
    assert report.n_episode == 1
    assert report.horizon_statistics[0].n == 1


def test_expected_shortfall_uses_the_worst_five_percent_tail() -> None:
    assert expected_shortfall_5([0.10, -0.50, -0.20, 0.30]) == pytest.approx(-0.50)


def test_fixed_seed_block_bootstrap_is_deterministic() -> None:
    values = [0.20, -0.10, 0.05, 0.30, -0.25, 0.12]

    first = block_bootstrap_interval(
        values,
        rng=np.random.default_rng(7749),
        block_size=2,
        iterations=200,
    )
    second = block_bootstrap_interval(
        values,
        rng=np.random.default_rng(7749),
        block_size=2,
        iterations=200,
    )

    assert first == second
