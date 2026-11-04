"""Which model a worker runs, and how its records say so.

The worker noun names the model id (the volunteer mode has its own), the `models.meta` noun gives its
display name and token rates, status facts carry `model` (the id), `model_display` and a separate
`harness`, a spent cap or a refused model stops research claims, and a volunteer claims at once under
its own label. Nothing here calls a model or a server.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from eranos import __version__
from eranos.jsonfile import load_json
from eranos.model_client import KEY_FILE_ENV, LEDGER_ENV, MetaModel, ModelCall, UsageMeter
from eranos.pipeline import process as process_part
from eranos.worker_loop import LOCAL_CATALOG, Worker, WorkerConfig

ROOT = Path(__file__).resolve().parents[1]
RULES = load_json(ROOT / "instructions" / "worker.json")
CATALOG = load_json(LOCAL_CATALOG)
TUNING = load_json(ROOT / "instructions" / "worker.policy.json")


class Backend:
    """Serves the worker noun and, when given one, a `models.meta` record; every claim is empty."""

    def __init__(
        self, rules: dict[str, Any] | None = None, catalog: dict[str, Any] | None = None
    ) -> None:
        self.rules, self.catalog = rules or RULES, catalog
        self.claims: list[list[str]] = []

    def get_record(self, store: str, key: str) -> Any:
        if (store, key) == ("eranos.instructions", "worker"):
            return SimpleNamespace(value=self.rules)
        if (store, key) == ("eranos.instructions", "models.meta") and self.catalog is not None:
            return SimpleNamespace(value=self.catalog)
        raise LookupError(f"{store}/{key}")

    def claim_with_hint(
        self, queue: str, worker: str, *, kinds: list[str]
    ) -> tuple[None, float, int]:
        self.claims.append(list(kinds))
        return None, 5.0, 60

    def ready_verbs(self, queue: str) -> list[dict[str, Any]]:
        raise AssertionError("a volunteer never waits for the dedicated workers' grace period")


class Declared:
    """An injected model that only says which id it is."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def describe(self) -> dict[str, Any]:
        return {"provider": "meta", "id": self.model_id, "tier": "standard"}

    def healthy(self) -> None:
        return None


@pytest.fixture
def meta_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    key = tmp_path / "meta-key"
    key.write_text("test-key-not-real\n")
    key.chmod(0o600)
    monkeypatch.setenv(KEY_FILE_ENV, str(key))
    monkeypatch.setenv(LEDGER_ENV, str(tmp_path / "spend.json"))
    return tmp_path / "spend.json"


def make(
    tmp_path: Path,
    *,
    role: str = "builder",
    volunteer: bool = False,
    dedicated: bool = False,
    backend: Backend | None = None,
    model: Any = None,
    handler: Any = None,
    clock: Any = None,
) -> Worker:
    config = WorkerConfig(
        role=role,
        label="test-worker",
        tessera_url="http://127.0.0.1:9",
        key="x",
        key_id="k_test",
        trace_path=str(tmp_path / "trace.jsonl"),
        volunteer=volunteer,
        dedicated=dedicated,
        display_name="dedicated worker 2 (run by ta-amps)" if dedicated else "",
    )
    extra = {"clock": clock} if clock else {}
    return Worker(
        config,
        backend=backend or Backend(),
        heartbeat_backend=object(),
        handler=handler or process_part.StubHandler(),
        model=model,
        **extra,
    )


def events(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / "trace.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_the_noun_names_the_model_and_the_catalog_names_and_prices_it(
    tmp_path: Path, meta_env: Path
) -> None:
    dedicated = make(tmp_path)
    model = dedicated._model()
    assert isinstance(model, MetaModel)
    assert (model.model, model.display) == ("muse-spark-1.3", "Muse Spark 1.3")  # owner, Nov 1
    assert model.prices == {"input": 1.25, "output": 4.25}  # the catalog's rates, not code
    assert "self-tuning" in CATALOG["runtime"]["selection"]  # catalog v4: no fixed default
    # Each step's pick comes from the tuning noun's mix and is recorded in full.
    lease = SimpleNamespace(task_id="t_make", fencing_token=1)
    pick = dedicated.pick_for("make", lease)
    assert pick is not None
    fields = dedicated.model_fields("research", pick)
    variants = {v["id"]: v for v in TUNING["variants"]}
    chosen = variants[fields["variant"]]
    assert fields["model"] == chosen["model"] and fields["persona"] == chosen["persona"]["title"]
    assert fields["model_display"] in ("Muse Spark 1.3", "Muse Wonder 1.0")
    assert fields["harness"] == "eranos-worker" and fields["harness_version"] == __version__
    assert fields["tuner_version"] == 0 and fields["probability"] == round(1 / 3, 4)
    assert "starting mix" in fields["why"]
    assert pick == dedicated.pick_for("make", lease)  # reproducible from the lease
    for kind in ("request", "spec", "draft", "review", "tune"):
        plain = dedicated.model_fields(kind)
        assert "model" not in plain and plain["method"] and plain["harness"] == "eranos-worker"
    assert dedicated.meta("muse-wonder-1.0").prices == {"input": 4.0, "output": 20.0}
    volunteer = make(tmp_path, volunteer=True)._model()
    assert (volunteer.model, volunteer.display) == ("muse-spark-1.3", "Muse Spark 1.3")
    # The frontier model is priced in the catalog too: a step moves to it by changing the noun only.
    rules = {**RULES, "model": {**RULES["model"], "id": "muse-wonder-1.0"}}
    wonder = make(tmp_path, backend=Backend(rules=rules))._model()
    assert (wonder.display, wonder.prices) == ("Muse Wonder 1.0", {"input": 4.0, "output": 20.0})


def test_the_catalog_on_tessera_wins_over_the_repository_copy(tmp_path: Path) -> None:
    renamed = json.loads(json.dumps(CATALOG))
    renamed["runtime"]["display_by_id"]["muse-spark-1.3"] = "Muse Spark 1.3 (as Tessera holds it)"
    worker = make(tmp_path, backend=Backend(catalog=renamed))
    assert worker.model_display("muse-spark-1.3") == "Muse Spark 1.3 (as Tessera holds it)"
    assert worker.model_display("muse-code") == "Muse Code 1.4.14"  # agent apps are named too
    assert worker.model_display("not-in-the-catalog") == "not-in-the-catalog"
    assert [e["event"] for e in events(tmp_path)] == ["model_not_in_catalog"]


def test_a_changed_noun_switches_the_model_at_its_next_read(tmp_path: Path, meta_env: Path) -> None:
    now = [1000.0]
    backend = Backend()
    worker = make(tmp_path, backend=backend, clock=lambda: now[0])
    assert worker._model().model == "muse-spark-1.3"
    backend.rules = {**RULES, "model": {**RULES["model"], "id": "muse-wonder-1.0"}}
    # The noun is read again after its refresh interval (claims.noun_refresh_seconds).
    assert worker._model().model == "muse-spark-1.3"
    now[0] += worker.refresh_seconds() + 1
    assert worker._model().model == "muse-wonder-1.0"


@pytest.mark.parametrize(
    ("model_id", "reason"),
    [
        ("muse-spark-1.3-contributor", "contributor-tier"),
        ("muse-spark-1.2", "no token rates"),
        ("muse-glimmer-30b", "no token rates"),  # named in the catalog, not called through the API
    ],
)
def test_a_refused_or_unpriced_model_is_never_claimed_for(
    tmp_path: Path, meta_env: Path, model_id: str, reason: str
) -> None:
    rules = {**RULES, "model": {**RULES["model"], "id": model_id}}
    worker = make(tmp_path, backend=Backend(rules=rules))
    assert "research" not in worker.claim_kinds()
    (event,) = [e for e in events(tmp_path) if e["event"] == "model_unavailable"]
    assert reason in event["error"]


def test_a_spent_cap_stops_research_claims_and_says_so(tmp_path: Path, meta_env: Path) -> None:
    import time

    today = time.strftime("%Y-%m-%d", time.gmtime())
    meta_env.write_text(json.dumps({"days": {today: 25.0}, "total_usd": 25.0, "calls": 200}))
    backend = Backend()
    worker = make(tmp_path, backend=backend)
    assert worker.run_once() == "empty"
    assert backend.claims == [["draft"]]  # research is not claimed; the kit work still is
    (event,) = [e for e in events(tmp_path) if e["event"] == "model_budget_reached"]
    assert "daily Meta cap" in event["error"]


def test_a_volunteer_claims_at_once_and_only_research(tmp_path: Path) -> None:
    backend = Backend()
    # Even if a volunteer's settings also said dedicated, it never waits out the grace period.
    worker = make(
        tmp_path, volunteer=True, dedicated=True, backend=backend, model=Declared("muse-spark-1.3")
    )
    assert worker.run_once() == "empty"
    assert backend.claims == [["research"]]
    assert worker.who() == {
        "worker": "a volunteer's AI",
        "dedicated": False,
        "worker_kind": "volunteer",
    }
    pick = worker.pick_for("make", SimpleNamespace(task_id="t_vol", fencing_token=1))
    assert pick is not None
    fields = worker.pick_fields(pick)
    # A volunteer runs its own model and draws a persona from the mix's variants on that model.
    assert fields["model_display"] == "Muse Spark 1.3" and fields["variant"].startswith(
        "make-spark-"
    )
    assert fields["persona"] and fields["why"].startswith("a volunteer's AI on its own model")
    checker = make(
        tmp_path,
        role="reviewer",
        volunteer=True,
        handler=object(),
        model=Declared("muse-spark-1.3"),
    )  # no builder keys needed
    assert checker.claim_kinds() == ["report_review"]


def test_the_volunteer_mode_comes_from_its_own_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "TESSERA_URL": "http://127.0.0.1:9",
        "TESSERA_KEY": "x",
        "ERANOS_KEY_ID": "k_test",
        "ERANOS_VOLUNTEER": "1",
        "ERANOS_DEDICATED": "1",
    }.items():
        monkeypatch.setenv(name, value)
    config = WorkerConfig.from_env("builder")
    assert config.volunteer is True and config.dedicated is False
    with pytest.raises(ValueError, match="volunteer"):
        WorkerConfig.from_env("planner")


def test_execution_reports_name_the_model_tier_tokens_cost_and_payer(tmp_path: Path) -> None:
    lease = SimpleNamespace(kind="research", brief={"title": "A made-up question"}, task_id="t1")
    meter = UsageMeter()
    meter.add(
        {
            "provider": "meta",
            "id": "muse-spark-1.3",
            "model_display": "Muse Spark 1.3",
            "tier": "standard",
        },
        ModelCall(input_tokens=1000, output_tokens=200, seconds=1.0, cost_usd=0.00205),
    )
    volunteer = make(tmp_path, volunteer=True, model=Declared("muse-spark-1.3"))
    pick = volunteer.pick_for("make", SimpleNamespace(task_id="t1", fencing_token=1))
    report = volunteer._report_factory(lease, meter, {"pick": pick})(
        {"status": "report"}, True, None
    )
    harness = report["harness"]
    assert harness["name"] == "eranos-worker" and harness["declared_model"] == "muse-spark-1.3"
    assert harness["variant"].startswith("make-spark-") and harness["persona"]
    assert harness["probability"] == 0.5 and harness["why"].startswith(
        "a volunteer's AI on its own model"
    )
    assert harness["tier"] == "standard" and harness["cost_usd"] == 0.00205
    assert harness["worker_kind"] == "volunteer"
    assert harness["payer"].startswith("spare Meta API credit given by the volunteer")
    assert (
        report["model"]["id"] == "muse-spark-1.3"
        and report["model"]["model_display"] == "Muse Spark 1.3"
    )
    assert report["usage"]["total_tokens"] == 1200
    review = SimpleNamespace(
        kind="report_review", brief={"title": "A made-up question"}, task_id="t2"
    )
    plain = make(tmp_path, role="reviewer")._report_factory(review, UsageMeter(), {})(
        {}, True, None
    )
    assert plain["model"] is None and plain["harness"]["declared_model"] is None
    assert (
        plain["harness"]["method"].startswith("deterministic")
        and plain["harness"]["cost_usd"] == 0.0
    )
    assert plain["harness"]["payer"] == "no model call; no charge"


def test_the_cli_volunteer_flag_turns_on_the_volunteer_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from eranos import cli

    seen: dict[str, Any] = {}
    monkeypatch.setenv("ERANOS_VOLUNTEER", "0")  # recorded, so the flag's change is undone after
    monkeypatch.setattr(cli, "cmd_work", lambda role, **kw: seen.update(role=role, **kw) or 0)
    monkeypatch.setattr(
        sys, "argv", ["eranos", "work", "--role", "builder", "--volunteer", "--once"]
    )
    assert cli.main() == 0
    assert seen["role"] == "builder" and seen["once"] is True
    import os

    assert os.environ["ERANOS_VOLUNTEER"] == "1"


def test_every_model_a_worker_can_name_resolves_through_the_catalog() -> None:
    """Claim facts carry model ids; pages name them through models.meta's runtime.display_by_id,
    and a model without rates there is never called, so every id the workers can pick must have both."""
    runtime = CATALOG["runtime"]
    ids = {RULES["model"]["id"], RULES["model"]["volunteer_id"]}
    ids |= {v["model"] for v in TUNING["variants"]}
    ids.add(TUNING["propose"]["model"])
    for model_id in sorted(ids):
        assert runtime["display_by_id"][model_id].startswith("Muse "), model_id
        assert {"input", "output"} <= set(runtime["rates_usd_per_million_tokens"][model_id]), (
            model_id
        )
    assert runtime["tier"] == "standard"


def test_a_failed_research_says_whether_its_sources_or_its_answer_came_up_empty(
    tmp_path: Path,
) -> None:
    worker = make(tmp_path, model=Declared("muse-spark-1.3"))
    lease = SimpleNamespace(kind="research", task_id="t_r", fencing_token=1)
    worker._pick = worker.pick_for("make", lease)

    def failed(fetched: int, candidates: int, answer: str) -> dict[str, Any]:
        stages = {"fetch": {"fetched": fetched}, "candidates": candidates, "answer": answer}
        return worker._failed_tuning(lease, {"output": {"report": {"stages": stages}}})["tuning"]

    assert failed(0, 0, "no_call").get("source_side") is True
    assert failed(2, 0, "no_call").get("source_side") is True
    assert failed(2, 16, "no_claims").get("no_claims") is True
    assert not {"source_side", "no_claims"} & set(failed(2, 16, "unparsed"))  # the variant's answer


def test_the_second_maker_has_its_own_key_shape_and_the_noun_allows_five_workers() -> None:
    from eranos.worker_keys import ROLE_KEYS

    assert ROLE_KEYS["builder2"] == ROLE_KEYS["builder"]  # the same scope, issued as its own key
    assert RULES["dedicated"]["max_workers"] == 5 and RULES["model"]["budget"]["daily_usd"] == 25


def test_the_plain_log_never_shows_an_id_a_key_a_hash_or_a_link(tmp_path: Path) -> None:
    from eranos.worker_loop import plain_words_only

    text = plain_words_only(
        "could not finish t_de01286fed9c49aabd492c33b2cb1da5 for rq-r_02c6-exrecu with k_12323a7b4649 "
        "tsk_secretvalue123 at https://example.org/x digest 64fd2f0fab24ea41194eed3650c71c5de8203b1d RPT-R49552D4-01"
    )
    assert not any(
        bit in text for bit in ("t_de0", "rq-", "k_1", "tsk_", "https://", "64fd2f", "RPT-")
    )
    worker = make(tmp_path, dedicated=True)
    worker.config.plain_log = str(tmp_path / "plain.log")
    worker.say("claimed a research Task · Muse Spark 1.3 · persona Careful maker")
    worker.say("claimed a research Task · Muse Spark 1.3 · persona Careful maker")  # not repeated
    worker.say("waiting t_abc123def456789")
    lines = (tmp_path / "plain.log").read_text().splitlines()
    assert len(lines) == 2 and lines[0].endswith(
        "dedicated worker 2 (run by ta-amps) · claimed a research Task · Muse Spark 1.3 · persona Careful maker"
    )
    assert "t_abc" not in lines[1]


def test_each_named_volunteer_is_its_own_principal() -> None:
    import httpx

    from eranos.worker_keys import issue_key

    seen: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(201, json={"key": "tsk_" + "x" * 32, "key_id": f"k_{len(seen)}"})

    with httpx.Client(
        base_url="https://tessera.example", transport=httpx.MockTransport(handle)
    ) as http:
        for name in ("ag1", "ag2"):
            issue_key(
                http,
                "admin-placeholder",
                "volunteer",
                days=8,
                account_id=f"eranos-volunteer-{name}",
                label=f"eranos-volunteer-{name}",
            )
    assert [b["account_id"] for b in seen] == ["eranos-volunteer-ag1", "eranos-volunteer-ag2"]
    for body in seen:  # research and its checks only: no planner, builder or kit kinds
        assert body["queues"] == ["eq02", "eq03"] and body["kinds"] == ["research", "report_review"]


def test_a_narrow_volunteer_key_writes_no_record_and_holds_one_queue() -> None:
    import httpx

    from eranos.worker_keys import issue_key

    seen: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(201, json={"key": "tsk_" + "y" * 32, "key_id": f"k_n{len(seen)}"})

    with httpx.Client(
        base_url="https://tessera.example", transport=httpx.MockTransport(handle)
    ) as http:
        for queue in ("research", "check"):
            issue_key(
                http,
                "admin-placeholder",
                "volunteer",
                days=8,
                narrow=queue,
                account_id=f"eranos-volunteer-ext-{queue}",
            )
    research, check = seen
    assert (research["queues"], research["kinds"]) == (["eq02"], ["research"])
    assert (check["queues"], check["kinds"]) == (["eq03"], ["report_review"])
    for body in seen:
        assert "cas:write" not in body["scopes"] and "verbs:claim" in body["scopes"]


def test_a_task_the_requests_plan_does_not_name_is_never_worked(tmp_path: Path) -> None:
    from eranos.worker_loop import NotInPlan, _task_ids

    plan = {
        "parts": [{"work_task_id": "t_a", "review_task_id": "t_b"}],
        "occurrences": [{"parts": [{"work_task_id": "t_c", "review_task_id": "t_d"}]}],
    }
    assert _task_ids(plan) == {"t_a", "t_b", "t_c", "t_d"}

    class Plans:
        def __init__(self, value: Any) -> None:
            self.value, self.reads = value, 0

        def get_record(self, store: str, key: str) -> Any:
            self.reads += 1
            return SimpleNamespace(value=self.value)

    worker = make(tmp_path, model=Declared("muse-spark-1.3"))
    worker.sleep = lambda seconds: None
    named = SimpleNamespace(task_id="t_c", kind="research")
    worker.planned_task(Plans(plan), named, "rq-1")  # an occurrence's Task: worked
    forged = SimpleNamespace(task_id="t_forged", kind="research")
    gate = Plans(plan)
    with pytest.raises(NotInPlan):
        worker.planned_task(gate, forged, "rq-1")
    assert (
        gate.reads == 3
    )  # read again before refusing: the planner writes the plan just after the Tasks
    worker.planned_task(
        Plans(None), SimpleNamespace(task_id="t_k", kind="draft"), None
    )  # kit Tasks have no plan


def test_a_failure_line_names_only_the_exceptions_class(tmp_path: Path) -> None:
    worker = make(tmp_path, dedicated=True)
    worker.config.plain_log = str(tmp_path / "plain.log")
    lease = SimpleNamespace(
        task_id="t_x", kind="research", fencing_token=1, attempt=1, queue="eq02", brief={}
    )
    gate = SimpleNamespace(ended="failed", receipt=None)
    beat = SimpleNamespace(lost=None)
    worker.fail(
        gate, lease, RuntimeError("www.evil.example answered 404 \\x1b[2J"), None, None, beat
    )  # type: ignore[arg-type]
    line = (tmp_path / "plain.log").read_text()
    assert (
        line.rstrip().endswith("could not finish a research Task · RuntimeError")
        and "evil" not in line
    )


def test_an_information_request_that_mentions_donors_is_researched_not_built() -> None:
    from eranos.pipeline.planner import _parts

    classify = load_json(ROOT / "instructions" / "classify.json")
    asked = (
        "What must a nonprofit's donor thank-you letter say so the donor can deduct the gift? "
        "How should we protect the personal information we keep about donors and clients?"
    )
    assert {p["route"] for p in _parts(asked, classify, "information")} == {"public-only"}
    assert {p["route"] for p in _parts(asked, classify, "process")} == {"private-files"}


def test_a_topic_whose_own_page_is_short_gets_more_official_pages() -> None:
    from eranos.pipeline import research

    part = {
        "part": 1,
        "route": "public-only",
        "legal": False,
        "text": "Which annual return must a small tax-exempt nonprofit file with the IRS (Form 990-N, 990-EZ or 990)?",
    }
    link = "https://www.irs.gov/charities-non-profits/exempt-organization-annual-filing-requirements-overview"
    brief = research.research_brief("rq-a", part, "Small nonprofit", {}, RULES, [link])
    urls = [(url, access) for url, access, _ in research.permitted_urls(brief)]
    assert urls[0] == (link, "public_web_page")  # the request's own link first, once
    assert {access for _, access in urls[1:]} == {"public_web_page"} and len(urls) == 3
    unrelated = {
        **part,
        "text": "A checklist of quick accessibility checks for a small nonprofit's website.",
    }
    assert not research.research_brief("rq-b", unrelated, "Small nonprofit", {}, RULES, [])[
        "fetch"
    ]["pages"]
    federal = next(a for a in RULES["sources"]["official_apis"] if a["id"] == "federal-register")
    assert "fields%5B%5D=dates" in federal["query"]  # a notice's dates (deadlines) are in the text


THANKS = (
    "Example request: what must a nonprofit's donor thank-you letter say so the donor can deduct the gift, "
    "including gifts where the donor gets something back?"
)
PRIVACY = (
    "Example request: in plain language, how should a small nonprofit protect the personal information it keeps "
    "about donors and clients, following the FTC's guide?"
)


def test_a_question_about_donors_or_privacy_law_is_researched() -> None:
    """FB1-025: routing follows what a request holds, not words such as donors or personal information."""
    from eranos.pipeline.planner import _parts
    from eranos.pipeline.requests import check_findings

    classify = load_json(ROOT / "instructions" / "classify.json")
    law = "What does the law say about how a charity may share its donors' personal information?"
    for text, chosen in (
        (THANKS, "information"),
        (PRIVACY, "information"),
        (law, "information"),
        (law, None),
    ):
        assert {p["route"] for p in _parts(text, classify, chosen)} == {"public-only"}, (
            text,
            chosen,
        )
        assert (
            check_findings({"text": text, "links": ""}) == []
        )  # nothing personal is held, nothing is refused
    assert {p["route"] for p in _parts("Clean our donor records spreadsheet.", classify, None)} == {
        "private-files"
    }


def test_pasted_records_are_refused_and_never_researched() -> None:
    from eranos.pipeline.requests import check_findings

    pasted = "Please summarize our intake. Name: Jane Roe\nPhone: 555-867-5309\nEmail: jane.roe@example.org"
    assert check_findings({"text": pasted, "links": ""})  # the planner blocks it before any routing


def test_a_task_that_names_no_request_is_refused_and_a_refusal_writes_no_fact(
    tmp_path: Path,
) -> None:
    from eranos.worker_loop import NotInPlan

    worker = make(tmp_path, model=Declared("muse-spark-1.3"))
    worker.sleep = lambda seconds: None
    with pytest.raises(NotInPlan, match="names no request"):
        worker.planned_task(
            SimpleNamespace(), SimpleNamespace(task_id="t_x", kind="research"), None
        )

    class Records:
        def __init__(self) -> None:
            self.puts: list[tuple[str, str]] = []

        def put_record(self, store: str, key: str, *args: Any, **kw: Any) -> Any:
            self.puts.append((store, key))
            return SimpleNamespace(version=1)

        def get_record(self, store: str, key: str) -> Any:
            raise LookupError(key)

    worker.backend = Records()
    lease = SimpleNamespace(
        task_id="t_f", kind="research", fencing_token=1, attempt=1, queue="eq02", brief={}
    )
    gate = SimpleNamespace(ended="failed", receipt=None)
    worker.fail(
        gate,
        lease,
        NotInPlan("the request's plan does not name this Task"),
        1,
        "rq-victim",
        SimpleNamespace(lost=None),
    )  # type: ignore[arg-type]
    assert worker.backend.puts == []  # nothing is written onto the request the forged brief names


@pytest.mark.parametrize(
    ("volunteer", "dedicated", "run_by", "kind", "shown"),
    [
        (True, False, "", "volunteer", "a volunteer's AI"),  # an outside volunteer's own run
        (True, False, "ta-amps", "dedicated", "the on-camera worker (run by ta-amps)"),  # our take
        (False, True, "", "dedicated", "dedicated worker 2 (run by ta-amps)"),
        (
            False,
            False,
            "",
            "dedicated",
            "test-worker",
        ),  # the default mode is ours, never a volunteer's
    ],
)
def test_only_an_outside_volunteers_run_is_marked_volunteer(
    tmp_path: Path, volunteer: bool, dedicated: bool, run_by: str, kind: str, shown: str
) -> None:
    worker = make(tmp_path, volunteer=volunteer, dedicated=dedicated)
    worker.config.run_by = run_by
    who = worker.who()
    assert who["worker_kind"] == kind and who["worker"] == shown
    if kind == "volunteer":
        assert who["dedicated"] is False and "run_by" not in who
    else:
        assert who["dedicated"] is True and who["run_by"] == "ta-amps"


def test_the_run_by_setting_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TESSERA_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("TESSERA_KEY", "x")
    monkeypatch.setenv("ERANOS_KEY_ID", "k_test")
    monkeypatch.setenv("ERANOS_VOLUNTEER", "1")
    monkeypatch.setenv("ERANOS_RUN_BY", "ta-amps")
    assert WorkerConfig.from_env("builder").run_by == "ta-amps"
