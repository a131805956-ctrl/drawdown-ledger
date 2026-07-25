from __future__ import annotations

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


def _month(value: str | date) -> date:
    if isinstance(value, date):
        return value.replace(day=1)
    return date.fromisoformat(f"{value}-01")


def bonus(month: str | date, amount: Decimal | int | float | str) -> ContributionEvent:
    return ContributionEvent(_month(month), "bonus", quantize_money(amount))


def override(month: str | date, amount: Decimal | int | float | str) -> ContributionEvent:
    return ContributionEvent(_month(month), "override", quantize_money(amount))


def pause(month: str | date) -> ContributionEvent:
    return ContributionEvent(_month(month), "pause")


def resume(month: str | date) -> ContributionEvent:
    return ContributionEvent(_month(month), "resume")


@dataclass(frozen=True, slots=True)
class ContributionSchedule:
    monthly: Money
    annual_growth: Decimal = Decimal("0")
    start: date = date(2026, 1, 1)
    events: tuple[ContributionEvent, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "monthly", quantize_money(self.monthly))
        object.__setattr__(self, "annual_growth", as_decimal(self.annual_growth))
        object.__setattr__(self, "start", self.start.replace(day=1))
        if self.monthly < 0:
            raise ValueError("Monthly contribution must be non-negative")
        if self.annual_growth <= Decimal("-1"):
            raise ValueError("Annual growth must be greater than -1")
        seen: set[tuple[date, str]] = set()
        for event in self.events:
            key = (event.month, event.kind)
            if key in seen and event.kind != "bonus":
                raise ValueError(f"Duplicate {event.kind} event for {event.month:%Y-%m}")
            seen.add(key)

    def amount_for(self, when: date) -> Money:
        target = when.replace(day=1)
        if target < self.start:
            return Decimal("0.00")

        active = True
        completed = 0
        cursor = self.start
        while cursor <= target:
            events = tuple(event for event in self.events if event.month == cursor)
            if any(event.kind == "pause" for event in events):
                active = False
            if any(event.kind == "resume" for event in events):
                active = True

            amount = self.monthly * (Decimal("1") + self.annual_growth) ** (completed // 12)
            overrides = tuple(event for event in events if event.kind == "override")
            if overrides:
                amount = overrides[0].amount
            amount += sum(
                (event.amount for event in events if event.kind == "bonus"),
                start=Decimal("0"),
            )
            if not active:
                amount = Decimal("0")

            if cursor == target:
                return quantize_money(amount)
            if amount > 0:
                completed += 1
            cursor = _next_month(cursor)
        raise AssertionError("unreachable")


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def accrue_cash(principal: Money, annual_rate: Decimal, actual_days: int) -> Money:
    if actual_days < 0:
        raise ValueError("Actual days cannot be negative")
    accrued = as_decimal(principal) * (
        Decimal("1") + as_decimal(annual_rate) * Decimal(actual_days) / Decimal("365")
    )
    return quantize_money(accrued)
