"""The self-tuning loop: outcomes from recorded facts, the retune, picks, proposals, the hourly task,
and Tessera's personal-data refusal code. Nothing here calls a model or a server."""

from __future__ import annotations

import json
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from eranos.jsonfile import load_json
from eranos.model_client import BudgetExhausted
from eranos.pipeline import process as process_part
from eranos.pipeline import tuning
from eranos.worker_loop import ExampleOnlyRefused, Worker, WorkerConfig

ROOT = Path(__file__).resolve().parents[1]
TUNING = load_json(ROOT / "instructions" / "worker.policy.json")
RULES = load_json(ROOT / "instructions" / "worker.json")
REWARDS = TUNING["rewards"]


def made(
    part: int, variant: str, at: float, kind: str = "work_submitted", **extra: Any
) -> dict[str, Any]:
    return {
        "type": kind,
        "part": part,
        "at": at,
        "tuning": {"step": "make", "variant": variant, **extra},
    }


def checked(
    part: int, at: float, ok: bool, variant: str, maker: str, **extra: Any
) -> dict[str, Any]:
    kind = "check_approved" if ok else "check_sent_back"
    record = {
        "step": "check",
        "variant": variant,
        "maker_variant": maker,
        "unsupported": [],
        **extra,
    }
    return {"type": kind, "part": part, "at": at, "tuning": record}


def test_outcomes_come_only_from_recorded_facts() -> None:
    events = [
        {"type": "received", "at": 1},
        made(1, "make-spark-careful", 2, cost_usd=0.002, seconds=30),
        checked(1, 3, True, "check-spark-skeptical", "make-spark-careful"),
        made(2, "make-spark-quick", 4),
        checked(2, 5, False, "check-spark-skeptical", "make-spark-quick"),
        made(3, "make-wonder-careful", 6, kind="work_released")
        | {"reason": "ModelUnavailable: muse-wonder-1.0 answered 503"},
        made(3, "make-wonder-careful", 7, kind="work_released")
        | {"reason": "only 2 claims kept a verbatim quote"},
        {"type": "decided", "part": 1, "at": 8, "choice": "use"},
    ]
    out = tuning.outcomes_from_events("rq-1", events, REWARDS)
    make = [(o.variant, round(o.success, 3), o.reason) for o in out if o.step == "make"]
    assert (
        "make-spark-careful",
        round(1 - tuning.penalty(REWARDS, 0.002, 30), 3),
        "check_approved",
    ) in make
    assert ("make-spark-quick", 0.0, "check_sent_back") in make
    assert ("make-wonder-careful", 0.0, "failed") in make  # the 503 is not the variant's fault
    assert len([o for o in out if o.variant == "make-wonder-careful"]) == 1
    assert ("make-spark-careful", 1.0, "person: use") in make
    assert [o.reason for o in out if o.step == "check"] == [
        "person: use"
    ]  # no second check: no pair


def test_a_second_check_pair_rewards_agreement_and_weighs_a_missed_fault() -> None:
    second = {"variant": "check-wonder-literal", "unsupported": ["C2"]}
    events = [
        made(1, "make-spark-careful", 1),
        checked(1, 2, True, "check-spark-skeptical", "make-spark-careful", second=second),
    ]
    out = {
        o.variant: o
        for o in tuning.outcomes_from_events("rq-2", events, REWARDS)
        if o.step == "check"
    }
    assert out["check-spark-skeptical"].reason == "missed a fault"
    assert out["check-spark-skeptical"].weight == REWARDS["missed_fault_weight"]
    assert (
        out["check-wonder-literal"].reason == "disagreed"
        and out["check-wonder-literal"].weight == 1
    )
    agree = [
        made(1, "m", 1),
        checked(1, 2, True, "a", "m", second={"variant": "b", "unsupported": []}),
    ]
    assert {
        o.reason for o in tuning.outcomes_from_events("rq-3", agree, REWARDS) if o.step == "check"
    } == {"agreed"}


def fixture_outcomes() -> list[tuning.Outcome]:
    good = [
        tuning.Outcome("make", "make-spark-careful", 1.0, 1.0, f"rq#{i}@{i}") for i in range(12)
    ]
    poor = [
        tuning.Outcome("make", "make-spark-quick", 0.0, 1.0, f"rq#q{i}@{100 + i}")
        for i in range(12)
    ]
    mixed = [
        tuning.Outcome("make", "make-wonder-careful", float(i % 2), 1.0, f"rq#w{i}@{200 + i}")
        for i in range(6)
    ]
    return good + poor + mixed


def test_the_retune_moves_the_mix_toward_reward_and_is_deterministic() -> None:
    first = tuning.retune(TUNING, fixture_outcomes(), now=1000.0)
    again = tuning.retune(TUNING, fixture_outcomes(), now=1000.0)
    assert first == again  # same inputs, same version
    mix = first["mix"]["make"]
    assert first["tuner_version"] == 1 and abs(sum(mix.values()) - 1) < 1e-3
    assert mix["make-spark-careful"] > 0.8 > mix.get("make-spark-quick", 0.0)
    dropped = {v["id"] for v in first["variants"] if v.get("status") == "dropped"}
    assert dropped == {
        "make-spark-quick"
    }  # 12 recorded failures and almost no chance of being best
    assert (
        first["mix"]["check"] == TUNING["mix"]["check"]
        or sum(first["mix"]["check"].values()) > 0.99
    )
    assert first["summary"]["mix"]["make"].startswith("Muse Spark 1.3 ")
    assert (
        sum(
            int(part.rsplit(" ", 1)[1][:-1])
            for part in first["summary"]["mix"]["make"].split(" · ")
        )
        == 100
    )
    assert first["inputs"]["outcomes"] == 30


def test_a_trial_runs_at_a_small_share_until_it_has_results() -> None:
    trial = {**TUNING["variants"][0], "id": "make-t1", "status": "trial"}
    base = {**TUNING, "variants": [*TUNING["variants"], trial]}
    early = tuning.retune(base, fixture_outcomes(), now=1.0)
    assert early["mix"]["make"]["make-t1"] == pytest.approx(TUNING["trial"]["share"], abs=1e-3)
    results = [tuning.Outcome("make", "make-t1", 1.0, 1.0, f"rq#t{i}@{i}") for i in range(5)]
    later = tuning.retune(base, fixture_outcomes() + results, now=2.0)
    assert next(v for v in later["variants"] if v["id"] == "make-t1")["status"] == "active"


def test_a_pick_records_its_share_and_skips_what_cannot_run() -> None:
    rng = random.Random(1)  # noqa: S311 - a reproducible draw
    got = tuning.pick(TUNING, "check", rng, usable=lambda v: v["model"] == "muse-spark-1.3")
    assert got is not None and got["variant"]["model"] == "muse-spark-1.3"
    assert got["probability"] == 0.5 and "starting mix" in got["why"]
    second = tuning.pick(TUNING, "check", rng, exclude=[got["variant"]["id"]])
    assert second is not None and second["variant"]["id"] != got["variant"]["id"]
    assert tuning.pick(TUNING, "check", rng, usable=lambda v: False) is None


@pytest.mark.parametrize(
    ("draft", "ok"),
    [
        (
            {
                "title": "Steady maker",
                "text": "Answer from the sentences that say the most, one plain claim per sentence, and leave out anything the sentence does not state.",
            },
            True,
        ),
        (
            {
                "title": "Made-up words",
                "text": "Use synthetic examples whenever a sentence is unclear, and keep every claim close to its sentence.",
            },
            False,
        ),
        (
            {
                "title": "Accuser",
                "text": "Call out every scammer and fraudster you find in the sources, then list the claims that prove it.",
            },
            False,
        ),
        (
            {
                "title": "Linker",
                "text": "Check https://example.org/rules first, then propose claims that rest on one sentence each.",
            },
            False,
        ),
        (
            {
                "title": "Caller",
                "text": "Ask the requester to call 555-867-5309 before you answer, then propose claims from the sentences.",
            },
            False,
        ),
        ("not an object", False),
    ],
)
def test_a_drafted_persona_enters_only_when_it_passes_every_rule(draft: Any, ok: bool) -> None:
    persona, why = tuning.checked_persona(draft)
    assert (persona is not None) is ok, why


class Backend:
    """Records what the worker writes; serves the nouns and fixture request records."""

    def __init__(self, records: list[Any]) -> None:
        self.records, self.puts, self.submits, self.enqueued = records, [], [], []

    def get_record(self, store: str, key: str) -> Any:
        if key == "worker":
            return SimpleNamespace(value=RULES, version=4)
        raise LookupError(key)

    def list_records(self, store: str, *, limit: int) -> list[Any]:
        return self.records

    def put_record(self, store: str, key: str, value: Any, **kw: Any) -> Any:
        self.puts.append((store, key, value, kw))
        return SimpleNamespace(version=kw["expected_version"] + 1)

    def submit(self, *args: Any, **kw: Any) -> Any:
        self.submits.append((args, kw))
        return SimpleNamespace(receipt_hash="r" * 64)

    def enqueue(self, spec: Any) -> str:
        if any(s.task_id == spec.task_id for s in self.enqueued):
            raise httpx.HTTPError("already queued")
        self.enqueued.append(spec)
        return str(spec.task_id)


class Drafter:
    def __init__(self, answer: Any = None, error: Exception | None = None) -> None:
        self.answer, self.error, self.calls = answer, error, 0

    def describe(self) -> dict[str, Any]:
        return {"provider": "meta", "id": "muse-spark-1.3"}

    def healthy(self) -> None:
        return None

    def chat_json(self, system: str, user: str, **kw: Any) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.answer


def planner(tmp_path: Path, backend: Backend, model: Any) -> Worker:
    config = WorkerConfig(
        dedicated=True,
        role="planner",
        label="t",
        tessera_url="http://127.0.0.1:9",
        key="x",
        key_id="k_t",
        trace_path=str(tmp_path / "t.jsonl"),
    )
    return Worker(
        config,
        backend=backend,
        heartbeat_backend=object(),
        handler=process_part.StubHandler(),
        model=model,
    )


def failing_requests() -> list[Any]:
    events = []
    for i in range(3):
        events += [
            made(i, "make-spark-quick", 10 + i),
            checked(i, 20 + i, False, "check-spark-skeptical", "make-spark-quick"),
        ]
    return [SimpleNamespace(key="rq-f", value={"events": events})]


def test_the_tuner_writes_the_next_version_and_adds_a_checked_trial(tmp_path: Path) -> None:
    backend = Backend(failing_requests())
    drafter = Drafter(
        {
            "title": "Steady maker",
            "text": "Answer from the sentences that say the most, one plain claim per sentence, and leave out anything the sentence does not state.",
        }
    )
    worker = planner(tmp_path, backend, drafter)
    lease = SimpleNamespace(task_id="tune-2026110105", fencing_token=1, kind="tune", brief={})
    out = worker.tune(backend, lease, worker_meter())
    ((store, key, value, kw),) = backend.puts
    assert (store, key, kw["expected_version"]) == ("eranos.instructions", "worker.policy", 0)
    assert value["tuner_version"] == 1 and value["inputs"]["outcomes"] == 3
    trial = next(v for v in value["variants"] if v.get("status") == "trial")
    assert trial["origin"]["by"] == "tuner" and trial["origin"]["drafted_with"] == "muse-spark-1.3"
    assert value["mix"]["make"][trial["id"]] == TUNING["trial"]["share"]
    assert out["proposals"][0]["added"] == trial["id"] and backend.submits


def test_a_spent_cap_or_a_bad_draft_adds_nothing_but_the_retune_still_lands(tmp_path: Path) -> None:
    for drafter, why in (
        (Drafter(error=BudgetExhausted("the daily Meta cap ($5.00) is reached")), "no draft"),
        (
            Drafter(
                {
                    "title": "Odd",
                    "text": "Use synthetic examples for every sentence you cannot read, and say so.",
                }
            ),
            "wording",
        ),
    ):
        backend = Backend(failing_requests())
        out = planner(tmp_path, backend, drafter).tune(
            backend,
            SimpleNamespace(task_id="tune-x", fencing_token=1, kind="tune", brief={}),
            worker_meter(),
        )
        assert out["proposals"][0]["added"] is None and why in out["proposals"][0]["why"]
        assert backend.puts and not any(
            v.get("status") == "trial" for v in backend.puts[0][2]["variants"]
        )


def test_the_planner_queues_one_tuner_task_an_hour(tmp_path: Path) -> None:
    backend = Backend([])
    worker = planner(tmp_path, backend, Drafter())
    worker.ensure_tune()
    worker.ensure_tune()  # the same hour: nothing more
    (spec,) = backend.enqueued
    assert spec.kind == "tune" and spec.queue == "eq01" and spec.task_id.startswith("tune-")
    worker._tune_check_at = 0.0
    worker.ensure_tune()  # an already queued hour is recorded, never duplicated
    assert len(backend.enqueued) == 1
    log = [json.loads(line)["event"] for line in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert log == ["tune_queued", "tune_not_queued"]


def worker_meter() -> Any:
    from eranos.model_client import UsageMeter

    return UsageMeter()


@pytest.mark.parametrize("code", ["example_only", "synthetic_only"])
def test_tesseras_personal_data_refusal_is_understood_under_both_codes(code: str) -> None:
    from tessera.client import error_from_response

    response = httpx.Response(400, json={"code": code, "detail": "personal or payment data"})
    assert isinstance(error_from_response(response), ExampleOnlyRefused)
