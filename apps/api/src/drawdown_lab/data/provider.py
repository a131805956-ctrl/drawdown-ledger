from __future__ import annotations

from datetime import date
from typing import Protocol

from drawdown_lab.data.models import MarketFrame


class MarketDataProvider(Protocol):
    def fetch(self, symbol: str, start: date, end: date) -> MarketFrame:
        """Fetch inclusive daily history for ``symbol`` from ``start`` through ``end``."""
