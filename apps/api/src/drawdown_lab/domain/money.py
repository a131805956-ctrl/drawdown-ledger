from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, DecimalException
from typing import TypeAlias

Money: TypeAlias = Decimal
CENT = Decimal("0.01")
MAX_SAFE_DECIMAL = Decimal("999999999999999999.99")


def as_decimal(value: Decimal | int | float | str) -> Decimal:
    try:
        normalized = value if isinstance(value, Decimal) else Decimal(str(value))
    except (DecimalException, ValueError) as error:
        raise ValueError("Decimal value is invalid") from error
    if not normalized.is_finite():
        raise ValueError("Decimal value must be finite")
    if normalized.copy_abs() > MAX_SAFE_DECIMAL:
        raise ValueError(
            f"Decimal value exceeds the safe maximum of {MAX_SAFE_DECIMAL}"
        )
    return normalized


def quantize_money(value: Decimal | int | float | str) -> Money:
    try:
        return as_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
    except DecimalException as error:
        raise ValueError("Money value cannot be represented safely") from error
