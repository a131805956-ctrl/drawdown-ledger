from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TypeAlias

Money: TypeAlias = Decimal
CENT = Decimal("0.01")


def as_decimal(value: Decimal | int | float | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_money(value: Decimal | int | float | str) -> Money:
    return as_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
