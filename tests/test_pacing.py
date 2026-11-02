"""Requests against the hosted sites' daily cap: counted, paced while idle, and woken locally.

The Cloudflare Free plan allows 100,000 requests a day for every site together (Nov 2), so an idle
worker must cost little: these tests hold the counting, the jittered backoff, the noun refresh
interval, the per-queue idle limit and the local wake files that let a worker look at once when a
worker on the same machine has just made work for it. No server is needed.
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from tessera import Lease

from eranos.jsonfile import load_json
from eranos.pacing import CountingTransport, RequestCounter, hourly_summary, poke, wake_mark
from eranos.pipeline import process as process_part
from eranos.worker_loop import Pacer, Worker, WorkerConfig

ROOT = Path(__file__).resolve().parents[1]
RULES = load_json(ROOT / "instructions" / "worker.json")


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Backend:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.rules, self.reads = rules, 0

    def get_record(self, store: str, key: str) -> Any:
        self.reads += 1
        if (store, key) == ("eranos.instructions", "worker"):
            return SimpleNamespace(value=self.rules)
        raise LookupError(f"{store}/{key}")


def _worker(
    tmp_path: Path, rules: dict[str, Any], *, role: str = "reviewer", clock: Any = None
) -> Worker:
    config = WorkerConfig(
        role=role,
        label="test-worker",
        tessera_url="http://127.0.0.1:9",
        key="x",
        key_id="k_test",
        trace_path=str(tmp_path / "trace.jsonl"),
    )
    return Worker(
        config,
        backend=Backend(rules),
        heartbeat_backend=object(),
        handler=process_part.StubHandler(),
        **({"clock": clock} if clock else {}),
    )


def test_every_request_is_counted_by_target_and_method_and_reported_once_an_hour() -> None:
    clock = Clock(3600 * 500 + 10)
    counter = RequestCounter(clock)
    inner = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    with httpx.Client(
        transport=CountingTransport(inner, counter, "tessera"), base_url="https://t.example"
    ) as http:
        http.get("/v1/health")
        http.post("/v1/claim", json={})
        http.get("/v1/health")
        assert counter.finished() == []  # the hour has not ended
        clock.now += 3600
        http.get("/v1/health")
    done = counter.finished()
    assert done == [(500, {"tessera GET": 2, "tessera POST": 1})]
    assert counter.finished() == [] and counter.current() == {"tessera GET": 1}
    summary = hourly_summary(*done[0])
    assert summary["by_target"] == {"tessera": 3} and summary["hour"].endswith(":00Z")
    assert counter.total == {"tessera GET": 3, "tessera POST": 1}


def test_idle_backoff_has_jitter_but_never_waits_less_than_without_it() -> None:
    plain, jittered = Pacer(60.0), Pacer(60.0, jitter=0.2, rng=random.Random(7))  # noqa: S311
    for n in range(8):
        now = 1000.0 * (n + 1)
        base = plain.empty("eq03", now, 5.0) - now
        waited = jittered.empty("eq03", now, 5.0) - now
        assert base <= waited <= base * 1.2 + 1e-9
    jittered.worked("eq03", 9000.0)
    assert jittered.ready("eq03", 9000.0) and jittered.idle["eq03"] == 0


def test_the_noun_sets_the_refresh_interval_and_each_queues_longest_idle_wait(
    tmp_path: Path,
) -> None:
    rules = {
        **RULES,
        "claims": {
            **RULES["claims"],
            "noun_refresh_seconds": 900,
            "max_idle_seconds_by_queue": {"eq01": 300, "eq03": 900},
            "idle_jitter": 0.2,
        },
    }
    clock = Clock(10_000.0)
    worker = _worker(tmp_path, rules, clock=clock)
    worker.rules()
    reads = worker.backend.reads
    clock.now += 600  # within the noun's 15 minutes: no new read
    worker.rules()
    assert worker.backend.reads == reads and worker.refresh_seconds() == 900
    clock.now += 400
    worker.rules()
    assert worker.backend.reads == reads + 1
    worker.pacing(rules["claims"])
    assert worker.pacer.max_idle_seconds == 900 and worker.pacer.jitter == 0.2
    planner = _worker(tmp_path, rules, role="planner")
    planner.pacing(rules["claims"])
    assert planner.pacer.max_idle_seconds == 300


def test_the_shipped_noun_paces_idle_workers_slowly(tmp_path: Path) -> None:
    claims = RULES["claims"]
    assert claims["noun_refresh_seconds"] >= 600 and claims["idle_jitter"] > 0
    assert claims["max_idle_seconds_by_queue"]["eq01"] <= 300  # new requests come from outside
    assert claims["max_idle_seconds_by_queue"]["eq02"] >= 600  # their work comes from the planner
    assert claims["max_idle_seconds_by_queue"]["eq03"] >= 600


def test_a_poke_ends_an_idle_wait_at_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ERANOS_WAKE_DIR", str(tmp_path / "wake"))
    worker = _worker(tmp_path, RULES)
    worker.pacer.next_at["eq03"] = worker.clock() + 3600  # an hour of idle ahead
    poke("eq03")
    started = time.monotonic()
    worker.idle_wait()
    assert time.monotonic() - started < 2.0 and worker.pacer.ready("eq03", worker.clock())
    assert any(
        json.loads(line)["event"] == "woken"
        for line in (tmp_path / "trace.jsonl").read_text().splitlines()
    )
    # The same poke does not wake it twice.
    worker.pacer.next_at["eq03"] = worker.clock() + 3600
    worker.stop.set()
    worker.idle_wait()
    assert not worker.pacer.ready("eq03", worker.clock())


def test_each_worker_wakes_the_queue_it_just_made_work_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ERANOS_WAKE_DIR", str(tmp_path / "wake"))
    worker = _worker(tmp_path, RULES)
    now = time.time()

    def lease(kind: str, queue: str) -> Lease:
        return Lease(
            task_id=f"{kind}-1",
            queue=queue,
            fencing_token=1,
            worker="t",
            attempt=1,
            kind=kind,
            effect_class="write-internal",
            brief={},
            claimed_at=now,
            expires_at=now + 60,
            hard_expires_at=now + 120,
            heartbeat_seconds=60,
        )

    worker.poke_after(lease("request", "eq01"), {"status": "split"})
    assert wake_mark("eq02") > 0 and wake_mark("eq03") > 0 and wake_mark("eq01") == 0
    worker.poke_after(lease("report_review", "eq03"), {"status": "delivered"})
    assert wake_mark("eq01") > 0
    os.utime(tmp_path / "wake" / "eq03", (1.0, 1.0))
    worker.poke_after(lease("research", "eq02"), {"status": "submitted"})
    assert wake_mark("eq03") > 1.0
