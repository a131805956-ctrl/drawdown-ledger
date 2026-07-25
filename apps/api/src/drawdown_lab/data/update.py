from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import cast

import pandas as pd

from drawdown_lab.data.catalog import DataCatalog
from drawdown_lab.data.cutoff import policy_cutoff
from drawdown_lab.data.models import MarketFrame, merge_market_frames, validate_market_frame
from drawdown_lab.data.provider import MarketDataProvider
from drawdown_lab.domain.instruments import INSTRUMENT_FAMILIES


class DataUpdateError(RuntimeError):
    """A provider response could not safely replace the cached market data."""


@dataclass(frozen=True, slots=True)
class UpdateSummary:
    cutoff: date
    request_count: int
    refreshed_symbols: tuple[str, ...]


class UpdateCoordinator:
    def __init__(
        self,
        provider: MarketDataProvider,
        catalog: DataCatalog,
        symbols: Iterable[str] | None = None,
    ) -> None:
        self.provider = provider
        self.catalog = catalog
        self.symbols = tuple(symbols) if symbols is not None else None

    def ensure_current(self, as_of: date) -> UpdateSummary:
        cutoff = policy_cutoff(as_of)
        requests = 0
        refreshed_symbols: list[str] = []
        symbols = self.symbols if self.symbols is not None else self._approved_symbols()

        for symbol in symbols:
            if self.catalog.is_complete_through(symbol, cutoff):
                continue

            existing = self.catalog.read(symbol)
            start = self._refresh_start(existing)
            try:
                refreshed = self.provider.fetch(symbol, start, cutoff)
                validate_market_frame(refreshed)
                merged = merge_market_frames(existing, refreshed)
                validate_market_frame(merged)
                self.catalog.store(symbol, merged, completed_cutoff=cutoff)
            except DataUpdateError:
                raise
            except Exception as error:
                raise DataUpdateError(f"Failed to update {symbol}: {error}") from error
            requests += 1
            refreshed_symbols.append(symbol)

        return UpdateSummary(cutoff, requests, tuple(refreshed_symbols))

    @staticmethod
    def _refresh_start(existing: MarketFrame | None) -> date:
        if existing is None:
            return date(1970, 1, 1)
        sessions = existing.data.index
        return cast(pd.Timestamp, sessions[max(0, len(sessions) - 5)]).date()

    @staticmethod
    def _approved_symbols() -> tuple[str, ...]:
        return tuple(
            instrument.symbol for family in INSTRUMENT_FAMILIES for instrument in family.instruments
        )
