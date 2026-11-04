"""What the workers' requests cost, counted, and local wake-ups instead of fast polling.

The hosted sites share one daily cap on requests (the Cloudflare Free plan: 100,000 a day for the
whole account, Nov 2), so an idle worker must cost little. Claims back off while a queue is empty
(`Pacer` in the worker loop, with jitter so restarted workers do not poll in step), the nouns a
worker reads are refreshed at most every `claims.noun_refresh_seconds`, and every request a worker
sends is counted by target and method and written to its run log once an hour (`requests_hourly`).

A worker that makes work for another queue on this machine touches that queue's wake file, so the
worker that claims it looks at once rather than polling often: the planner after it splits a request,
a maker after it submits, a checker after it decides (the request then wakes for the planner). An
operator can do the same with `touch` (for example to have a reopened request picked up while a
recording runs). A wake file holds nothing; it is read with one local stat, never over the network.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

WAKE_ENV = "ERANOS_WAKE_DIR"


def wake_dir() -> Path:
    return Path(os.environ.get(WAKE_ENV) or Path.home() / ".local/state/eranos-worker/wake")


def poke(queue: str) -> None:
    """Ask the local worker of `queue` to look now (best effort: a failure only means it polls later)."""
    with contextlib.suppress(OSError):
        folder = wake_dir()
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = folder / queue
        path.touch(mode=0o600, exist_ok=True)
        os.utime(path)


def wake_mark(queue: str) -> float:
    """When `queue` was last poked (0 when never)."""
    try:
        return (wake_dir() / queue).stat().st_mtime
    except OSError:
        return 0.0


class RequestCounter:
    """Requests by target (`tessera`, `meta`) and method, in whole UTC hours; thread-safe."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._hour = int(clock() // 3600)
        self._counts: Counter[str] = Counter()
        self._done: list[tuple[int, dict[str, int]]] = []
        self.total: Counter[str] = Counter()

    def _roll(self, now: float) -> None:
        hour = int(now // 3600)
        if hour != self._hour:
            if self._counts:
                self._done.append((self._hour, dict(self._counts)))
            self._hour, self._counts = hour, Counter()

    def add(self, target: str, method: str) -> None:
        with self._lock:
            self._roll(self.clock())
            self._counts[f"{target} {method}"] += 1
            self.total[f"{target} {method}"] += 1

    def finished(self) -> list[tuple[int, dict[str, int]]]:
        """The whole hours that ended since the last call, with their counts (each reported once)."""
        with self._lock:
            self._roll(self.clock())
            done, self._done = self._done, []
            return done

    def current(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)


class CountingTransport(httpx.BaseTransport):
    """Counts every request through it, then sends it unchanged."""

    def __init__(self, inner: httpx.BaseTransport, counter: RequestCounter, target: str) -> None:
        self.inner, self.counter, self.target = inner, counter, target

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.counter.add(self.target, request.method)
        return self.inner.handle_request(request)

    def close(self) -> None:
        self.inner.close()


def hourly_summary(hour: int, counts: dict[str, int]) -> dict[str, Any]:
    """One hour's counts as the run log records them: per target and method, and per target."""
    by_target: Counter[str] = Counter()
    for key, n in counts.items():
        by_target[key.split(" ", 1)[0]] += n
    start = time.strftime("%Y-%m-%dT%H:00Z", time.gmtime(hour * 3600))
    return {"hour": start, "requests": dict(sorted(counts.items())), "by_target": dict(by_target)}
