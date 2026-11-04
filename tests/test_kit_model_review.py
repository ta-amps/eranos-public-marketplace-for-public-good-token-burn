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
from eranos.pipeline.model_review import judge, maker_model_of, pick_review_model
from eranos.pipeline.publication import OUTBOX_STORE
from eranos.privacy import text_personal_findings
from eranos.schemas import KitDraft, KitRequest, ReviewDecision
from eranos.tracks import get_track
from eranos.verifier import verify_kit
from eranos.worker_loop import Worker, WorkerConfig, plain

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
    assert json.loads(reader.calls[0])["kit"]["summary"], "the model is sent the kit's text"
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
