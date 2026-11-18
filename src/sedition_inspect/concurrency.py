"""Small concurrency helpers owned by the AI Sedition adapter."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar, cast

import anyio

T = TypeVar("T")


async def collect_concurrently(
    factories: Iterable[Callable[[], Awaitable[T]]],
) -> list[T]:
    """Run awaitable factories concurrently and preserve input order."""
    pending = list(factories)
    results: list[T | None] = [None] * len(pending)

    async def run_one(index: int, factory: Callable[[], Awaitable[T]]) -> None:
        results[index] = await factory()

    async with anyio.create_task_group() as task_group:
        for index, factory in enumerate(pending):
            task_group.start_soon(run_one, index, factory)

    return cast(list[T], results)
