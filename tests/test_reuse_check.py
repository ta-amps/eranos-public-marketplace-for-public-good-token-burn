"""Finding F-REUSE-001: a library answer never closes a request without a check by another key.

The film's request ("key food-safety rules for a community food pantry") was closed at similarity
0.71 with a report on political-campaign rules for 501(c)(3) charities, by the planner alone. These
tests hold the fix: that pair never matches; a true near-duplicate only becomes a reuse check verb,
which a different key's Muse model must approve before the request is answered from the library; a
check that says no or is unsure has new work planned; and a wrongly reused request can be opened
again by a recorded reopen, which only its own record can authorize. No server is needed: an
in-memory stand-in for Tessera holds versioned records, splits and submits. The texts are made up
for these tests, except the film pair, which is the real public request and report.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import jsonschema
import pytest
from tessera import Lease, NotFound, VersionConflict
from tessera.models import ChildResult

from eranos.jsonfile import load_json
from eranos.pipeline import reuse, reuse_check
from eranos.pipeline.planner import Planner
from eranos.pipeline.request_noun import REQUESTS_STORE
from eranos.pipeline.run import SelfReviewRefused
from eranos.worker_keys import ROLE_KEYS

ROOT = Path(__file__).resolve().parents[1]
RULES = load_json(ROOT / "instructions" / "worker.json")
CLASSIFY = load_json(ROOT / "instructions" / "classify.json")
GUARDRAILS = load_json(ROOT / "instructions" / "public-research.json")
NOUNS = {"worker": RULES, "classify": CLASSIFY, "public-research": GUARDRAILS}
EVENT_SCHEMA = json.loads((ROOT / "tests" / "support" / "status-event.schema.json").read_text())

# The film pair (F-REUSE-001): the real public request and the report it was wrongly answered with.
FILM_REQUEST = (
    "What are the key food-safety rules for a community food pantry, with a source for every point?"
)
IRS_REPORT = {
    "report_id": "RPT-RC676414-01",
    "title": "Community food pantry: Summarize the IRS tax law rules on political campaign activity for 501(c)(3) charities, with a citation for every poi",
    "question": "Summarize the IRS tax law rules on political campaign activity for 501(c)(3) charities, with a citation for every point.",
    "claims": [
        {
            "id": "C1",
            "text": "Section 501(c)(3) organizations may not take part in any political campaign for or against a candidate.",
        },
        {
            "id": "C2",
            "text": "The ban covers contributions to political campaign funds and public statements of position.",
        },
        {
            "id": "C3",
            "text": "Voter education activities run in a nonpartisan manner are not prohibited.",
        },
    ],
}
NEAR_QUESTION = "Summarize the tax law rules on political campaign activity for 501(c)(3) charities, with a citation for every point."
NEAR_REQUEST = "Our charity needs a cited overview of what the rules say about 501(c)(3) groups and political campaigns."
PLANNER_KEY, REVIEWER_KEY = "k_planner_test", "k_reviewer_test"


class Fabric:
    """Just enough of Tessera: versioned records with compare-and-set, results, splits, submits."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], list[Any]] = {}
        self.result_views: dict[str, list[Any]] = {}
        self.splits: list[tuple[str, list[Any], list[str]]] = []
        self.submits: list[dict[str, Any]] = []

    def get_record(self, store: str, key: str) -> Any:
        versions = self.records.get((store, key))
        if not versions:
            raise NotFound(f"{store}/{key}")
        return SimpleNamespace(
            store=store, key=key, value=copy.deepcopy(versions[-1]), version=len(versions)
        )

    def put_record(
        self, store: str, key: str, value: Any, *, expected_version: int, **kw: Any
    ) -> Any:
        versions = self.records.setdefault((store, key), [])
        if expected_version != len(versions):
            raise VersionConflict(f"{store}/{key} is at {len(versions)}")
        versions.append(copy.deepcopy(value))
        return SimpleNamespace(store=store, key=key, value=value, version=len(versions))

    def list_records(self, store: str, limit: int = 200) -> list[Any]:
        return [self.get_record(s, k) for (s, k) in list(self.records) if s == store][:limit]

    def results(self, task_id: str) -> list[Any]:
        return self.result_views.get(task_id, [])

    def split(self, task_id: str, token: int, children: list[Any]) -> list[str]:
        ids = [f"t_{len(self.splits)}_{i}" for i, _ in enumerate(children)]
        self.splits.append((task_id, list(children), ids))
        return ids

    def submit(self, task_id: str, token: int, output: Any, **kw: Any) -> Any:
        self.submits.append({"task_id": task_id, "output": output, **kw})
        digest = hashlib.sha256(f"{task_id}:{len(self.submits)}".encode()).hexdigest()
        return SimpleNamespace(receipt_hash=digest)

    def task(self, task_id: str) -> Any:
        return SimpleNamespace(created_at=time.time() - 60)

    def counts(self) -> dict[str, Any]:
        return {}

    # helpers for the tests
    def library_report(self, key: str, report: dict[str, Any]) -> None:
        receipt = hashlib.sha256(key.encode()).hexdigest()
        self.records[("eranos.solutions", key)] = [
            {"report": report, "review_receipt": receipt, "review_task_id": f"review-{key}"}
        ]
        self.result_views[f"review-{key}"] = [
            SimpleNamespace(receipt_hash=receipt, ok=True, output={"approved": True})
        ]

    def request(self, request_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.records[(REQUESTS_STORE, request_id)][-1])

    def history(self, request_id: str) -> list[dict[str, Any]]:
        return [v.get("event") or {} for v in self.records[(REQUESTS_STORE, request_id)]]


def _lease(
    task_id: str,
    kind: str,
    queue: str,
    brief: dict[str, Any],
    children: list[ChildResult] | None = None,
) -> Lease:
    now = time.time()
    return Lease(
        task_id=task_id,
        queue=queue,
        fencing_token=3,
        worker="t",
        attempt=1,
        kind=kind,
        effect_class="write-internal",
        brief=brief,
        claimed_at=now,
        expires_at=now + 600,
        hard_expires_at=now + 3600,
        heartbeat_seconds=60,
        claim_receipt="a" * 64,
        children=children or [],
    )


def _request_brief(text: str) -> dict[str, Any]:
    return {"text": text, "links": [], "output_type": "information", "frequency": "one-off"}


def _planner(fabric: Fabric, lease: Lease) -> Planner:
    return Planner(
        fabric,
        lease,
        worker="dedicated worker 1 (run by ta-amps)",
        nouns=NOUNS,
        who={"worker": "dedicated worker 1 (run by ta-amps)", "dedicated": True},
        key_id=PLANNER_KEY,
    )


def _judge(answers: str) -> Any:
    def judge(question: str, library: dict[str, Any]) -> dict[str, Any]:
        return {
            "answers": answers,
            "why": "made-up verdict for the test",
            "model": "muse-spark-1.3",
        }

    return judge


def _kinds(fabric: Fabric) -> list[list[str | None]]:
    return [[c.kind for c in children] for _, children, _ in fabric.splits]


# 1. the film pair -----------------------------------------------------------------------------------
def test_the_film_request_never_matches_the_political_campaign_report() -> None:
    rules = RULES["reuse"]
    old_style = reuse.score(  # the old one-way score over title, question and claims: 0.71
        reuse.terms(FILM_REQUEST, {**rules, "strip": [], "generic": []}),
        reuse.terms(
            " ".join([IRS_REPORT["title"], IRS_REPORT["question"]])
            + " "
            + " ".join(c["text"] for c in IRS_REPORT["claims"]),
            {**rules, "strip": [], "generic": []},
        ),
    )
    assert (
        old_style >= 0.6
    )  # the finding's shape, reproduced: shared phrasing and the title's prefix
    fabric = Fabric()
    fabric.library_report("RPT-RC676414-01", IRS_REPORT)
    considered: dict[str, Any] = {}
    match = reuse.find_reuse(
        fabric, FILM_REQUEST, rules, output_type="information", considered=considered
    )
    assert match is None
    assert considered["threshold"] >= reuse.MIN_THRESHOLD and considered["outcome"]
    # The film request keeps too few distinctive words once the shared phrasing is gone.
    assert reuse.terms(FILM_REQUEST, rules) == {"food", "safety"}


def test_the_film_request_is_planned_as_new_work_and_the_decision_is_recorded() -> None:
    fabric = Fabric()
    fabric.library_report("RPT-RC676414-01", IRS_REPORT)
    rid = "rq-film-pair"
    out = _planner(fabric, _lease(rid, "request", "eq01", _request_brief(FILM_REQUEST))).run()
    assert out["status"] == "split"
    assert _kinds(fabric) == [["research", "report_review"]]
    record = fabric.request(rid)
    assert record["status"] == "open_for_build" and "reused_from" not in record
    planned = next(e for e in fabric.history(rid) if e.get("type") == "planned")
    assert planned["summary"]["reuse"]["outcome"] and "threshold" in planned["summary"]["reuse"]
    assert not any((s["output"] or {}).get("status") == "reused" for s in fabric.submits)


# 2. a true near-duplicate becomes a check, never a close ---------------------------------------------
def _near_duplicate(fabric: Fabric) -> tuple[str, dict[str, Any]]:
    fabric.library_report(
        "RPT-NEAR-01",
        {
            "report_id": "RPT-NEAR-01",
            "title": "Legal-aid clinic: " + NEAR_QUESTION,
            "question": NEAR_QUESTION,
            "claims": IRS_REPORT["claims"],
        },
    )
    rid = "rq-near-duplicate"
    out = _planner(fabric, _lease(rid, "request", "eq01", _request_brief(NEAR_REQUEST))).run()
    return rid, out


def test_a_near_duplicate_only_queues_a_reuse_check_by_another_key() -> None:
    fabric = Fabric()
    rid, out = _near_duplicate(fabric)
    assert out["status"] == "reuse_check" and out["candidate"]["key"] == "RPT-NEAR-01"
    assert _kinds(fabric) == [[reuse_check.REUSE_KIND]]
    child = fabric.splits[0][1][0]
    assert child.queue == "eq03" and child.brief["proposed_by_key"] == PLANNER_KEY
    assert child.brief["candidate"]["score"] >= reuse.MIN_THRESHOLD
    record = fabric.request(rid)
    assert record["status"] == "open_for_build" and record["parts"]["1"]["route"] == "reuse_check"
    assert not fabric.submits  # nothing closed the request
    # The planner's key cannot claim the check; the reviewers' keys can.
    assert reuse_check.REUSE_KIND not in ROLE_KEYS["planner"]["kinds"]
    assert all(reuse_check.REUSE_KIND in ROLE_KEYS[r]["kinds"] for r in ("reviewer", "reviewer2"))


def _check_and_wake(fabric: Fabric, rid: str, answers: str) -> tuple[dict[str, Any], Any]:
    _, children, ids = fabric.splits[-1]
    lease = _lease(ids[0], reuse_check.REUSE_KIND, "eq03", children[0].brief)
    checked = reuse_check.review_reuse(fabric, lease, key_id=REVIEWER_KEY, judge=_judge(answers))
    submitted = fabric.submits[-1]
    done = ChildResult(
        task_id=ids[0],
        state="done",
        ok=True,
        output=submitted["output"],
        receipt_hash=checked["receipt"],
        completed_by_key=REVIEWER_KEY,
    )
    woke = _planner(
        fabric, _lease(rid, "request", "eq01", _request_brief(NEAR_REQUEST), [done])
    ).run()
    return checked, woke


def test_an_approved_check_answers_the_request_from_the_library_then_it_closes() -> None:
    fabric = Fabric()
    rid, _ = _near_duplicate(fabric)
    checked, woke = _check_and_wake(fabric, rid, "yes")
    assert checked["status"] == "delivered" and checked["check"]["answers"] == "yes"
    assert checked["check"]["model"] == "muse-spark-1.3" and checked["check"]["why"]
    record = fabric.request(rid)
    assert woke["status"] == "closed" and record["status"] == "closed"
    assert record["parts"]["1"]["status"] == "delivered"
    assert record["parts"]["1"]["reused_from"]["key"] == "RPT-NEAR-01"
    assert record["parts"]["1"]["reuse_check"]["receipt"] == checked["receipt"]
    types = [e.get("type") for e in fabric.history(rid)]
    assert types.index("delivered") < types.index("closed")
    assert _kinds(fabric) == [[reuse_check.REUSE_KIND]]  # no other work was needed


@pytest.mark.parametrize("answers", ["no", "unsure"])
def test_a_check_that_says_no_or_is_unsure_has_new_work_planned(answers: str) -> None:
    fabric = Fabric()
    rid, _ = _near_duplicate(fabric)
    checked, woke = _check_and_wake(fabric, rid, answers)
    assert checked["status"] == "sent_back" and checked["reason"] == f"reuse_{answers}"
    assert woke["status"] == "split"
    assert _kinds(fabric) == [[reuse_check.REUSE_KIND], ["research", "report_review"]]
    record = fabric.request(rid)
    assert record["status"] == "open_for_build" and "reused_from" not in record
    first = record["occurrences"][0]
    assert first["status"] == "reuse_sent_back" and first["reuse_check"]["key"] == "RPT-NEAR-01"


def test_a_check_that_never_finished_is_recorded_and_new_work_is_planned() -> None:
    fabric = Fabric()
    rid, _ = _near_duplicate(fabric)
    _, _, ids = fabric.splits[-1]
    dead = ChildResult(task_id=ids[0], state="dead", ok=False, output=None, receipt_hash=None)
    woke = _planner(
        fabric, _lease(rid, "request", "eq01", _request_brief(NEAR_REQUEST), [dead])
    ).run()
    assert woke["status"] == "split" and _kinds(fabric)[-1] == ["research", "report_review"]
    verdicts = [e for e in fabric.history(rid) if e.get("type") == "reuse_checked"]
    assert verdicts and verdicts[-1]["verdict"] == "does_not_fit"
    assert (
        "did not finish" in verdicts[-1]["reason"]
        and verdicts[-1]["ref"] == "eranos.solutions/RPT-NEAR-01"
    )
    jsonschema.validate(verdicts[-1], EVENT_SCHEMA)


def test_the_key_that_proposed_a_reuse_may_not_check_it() -> None:
    fabric = Fabric()
    _near_duplicate(fabric)
    _, children, ids = fabric.splits[-1]
    lease = _lease(ids[0], reuse_check.REUSE_KIND, "eq03", children[0].brief)
    with pytest.raises(SelfReviewRefused):
        reuse_check.review_reuse(fabric, lease, key_id=PLANNER_KEY, judge=_judge("yes"))
    assert fabric.submits[-1]["ok"] is False


def test_a_library_answer_that_changed_or_lost_its_review_is_not_used() -> None:
    fabric = Fabric()
    _near_duplicate(fabric)
    fabric.result_views["review-RPT-NEAR-01"] = []  # Tessera no longer confirms the review
    _, children, ids = fabric.splits[-1]
    lease = _lease(ids[0], reuse_check.REUSE_KIND, "eq03", children[0].brief)
    called: list[str] = []

    def judge(question: str, library: dict[str, Any]) -> dict[str, Any]:
        called.append(question)
        return {"answers": "yes", "why": "", "model": "muse-spark-1.3"}

    out = reuse_check.review_reuse(fabric, lease, key_id=REVIEWER_KEY, judge=judge)
    assert out["status"] == "sent_back" and not called
    assert "cannot be confirmed" in out["check"]["why"]


def test_an_answer_without_a_clear_verdict_counts_as_unsure() -> None:
    assert reuse_check.read_judgment({"answers": "probably"})["answers"] == "unsure"
    assert reuse_check.read_judgment("yes")["answers"] == "unsure"
    assert reuse_check.read_judgment({"answers": " YES ", "why": "same"})["answers"] == "yes"


# 3. the recorded reopen ------------------------------------------------------------------------------
def _wrongly_reused(fabric: Fabric, rid: str) -> None:
    pointer = {
        "store": "eranos.solutions",
        "key": "RPT-RC676414-01",
        "version": 1,
        "score": 0.7143,
        "kind": "report",
    }
    events = [
        {"type": "received", "at": 1.0, "ref": rid},
        {
            "type": "delivered",
            "at": 2.0,
            "part": 1,
            "ref": "eranos.solutions/RPT-RC676414-01",
            "summary": {"reused": True, "score": 0.7143},
        },
        {"type": "closed", "at": 3.0, "receipt": "c" * 64},
    ]
    fabric.records[(REQUESTS_STORE, rid)] = [
        {
            "schema_version": 1,
            "request_id": rid,
            "status": "closed",
            "text": FILM_REQUEST,
            "output_type": "information",
            "frequency": "one-off",
            "reused_from": pointer,
            "close_receipt": "c" * 64,
            "parts": {"1": {"route": "reused", "status": "delivered", "reused_from": pointer}},
            "events": events,
            "event": events[-1],
        }
    ]


def _reopen(fabric: Fabric, rid: str) -> str:
    current = fabric.get_record(REQUESTS_STORE, rid)
    task_id = reuse_check.reopen_task_id(rid, 1)
    value = reuse_check.reopened_value(
        current.value,
        reason="The library answer did not fit this request.",
        n=1,
        task_id=task_id,
        finding="F-REUSE-001",
        at=time.time(),
    )
    fabric.put_record(REQUESTS_STORE, rid, value, expected_version=current.version)
    return task_id


def test_a_reopen_matches_the_request_pages_event_schema() -> None:
    fabric = Fabric()
    rid = "rq-wrongly-reused"
    _wrongly_reused(fabric, rid)
    task_id = _reopen(fabric, rid)
    record = fabric.request(rid)
    event = record["event"]
    jsonschema.validate(event, EVENT_SCHEMA)
    assert event["type"] == "reopened" and event["ref"] == task_id and event["reason"]
    assert record["status"] == "received" and record["parts"] == {}
    assert "reused_from" not in record and record["reuse_withdrawn"][0]["key"] == "RPT-RC676414-01"
    # The wrong reuse stays in the history: every earlier version and fact is still there.
    assert [e["type"] for e in fabric.history(rid)] == ["closed", "reopened"]
    assert [e["type"] for e in record["events"]] == ["received", "delivered", "closed", "reopened"]


def test_a_recorded_reopen_is_planned_again_as_new_work_on_the_same_request() -> None:
    fabric = Fabric()
    fabric.library_report("RPT-RC676414-01", IRS_REPORT)
    rid = "rq-wrongly-reused"
    _wrongly_reused(fabric, rid)
    task_id = _reopen(fabric, rid)
    brief = {**_request_brief(FILM_REQUEST), "reopens": rid, "reopen": 1}
    out = _planner(fabric, _lease(task_id, "request", "eq01", brief)).run()
    assert out["status"] == "split" and out["request_id"] == rid
    assert _kinds(fabric) == [["research", "report_review"]]
    record = fabric.request(rid)
    assert record["status"] == "open_for_build" and record["parts"]["1"]["route"] == "public-only"
    types = [e.get("type") for e in fabric.history(rid)]
    assert types[types.index("reopened") :][:3] == ["reopened", "plan_claimed", "planned"]
    assert (REQUESTS_STORE, task_id) not in fabric.records  # nothing went to a record of its own


def test_a_reopen_the_request_record_does_not_name_is_refused_and_writes_nothing() -> None:
    fabric = Fabric()
    rid = "rq-wrongly-reused"
    _wrongly_reused(fabric, rid)
    before = copy.deepcopy(fabric.records)
    forged = _lease(
        reuse_check.reopen_task_id(rid, 1),
        "request",
        "eq01",
        {
            **_request_brief("Anything at all, written by someone else."),
            "reopens": rid,
            "reopen": 1,
        },
    )
    with pytest.raises(reuse_check.ReopenRefused):
        _planner(fabric, forged)
    assert fabric.records == before


def test_a_request_whose_research_never_finished_can_be_reopened_as_new_work() -> None:
    """The annual and grantdl examples: closed with every part sent back, no result, no reuse."""
    fabric = Fabric()
    rid = "rq-closed-without-a-result"
    events = [
        {"type": "received", "at": 1.0, "ref": rid},
        {"type": "closed", "at": 3.0, "receipt": "c" * 64},
    ]
    fabric.records[(REQUESTS_STORE, rid)] = [
        {
            "schema_version": 1,
            "request_id": rid,
            "status": "closed",
            "text": NEAR_REQUEST,
            "output_type": "information",
            "frequency": "one-off",
            "parts": {"1": {"route": "public-only", "status": "needs_revision"}},
            "occurrences": [{"n": 1, "status": "finished", "children": ["t_old_0", "t_old_1"]}],
            "events": events,
            "event": events[-1],
        }
    ]
    task_id = _reopen(fabric, rid)
    record = fabric.request(rid)
    jsonschema.validate(record["event"], EVENT_SCHEMA)
    assert "wrong_reuse" not in record["event"]["summary"] and "reuse_withdrawn" not in record
    assert record["parts_before_reopen"][0]["parts"]["1"]["status"] == "needs_revision"
    brief = {**_request_brief(NEAR_REQUEST), "reopens": rid, "reopen": 1}
    out = _planner(fabric, _lease(task_id, "request", "eq01", brief)).run()
    assert out["status"] == "split" and _kinds(fabric) == [["research", "report_review"]]
    assert fabric.request(rid)["status"] == "open_for_build"


@pytest.mark.parametrize(
    ("answers", "verdict"), [("yes", "fits"), ("no", "does_not_fit"), ("unsure", "does_not_fit")]
)
def test_the_checker_writes_the_pages_reuse_checked_fact(
    tmp_path: Path, answers: str, verdict: str
) -> None:
    from eranos.pipeline import process as process_part
    from eranos.worker_loop import Worker, WorkerConfig

    fabric = Fabric()
    _near_duplicate(fabric)
    _, children, ids = fabric.splits[-1]
    lease = _lease(ids[0], reuse_check.REUSE_KIND, "eq03", children[0].brief)
    out = reuse_check.review_reuse(fabric, lease, key_id=REVIEWER_KEY, judge=_judge(answers))
    config = WorkerConfig(
        role="reviewer",
        label="dedicated-worker-3",
        tessera_url="http://127.0.0.1:9",
        key="x",
        key_id=REVIEWER_KEY,
        trace_path=str(tmp_path / "trace.jsonl"),
        dedicated=True,
        display_name="dedicated worker 3 (run by ta-amps)",
    )
    worker = Worker(
        config, backend=fabric, heartbeat_backend=object(), handler=process_part.StubHandler()
    )
    facts = worker.reuse_facts(lease, out, 1)
    checked = facts[0]
    jsonschema.validate(checked, EVENT_SCHEMA)
    assert checked["type"] == "reuse_checked" and checked["verdict"] == verdict
    assert checked["checker_role"] == "dedicated worker 3 (run by ta-amps)"
    assert checked["model"] == "muse-spark-1.3" and checked["similarity"] >= reuse.MIN_THRESHOLD
    assert checked["ref"] == "eranos.solutions/RPT-NEAR-01" and len(checked["receipt"]) == 64
    assert REVIEWER_KEY not in json.dumps(facts) and PLANNER_KEY not in json.dumps(facts)
    assert [f["type"] for f in facts] == (
        ["reuse_checked", "delivered"] if verdict == "fits" else ["reuse_checked"]
    )


# a storage error right after the split (the reviewer's R8) ---------------------------------------------
@pytest.mark.parametrize("where", ["plan_write", "plan_facts"])
@pytest.mark.parametrize("answers", ["yes", "no"])
def test_a_storage_error_after_the_split_never_closes_a_request_with_nothing(
    monkeypatch: pytest.MonkeyPatch, where: str, answers: str
) -> None:
    import eranos.pipeline.planner as planner_mod

    fabric = Fabric()
    fabric.library_report(
        "RPT-NEAR-01",
        {
            "report_id": "RPT-NEAR-01",
            "title": NEAR_QUESTION,
            "question": NEAR_QUESTION,
            "claims": IRS_REPORT["claims"],
        },
    )
    rid = "rq-cut-short"
    real_plan, real_facts = planner_mod._write_plan, Planner._facts
    broke = {"done": False}

    def flaky_plan(*a: Any, **k: Any) -> Any:
        if where == "plan_write" and not broke["done"]:
            broke["done"] = True
            raise RuntimeError("a made-up storage error after the split")
        return real_plan(*a, **k)

    def flaky_facts(self: Any, events: list[dict[str, Any]], **k: Any) -> Any:
        if (
            where == "plan_facts"
            and any(e.get("type") == "planned" for e in events)
            and not broke["done"]
        ):
            broke["done"] = True
            raise RuntimeError("a made-up storage error after the plan was written")
        return real_facts(self, events, **k)

    monkeypatch.setattr(planner_mod, "_write_plan", flaky_plan)
    monkeypatch.setattr(Planner, "_facts", flaky_facts)
    with pytest.raises(RuntimeError):
        _planner(fabric, _lease(rid, "request", "eq01", _request_brief(NEAR_REQUEST))).run()
    assert _kinds(fabric) == [[reuse_check.REUSE_KIND]]  # the split happened
    _, children, ids = fabric.splits[-1]
    if (
        where == "plan_write"
    ):  # the plan never named the check, so the reviewer refuses it (G1) and it dies
        child = ChildResult(
            task_id=ids[0],
            state="dead",
            ok=False,
            output={"node": reuse_check.REUSE_KIND, "status": "failed", "error": "NotInPlan"},
        )
        fabric.task = lambda task_id: SimpleNamespace(created_at=0.0, brief=children[0].brief)  # type: ignore[method-assign]
    else:  # the plan named it: the check runs
        lease = _lease(ids[0], reuse_check.REUSE_KIND, "eq03", children[0].brief)
        checked = reuse_check.review_reuse(
            fabric, lease, key_id=REVIEWER_KEY, judge=_judge(answers)
        )
        child = ChildResult(
            task_id=ids[0],
            state="done",
            ok=True,
            output=fabric.submits[-1]["output"],
            receipt_hash=checked["receipt"],
            completed_by_key=REVIEWER_KEY,
        )
    woke = _planner(
        fabric, _lease(rid, "request", "eq01", _request_brief(NEAR_REQUEST), [child])
    ).run()
    record = fabric.request(rid)
    if where == "plan_facts" and answers == "yes":
        assert woke["status"] == "closed" and record["parts"]["1"]["status"] == "delivered"
    else:  # never closed with no answer and no new work
        assert woke["status"] == "split" and _kinds(fabric)[-1] == ["research", "report_review"]
        assert record["status"] == "open_for_build"
        if where == "plan_write":  # no checker wrote a verdict, so the planner records does_not_fit
            verdicts = [e for e in fabric.history(rid) if e.get("type") == "reuse_checked"]
            assert verdicts and verdicts[-1]["verdict"] == "does_not_fit"
            assert verdicts[-1]["ref"] == "eranos.solutions/RPT-NEAR-01"
            jsonschema.validate(verdicts[-1], EVENT_SCHEMA)


# the review's F2, F3 and F4 ---------------------------------------------------------------------------
@pytest.mark.parametrize("who", ["planner", "proposer", "nobody"])
def test_an_accepted_check_counts_only_from_another_key(who: str) -> None:
    fabric = Fabric()
    rid, _ = _near_duplicate(fabric)
    _, children, ids = fabric.splits[-1]
    lease = _lease(ids[0], reuse_check.REUSE_KIND, "eq03", children[0].brief)
    checked = reuse_check.review_reuse(fabric, lease, key_id=REVIEWER_KEY, judge=_judge("yes"))
    key = {"planner": PLANNER_KEY, "proposer": PLANNER_KEY, "nobody": None}[who]
    done = ChildResult(
        task_id=ids[0],
        state="done",
        ok=True,
        output=fabric.submits[-1]["output"],
        receipt_hash=checked["receipt"],
        completed_by_key=key,
    )
    woke = _planner(
        fabric, _lease(rid, "request", "eq01", _request_brief(NEAR_REQUEST), [done])
    ).run()
    assert woke["status"] == "split" and _kinds(fabric)[-1] == ["research", "report_review"]


def test_an_accepted_check_about_another_answer_is_not_used() -> None:
    fabric = Fabric()
    rid, _ = _near_duplicate(fabric)
    _, children, ids = fabric.splits[-1]
    lease = _lease(ids[0], reuse_check.REUSE_KIND, "eq03", children[0].brief)
    checked = reuse_check.review_reuse(fabric, lease, key_id=REVIEWER_KEY, judge=_judge("yes"))
    output = {**fabric.submits[-1]["output"]}
    output["reused"] = {**output["reused"], "key": "RPT-SOMETHING-ELSE"}
    done = ChildResult(
        task_id=ids[0],
        state="done",
        ok=True,
        output=output,
        receipt_hash=checked["receipt"],
        completed_by_key=REVIEWER_KEY,
    )
    woke = _planner(
        fabric, _lease(rid, "request", "eq01", _request_brief(NEAR_REQUEST), [done])
    ).run()
    assert woke["status"] == "split"


def test_the_checks_reason_is_published_without_links_or_retired_words() -> None:
    from eranos.pipeline.plain_words import forbidden

    why = reuse_check.read_judgment(
        {
            "answers": "no",
            "why": "See https://example.org/x and www.example.com; the "
            + "synth"
            + "etic case differs.",
        }
    )["why"]
    # Links go; the retired word becomes plain words. The display layer filters everything else
    # through the shared list, which this repository does not copy.
    assert "http" not in why and "www." not in why and not forbidden(why) and "made-up" in why


def test_a_part_level_reuse_is_found_for_a_reopen() -> None:
    pointer = {"store": "eranos.solutions", "key": "RPT-X-01", "version": 2}
    value = {"parts": {"1": {"route": "reused", "status": "delivered", "reused_from": pointer}}}
    assert reuse_check.reused_pointer(value) == pointer
    assert reuse_check.reused_pointer({"reused_from": pointer, "parts": {}}) == pointer
    assert reuse_check.reused_pointer({"parts": {"1": {"route": "public-only"}}}) == {}


@pytest.mark.parametrize(
    "reason",
    [
        "Compare it with spam.xyz first.",
        "The news.info story differs.",
        "See bit.ly/abc123 for the rules.",
        "Ask in t.me/somegroup.",
        "It is on 192.168.1.10:8080/path today.",
        "Try hxxps://evil.example/x for more.",
        "The page at example dot org disagrees.",
        "Mail someone at user@example.com about it.",
    ],
)
def test_no_link_like_token_survives_in_the_published_reason(reason: str) -> None:
    import re

    why = reuse_check.read_judgment({"answers": "no", "why": reason})["why"]
    assert not re.search(
        r"://|@|\b\w+\.(?:xyz|info|ly|me|example|org|com)\b|\d+\.\d+\.\d+|\bdot org\b", why
    ), why


def test_a_plan_whose_record_keeps_failing_is_planned_again_three_times_then_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import eranos.pipeline.planner as planner_mod

    def always_fails(*a: Any, **k: Any) -> Any:
        raise RuntimeError("a made-up storage error, every time")

    fabric = Fabric()
    rid = "rq-never-recorded"
    monkeypatch.setattr(planner_mod, "_write_plan", always_fails)
    with pytest.raises(RuntimeError):
        _planner(fabric, _lease(rid, "request", "eq01", _request_brief(NEAR_REQUEST))).run()
    children: list[ChildResult] = []
    outcomes = []
    for _ in range(6):
        _, _, ids = fabric.splits[-1]
        children += [ChildResult(task_id=i, state="dead", ok=False, output=None) for i in ids]
        try:
            outcomes.append(
                _planner(
                    fabric,
                    _lease(rid, "request", "eq01", _request_brief(NEAR_REQUEST), list(children)),
                ).run()["status"]
            )
        except RuntimeError:
            outcomes.append("split, unrecorded")
        if outcomes[-1] == "closed":
            break
    assert outcomes[-1] == "closed" and len(fabric.splits) == 1 + planner_mod.MAX_UNRECORDED_REPLANS
    blocked = [e for e in fabric.history(rid) if e.get("type") == "blocked"]
    assert blocked and "could not be recorded" in blocked[-1]["findings"][0]


def test_reuse_brief_and_review_preserve_decisive_requirements_past_1200_chars(
    tmp_path: Path,
) -> None:
    from tessera import TesseraError

    from eranos.model_client import UsageMeter
    from eranos.pipeline import process as process_part
    from eranos.worker_loop import LeaseGate, Worker, WorkerConfig

    requirement = (
        "French labels are required for every equipment item; "
        "an English-only answer does not satisfy this request."
    )
    header = "Make an equipment-label checklist for an example workshop. "
    padding = "Use the same workshop equipment inventory and checklist context. "
    cases = [
        ("short_control", header + requirement),
        ("before_boundary", (header + padding * 40)[:1080] + requirement),
        ("after_boundary", (header + padding * 40)[:1210] + requirement),
    ]
    for name, full_text in cases:
        fabric = Fabric()
        rid = f"rq-reuse-boundary-{name}"
        fabric.records[(REQUESTS_STORE, rid)] = [
            {"status": "received", "text": full_text, "parts": {}}
        ]
        fabric.library_report("RPT-EQUIP-01", IRS_REPORT)
        actor = _planner(fabric, _lease(rid, "request", "eq01", _request_brief(full_text)))
        match = SimpleNamespace(
            store="eranos.solutions",
            key="RPT-EQUIP-01",
            version=1,
            score=0.9,
            kind="report",
            review_receipt=hashlib.sha256(b"RPT-EQUIP-01").hexdigest(),
            title="Example equipment report",
        )
        actor.check_reuse(match, {"best": {"score": 0.9}})
        _, children, ids = fabric.splits[-1]
        child_brief = children[0].brief
        assert requirement in child_brief["question"], name
        assert child_brief["question"] == full_text, name

        seen_questions: list[str] = []

        def capture_judge(
            question: str,
            library: dict[str, Any],
            bucket: list[str] = seen_questions,
        ) -> dict[str, Any]:
            bucket.append(question)
            return {"answers": "unsure", "why": "example judge abstains"}

        review_lease = _lease(ids[0], reuse_check.REUSE_KIND, "eq03", child_brief)
        res = reuse_check.review_reuse(
            fabric, review_lease, key_id=REVIEWER_KEY, judge=capture_judge
        )
        assert res["status"] == "sent_back"
        assert seen_questions == [full_text]

        # Even if an older in-flight brief was truncated at 1,200 chars, review_reuse restores full stored text.
        legacy_brief = {**child_brief, "question": full_text[:1200]}
        seen_legacy: list[str] = []

        def legacy_judge(
            q: str,
            lib: dict[str, Any],
            bucket: list[str] = seen_legacy,
        ) -> dict[str, Any]:
            bucket.append(q)
            return {"answers": "no", "why": "missing french"}

        reuse_check.review_reuse(
            fabric,
            _lease(f"{ids[0]}-legacy", reuse_check.REUSE_KIND, "eq03", legacy_brief),
            key_id=REVIEWER_KEY,
            judge=legacy_judge,
        )
        assert seen_legacy == [full_text]

        # If max_question_chars is smaller than the full request, review_reuse refuses silent truncation.
        if len(full_text) > 1200:
            truncated_res = reuse_check.review_reuse(
                fabric,
                _lease(f"{ids[0]}-cap", reuse_check.REUSE_KIND, "eq03", child_brief),
                key_id=REVIEWER_KEY,
                judge=lambda q, lib: {"answers": "yes", "why": "would wrongly close"},
                max_question_chars=1200,
            )
            assert truncated_res["status"] == "sent_back"
            assert "incomplete" in truncated_res["check"]["why"]

    # Volunteer reviewer hitting PermissionDenied on surface_only request record still gets full brief.question,
    # and Worker.check_reuse -> judge_user retains requirements past char 1,200 even if remote noun omits max_question_chars.
    after_text = cases[-1][1]
    fabric = Fabric()
    rid = "rq-worker-check-reuse"
    fabric.records[(REQUESTS_STORE, rid)] = [
        {"status": "received", "text": after_text, "parts": {}}
    ]
    fabric.library_report("RPT-EQUIP-01", IRS_REPORT)
    actor = _planner(fabric, _lease(rid, "request", "eq01", _request_brief(after_text)))
    match = SimpleNamespace(
        store="eranos.solutions",
        key="RPT-EQUIP-01",
        version=1,
        score=0.9,
        kind="report",
        review_receipt=hashlib.sha256(b"RPT-EQUIP-01").hexdigest(),
        title="Example equipment report",
    )
    actor.check_reuse(match, {"best": {"score": 0.9}})
    _, children, ids = fabric.splits[-1]
    child_brief = children[0].brief

    seen_prompts: list[str] = []

    class FakeMeta:
        def chat_json(self, system: str, user: str, **kwargs: Any) -> dict[str, Any]:
            seen_prompts.append(user)
            return {"answers": "unsure", "why": "abstain"}

    config = WorkerConfig(
        role="reviewer",
        label="dedicated-worker-3",
        tessera_url="http://127.0.0.1:9",
        key="x",
        key_id=REVIEWER_KEY,
        trace_path=str(tmp_path / "trace-worker.jsonl"),
        dedicated=True,
        display_name="dedicated worker 3 (run by ta-amps)",
    )
    worker = Worker(
        config, backend=fabric, heartbeat_backend=object(), handler=process_part.StubHandler()
    )
    remote_rules = dict(worker.rules())
    ((remote_rules.get("reuse") or {}).get("check") or {}).pop("max_question_chars", None)
    worker.rules = lambda: remote_rules  # type: ignore[method-assign]
    worker.meta = lambda _mid: FakeMeta()  # type: ignore[method-assign]

    rev_lease = _lease(ids[0], reuse_check.REUSE_KIND, "eq03", child_brief)
    gate = LeaseGate(fabric, rev_lease, lambda _out, _ok, _err: {})
    orig_read_req = reuse_check.read_request

    def deny_read_request(_b: Any, _rid: str) -> Any:
        raise TesseraError("surface_only")

    reuse_check.read_request = deny_read_request  # type: ignore[assignment]
    try:
        out = worker.check_reuse(gate, rev_lease, UsageMeter(), 1, rid)
    finally:
        reuse_check.read_request = orig_read_req  # type: ignore[assignment]
    assert out["status"] == "sent_back"
    assert len(seen_prompts) == 1
    parsed_user = json.loads(seen_prompts[0])
    assert parsed_user["request"] == after_text
    assert requirement in parsed_user["request"]


def test_a_report_taken_off_display_is_never_offered_again() -> None:
    rules = json.loads((ROOT / "instructions" / "worker.json").read_text())["reuse"]
    fabric = Fabric()
    fabric.library_report("RPT-RC676414-01", IRS_REPORT)
    assert any(c[1].key == "RPT-RC676414-01" for c in reuse.candidates(fabric, rules))
    gone = {**rules, "not_reused": ["RPT-RC676414-01"]}
    assert not any(c[1].key == "RPT-RC676414-01" for c in reuse.candidates(fabric, gone))


# A label on our own test requests must not decide a match (Nov 4: 0 of 200 answered from the library).
LABELED = "How can a health nonprofit run a vaccination event? Test run, Nov 4, our own example, not a real organization's request."
RULES_NOW = json.loads((ROOT / "instructions" / "worker.json").read_text())["reuse"]


@pytest.mark.parametrize(
    "text",
    [
        "How can a health nonprofit run a vaccination event?",
        "how can a health nonprofit run a vaccination event",
        "How can a health nonprofit run a vaccination event? Labeled gaps test, Nov 4, a repeat of an earlier question, our own, not a real organization's request.",
        "How can a health nonprofit run a vaccination event? Test run, Nov 4.",
        "Example request: How can a health nonprofit run a vaccination event? Final-read test run, second request, Nov 4.",
    ],
)
def test_labels_do_not_change_what_a_question_is(text: str) -> None:
    assert reuse.same_question(text, LABELED, RULES_NOW)
    assert reuse.terms(text, RULES_NOW) == reuse.terms(LABELED, RULES_NOW)


@pytest.mark.parametrize(
    "text",
    [
        "How can a health nonprofit run a vaccination event in Ohio?",
        "How do we test run a generator for a vaccination event?",
        "",
    ],
)
def test_other_words_are_another_question(text: str) -> None:
    assert not reuse.same_question(text, LABELED, RULES_NOW)


def test_a_label_alone_does_not_make_two_questions_alike() -> None:
    other = "How should a shelter respond to bed bugs? Test run, Nov 4, our own example, not a real organization's request."
    assert (
        reuse.similarity(reuse.terms(other, RULES_NOW), reuse.terms(LABELED, RULES_NOW))
        < RULES_NOW["threshold"]
    )


def _exact_setup(
    question: str, *, not_reused: list[str] | None = None
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    fabric = Fabric()
    report = {**IRS_REPORT, "question": LABELED, "title": "nonprofit: run a vaccination event"}
    fabric.library_report("RPT-SAME-01", report)
    rules = {**RULES_NOW, "not_reused": not_reused or []}
    considered: dict[str, Any] = {}
    match = reuse.find_reuse(
        fabric, question, rules, output_type="information", considered=considered
    )
    return fabric, {"match": match, "considered": considered}, rules


def test_a_short_exact_repeat_matches_though_it_has_few_distinctive_words() -> None:
    short = "Should a small nonprofit get an independent audit?"
    fabric = Fabric()
    fabric.library_report("RPT-AUDIT-01", {**IRS_REPORT, "question": short + " Test run, Nov 4."})
    assert len(reuse.terms(short, RULES_NOW)) < reuse.MIN_TERMS
    match = reuse.find_reuse(fabric, short, RULES_NOW, output_type="information")
    assert match is not None and match.key == "RPT-AUDIT-01"


def test_a_report_taken_off_display_is_not_reused_even_word_for_word() -> None:
    _, found, _ = _exact_setup(
        "How can a health nonprofit run a vaccination event?", not_reused=["RPT-SAME-01"]
    )
    assert found["match"] is None


def test_a_process_request_is_not_answered_by_a_report_with_the_same_words() -> None:
    fabric = Fabric()
    fabric.library_report("RPT-SAME-01", {**IRS_REPORT, "question": LABELED})
    assert reuse.find_reuse(fabric, LABELED, RULES_NOW, output_type="process") is None


def test_the_same_words_are_approved_by_the_other_key_with_no_model_call() -> None:
    fabric = Fabric()
    fabric.library_report("RPT-SAME-01", {**IRS_REPORT, "question": LABELED})
    match = reuse.find_reuse(
        fabric,
        "How can a health nonprofit run a vaccination event?",
        RULES_NOW,
        output_type="information",
    )
    assert match is not None
    pointer = {
        "store": match.store,
        "key": match.key,
        "version": match.version,
        "score": match.score,
        "kind": match.kind,
        "review_receipt": match.review_receipt,
        "title": match.title,
    }
    brief = reuse_check.reuse_brief(
        "rq-same",
        "How can a health nonprofit run a vaccination event?",
        {"output_type": "information"},
        pointer,
        proposed_by_key=PLANNER_KEY,
    )
    fabric.requests = getattr(fabric, "requests", {})

    def no_model(question: str, library: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("no model call for the same words")

    lease = _lease("t_same", reuse_check.REUSE_KIND, "eq03", brief)
    out = reuse_check.review_reuse(
        fabric, lease, key_id=REVIEWER_KEY, judge=no_model, reuse_rules=RULES_NOW
    )
    assert (
        out["check"]["answers"] == "yes"
        and out["check"]["model"] is None
        and out["check"]["cost_usd"] == 0.0
    )
    assert out["status"] == "delivered"


def test_the_proposing_key_still_may_not_approve_the_same_words() -> None:
    fabric = Fabric()
    fabric.library_report("RPT-SAME-01", {**IRS_REPORT, "question": LABELED})
    match = reuse.find_reuse(fabric, LABELED, RULES_NOW, output_type="information")
    assert match is not None
    pointer = {
        "store": match.store,
        "key": match.key,
        "version": match.version,
        "score": match.score,
        "kind": match.kind,
        "review_receipt": match.review_receipt,
        "title": match.title,
    }
    brief = reuse_check.reuse_brief(
        "rq-same", LABELED, {"output_type": "information"}, pointer, proposed_by_key=PLANNER_KEY
    )
    with pytest.raises(reuse_check.SelfReviewRefused):
        reuse_check.review_reuse(
            fabric,
            _lease("t_same", reuse_check.REUSE_KIND, "eq03", brief),
            key_id=PLANNER_KEY,
            judge=_judge("yes"),
            reuse_rules=RULES_NOW,
        )


@pytest.mark.parametrize(
    ("one", "two"),
    [
        (
            "Our town is in Ohio and we are not a real organization yet. How do we incorporate?",
            "Our town is in Texas and we are not a real organization yet. How do we incorporate?",
        ),
        (
            "Our shelter needs help. Test run, Nov 9 in Ohio, how many volunteers do we need?",
            "Our shelter needs help. Test run, Nov 9 in Texas, how many volunteers do we need?",
        ),
        ("Who regulates charities in \u65e5\u672c?", "Who regulates charities in \u4e2d\u56fd?"),
        ("Can we accept a gift of $500?", "Can we accept a gift of \u20ac500?"),
        ("Must we keep 5% aside?", "Must we keep 5 aside?"),
    ],
)
def test_a_place_or_an_amount_stays_part_of_the_question(one: str, two: str) -> None:
    assert not reuse.same_question(one, two, RULES_NOW)


def test_a_report_taken_off_after_the_check_was_queued_is_not_approved() -> None:
    fabric = Fabric()
    fabric.library_report("RPT-SAME-01", {**IRS_REPORT, "question": LABELED})
    match = reuse.find_reuse(fabric, LABELED, RULES_NOW, output_type="information")
    assert match is not None
    pointer = {
        "store": match.store,
        "key": match.key,
        "version": match.version,
        "score": match.score,
        "kind": match.kind,
        "review_receipt": match.review_receipt,
        "title": match.title,
    }
    brief = reuse_check.reuse_brief(
        "rq-same", LABELED, {"output_type": "information"}, pointer, proposed_by_key=PLANNER_KEY
    )
    out = reuse_check.review_reuse(
        fabric,
        _lease("t_same", reuse_check.REUSE_KIND, "eq03", brief),
        key_id=REVIEWER_KEY,
        judge=_judge("yes"),
        reuse_rules={**RULES_NOW, "not_reused": ["RPT-SAME-01"]},
    )
    assert out["status"] == "sent_back"
