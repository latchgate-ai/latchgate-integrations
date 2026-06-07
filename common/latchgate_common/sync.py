"""Sync-to-async bridge for LatchGate framework integrations.

Provides a safe way to call async LatchGate operations from synchronous
code, including inside a running event loop (Jupyter, FastAPI, Celery).

The previous approach used ``nest_asyncio.apply()`` which monkey-patches
the running event loop globally. This caused subtle reentrancy bugs and
introduced a hidden global side-effect. The background-thread approach
here is isolated: each sync call gets its own event loop on a daemon
thread, with no mutation of the caller's loop.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any, TypeVar

T = TypeVar("T")

_DEFAULT_TIMEOUT_SECONDS: float = 120.0


def run_sync(coro: Coroutine[Any, Any, T], *, timeout: float = _DEFAULT_TIMEOUT_SECONDS) -> T:
    """Run an async coroutine from synchronous context.

    Behaviour:

    - **No running loop** — delegates to ``asyncio.run()``.
    - **Running loop detected** — spawns a daemon thread with its own
      event loop, runs the coroutine there, and blocks until completion.
      No global side-effects, no monkey-patching.

    Parameters
    ----------
    coro:
        The coroutine to execute.
    timeout:
        Maximum seconds to wait for the background thread to complete.
        Only applies when a running event loop forces the background-thread
        path. Default: 120s.

    Returns
    -------
    The coroutine's return value.

    Raises
    ------
    TimeoutError
        If the background thread does not complete within ``timeout``.
    Exception
        Any exception raised by the coroutine is re-raised in the
        calling thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — fast path.
        return asyncio.run(coro)

    # Inside a running loop — run in a background thread to avoid
    # blocking the caller's loop or requiring nest_asyncio.
    future: Future[T] = Future()

    def _run_in_thread() -> None:
        try:
            result = asyncio.run(coro)
            future.set_result(result)
        except BaseException as exc:
            future.set_exception(exc)

    thread = threading.Thread(target=_run_in_thread, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        raise TimeoutError(
            f"LatchGate operation did not complete within {timeout}s. "
            f"The background thread is still running — this usually "
            f"indicates a hung network call or unresponsive gate."
        )

    return future.result()
