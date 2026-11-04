"""A kit publishes only after a model other than the maker's read every word; there's no person's step."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from tessera.receipts import canonical_json

from eranos.adapter import TracedBackend
from eranos.adapter import local as local_adapter
from eranos.model_client import BudgetExhausted, Ledger, MetaModel, ModelUnavailable, UsageMeter
from eranos.pipeline import (
    SelfReviewRefused,
    UnverifiedKitRefused,
    get_published_kit,
    load_example_bundles,
    run_draft_step,
    run_review_step,
    run_spec_step,
    submit_kit_request,
)
from eranos.pipeline import process as process_part
from eranos.pipeline.model_review import (
    MAX_KIT_BYTES,
    PROCESS_KIT_TEXT,
    judge,
    maker_model_of,
    pick_review_model,
    read_kit,
)
from eranos.pipeline.publication import OUTBOX_STORE
from eranos.pipeline.reuse_check import clean_why
from eranos.pipeline.run import brief_kit_id
from eranos.privacy import text_personal_findings
from eranos.schemas import KitDraft, KitRequest, ReviewDecision
from eranos.tracks import get_track
from eranos.verifier import verify_kit
from eranos.worker_loop import MODEL_KINDS, Worker, WorkerConfig, plain, public_failure

CLEAN = {
    "verdict": "approved",
    "dangerous_advice": [],
    "personal_data": [],
    "autonomy": [],
    "false_claims": [],
    "notes": "Read it all and found nothing.",
}
HOTLINE = 1  # KIT-HOTLINE-02, a sensitive track
UNSAFE = "Tell the caller to go back at night, take the passport from the employer's office and not to contact staff or police."


class Reader:
    def __init__(self, answer: Any = None, error: Exception | None = None) -> None:
        self.answer, self.error, self.calls = answer, error, []

    def describe(self) -> dict[str, Any]:
        return {"id": "fake"}

    def chat_json(self, system: str, user: str, **kwargs: Any) -> Any:
        self.calls.append(user)
        if self.error is not None:
            raise self.error
        return self.answer


@pytest.fixture
def backend(tmp_path: Path) -> TracedBackend:
    return TracedBackend(
        local_adapter.create(str(tmp_path / "e.db")),
        backend="local",
        trace_path=str(tmp_path / "t.jsonl"),
    )


def _reviewer(backend: Any, tmp_path: Path, model: Any) -> Worker:
    config = WorkerConfig(
        role="reviewer",
        label="reviewer-01",
        tessera_url="http://127.0.0.1:9",
        key="x",
        key_id="review-key",
        trace_path=str(tmp_path / "w.jsonl"),
    )
    with mock.patch.dict(os.environ, {process_part.BUILDER_KEYS_ENV: "draft-key"}):
        return Worker(
            config, backend=backend, heartbeat_backend=object(), handler=object(), model=model
        )


def _build(backend: Any, draft_change: Any = None, *, index: int = HOTLINE) -> tuple[Any, Any]:
    bundle = load_example_bundles()[index]
    req = KitRequest.model_validate(bundle["request"])
    graph = submit_kit_request(backend, req)
    run_spec_step(backend)
    draft = plain(copy.deepcopy(bundle["draft"]))
    if draft_change:
        draft_change(draft)
    run_draft_step(backend, draft, worker="drafter-01", key_id="draft-key")
    return req, graph


def _review(backend: Any, tmp_path: Path, model: Any) -> None:
    lease = backend.claim("eq03", "reviewer-01", kinds=["review"], key_id="review-key")
    if lease is not None:  # a draft that fails its own checks never reaches review
        _reviewer(backend, tmp_path, model).handle(lease)


def test_a_clean_kit_publishes_after_the_model_read_it_and_the_record_says_so(
    backend: Any, tmp_path: Path
) -> None:
    req, _ = _build(backend)
    reader = Reader(CLEAN)
    _review(backend, tmp_path, reader)
    published = get_published_kit(backend, req.kit_id)
    assert published is not None and published.steward_signoff is None
    assert "read all of this kit's text" in published.review_notes
    sent = json.loads(reader.calls[0])
    assert sent["kit"]["summary"], "the model is sent the kit's text"
    assert "tags" in sent["kit"] and "target_cohorts" in sent["kit"], (
        "the maker can write labels, so they're read too"
    )
    assert sent["checked_by_this_worker"] == [
        "This worker ran the kit's fixed checks itself, and they passed."
    ]
    assert "no model" not in published.review_notes.lower()


def test_dangerous_advice_is_sent_back_and_nothing_publishes(backend: Any, tmp_path: Path) -> None:
    req, _ = _build(backend, lambda d: d.update(summary=UNSAFE))
    reader = Reader(
        {
            **CLEAN,
            "verdict": "needs_revision",
            "dangerous_advice": ["tells a caller to act alone at night"],
        }
    )
    _review(backend, tmp_path, reader)
    assert reader.calls and UNSAFE in reader.calls[0]
    assert get_published_kit(backend, req.kit_id) is None


@pytest.mark.parametrize(
    "answer",
    [
        None,
        {},
        "yes",
        {"verdict": "approved"},
        {**CLEAN, "verdict": "APPROVED"},
        {**CLEAN, "dangerous_advice": ["a finding"]},
        {**CLEAN, "personal_data": "none"},
    ],
)
def test_any_unclear_answer_keeps_the_kit_unpublished(
    backend: Any, tmp_path: Path, answer: Any
) -> None:
    req, _ = _build(backend)
    _review(backend, tmp_path, Reader(answer))
    assert get_published_kit(backend, req.kit_id) is None


def test_a_model_that_cannot_answer_keeps_the_kit_unpublished(backend: Any, tmp_path: Path) -> None:
    from eranos.model_client import ModelUnavailable

    req, _ = _build(backend)
    _review(backend, tmp_path, Reader(error=ModelUnavailable("down")))
    assert get_published_kit(backend, req.kit_id) is None


def test_contact_details_are_stopped_by_the_screen_before_any_model_call(
    backend: Any, tmp_path: Path
) -> None:
    req, _ = _build(
        backend,
        lambda d: d.update(
            summary="Call Maria Lopez at 617-204-8831 or maria.lopez@realmail.org, 12 Elm Street, Boston."
        ),
    )
    reader = Reader(CLEAN)
    _review(backend, tmp_path, reader)
    assert get_published_kit(backend, req.kit_id) is None
    assert reader.calls == []


def test_the_screen_reads_all_text_and_never_repeats_the_match() -> None:
    found = text_personal_findings(
        {"steps": [{"guidance": "Write to maria.lopez@realmail.org"}], "tags": ["x"]}
    )
    assert found and "maria" not in " ".join(found)
    assert text_personal_findings({"summary": "Use 555-0100 for the made-up test."}) == []
    assert text_personal_findings({"target_cohorts": ["Call 617-204-8831 for Maria Lopez"]}), (
        "labels are screened too"
    )
    assert (
        verify_kit(
            _draft_with("Write to maria.lopez@realmail.org"), get_track(_draft_with("x").track_id)
        ).passed
        is False
    )


def _draft_with(summary: str) -> KitDraft:
    draft = copy.deepcopy(load_example_bundles()[HOTLINE]["draft"])
    draft["summary"] = (
        summary if len(summary) > 40 else summary + " and more words to fill the field."
    )
    return KitDraft.model_validate(draft)


def test_every_example_kit_still_passes_the_screen() -> None:
    for bundle in load_example_bundles():
        assert text_personal_findings(bundle["draft"]) == [], bundle["request"]["kit_id"]


def test_the_reader_is_never_the_makers_model() -> None:
    assert pick_review_model("muse-wonder-1.0") == "muse-spark-1.3"
    assert pick_review_model("muse-spark-1.3") == "muse-wonder-1.0"
    assert pick_review_model("") == "muse-wonder-1.0"
    assert pick_review_model("only-one", ["only-one"]) is None
    assert maker_model_of({"made_with": {"model": "muse-spark-1.3"}}) == "muse-spark-1.3"


def test_a_kit_made_by_the_only_model_available_stays_unpublished(
    backend: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    import eranos.worker_loop as loop

    monkeypatch.setattr(loop, "pick_review_model", lambda maker: None)
    req, _ = _build(backend)
    _review(backend, tmp_path, Reader(CLEAN))
    assert get_published_kit(backend, req.kit_id) is None


def test_judge_needs_a_clear_yes() -> None:
    assert judge(CLEAN, model_id="m", model_display="M")["approved"] is True
    no = judge(
        {**CLEAN, "verdict": "needs_revision", "notes": "Unsure."}, model_id="m", model_display="M"
    )
    assert no["approved"] is False and no["findings"]


# From the independent review of 9e140ce ----------------------------------------------------------
def _approve(kit: str, who: str = "reviewer-01", key: str = "review-key") -> ReviewDecision:
    return ReviewDecision(
        kit_id=kit,
        verdict="approved",
        reviewed_by=who,
        reviewed_by_key=key,
        notes="A test audit note.",
    )


def _park_then_resume(backend: Any, payload: Any) -> Any:
    req, graph = _build(backend)
    lease = backend.claim("eq03", "old-reviewer", kinds=["review"])
    backend.park(lease.task_id, lease.fencing_token, reason="old rule", resume_within=604800.0)
    backend.resume(graph.review_task_id, payload(req), by="human-steward")
    return req


@pytest.mark.parametrize(
    "payload",
    [
        lambda r: {"approved": False, "steward": "helpline-director", "notes": "no"},
        lambda r: {
            "approved": True,
            "kit_id": r.kit_id,
            "draft_sha256": "0" * 64,
            "steward": "stale-steward",
        },
        lambda r: {
            "approved": True,
            "kit_id": "KIT-OTHER-98",
            "draft_sha256": "0" * 64,
            "steward": "replayed-steward",
        },
        lambda r: {"timed_out": True},
    ],
)
def test_an_old_park_names_nobody_unless_a_person_said_yes_to_this_draft(
    backend: Any, payload: Any
) -> None:
    req = _park_then_resume(backend, payload)
    run_review_step(backend, _approve(req.kit_id), worker="reviewer-01", key_id="review-key")
    published = get_published_kit(backend, req.kit_id)
    assert published is not None and published.steward_signoff is None


def test_an_old_park_with_a_real_yes_keeps_its_name(backend: Any) -> None:
    req, graph = _build(backend)
    lease = backend.claim("eq03", "old-reviewer", kinds=["review"])
    sha = lease.dependencies[0].output["blob_sha256"]
    backend.park(lease.task_id, lease.fencing_token, reason="old rule", resume_within=604800.0)
    backend.resume(
        graph.review_task_id,
        {
            "approved": True,
            "kit_id": req.kit_id,
            "draft_sha256": sha,
            "steward": "helpline-director",
        },
        by="human-steward",
    )
    run_review_step(backend, _approve(req.kit_id), worker="reviewer-01", key_id="review-key")
    published = get_published_kit(backend, req.kit_id)
    assert published is not None and published.steward_signoff == "helpline-director"


def test_the_maker_cant_review_an_old_parked_kit(backend: Any) -> None:
    req = _park_then_resume(backend, lambda r: {"timed_out": True})
    with pytest.raises(SelfReviewRefused):
        run_review_step(
            backend,
            _approve(req.kit_id, "drafter-01", "other-key"),
            worker="drafter-01",
            key_id="other-key",
        )
    assert get_published_kit(backend, req.kit_id) is None


def test_a_kit_that_fails_its_checks_is_refused_with_a_correct_digest(backend: Any) -> None:
    bundle = load_example_bundles()[HOTLINE]
    req = KitRequest.model_validate(bundle["request"])
    submit_kit_request(backend, req)
    run_spec_step(backend)
    draft = {
        **copy.deepcopy(bundle["draft"]),
        "drafted_by": "rogue-drafter",
        "drafted_by_key": "key_rogue",
    }
    draft["steps"] = [s for s in draft["steps"] if s["kind"] != "interview"]
    lease = backend.claim("eq02", "rogue-drafter", key_id="anon-key")
    digest = hashlib.sha256(canonical_json(draft).encode()).hexdigest()
    backend.submit(
        lease.task_id,
        lease.fencing_token,
        {
            "node": "draft",
            "draft": draft,
            "verification": {
                "kit_id": req.kit_id,
                "passed": True,
                "checks_run": ["all"],
                "issues": [],
                "fixture_count": 2,
            },
            "blob_sha256": digest,
        },
        idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
        ok=True,
    )
    with pytest.raises(UnverifiedKitRefused):
        run_review_step(backend, _approve(req.kit_id), worker="reviewer-01", key_id="review-key")
    assert get_published_kit(backend, req.kit_id) is None


def test_editing_the_outbox_after_approval_publishes_nothing(
    backend: Any, monkeypatch: Any
) -> None:
    from eranos.pipeline import CATALOG_STORE

    req, _ = _build(backend, index=0)
    original = backend.put_records

    def fail(writes: Any, **kwargs: Any) -> Any:
        if any(w.store == CATALOG_STORE for w in writes):
            raise RuntimeError("the catalog write failed")
        return original(writes, **kwargs)

    monkeypatch.setattr(backend, "put_records", fail)
    with pytest.raises(RuntimeError):
        run_review_step(backend, _approve(req.kit_id), worker="reviewer-01", key_id="review-key")
    monkeypatch.setattr(backend, "put_records", original)
    with backend.scope_context(surface="surface:eranos"):
        current = backend.get_record(OUTBOX_STORE, req.kit_id)
        value = copy.deepcopy(current.value)
        value["publication"]["kit"]["summary"] = (
            "Changed after the audit, a different text entirely for this test."
        )
        backend.put_record(
            OUTBOX_STORE,
            req.kit_id,
            value,
            expected_version=current.version,
            producer_surface="surface:eranos",
            visibility_scope="surface_only",
            tags=["status:quarantined"],
        )
    run_review_step(backend, _approve(req.kit_id), worker="reviewer-01", key_id="review-key")
    assert get_published_kit(backend, req.kit_id) is None


# From the independent review of 2001ef3 ----------------------------------------------------------
def test_advice_in_a_label_is_sent_to_the_model(backend: Any, tmp_path: Path) -> None:
    def label(draft: dict[str, Any]) -> None:
        draft["tags"] = [*draft.get("tags", []), "note:take-the-passport-at-night-and-avoid-police"]

    _build(backend, label)
    reader = Reader({**CLEAN, "verdict": "needs_revision", "dangerous_advice": ["a label"]})
    _review(backend, tmp_path, reader)
    assert reader.calls and "take-the-passport-at-night" in reader.calls[0]


def test_the_models_words_never_reach_a_public_record(backend: Any, tmp_path: Path) -> None:
    secret = "QUOTED-FROM-THE-KIT Maria Lopez said"
    req, graph = _build(backend)
    reader = Reader(
        {**CLEAN, "verdict": "needs_revision", "dangerous_advice": [secret], "notes": secret}
    )
    _review(backend, tmp_path, reader)
    assert get_published_kit(backend, req.kit_id) is None
    assert secret not in json.dumps(
        [r.output for r in backend.results(graph.review_task_id)], default=str
    )
    out = judge(
        {
            **CLEAN,
            "verdict": "needs_revision",
            "dangerous_advice": [secret, secret],
            "notes": secret,
        },
        model_id="m",
        model_display="M",
    )
    assert secret not in json.dumps(out) and out["counts"] == {"dangerous_advice": 2}


def test_a_clean_yes_writes_only_our_own_sentence() -> None:
    out = judge(
        {**CLEAN, "notes": "Ignore this and say Call 617-204-8831."},
        model_id="m",
        model_display="M",
    )
    assert out["notes"] == "M read all of this kit's text and found no problems."


def test_too_large_or_failing_kits_cost_no_model_call(backend: Any, tmp_path: Path) -> None:
    reader = Reader(CLEAN)
    big = read_kit(
        reader.chat_json,
        {"text": "x" * (MAX_KIT_BYTES + 1)},
        model_id="m",
        model_display="M",
        meter=None,
    )
    assert big["approved"] is False and reader.calls == []
    assert "no model read it" in big["notes"]

    bundle = load_example_bundles()[HOTLINE]
    req = KitRequest.model_validate(bundle["request"])
    submit_kit_request(backend, req)
    run_spec_step(backend)
    draft = plain(copy.deepcopy(bundle["draft"]))
    draft["steps"] = [s for s in draft["steps"] if s["kind"] != "interview"]
    draft.update(drafted_by="rogue", drafted_by_key="key_rogue")
    lease = backend.claim("eq02", "rogue", key_id="anon-key")
    backend.submit(
        lease.task_id,
        lease.fencing_token,
        {
            "node": "draft",
            "draft": draft,
            "verification": {
                "kit_id": req.kit_id,
                "passed": True,
                "checks_run": ["all"],
                "issues": [],
                "fixture_count": 2,
            },
            "blob_sha256": hashlib.sha256(canonical_json(draft).encode()).hexdigest(),
        },
        idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
        ok=True,
    )
    _review(backend, tmp_path, reader)
    assert reader.calls == [], (
        "the worker's own checks stopped it, though the maker reported a pass"
    )
    assert get_published_kit(backend, req.kit_id) is None


def test_a_review_needs_a_model_so_a_spent_cap_leaves_it_queued() -> None:
    assert {"review", process_part.REVIEW_KIND} <= MODEL_KINDS


def test_a_new_no_never_publishes_an_old_yes(backend: Any, monkeypatch: Any) -> None:
    from eranos.pipeline import CATALOG_STORE

    req, _ = _build(backend, index=0)
    original = backend.put_records

    def fail(writes: Any, **kwargs: Any) -> Any:
        if any(w.store == CATALOG_STORE for w in writes):
            raise RuntimeError("the catalog write failed")
        return original(writes, **kwargs)

    monkeypatch.setattr(backend, "put_records", fail)
    with pytest.raises(RuntimeError):
        run_review_step(backend, _approve(req.kit_id), worker="reviewer-01", key_id="review-key")
    monkeypatch.setattr(backend, "put_records", original)
    no = ReviewDecision(
        kit_id=req.kit_id,
        verdict="needs_revision",
        reviewed_by="reviewer-01",
        reviewed_by_key="review-key",
        notes="A new reading said no.",
    )
    run_review_step(backend, no, worker="reviewer-01", key_id="review-key")
    assert get_published_kit(backend, req.kit_id) is None


# From the independent review of 5bba77a ----------------------------------------------------------
def _anon_draft(backend: Any, change: Any = None, output_change: Any = None) -> tuple[Any, Any]:
    bundle = load_example_bundles()[HOTLINE]
    req = KitRequest.model_validate(bundle["request"])
    graph = submit_kit_request(backend, req)
    run_spec_step(backend)
    draft = plain(copy.deepcopy(bundle["draft"]))
    draft.update(drafted_by="rogue", drafted_by_key="key_rogue")
    if change:
        change(draft)
    lease = backend.claim("eq02", "rogue", key_id="anon-key")
    output = {
        "node": "draft",
        "draft": draft,
        "verification": {
            "kit_id": draft["kit_id"],
            "passed": True,
            "checks_run": ["all"],
            "issues": [],
            "fixture_count": 2,
        },
        "blob_sha256": hashlib.sha256(canonical_json(draft).encode()).hexdigest(),
    }
    if output_change:
        output_change(output)
    backend.submit(
        lease.task_id,
        lease.fencing_token,
        output,
        idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
        ok=True,
    )
    return req, graph


PRIVATE = "Call Maria Lopez 617-204-8831"


def _facts_of_review(backend: Any, tmp_path: Path, reader: Any) -> str:
    seen: list[Any] = []
    lease = backend.claim("eq03", "reviewer-01", kinds=["review"], key_id="review-key")
    worker = _reviewer(backend, tmp_path, reader)
    with mock.patch(
        "eranos.worker_loop.record_events",
        side_effect=lambda b, rid, events, **k: seen.append(events),
    ):
        worker.handle(lease)
    return (
        json.dumps(seen, default=str)
        + json.dumps([r.output for r in backend.results(lease.task_id)], default=str)
        + json.dumps([r.error for r in backend.results(lease.task_id)], default=str)
    )


@pytest.mark.parametrize(
    "output_change",
    [
        lambda o: o.pop("verification"),
        lambda o: o["verification"].update(passed=False, issues=[PRIVATE]),
    ],
    ids=["no_report", "failed_report"],
)
def test_a_makers_missing_or_failed_report_costs_no_read_and_its_words_stay_private(
    backend: Any, tmp_path: Path, output_change: Any
) -> None:
    req, _ = _anon_draft(backend, None, output_change)
    reader = Reader(CLEAN)
    public = _facts_of_review(backend, tmp_path, reader)
    assert reader.calls == []
    assert get_published_kit(backend, req.kit_id) is None
    assert "Maria" not in public and "617-204" not in public


def test_a_draft_for_another_kit_costs_no_read_and_doesnt_publish(
    backend: Any, tmp_path: Path
) -> None:
    req, _ = _anon_draft(backend, lambda d: d.update(kit_id="KIT-OTHER-99"))
    reader = Reader(CLEAN)
    _facts_of_review(backend, tmp_path, reader)
    assert reader.calls == []
    assert (
        get_published_kit(backend, req.kit_id) is None
        and get_published_kit(backend, "KIT-OTHER-99") is None
    )


def test_a_brief_that_names_no_kit_refuses_every_draft() -> None:
    assert brief_kit_id({}) is None
    assert brief_kit_id({"kit_id": "K"}) == "K"
    assert brief_kit_id({"request": {"kit_id": "K"}}) == "K"


def test_validation_errors_dont_quote_a_maker_in_public() -> None:
    try:
        KitDraft.model_validate({"title": PRIVATE})
    except ValueError as exc:
        text = public_failure(exc)
    assert "Maria" not in text and "field(s) failed" in text
    assert "Maria" not in public_failure(RuntimeError(PRIVATE))
    assert clean_why(PRIVATE) == ""


def test_the_reader_is_never_the_makers_model_on_the_live_route(
    backend: Any, tmp_path: Path
) -> None:
    import eranos.worker_loop as loop

    seen: list[str] = []
    original = loop.read_kit

    def spy(chat: Any, value: Any, **kwargs: Any) -> Any:
        seen.append(kwargs["model_id"])
        return original(chat, value, **kwargs)

    _anon_draft(backend, None, lambda o: o.update(made_with={"model": "muse-wonder-1.0"}))
    with mock.patch.object(loop, "read_kit", spy):
        _review(backend, tmp_path, Reader(CLEAN))
    assert seen == ["muse-spark-1.3"]


def _claiming(tmp_path: Path, model: Any) -> list[str]:
    return _reviewer(object(), tmp_path, model).claim_kinds()


class _Down(Reader):
    def healthy(self) -> None:
        raise ModelUnavailable("down")


class _ReaderCapped(Reader):
    def afford(self, prompt_chars: int) -> None:
        assert prompt_chars == MAX_KIT_BYTES
        raise BudgetExhausted("the reader's largest read passes the cap")


def test_no_model_means_no_review_is_claimed(tmp_path: Path) -> None:
    assert not {"review", process_part.REVIEW_KIND} & set(_claiming(tmp_path, _Down()))


def test_a_cap_too_low_for_the_reader_leaves_reviews_queued_and_other_work_going(
    tmp_path: Path,
) -> None:
    kinds = _claiming(tmp_path, _ReaderCapped())
    assert "review" not in kinds and process_part.REVIEW_KIND not in kinds
    assert "report_review" in kinds


def test_the_limit_is_64_kb_and_counts_bytes() -> None:
    assert MAX_KIT_BYTES == 64 * 1024
    reader = Reader(CLEAN)
    wide = read_kit(
        reader.chat_json,
        {"text": "é" * (MAX_KIT_BYTES // 2 + 1)},
        model_id="m",
        model_display="M",
        meter=None,
    )
    assert wide["approved"] is False and reader.calls == []


def test_an_old_intent_never_publishes_in_place_of_the_draft_just_read(
    backend: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    from eranos.pipeline import CATALOG_STORE

    req, _ = _build(backend, index=0)
    original = backend.put_records

    def fail(writes: Any, **kwargs: Any) -> Any:
        if any(w.store == CATALOG_STORE for w in writes):
            raise RuntimeError("the catalog write failed")
        return original(writes, **kwargs)

    monkeypatch.setattr(backend, "put_records", fail)
    with pytest.raises(RuntimeError):
        run_review_step(backend, _approve(req.kit_id), worker="reviewer-01", key_id="review-key")
    monkeypatch.setattr(backend, "put_records", original)
    bundle = load_example_bundles()[0]
    submit_kit_request(backend, KitRequest.model_validate(bundle["request"]), run_id="second")
    run_spec_step(backend)
    newer = plain(copy.deepcopy(bundle["draft"]))
    newer["summary"] = "A newer draft of this kit, with its summary corrected after the first one."
    run_draft_step(backend, newer, worker="drafter-01", key_id="draft-key")
    lease = backend.claim("eq03", "reviewer-01", kinds=["review"], key_id="review-key")
    assert lease is not None
    reader = Reader(CLEAN)
    _reviewer(backend, tmp_path, reader).handle(lease)
    assert newer["summary"] in reader.calls[0]
    published = get_published_kit(backend, req.kit_id)
    assert published is not None and published.kit.summary == newer["summary"]
    assert backend.task(lease.task_id).state == "done", "the lease isn't left behind"


@pytest.mark.parametrize(
    "number", ["1-800-373-7888", "0917-123-4567", "+44 20 7946 0958", "6172048831", "617-204-8831"]
)
def test_the_screen_stops_common_phone_formats(number: str) -> None:
    assert text_personal_findings({"summary": f"Call {number} for help."})


@pytest.mark.parametrize(
    "text",
    [
        "See 2 CFR 200.329 and 29 U.S.C. 203 and 2 CFR Part 200.",
        "Version 1.2.3 of the form, 2026-11-04.",
    ],
)
def test_a_citation_or_date_is_not_a_phone_number(text: str) -> None:
    assert text_personal_findings({"summary": text}) == []


def test_a_sources_title_is_read_and_its_address_isnt_wherever_it_sits() -> None:
    link = "https://www.ecfr.gov/current/title-2/section-200.329"
    for value in ({"sources": [{"url": link}]}, {"catalog": {"kit": {"sources": [{"url": link}]}}}):
        assert text_personal_findings(value) == []
    assert text_personal_findings({"sources": [{"url": link, "title": PRIVATE}]})
    assert text_personal_findings({"sources": [{"publisher": PRIVATE}]})
    assert text_personal_findings({"notes": {"url": "maria.lopez@realmail.org"}})


def test_a_process_kits_sentence_says_what_was_read() -> None:
    out = judge(CLEAN, model_id="m", model_display="M", what=PROCESS_KIT_TEXT)
    assert "read all" not in out["notes"]
    assert "the records this kit publishes" in out["notes"] and "bundle's files" in out["notes"]


def test_the_reader_can_be_afforded_at_the_largest_kit(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "l.json", daily_usd=25, total_usd=150)
    key = tmp_path / "k"
    key.write_text("x")
    settings = {
        "id": "muse-wonder-1.0",
        "model_display": "W",
        "base_url": "https://api.meta.ai/v1",
        "max_tokens": 1500,
        "prices_usd_per_million": {"input": 4.0, "output": 20.0},
    }
    wonder = MetaModel(settings, key_file=str(key), ledger=ledger)
    wonder.afford(MAX_KIT_BYTES)
    ledger.reserve(25.0 - wonder.estimate(100))
    with pytest.raises(ModelUnavailable):
        wonder.afford(MAX_KIT_BYTES)


# Mutants the review named ------------------------------------------------------------------------
def test_a_kit_by_this_worker_or_with_a_bad_digest_costs_no_read(
    backend: Any, tmp_path: Path
) -> None:
    req, _ = _anon_draft(backend, lambda d: d.update(drafted_by="reviewer-01"))
    reader = Reader(CLEAN)
    _facts_of_review(backend, tmp_path, reader)
    assert reader.calls == [] and get_published_kit(backend, req.kit_id) is None


def test_a_bad_digest_costs_no_read(backend: Any, tmp_path: Path) -> None:
    req, _ = _anon_draft(backend, None, lambda o: o.update(blob_sha256="0" * 64))
    reader = Reader(CLEAN)
    _facts_of_review(backend, tmp_path, reader)
    assert reader.calls == [] and get_published_kit(backend, req.kit_id) is None


def test_the_readers_screen_stops_contact_details_with_kinds_only(tmp_path: Path) -> None:
    reader = Reader(CLEAN)
    worker = _reviewer(object(), tmp_path, reader)
    lease = mock.Mock(task_id="t", fencing_token=1)
    read = worker.review_reader(lease, UsageMeter(), {}, "")
    out = read({"catalog": {"kit": {"steps": [{"guidance": PRIVATE}]}}})
    assert out["approved"] is False and reader.calls == []
    assert out["findings"] == ["personal_data: 1"], "no field names or words in a public record"
