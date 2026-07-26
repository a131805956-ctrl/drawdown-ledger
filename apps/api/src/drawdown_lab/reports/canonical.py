"""Canonical encodings shared by report rendering and verification."""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

CANDIDATE_FIELDS = (
    "ratios",
    "fold_oos_xirr",
    "oos_xirr",
    "stability_score",
    "stability_adjusted_xirr",
    "neighbor_count",
    "worst_5_return",
    "early_depletion_rate",
    "longest_trap_days",
    "synthetic_stress_pass",
    "pareto_member",
    "recommendation_labels",
    "fold_evaluations",
    "walk_forward_eligible",
)
RECOMMENDATION_FIELDS = (
    "profile",
    "ratios",
    "oos_xirr",
    "stability_adjusted_xirr",
)
TRADE_FIELDS = (
    "date",
    "signal_date",
    "threshold",
    "cash_spent",
    "shares_bought",
    "raw_price",
    "execution_price",
    "fee",
    "prototype_drawdown",
    "target_drawdown",
    "post_trade_cash",
    "marker_profit_loss",
    "kind",
)


def canonical_jsonable(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Report payload cannot contain non-finite floats")
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("Report datetimes must be timezone-aware")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return canonical_jsonable(value.value)
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Report mapping keys must be strings")
            normalized[key] = canonical_jsonable(item)
        return dict(sorted(normalized.items()))
    if isinstance(value, Sequence) and not isinstance(
        value,
        (bytes, bytearray, str),
    ):
        return [canonical_jsonable(item) for item in value]
    raise TypeError(f"Unsupported report payload type: {type(value).__name__}")


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            canonical_jsonable(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _csv_cell(value: object) -> str:
    normalized = canonical_jsonable(value)
    if normalized is None:
        return ""
    if isinstance(normalized, (dict, list)):
        return json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    if isinstance(normalized, bool):
        return "true" if normalized else "false"
    return str(normalized)


def canonical_csv_bytes(
    rows: Sequence[Mapping[str, object]],
    *,
    empty_fields: Sequence[str],
) -> bytes:
    normalized_rows = [dict(row) for row in rows]
    fields = sorted(
        {key for row in normalized_rows for key in row}
        or set(empty_fields)
    )
    stream = io.StringIO(newline="")
    if fields:
        writer = csv.DictWriter(
            stream,
            fieldnames=fields,
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in normalized_rows:
            writer.writerow(
                {field: _csv_cell(row.get(field)) for field in fields}
            )
    return stream.getvalue().encode("utf-8")
