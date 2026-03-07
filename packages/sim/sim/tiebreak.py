from __future__ import annotations

from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


def stable_sorted(items: Iterable[T], key: Callable[[T], tuple]) -> list[T]:
    indexed = list(enumerate(items))
    indexed.sort(key=lambda pair: (*key(pair[1]), pair[0]))
    return [item for _, item in indexed]


def stable_argmax(items: Iterable[T], key: Callable[[T], tuple]) -> T | None:
    indexed = list(enumerate(items))
    if not indexed:
        return None
    indexed.sort(key=lambda pair: (*key(pair[1]), -pair[0]), reverse=True)
    return indexed[0][1]
