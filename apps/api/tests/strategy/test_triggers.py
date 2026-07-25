from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
from drawdown_lab.analysis.strategy import StrategyConfig, ThresholdTier, simulate_strategy
from drawdown_lab.data.models import MarketFrame


def _frame(
    closes: list[float],
    *,
    opens: list[float] | None = None,
    start: str = "2020-03-09",
) -> MarketFrame:
    index = pd.date_range(start, periods=len(closes), freq="B")
    raw_open = opens or closes
    data = pd.DataFrame(
        {
            "raw_open": raw_open,
            "raw_high": closes,
            "raw_low": closes,
            "raw_close": closes,
            "price_open": closes,
            "price_high": closes,
            "price_low": closes,
            "price_close": closes,
            "adj_close": closes,
            "dividend_raw": 0.0,
            "split_ratio": 1.0,
        },
        index=index,
    )
    return MarketFrame(data)


def _config(
    *,
    start: date = date(2020, 3, 12),
    end: date | None = None,
    tiers: tuple[ThresholdTier, ...] = (
        ThresholdTier(Decimal("0.20"), Decimal("0.25")),
        ThresholdTier(Decimal("0.30"), Decimal("0.40")),
    ),
) -> StrategyConfig:
    return StrategyConfig(
        start=start,
        end=end,
        initial_cash=Decimal("1000000"),
        tiers=tiers,
    )


def test_starting_mid_drawdown_triggers_all_satisfied_tiers_next_open() -> None:
    frame = _frame([100, 90, 80, 65, 60, 62])

    result = simulate_strategy(_config(), prototype=frame, traded=frame)

    assert [(trade.threshold, trade.cash_spent) for trade in result.trades[:2]] == [
        (Decimal("0.20"), Decimal("250000.00")),
        (Decimal("0.30"), Decimal("300000.00")),
    ]
    assert [trade.date for trade in result.trades[:2]] == [
        date(2020, 3, 13),
        date(2020, 3, 13),
    ]


def test_close_signal_never_executes_at_same_day_open() -> None:
    frame = _frame([100, 79, 78], opens=[100, 50, 40], start="2020-01-01")
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal("1000"),
        tiers=(ThresholdTier(Decimal("0.20"), Decimal("1")),),
    )

    result = simulate_strategy(config, frame, frame)

    assert result.trades[0].date == date(2020, 1, 3)
    assert result.trades[0].raw_price == Decimal("40")


def test_order_waits_for_first_strictly_later_valid_raw_open() -> None:
    frame = _frame([100, 79, 78, 77], opens=[100, 79, 0, 55], start="2020-01-01")
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal("1000"),
        tiers=(ThresholdTier(Decimal("0.20"), Decimal("1")),),
    )

    result = simulate_strategy(config, frame, frame)

    assert result.trades[0].date == date(2020, 1, 6)
    assert result.trades[0].raw_price == Decimal("55")


def test_new_high_resets_flags_without_selling_or_refilling_cash() -> None:
    frame = _frame([100, 79, 78, 101, 79, 78], start="2020-01-01")
    config = StrategyConfig(
        start=date(2020, 1, 1),
        initial_cash=Decimal("1000"),
        tiers=(ThresholdTier(Decimal("0.20"), Decimal("0.50")),),
    )

    result = simulate_strategy(config, frame, frame)

    trades = result.trades_for(Decimal("0.20"))
    assert len(trades) == 2
    assert result.sell_trades == ()
    assert [trade.cash_spent for trade in trades] == [
        Decimal("500.00"),
        Decimal("250.00"),
    ]
    assert result.shares_after_first_cycle == trades[0].shares_bought
    assert result.ending_shares > trades[0].shares_bought


def test_pending_order_at_end_date_is_not_backfilled() -> None:
    frame = _frame([100, 79, 70], start="2020-01-01")
    config = StrategyConfig(
        start=date(2020, 1, 1),
        end=date(2020, 1, 2),
        initial_cash=Decimal("1000"),
        tiers=(ThresholdTier(Decimal("0.20"), Decimal("1")),),
    )

    result = simulate_strategy(config, frame, frame)

    assert result.trades == ()
    assert result.pending_thresholds == (Decimal("0.20"),)
