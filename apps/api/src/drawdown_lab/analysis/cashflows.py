from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from drawdown_lab.domain.money import Money, as_decimal, quantize_money

ContributionEventKind = Literal["bonus", "override", "pause", "resume"]


@dataclass(frozen=True, slots=True)
class CashFlow:
    date: date
    amount: Money


@dataclass(frozen=True, slots=True)
class ContributionEvent:
    month: date
    kind: ContributionEventKind
    amount: Money = Decimal("0")

    def __post_init__(self) -> None:
        if self.kind not in {"bonus", "override", "pause", "resume"}:
            raise ValueError(f"Unknown contribution event kind: {self.kind}")
        normalized_amount = as_decimal(self.amount)
        if self.kind in {"pause", "resume"} and normalized_amount != 0:
            raise ValueError(f"{self.kind} events cannot include an amount")
        object.__setattr__(self, "month", self.month.replace(day=1))
        object.__setattr__(self, "amount", quantize_money(normalized_amount))


def _event_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(f"{value}-01")


def bonus(month: str | date, amount: Decimal | int | float | str) -> ContributionEvent:
    return ContributionEvent(_event_date(month), "bonus", quantize_money(amount))


def override(month: str | date, amount: Decimal | int | float | str) -> ContributionEvent:
    return ContributionEvent(_event_date(month), "override", quantize_money(amount))


def pause(month: str | date) -> ContributionEvent:
    return ContributionEvent(_event_date(month), "pause")


def resume(month: str | date) -> ContributionEvent:
    return ContributionEvent(_event_date(month), "resume")


@dataclass(frozen=True, slots=True)
class ContributionSchedule:
    monthly: Money
    annual_growth: Decimal = Decimal("0")
    start: date | None = None
    events: tuple[ContributionEvent, ...] = ()
    contribution_day: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "monthly", quantize_money(self.monthly))
        object.__setattr__(self, "annual_growth", as_decimal(self.annual_growth))
        if self.monthly < 0:
            raise ValueError("Monthly contribution must be non-negative")
        if self.annual_growth <= Decimal("-1"):
            raise ValueError("Annual growth must be greater than -1")
        if not 1 <= self.contribution_day <= 31:
            raise ValueError("Contribution day must be between 1 and 31")
        seen: set[tuple[date, str]] = set()
        control_kinds: dict[date, set[str]] = {}
        for event in self.events:
            if event.amount < 0:
                raise ValueError("Contribution event amounts must be non-negative")
            key = (event.month, event.kind)
            if key in seen and event.kind != "bonus":
                raise ValueError(f"Duplicate {event.kind} event for {event.month:%Y-%m}")
            seen.add(key)
            if event.kind in {"pause", "resume"}:
                kinds = control_kinds.setdefault(event.month, set())
                kinds.add(event.kind)
                if kinds == {"pause", "resume"}:
                    raise ValueError(
                        f"pause and resume events conflict for {event.month:%Y-%m}"
                    )

    def amount_for(self, when: date, *, plan_start: date | None = None) -> Money:
        target = when.replace(day=1)
        flows = self.due_cashflows(_month_end(target), plan_start=plan_start)
        return quantize_money(
            sum(
                (
                    flow.amount
                    for flow in flows
                    if flow.date.year == target.year and flow.date.month == target.month
                ),
                start=Decimal("0"),
            )
        )

    def due_cashflows(
        self,
        through: date,
        *,
        plan_start: date | None = None,
    ) -> tuple[CashFlow, ...]:
        effective_start = self.start or plan_start
        if effective_start is None:
            raise ValueError("Contribution schedule requires a plan start")
        posting_start = max(effective_start, plan_start or effective_start)
        if through < effective_start:
            return ()

        active = True
        completed = 0
        current_monthly = self.monthly
        monthly_dates: list[date] = []
        cursor = effective_start.replace(day=1)
        first_due = _monthly_due(cursor, self.contribution_day)
        if first_due < effective_start:
            cursor = _next_month(cursor)
        while cursor <= through:
            due_date = _monthly_due(cursor, self.contribution_day)
            if due_date <= through:
                monthly_dates.append(due_date)
            cursor = _next_month(cursor)
        effective_month = effective_start.replace(day=1)
        event_dates = {
            event.month for event in self.events if effective_month <= event.month <= through
        }
        timeline = sorted(set(monthly_dates) | event_dates)
        due: list[CashFlow] = []
        for current in timeline:
            events = tuple(event for event in self.events if event.month == current)
            if any(event.kind == "pause" for event in events):
                active = False
            if any(event.kind == "resume" for event in events):
                active = True
            overrides = tuple(event for event in events if event.kind == "override")
            if overrides:
                current_monthly = overrides[0].amount

            if current in monthly_dates and active:
                amount = quantize_money(
                    current_monthly * (Decimal("1") + self.annual_growth) ** (completed // 12)
                )
                if amount:
                    if current >= posting_start:
                        due.append(CashFlow(current, amount))
                    completed += 1

            if active and current >= posting_start:
                due.extend(
                    CashFlow(current, event.amount)
                    for event in events
                    if event.kind == "bonus" and event.amount
                )
        return tuple(due)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _month_end(value: date) -> date:
    return _next_month(value) - date.resolution


def _monthly_due(month: date, contribution_day: int) -> date:
    day = min(contribution_day, monthrange(month.year, month.month)[1])
    return date(month.year, month.month, day)


def accrue_cash(principal: Money, annual_rate: Decimal, actual_days: int) -> Money:
    if actual_days < 0:
        raise ValueError("Actual days cannot be negative")
    accrued = as_decimal(principal) * (
        Decimal("1") + as_decimal(annual_rate) * Decimal(actual_days) / Decimal("365")
    )
    return quantize_money(accrued)
