"""The AllocationStrategy plugin API: how reviewers are matched to submissions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from previewit.domain.allocation import Allocation, Problem


@runtime_checkable
class AllocationStrategy(Protocol):
    key: str
    label: str
    automatic: bool  # False: the organizer pairs people by hand

    def allocate(self, problem: Problem, seed: int) -> Allocation:
        """A pure function of the problem and the seed (same input, same output)."""
        ...


class UnknownStrategy(KeyError):
    pass


class StrategyRegistry:
    def __init__(self, strategies: Iterable[AllocationStrategy] = ()) -> None:
        self._items: dict[str, AllocationStrategy] = {}
        for s in strategies:
            self.register(s)

    def register(self, strategy: AllocationStrategy) -> None:
        if strategy.key in self._items:
            raise ValueError(f"allocation strategy {strategy.key!r} is registered twice")
        self._items[strategy.key] = strategy

    def get(self, key: str) -> AllocationStrategy:
        try:
            return self._items[key]
        except KeyError:
            raise UnknownStrategy(key) from None

    def all(self) -> list[AllocationStrategy]:
        return list(self._items.values())
