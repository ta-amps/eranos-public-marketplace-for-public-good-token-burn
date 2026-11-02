"""Volunteer workers on Eranos's queues: `eranos work --role planner|builder|reviewer`.

One loop per role, each with its own scoped key:
- planner claims request verbs on eq01: checks, reuses, splits, closes, and parks recurring requests;
- builder claims work verbs on eq02: research (a Muse model through the Meta API, standard tier,
  permitted sources), kit builds, process packages (through the B4 handler interface);
- reviewer claims review verbs on eq03 with a different key: re-checks and delivers or publishes.

Every lease follows the same cycle: claim (an empty claim waits at least a minute, or longer when the
server's Retry-After says so), heartbeat in the background, do the work, submit once with an
idempotency key and an execution report (harness, model, adapter, tokens, cost), and write each state
change into the request's public record. Every failure is submitted with ok=false when the lease is
still held, and every failure (including a lost lease) is written to the run log and the request's
record. The key lives only in the environment; it is never printed or logged.

`--volunteer` runs the same code as a volunteer: its own scoped key (research and report reviews
only), no grace delay, labelled "a volunteer's AI", using the same Meta client and caps. It runs only
when someone starts it for a take.
"""

from __future__ import annotations

import contextlib
import json
import os
import random
import re
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
    TaskSpec,
    TesseraError,
    Unavailable,
)
from tessera.client import Client, _retry_after
from tessera.errors import BY_CODE, InvalidRequest

from eranos import __version__, config
from eranos.adapter.traced import TracedBackend
from eranos.donor_worker import synthesize_review_decision
from eranos.log import TraceWriter
from eranos.model_client import (
    LEDGER_ENV,
    MIN_RATES_USD_PER_MILLION,
    BudgetExhausted,
    ContributorTierRefused,
    Ledger,
    MetaModel,
    ModelUnavailable,
    UsageMeter,
    refuse_contributor,
)
from eranos.pacing import CountingTransport, RequestCounter, hourly_summary, poke, wake_mark
from eranos.pipeline import load_example_bundles, research
from eranos.pipeline import process as process_part
from eranos.pipeline import tuning as tuning_mod
from eranos.pipeline.plain_words import forbidden, plain
from eranos.pipeline.planner import Planner, load_nouns
from eranos.pipeline.reuse_check import (
    REUSE_KIND,
    ReopenRefused,
    judge_user,
    read_judgment,
    reopen_target,
    review_reuse,
)
from eranos.pipeline.run import SelfReviewRefused, run_draft_step, run_review_step, run_spec_step
from eranos.pipeline.status_events import fact, queue_snapshot, record_events
from eranos.schemas import KitDraft, VerificationReport
from eranos.sources import Fetched, fetch, policy_from_rules

# Kit builds and kit reviews are not claimed here: kits carry a fixture mark these workers must
# not publish. Work on a nonprofit's own files goes through process packages instead.
ROLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "planner": ("eq01", ("request", "spec", "tune")),
    "builder": ("eq02", ("research", process_part.BUILD_KIND, "draft")),
    "reviewer": ("eq03", ("report_review", process_part.REVIEW_KIND, "review", REUSE_KIND)),
}
KIT_KINDS = frozenset({"spec", "draft", "review"})
# The volunteer mode does research and checks research, nothing else (its key says the same).
VOLUNTEER_KINDS = frozenset({"research", "report_review"})
# The steps that call a model, by verb kind (the tuning noun's steps).
MODEL_STEPS = {"research": "make", "report_review": "check"}
# Verbs that need a model to answer, so none is claimed while it cannot (the reuse check runs the
# worker noun's fixed model, not a tuned variant).
MODEL_KINDS = frozenset({*MODEL_STEPS, REUSE_KIND})
MODEL_CATALOG = ("eranos.instructions", "models.meta")
LOCAL_CATALOG = Path(__file__).resolve().parents[1] / "instructions" / "models.meta.json"
DECLARED = {
    "request": "deterministic planner (no model)",
    "tune": "the hourly tuner: deterministic shares from recorded outcomes",
    "report_review": "deterministic re-fetch and quote check (no model)",
    "spec": "deterministic scope check (no model)",
    "draft": "example kit in plain words (no model)",
    "review": "deterministic kit checks (no model)",
    process_part.REVIEW_KIND: "process handler review, in a clean process",
    REUSE_KIND: "a Muse model checks that a library answer fits the request",
}
EXIT_STORAGE_ALLOWANCE = (
    75  # EX_TEMPFAIL: the hosted storage allowance is spent; the units do not restart
)


# The plain log shows a token only if it is a plain word, a short number or version, or one of the
# log's own separators; anything else becomes an ellipsis (an allowlist, review B1 of 6e86d28).
_OK = re.compile(
    r"""
      \(?[A-Za-z][A-Za-z'-]{0,23}[.,;:!?)]*          # a word, maybe in a bracket, maybe with closing punctuation
    | \$?\d{1,4}(?:\.\d{1,2})?[%A-Za-z]?[.,;:!?)]*   # a short number, a version such as 1.3, a price, 30B
    | [·…-]                                           # the separators the log itself writes
    """,
    re.X,
)
STEP_WORDS = {
    "research": "a research Task",
    "report_review": "a check Task",
    "request": "a request to plan",
    "process": "a build Task",
    "process_review": "a check of a build",
    "spec": "a kit Task",
    "draft": "a kit Task",
    "review": "a kit check",
    "tune": "the hourly tuning Task",
    REUSE_KIND: "a check of a library answer",
}


def plain_words_only(text: str) -> str:
    """A log line with anything that is not a plain word or a short number taken out."""
    return " ".join(t if _OK.fullmatch(t) else "…" for t in text.split())


class NotInPlan(RuntimeError):
    """A Task that names a request whose plan does not list it: never worked (anti-forgery)."""


class ExampleOnlyRefused(InvalidRequest):
    """Tessera refused personal or payment data in a write. Its code is `example_only`; older
    Tessera Workers send the former code for the same refusal, and both are understood here."""

    code = "example_only"


EXAMPLE_ONLY_CODES = ("example_only", "synthetic_only")  # the current code, then the former one
for _code in EXAMPLE_ONLY_CODES:
    BY_CODE[_code] = ExampleOnlyRefused


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
    """When each queue may be claimed again. An empty claim waits at least a minute, then twice as
    long each time the queue is still empty, up to `max_idle_seconds`, or the server's Retry-After
    when that is longer; any work resets the wait."""

    min_empty_seconds: float = 60.0
    max_idle_seconds: float = 300.0
    next_at: dict[str, float] = field(default_factory=dict)
    idle: dict[str, int] = field(default_factory=dict)
    jitter: float = 0.0  # up to this share longer, so restarted workers do not poll in step
    rng: random.Random = field(default_factory=random.Random, repr=False)

    def ready(self, queue: str, now: float) -> bool:
        return now >= self.next_at.get(queue, 0.0)

    def empty(self, queue: str, now: float, retry_after: float) -> float:
        n = self.idle.get(queue, 0) + 1
        self.idle[queue] = n
        backoff = min(self.max_idle_seconds, self.min_empty_seconds * 2 ** min(n - 1, 16))
        if self.jitter > 0:
            backoff *= 1.0 + min(self.jitter, 1.0) * self.rng.random()
        self.next_at[queue] = now + max(backoff, self.min_empty_seconds, retry_after)
        return self.next_at[queue]

    def refused(self, queue: str, now: float, retry_after: float) -> float:
        self.next_at[queue] = now + max(1.0, retry_after)
        return self.next_at[queue]

    def worked(self, queue: str, now: float) -> None:
        self.next_at[queue] = now
        self.idle[queue] = 0

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
    # A volunteer donates spare Meta credits through the same client: no grace delay, its own key.
    volunteer: bool = False
    # One readable line per step, with no ids, keys or hashes (ERANOS_PLAIN_LOG; "" for none).
    plain_log: str = ""
    min_empty_seconds: float = 60.0
    status_heartbeat_seconds: float = 600.0
    # A dedicated worker is run by ta-amps on its own machine; it gives volunteers first pick.
    dedicated: bool = False
    display_name: str = ""
    our_key_ids: tuple[str, ...] = ()
    # Set to "ta-amps" for a program ta-amps runs itself in the volunteer mode (the on-camera take):
    # its claims are ours and never shown as an outside volunteer's (ERANOS_RUN_BY).
    run_by: str = ""

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
        volunteer = os.environ.get("ERANOS_VOLUNTEER", "") == "1"
        if volunteer and role not in ("builder", "reviewer"):
            raise ValueError("a volunteer does research (builder) or checks it (reviewer) only")
        return cls(
            role=role,
            label=label
            or os.environ.get("ERANOS_WORKER_LABEL")
            or f"eranos-{role}-{socket.gethostname()[:12]}",
            tessera_url=url,
            key=key,
            key_id=key_id,
            trace_path=os.environ.get("ERANOS_TRACE") or f"traces/worker-{role}.jsonl",
            volunteer=volunteer,
            plain_log=os.environ.get("ERANOS_PLAIN_LOG", ""),
            min_empty_seconds=max(60.0, float(os.environ.get("ERANOS_MIN_EMPTY_SECONDS") or 60)),
            dedicated=os.environ.get("ERANOS_DEDICATED", "") == "1" and not volunteer,
            display_name=os.environ.get("ERANOS_WORKER_DISPLAY", ""),
            run_by=os.environ.get("ERANOS_RUN_BY", "").strip(),
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
        # About once a minute: Tessera's lease outlives two missed beats (heartbeat x miss_limit), and
        # every beat costs storage rows on the free plan, so beat no more often than that.
        interval = max(2.0, float(lease.heartbeat_seconds) * 0.92)
        last_fact = 0.0
        request_id = self.worker.request_of(lease)  # once per lease, not one read per beat
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
        # Every request this worker sends is counted (the hosted sites share a daily request cap).
        self.requests = RequestCounter()
        client = backend or _client(config, self.requests)
        self.client = client
        self.backend = (
            TracedBackend(client, backend="tessera", trace_path=config.trace_path)
            if backend is None
            else backend
        )
        self.heartbeat_backend = heartbeat_backend or _client(config, self.requests)
        self.model = model
        self.fetcher = fetcher
        self.handler = handler if handler is not None else process_part.load_handler()
        # A reviewer that runs a process handler must name the builder keys it trusts; it refuses to
        # start without them, so a package written by any other key can never be approved.
        self.process_builder_keys = process_part.trusted_builder_keys()
        if (
            config.role == "reviewer"
            and not config.volunteer  # a volunteer checks research only, never a process package
            and not process_part.is_stub(self.handler)
            and not self.process_builder_keys
        ):
            raise process_part.BuilderKeysMissing(process_part.BUILDER_KEYS_REQUIRED)
        self.pacer = Pacer(config.min_empty_seconds)
        self.clock, self.sleep = clock, sleep
        self.stop = threading.Event()
        self.exit_code = 0
        self._noun: dict[str, Any] | None = None
        self._catalog: dict[str, dict[str, Any]] | None = None
        self._catalog_at = 0.0
        self._model_settings: dict[str, Any] | None = None
        self._metas: dict[str, tuple[Any, Any]] = {}
        self._woke_at = wake_mark(self.queue)  # a poke from before this start is not news
        self._tuning: tuple[dict[str, Any], int] | None = None
        self._tuning_at = 0.0
        self._pick: dict[str, Any] | None = None  # the running lease's pick, for its failure fact
        self._tune_check_at = 0.0
        self._kit_bundles: dict[str, dict[str, Any]] | None = None
        self._noun_at = 0.0
        self.stats = {"claims": 0, "empty": 0, "refused": 0, "worked": 0, "failed": 0, "lost": 0}

    def who(self) -> dict[str, Any]:
        """How this worker appears on a request's record. Only an outside volunteer's run (the
        explicit volunteer mode, not run by ta-amps) is marked `volunteer`; a dedicated worker, the
        default mode and ta-amps's own volunteer-mode take are ours and marked `dedicated`, run by
        ta-amps, so our work never appears as an outside volunteer's. The model each declares is in
        the facts that name the work."""
        if self.config.volunteer and self.config.run_by != "ta-amps":
            return {"worker": "a volunteer's AI", "dedicated": False, "worker_kind": "volunteer"}
        if self.config.volunteer:
            label = self.config.display_name or "the on-camera worker (run by ta-amps)"
            return {
                "worker": label,
                "dedicated": True,
                "worker_kind": "dedicated",
                "run_by": "ta-amps",
            }
        return {
            "worker": self.config.display,
            "dedicated": True,
            "worker_kind": "dedicated",
            "run_by": "ta-amps",
        }

    def say(self, text: str) -> None:
        """One plain line for people watching: no ids, keys or hashes, never fatal."""
        if not self.config.plain_log:
            return
        line = f"{time.strftime('%H:%M:%S')}  {self.who()['worker']} · {plain_words_only(text)}\n"
        if line[10:] == getattr(self, "_last_said", None):
            return  # the same idle line again is not news
        self._last_said = line[10:]
        with contextlib.suppress(OSError):
            path = Path(self.config.plain_log)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write(line)

    def payer(self) -> str:
        """Who pays for this worker's model calls, as its execution reports say."""
        if self.config.volunteer:
            return "spare Meta API credit given by the volunteer who started this worker (standard tier)"
        return "the owner's Meta API credit (standard tier)"

    def refresh_seconds(self) -> float:
        """How long a read noun is used before it is read again (`claims.noun_refresh_seconds`,
        five minutes by default): each read is a request against the hosted sites' daily cap."""
        claims = (self._noun or {}).get("claims") or {}
        return max(60.0, float(claims.get("noun_refresh_seconds") or 300))

    def rules(self) -> dict[str, Any]:
        """The worker noun, read again at most every `refresh_seconds` (claim timing comes from it)."""
        now = self.clock()
        if self._noun is None or now - self._noun_at > self.refresh_seconds():
            try:
                self._noun = dict(self.backend.get_record("eranos.instructions", "worker").value)
                self._noun_at = now
            except Exception:
                self._noun = self._noun or {}
        return self._noun

    def grace_wait(self, kinds: list[str]) -> float | None:
        """Volunteers first: seconds until the oldest ready verb of these kinds has waited the grace
        period since it was queued (0 means claim now), or None when none is ready."""
        claims = self.rules().get("claims") or {}
        self.pacing(claims)
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

    def pacing(self, claims: dict[str, Any]) -> None:
        """Claim timing from the worker noun: the longest idle wait (per queue when it says so) and
        the jitter that keeps restarted workers from polling in step."""
        by_queue = claims.get("max_idle_seconds_by_queue") or {}
        idle = by_queue.get(self.queue, claims.get("max_idle_seconds", self.pacer.max_idle_seconds))
        self.pacer.max_idle_seconds = float(idle)
        self.pacer.jitter = float(claims.get("idle_jitter") or 0.0)

    # model and sources -----------------------------------------------------------------------
    def catalog(self) -> dict[str, dict[str, Any]]:
        """The model catalog noun (`models.meta`), as id -> {display, rates}: its `runtime` section
        names each id and gives its token rates. It is read again at most every five minutes; the
        repository's copy stands in until the Tessera record exists."""
        now = self.clock()
        if self._catalog is None or now - self._catalog_at > self.refresh_seconds():
            value: Any = None
            try:
                value = self.backend.get_record(*MODEL_CATALOG).value
            except Exception:
                value = None
            if not isinstance(value, dict) or not isinstance(value.get("runtime"), dict):
                try:
                    value = json.loads(LOCAL_CATALOG.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    value = {}
            runtime = value.get("runtime") if isinstance(value, dict) else None
            runtime = runtime if isinstance(runtime, dict) else {}
            names = runtime.get("display_by_id") or {}
            rates = runtime.get("rates_usd_per_million_tokens") or {}
            self._catalog = {
                str(model_id): {"display": str(name), "rates": dict(rates.get(model_id) or {})}
                for model_id, name in names.items()
                if isinstance(name, str) and name
            }
            self._catalog_at = now
        return self._catalog

    def model_display(self, model_id: str) -> str:
        """The display name the catalog gives this id, or the id itself when it holds none."""
        entry = self.catalog().get(model_id)
        if entry is None:
            self.trace.write("model_not_in_catalog", level="warning", model=model_id)
            return model_id
        return str(entry["display"])

    def model_id(self) -> str:
        """The id the worker noun names for this worker; the volunteer mode has its own."""
        settings = self.rules().get("model") or {}
        chosen = settings.get("volunteer_id") if self.config.volunteer else None
        return str(chosen or settings.get("id") or "")

    def _model(self) -> Any:
        """The worker noun's own model (its fallback id, or the volunteer's): used for health."""
        return self.meta(self.model_id())

    def meta(self, model_id: str) -> Any:
        """A Muse model through the Meta API, at the catalog's rates, under the owner's caps; one
        client per model id, rebuilt when the noun or the catalog changes. An injected model
        (tests) answers for every id."""
        if self.model is not None and self._model_settings is None:
            return self.model
        settings = dict(self.rules().get("model") or {})
        entry = self.catalog().get(model_id) or {}
        rates = dict(entry.get("rates") or {})
        wanted = {"settings": settings, "rates": rates}
        cached = self._metas.get(model_id)
        if cached is not None and cached[1] == wanted:
            return cached[0]
        if not model_id:
            raise ModelUnavailable("the worker noun names no model")
        try:
            refuse_contributor(model_id)
        except ContributorTierRefused as exc:
            raise ModelUnavailable(f"the worker noun's model is refused: {exc}") from exc
        if not {"input", "output"} <= set(rates):
            raise ModelUnavailable(
                f"models.meta gives no token rates for {model_id}; it is not called"
            )
        caps = settings.get("budget") or {}
        ledger = Ledger(
            os.environ.get(LEDGER_ENV)
            or str(Path.home() / ".local/state/eranos-worker/meta-spend.json"),
            daily_usd=float(caps.get("daily_usd", 5)),
            total_usd=float(caps.get("total_usd", 150)),
        )
        try:
            model = MetaModel(
                {
                    **settings,
                    "id": model_id,
                    "model_display": self.model_display(model_id),
                    "prices_usd_per_million": {k: rates[k] for k in ("input", "output")},
                },
                ledger=ledger,
                transport=CountingTransport(httpx.HTTPTransport(retries=0), self.requests, "meta"),
            )
        except (ContributorTierRefused, ValueError) as exc:
            raise ModelUnavailable(f"the worker noun's model is refused: {exc}") from exc
        if cached is not None and hasattr(cached[0], "close"):
            cached[0].close()
        self._metas[model_id] = (model, wanted)
        return model

    def usable(self, variant: dict[str, Any]) -> bool:
        """A variant may run only with a priced Muse model at the standard tier, and only with a
        persona that passes the gate again here, so a hand edit of the noun cannot bypass it."""
        model_id = str(variant.get("model") or "")
        if not model_id or "contributor" in model_id.lower():
            return False
        if model_id not in MIN_RATES_USD_PER_MILLION:
            return False
        persona = variant.get("persona")
        if persona is not None and tuning_mod.checked_persona(persona)[0] is None:
            self.trace.write("persona_refused", level="warning", variant=variant.get("id"))
            return False
        return {"input", "output"} <= set((self.catalog().get(model_id) or {}).get("rates") or {})

    def tuning(self, *, fresh: bool = False) -> tuple[dict[str, Any], int]:
        """The tuning noun and its Tessera version (0 when only the repository's copy exists),
        read again at most every five minutes."""
        now = self.clock()
        if fresh or self._tuning is None or now - self._tuning_at > 300:
            found: tuple[dict[str, Any], int] | None = None
            try:
                record = self.backend.get_record(tuning_mod.TUNING_STORE, tuning_mod.TUNING_KEY)
                if isinstance(record.value, dict):
                    found = (dict(record.value), int(record.version))
            except Exception:
                found = None
            if found is None:
                try:
                    found = (json.loads(tuning_mod.LOCAL_TUNING.read_text(encoding="utf-8")), 0)
                except (OSError, ValueError):
                    found = ({}, 0)
            self._tuning, self._tuning_at = found, now
        return self._tuning

    def pick_for(
        self, step: str, lease: Lease, *, exclude: tuple[str, ...] = ()
    ) -> dict[str, Any] | None:
        """This lease's variant for a step, drawn from the tuning noun's mix (reproducible from the
        task id and fencing token). The volunteer mode runs its own fixed model; with no usable
        variant the step runs the worker noun's model (and says so). None only for a second check
        when no other variant can run."""
        settings = self.rules().get("model") or {}
        tuning, _ = self.tuning()
        version = tuning.get("tuner_version")
        rng = random.Random(f"{lease.task_id}:{lease.fencing_token}:{step}:{len(exclude)}")  # noqa: S311
        if self.config.volunteer:
            # A volunteer runs its own model and draws a persona from the mix's variants on it, so its
            # facts name the model and the persona; with none usable it runs the model plainly.
            own = self.model_id()
            drawn = tuning_mod.pick(
                tuning,
                step,
                rng,
                usable=lambda v: self.usable(v) and v.get("model") == own,
                exclude=exclude,
            )
            if drawn is not None:
                return {**drawn, "why": f"a volunteer's AI on its own model: {drawn['why']}"}
            if exclude:
                return None
            fixed = {"id": "volunteer", "step": step, "model": own, "temperature": 0.0}
            why = "the volunteer mode runs its own fixed model"
            return {"variant": fixed, "probability": 1.0, "tuner_version": None, "why": why}
        picked = tuning_mod.pick(tuning, step, rng, usable=self.usable, exclude=exclude)
        if picked is not None or exclude:
            return picked
        fallback = {"id": "fallback", "step": step, "model": str(settings.get("id") or "")}
        why = "no usable variant in the tuning noun; the worker noun's model"
        return {"variant": fallback, "probability": 1.0, "tuner_version": version, "why": why}

    def pick_fields(self, pick: dict[str, Any]) -> dict[str, Any]:
        """A pick as status facts and execution reports record it."""
        variant = pick["variant"]
        model_id = str(variant.get("model") or "")
        persona = variant.get("persona") if isinstance(variant.get("persona"), dict) else {}
        return {
            "model": model_id,
            "model_display": self.model_display(model_id),
            "variant": variant.get("id"),
            "persona": persona.get("title"),
            "tuner_version": pick.get("tuner_version"),
            "probability": pick.get("probability"),
            "why": pick.get("why"),
        }

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
        if self.config.volunteer:
            kinds = [k for k in kinds if k in VOLUNTEER_KINDS]
        if process_part.is_stub(self.handler):
            kinds = [
                k for k in kinds if k not in (process_part.BUILD_KIND, process_part.REVIEW_KIND)
            ]
        if any(k in MODEL_KINDS for k in kinds):
            try:
                model = self._model()
                if hasattr(model, "healthy"):
                    model.healthy()
                model.describe()
            except (
                ModelUnavailable
            ) as exc:  # includes a spent cap: nothing is claimed that needs it
                event = (
                    "model_budget_reached"
                    if isinstance(exc, BudgetExhausted)
                    else "model_unavailable"
                )
                self.trace.write(event, level="warning", error=str(exc)[:200])
                kinds = [k for k in kinds if k not in MODEL_KINDS]
        return kinds

    def model_fields(self, kind: str, pick: dict[str, Any] | None = None) -> dict[str, Any]:
        """What a status fact says a verb runs: the pick (`model` id, `model_display`, variant,
        persona, tuner version, share, why), or the `method` of a step that runs no model, and
        always the `harness` (this worker program, which is never called a model)."""
        out: dict[str, Any] = {"harness": "eranos-worker", "harness_version": __version__}
        if pick is not None:
            return {**out, **self.pick_fields(pick)}
        if kind == process_part.BUILD_KIND:
            name = getattr(self.handler, "name", "installed")
            return {**out, "method": f"process handler: {name}"}
        return {**out, "method": DECLARED.get(kind, "deterministic (no model)")}

    def request_of(self, lease: Lease) -> str | None:
        """The request a verb's facts go to: a request verb's own id, or the request its recorded
        reopen names (none for a reopen its request's record does not name: nothing is written)."""
        if lease.kind == "request":
            try:
                return reopen_target(self.backend, lease) or str(lease.task_id)
            except ReopenRefused:
                return None
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
        self.ensure_tune()
        kinds = self.claim_kinds()
        if not kinds:
            self.pacer.empty(self.queue, now, 0.0)
            return "empty"
        if (
            self.config.dedicated
            and not self.config.volunteer
            and hasattr(self.client, "ready_verbs")
        ):
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
                self.say(
                    "a Task is waiting · volunteers get the first pick, so this worker waits its turn"
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
        self.say(
            f"started ({self.config.role}), looking for {', '.join(STEP_WORDS.get(k, k) for k in self.kinds)}"
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
            self.report_requests()
            if (
                outcome == "worked"
                and max_leases is not None
                and self.stats["worked"] >= max_leases
            ):
                break
            if outcome not in ("worked", "stopped"):
                self.idle_wait()
        self.trace.write(
            "worker_stopped",
            role=self.config.role,
            worker=self.config.label,
            exit_code=self.exit_code,
            stats=dict(self.stats),
            requests_this_hour=self.requests.current(),
            requests_since_start=dict(self.requests.total),
        )
        return self.stats

    def report_requests(self) -> None:
        """Each whole hour's requests by target and method, once, in the run log."""
        for hour, counts in self.requests.finished():
            self.trace.write("requests_hourly", queue=self.queue, **hourly_summary(hour, counts))

    def idle_wait(self) -> None:
        """Wait for the queue's next claim time, looking every few seconds (one local stat) at its
        wake file: a poke from a worker that just made work here, or an operator, ends the wait."""
        end = time.monotonic() + min(60.0, max(1.0, self.pacer.wait(self.clock())))
        while not self.stop.is_set():
            mark = wake_mark(self.queue)
            if mark > self._woke_at:
                self._woke_at = mark
                self.pacer.worked(self.queue, self.clock())
                self.trace.write("woken", queue=self.queue)
                return
            left = end - time.monotonic()
            if left <= 0:
                return
            self.stop.wait(min(5.0, left))

    def poke_after(self, lease: Lease, outcome: Any) -> None:
        """Wake the local worker of the queue this lease just made work for."""
        status = (outcome or {}).get("status") if isinstance(outcome, dict) else None
        if lease.kind == "request" and status in ("split", "reuse_check"):
            poke("eq02")
            poke("eq03")
        elif lease.queue == "eq02":
            poke("eq03")  # a submitted part's check is ready
        elif lease.queue == "eq03":
            poke("eq01")  # a decided check wakes its request for the planner

    # the work ----------------------------------------------------------------------------------
    def _report_factory(
        self, lease: Lease, meter: UsageMeter, notes: dict[str, Any]
    ) -> Callable[[Any, bool, str | None], dict[str, Any]]:
        def report(output: Any, ok: bool, error: str | None) -> dict[str, Any]:
            status = output.get("status") if isinstance(output, dict) else None
            pick = notes.get("pick")
            declared = self.model_fields(lease.kind, pick)
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
                    "worker_kind": self.who()["worker_kind"],
                    "declared_model": declared.get("model"),
                    **{
                        k: declared[k]
                        for k in (
                            "method",
                            "variant",
                            "persona",
                            "tuner_version",
                            "probability",
                            "why",
                        )
                        if k in declared
                    },
                    **(
                        {"second_check": self.pick_fields(notes["second_pick"])}
                        if notes.get("second_pick")
                        else {}
                    ),
                    "tier": "standard" if meter.calls else None,
                    "cost_usd": meter.cost_usd,
                    "payer": self.payer() if meter.calls else "no model call; no charge",
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
            self._pick = None
            if lease.kind in KIT_KINDS:
                outcome = self.kit(gate, lease)
            elif lease.kind == "tune":
                outcome = self.tune(gate, lease, meter)
            elif self.config.role == "planner":
                self.say("claimed a request to plan · deterministic planner (no model)")
                outcome = Planner(
                    gate,
                    lease,
                    worker=self.config.display,
                    nouns=load_nouns(gate),
                    handler=self.handler,
                    who=self.who(),
                    key_id=self.config.key_id,
                ).run()
                self.say(
                    f"planned it · {str((outcome or {}).get('status') or 'done').replace('_', ' ')}"
                )
            elif self.config.role == "builder":
                outcome = self.build(gate, lease, meter, notes, part, request_id)
            else:
                outcome = self.review(gate, lease, meter, notes, part, request_id)
            self.stats["worked"] += 1
            self.poke_after(lease, outcome)
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
        self.say(f"could not finish {STEP_WORDS.get(lease.kind, 'a Task')} · {type(exc).__name__}")
        if isinstance(exc, ExampleOnlyRefused):
            message = (
                "Tessera refused personal or payment data in a write (example_only); the part"
                f" needs example data only: {str(exc)[:600]}"
            )
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
            if (
                request_id
                and not self.stop.is_set()
                and not isinstance(exc, (NotInPlan, ReopenRefused))
            ):
                # G2: a Task its request's plan does not list writes nothing onto that request.
                # A self-approval that was refused is the page's check_refused; any other failure
                # puts the verb back in line (work_released), citing its ok=false receipt if any.
                kind = "check_refused" if isinstance(exc, SelfReviewRefused) else "work_released"
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
                            **self._failed_tuning(lease),
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

    def _claimed(
        self,
        kind: str,
        lease: Lease,
        part: Any,
        request_id: str | None,
        pick: dict[str, Any] | None = None,
    ) -> None:
        fields = self.model_fields(lease.kind, pick)
        how = (
            f"{fields['model_display']}"
            + (f" · persona {fields['persona']}" if fields.get("persona") else "")
            if pick is not None
            else str(fields.get("method") or "")
        )
        self.say(f"claimed {STEP_WORDS.get(lease.kind, 'a Task')} · {how}")
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
                    **self.model_fields(lease.kind, pick),
                    lease_ends=lease.expires_at,
                    queue=queue_snapshot(self.backend, [self.config.label]),
                )
            ],
        )

    def planned_task(self, gate: LeaseGate, lease: Lease, request_id: str | None) -> None:
        """Refuse a request's research, build or check Task unless the request's plan names it, so a
        Task someone else queued with a brief of their own is never worked or published. The planner
        writes the plan just after it creates the Tasks, so a missing name is read again shortly."""
        if lease.kind in KIT_KINDS:
            return
        if not request_id:  # G1: a research, build or check Task always belongs to a request
            raise NotInPlan("the Task names no request")
        for wait in (0.0, 2.0, 5.0):
            if wait:
                self.sleep(wait)
            try:
                plan = gate.get_record("eranos.plans", request_id).value
            except NotFound:
                plan = None
            if lease.task_id in _task_ids(plan):
                return
        raise NotInPlan("the request's plan does not name this Task")

    def build(
        self,
        gate: LeaseGate,
        lease: Lease,
        meter: UsageMeter,
        notes: dict[str, Any],
        part: Any,
        request_id: str | None,
    ) -> dict[str, Any]:
        self.planned_task(gate, lease, request_id)
        pick = self.pick_for("make", lease) if lease.kind == "research" else None
        notes["pick"] = self._pick = pick
        self._claimed("work_claimed", lease, part, request_id, pick)
        started = time.time()
        nouns = load_nouns(gate)
        if pick is not None:
            variant = pick["variant"]
            done = research.do_research(
                gate,
                lease,
                fetcher=self._fetcher(nouns["worker"]),
                model=self.meta(str(variant.get("model") or "")),
                meter=meter,
                worker_rules=nouns["worker"],
                variant=variant,
            )
        else:
            done = process_part.do_process(gate, lease, handler=self.handler)
        notes["artifact_refs"] = done.get("artifact_refs") or []
        idem = f"{lease.task_id}:{lease.fencing_token}"
        stages = (((done.get("output") or {}).get("report") or {}).get("stages")) or {}
        if pick is not None and stages:
            fetched = int((stages.get("fetch") or {}).get("fetched", 0) or 0)
            kept = int(stages.get("kept", 0) or 0)
            self.say(
                f"fetched {fetched} public source{'' if fetched == 1 else 's'} · "
                f"{kept} claim{'' if kept == 1 else 's'} kept with word-for-word quotes"
            )
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
                        "work_released",
                        part=part,
                        receipt=receipt.receipt_hash,
                        **self.who(),
                        reason=error[:500],
                        summary={**(done.get("summary") or {}), "tokens": meter.total_tokens},
                        **self._failed_tuning(lease, done),
                    )
                ],
            )
            return {"status": "self_test_failed"}
        receipt = gate.submit(
            lease.task_id, lease.fencing_token, done["output"], idempotency_key=idem, ok=True
        )
        self.say("its own checks passed · reported: submitted for an independent check")
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
                    **(
                        {
                            "tuning": {
                                "step": "make",
                                "variant": pick["variant"].get("id"),
                                "cost_usd": meter.cost_usd,
                                "seconds": round(time.time() - started, 1),
                            }
                        }
                        if pick is not None
                        else {}
                    ),
                )
            ],
        )
        return {"status": "submitted", "receipt": receipt.receipt_hash}

    def review(
        self,
        gate: LeaseGate,
        lease: Lease,
        meter: UsageMeter,
        notes: dict[str, Any],
        part: Any,
        request_id: str | None,
    ) -> dict[str, Any]:
        self.planned_task(gate, lease, request_id)
        if lease.kind == REUSE_KIND:
            return self.check_reuse(gate, lease, meter, part, request_id)
        pick = self.pick_for("check", lease) if lease.kind == "report_review" else None
        notes["pick"] = self._pick = pick
        self._claimed("check_claimed", lease, part, request_id, pick)
        nouns = load_nouns(gate)
        if pick is not None:
            out = research.review_research(
                gate,
                lease,
                worker=self.config.label,
                key_id=self.config.key_id,
                fetcher=self._fetcher(nouns["worker"]),
                worker_rules=nouns["worker"],
                guardrails=nouns.get("public-research") or {},
                checker=self.checker(lease, pick, meter, notes, nouns["worker"]),
            )
        else:
            out = process_part.review_package(
                gate,
                lease,
                handler=self.handler,
                key_id=self.config.key_id,
                trusted_keys=self.process_builder_keys,
            )
        self._facts(gate, request_id, self.review_facts(lease, out, part))
        status = out.get("status")
        self.say(
            "checks passed · reported: delivered to the requester"
            if status == "delivered"
            else "checks passed · reported: published to the library"
            if status == "published"
            else "reported: sent back for another try"
        )
        return out

    def reuse_pick(self) -> dict[str, Any]:
        """The reuse check's fixed model (the worker noun's `reuse.check.model`), as facts name it."""
        check = (self.rules().get("reuse") or {}).get("check") or {}
        model_id = str(check.get("model") or self.model_id())
        variant = {"id": "reuse-check", "step": "reuse", "model": model_id, "temperature": 0.0}
        why = "the reuse check's fixed model (the worker noun)"
        return {"variant": variant, "probability": 1.0, "tuner_version": None, "why": why}

    def check_reuse(
        self, gate: LeaseGate, lease: Lease, meter: UsageMeter, part: Any, request_id: str | None
    ) -> dict[str, Any]:
        """F-REUSE-001: decide with a Muse model whether a library answer fits this request."""
        pick = self.reuse_pick()
        self._claimed("check_claimed", lease, part, request_id, pick)
        rules = (self.rules().get("reuse") or {}).get("check") or {}
        model_id = str(pick["variant"]["model"])

        def judge(question: str, library: dict[str, Any]) -> dict[str, Any]:
            spent, started = meter.cost_usd, time.time()
            answer = self.meta(model_id).chat_json(
                str(rules.get("prompt") or ""),
                judge_user(question, library),
                meter=meter,
                temperature=float(rules.get("temperature") or 0.0),
                reasoning_effort=rules.get("reasoning_effort"),
            )
            return {
                **read_judgment(answer),
                "model": model_id,
                "model_display": self.model_display(model_id),
                "cost_usd": round(meter.cost_usd - spent, 6),
                "seconds": round(time.time() - started, 1),
            }

        out = review_reuse(gate, lease, key_id=self.config.key_id, judge=judge)
        self._facts(gate, request_id, self.reuse_facts(lease, out, part))
        check = out.get("check") or {}
        self.say(
            "checks passed · reported: answered from the library"
            if out.get("status") == "delivered"
            else f"reported: the library answer does not fit ({check.get('answers')}) · new work next"
        )
        return out

    def reuse_facts(self, lease: Lease, out: dict[str, Any], part: Any) -> list[dict[str, Any]]:
        """The fit check's own fact, the page's `reuse_checked` (Eranos 2dce2dd): `fits` only when
        the model said yes, `does_not_fit` for a no or an unsure answer; the checker's role (its
        label, never a key), the model, the similarity and a ref to the matched answer. A fit is then
        answered from the library; otherwise the planner plans new work."""
        who, receipt = self.who()["worker"], out.get("receipt")
        pointer, check = dict(out.get("reused") or {}), dict(out.get("check") or {})
        answer_ref = f"{pointer.get('store')}/{pointer.get('key')}"
        fits = out.get("status") == "delivered"
        facts = [
            fact(
                "reuse_checked",
                part=part,
                receipt=receipt,
                ref=answer_ref,
                worker=who,
                verdict="fits" if fits else "does_not_fit",
                checker_role=who,
                model=check.get("model"),
                model_name=check.get("model_display"),
                model_display=check.get("model_display"),
                similarity=pointer.get("score"),
                reason=check.get("why") or None,
                summary={"answers": check.get("answers"), "cost_usd": check.get("cost_usd")},
            )
        ]
        if fits:
            kind = "delivered" if pointer.get("kind") == "report" else "published"
            facts.append(
                fact(
                    kind,
                    part=part,
                    receipt=receipt,
                    ref=answer_ref,
                    result_id=pointer.get("key"),
                    reason=f"Answered from the library after another worker checked that it fits: {check.get('why') or 'it answers this request'}",
                    summary={"reused": True, "score": pointer.get("score"), "new_verbs": 1},
                )
            )
        return facts

    # example kits (spec on eq01, draft on eq02, review on eq03) ----------------------------------
    def _bundles(self) -> dict[str, dict[str, Any]]:
        if self._kit_bundles is None:
            self._kit_bundles = {str(b["request"]["kit_id"]): b for b in load_example_bundles()}
        return self._kit_bundles

    def kit(self, gate: LeaseGate, lease: Lease) -> dict[str, Any]:
        """One step of an example kit's rebuild, in plain words; publication follows the review."""
        worker, key_id = self.config.label, self.config.key_id
        if lease.kind == "spec":
            return dict(
                run_spec_step(gate, worker=worker, key_id=key_id) or {"status": "nothing_claimed"}
            ) | {"status": "spec_done"}
        if lease.kind == "draft":
            kit_id = str(((lease.brief or {}).get("request") or {}).get("kit_id") or "")
            bundle = self._bundles().get(kit_id)
            if bundle is None:
                raise ValueError(f"there is no example kit {kit_id!r} on this machine")
            draft = plain(bundle["draft"])
            if left := forbidden(draft):
                raise ValueError(f"the kit still says a forbidden word at {', '.join(left[:3])}")
            done = run_draft_step(gate, draft, worker=worker, key_id=key_id)
            return {"status": "submitted" if done else "nothing_claimed", "kit_id": kit_id}
        dep = lease.dependencies[0]
        if dep.state != "done" or not isinstance(dep.output, dict):
            receipt = gate.submit(
                lease.task_id,
                lease.fencing_token,
                {"node": "review", "status": "nothing_to_review", "draft_state": dep.state},
                idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
                ok=True,
            )
            return {"status": "nothing_to_review", "receipt": receipt.receipt_hash}
        draft = KitDraft.model_validate(dep.output["draft"])
        decision = synthesize_review_decision(
            draft,
            VerificationReport.model_validate(dep.output["verification"]),
            worker=worker,
            key_id=key_id,
        )
        if forbidden(dep.output):
            decision = decision.model_copy(
                update={
                    "verdict": "needs_revision",
                    "notes": "The kit still says a word the owner forbids; it is not published.",
                }
            )
        return dict(
            run_review_step(gate, decision, worker=worker, key_id=key_id)
            or {"status": "nothing_claimed"}
        )

    def review_facts(self, lease: Lease, out: dict[str, Any], part: Any) -> list[dict[str, Any]]:
        who, status = self.who()["worker"], out.get("status")
        tuned = self._check_tuning(lease, out)
        receipt = out.get("receipt") or out.get("review_receipt")
        tasks = [d.task_id for d in lease.dependencies] + [lease.task_id]
        kind = {k: v for k, v in self.who().items() if k != "worker"}
        builder = lease.dependencies[0].completed_by_key if lease.dependencies else None
        work_by = (
            "a dedicated worker (run by ta-amps)"
            if builder and builder in self.config.our_key_ids
            else "a volunteer's AI"
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
                    **tuned,
                ),
                fact("delivered", part=part, receipt=receipt, ref=ref, result_id=out["report_id"]),
                fact(
                    "library_added",
                    part=part,
                    receipt=receipt,
                    ref=ref,
                    library_ref=f"{config.surface_public_url()}/api/nouns/eranos.solutions/{out['report_id']}",
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
                    "library_added",
                    part=part,
                    receipt=receipt,
                    ref=ref,
                    library_ref=f"{config.surface_public_url()}/api/catalog/{key}",
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
                **tuned,
            )
        ]

    # self-tuning ------------------------------------------------------------------------------
    def _failed_tuning(self, lease: Lease, done: dict[str, Any] | None = None) -> dict[str, Any]:
        """A failed make attempt's variant, for the tuner (which leaves out failures of the model
        or the store, by the recorded reason). A research that fetched nothing or found no
        candidate sentence failed on its sources (`source_side`), and an empty answer is marked
        `no_claims`, so neither is charged to the variant on its own (FB1-024)."""
        pick = self._pick
        if pick is None or lease.kind != "research":
            return {}
        record: dict[str, Any] = {"step": "make", "variant": pick["variant"].get("id")}
        stages = ((((done or {}).get("output") or {}).get("report") or {}).get("stages")) or {}
        if stages:
            if not (stages.get("fetch") or {}).get("fetched") or not stages.get("candidates"):
                record["source_side"] = True
            elif stages.get("answer") == "no_claims":
                record["no_claims"] = True
        return {"tuning": record}

    def _check_tuning(self, lease: Lease, out: dict[str, Any]) -> dict[str, Any]:
        """A check's record for the tuner: its variant, the make variant it judged, what it and
        any second check found unsupported, and their cost and time."""
        checked = out.get("model_check")
        if not isinstance(checked, dict):
            return {}
        research_out = lease.dependencies[0].output if lease.dependencies else None
        made = (research_out or {}).get("made_with") if isinstance(research_out, dict) else None
        record = {
            "step": "check",
            "variant": checked.get("variant"),
            "maker_variant": (made or {}).get("variant"),
            "unsupported": checked.get("unsupported") or [],
            "cost_usd": checked.get("cost_usd"),
            "seconds": checked.get("seconds"),
        }
        second = checked.get("second")
        if isinstance(second, dict):
            record["second"] = {
                k: second.get(k) for k in ("variant", "unsupported", "cost_usd", "seconds")
            }
        return {"tuning": record}

    def checker(
        self,
        lease: Lease,
        pick: dict[str, Any],
        meter: UsageMeter,
        notes: dict[str, Any],
        rules: dict[str, Any],
    ) -> Callable[[str, list[dict[str, Any]]], dict[str, Any]]:
        """The tuned model check of a report's kept claims; a share of checks (the tuning noun's
        check_sampling) get a second check by another variant, whose failure never fails the first."""

        def check(question: str, claims: list[dict[str, Any]]) -> dict[str, Any]:
            result = self.model_check(pick, question, claims, meter, rules)
            tuning, _ = self.tuning()
            share = float((tuning.get("check_sampling") or {}).get("second_check_share") or 0.0)
            draw = random.Random(f"{lease.task_id}:{lease.fencing_token}:second").random()  # noqa: S311
            if self.config.volunteer or draw >= share:
                return result
            second = self.pick_for("check", lease, exclude=(str(pick["variant"].get("id")),))
            if second is None:
                return result
            notes["second_pick"] = second
            try:
                result["second"] = self.model_check(second, question, claims, meter, rules)
            except ModelUnavailable as exc:
                self.trace.write("second_check_failed", level="warning", error=str(exc)[:200])
            return result

        return check

    def model_check(
        self,
        pick: dict[str, Any],
        question: str,
        claims: list[dict[str, Any]],
        meter: UsageMeter,
        rules: dict[str, Any],
    ) -> dict[str, Any]:
        """One variant's verdicts: the claims whose quote does not support them. A claim the model
        gives no verdict for counts as unsupported; no verdicts at all fail the check."""
        variant = pick["variant"]
        persona = variant.get("persona") if isinstance(variant.get("persona"), dict) else {}
        system = str((rules.get("check") or {}).get("prompt") or "")
        if persona.get("text"):
            system += "\n\nHow to work: " + str(persona["text"])
        user = json.dumps(
            {
                "question": question,
                "claims": [
                    {"id": c["id"], "claim": c["text"], "quote": c["citations"][0]["quote"]}
                    for c in claims
                ],
            },
            ensure_ascii=False,
        )
        spent, started = meter.cost_usd, time.time()
        answer = self.meta(str(variant.get("model") or "")).chat_json(
            system,
            user,
            meter=meter,
            temperature=float(variant.get("temperature") or 0.0),
            reasoning_effort=variant.get("reasoning_effort"),
        )
        verdicts = answer.get("claims") if isinstance(answer, dict) else None
        if not isinstance(verdicts, list) or not verdicts:
            raise ModelUnavailable(f"{variant.get('model')} gave no claim verdicts")
        supported = {
            str(v.get("id")) for v in verdicts if isinstance(v, dict) and v.get("supported") is True
        }
        return {
            "variant": variant.get("id"),
            "model": variant.get("model"),
            "unsupported": sorted(c["id"] for c in claims if c["id"] not in supported),
            "cost_usd": round(meter.cost_usd - spent, 6),
            "seconds": round(time.time() - started, 1),
        }

    def ensure_tune(self) -> None:
        """The dedicated planner queues this hour's tuner task once (a fixed task id, so never twice)."""
        now = time.time()
        if self.config.role != "planner" or not self.config.dedicated or now < self._tune_check_at:
            return
        if not hasattr(self.backend, "enqueue"):  # a backend that cannot queue tasks (tests)
            return
        self._tune_check_at = (now // 3600 + 1) * 3600
        task_id = tuning_mod.hour_task_id(now)
        try:
            self.backend.enqueue(
                TaskSpec(
                    queue="eq01",
                    task_id=task_id,
                    kind="tune",
                    effect_class="write-internal",
                    producer_surface="surface:eranos",
                    brief={
                        "title": "Retune the workers' variant mix",
                        "noun": "eranos.instructions/worker.policy",
                    },
                )
            )
            self.trace.write("tune_queued", task_id=task_id)
        except StorageQuotaExhausted as exc:
            self._allowance_spent(exc)
        except Exception as exc:  # already queued, or not allowed: recorded, never fatal
            self.trace.write("tune_not_queued", task_id=task_id, error=type(exc).__name__)

    def tune(self, gate: LeaseGate, lease: Lease, meter: UsageMeter) -> dict[str, Any]:
        """The hourly tuner: shares from every recorded outcome, trials kept or dropped, and a
        drafted persona for a step that keeps failing. It writes the next tuning version (compare
        and set) and submits what it read and changed."""
        tuning, version = self.tuning(fresh=True)
        rewards = tuning.get("rewards") or {}
        records = gate.list_records("eranos.requests", limit=200)
        outcomes = [
            o
            for r in records
            if isinstance(r.value, dict)
            for o in tuning_mod.outcomes_from_events(
                r.key, list(r.value.get("events") or []), rewards
            )
        ]
        now = time.time()
        for v in tuning.get("variants") or []:
            if isinstance(v, dict) and v.get("model"):
                v["model_display"] = self.model_display(str(v["model"]))
        nxt = tuning_mod.retune(tuning, outcomes, now=now)
        proposals = []
        for step in tuning_mod.STEPS:
            failed = tuning_mod.failures_to_propose(tuning, outcomes, step)
            if not failed:
                continue
            proposals.append(self._propose(nxt, step, failed, meter, now))
        if proposals:
            nxt["inputs"]["proposals"] = proposals
            nxt["summary"] = tuning_mod.summary(nxt["variants"], nxt["mix"], nxt["stats"])
        saved = gate.put_record(
            tuning_mod.TUNING_STORE,
            tuning_mod.TUNING_KEY,
            nxt,
            expected_version=version,
            producer_surface="surface:eranos",
            visibility_scope="public_commons",
            tags=["kind:instructions", "kind:worker_policy"],
        )
        self._tuning = (nxt, int(saved.version))
        self._write_shares(gate, nxt, len(outcomes), now)
        output = {
            "node": "tune",
            "status": "tuned",
            "tuner_version": nxt["tuner_version"],
            "record_version": int(saved.version),
            "outcomes": len(outcomes),
            "mix": nxt["mix"],
            "proposals": proposals,
        }
        gate.submit(
            lease.task_id,
            lease.fencing_token,
            output,
            idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
            ok=True,
        )
        self.trace.write("tuned", tuner_version=nxt["tuner_version"], outcomes=len(outcomes))
        return output

    def _write_shares(
        self, gate: LeaseGate, policy: dict[str, Any], outcomes: int, now: float
    ) -> None:
        """The public share line beside the tuning noun (eranos.instructions/worker.shares); a
        failed write is logged and never fails the tune."""
        value = tuning_mod.shares(
            list(policy.get("variants") or []),
            dict(policy.get("mix") or {}),
            dict(policy.get("stats") or {}),
            tuner_version=int(policy.get("tuner_version") or 0),
            as_of=now,
            outcomes=outcomes,
        )
        try:
            try:
                version = int(
                    gate.get_record(tuning_mod.TUNING_STORE, tuning_mod.SHARES_KEY).version
                )
            except NotFound:
                version = 0
            gate.put_record(
                tuning_mod.TUNING_STORE,
                tuning_mod.SHARES_KEY,
                value,
                expected_version=version,
                producer_surface="surface:eranos",
                visibility_scope="public_commons",
                tags=["kind:instructions", "kind:worker_shares"],
            )
        except Exception as exc:
            self.trace.write("shares_not_written", level="warning", error=type(exc).__name__)

    def _propose(
        self,
        nxt: dict[str, Any],
        step: str,
        failed: list[tuning_mod.Outcome],
        meter: UsageMeter,
        now: float,
    ) -> dict[str, Any]:
        """Ask a Muse model for a new persona from the step's recorded failures; a draft that
        passes every rule enters as a trial at a small share. Any refusal is recorded."""
        rules = nxt.get("propose") or {}
        model_id = str(rules.get("model") or self.model_id())
        shares = (nxt.get("mix") or {}).get(step) or {}
        live = [x for x in tuning_mod.live_variants(nxt, step) if self.usable(x)]  # review N3
        base = max(live, key=lambda v: shares.get(v["id"], 0.0)) if live else {}
        nxt.setdefault("proposed_at", {})[step] = now
        try:
            system, user = tuning_mod.proposal_prompt(step, base, failed)
            answer = self.meta(model_id).chat_json(system, user, meter=meter, temperature=0.4)
        except ModelUnavailable as exc:
            return {"step": step, "added": None, "why": f"no draft: {str(exc)[:200]}"}
        persona, why = tuning_mod.checked_persona(answer)
        if persona is None:
            return {"step": step, "added": None, "why": why, "drafted_with": model_id}
        trial = tuning_mod.trial_variant(
            step,
            base,
            persona,
            version=int(nxt["tuner_version"]),
            drafted_with=model_id,
            failed=failed,
            now=now,
        )
        nxt["variants"].append(trial)
        share = float((nxt.get("trial") or {}).get("share") or 0.05)
        scaled = {k: round(v * (1.0 - share), 4) for k, v in shares.items()}
        nxt["mix"][step] = {**scaled, trial["id"]: share}
        return {"step": step, "added": trial["id"], "why": why, "drafted_with": model_id}


def _task_ids(value: Any) -> set[str]:
    """Every work and check Task id a plan names, in its parts and in each occurrence's parts."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("work_task_id", "review_task_id") and isinstance(item, str):
                found.add(item)
            else:
                found |= _task_ids(item)
    elif isinstance(value, list):
        for item in value:
            found |= _task_ids(item)
    return found


def _client(config: WorkerConfig, counter: RequestCounter | None = None) -> WorkerClient:
    """A Tessera client for this worker's key; an explicit transport means no proxy from the
    environment. With a counter, every request it sends is counted."""
    transport: httpx.BaseTransport = httpx.HTTPTransport(retries=0)
    if counter is not None:
        transport = CountingTransport(transport, counter, "tessera")
    return WorkerClient(
        config.tessera_url,
        key=config.key,
        surface_id="eranos",
        namespace="main",
        max_retries=0,
        transport=transport,
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
