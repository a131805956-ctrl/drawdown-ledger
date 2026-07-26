from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

MarketSymbolRole = Literal["tradable", "prototype"]


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    name: str
    family_id: str
    leverage: int
    prototype_symbol: str
    currency: str
    timezone: str
    inception: date | None = None


@dataclass(frozen=True, slots=True)
class InstrumentFamily:
    id: str
    name: str
    benchmark_symbol: str
    instruments: tuple[Instrument, ...]


def _instrument(
    symbol: str,
    name: str,
    family_id: str,
    leverage: int,
    prototype_symbol: str,
    currency: str,
    timezone: str,
) -> Instrument:
    return Instrument(
        symbol=symbol,
        name=name,
        family_id=family_id,
        leverage=leverage,
        prototype_symbol=prototype_symbol,
        currency=currency,
        timezone=timezone,
    )


INSTRUMENT_FAMILIES: tuple[InstrumentFamily, ...] = (
    InstrumentFamily(
        id="taiwan-50",
        name="Taiwan 50",
        benchmark_symbol="0050.TW",
        instruments=(
            _instrument(
                "0050.TW", "Yuanta Taiwan Top 50", "taiwan-50", 1, "0050.TW", "TWD", "Asia/Taipei"
            ),
            _instrument(
                "00631L.TW",
                "Yuanta Taiwan 50 Leveraged 2X",
                "taiwan-50",
                2,
                "0050.TW",
                "TWD",
                "Asia/Taipei",
            ),
        ),
    ),
    InstrumentFamily(
        id="taiwan-weighted",
        name="Taiwan Weighted",
        benchmark_symbol="^TWII",
        instruments=(
            _instrument(
                "006204.TW", "SinoPac TAIEX", "taiwan-weighted", 1, "^TWII", "TWD", "Asia/Taipei"
            ),
            _instrument(
                "00685L.TW",
                "Fubon TAIEX Leveraged 2X",
                "taiwan-weighted",
                2,
                "^TWII",
                "TWD",
                "Asia/Taipei",
            ),
        ),
    ),
    InstrumentFamily(
        id="nasdaq-100",
        name="Nasdaq-100",
        benchmark_symbol="^NDX",
        instruments=(
            _instrument(
                "QQQ", "Invesco QQQ Trust", "nasdaq-100", 1, "QQQ", "USD", "America/New_York"
            ),
            _instrument(
                "QLD", "ProShares Ultra QQQ", "nasdaq-100", 2, "QQQ", "USD", "America/New_York"
            ),
            _instrument(
                "TQQQ", "ProShares UltraPro QQQ", "nasdaq-100", 3, "QQQ", "USD", "America/New_York"
            ),
        ),
    ),
    InstrumentFamily(
        id="sp-500",
        name="S&P 500",
        benchmark_symbol="^GSPC",
        instruments=(
            _instrument(
                "SPY", "SPDR S&P 500 ETF Trust", "sp-500", 1, "SPY", "USD", "America/New_York"
            ),
            _instrument(
                "SSO", "ProShares Ultra S&P500", "sp-500", 2, "SPY", "USD", "America/New_York"
            ),
            _instrument(
                "UPRO", "ProShares UltraPro S&P500", "sp-500", 3, "SPY", "USD", "America/New_York"
            ),
        ),
    ),
    InstrumentFamily(
        id="dow-jones-industrial-average",
        name="Dow Jones Industrial Average",
        benchmark_symbol="^DJI",
        instruments=(
            _instrument(
                "DIA",
                "SPDR Dow Jones Industrial Average ETF Trust",
                "dow-jones-industrial-average",
                1,
                "DIA",
                "USD",
                "America/New_York",
            ),
            _instrument(
                "DDM",
                "ProShares Ultra Dow30",
                "dow-jones-industrial-average",
                2,
                "DIA",
                "USD",
                "America/New_York",
            ),
            _instrument(
                "UDOW",
                "ProShares UltraPro Dow30",
                "dow-jones-industrial-average",
                3,
                "DIA",
                "USD",
                "America/New_York",
            ),
        ),
    ),
    InstrumentFamily(
        id="russell-2000",
        name="Russell 2000",
        benchmark_symbol="^RUT",
        instruments=(
            _instrument(
                "IWM",
                "iShares Russell 2000 ETF",
                "russell-2000",
                1,
                "IWM",
                "USD",
                "America/New_York",
            ),
            _instrument(
                "UWM",
                "ProShares Ultra Russell2000",
                "russell-2000",
                2,
                "IWM",
                "USD",
                "America/New_York",
            ),
            _instrument(
                "URTY",
                "ProShares UltraPro Russell2000",
                "russell-2000",
                3,
                "IWM",
                "USD",
                "America/New_York",
            ),
        ),
    ),
)


def market_symbol_roles() -> dict[str, tuple[MarketSymbolRole, ...]]:
    """Return every trusted series required by the registered instruments.

    Prototype-only symbols stay out of ``INSTRUMENT_FAMILIES[*].instruments``
    so they cannot accidentally become user-selectable traded targets.
    """

    roles_by_symbol: dict[str, list[MarketSymbolRole]] = {}
    for family in INSTRUMENT_FAMILIES:
        for instrument in family.instruments:
            roles_by_symbol.setdefault(instrument.symbol, []).append("tradable")
            prototype_roles = roles_by_symbol.setdefault(
                instrument.prototype_symbol,
                [],
            )
            if "prototype" not in prototype_roles:
                prototype_roles.append("prototype")
    return {
        symbol: tuple(roles)
        for symbol, roles in roles_by_symbol.items()
    }


def required_market_symbols() -> tuple[str, ...]:
    return tuple(market_symbol_roles())


class InstrumentFamilyNotFoundError(LookupError):
    pass


class InstrumentFamilyMismatchError(ValueError):
    pass


def resolve_family_instrument(
    family_id: str,
    target_symbol: str,
) -> tuple[InstrumentFamily, Instrument]:
    family = next(
        (candidate for candidate in INSTRUMENT_FAMILIES if candidate.id == family_id),
        None,
    )
    if family is None:
        raise InstrumentFamilyNotFoundError(f"Unknown instrument family: {family_id}")
    target = next(
        (
            instrument
            for instrument in family.instruments
            if instrument.symbol == target_symbol
        ),
        None,
    )
    if target is None:
        raise InstrumentFamilyMismatchError(
            f"Target symbol {target_symbol} does not belong to family {family_id}"
        )
    return family, target
