from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal, cast

import pandas as pd

from drawdown_lab.data.catalog import DataCatalog
from drawdown_lab.data.cutoff import policy_cutoff
from drawdown_lab.data.models import MarketFrame, merge_market_frames, validate_market_frame
from drawdown_lab.data.provider import MarketDataProvider
from drawdown_lab.domain.instruments import required_market_symbols


class DataUpdateError(RuntimeError):
    """A provider response could not safely replace the cached market data."""


@dataclass(frozen=True, slots=True)
class UpdateFailure:
    symbol: str
    message: str


@dataclass(frozen=True, slots=True)
class UpdateSummary:
    status: Literal["completed", "partial", "failed"]
    cutoff: date
    request_count: int
    refreshed_symbols: tuple[str, ...]
    failures: tuple[UpdateFailure, ...]


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
        failures: list[UpdateFailure] = []
        symbols = self.symbols if self.symbols is not None else self._approved_symbols()

        for symbol in symbols:
            try:
                if self.catalog.is_complete_through(symbol, cutoff):
                    continue

                existing = self.catalog.read(symbol)
                start = self._refresh_start(existing)
                requests += 1
                refreshed = self.provider.fetch(symbol, start, cutoff)
                validate_market_frame(refreshed)
                merged = merge_market_frames(existing, refreshed)
                validate_market_frame(merged)
                provider_name = str(
                    getattr(
                        self.provider,
                        "provider_name",
                        f"{type(self.provider).__module__}.{type(self.provider).__qualname__}",
                    )
                )
                self.catalog.store(
                    symbol,
                    merged,
                    completed_cutoff=cutoff,
                    provider=provider_name,
                )
            except Exception as error:
                message = str(error).strip() or type(error).__name__
                failures.append(UpdateFailure(symbol=symbol, message=message))
                continue
            refreshed_symbols.append(symbol)

        status: Literal["completed", "partial", "failed"]
        if not failures:
            status = "completed"
        elif refreshed_symbols:
            status = "partial"
        else:
            status = "failed"
        return UpdateSummary(
            status=status,
            cutoff=cutoff,
            request_count=requests,
            refreshed_symbols=tuple(refreshed_symbols),
            failures=tuple(failures),
        )

    @staticmethod
    def _refresh_start(existing: MarketFrame | None) -> date:
        if existing is None:
            return date(1970, 1, 1)
        sessions = existing.data.index
        return cast(pd.Timestamp, sessions[max(0, len(sessions) - 5)]).date()

    @staticmethod
    def _approved_symbols() -> tuple[str, ...]:
        return required_market_symbols()
