from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date
from decimal import Decimal
from enum import StrEnum
from math import isfinite

import pandas as pd

from drawdown_lab.analysis.cashflows import CashFlow, ContributionSchedule
from drawdown_lab.analysis.performance import PerformanceMetrics, calculate_performance
from drawdown_lab.data.models import MarketFrame, validate_market_frame
from drawdown_lab.domain.money import Money, as_decimal, quantize_money


class DividendPolicy(StrEnum):
    CASH = "cash"
    REINVEST = "reinvest"


@dataclass(frozen=True, slots=True)
class ThresholdTier:
    depth: Decimal
    cash_fraction: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "depth", as_decimal(self.depth))
        object.__setattr__(self, "cash_fraction", as_decimal(self.cash_fraction))
        if not Decimal("0") < self.depth <= Decimal("1"):
            raise ValueError("Threshold depth must be a positive ratio no greater than 1")
        if not Decimal("0") < self.cash_fraction <= Decimal("1"):
            raise ValueError("Tier cash fraction must be a positive ratio no greater than 1")


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    start: Date
    initial_cash: Money
    tiers: tuple[ThresholdTier, ...]
    initial_shares: Decimal = Decimal("0")
    end: Date | None = None
    contributions: ContributionSchedule | None = None
    cash_interest_rate: Decimal = Decimal("0")
    dividend_policy: DividendPolicy | str = DividendPolicy.CASH
    fixed_fee: Money = Decimal("0")
    fee_rate: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    name: str = "cash-pool"
    scheduled_initial_months: int = 0
    invest_contributions_immediately: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "initial_cash", quantize_money(self.initial_cash))
        object.__setattr__(self, "initial_shares", as_decimal(self.initial_shares))
        object.__setattr__(self, "cash_interest_rate", as_decimal(self.cash_interest_rate))
        object.__setattr__(self, "fixed_fee", quantize_money(self.fixed_fee))
        object.__setattr__(self, "fee_rate", as_decimal(self.fee_rate))
        object.__setattr__(self, "slippage", as_decimal(self.slippage))
        object.__setattr__(self, "dividend_policy", DividendPolicy(self.dividend_policy))
        object.__setattr__(self, "tiers", tuple(sorted(self.tiers, key=lambda tier: tier.depth)))
        if self.initial_cash < 0 or self.initial_shares < 0:
            raise ValueError("Initial cash and shares must be non-negative")
        if self.end is not None and self.end < self.start:
            raise ValueError("End date cannot precede start date")
        if self.fixed_fee < 0 or self.fee_rate < 0 or self.slippage < 0:
            raise ValueError("Fees and slippage must be non-negative")
        if self.scheduled_initial_months < 0:
            raise ValueError("Scheduled initial months must be non-negative")
        depths = tuple(tier.depth for tier in self.tiers)
        if len(depths) != len(set(depths)):
            raise ValueError("Tier depths must be unique")


@dataclass(frozen=True, slots=True)
class Trade:
    date: Date
    signal_date: Date
    threshold: Decimal | None
    cash_spent: Money
    shares_bought: Decimal
    raw_price: Decimal
    execution_price: Decimal
    fee: Money
    kind: str = "buy"


@dataclass(frozen=True, slots=True)
class PortfolioPoint:
    date: Date
    cash: Money
    shares: Decimal
    close: Decimal
    value: Money
    external_flow: Money = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class StrategyResult:
    name: str
    trades: tuple[Trade, ...]
    ending_cash: Money
    ending_shares: Decimal
    shares_after_first_cycle: Decimal
    dividend_income: Money
    contribution_total: Money
    interest_income: Money
    total_fees: Money
    equity_curve: tuple[PortfolioPoint, ...]
    external_cashflows: tuple[CashFlow, ...]
    pending_thresholds: tuple[Decimal, ...] = ()
    missed_thresholds: tuple[Decimal, ...] = ()
    metrics: PerformanceMetrics | None = None

    @property
    def cash(self) -> Money:
        return self.ending_cash

    @property
    def shares(self) -> Decimal:
        return self.ending_shares

    @property
    def sell_trades(self) -> tuple[Trade, ...]:
        return tuple(trade for trade in self.trades if trade.kind == "sell")

    def trades_for(self, threshold: Decimal | int | float | str) -> tuple[Trade, ...]:
        normalized = as_decimal(threshold)
        return tuple(trade for trade in self.trades if trade.threshold == normalized)


@dataclass(frozen=True, slots=True)
class _Order:
    signal_date: Date
    tier: ThresholdTier


@dataclass(frozen=True, slots=True)
class _DividendOrder:
    signal_date: Date
    amount: Money


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _valid_positive(value: object) -> bool:
    try:
        numeric = float(str(value))
    except (TypeError, ValueError):
        return False
    return isfinite(numeric) and numeric > 0


def _date_index(frame: MarketFrame) -> pd.DataFrame:
    data = frame.data.copy()
    data.index = pd.DatetimeIndex(data.index).normalize()
    return data


def simulate_strategy(
    config: StrategyConfig,
    prototype: MarketFrame,
    traded: MarketFrame,
) -> StrategyResult:
    """Simulate close-triggered tiers against raw traded-asset opens and actions."""

    validate_market_frame(prototype)
    validate_market_frame(traded)
    prototype_data = _date_index(prototype)
    traded_data = _date_index(traded)
    end = config.end or max(prototype_data.index.max(), traded_data.index.max()).date()
    start_stamp = pd.Timestamp(config.start)
    end_stamp = pd.Timestamp(end)

    prior_close = prototype_data.loc[prototype_data.index < start_stamp, "price_close"]
    prior_close = prior_close[prior_close > 0]
    ath = _decimal(prior_close.max()) if not prior_close.empty else None

    event_dates = sorted(
        set(prototype_data.loc[start_stamp:end_stamp].index)
        | set(traded_data.loc[start_stamp:end_stamp].index)
    )
    cash = config.initial_cash
    shares = config.initial_shares
    dividend_income = Decimal("0.00")
    contribution_total = Decimal("0.00")
    interest_income = Decimal("0.00")
    total_fees = Decimal("0.00")
    trades: list[Trade] = []
    equity_curve: list[PortfolioPoint] = []
    external_cashflows = [CashFlow(config.start, -config.initial_cash)]
    pending: list[_Order] = []
    pending_dividends: list[_DividendOrder] = []
    passive_pending: list[tuple[Date, Money, str]] = []
    initial_months_invested: set[tuple[int, int]] = set()
    initial_tranche = (
        quantize_money(config.initial_cash / config.scheduled_initial_months)
        if config.scheduled_initial_months
        else Decimal("0.00")
    )
    missed_thresholds: list[Decimal] = []
    triggered: set[Decimal] = set()
    deposited_months: set[tuple[int, int]] = set()
    last_open_date = config.start
    last_close = Decimal("0")
    first_cycle_shares: Decimal | None = None

    for timestamp in event_dates:
        current_date = timestamp.date()

        if timestamp in traded_data.index:
            row = traded_data.loc[timestamp]
            external_flow_today = Decimal("0.00")
            actual_days = (current_date - last_open_date).days
            if actual_days:
                before_interest = cash
                cash = quantize_money(
                    cash
                    * (
                        Decimal("1")
                        + config.cash_interest_rate
                        * Decimal(actual_days)
                        / Decimal("365")
                    )
                )
                interest_income += cash - before_interest
            last_open_date = current_date

            month_key = (current_date.year, current_date.month)
            if config.contributions is not None and month_key not in deposited_months:
                contribution = config.contributions.amount_for(current_date)
                deposited_months.add(month_key)
                if contribution:
                    cash += contribution
                    contribution_total += contribution
                    external_flow_today += contribution
                    external_cashflows.append(CashFlow(current_date, -contribution))
                    if config.invest_contributions_immediately:
                        passive_pending.append((current_date, contribution, "dca"))

            split_ratio = _decimal(row["split_ratio"])
            if split_ratio != Decimal("1"):
                shares *= split_ratio

            dividend = _decimal(row["dividend_raw"])
            if dividend and shares:
                received = quantize_money(shares * dividend)
                cash += received
                dividend_income += received
                if config.dividend_policy is DividendPolicy.REINVEST:
                    pending_dividends.append(_DividendOrder(current_date, received))

            raw_open = row["raw_open"]
            if (
                config.scheduled_initial_months
                and month_key not in initial_months_invested
                and len(initial_months_invested) < config.scheduled_initial_months
            ):
                passive_pending.append((current_date, initial_tranche, config.name.lower()))
                initial_months_invested.add(month_key)

            if (pending or pending_dividends or passive_pending) and _valid_positive(raw_open):
                price = _decimal(raw_open)
                passive_orders = tuple(passive_pending)
                passive_pending.clear()
                for signal_date, requested, kind in passive_orders:
                    allocation = min(cash, requested)
                    if allocation <= config.fixed_fee:
                        continue
                    execution_price = price * (Decimal("1") + config.slippage)
                    pre_fee_notional = (allocation - config.fixed_fee) / (
                        Decimal("1") + config.fee_rate
                    )
                    fee = quantize_money(
                        config.fixed_fee + pre_fee_notional * config.fee_rate
                    )
                    shares_bought = pre_fee_notional / execution_price
                    cash -= allocation
                    shares += shares_bought
                    total_fees += fee
                    trades.append(
                        Trade(
                            date=current_date,
                            signal_date=signal_date,
                            threshold=None,
                            cash_spent=allocation,
                            shares_bought=shares_bought,
                            raw_price=price,
                            execution_price=execution_price,
                            fee=fee,
                            kind=kind,
                        )
                    )
                dividend_orders = tuple(
                    order
                    for order in pending_dividends
                    if order.signal_date < current_date
                )
                pending_dividends = [
                    order
                    for order in pending_dividends
                    if order.signal_date >= current_date
                ]
                for dividend_order in dividend_orders:
                    allocation = min(cash, dividend_order.amount)
                    if allocation <= config.fixed_fee:
                        continue
                    execution_price = price * (Decimal("1") + config.slippage)
                    pre_fee_notional = (allocation - config.fixed_fee) / (
                        Decimal("1") + config.fee_rate
                    )
                    fee = quantize_money(
                        config.fixed_fee + pre_fee_notional * config.fee_rate
                    )
                    shares_bought = pre_fee_notional / execution_price
                    cash -= allocation
                    shares += shares_bought
                    total_fees += fee
                    trades.append(
                        Trade(
                            date=current_date,
                            signal_date=dividend_order.signal_date,
                            threshold=None,
                            cash_spent=allocation,
                            shares_bought=shares_bought,
                            raw_price=price,
                            execution_price=execution_price,
                            fee=fee,
                            kind="reinvest",
                        )
                    )
                orders = tuple(
                    order for order in pending if order.signal_date < current_date
                )
                pending = [
                    order for order in pending if order.signal_date >= current_date
                ]
                for tier_order in sorted(orders, key=lambda item: item.tier.depth):
                    allocation = quantize_money(cash * tier_order.tier.cash_fraction)
                    if allocation <= config.fixed_fee:
                        missed_thresholds.append(tier_order.tier.depth)
                        continue
                    execution_price = price * (Decimal("1") + config.slippage)
                    pre_fee_notional = (allocation - config.fixed_fee) / (
                        Decimal("1") + config.fee_rate
                    )
                    fee = quantize_money(
                        config.fixed_fee + pre_fee_notional * config.fee_rate
                    )
                    shares_bought = pre_fee_notional / execution_price
                    cash -= allocation
                    shares += shares_bought
                    total_fees += fee
                    trades.append(
                        Trade(
                            date=current_date,
                            signal_date=tier_order.signal_date,
                            threshold=tier_order.tier.depth,
                            cash_spent=allocation,
                            shares_bought=shares_bought,
                            raw_price=price,
                            execution_price=execution_price,
                            fee=fee,
                        )
                    )

            if _valid_positive(row["raw_close"]):
                last_close = _decimal(row["raw_close"])

        if timestamp in prototype_data.index:
            prototype_close = prototype_data.loc[timestamp, "price_close"]
            if _valid_positive(prototype_close):
                close = _decimal(prototype_close)
                if ath is None:
                    ath = close
                elif close > ath:
                    ath = close
                    if first_cycle_shares is None and triggered:
                        first_cycle_shares = shares
                    triggered.clear()
                else:
                    drawdown = Decimal("1") - close / ath
                    for tier in config.tiers:
                        if tier.depth <= drawdown and tier.depth not in triggered:
                            pending.append(_Order(current_date, tier))
                            triggered.add(tier.depth)

        if timestamp in traded_data.index:
            value = quantize_money(cash + shares * last_close)
            equity_curve.append(
                PortfolioPoint(
                    current_date,
                    cash,
                    shares,
                    last_close,
                    value,
                    external_flow_today,
                )
            )

    ending_value = quantize_money(cash + shares * last_close)
    external_cashflows.append(CashFlow(end, ending_value))
    missed = tuple(missed_thresholds) + tuple(order.tier.depth for order in pending)
    metrics = calculate_performance(
        values=tuple(point.value for point in equity_curve),
        dates=tuple(point.date for point in equity_curve),
        cash_values=tuple(point.cash for point in equity_curve),
        external_flows=tuple(point.external_flow for point in equity_curve),
        cashflows=tuple(external_cashflows),
        missed_thresholds=missed,
    )
    return StrategyResult(
        name=config.name,
        trades=tuple(trades),
        ending_cash=cash,
        ending_shares=shares,
        shares_after_first_cycle=first_cycle_shares or shares,
        dividend_income=dividend_income,
        contribution_total=contribution_total,
        interest_income=interest_income,
        total_fees=total_fees,
        equity_curve=tuple(equity_curve),
        external_cashflows=tuple(external_cashflows),
        pending_thresholds=tuple(order.tier.depth for order in pending),
        missed_thresholds=missed,
        metrics=metrics,
    )
