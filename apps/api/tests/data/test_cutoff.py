from datetime import date

import pandas as pd
from drawdown_lab.data.cutoff import last_session_on_or_before, policy_cutoff


def test_august_uses_july_31_cutoff() -> None:
    assert policy_cutoff(date(2026, 8, 1)) == date(2026, 7, 31)


def test_last_session_selects_latest_session_not_after_cutoff() -> None:
    index = pd.DatetimeIndex(["2026-07-29", "2026-07-30", "2026-08-03"])

    assert last_session_on_or_before(index, date(2026, 7, 31)) == date(2026, 7, 30)
