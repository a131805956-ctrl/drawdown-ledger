from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from drawdown_lab.analysis.strategy import (
    StrategyConfig,
    StrategyResult,
    ThresholdTier,
    simulate_strategy,
)
from drawdown_lab.data.models import MarketFrame


def build_baselines(
    config: StrategyConfig,
    prototype: MarketFrame,
    traded: MarketFrame,
) -> tuple[StrategyResult, ...]:
    """Build comparable DCA, cash, simple-trigger, and lump-sum paths.

    DCA spreads starting cash over twelve first-valid monthly opens and invests
    scheduled deposits immediately. Buy-and-hold invests starting cash at the
    first valid open and also invests later scheduled deposits immediately.
    """

    shallowest = config.tiers[0].depth if config.tiers else Decimal("0.20")
    baseline_configs = (
        replace(
            config,
            name="DCA",
            tiers=(),
            scheduled_initial_months=12,
            invest_contributions_immediately=True,
        ),
        replace(
            config,
            name="cash",
            tiers=(),
            scheduled_initial_months=0,
            invest_contributions_immediately=False,
        ),
        replace(
            config,
            name="simple-threshold",
            tiers=(ThresholdTier(shallowest, Decimal("1")),),
            scheduled_initial_months=0,
            invest_contributions_immediately=False,
        ),
        replace(
            config,
            name="buy-and-hold",
            tiers=(),
            scheduled_initial_months=1,
            invest_contributions_immediately=True,
        ),
    )
    return tuple(
        simulate_strategy(baseline, prototype, traded) for baseline in baseline_configs
    )
