from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from drawdown_lab.analysis.chart_series import actual_chart_series, synthetic_chart_series
from drawdown_lab.data.models import MarketFrame


def _frame(
    price_closes: list[float],
    *,
    adjusted_closes: list[float] | None = None,
) -> MarketFrame:
    index = pd.bdate_range("2020-01-01", periods=len(price_closes))
    price = pd.Series(price_closes, index=index, dtype=float)
    adjusted = pd.Series(adjusted_closes or price_closes, index=index, dtype=float)
    return MarketFrame(
        pd.DataFrame(
            {
                "raw_open": price,
                "raw_high": price,
                "raw_low": price,
                "raw_close": price,
                "price_open": price,
                "price_high": price,
                "price_low": price,
                "price_close": price,
                "adj_close": adjusted,
                "dividend_raw": 0.0,
                "split_ratio": 1.0,
            },
            index=index,
        )
    )


def test_actual_chart_rebases_selected_total_return_without_resetting_drawdown() -> None:
    frame = _frame([100.0, 80.0, 88.0], adjusted_closes=[100.0, 90.0, 99.0])

    series = actual_chart_series(frame, start=date(2020, 1, 2))

    assert [point.normalized_total_return for point in series.points] == pytest.approx(
        [100.0, 110.0]
    )
    assert series.points[0].drawdown == pytest.approx(-0.20)


def test_synthetic_chart_rebases_selected_index_without_resetting_drawdown() -> None:
    frame = _frame([100.0, 90.0, 99.0])

    series = synthetic_chart_series(frame, 2.0, start=date(2020, 1, 2))

    assert [point.normalized_total_return for point in series.points] == pytest.approx(
        [100.0, 120.0]
    )
    assert series.points[0].drawdown == pytest.approx(-0.20)
