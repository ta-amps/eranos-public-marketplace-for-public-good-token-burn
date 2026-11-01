"""Volunteer workers on Eranos's queues: `eranos work --role planner|builder|reviewer`.

One loop per role, each with its own scoped key:
- planner claims request verbs on eq01: checks, reuses, splits, closes, and parks recurring requests;
- builder claims work verbs on eq02: research (local model, permitted sources), kit builds, process
  packages (through the B4 handler interface);
- reviewer claims review verbs on eq03 with a different key: re-checks and delivers or publishes.

Every lease follows the same cycle: claim (an empty claim waits at least a minute, or longer when the
server's Retry-After says so), heartbeat in the background, do the work, submit once with an
idempotency key and an execution report (harness, model, adapter, tokens, cost), and write each state
change into the request's public record. Every failure is submitted with ok=false when the lease is
still held, and every failure (including a lost lease) is written to the run log and the request's
record. The key lives only in the environment; it is never printed or logged.
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx
from tessera import (
    InvalidState,
    Lease,
    NotFound,
    RateLimited,
    StaleLease,
    StorageQuotaExhausted,
    TesseraError,
    Unavailable,
)
from tessera.client import Client, _retry_after

from eranos import __version__
from eranos.adapter.traced import TracedBackend
from eranos.log import TraceWriter
from eranos.model_client import (
    DEFAULT_MODEL,
    DEFAULT_URL,
    ModelUnavailable,
    OllamaModel,
    UsageMeter,
)
from eranos.pipeline import process as process_part
from eranos.pipeline import research
from eranos.pipeline.planner import Planner, load_nouns
from eranos.pipeline.status_events import fact, queue_snapshot, record_events
from eranos.sources import Fetched, fetch, policy_from_rules

# Kit builds and kit reviews are not claimed here: kits carry a fixture mark these workers must
# not publish. Work on a nonprofit's own files goes through process packages instead.
ROLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "planner": ("eq01", ("request",)),
    "builder": ("eq02", ("research", process_part.BUILD_KIND)),
    "reviewer": ("eq03", ("report_review", process_part.REVIEW_KIND)),
}
DECLARED = {
    "request": "deterministic planner (no model)",
    "report_review": "deterministic re-fetch and quote check (no model)",
    process_part.REVIEW_KIND: "process handler review, in a clean process",
}
EXIT_STORAGE_ALLOWANCE = (
    75  # EX_TEMPFAIL: the hosted storage allowance is spent; the units do not restart
)


class WorkerClient(Client):
    """Tessera's client plus the claim hints the plain client drops (204 Retry-After, heartbeat)."""

    def claim_with_hint(
        self, queue: str, worker: str, *, kinds: list[str]
    ) -> tuple[Lease | None, float, int]:
        body = {"queue": queue, "worker": worker, "kinds": kinds}
        response = self._call("POST", "/v1/tasks/claim", body=body)
        beat = int(response.headers.get("x-heartbeat-seconds") or 60)
        if response.status_code == 204:
            return None, _retry_after(response), beat
        return Lease.model_validate(response.json()), 0.0, beat

    def ready_verbs(self, queue: str) -> list[dict[str, Any]]:
        """Ready verbs this key may see on a queue, oldest first (a read; it claims nothing)."""
        response = self._call(
            "GET", "/v1/verbs", params={"queue": queue, "status": "ready", "limit": 100}
        )
        return [dict(v) for v in response.json().get("verbs") or []]


@dataclass
class Pacer:
    """When each queue may be claimed again: at most one empty claim per queue per interval."""

    min_empty_seconds: float = 60.0
    next_at: dict[str, float] = field(default_factory=dict)

    def ready(self, queue: str, now: float) -> bool:
        return now >= self.next_at.get(queue, 0.0)

    def empty(self, queue: str, now: float, retry_after: float) -> float:
        self.next_at[queue] = now + max(self.min_empty_seconds, retry_after)
        return self.next_at[queue]

    def refused(self, queue: str, now: float, retry_after: float) -> float:
        self.next_at[queue] = now + max(1.0, retry_after)
        return self.next_at[queue]

    def worked(self, queue: str, now: float) -> None:
        self.next_at[queue] = now

    def wait(self, now: float) -> float:
        if not self.next_at:
            return 0.0
        return max(0.0, min(self.next_at.values()) - now)


class LeaseGate:
    """The backend a step sees while one lease is held: claim hands over that lease once, submit
    adds the execution report and happens once, and split, park or submit end the heartbeat."""

    def __init__(
        self, inner: Any, lease: Lease, report: Callable[[Any, bool, str | None], dict[str, Any]]
    ) -> None:
        self._inner = inner
        self.lease = lease
        self._report = report
        self._handed = False
        self.ended: str | None = None
        self.receipt: Any = None
        self.ended_event = threading.Event()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def claim(
        self,
        queue: str,
        worker: str,
        *,
        kinds: Any = None,
        effect_classes: Any = None,
        key_id: Any = None,
    ) -> Lease | None:
        if self._handed or queue != self.lease.queue or (kinds and self.lease.kind not in kinds):
            return None
        self._handed = True
        return self.lease

    def _end(self, how: str) -> None:
        self.ended = how
        self.ended_event.set()

    def submit(
        self,
        task_id: str,
        fencing_token: int,
        output: Any,
        *,
        idempotency_key: str,
        ok: bool = True,
        error: str | None = None,
    ) -> Any:
        if task_id != self.lease.task_id or fencing_token != self.lease.fencing_token:
            raise StaleLease("a step tried to submit a verb this worker does not hold")
        if self.ended:
            raise InvalidState(f"this lease already ended ({self.ended}); a verb is submitted once")
        report = self._report(output, ok, error)
        for attempt in range(3):  # the same idempotency key makes a repeated submit safe
            try:
                self.receipt = self._inner.submit(
                    task_id,
                    fencing_token,
                    output,
                    idempotency_key=idempotency_key,
                    ok=ok,
                    error=error,
                    execution_report=report,
                )
                break
            except (StaleLease, NotFound, InvalidState):
                self._end("lost")
                raise
            except StorageQuotaExhausted:
                raise  # never retried: the allowance stays spent until it resets
            except (Unavailable, httpx.TransportError):
                if attempt == 2:
                    raise
                time.sleep(2.0 * (attempt + 1))
        self._end("submitted" if ok else "failed")
        return self.receipt

    def split(self, task_id: str, fencing_token: int, children: Any) -> list[str]:
        # The lease ends only when the split succeeds; a failed split is still the worker's to fail.
        ids: list[str] = self._inner.split(task_id, fencing_token, children)
        self._end("split")
        return ids

    def park(
        self, task_id: str, fencing_token: int, *, reason: str, resume_within: float | None = None
    ) -> Any:
        view = self._inner.park(task_id, fencing_token, reason=reason, resume_within=resume_within)
        self._end("parked")
        return view


@dataclass
class WorkerConfig:
    role: str
    label: str
    tessera_url: str
    key: str = field(repr=False)
    key_id: str
    trace_path: str
    model_url: str = DEFAULT_URL
    model_id: str = DEFAULT_MODEL
    min_empty_seconds: float = 60.0
    status_heartbeat_seconds: float = 600.0
    # A dedicated worker is run by ta-amps on its own machine; it gives volunteers first pick.
    dedicated: bool = False
    display_name: str = ""
    our_key_ids: tuple[str, ...] = ()

    @property
    def display(self) -> str:
        return self.display_name or self.label

    @classmethod
    def from_env(cls, role: str, label: str | None = None) -> WorkerConfig:
        if role not in ROLES:
            raise ValueError(f"role must be one of {', '.join(ROLES)}")
        url, key, key_id = (
            os.environ.get("TESSERA_URL", ""),
            os.environ.get("TESSERA_KEY", ""),
            os.environ.get("ERANOS_KEY_ID", ""),
        )
        missing = [
            n
            for n, v in (("TESSERA_URL", url), ("TESSERA_KEY", key), ("ERANOS_KEY_ID", key_id))
            if not v
        ]
        if missing:
            raise RuntimeError(f"eranos work needs {', '.join(missing)} in its environment file")
        return cls(
            role=role,
            label=label
            or os.environ.get("ERANOS_WORKER_LABEL")
            or f"eranos-{role}-{socket.gethostname()[:12]}",
            tessera_url=url,
            key=key,
            key_id=key_id,
            trace_path=os.environ.get("ERANOS_TRACE") or f"traces/worker-{role}.jsonl",
            model_url=os.environ.get("ERANOS_MODEL_URL") or DEFAULT_URL,
            model_id=os.environ.get("ERANOS_MODEL") or DEFAULT_MODEL,
            min_empty_seconds=max(60.0, float(os.environ.get("ERANOS_MIN_EMPTY_SECONDS") or 60)),
            dedicated=os.environ.get("ERANOS_DEDICATED", "") == "1",
            display_name=os.environ.get("ERANOS_WORKER_DISPLAY", ""),
            our_key_ids=tuple(
                k for k in os.environ.get("ERANOS_DEDICATED_KEY_IDS", "").split(",") if k
            ),
        )


class Heartbeat(threading.Thread):
    """Keeps one lease alive until the gate ends it; a lost lease is recorded, never ignored."""

    def __init__(self, worker: Worker, gate: LeaseGate, part: Any) -> None:
        super().__init__(daemon=True, name=f"heartbeat-{gate.lease.task_id}")
        self.worker, self.gate, self.part = worker, gate, part
        self.lost: BaseException | None = None
        self.beats = 0

    def run(self) -> None:
        lease = self.gate.lease
        interval = max(2.0, float(lease.heartbeat_seconds) * 0.5)
        last_fact = 0.0
        while not self.gate.ended_event.wait(interval):
            try:
                self.worker.heartbeat_backend.heartbeat(lease.task_id, lease.fencing_token)
            except (StaleLease, NotFound, InvalidState) as exc:
                self.lost = exc
                self.worker.trace.write(
                    "lease_lost",
                    level="error",
                    task_id=lease.task_id,
                    queue=lease.queue,
                    lease_id=lease.fencing_token,
                    error=str(exc)[:300],
                )
                return
            except (TesseraError, httpx.HTTPError) as exc:
                self.worker.trace.write(
                    "heartbeat_failed",
                    level="warning",
                    task_id=lease.task_id,
                    error=type(exc).__name__,
                )
                continue
            self.beats += 1
            self.worker.trace.write(
                "heartbeat",
                task_id=lease.task_id,
                queue=lease.queue,
                lease_id=lease.fencing_token,
                beats=self.beats,
            )
            now = time.time()
            request_id = self.worker.request_of(lease)
            if request_id and now - last_fact >= self.worker.config.status_heartbeat_seconds:
                last_fact = now
                with contextlib.suppress(TesseraError):
                    record_events(
                        self.worker.heartbeat_backend,
                        request_id,
                        [
                            fact(
                                "heartbeat",
                                part=self.part,
                                ref=f"{lease.task_id} heartbeat {self.beats}",
                                **self.worker.who(),
                            )
                        ],
                    )


class Worker:
    """One role's loop. `backend` and `heartbeat_backend` are separate clients with the same key."""

    def __init__(
        self,
        config: WorkerConfig,
        *,
        backend: Any = None,
        heartbeat_backend: Any = None,
        model: Any = None,
        fetcher: Callable[[str], Fetched] | None = None,
        handler: Any = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.queue, self.kinds = ROLES[config.role]
        self.trace = TraceWriter(config.trace_path)
        client = backend or _client(config)
        self.client = client
        self.backend = (
            TracedBackend(client, backend="tessera", trace_path=config.trace_path)
            if backend is None
            else backend
        )
        self.heartbeat_backend = heartbeat_backend or _client(config)
        self.model = model
        self.fetcher = fetcher
        self.handler = handler if handler is not None else process_part.load_handler()
        self.pacer = Pacer(config.min_empty_seconds)
        self.clock, self.sleep = clock, sleep
        self.stop = threading.Event()
        self.exit_code = 0
        self._noun: dict[str, Any] | None = None
        self._noun_at = 0.0
        self.stats = {"claims": 0, "empty": 0, "refused": 0, "worked": 0, "failed": 0, "lost": 0}

    def who(self) -> dict[str, Any]:
        """How this worker appears on a request's record: a dedicated worker run by ta-amps, or a
        volunteer's agent; the model each declares is in the facts that name the work."""
        if self.config.dedicated:
            return {"worker": self.config.display, "worker_kind": "dedicated", "run_by": "ta-amps"}
        return {"worker": self.config.display, "worker_kind": "volunteer"}

    def rules(self) -> dict[str, Any]:
        """The worker noun, read again at most every five minutes (claim timing comes from it)."""
        now = self.clock()
        if self._noun is None or now - self._noun_at > 300:
            try:
                self._noun = dict(self.backend.get_record("eranos.instructions", "worker").value)
                self._noun_at = now
            except Exception:
                self._noun = self._noun or {}
        return self._noun

    def grace_wait(self, kinds: list[str]) -> float | None:
        """Volunteers first: seconds until the oldest ready verb of these kinds has waited the grace
        period since it was queued (0 means claim now), or None when none is ready."""
        dedicated = self.rules().get("dedicated") or {}
        grace = float(dedicated.get("grace_seconds", 90))
        if grace <= 0 or self.queue not in (dedicated.get("queues") or ("eq01", "eq02", "eq03")):
            return 0.0
        verbs = [v for v in self.client.ready_verbs(self.queue) if v.get("kind") in kinds]
        if not verbs:
            return None
        now = time.time()
        queued = min(
            max(
                float(v.get("updated_at") or v.get("created_at") or now),
                float(v.get("not_before") or 0),
            )
            for v in verbs
        )
        return max(0.0, queued + grace - now)

    # model and sources -----------------------------------------------------------------------
    def _model(self) -> Any:
        if self.model is None:
            self.model = OllamaModel(self.config.model_url, self.config.model_id)
        return self.model

    def _fetcher(self, rules: dict[str, Any]) -> Callable[[str], Fetched]:
        """The injected fetcher (tests) or one with the worker noun's own limits."""
        if self.fetcher is not None:
            return self.fetcher
        policy = policy_from_rules(rules)
        return lambda url: fetch(url, policy)

    def claim_kinds(self) -> list[str]:
        """The kinds this worker can do now: research only while its model answers, and process
        verbs only with a real process handler (the stub never claims them)."""
        kinds = list(self.kinds)
        if process_part.is_stub(self.handler):
            kinds = [
                k for k in kinds if k not in (process_part.BUILD_KIND, process_part.REVIEW_KIND)
            ]
        if "research" in kinds:
            try:
                model = self._model()
                if hasattr(model, "healthy"):
                    model.healthy()
                model.describe()
            except ModelUnavailable as exc:
                self.trace.write("model_unavailable", level="warning", error=str(exc)[:200])
                kinds.remove("research")
        return kinds

    def declared_model(self, kind: str) -> str:
        if kind == "research":
            try:
                return f"{self._model().describe()['id']} (local, $0)"
            except ModelUnavailable:
                return "local model unavailable"
        if kind == process_part.BUILD_KIND:
            return f"process handler: {getattr(self.handler, 'name', 'installed')}"
        return DECLARED.get(kind, "deterministic (no model)")

    @staticmethod
    def request_of(lease: Lease) -> str | None:
        if lease.kind == "request":
            return str(lease.task_id)
        brief = lease.brief if isinstance(lease.brief, dict) else {}
        return str(brief["request_id"]) if brief.get("request_id") else None

    # one claim -------------------------------------------------------------------------------
    def claim(self, kinds: list[str]) -> tuple[Lease | None, float]:
        if hasattr(self.client, "claim_with_hint"):
            lease, retry_after, _ = self.client.claim_with_hint(
                self.queue, self.config.label, kinds=kinds
            )
            if lease is not None:
                self.trace.write(
                    "claimed",
                    task_id=lease.task_id,
                    queue=self.queue,
                    worker=self.config.label,
                    lease_id=lease.fencing_token,
                    kind=lease.kind,
                )
            return lease, retry_after
        return self.backend.claim(self.queue, self.config.label, kinds=kinds), 5.0

    def _allowance_spent(self, exc: BaseException, task_id: str | None = None) -> None:
        """The hosted storage allowance is spent: stop claiming, record it, exit with its own code."""
        self.stop.set()
        self.exit_code = EXIT_STORAGE_ALLOWANCE
        self.trace.write(
            "storage_allowance_exhausted",
            level="error",
            task_id=task_id,
            queue=self.queue,
            retry_after=getattr(exc, "retry_after", None),
            reset_at=getattr(exc, "reset_at", None),
            error=str(exc)[:300],
        )

    def run_once(self) -> str:
        """Claim at most one verb and finish it: 'worked', 'empty', 'refused', 'paced', 'error' or 'stopped'."""
        now = self.clock()
        if self.stop.is_set():
            return "stopped"
        if not self.pacer.ready(self.queue, now):
            return "paced"
        kinds = self.claim_kinds()
        if not kinds:
            self.pacer.empty(self.queue, now, 0.0)
            return "empty"
        if self.config.dedicated and hasattr(self.client, "ready_verbs"):
            try:
                wait = self.grace_wait(kinds)
            except StorageQuotaExhausted as exc:
                self._allowance_spent(exc)
                return "stopped"
            except (TesseraError, httpx.HTTPError) as exc:
                until = self.pacer.refused(self.queue, now, 60.0)
                self.trace.write(
                    "queue_unreadable",
                    level="error",
                    queue=self.queue,
                    error=type(exc).__name__,
                    retry_at=round(until, 1),
                )
                return "error"
            if wait is None:
                until = self.pacer.empty(self.queue, now, 0.0)
                self.trace.write("nothing_ready", queue=self.queue, next_check_at=round(until, 1))
                return "empty"
            if wait > 0:
                until = self.pacer.refused(self.queue, now, wait)
                self.trace.write(
                    "volunteers_first",
                    queue=self.queue,
                    wait_seconds=round(wait, 1),
                    next_claim_at=round(until, 1),
                )
                return "grace"
        self.stats["claims"] += 1
        try:
            lease, retry_after = self.claim(kinds)
        except StorageQuotaExhausted as exc:
            self._allowance_spent(exc)
            return "stopped"
        except (RateLimited, Unavailable) as exc:
            wait = float(getattr(exc, "retry_after", 60.0) or 60.0)
            until = self.pacer.refused(self.queue, now, wait)
            self.stats["refused"] += 1
            self.trace.write(
                "claim_refused",
                level="warning",
                queue=self.queue,
                code=exc.code,
                retry_at=round(until, 1),
            )
            return "refused"
        except (TesseraError, httpx.HTTPError) as exc:
            until = self.pacer.refused(self.queue, now, 60.0)
            self.trace.write(
                "claim_error",
                level="error",
                queue=self.queue,
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
                retry_at=round(until, 1),
            )
            return "error"
        if lease is None:
            until = self.pacer.empty(self.queue, now, retry_after)
            self.stats["empty"] += 1
            self.trace.write(
                "claim_empty",
                queue=self.queue,
                retry_after=retry_after,
                next_claim_at=round(until, 1),
            )
            return "empty"
        self.pacer.worked(self.queue, now)
        self.handle(lease)
        return "stopped" if self.stop.is_set() else "worked"

    def run_forever(self, *, max_leases: int | None = None) -> dict[str, int]:
        for name in ("SIGTERM", "SIGINT"):
            if threading.current_thread() is threading.main_thread():
                signal.signal(getattr(signal, name), lambda *_: self.stop.set())
        self.trace.write(
            "worker_started",
            role=self.config.role,
            worker=self.config.label,
            queue=self.queue,
            version=__version__,
        )
        while not self.stop.is_set():
            try:
                outcome = self.run_once()
            except StorageQuotaExhausted as exc:
                self._allowance_spent(exc)
                break
            except Exception as exc:
                until = self.pacer.refused(self.queue, self.clock(), 60.0)
                self.trace.write(
                    "loop_error",
                    level="error",
                    queue=self.queue,
                    error=f"{type(exc).__name__}: {str(exc)[:300]}",
                    retry_at=round(until, 1),
                )
                outcome = "error"
            if (
                outcome == "worked"
                and max_leases is not None
                and self.stats["worked"] >= max_leases
            ):
                break
            if outcome not in ("worked", "stopped"):
                self.stop.wait(min(60.0, max(1.0, self.pacer.wait(self.clock()))))
        self.trace.write(
            "worker_stopped",
            role=self.config.role,
            worker=self.config.label,
            exit_code=self.exit_code,
            stats=dict(self.stats),
        )
        return self.stats

    # the work ----------------------------------------------------------------------------------
    def _report_factory(
        self, lease: Lease, meter: UsageMeter, notes: dict[str, Any]
    ) -> Callable[[Any, bool, str | None], dict[str, Any]]:
        def report(output: Any, ok: bool, error: str | None) -> dict[str, Any]:
            status = output.get("status") if isinstance(output, dict) else None
            solution = (
                f"{lease.kind} {'done' if ok else 'failed'}"
                + (f": {status}" if status else "")
                + (f"; {error}" if error else "")
            )
            out: dict[str, Any] = {
                "version": 1,
                "harness": {
                    "name": "eranos-worker",
                    "version": __version__,
                    "role": self.config.role,
                    "worker": self.config.label,
                    "kind": lease.kind,
                    "declared_model": self.declared_model(lease.kind),
                    "cost_usd": 0.0,
                    "payer": "the volunteer running this worker; $0 in API charges",
                },
                "model": meter.model_report(),
                "summaries": {
                    "problem": str((lease.brief or {}).get("title") or lease.kind)[:4000],
                    "solution": solution[:4000],
                },
                "usage": meter.usage(),
            }
            refs = [r for r in notes.get("artifact_refs") or [] if isinstance(r, dict)][:32]
            if refs:
                out["artifact_refs"] = refs
            return out

        return report

    def _facts(self, backend: Any, request_id: str | None, events: list[dict[str, Any]]) -> None:
        """Write status facts; a fact that cannot be written is logged and never fails the verb."""
        if not request_id:
            return
        try:
            record_events(backend, request_id, events)
        except StorageQuotaExhausted:
            raise
        except Exception as exc:
            self.trace.write(
                "fact_not_recorded",
                level="error",
                request_id=request_id,
                facts=[e.get("type") for e in events],
                error=type(exc).__name__,
            )

    def handle(self, lease: Lease) -> None:
        meter, notes = UsageMeter(), cast(dict[str, Any], {})
        gate = LeaseGate(self.backend, lease, self._report_factory(lease, meter, notes))
        part = (lease.brief or {}).get("part") if lease.kind != "request" else None
        request_id = self.request_of(lease)
        beat = Heartbeat(self, gate, part)
        beat.start()
        try:
            if self.config.role == "planner":
                outcome = Planner(
                    gate,
                    lease,
                    worker=self.config.display,
                    nouns=load_nouns(gate),
                    handler=self.handler,
                ).run()
            elif self.config.role == "builder":
                outcome = self.build(gate, lease, meter, notes, part, request_id)
            else:
                outcome = self.review(gate, lease, part, request_id)
            self.stats["worked"] += 1
            self.trace.write(
                "lease_done",
                task_id=lease.task_id,
                queue=lease.queue,
                kind=lease.kind,
                ended=gate.ended,
                status=(outcome or {}).get("status"),
            )
        except StorageQuotaExhausted as exc:
            self.trace.write(
                "lease_failed",
                level="error",
                task_id=lease.task_id,
                queue=lease.queue,
                kind=lease.kind,
                error="the hosted storage allowance is spent; the lease will lapse and be retried",
                receipt=getattr(gate.receipt, "receipt_hash", None),
            )
            self.stats["failed"] += 1
            self._allowance_spent(exc, lease.task_id)
        except Exception as exc:
            self.fail(gate, lease, exc, part, request_id, beat)
        finally:
            gate.ended_event.set()
            beat.join(timeout=10)

    def fail(
        self,
        gate: LeaseGate,
        lease: Lease,
        exc: BaseException,
        part: Any,
        request_id: str | None,
        beat: Heartbeat,
    ) -> None:
        """Record a failure: submit ok=false while the lease is held, log it, write a fact. Never raises."""
        self.stats["failed"] += 1
        message = f"{type(exc).__name__}: {str(exc)[:900]}"
        receipt = (
            gate.receipt.receipt_hash
            if gate.receipt is not None and gate.ended == "failed"
            else None
        )
        if gate.ended == "lost" or beat.lost is not None:
            message += "; the lease was lost before the result could be submitted"
        if gate.ended is None:
            try:  # a separate key: an earlier submit under the lease's key may have landed unseen
                receipt = gate.submit(
                    lease.task_id,
                    lease.fencing_token,
                    {"node": lease.kind, "status": "failed", "error": message},
                    idempotency_key=f"{lease.task_id}:{lease.fencing_token}:failed",
                    ok=False,
                    error=message,
                ).receipt_hash
            except StorageQuotaExhausted as spent:
                self._allowance_spent(spent, lease.task_id)
            except Exception as lost:
                message += f"; the failure could not be submitted ({type(lost).__name__})"
        if gate.ended == "lost" or beat.lost is not None:
            self.stats["lost"] += 1
        try:
            self.trace.write(
                "lease_failed",
                level="error",
                task_id=lease.task_id,
                queue=lease.queue,
                kind=lease.kind,
                error=message[:600],
                receipt=receipt,
                lease_lost=beat.lost is not None or gate.ended == "lost",
            )
            if request_id and not self.stop.is_set():
                kind = "work_released" if receipt is None else "work_failed"
                record_events(
                    self.backend,
                    request_id,
                    [
                        fact(
                            kind,
                            part=part,
                            receipt=receipt,
                            ref=None if receipt else f"{lease.task_id} attempt {lease.attempt}",
                            **self.who(),
                            reason=message[:500],
                            summary={"role": self.config.role, "kind": lease.kind},
                        )
                    ],
                )
        except StorageQuotaExhausted as spent:
            self._allowance_spent(spent, lease.task_id)
        except Exception as again:  # fail() never raises
            with contextlib.suppress(Exception):  # even an unwritable run log must not raise here
                self.trace.write(
                    "fact_not_recorded",
                    level="error",
                    task_id=lease.task_id,
                    error=type(again).__name__,
                )

    def _claimed(self, kind: str, lease: Lease, part: Any, request_id: str | None) -> None:
        self._facts(
            self.backend,
            request_id,
            [
                fact(
                    kind,
                    part=part,
                    at=lease.claimed_at,
                    receipt=lease.claim_receipt,
                    **self.who(),
                    model=self.declared_model(lease.kind),
                    lease_ends=lease.expires_at,
                    queue=queue_snapshot(self.backend, [self.config.label]),
                )
            ],
        )

    def build(
        self,
        gate: LeaseGate,
        lease: Lease,
        meter: UsageMeter,
        notes: dict[str, Any],
        part: Any,
        request_id: str | None,
    ) -> dict[str, Any]:
        self._claimed("work_claimed", lease, part, request_id)
        nouns = load_nouns(gate)
        if lease.kind == "research":
            done = research.do_research(
                gate,
                lease,
                fetcher=self._fetcher(nouns["worker"]),
                model=self._model(),
                meter=meter,
                worker_rules=nouns["worker"],
            )
        else:
            done = process_part.do_process(gate, lease, handler=self.handler)
        notes["artifact_refs"] = done.get("artifact_refs") or []
        idem = f"{lease.task_id}:{lease.fencing_token}"
        if not done["self_test"]["passed"]:
            error = "self-test failed: " + "; ".join(done["self_test"]["issues"])[:900]
            receipt = gate.submit(
                lease.task_id,
                lease.fencing_token,
                {**done["output"], "status": "self_test_failed", "self_test": done["self_test"]},
                idempotency_key=idem,
                ok=False,
                error=error,
            )
            self.stats["failed"] += 1
            self.trace.write(
                "lease_failed",
                level="error",
                task_id=lease.task_id,
                queue=lease.queue,
                kind=lease.kind,
                error=error[:600],
                receipt=receipt.receipt_hash,
            )
            self._facts(
                gate,
                request_id,
                [
                    fact(
                        "work_failed",
                        part=part,
                        receipt=receipt.receipt_hash,
                        **self.who(),
                        reason=error[:500],
                        summary={**(done.get("summary") or {}), "tokens": meter.total_tokens},
                    )
                ],
            )
            return {"status": "self_test_failed"}
        receipt = gate.submit(
            lease.task_id, lease.fencing_token, done["output"], idempotency_key=idem, ok=True
        )
        self._facts(
            gate,
            request_id,
            [
                fact(
                    "work_submitted",
                    part=part,
                    receipt=receipt.receipt_hash,
                    **self.who(),
                    summary={**(done.get("summary") or {}), "tokens": meter.total_tokens},
                    queue=queue_snapshot(gate),
                )
            ],
        )
        return {"status": "submitted", "receipt": receipt.receipt_hash}

    def review(
        self, gate: LeaseGate, lease: Lease, part: Any, request_id: str | None
    ) -> dict[str, Any]:
        self._claimed("check_claimed", lease, part, request_id)
        nouns = load_nouns(gate)
        if lease.kind == "report_review":
            out = research.review_research(
                gate,
                lease,
                worker=self.config.label,
                key_id=self.config.key_id,
                fetcher=self._fetcher(nouns["worker"]),
                worker_rules=nouns["worker"],
                guardrails=nouns.get("public-research") or {},
            )
        else:
            out = process_part.review_package(
                gate, lease, handler=self.handler, key_id=self.config.key_id
            )
        self._facts(gate, request_id, self.review_facts(lease, out, part))
        return out

    def review_facts(self, lease: Lease, out: dict[str, Any], part: Any) -> list[dict[str, Any]]:
        who, status = self.config.display, out.get("status")
        receipt = out.get("receipt") or out.get("review_receipt")
        tasks = [d.task_id for d in lease.dependencies] + [lease.task_id]
        kind = (
            {"worker_kind": "dedicated", "run_by": "ta-amps"}
            if self.config.dedicated
            else {"worker_kind": "volunteer"}
        )
        builder = lease.dependencies[0].completed_by_key if lease.dependencies else None
        work_by = (
            "a dedicated worker (run by ta-amps)"
            if builder and builder in self.config.our_key_ids
            else "a volunteer's agent"
        )
        if status == "delivered":
            ref = f"eranos.solutions/{out['report_id']}"
            return [
                fact(
                    "check_approved",
                    part=part,
                    receipt=receipt,
                    worker=who,
                    summary={"rechecked": len(out.get("rechecked") or [])},
                ),
                fact("delivered", part=part, receipt=receipt, ref=ref, result_id=out["report_id"]),
                fact(
                    "added",
                    part=part,
                    receipt=receipt,
                    ref=ref,
                    result_id=out["report_id"],
                    summary={
                        "nouns": [
                            f"{ref}@{out.get('solution_version')}",
                            f"eranos.plans/{lease.brief.get('request_id')}",
                        ],
                        "tasks": tasks,
                    },
                ),
            ]
        if status == "published":
            key = out.get("kit_id") or (out.get("published") or [{}])[0].get("key")
            ref = f"eranos.processes/{key}"
            return [
                fact(
                    "check_approved",
                    part=part,
                    receipt=receipt,
                    worker=who,
                    **kind,
                    summary={"work_by": work_by},
                ),
                fact("published", part=part, receipt=receipt, ref=ref, result_id=key),
                fact(
                    "added",
                    part=part,
                    receipt=receipt,
                    ref=ref,
                    result_id=key,
                    summary={"nouns": [ref], "tasks": tasks},
                ),
            ]
        return [
            fact(
                "check_sent_back",
                part=part,
                receipt=receipt,
                worker=who,
                reason=str(out.get("reason") or status),
                findings=[str(f) for f in out.get("findings") or []][:20],
            )
        ]


def _client(config: WorkerConfig) -> WorkerClient:
    """A Tessera client for this worker's key; an explicit transport means no proxy from the environment."""
    return WorkerClient(
        config.tessera_url,
        key=config.key,
        surface_id="eranos",
        namespace="main",
        max_retries=0,
        transport=httpx.HTTPTransport(retries=0),
    )


def run_cli(
    role: str, *, once: bool = False, max_leases: int | None = None, label: str | None = None
) -> tuple[int, dict[str, Any]]:
    config = WorkerConfig.from_env(role, label)
    Path(config.trace_path).parent.mkdir(parents=True, exist_ok=True)
    worker = Worker(config)
    if once:
        outcome = worker.run_once()
        return worker.exit_code, {"outcome": outcome, **worker.stats}
    stats = dict(worker.run_forever(max_leases=max_leases))
    return worker.exit_code, stats
