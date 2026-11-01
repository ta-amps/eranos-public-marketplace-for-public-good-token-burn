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
TUNING = load_json(ROOT / "instructions" / "worker.tuning.json")


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
    assert CATALOG["runtime"]["dedicated_worker_default"] == RULES["model"]["id"]
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
    assert worker._model().model == "muse-spark-1.3"  # the noun is read again after five minutes
    now[0] += 301
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
    meta_env.write_text(json.dumps({"days": {today: 5.0}, "total_usd": 5.0, "calls": 200}))
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
    assert pick is not None and worker.pick_fields(pick)["variant"] == "volunteer"
    assert worker.pick_fields(pick)["model_display"] == "Muse Spark 1.3"
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
    assert harness["variant"] == "volunteer" and harness["probability"] == 1.0
    assert harness["why"] == "the volunteer mode runs its own fixed model"
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
