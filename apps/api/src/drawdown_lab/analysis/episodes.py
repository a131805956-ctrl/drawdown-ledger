from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import cast

import pandas as pd

from drawdown_lab.data.models import MarketFrame, validate_market_frame


@dataclass(frozen=True, slots=True)
class DrawdownEpisode:
    threshold: float
    cycle_id: int
    peak_date: date
    peak_price: float
    signal_date: date
    signal_price: float
    drawdown: float
    recovery_date: date | None = None
    recovery_sessions: int | None = None

    @property
    def v_recovered(self) -> bool:
        return self.recovery_sessions is not None and self.recovery_sessions <= 126


def _validate_thresholds(thresholds: tuple[float, ...]) -> tuple[float, ...]:
    if not thresholds or any(depth <= 0.0 or depth > 1.0 for depth in thresholds):
        raise ValueError("Drawdown thresholds must be positive ratios no greater than 1")
    return tuple(sorted(set(thresholds)))


def _as_date(value: object) -> date:
    return cast(pd.Timestamp, value).date()


def classify_episodes(
    frame: MarketFrame,
    thresholds: tuple[float, ...],
) -> tuple[DrawdownEpisode, ...]:
    """Return the first trigger for each depth in every strict-new-ATH cycle."""

    validate_market_frame(frame)
    depths = _validate_thresholds(thresholds)
    close = frame.data["price_close"].astype(float)

    peak_price = float(close.iloc[0])
    peak_position = 0
    cycle_id = 1
    triggered: set[float] = set()
    episodes: list[tuple[DrawdownEpisode, int]] = []

    for position, (timestamp, value) in enumerate(close.items()):
        price = float(value)
        if price > peak_price:
            peak_price = price
            peak_position = position
            cycle_id += 1
            triggered.clear()
            continue

        drawdown = price / peak_price - 1.0
        for depth in depths:
            if depth not in triggered and price <= peak_price * (1.0 - depth):
                episodes.append(
                    (
                        DrawdownEpisode(
                            threshold=depth,
                            cycle_id=cycle_id,
                            peak_date=_as_date(close.index[peak_position]),
                            peak_price=peak_price,
                            signal_date=_as_date(timestamp),
                            signal_price=price,
                            drawdown=drawdown,
                        ),
                        position,
                    )
                )
                triggered.add(depth)

    recovered: list[DrawdownEpisode] = []
    for episode, signal_position in episodes:
        recovery_date: date | None = None
        recovery_sessions: int | None = None
        later = close.iloc[signal_position + 1 :]
        for offset, (recovery_timestamp, recovery_value) in enumerate(later.items(), start=1):
            if float(recovery_value) >= episode.peak_price:
                recovery_date = _as_date(recovery_timestamp)
                recovery_sessions = offset
                break
        recovered.append(
            replace(
                episode,
                recovery_date=recovery_date,
                recovery_sessions=recovery_sessions,
            )
        )

    return tuple(recovered)
