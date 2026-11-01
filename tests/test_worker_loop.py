"""The volunteer worker loop: unit checks, then whole flows against a local Tessera on workerd.

SYNTHETIC data only: the public-rules page and the model are test stand-ins. The integration tests
need ERANOS_WORKERD_TESSERA (a Tessera checkout with node_modules) and are skipped without it.
"""

from __future__ import annotations

import hashlib
import json
import os
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
from eranos.model_client import ContributorTierRefused, OllamaModel
from eranos.pipeline import process as process_part
from eranos.pipeline.planner import request_terms
from eranos.pipeline.research import check_claims
from eranos.pipeline.reuse import find_reuse, score, terms
from eranos.sources import SourcePolicy, SourceRefused, check_address, extract_text
from eranos.worker_loop import Pacer, Worker, WorkerConfig

ROOT = Path(__file__).resolve().parents[1]
RULES = load_json(ROOT / "instructions" / "worker.json")
INFO_TEXT = "Summarize the tax law rules on political campaign activity for 501(c)(3) charities, with a citation for every point."
REWORDED = "Our charity needs a cited overview of what the rules say about 501(c)(3) groups and political campaigns."


# unit checks ------------------------------------------------------------------------------------
def test_empty_claim_waits_a_minute_or_the_servers_retry_after() -> None:
    pacer = Pacer(60.0)
    assert pacer.ready("eq02", 0.0)
    assert pacer.empty("eq02", 100.0, 5.0) == 160.0
    assert not pacer.ready("eq02", 159.0) and pacer.ready("eq02", 160.0)
    assert pacer.empty("eq02", 200.0, 90.0) == 290.0
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
    assert Empty.calls == 3  # at t=0, t=60 and t=120
    assert outcomes.count("empty") == 3 and outcomes.count("paced") == len(outcomes) - 3
    log = [json.loads(line) for line in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert [e["event"] for e in log] == ["claim_empty"] * 3


def test_html_text_drops_scripts_and_keeps_sentences_whole() -> None:
    title, text = extract_text("text/html; charset=utf-8", RULES_HTML.encode())
    assert title.startswith("SYNTHETIC public rules")
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
        "quote not verbatim",
        "the claim says more than its quote",
        "names no numbered sentence",
    }


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


def test_contributor_tier_and_remote_models_are_refused() -> None:
    with pytest.raises(ContributorTierRefused):
        OllamaModel(model="muse-spark-1.3-contributor")
    with pytest.raises(ValueError, match="loopback"):
        OllamaModel(url="https://api.example.com")


# whole flows on a local Tessera (workerd) ------------------------------------------------------------
needs_workerd = pytest.mark.skipif(
    not available(), reason="set ERANOS_WORKERD_TESSERA to a Tessera checkout with node_modules"
)


@pytest.fixture
def fabric(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """A fresh local Tessera per test, so no test claims another test's verbs."""
    noun = {**RULES, "recurring": {**RULES["recurring"], "min_period_seconds": 2}}
    with local_tessera(tmp_path_factory.mktemp("workerd"), worker_noun=noun) as running:
        yield running


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
        "reviewer": fabric.worker("reviewer", fetcher=fetcher, handler=handler),
    }


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
        "work_claimed",
        "work_submitted",
        "check_claimed",
        "check_approved",
        "delivered",
        "added",
        "plan_claimed",
        "closed",
    ]
    assert all(e.get("receipt") or e.get("ref") for e in record["events"])
    claimed = next(e for e in record["events"] if e["type"] == "work_claimed")
    assert (
        claimed["worker"] == "test-builder"
        and claimed["model"].startswith("fake-llama")
        and claimed["lease_ends"] > claimed["at"]
    )

    part = plan["parts"][0]
    solution = fabric.get(f"/v1/stores/eranos.solutions/records/{part['report_id']}")["value"]
    claims = solution["report"]["claims"]
    assert len(claims) >= 3 and solution["synthetic"] is False
    _, page = extract_text("text/html", RULES_HTML.encode())
    assert all(c["citations"][0]["quote"] in page for c in claims)
    assert "not legal advice" in solution["report"]["disclaimer"]
    assert solution["report"]["stages"]["dropped"], "the invented quote was dropped"

    work = fabric.get(f"/v1/tasks/{part['work_task_id']}/results")["results"][-1]
    review = fabric.get(f"/v1/tasks/{part['review_task_id']}/results")["results"][-1]
    assert work["completed_by_key"] == fabric.keys["builder"]["key_id"]
    assert (
        review["completed_by_key"] == fabric.keys["reviewer"]["key_id"] != work["completed_by_key"]
    )
    report = _executions(fabric, part["work_task_id"])[0]["report"]
    assert report["model"]["id"] == "fake-llama-for-tests" and report["usage"]["total_tokens"] > 0
    assert report["harness"]["cost_usd"] == 0.0 and report["harness"]["role"] == "builder"
    review_report = _executions(fabric, part["review_task_id"])[0]["report"]
    assert review_report["model"] is None and review_report["usage"]["total_tokens"] == 0


@needs_workerd
def test_reworded_repeat_is_answered_from_stored_work_with_no_new_verbs_or_tokens(
    fabric: Any,
) -> None:
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
    assert _workers(fabric)["planner"].run_once() == "worked"
    after = fabric.get("/v1/counts")
    for queue in ("eq02", "eq03"):
        assert sum(after["queues"][queue].values()) == sum(before["queues"][queue].values()), queue
    record = _record(fabric, rid)
    assert record["status"] == "closed" and record["reused_from"]["store"] == "eranos.solutions"
    assert _types(record)[-3:] == ["reused", "delivered", "closed"]
    task = fabric.get(f"/v1/tasks/{rid}")
    assert task["state"] == "done" and task["pending_children"] == 0
    report = _executions(fabric, rid)[0]["report"]
    assert report["model"] is None and report["usage"]["total_tokens"] == 0


@needs_workerd
def test_process_request_without_a_handler_records_every_failure(fabric: Any) -> None:
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
    for _ in range(3):
        deadline = time.time() + 10
        while w["builder"].run_once() != "worked" and time.time() < deadline:
            time.sleep(0.3)
    results = fabric.get(f"/v1/tasks/{part['work_task_id']}/results")["results"]
    assert len(results) == 3 and all(not r["ok"] and "not built yet" in r["error"] for r in results)
    assert fabric.get(f"/v1/tasks/{part['work_task_id']}")["state"] == "dead"
    assert w["reviewer"].run_once() == "worked"
    assert w["planner"].run_once() == "worked"
    record = _record(fabric, rid)
    assert _types(record).count("work_failed") == 3
    assert "check_sent_back" in _types(record) and record["status"] == "closed"


@needs_workerd
def test_process_request_with_a_handler_is_built_reviewed_and_published(
    fabric: Any, tmp_path: Path
) -> None:
    bundle = tmp_path / "bundle.tgz"
    bundle.write_bytes(b"made-up process bundle")

    class Handler:
        name = "test handler"

        def expected_records(
            self, request: dict[str, Any], plan_part: dict[str, Any]
        ) -> dict[str, Any]:
            key = f"PROC-{request['request_id'][-6:]}"
            return {
                "request_id": request["request_id"],
                "kit_id": key,
                "catalog_record": {"store": "eranos.processes", "key": key},
                "task_template_record": {"store": "eranos.process_templates", "key": key},
            }

        def build_process(
            self, request: dict[str, Any], plan_part: dict[str, Any]
        ) -> dict[str, Any]:
            ids = self.expected_records(request, plan_part)
            return {
                "bundle_path": str(bundle),
                "catalog_record": {
                    **ids["catalog_record"],
                    "value": {
                        "title": "Made-up data-cleaning process",
                        "request": request["request_id"],
                    },
                },
                "task_template_record": {
                    **ids["task_template_record"],
                    "value": {"kind": "run_process", "request": request["request_id"]},
                },
                "test_report": {"passed": True, "tests": 4, "issues": []},
                "ids": ids,
            }

        def record_digest(self, value: Any) -> str:
            return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

        def review_process(
            self,
            package: dict[str, Any],
            request: dict[str, Any],
            plan_part: dict[str, Any],
            *,
            bundle_path: Any = None,
            records: dict[str, Any] | None = None,
            builder_key_id: str | None = None,
            **_: Any,
        ) -> dict[str, Any]:
            data = Path(bundle_path).read_bytes()
            ok = hashlib.sha256(data).hexdigest() == package["blob_sha256"]
            mine = all(
                r["owner_key_id"] == builder_key_id
                and r["value"].get("request") == request["request_id"]
                for r in (records or {}).values()
            )
            return {
                "passed": ok and mine,
                "checks": [
                    "bundle fetched by digest",
                    "records written by the build's key",
                    "4 tests passed",
                ],
                "verified": {
                    n: {"value_sha256": self.record_digest(r["value"])}
                    for n, r in (records or {}).items()
                },
            }

    handler = Handler()
    requester = fabric.requester()
    rid = fabric.file_request(
        requester,
        {
            "text": "A reusable process to merge our SYNTHETIC shift lists and flag gaps.",
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
    assert _types(record)[-5:] == ["check_approved", "published", "added", "plan_claimed", "closed"]
    key = f"PROC-{rid[-6:]}"
    stored = fabric.get(f"/v1/stores/eranos.processes/records/{key}")
    assert stored["visibility_scope"] == "public_commons"


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
    assert reviewer.stats["failed"] == 1 and "work_failed" in _types(_record(fabric, rid))
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
                    json={"task_id": part["work_task_id"], "reason": "SYNTHETIC test"},
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


def test_find_reuse_requires_a_review_receipt() -> None:
    class Record:
        def __init__(self, key: str, value: dict[str, Any]) -> None:
            self.key, self.value, self.version = key, value, 1

    class Backend:
        def list_records(self, store: str, limit: int) -> list[Record]:
            if store != "eranos.solutions":
                return []
            report = {"title": "SYNTHETIC rules", "question": INFO_TEXT, "claims": []}
            return [
                Record("RPT-unreviewed", {"report": report}),
                Record("RPT-reviewed", {"report": report, "review_receipt": "r" * 64}),
            ]

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
    """The film's request end to end with the real B4 handler: claim, build (local Llama 3.2 3B and a
    container test), a different key's review, published, added; then a reworded request is answered
    from the stored package with no new verbs and no model tokens."""
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
            pytest.fail(f"{role}: {outcome}; build {[(r['ok'], r['error']) for r in results]}")
    record = _record(fabric, rid)
    part = fabric.get(f"/v1/stores/eranos.plans/records/{rid}")["value"]["parts"][0]
    if os.environ.get("B4_EVENTS_FILE"):
        Path(os.environ["B4_EVENTS_FILE"]).write_text(
            json.dumps(record.get("events"), indent=1), encoding="utf-8"
        )
    assert _types(record)[-5:] == [
        "check_approved",
        "published",
        "added",
        "plan_claimed",
        "closed",
    ], (" ".join(_types(record)),)
    built = [
        r for r in fabric.get(f"/v1/tasks/{part['work_task_id']}/results")["results"] if r["ok"]
    ]
    reviewed = [
        r for r in fabric.get(f"/v1/tasks/{part['review_task_id']}/results")["results"] if r["ok"]
    ]
    output, approval = built[-1]["output"], reviewed[-1]["output"]
    assert approval["status"] == "approved"
    assert approval["drafter_key_id"] != approval["reviewer_key_id"]
    draft = fabric.get(
        f"/v1/stores/{output['catalog_record']['store']}/records/{output['catalog_record']['key']}"
    )
    assert draft["visibility_scope"] == "public_commons"
    assert output["catalog_record"]["key"].startswith(f"{rid}.1.")
    catalog = fabric.get(f"/v1/stores/eranos.catalog/records/{output['draft']['kit_id']}")
    assert catalog["visibility_scope"] == "public_commons"
    value = catalog["value"]
    assert value["blob_sha256"] == output["bundle_sha256"]
    assert value["review_receipt"] and "status:verified" in value["tags"]
    assert value["reviewed_by_key"] != value["kit"]["drafted_by_key"]
    assert [t for t in value["tags"] if t.startswith("reuse:")] == ["reuse:proc2-7eefca618400649c"]
    assert f"request:{rid}" in value["tags"]
    assert "synthetic" not in json.dumps(value).lower()
    assert output["test_report"]["passed"] is True
    reused = fabric.file_request(requester, {"text": FILM_REWORDED, **terms}, "film2")
    assert w["planner"].run_once() == "worked"
    again = _record(fabric, reused)
    plan = fabric.get(f"/v1/stores/eranos.plans/records/{reused}")["value"]
    assert again["status"] == "closed"
    assert plan["parts"][0]["route"] == "reused"
    assert plan["parts"][0]["reused_from"]["key"] == output["draft"]["kit_id"]
    assert plan["parts"][0]["reused_from"]["score"] == 1.0
    if os.environ.get("B4_E2E_EVIDENCE"):
        report = output["test_report"]
        evidence = {
            "request_events": [
                e["type"] for e in record.get("events") or [] if e["type"] != "heartbeat"
            ],
            "bundle_sha256": output["bundle_sha256"],
            "bundle_bytes": output["bundle_bytes"],
            "build_checks": {k: v.get("passed") for k, v in report["checks"].items()},
            "build_tests": report["tests"],
            "model_usage": report["model_usage"],
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
