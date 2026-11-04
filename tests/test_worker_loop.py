"""The volunteer worker loop: unit checks, then whole flows against a local Tessera on workerd.

Made-up samples only (SYNTHETIC test fixtures): the public-rules page and the model are test stand-ins. The integration tests
need ERANOS_WORKERD_TESSERA (a Tessera checkout with node_modules) and are skipped without it.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import pytest
from support.workerd_fabric import (
    RULES_HTML,
    RULES_URL,
    FakeModel,
    available,
    fixture_fetcher,
    local_tessera,
)

from eranos.jsonfile import load_json
from eranos.pipeline import process as process_part
from eranos.pipeline.planner import request_terms
from eranos.pipeline.research import check_claims
from eranos.pipeline.reuse import find_reuse, score, terms
from eranos.sources import SourcePolicy, SourceRefused, check_address, extract_text
from eranos.worker_loop import Pacer, Worker, WorkerConfig

ROOT = Path(__file__).resolve().parents[1]
RULES = load_json(ROOT / "instructions" / "worker.json")
TUNING = load_json(ROOT / "instructions" / "worker.policy.json")
INFO_TEXT = "Summarize the tax law rules on political campaign activity for 501(c)(3) charities, with a citation for every point."
REWORDED = "Our charity needs a cited overview of what the rules say about 501(c)(3) groups and political campaigns."


# unit checks ------------------------------------------------------------------------------------
def test_empty_claim_waits_a_minute_or_the_servers_retry_after() -> None:
    pacer = Pacer(60.0)
    assert pacer.ready("eq02", 0.0)
    assert pacer.empty("eq02", 100.0, 5.0) == 160.0
    assert not pacer.ready("eq02", 159.0) and pacer.ready("eq02", 160.0)
    assert pacer.empty("eq02", 200.0, 90.0) == 320.0  # still empty: twice as long (120 s)
    assert (
        pacer.empty("eq02", 400.0, 5.0) == 640.0 and pacer.empty("eq02", 700.0, 5.0) == 1000.0
    )  # capped at 300 s
    assert pacer.refused("eq02", 300.0, 30.0) == 330.0
    pacer.worked("eq02", 400.0)
    assert pacer.ready("eq02", 400.0)


def test_worker_claims_at_most_once_per_minute_on_an_empty_queue(tmp_path: Path) -> None:
    class Empty:
        calls = 0

        def claim_with_hint(
            self, queue: str, worker: str, *, kinds: list[str]
        ) -> tuple[None, float, int]:
            Empty.calls += 1
            return None, 5.0, 60

    now = [1000.0]
    config = WorkerConfig(
        role="planner",
        label="t",
        tessera_url="http://127.0.0.1:9",
        key="x",
        key_id="k_test",
        trace_path=str(tmp_path / "t.jsonl"),
    )
    worker = Worker(
        config, backend=Empty(), heartbeat_backend=object(), handler=object(), clock=lambda: now[0]
    )
    outcomes = []
    for step in range(0, 125, 5):
        now[0] = 1000.0 + step
        outcomes.append(worker.run_once())
    assert Empty.calls == 2  # at t=0 and t=60; the next waits 120 s (idle backoff)
    assert outcomes.count("empty") == 2 and outcomes.count("paced") == len(outcomes) - 2
    log = [json.loads(line) for line in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert [e["event"] for e in log] == ["claim_empty"] * 2


def test_html_text_drops_scripts_and_keeps_sentences_whole() -> None:
    title, text = extract_text("text/html; charset=utf-8", RULES_HTML.encode())
    assert title.startswith("Made-up rules page")
    assert "tracking" not in text
    assert (
        "a charity registered under section 501(c)(3) may not take part in any political campaign"
        in text
    )
    _, flat = extract_text(
        "application/json", json.dumps({"results": [{"title": "A", "abstract": "B c."}]}).encode()
    )
    assert flat == "A\nB c."


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/x",
        "https://127.0.0.1/x",
        "https://localhost/x",
        "https://user:pw@example.org/",
        "https://example.org:8443/",
    ],
)
def test_only_public_https_addresses_are_fetched(url: str) -> None:
    with pytest.raises(SourceRefused):
        check_address(url, SourcePolicy())


def test_reworded_request_matches_and_an_unrelated_one_does_not() -> None:
    rules = RULES["reuse"]
    stored = terms(
        INFO_TEXT + " Under these rules a charity may not take part in a political campaign.", rules
    )
    assert score(terms(REWORDED, rules), stored) >= rules["threshold"]
    assert (
        score(
            terms("Clean our volunteer sign-up spreadsheets and remove duplicate rows.", rules),
            stored,
        )
        < rules["threshold"]
    )


def test_claims_keep_only_verbatim_quotes_that_support_them() -> None:
    source = {
        "id": "SRC-1",
        "text": "A charity may hold nonpartisan voter registration drives when the drives do not favor any candidate.",
    }
    sentences = [{"id": "S1-1", "source": "SRC-1", "text": source["text"]}]
    proposed = {
        "claims": [
            {
                "sentence": "S1-1",
                "quote": source["text"],
                "claim": "A charity may hold nonpartisan voter registration drives.",
            },
            {
                "sentence": "S1-1",
                "quote": "A charity may hold partisan rallies for a candidate.",
                "claim": "Rallies are fine.",
            },
            {
                "sentence": "S1-1",
                "quote": source["text"],
                "claim": "Charities must pay a large federal penalty every year.",
            },
            {"sentence": "S9-9", "quote": source["text"], "claim": "x"},
        ]
    }
    kept, dropped = check_claims(proposed, sentences, [source], RULES)
    assert [c["text"] for c in kept] == [
        "A charity may hold nonpartisan voter registration drives."
    ]
    assert {d["reason"].split(":")[0] for d in dropped} == {
        "the claim says more than its quote",
        "names no numbered sentence",
    }
    assert kept[0]["citations"][0]["quote"] == source["text"]  # copied by code, never typed


ABSTRACTS = {
    "results": [
        {
            "title": "Notice of Funding Opportunity: Emergency Food Assistance Program",
            "abstract": (
                "The Department announces the availability of funds for the Emergency Food Assistance Program for fiscal year 2027, "
                "which supports food banks and food pantries that distribute commodities to households with low incomes. "
                "Eligible applicants include State agencies that administer the program and that partner with local emergency feeding "
                "organizations, including food banks and food pantries operated by nonprofit organizations. "
                "Applications must be submitted electronically by the closing date listed in this notice, and late applications "
                "will not be considered for funding under this announcement."
            ),
        }
    ]
}


def test_long_abstract_claims_get_their_quote_copied_from_the_cited_sentence() -> None:
    import json as _json

    from eranos.pipeline.research import candidate_sentences
    from eranos.sources import Fetched, source_record

    raw = _json.dumps(ABSTRACTS).encode()
    fetched = Fetched(
        "https://www.federalregister.gov/api/v1/documents.json?x",
        "https://www.federalregister.gov/api/v1/documents.json?x",
        200,
        "application/json",
        raw,
        time.time(),
    )
    record = source_record(
        fetched,
        source_id="SRC-1",
        access="official_api",
        publisher="Federal Register",
        max_text_chars=60000,
        request_id="r",
        part=1,
    )
    question = "List new federal grant funding notices relevant to food banks and food pantries."
    sentences = candidate_sentences([record], question, 30)
    assert len(sentences) >= 3
    proposed = {
        "claims": [  # paraphrased claims; the model's own quote is wrong or missing
            {
                "sentence": s["id"],
                "quote": "not what the source says",
                "claim": s["text"].split(",")[0],
            }
            for s in sentences
        ]
    }
    kept, _ = check_claims(proposed, sentences, [record], RULES)
    assert len(kept) >= 3
    assert all(c["citations"][0]["quote"] in record["text"] for c in kept)


def test_a_retried_research_verb_samples_differently_and_says_so() -> None:
    from types import SimpleNamespace

    from eranos.model_client import UsageMeter as Meter
    from eranos.pipeline import research

    part = {"part": 1, "route": "public-only", "text": INFO_TEXT, "legal": True}
    guardrails = load_json(ROOT / "instructions" / "public-research.json")
    brief = research.research_brief("rq-retry", part, "Food bank", guardrails, RULES, [RULES_URL])

    class Store:
        def get_record(self, *a: Any) -> Any:
            from tessera import NotFound

            raise NotFound("none")

        def put_record(
            self, store: str, key: str, value: Any, *, expected_version: int, **kw: Any
        ) -> Any:
            return SimpleNamespace(version=expected_version + 1)

    for attempt, hot in ((1, False), (2, True)):
        model, meter = FakeModel(bad=False), Meter()
        research.do_research(
            Store(),
            SimpleNamespace(brief=brief, attempt=attempt),
            fetcher=fixture_fetcher({RULES_URL: RULES_HTML}),
            model=model,
            meter=meter,
            worker_rules=RULES,
        )
        temperature, seed = model.sampling
        assert (temperature > 0) is hot and seed == 20261031 + attempt - 1
        assert meter.model_report()["sampling"] == [{"temperature": temperature, "seed": seed}]


def test_an_operator_rerun_plans_a_parked_occurrence_now() -> None:
    from types import SimpleNamespace

    from eranos.pipeline.planner import Planner

    lease = SimpleNamespace(
        task_id="rq-rec",
        brief={"text": INFO_TEXT, "frequency": "recurring", "cadence": "monthly"},
        inputs=[{"rerun": True, "by": "operator"}],
        children=[],
        claimed_at=0,
        claim_receipt="r",
        expires_at=0,
    )
    nouns = {"worker": RULES, "classify": load_json(ROOT / "instructions" / "classify.json")}

    class NoRecords:
        def get_record(self, *a: Any) -> Any:
            from tessera import NotFound

            raise NotFound("none")

    planner = Planner(NoRecords(), lease, worker="dedicated worker 1 (run by ta-amps)", nouns=nouns)
    facts: list[Any] = []
    planner._facts = lambda events, **kw: facts.extend(events)  # type: ignore[method-assign]
    planner.plan = lambda occurrence, reuse: {"planned": occurrence}  # type: ignore[method-assign]
    planner.park = lambda *a, **k: {"parked": True}  # type: ignore[method-assign]
    latest = {"n": 1, "status": "scheduled", "next_at": time.time() + 86400, "park": 1}
    assert planner.wake(latest) == {"planned": 2}
    assert facts and facts[0]["type"] == "queued" and facts[0]["summary"]["rerun"] is True
    lease.inputs = [{"timed_out": True}]
    assert planner.wake(latest) == {"parked": True}  # without a re-run, an early wake waits again


def test_example_kits_are_rewritten_in_plain_words_and_still_verify() -> None:
    from eranos.pipeline import load_example_bundles
    from eranos.pipeline.plain_words import PRACTICE_MARK, forbidden, plain
    from eranos.schemas import KitDraft
    from eranos.tracks import get_track
    from eranos.verifier import verify_kit

    bundles = load_example_bundles()
    assert len(bundles) == 14
    for bundle in bundles:
        draft = KitDraft.model_validate(
            {**plain(bundle["draft"]), "drafted_by": "check-drafter", "drafted_by_key": "k_check"}
        )
        report = verify_kit(draft, get_track(draft.track_id))
        assert report.passed, (draft.kit_id, report.issues)
        assert not forbidden(draft.model_dump(mode="json")) and not forbidden(
            report.model_dump(mode="json")
        )
        assert all(PRACTICE_MARK in fx.sample_input for fx in draft.fixtures)


def test_request_terms_bound_the_recurring_period() -> None:
    assert request_terms(
        {"output_type": "information", "frequency": "recurring", "cadence": "monthly"}, RULES
    ) == {
        "output_type": "information",
        "frequency": "recurring",
        "cadence": "monthly",
        "period_s": 2592000,
    }
    assert request_terms({"frequency": "recurring", "period_s": 5}, RULES)["period_s"] == 900
    assert request_terms({"output_type": "anything"}, RULES) == {}


# whole flows on a local Tessera (workerd) ------------------------------------------------------------
needs_workerd = pytest.mark.skipif(
    not available(), reason="set ERANOS_WORKERD_TESSERA to a Tessera checkout with node_modules"
)


@pytest.fixture
def fabric(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """A fresh local Tessera per test, so no test claims another test's verbs."""
    noun = {
        **RULES,
        "recurring": {**RULES["recurring"], "min_period_seconds": 2},
        "dedicated": {**RULES["dedicated"], "grace_seconds": 3},
    }
    with local_tessera(tmp_path_factory.mktemp("workerd"), worker_noun=noun) as running:
        yield running


# The request-status page's event types (docs/status-events.schema.json at the redesign's 2a1510b,
# plus `reopened` from the Eranos web commit 59c932c and `reuse_checked` from 2dce2dd).
SCHEMA_TYPES = {
    "reopened",
    "reuse_checked",
    "received",
    "plan_claimed",
    "plan_released",
    "planned",
    "blocked",
    "queued",
    "work_claimed",
    "work_released",
    "work_submitted",
    "check_claimed",
    "in_review",
    "check_approved",
    "check_sent_back",
    "check_refused",
    "signoff_required",
    "signed_off",
    "delivered",
    "published",
    "library_added",
    "decided",
    "heartbeat",
    "closed",
    "withdrawn",
}
PUBLIC_STORES = (
    "eranos.requests",
    "eranos.plans",
    "eranos.solutions",
    "eranos.processes",
    "eranos.process_templates",
)


def assert_nothing_public_says_synthetic(fabric: Any, task_ids: list[str]) -> None:
    """The owner's rules: no public record, status fact or execution report says "synthetic", and
    none names the old open-weights family the workers no longer run."""
    seen = []
    for store in PUBLIC_STORES:
        for record in fabric.get(f"/v1/stores/{store}/records?limit=200")["records"]:
            if record.get("visibility_scope") == "public_commons":
                seen.append(json.dumps(record["value"]))
    for task_id in task_ids:
        seen += [json.dumps(r) for r in _executions(fabric, task_id)]
    assert seen
    for text in seen:
        found = re.search("synthetic|(?<!o)llama", text, re.IGNORECASE)
        assert not found, text[max(0, found.start() - 200) : found.end() + 100] if found else ""


def _record(fabric: Any, request_id: str) -> dict[str, Any]:
    return dict(fabric.get(f"/v1/stores/eranos.requests/records/{request_id}")["value"])


def _types(record: dict[str, Any]) -> list[str]:
    return [e["type"] for e in record.get("events") or [] if e["type"] != "heartbeat"]


def _executions(fabric: Any, task_id: str) -> list[dict[str, Any]]:
    runs = fabric.get(f"/v1/tasks/{task_id}/executions?limit=10")["executions"]
    return [fabric.get(f"/v1/executions/{r['run_id']}") for r in runs]


def _workers(fabric: Any, *, model: Any = None, handler: Any = None) -> dict[str, Worker]:
    fetcher = fixture_fetcher({RULES_URL: RULES_HTML})
    return {
        "planner": fabric.worker("planner", handler=handler),
        "builder": fabric.worker(
            "builder", model=model or FakeModel(), fetcher=fetcher, handler=handler
        ),
        "reviewer": _reviewer(fabric, fetcher=fetcher, handler=handler),
    }


def _reviewer(fabric: Any, name: str = "reviewer", **kwargs: Any) -> Worker:
    """A reviewer with a process handler starts only with the builder keys it trusts."""
    from unittest import mock

    keys = {process_part.BUILDER_KEYS_ENV: fabric.keys["builder"]["key_id"]}
    with mock.patch.dict(os.environ, keys):
        return fabric.worker(name, **kwargs)


@needs_workerd
def test_information_request_is_claimed_worked_reviewed_and_delivered(fabric: Any) -> None:
    requester = fabric.requester()
    rid = fabric.file_request(
        requester,
        {
            "text": INFO_TEXT,
            "links": [RULES_URL],
            "organization_type": "Legal-aid clinic",
            "output_type": "information",
            "frequency": "one-off",
        },
        "info1",
    )
    w = _workers(fabric)
    plain = Path(fabric.trace_dir) / "workers.plain.log"
    for role in (
        "planner",
        "builder",
        "reviewer",
    ):  # one shared plain log, as the live units write it
        w[role].config.plain_log = str(plain)
    assert w["planner"].run_once() == "worked"
    plan = fabric.get(f"/v1/stores/eranos.plans/records/{rid}")["value"]
    assert [p["route"] for p in plan["parts"]] == ["public-only"]
    assert w["builder"].run_once() == "worked"
    assert w["reviewer"].run_once() == "worked"
    assert w["planner"].run_once() == "worked"

    record = _record(fabric, rid)
    assert record["status"] == "closed"
    assert _types(record) == [
        "received",
        "plan_claimed",
        "planned",
        "queued",
        "work_claimed",
        "work_submitted",
        "check_claimed",
        "check_approved",
        "delivered",
        "library_added",
        "plan_claimed",
        "closed",
    ]
    assert all(e.get("receipt") or e.get("ref") for e in record["events"])
    # The page reads the history: every version after the first carries one event, of its own types.
    history = fabric.get(f"/v1/stores/eranos.requests/records/{rid}/history")["versions"]
    carried = [h["value"]["event"]["type"] for h in history if "event" in h["value"]]
    assert carried == _types(record) and set(carried) <= SCHEMA_TYPES
    added = next(e for e in record["events"] if e["type"] == "library_added")
    assert added["library_ref"].endswith(
        f"/api/nouns/eranos.solutions/{plan['parts'][0]['report_id']}"
    )
    claimed = next(e for e in record["events"] if e["type"] == "work_claimed")
    names = {"muse-spark-1.3": "Muse Spark 1.3", "muse-wonder-1.0": "Muse Wonder 1.0"}
    variants = {v["id"]: v for v in TUNING["variants"]}
    assert claimed["worker"] == "test-builder" and claimed["lease_ends"] > claimed["at"]
    check_claim = next(e for e in record["events"] if e["type"] == "check_claimed")
    for step, pick in (("make", claimed), ("check", check_claim)):
        # Every pick is recorded: the model id, its catalog name, the variant, its persona, the
        # tuner version, the share it was drawn at and why; the harness is named apart.
        chosen = variants[pick["variant"]]
        assert chosen["step"] == step and pick["model"] == chosen["model"]
        assert pick["model_display"] == names[pick["model"]]  # from the models.meta noun
        assert pick["persona"] == chosen["persona"]["title"] and pick["harness"] == "eranos-worker"
        assert pick["tuner_version"] == 0 and pick["probability"] == round(1 / 3, 4)
        assert "starting mix" in pick["why"]
    approved = next(e for e in record["events"] if e["type"] == "check_approved")
    assert approved["tuning"]["maker_variant"] == claimed["variant"]
    assert approved["tuning"]["unsupported"] == []
    # The plain log reads as plain steps, with no ids, keys or hashes (the film's C2 shot).
    lines = [line.split("  ", 1)[1] for line in plain.read_text().splitlines()]
    steps = [line.split(" · ", 1)[1] for line in lines]
    assert any(
        t.startswith(
            f"claimed a research Task · {claimed['model_display']} · persona {claimed['persona']}"
        )
        for t in steps
    )
    assert any(t.startswith("fetched 1 public source · ") for t in steps)
    assert "claimed a request to plan · deterministic planner (no model)" in steps
    assert "its own checks passed · reported: submitted for an independent check" in steps
    assert any(t.startswith("claimed a check Task · ") for t in steps)
    assert "checks passed · reported: delivered to the requester" in steps
    assert not re.search(r"[0-9a-f]{12,}|\bt_[0-9a-f]|rq-|k_|https?://", plain.read_text())

    part = plan["parts"][0]
    solution = fabric.get(f"/v1/stores/eranos.solutions/records/{part['report_id']}")["value"]
    claims = solution["report"]["claims"]
    assert len(claims) >= 3 and solution["made_up_sample"] is False
    _, page = extract_text("text/html", RULES_HTML.encode())
    assert all(c["citations"][0]["quote"] in page for c in claims)
    assert "not legal advice" in solution["report"]["disclaimer"]

    work = fabric.get(f"/v1/tasks/{part['work_task_id']}/results")["results"][-1]
    review = fabric.get(f"/v1/tasks/{part['review_task_id']}/results")["results"][-1]
    assert work["output"]["report"]["stages"]["dropped"], "the builder dropped the invented quote"
    assert solution["report"]["stages"]["reviewed"]["kept"] == len(claims)
    assert work["completed_by_key"] == fabric.keys["builder"]["key_id"]
    assert (
        review["completed_by_key"] == fabric.keys["reviewer"]["key_id"] != work["completed_by_key"]
    )
    report = _executions(fabric, part["work_task_id"])[0]["report"]
    assert report["model"]["id"] == "muse-spark-1.3" and report["usage"]["total_tokens"] > 0
    assert report["model"]["tier"] == "standard" and report["model"]["cost_usd"] == 0.0123
    assert report["harness"]["declared_model"] == claimed["model"]
    assert report["harness"]["variant"] == claimed["variant"] and report["harness"]["why"]
    assert report["harness"]["cost_usd"] == 0.0123 and report["harness"]["role"] == "builder"
    assert report["harness"]["payer"] == "the owner's Meta API credit (standard tier)"
    review_report = _executions(fabric, part["review_task_id"])[0]["report"]
    assert review_report["harness"]["variant"].startswith("check-")
    assert review_report["usage"]["total_tokens"] > 0  # the model check
    # The approval carries the shape Tessera's eq03 rule checks, and the server accepted it (M2).
    assert review["ok"] is True and review["output"]["approved"] is True
    assert review["output"]["drafter_key_id"] == work["completed_by_key"]
    assert solution["report"]["title"] == plan["parts"][0]["text"] or solution["report"][
        "title"
    ].startswith("Legal-aid clinic:")
    assert_nothing_public_says_synthetic(
        fabric, [part["work_task_id"], part["review_task_id"], rid]
    )


@needs_workerd
def test_reworded_repeat_is_answered_from_the_library_only_after_another_keys_check(
    fabric: Any,
) -> None:
    """F-REUSE-001: a reuse match queues one check on eq03 and no research; a reviewer's key (not
    the planner's) approves it with a model, and only then is the request answered and closed."""
    if not fabric.get("/v1/stores/eranos.solutions/records?limit=5")["records"]:
        test_information_request_is_claimed_worked_reviewed_and_delivered(fabric)
    before = fabric.get("/v1/counts")
    requester = fabric.requester()
    rid = fabric.file_request(
        requester,
        {
            "text": REWORDED,
            "links": [],
            "organization_type": "Food pantry",
            "output_type": "information",
            "frequency": "one-off",
        },
        "info2",
    )
    w = _workers(fabric)
    assert w["planner"].run_once() == "worked"
    after = fabric.get("/v1/counts")
    assert sum(after["queues"]["eq02"].values()) == sum(before["queues"]["eq02"].values())
    assert sum(after["queues"]["eq03"].values()) == sum(before["queues"]["eq03"].values()) + 1
    plan = fabric.get(f"/v1/stores/eranos.plans/records/{rid}")["value"]
    check_id = plan["parts"][0]["review_task_id"]
    assert plan["parts"][0]["route"] == "reuse_check" and _record(fabric, rid)["status"] != "closed"
    assert w["reviewer"].run_once() == "worked"
    assert w["planner"].run_once() == "worked"
    record = _record(fabric, rid)
    assert record["status"] == "closed" and record["parts"]["1"]["status"] == "delivered"
    assert record["parts"]["1"]["reused_from"]["store"] == "eranos.solutions"
    types = _types(record)
    assert types[-5:] == ["check_claimed", "reuse_checked", "delivered", "plan_claimed", "closed"]
    assert set(_types(record)) <= SCHEMA_TYPES
    checked = next(e for e in record["events"] if e["type"] == "reuse_checked")
    assert checked["verdict"] == "fits" and checked["model"] == "muse-spark-1.3"
    assert checked["ref"].startswith("eranos.solutions/") and checked["similarity"] >= 0.8
    delivered = next(e for e in record["events"] if e["type"] == "delivered")
    assert delivered["summary"]["reused"] is True
    check = [r for r in fabric.get(f"/v1/tasks/{check_id}/results")["results"] if r["ok"]][-1]
    assert check["output"]["accepted"] is True and "approved" not in check["output"]
    assert check["completed_by_key"] != fabric.keys["planner"]["key_id"]
    task = fabric.get(f"/v1/tasks/{rid}")
    assert task["state"] == "done" and task["pending_children"] == 0
    planner_report = _executions(fabric, rid)[0]["report"]
    assert planner_report["model"] is None and planner_report["usage"]["total_tokens"] == 0
    check_report = _executions(fabric, check_id)[0]["report"]
    assert check_report["usage"]["total_tokens"] > 0  # the reuse check called a model


@needs_workerd
def test_process_request_waits_for_a_real_handler_and_the_stub_never_claims_it(fabric: Any) -> None:
    requester = fabric.requester()
    rid = fabric.file_request(
        requester,
        {
            "text": "A reusable process to clean our volunteer sign-up spreadsheets: remove duplicates, fix date formats and flag missing contact fields, with a short report.",
            "links": [],
            "organization_type": "Food pantry",
            "output_type": "process",
            "frequency": "one-off",
        },
        "proc1",
    )
    w = _workers(fabric)
    assert w["planner"].run_once() == "worked"
    part = fabric.get(f"/v1/stores/eranos.plans/records/{rid}")["value"]["parts"][0]
    assert part["route"] == "process"
    assert w["builder"].run_once() == "empty"  # the stub does not claim what it cannot build
    assert fabric.get(f"/v1/tasks/{part['work_task_id']}")["state"] == "ready"
    assert not fabric.get(f"/v1/tasks/{part['work_task_id']}/results")["results"]
    record = _record(fabric, rid)
    assert record["status"] == "open_for_build" and "work_failed" not in _types(record)


HANDLER_FILE = """
import os, hashlib, json
from pathlib import Path
name = "test handler (a test we wrote)"

def expected_records(request, plan_part):
    rid, part = request["request_id"], int(plan_part["part"])
    kit = "PRC-TEST" + "%04d" % (sum(map(ord, rid)) % 10000) + "-%02d" % part
    return {"kit_id": kit, "pack_id": "data-cleaning", "request_id": rid, "part": part,
            "catalog_record": {"store": "eranos.processes", "key": f"{rid}.{part}.{kit}"},
            "task_template_record": {"store": "eranos.process_templates", "key": f"{rid}.{part}.data-cleaning"},
            "listed_catalog_record": {"store": "eranos.catalog", "key": kit}}

def record_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

def build_process(request, plan_part):
    ids = expected_records(request, plan_part)
    return {"bundle_path": os.environ["TEST_BUNDLE"],
            "catalog_record": {**ids["catalog_record"], "value": {"title": "Made-up sample data-cleaning process", "request_text": request.get("text")}},
            "task_template_record": {**ids["task_template_record"], "value": {"kind": "run_process", "pack": "data-cleaning"}},
            "test_report": {"passed": True, "tests": 4, "issues": [], "pack_id": "data-cleaning"}}

def review_process(package, request, plan_part, *, bundle_path=None, records=None, builder_key_id=None, trusted_builder_keys=None):
    if bundle_path is None or not trusted_builder_keys:
        return {"passed": False, "checks": ["no bundle_path or no trusted builder keys: fail closed"]}
    data = Path(bundle_path).read_bytes()
    writers = {name: (rec or {}).get("owner_key_id") for name, rec in (records or {}).items()}
    checks = ["the bundle matches its digest" if hashlib.sha256(data).hexdigest() == package["blob_sha256"] else "MISMATCH",
              "no worker key in the review environment" if "TESSERA_KEY" not in os.environ else "LEAKED KEY",
              "reviewed the reviewer's own copy" if str(bundle_path) != os.environ.get("TEST_BUNDLE") else "BUILDER PATH",
              "the build's key is a trusted builder" if builder_key_id in trusted_builder_keys else "UNTRUSTED BUILDER",
              "both drafts were written by the build's key" if set(writers.values()) == {builder_key_id} else "OTHER WRITER"]
    verified = {name: {"value_sha256": record_digest(rec["value"])} for name, rec in (records or {}).items()}
    # Rebuilt from the bundle and the request, never copied from the drafts.
    verified["catalog_value"] = {"title": "Made-up sample data-cleaning process", "request_id": request["request_id"]}
    verified["template_value"] = {"kind": "run_process", "pack": "data-cleaning"}
    return {"passed": not any(c.isupper() for c in checks), "checks": checks, "verified": verified}
"""


@needs_workerd
def test_process_request_with_a_handler_is_built_reviewed_and_published(
    fabric: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle" / "bundle.tgz"
    bundle.parent.mkdir()
    bundle.write_bytes(b"made-up sample process bundle")
    handler_path = tmp_path / "handler.py"
    handler_path.write_text(HANDLER_FILE)
    monkeypatch.setenv("TEST_BUNDLE", str(bundle))
    monkeypatch.setenv("TESSERA_KEY", "tsk_must_never_reach_package_code")
    handler = process_part.load_handler(str(handler_path))
    requester = fabric.requester()
    rid = fabric.file_request(
        requester,
        {
            "text": "A reusable process to merge our made-up shift lists and flag gaps.",
            "links": [],
            "organization_type": "Food pantry",
            "output_type": "process",
            "frequency": "one-off",
        },
        "proc2",
    )
    w = _workers(fabric, handler=handler)
    for role in ("planner", "builder", "reviewer", "planner"):
        outcome = w[role].run_once()
        if outcome != "worked":
            part = fabric.get(f"/v1/stores/eranos.plans/records/{rid}")["value"]["parts"][0]
            results = fabric.get(f"/v1/tasks/{part['work_task_id']}/results")["results"]
            reviews = fabric.get(f"/v1/tasks/{part['review_task_id']}/results")["results"]
            pytest.fail(
                f"{role}: {outcome}; build {[(r['ok'], r['error']) for r in results]}; review {[(r['ok'], r['error']) for r in reviews]}"
            )
    record = _record(fabric, rid)
    assert _types(record)[-5:] == [
        "check_approved",
        "published",
        "library_added",
        "plan_claimed",
        "closed",
    ]
    ids = handler.expected_records({"request_id": rid}, {"part": 1})
    stored = fabric.get(f"/v1/stores/eranos.processes/records/{ids['catalog_record']['key']}")
    assert stored["visibility_scope"] == "public_commons" and stored["value"]["review_receipt"]
    part = fabric.get(f"/v1/stores/eranos.plans/records/{rid}")["value"]["parts"][0]
    review = fabric.get(f"/v1/tasks/{part['review_task_id']}/results")["results"][-1]
    assert review["output"]["approved"] is True and review["output"]["publication_sha256"]
    assert "no worker key in the review environment" in review["output"]["checks"]
    assert "reviewed the reviewer's own copy" in review["output"]["checks"]
    assert "both drafts were written by the build's key" in review["output"]["checks"]
    assert_nothing_public_says_synthetic(
        fabric, [part["work_task_id"], part["review_task_id"], rid]
    )


B4_HANDLER = os.environ.get("ERANOS_PROCESS_HANDLER", "")
FILM_REQUEST = (
    "A reusable process to clean our volunteer sign-up spreadsheets: remove duplicates, fix date and phone "
    "formats, flag missing contact fields, with a short report."
)
FILM_REWORDED = (
    "We need something reusable that tidies our volunteer registration sheets: get rid of double entries, "
    "standardize the dates and phone numbers, and point out anyone missing an email or phone, plus a brief summary."
)


@needs_workerd
@pytest.mark.skipif(
    not Path(B4_HANDLER).is_file(),
    reason="set ERANOS_PROCESS_HANDLER to build B4's eranos_handler.py",
)
def test_film_data_cleaning_request_is_built_reviewed_published_and_reused(
    fabric: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The film's request end to end with B4's real handler (adapted from its reference branch):
    claim, build, a different key's review in a clean process, published and listed; then a
    reworded request is answered from the stored package after another key's reuse check."""
    monkeypatch.setenv("B4_OUT_DIR", str(tmp_path / "b4"))
    handler = process_part.load_handler(B4_HANDLER)
    requester = fabric.requester()
    terms = {
        "links": [],
        "organization_type": "Volunteer center",
        "output_type": "process",
        "frequency": "one-off",
    }
    rid = fabric.file_request(requester, {"text": FILM_REQUEST, **terms}, "film1")
    w = _workers(fabric, handler=handler)
    for role in ("planner", "builder", "reviewer", "planner"):
        outcome = w[role].run_once()
        if outcome != "worked":
            part = fabric.get(f"/v1/stores/eranos.plans/records/{rid}")["value"]["parts"][0]
            results = fabric.get(f"/v1/tasks/{part['work_task_id']}/results")["results"]
            reviews = fabric.get(f"/v1/tasks/{part['review_task_id']}/results")["results"]
            pytest.fail(
                f"{role}: {outcome}; build {[(r['ok'], r['error']) for r in results]}; review {[(r['ok'], (r['output'] or {}).get('findings')) for r in reviews]}"
            )
    record = _record(fabric, rid)
    part = fabric.get(f"/v1/stores/eranos.plans/records/{rid}")["value"]["parts"][0]
    assert _types(record)[-5:] == [
        "check_approved",
        "published",
        "library_added",
        "plan_claimed",
        "closed",
    ], _types(record)
    output = [
        r for r in fabric.get(f"/v1/tasks/{part['work_task_id']}/results")["results"] if r["ok"]
    ][-1]["output"]
    approval = [
        r for r in fabric.get(f"/v1/tasks/{part['review_task_id']}/results")["results"] if r["ok"]
    ][-1]["output"]
    assert (
        approval["status"] == "approved"
        and approval["drafter_key_id"] != approval["reviewer_key_id"]
    )
    assert output["catalog_record"]["key"].startswith(f"{rid}.1.")
    catalog = fabric.get(f"/v1/stores/eranos.catalog/records/{output['draft']['kit_id']}")
    value = catalog["value"]
    assert (
        catalog["visibility_scope"] == "public_commons"
        and value["review_receipt"]
        and "status:verified" in value["tags"]
    )
    assert value["reviewed_by_key"] != value["kit"]["drafted_by_key"]
    assert (
        any(t.startswith("reuse:") for t in value["tags"])
        and "synthetic" not in json.dumps(value).lower()
    )
    reused = fabric.file_request(requester, {"text": FILM_REWORDED, **terms}, "film2")
    for role in ("planner", "reviewer", "planner"):  # the match, the reuse check, the close
        assert w[role].run_once() == "worked", role
    plan = fabric.get(f"/v1/stores/eranos.plans/records/{reused}")["value"]
    assert plan["parts"][0]["route"] == "reuse_check"
    again = _record(fabric, reused)
    assert again["status"] == "closed" and again["parts"]["1"]["status"] == "published"
    assert (
        plan["parts"][0]["reused_from"]["key"] == output["draft"]["kit_id"]
        and plan["parts"][0]["reused_from"]["score"] == 1.0
    )
    report = output["test_report"]
    assert report.get("model_calls") == 0  # the handler builds from fixed templates (FB1-020)
    assert_nothing_public_says_synthetic(
        fabric, [part["work_task_id"], part["review_task_id"], rid, reused]
    )
    if os.environ.get("B4_E2E_EVIDENCE"):  # B4's film evidence, as its branch records it
        again = _record(fabric, reused)
        evidence = {
            "request_events": [
                e["type"] for e in record.get("events") or [] if e["type"] != "heartbeat"
            ],
            "bundle_sha256": output["bundle_sha256"],
            "bundle_bytes": output["bundle_bytes"],
            "build_checks": {k: v.get("passed") for k, v in report["checks"].items()},
            "build_tests": report["tests"],
            "model_calls": report.get("model_calls"),
            "pieces": [(p["piece_id"], p["depends_on"], p["claimed_by"]) for p in report["pieces"]],
            "approval": {
                k: approval.get(k)
                for k in (
                    "status",
                    "drafter_key_id",
                    "reviewer_key_id",
                    "kit_id",
                    "draft_sha256",
                    "publication_sha256",
                    "checks",
                )
            },
            "catalog": {
                "key": output["draft"]["kit_id"],
                "version": catalog["version"],
                "tags": catalog["tags"],
                "value_tags": value["tags"],
                "review_receipt": value["review_receipt"],
            },
            "reuse": {
                "request_events": [
                    e["type"] for e in again.get("events") or [] if e["type"] != "heartbeat"
                ],
                "reused_from": plan["parts"][0]["reused_from"],
            },
        }
        Path(os.environ["B4_E2E_EVIDENCE"]).write_text(
            json.dumps(evidence, indent=1) + "\n", encoding="utf-8"
        )


@needs_workerd
def test_volunteers_get_first_pick_and_a_dedicated_worker_claims_after_the_grace_period(
    fabric: Any,
) -> None:
    from eranos.contributor import OpenSession

    requester = fabric.requester()
    brief = {
        "text": INFO_TEXT,
        "links": [RULES_URL],
        "organization_type": "Legal-aid clinic",
        "output_type": "information",
        "frequency": "one-off",
    }
    first = fabric.file_request(requester, brief, "grace1")
    planner = fabric.worker("planner")
    assert planner.run_once() == "worked"
    dedicated = fabric.worker(
        "builder",
        model=FakeModel(),
        fetcher=fixture_fetcher({RULES_URL: RULES_HTML}),
        dedicated=True,
        number=2,
    )
    assert dedicated.run_once() == "grace"  # inside the grace period: the dedicated worker waits
    volunteer = OpenSession(fabric.url, label="volunteer-in-test")
    volunteer.open()
    claimed = volunteer.claim(kinds=["research"])
    assert claimed.status_code == 200  # the volunteer's claim wins
    time.sleep(3.2)
    dedicated.pacer.next_at.clear()
    assert (
        dedicated.run_once() == "empty"
    )  # the volunteer holds it, so the dedicated worker backs off
    volunteer.close()
    second = fabric.file_request(
        requester, {**brief, "text": INFO_TEXT + " Second copy for the test."}, "grace2"
    )
    planner.pacer.next_at.clear()
    assert planner.run_once() == "worked"
    dedicated.pacer.next_at.clear()
    assert dedicated.run_once() == "grace"
    time.sleep(3.2)
    dedicated.pacer.next_at.clear()
    assert dedicated.run_once() == "worked"  # nobody else came: the dedicated worker takes it
    claim = next(e for e in _record(fabric, second)["events"] if e["type"] == "work_claimed")
    assert (
        claim["worker"] == "dedicated worker 2 (run by ta-amps)"
        and claim["worker_kind"] == "dedicated"
        and claim["run_by"] == "ta-amps"
    )
    # The pick is drawn from the tuning mix: whichever variant it is, it is recorded in full.
    variant = {v["id"]: v for v in TUNING["variants"]}[claim["variant"]]
    assert claim["model"] == variant["model"] and claim["dedicated"] is True
    names = {"muse-spark-1.3": "Muse Spark 1.3", "muse-wonder-1.0": "Muse Wonder 1.0"}
    assert claim["model_display"] == names[claim["model"]] and claim["harness"] == "eranos-worker"
    assert first != second


@needs_workerd
def test_a_volunteer_researches_at_once_under_its_own_label_key_and_model(fabric: Any) -> None:
    from eranos.worker_keys import issue_key

    with fabric.http() as http:
        fabric.keys["volunteer"] = issue_key(http, fabric.admin, "volunteer", days=1)
    requester = fabric.requester()
    rid = fabric.file_request(
        requester,
        {
            "text": INFO_TEXT,
            "links": [RULES_URL],
            "organization_type": "Legal-aid clinic",
            "output_type": "information",
            "frequency": "one-off",
        },
        "vol1",
    )
    fetcher = fixture_fetcher({RULES_URL: RULES_HTML})
    assert fabric.worker("planner").run_once() == "worked"
    dedicated = fabric.worker(
        "builder", model=FakeModel(), fetcher=fetcher, dedicated=True, number=2
    )
    assert dedicated.run_once() == "grace"  # the dedicated worker gives volunteers first pick
    volunteer = fabric.worker(
        "volunteer",
        role="builder",
        volunteer=True,
        model=FakeModel(model_id="muse-spark-1.3"),
        fetcher=fetcher,
    )
    assert volunteer.claim_kinds() == ["research"]
    assert volunteer.run_once() == "worked"  # no grace period: it claims at once
    assert _reviewer(fabric, fetcher=fetcher).run_once() == "worked"

    record = _record(fabric, rid)
    claim = next(e for e in record["events"] if e["type"] == "work_claimed")
    assert (claim["worker"], claim["worker_kind"], claim["dedicated"]) == (
        "a volunteer's AI",
        "volunteer",
        False,
    )
    assert (claim["model"], claim["model_display"], claim["harness"]) == (
        "muse-spark-1.3",
        "Muse Spark 1.3",
        "eranos-worker",
    )
    assert claim["persona"] and claim["variant"].startswith(
        "make-spark-"
    )  # model and persona recorded
    assert "delivered" in _types(record)
    approved = next(e for e in record["events"] if e["type"] == "check_approved")
    assert approved["worker"] == "test-reviewer"
    part = fabric.get(f"/v1/stores/eranos.plans/records/{rid}")["value"]["parts"][0]
    work = fabric.get(f"/v1/tasks/{part['work_task_id']}/results")["results"][-1]
    assert work["completed_by_key"] == fabric.keys["volunteer"]["key_id"]
    report = _executions(fabric, part["work_task_id"])[0]["report"]
    assert report["harness"]["worker_kind"] == "volunteer"
    assert report["harness"]["declared_model"] == "muse-spark-1.3"
    assert report["harness"]["payer"].startswith("spare Meta API credit given by the volunteer")
    assert_nothing_public_says_synthetic(
        fabric, [part["work_task_id"], part["review_task_id"], rid]
    )


@needs_workerd
def test_the_hourly_tuner_reads_recorded_outcomes_and_writes_the_next_mix(fabric: Any) -> None:
    requester = fabric.requester()
    fabric.file_request(
        requester,
        {
            "text": INFO_TEXT,
            "links": [RULES_URL],
            "organization_type": "Legal-aid clinic",
            "output_type": "information",
            "frequency": "one-off",
        },
        "tune1",
    )
    w = _workers(fabric)
    assert [w[r].run_once() for r in ("planner", "builder", "reviewer")] == ["worked"] * 3
    planner = fabric.worker("planner", dedicated=True, number=1)
    planner.ensure_tune()  # the dedicated planner queues this hour's tuner task, once
    deadline = time.time() + 20
    while True:
        planner.pacer.next_at.clear()
        ran = planner.run_once() == "worked"
        if ran and planner._tuning is not None and planner._tuning[1] > 0:
            break
        assert time.time() < deadline, "the tuner task never ran"
        time.sleep(0.5)
    saved = fabric.get("/v1/stores/eranos.instructions/records/worker.policy")
    value = saved["value"]
    assert saved["version"] >= 1 and value["tuner_version"] == 1
    assert value["inputs"]["outcomes"] >= 1  # the make outcome of the request above, at least
    assert abs(sum(value["mix"]["make"].values()) - 1) < 1e-3 and value["summary"]["mix"]["make"]
    ran = [e for e in _trace(planner) if e["event"] == "tuned"]
    assert ran and ran[-1]["tuner_version"] == 1


def _trace(worker: Worker) -> list[dict[str, Any]]:
    path = Path(worker.config.trace_path)
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


ANNUAL_PAGES = {
    page[
        "url"
    ]: f"""<!doctype html><html><head><title>Made-up filing page {n}, a test we wrote</title></head><body>
<h1>Practice page used only in tests</h1>
<p>Under these made-up rules, a small tax-exempt nonprofit files an annual return with the IRS each year.</p>
<p>Under these made-up rules, an organization with small gross receipts may file the Form 990-N electronic postcard.</p>
<p>Under these made-up rules, an organization that does not file an annual return for three years loses its exemption.</p>
<p>Under these made-up rules, larger organizations file Form 990-EZ or Form 990 instead of the postcard.</p>
</body></html>"""
    for n, page in enumerate(RULES["sources"]["official_pages"], start=1)
}


@needs_workerd
def test_a_research_task_that_uses_the_topics_official_pages_is_delivered(fabric: Any) -> None:
    """Review B1 of 4c509ee: the official pages a topic brings in pass the report's own checks."""
    requester = fabric.requester()
    rid = fabric.file_request(
        requester,
        {
            "text": "Which annual return must a small tax-exempt nonprofit file with the IRS (Form 990-N, 990-EZ or 990)?",
            "links": [],
            "organization_type": "Small nonprofit",
            "output_type": "information",
            "frequency": "one-off",
        },
        "annual1",
    )
    fetcher = fixture_fetcher(ANNUAL_PAGES)
    planner = fabric.worker("planner")
    builder = fabric.worker("builder", model=FakeModel(bad=False), fetcher=fetcher)
    reviewer = _reviewer(fabric, fetcher=fetcher)
    assert [w.run_once() for w in (planner, builder, reviewer)] == ["worked"] * 3
    assert "delivered" in _types(_record(fabric, rid))
    part = fabric.get(f"/v1/stores/eranos.plans/records/{rid}")["value"]["parts"][0]
    solution = fabric.get(f"/v1/stores/eranos.solutions/records/{part['report_id']}")["value"]
    sources = solution["report"]["sources"]
    assert {s["url"] for s in sources} <= set(ANNUAL_PAGES) and sources
    assert {s["access"] for s in sources} == {"public_web_page"}


@needs_workerd
def test_recurring_request_is_parked_for_its_period_and_planned_again(fabric: Any) -> None:
    requester = fabric.requester()
    rid = fabric.file_request(
        requester,
        {
            "text": INFO_TEXT,
            "links": [RULES_URL],
            "organization_type": "Legal-aid clinic",
            "output_type": "information",
            "frequency": "recurring",
            "period_s": 3,
        },
        "rec1",
    )
    w = _workers(fabric)
    receipts = []
    for occurrence in (1, 2):
        for role in ("planner", "builder", "reviewer", "planner"):
            assert w[role].run_once() == "worked", (occurrence, role)
        record = _record(fabric, rid)
        assert record["occurrences"][-1]["status"] == "scheduled"
        receipts.append([e["receipt"] for e in record["events"] if e["type"] == "delivered"][-1])
        time.sleep(3.5)
        fabric.reap()
    assert receipts[0] != receipts[1]
    assert [o["n"] for o in _record(fabric, rid)["occurrences"]] == [1, 2]


@needs_workerd
def test_a_key_that_researched_a_report_can_never_approve_it(fabric: Any) -> None:
    with fabric.http() as http:
        from eranos.worker_keys import ROLE_KEYS, issue_key

        ROLE_KEYS["both"] = {
            "queues": ["eq02", "eq03"],
            "kinds": ["research", "report_review"],
            "role": "builder",
        }
        try:
            fabric.keys["both"] = issue_key(http, fabric.admin, "both", days=1)
        finally:
            ROLE_KEYS.pop("both")
    requester = fabric.requester()
    rid = fabric.file_request(
        requester,
        {
            "text": INFO_TEXT,
            "links": [RULES_URL],
            "organization_type": "Legal-aid clinic",
            "output_type": "information",
            "frequency": "one-off",
        },
        "self1",
    )
    fetcher = fixture_fetcher({RULES_URL: RULES_HTML})
    assert fabric.worker("planner").run_once() == "worked"
    builder = fabric.worker("both", role="builder", model=FakeModel(), fetcher=fetcher)
    reviewer = fabric.worker("both", role="reviewer", fetcher=fetcher)
    assert builder.run_once() == "worked"
    assert reviewer.run_once() == "worked"
    part = fabric.get(f"/v1/stores/eranos.plans/records/{rid}")["value"]["parts"][0]
    review = fabric.get(f"/v1/tasks/{part['review_task_id']}/results")["results"][-1]
    assert review["ok"] is False and "may not review" in review["error"]
    assert reviewer.stats["failed"] == 1 and "check_refused" in _types(_record(fabric, rid))
    other = fabric.worker(
        "reviewer2", fetcher=fetcher
    )  # a different key may, once the retry is due
    deadline = time.time() + 10
    while other.run_once() != "worked":
        assert time.time() < deadline, "the refused review was never offered again"
        time.sleep(0.3)
    assert "delivered" in _types(_record(fabric, rid))


@needs_workerd
def test_a_lost_lease_is_recorded_as_a_failure(fabric: Any) -> None:
    requester = fabric.requester()
    rid = fabric.file_request(
        requester,
        {
            "text": INFO_TEXT,
            "links": [RULES_URL],
            "organization_type": "Legal-aid clinic",
            "output_type": "information",
            "frequency": "one-off",
        },
        "lost1",
    )
    assert fabric.worker("planner").run_once() == "worked"
    part = fabric.get(f"/v1/stores/eranos.plans/records/{rid}")["value"]["parts"][0]

    class Cancelling(FakeModel):
        def chat_json(self, system: str, user: str, **kwargs: Any) -> dict[str, Any]:
            with fabric.http() as http:  # an operator cancels the verb while it is being worked
                http.post(
                    "/v1/tasks/cancel",
                    json={"task_id": part["work_task_id"], "reason": "a test we wrote"},
                    headers={"authorization": f"Bearer {fabric.admin}", "x-namespace": "main"},
                ).raise_for_status()
            return super().chat_json(system, user, **kwargs)

    builder = fabric.worker(
        "builder", model=Cancelling(), fetcher=fixture_fetcher({RULES_URL: RULES_HTML})
    )
    assert builder.run_once() == "worked"
    assert builder.stats["lost"] == 1 and builder.stats["failed"] == 1
    log = [json.loads(line) for line in Path(builder.config.trace_path).read_text().splitlines()]
    failed = [
        e for e in log if e["event"] == "lease_failed" and e["task_id"] == part["work_task_id"]
    ]
    assert failed and "lease was lost" in failed[-1]["error"]
    assert "work_released" in _types(_record(fabric, rid))


@needs_workerd
def test_an_empty_hosted_style_claim_returns_the_servers_retry_after(fabric: Any) -> None:
    client = fabric.client("reviewer2")
    lease, retry_after, beat = client.claim_with_hint(
        "eq03", "test-reviewer2", kinds=["nothing_waiting"]
    )
    assert lease is None and retry_after >= 5 and beat == 60
    client.close()


def test_find_reuse_requires_a_review_receipt_that_tessera_confirms() -> None:
    from types import SimpleNamespace

    class Record:
        def __init__(self, key: str, value: dict[str, Any]) -> None:
            self.key, self.value, self.version = key, value, 1

    class Backend:
        def list_records(self, store: str, limit: int) -> list[Record]:
            if store != "eranos.solutions":
                return []
            report = {"title": "Made-up rules", "question": INFO_TEXT, "claims": []}
            return [
                Record("RPT-unreviewed", {"report": report}),
                Record(
                    "RPT-claimed",
                    {"report": report, "review_receipt": "f" * 64, "review_task_id": "t-forged"},
                ),
                Record(
                    "RPT-reviewed",
                    {"report": report, "review_receipt": "r" * 64, "review_task_id": "t-review"},
                ),
            ]

        def results(self, task_id: str) -> list[Any]:
            if task_id != "t-review":
                return []
            return [SimpleNamespace(receipt_hash="r" * 64, ok=True, output={"approved": True})]

    match = find_reuse(Backend(), REWORDED, RULES["reuse"], output_type="information")
    assert match is not None and match.key == "RPT-reviewed"


def test_a_source_digest_is_not_mistaken_for_a_card_number() -> None:
    from eranos.pipeline.solutions import report_findings

    text = "A charity may hold nonpartisan voter registration drives when the drives do not favor any candidate."
    source = {
        "id": "SRC-1",
        "url": RULES_URL,
        "access": "public_web_page",
        "public": True,
        "text": text,
    }
    digest = "1234567890123" + "a" * 51
    report = {
        "report_id": "RPT-1",
        "sources": [{**{k: v for k, v in source.items() if k != "text"}, "text_sha256": digest}],
        "claims": [
            {
                "id": "C1",
                "text": "Voter registration drives are allowed.",
                "citations": [{"source": "SRC-1", "quote": text}],
            }
        ],
        "decision": "A person decides what to do with this result.",
    }
    brief = {
        "report_id": "RPT-1",
        "sources": [source],
        "guardrails": load_json(ROOT / "instructions" / "public-research.json"),
    }
    assert report_findings(report, brief) == []
    report["sources"][0]["note_sha256"] = "card 4111 1111 1111 1111"
    assert any("payment card" in f for f in report_findings(report, brief))


@needs_workerd
def test_an_example_kit_is_rebuilt_in_plain_words_through_the_queues(fabric: Any) -> None:
    from tessera.client import Client

    from eranos.pipeline import load_example_bundles
    from eranos.pipeline.plain_words import PRACTICE_MARK
    from eranos.pipeline.run import submit_kit_request
    from eranos.schemas import KitRequest
    from eranos.worker_keys import issue_key
    from eranos.worker_loop import WorkerClient

    with fabric.http() as http:
        intake = issue_key(http, fabric.admin, "kit-intake", days=1)
    client = Client(
        fabric.url, key=intake["key"], surface_id="eranos", namespace="main", max_retries=0
    )

    class QueuesExist:  # the queues exist already; this key may only queue kit verbs
        def __getattr__(self, name: str) -> Any:
            return getattr(client, name)

        def define_queue(self, *_: Any, **__: Any) -> None:
            return None

    bundle = next(b for b in load_example_bundles() if b["request"]["kit_id"] == "KIT-SHIFT-05")
    submit_kit_request(QueuesExist(), KitRequest.model_validate(bundle["request"]))
    workers = {
        "planner": fabric.worker("planner"),
        "builder": fabric.worker("builder"),
        "reviewer": fabric.worker("reviewer"),
    }
    for role in ("planner", "builder", "reviewer"):
        assert workers[role].run_once() == "worked", role
    value = fabric.get("/v1/stores/eranos.catalog/records/KIT-SHIFT-05")["value"]
    assert value["review_receipt"] and value["reviewer_key_id"] == fabric.keys["reviewer"]["key_id"]
    assert value["drafter_key_id"] == fabric.keys["builder"]["key_id"] != value["reviewer_key_id"]
    assert not re.search("synthetic", json.dumps(value), re.IGNORECASE)
    assert all(PRACTICE_MARK in fx["sample_input"] for fx in value["kit"]["fixtures"])
    nobody = WorkerClient(
        fabric.url, key=intake["key"], surface_id="eranos", namespace="main", max_retries=0
    )
    with pytest.raises(Exception, match=r"(?i)scope|forbidden|may not"):
        nobody.claim_with_hint(
            "eq01", "intake", kinds=["spec"]
        )  # the intake key queues; it never claims
    client.close()
    nobody.close()


# The film's food-safety request (lead, Nov 2): official food-safety pages, not the Federal Register alone.
FOOD_REQUEST = (
    "What are the key food-safety rules for a community food pantry, with a source for every point?"
)


def _food_page(title: str, sentences: list[str]) -> str:
    body = "".join(f"<p>{s}</p>" for s in sentences)
    return f"<!doctype html><html><head><title>{title}</title></head><body><h1>Made-up page used only in tests</h1>{body}</body></html>"


FOOD_PAGES = {
    "https://www.fda.gov/food/buy-store-serve-safe-food/safe-food-handling": _food_page(
        "Made-up safe food handling page",
        [
            "Under these made-up food safety rules, a food pantry keeps cold food at or below 40 degrees.",
            "A food pantry washes hands and surfaces before it handles food, under these made-up rules.",
            "These made-up food safety rules say a pantry keeps raw meat apart from ready-to-eat food.",
        ],
    ),
    "https://www.epa.gov/sustainable-management-food/food-donation-basics": _food_page(
        "Made-up food donation page",
        [
            "Under these made-up rules, a food pantry that takes donated food in good faith is protected from liability.",
            "These made-up rules were updated in 2022 so a food pantry may give donated food at a small cost.",
            "A food pantry that follows these made-up food safety rules keeps a record of donated food.",
        ],
    ),
    "https://www.fda.gov/food/retail-food-protection/fda-food-code": _food_page(
        "Made-up food code page",
        [
            "This made-up food code is a model, and each state writes its own food safety rules from it.",
            "Under this made-up food code, a food pantry checks the dates on food before it hands food out.",
            "Local health departments inspect a food pantry under these made-up food safety rules.",
        ],
    ),
    "https://www.fda.gov/consumers/consumer-updates/are-you-storing-food-safely": _food_page(
        "Made-up food storage page",
        [
            "These made-up food safety rules say a pantry freezer keeps food at 0 degrees.",
            "A food pantry throws out food that has been left out for more than two hours, under these made-up rules.",
            "Under these made-up rules, a food pantry stores dry food off the floor.",
        ],
    ),
    "https://www.cdc.gov/food-safety/prevention/index.html": _food_page(
        "Made-up food poisoning page",
        [
            "Under these made-up food safety rules, a food pantry cleans, separates, cooks and chills food.",
            "A food pantry asks sick volunteers not to handle food, under these made-up rules.",
            "These made-up food safety rules say a pantry cooks food to a safe temperature.",
        ],
    ),
}


def test_food_safety_requests_use_the_official_food_pages_and_cite_every_point() -> None:
    from eranos.pipeline import research

    brief = research.research_brief(
        "rq-food",
        {"part": 1, "route": "public-only", "legal": False, "text": FOOD_REQUEST},
        "Nonprofit",
        load_json(ROOT / "instructions" / "public-research.json"),
        RULES,
        [],
    )
    ids = [p["id"] for p in brief["fetch"]["pages"]]
    assert set(ids) >= {
        "food-fda-safe-handling",
        "food-epa-donation-basics",
        "food-fda-food-code",
        "food-fda-storing",
        "food-cdc-prevention",
    }
    assert not any(i.startswith("irs-") for i in ids)
    assert all(
        p["access"] == "public_web_page" and p["url"].startswith("https://www.")
        for p in brief["fetch"]["pages"]
    )
    first_five = [u for u, _, _ in research.permitted_urls(brief)][: brief["fetch"]["max_sources"]]
    assert "https://www.epa.gov/sustainable-management-food/food-donation-basics" in first_five
    assert all(p.get("caveat") for p in brief["fetch"]["pages"])


@needs_workerd
def test_a_food_safety_information_request_is_delivered_with_a_source_for_every_claim(
    fabric: Any,
) -> None:
    requester = fabric.requester()
    rid = fabric.file_request(
        requester,
        {"text": FOOD_REQUEST, "links": [], "output_type": "information", "frequency": "one-off"},
        "food1",
    )
    fetcher = fixture_fetcher(FOOD_PAGES)
    w = {
        "planner": fabric.worker("planner"),
        "builder": fabric.worker("builder", model=FakeModel(bad=False), fetcher=fetcher),
        "reviewer": _reviewer(fabric, fetcher=fetcher),
    }
    for role in ("planner", "builder", "reviewer", "planner"):
        assert w[role].run_once() == "worked", role
    record = _record(fabric, rid)
    assert record["status"] == "closed" and record["parts"]["1"]["status"] == "delivered"
    plan = fabric.get(f"/v1/stores/eranos.plans/records/{rid}")["value"]
    report_id = plan["parts"][0]["report_id"]
    report = fabric.get(f"/v1/stores/eranos.solutions/records/{report_id}")["value"]["report"]
    urls = {s["url"] for s in report["sources"]}
    assert urls and urls <= set(FOOD_PAGES), urls
    sources = {s["id"]: s for s in report["sources"]}
    assert len(report["claims"]) >= 3
    for claim in report["claims"]:
        citation = claim["citations"][0]
        assert citation["source"] in sources and citation["quote"]
        assert citation["quote"] in FOOD_PAGES[sources[citation["source"]]["url"]]
    assert "state and local health departments" in report["summary"]


# The review's T2 and T3: the food pages go only to requests about food, and come first for them.
UNRELATED_TO_FOOD = {
    "stock or vehicle gift": "What are the legal requirements for accepting a donation of stock or a vehicle?",
    "in-kind donations": "How do we acknowledge in-kind donations for tax purposes?",
    "volunteer liability": "What liability protections do volunteers have under federal law?",
    "youth program safety": "What safety rules apply to volunteers working at a youth program?",
    "Internal Revenue Code": "What does the Internal Revenue Code say about private inurement for 501(c)(3) organizations?",
    "event permits": "What permits do we need for a street fair fundraiser?",
    "data handling": "What are the federal rules for data handling and breach notices at a nonprofit?",
    "records storing": "What rules apply to storing client records and how long must we keep them?",
    "cloud storage": "What cloud storage security rules apply to nonprofits?",
    "separate bank account": "Do we need a separate bank account for restricted grants?",
    "sick leave": "What are the rules for sick leave for nonprofit employees?",
    "thrift store": "What retail sales tax rules apply when a nonprofit runs a thrift store?",
    "building inspection": "What is required for a building inspection of our community center?",
    "animal rescue": "What are federal rules for animal rescue nonprofits?",
    "surplus property": "How can a nonprofit get surplus federal property?",
}


def _brief_for(text: str) -> dict[str, Any]:
    from eranos.pipeline import research

    return research.research_brief(
        "rq-topics",
        {"part": 1, "route": "public-only", "legal": False, "text": text},
        "Nonprofit",
        load_json(ROOT / "instructions" / "public-research.json"),
        RULES,
        [],
    )


@pytest.mark.parametrize("name", sorted(UNRELATED_TO_FOOD))
def test_a_request_about_something_else_gets_no_food_page(name: str) -> None:
    pages = [p["id"] for p in _brief_for(UNRELATED_TO_FOOD[name])["fetch"]["pages"]]
    assert not [p for p in pages if p.startswith("food-")], (name, pages)


def test_a_pantry_question_with_filing_words_gets_its_food_pages_first() -> None:
    from eranos.pipeline import research

    brief = _brief_for(
        "What annual return must a tax-exempt food pantry file with the IRS, and what are its food safety duties?"
    )
    fetched = [u for u, _, _ in research.permitted_urls(brief)][: brief["fetch"]["max_sources"]]
    ids = {p["url"]: p["id"] for p in brief["fetch"]["pages"]}
    first = [ids.get(u, u) for u in fetched]
    food = [i for i in first if i.startswith("food-")]
    assert len(food) >= 3 and first[: len(food)] == food, first


def test_specific_actionable_sentences_rank_first_among_a_sources_candidates() -> None:
    from eranos.pipeline.research import candidate_sentences, specificity

    assert specificity("Keep the refrigerator at 40 °F or below.") == 2
    assert specificity("A person shall not be subject to civil liability for donated food.") == 1
    assert specificity("Follow these four simple steps: clean, separate, cook, and chill.") == 0
    text = (
        "Food pantries follow simple food rules every day of the week. "
        "Keep cold pantry food at 40 °F or below and throw it out after 2 hours outside. "
        "A pantry that gives food in good faith is protected from liability for that food."
    )
    picked = candidate_sentences(
        [{"id": "SRC-1", "text": text}], "What food rules apply to a pantry?", 2
    )
    assert [p["text"][:9] for p in picked] == ["Keep cold", "A pantry "]


@needs_workerd
def test_a_sensitive_process_kit_waits_for_a_person_then_publishes(
    fabric: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page promises it: a kit on a sensitive track is not public until a person says yes."""
    monkeypatch.setattr(process_part, "_track_needs_person", lambda track_id: True)
    bundle = tmp_path / "bundle" / "bundle.tgz"
    bundle.parent.mkdir()
    bundle.write_bytes(b"made-up sample process bundle")
    handler_path = tmp_path / "handler.py"
    handler_path.write_text(
        HANDLER_FILE.replace(
            'verified["catalog_value"] = {"title": "Made-up sample data-cleaning process",',
            'verified["catalog_value"] = {"kit": {"track_id": "statement-transcription"}, "title": "Made-up sample data-cleaning process",',
        )
    )
    monkeypatch.setenv("TEST_BUNDLE", str(bundle))
    handler = process_part.load_handler(str(handler_path))
    requester = fabric.requester()
    rid = fabric.file_request(
        requester,
        {
            "text": "A reusable process to merge our made-up shift lists and flag gaps.",
            "links": [],
            "organization_type": "Food pantry",
            "output_type": "process",
            "frequency": "one-off",
        },
        "proc2",
    )
    w = _workers(fabric, handler=handler)
    for role in ("planner", "builder", "reviewer"):
        assert w[role].run_once() == "worked"
    part = fabric.get(f"/v1/stores/eranos.plans/records/{rid}")["value"]["parts"][0]
    ids = handler.expected_records({"request_id": rid}, {"part": 1})
    assert _record(fabric, rid)["parts"]["1"]["status"] == "awaiting_steward"
    assert "signoff_required" in _types(_record(fabric, rid))
    draft = fabric.get(f"/v1/stores/eranos.processes/records/{ids['catalog_record']['key']}")
    assert draft.get("visibility_scope") != "public_commons"
    process_part.person_signoff(
        fabric.admin_client(), part["review_task_id"], person="a test person", notes="read it"
    )
    assert w["reviewer"].run_once() == "worked"
    stored = fabric.get(f"/v1/stores/eranos.processes/records/{ids['catalog_record']['key']}")
    assert stored["visibility_scope"] == "public_commons" and stored["value"]["review_receipt"]
