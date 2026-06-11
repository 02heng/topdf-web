"""简单撤销栈（快照恢复）。"""
from __future__ import annotations

import copy
from typing import Any, Callable, Generic, List, Optional, TypeVar

T = TypeVar("T")


class UndoStack(Generic[T]):
    def __init__(self, *, max_size: int = 50) -> None:
        self._max = max(1, max_size)
        self._items: List[T] = []

    def push(self, snapshot: T) -> None:
        self._items.append(copy.deepcopy(snapshot))
        if len(self._items) > self._max:
            self._items.pop(0)

    def pop(self) -> Optional[T]:
        if not self._items:
            return None
        return self._items.pop()

    def clear(self) -> None:
        self._items.clear()

    @property
    def can_undo(self) -> bool:
        return bool(self._items)
