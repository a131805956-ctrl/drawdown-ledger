from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def policy_cutoff(as_of: date) -> date:
    return as_of.replace(day=1) - timedelta(days=1)


def last_session_on_or_before(index: pd.DatetimeIndex, cutoff: date) -> date:
    eligible = index[index.normalize() <= pd.Timestamp(cutoff)]
    if eligible.empty:
        raise ValueError("No market session exists on or before cutoff")
    return eligible[-1].date()
