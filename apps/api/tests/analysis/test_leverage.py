from __future__ import annotations

import pandas as pd
import pytest
from drawdown_lab.analysis.leverage import (
    analyze_leveraged_history,
    synthetic_daily_reset_nav,
)
from drawdown_lab.data.models import MarketFrame


def _frame(closes: list[float], start: str = "2010-02-11") -> MarketFrame:
    index = pd.date_range(start, periods=len(closes), freq="B")
    close = pd.Series(closes, index=index, dtype=float)
    return MarketFrame(
        pd.DataFrame(
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
    )


def test_daily_reset_synthetic_nav_compounds_leveraged_daily_returns() -> None:
    prototype = _frame([100, 110, 99], start="2009-01-02")

    synthetic = synthetic_daily_reset_nav(
        prototype,
        leverage=2.0,
        initial_nav=100.0,
    )

    assert synthetic.nav.tolist() == pytest.approx([100.0, 120.0, 96.0])
    assert synthetic.unit == "index"
    assert synthetic.source_kind == "synthetic"
    assert not hasattr(synthetic, "currency")


def test_synthetic_observations_never_count_as_actual_etf_evidence() -> None:
    actual = _frame([40, 41], start="2010-02-11")
    synthetic = synthetic_daily_reset_nav(
        _frame([100, 90, 95], start="2010-02-08"),
        leverage=3.0,
    )

    report = analyze_leveraged_history(actual=actual, synthetic=synthetic)

    assert all(row.source_kind == "actual" for row in report.actual_statistics.rows)
    assert all(row.source_kind == "synthetic" for row in report.stress_statistics.rows)
    assert report.actual_statistics.count == 2
    assert report.stress_statistics.count == 3
    assert report.actual_count == 2
    assert report.synthetic_count == 3
