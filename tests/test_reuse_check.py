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
