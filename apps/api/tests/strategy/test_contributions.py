from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
from drawdown_lab.analysis.cashflows import (
    CashFlow,
    ContributionSchedule,
    accrue_cash,
    bonus,
    override,
    pause,
    resume,
)
from drawdown_lab.analysis.strategy import StrategyConfig, ThresholdTier, simulate_strategy
from drawdown_lab.data.models import MarketFrame


def test_salary_growth_and_bonus_are_applied_on_effective_month() -> None:
    schedule = ContributionSchedule(
        monthly=Decimal("10000"),
        annual_growth=Decimal("0.10"),
        start=date(2026, 1, 1),
        events=(bonus("2027-03", Decimal("50000")),),
    )

    assert schedule.amount_for(date(2027, 1, 1)) == Decimal("11000.00")
    assert schedule.amount_for(date(2027, 3, 1)) == Decimal("61000.00")


def test_schedule_without_explicit_start_rebases_to_strategy_plan_start() -> None:
    schedule = ContributionSchedule(
        monthly=Decimal("10000"),
        annual_growth=Decimal("0.10"),
    )

    assert schedule.amount_for(
        date(2030, 2, 1),
        plan_start=date(2030, 2, 1),
    ) == Decimal("10000.00")
    assert schedule.amount_for(
        date(2031, 1, 1),
        plan_start=date(2030, 2, 1),
    ) == Decimal("10000.00")
    assert schedule.amount_for(
        date(2031, 2, 1),
        plan_start=date(2030, 2, 1),
    ) == Decimal("11000.00")


def test_growth_applies_only_after_twelve_completed_contribution_months() -> None:
    schedule = ContributionSchedule(
        monthly=Decimal("10000"),
        annual_growth=Decimal("0.10"),
        start=date(2026, 2, 1),
    )

    assert schedule.amount_for(date(2027, 1, 1)) == Decimal("10000.00")
    assert schedule.amount_for(date(2027, 2, 1)) == Decimal("11000.00")


def test_override_pause_resume_and_bonus_events_are_deterministic() -> None:
    schedule = ContributionSchedule(
        monthly=Decimal("10000"),
        start=date(2026, 1, 1),
        events=(
            bonus("2026-02", Decimal("500")),
            override("2026-02", Decimal("12000")),
            pause("2026-03"),
            bonus("2026-03", Decimal("999")),
            resume("2026-04"),
        ),
    )

    assert schedule.amount_for(date(2026, 2, 1)) == Decimal("12500.00")
    assert schedule.amount_for(date(2026, 3, 1)) == Decimal("0.00")
    assert schedule.amount_for(date(2026, 4, 1)) == Decimal("12000.00")


def test_cash_interest_uses_actual_days_over_365() -> None:
    assert accrue_cash(Decimal("100000"), Decimal("0.02"), 31) == Decimal("100169.86")


def _frame(dates: list[str], closes: list[float]) -> MarketFrame:
    index = pd.DatetimeIndex(dates)
    return MarketFrame(
        pd.DataFrame(
            {
                "raw_open": closes,
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
    )


def test_open_phase_applies_interest_then_deposit_then_prior_close_order() -> None:
    frame = _frame(["2020-12-31", "2021-01-01", "2021-02-01"], [100, 79, 75])
    schedule = ContributionSchedule(
        monthly=Decimal("100"),
        start=date(2021, 2, 1),
    )
    config = StrategyConfig(
        start=date(2021, 1, 1),
        initial_cash=Decimal("1000"),
        tiers=(ThresholdTier(Decimal("0.20"), Decimal("0.50")),),
        cash_interest_rate=Decimal("0.02"),
        contributions=schedule,
    )

    result = simulate_strategy(config, frame, frame)

    assert result.interest_income == Decimal("1.70")
    assert result.contribution_total == Decimal("100.00")
    assert result.trades[0].cash_spent == Decimal("550.85")
    assert result.cash == Decimal("550.85")


def test_monthly_deposits_continue_when_no_tier_triggers() -> None:
    frame = _frame(["2021-01-04", "2021-02-01", "2021-03-01"], [100, 101, 102])
    schedule = ContributionSchedule(
        monthly=Decimal("100"),
        start=date(2021, 1, 1),
    )
    config = StrategyConfig(
        start=date(2021, 1, 1),
        initial_cash=Decimal("0"),
        tiers=(ThresholdTier(Decimal("0.20"), Decimal("0.50")),),
        contributions=schedule,
    )

    result = simulate_strategy(config, frame, frame)

    assert result.trades == ()
    assert result.contribution_total == Decimal("300.00")
    assert result.cash == Decimal("300.00")


def test_sparse_sessions_accumulate_every_missed_calendar_month() -> None:
    frame = _frame(["2021-01-04", "2021-03-15"], [100, 101])
    schedule = ContributionSchedule(monthly=Decimal("100"))
    config = StrategyConfig(
        start=date(2021, 1, 1),
        initial_cash=Decimal("0"),
        tiers=(),
        contributions=schedule,
    )

    result = simulate_strategy(config, frame, frame)

    assert [point.cash for point in result.equity_curve] == [
        Decimal("100.00"),
        Decimal("300.00"),
    ]
    assert result.contribution_total == Decimal("300.00")


def test_dated_set_and_one_time_events_post_on_next_valid_session() -> None:
    frame = _frame(["2021-01-04", "2021-03-15", "2021-04-01"], [100, 101, 102])
    schedule = ContributionSchedule(
        monthly=Decimal("100"),
        events=(
            override(date(2021, 2, 1), Decimal("200")),
            bonus(date(2021, 2, 15), Decimal("50")),
        ),
    )
    config = StrategyConfig(
        start=date(2021, 1, 1),
        initial_cash=Decimal("0"),
        tiers=(),
        contributions=schedule,
    )

    result = simulate_strategy(config, frame, frame)

    assert [point.cash for point in result.equity_curve] == [
        Decimal("100.00"),
        Decimal("550.00"),
        Decimal("750.00"),
    ]


def test_midmonth_start_counts_march_as_first_completed_contribution_month() -> None:
    schedule = ContributionSchedule(
        monthly=Decimal("100"),
        annual_growth=Decimal("0.10"),
    )

    flows = schedule.due_cashflows(
        date(2031, 3, 1),
        plan_start=date(2030, 2, 15),
    )

    assert flows[0] == CashFlow(date(2030, 3, 1), Decimal("100.00"))
    assert [flow.amount for flow in flows[:12]] == [Decimal("100.00")] * 12
    assert flows[12] == CashFlow(date(2031, 3, 1), Decimal("110.00"))


def test_contribution_day_uses_first_due_date_on_or_after_midmonth_start() -> None:
    schedule = ContributionSchedule(
        monthly=Decimal("100"),
        annual_growth=Decimal("0.10"),
        contribution_day=20,
    )

    flows = schedule.due_cashflows(
        date(2031, 2, 20),
        plan_start=date(2030, 2, 15),
    )

    assert flows[0] == CashFlow(date(2030, 2, 20), Decimal("100.00"))
    assert [flow.amount for flow in flows[:12]] == [Decimal("100.00")] * 12
    assert flows[12] == CashFlow(date(2031, 2, 20), Decimal("110.00"))


def test_paused_month_does_not_advance_completed_contribution_count() -> None:
    schedule = ContributionSchedule(
        monthly=Decimal("100"),
        annual_growth=Decimal("0.10"),
        events=(pause("2030-07"), resume("2030-08")),
    )

    flows = schedule.due_cashflows(
        date(2031, 4, 1),
        plan_start=date(2030, 2, 15),
    )

    assert date(2030, 7, 1) not in [flow.date for flow in flows]
    assert [flow.amount for flow in flows[:12]] == [Decimal("100.00")] * 12
    assert flows[12] == CashFlow(date(2031, 4, 1), Decimal("110.00"))
