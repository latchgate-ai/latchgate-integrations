"""Tests for the sync-to-async bridge.

run_sync has two execution paths:
1. No running event loop → asyncio.run() (fast path)
2. Running event loop detected → background daemon thread (safe path)

Both must propagate return values and exceptions faithfully.
"""

from __future__ import annotations

import asyncio

import pytest

from latchgate_common.sync import run_sync

# ── Fast path (no event loop) ─────────────────────────────────────────────


class TestRunSyncNoEventLoop:
    """These are regular (non-async) tests — no event loop is running."""

    def test_returns_value(self) -> None:
        async def coro() -> int:
            return 42

        assert run_sync(coro()) == 42

    def test_returns_none(self) -> None:
        async def coro() -> None:
            pass

        assert run_sync(coro()) is None

    def test_propagates_value_error(self) -> None:
        async def coro() -> None:
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            run_sync(coro())

    def test_propagates_runtime_error(self) -> None:
        async def coro() -> None:
            raise RuntimeError("infra failure")

        with pytest.raises(RuntimeError, match="infra failure"):
            run_sync(coro())

    def test_async_work_executes(self) -> None:
        """Verify actual async operations complete — not just return."""

        async def coro() -> list[int]:
            results = []
            for i in range(3):
                await asyncio.sleep(0)
                results.append(i)
            return results

        assert run_sync(coro()) == [0, 1, 2]


# ── Background thread path (inside event loop) ───────────────────────────


class TestRunSyncInsideEventLoop:
    """Async tests — pytest-asyncio provides a running event loop."""

    async def test_returns_value(self) -> None:
        async def coro() -> str:
            return "hello"

        assert run_sync(coro()) == "hello"

    async def test_propagates_exception(self) -> None:
        async def coro() -> None:
            raise ValueError("from background thread")

        with pytest.raises(ValueError, match="from background thread"):
            run_sync(coro())

    async def test_async_sleep_completes(self) -> None:
        async def coro() -> int:
            await asyncio.sleep(0.01)
            return 99

        assert run_sync(coro()) == 99

    async def test_timeout_on_hung_coroutine(self) -> None:
        async def hung() -> None:
            await asyncio.sleep(60)

        with pytest.raises(TimeoutError, match="did not complete within"):
            run_sync(hung(), timeout=0.1)
