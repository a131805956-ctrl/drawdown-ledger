from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, TypeVar


class ParetoCandidate(Protocol):
    @property
    def oos_xirr(self) -> float: ...

    @property
    def worst_5_return(self) -> float: ...

    @property
    def early_depletion_rate(self) -> float: ...

    @property
    def longest_trap_days(self) -> int: ...


ParetoCandidateT = TypeVar("ParetoCandidateT", bound=ParetoCandidate)


def dominates(left: ParetoCandidate, right: ParetoCandidate) -> bool:
    no_worse = (
        left.oos_xirr >= right.oos_xirr
        and left.worst_5_return >= right.worst_5_return
        and left.early_depletion_rate <= right.early_depletion_rate
        and left.longest_trap_days <= right.longest_trap_days
    )
    strictly_better = (
        left.oos_xirr > right.oos_xirr
        or left.worst_5_return > right.worst_5_return
        or left.early_depletion_rate < right.early_depletion_rate
        or left.longest_trap_days < right.longest_trap_days
    )
    return no_worse and strictly_better


def pareto_membership(candidates: Iterable[ParetoCandidateT]) -> tuple[bool, ...]:
    rows = tuple(candidates)
    return tuple(
        not any(dominates(other, candidate) for other in rows if other is not candidate)
        for candidate in rows
    )


def pareto_frontier(
    candidates: Iterable[ParetoCandidateT],
) -> tuple[ParetoCandidateT, ...]:
    rows = tuple(candidates)
    membership = pareto_membership(rows)
    return tuple(row for row, is_member in zip(rows, membership, strict=True) if is_member)
