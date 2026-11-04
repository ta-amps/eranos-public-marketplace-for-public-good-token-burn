"""Tests for the two-step Tessera pipeline: quarantine, drafter != reviewer, parker != resumer, and CAS store."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tessera import RecordWrite

from eranos.adapter import TracedBackend
from eranos.adapter import local as local_adapter
from eranos.cli import main as cli_main
from eranos.donor_worker import (
    DRAFTER_QUEUES,
    REVIEWER_QUEUES,
    ContributorModelRefused,
    check_donor_model,
    issue_drafter_key,
    issue_reviewer_key,
    run_donor_demo,
)
from eranos.pipeline import (
    CATALOG_STORE,
    SelfReviewError,
    SelfReviewRefused,
    UnverifiedKitRefused,
    get_published_kit,
    list_published_kits,
    load_example_bundles,
    run_draft_step,
    run_review_step,
    run_spec_step,
    submit_kit_request,
)
from eranos.schemas import KitRequest, ReviewDecision


@pytest.fixture
def backend(tmp_path: Path) -> TracedBackend:
    store = local_adapter.create(str(tmp_path / "eranos.db"))
    return TracedBackend(store, backend="local", trace_path=str(tmp_path / "trace.jsonl"))


def test_two_step_pipeline_publishes_verified_kit_to_cas_store(
    backend: TracedBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    try:
        bundle = load_example_bundles()[0]
        req = KitRequest.model_validate(bundle["request"])
        submit_kit_request(backend, req)

        spec_out = run_spec_step(backend, worker="spec-01")
        assert spec_out is not None and spec_out["kit_id"] == req.kit_id
        assert spec_out["visibility_scope"] == "surface_only"
        assert "status:quarantined" in spec_out["tags"]

        draft_out = run_draft_step(
            backend, bundle["draft"], worker="drafter-01", key_id="key_drafter_01"
        )
        assert draft_out is not None and draft_out["verification"]["passed"] is True
        assert draft_out["visibility_scope"] == "surface_only"
        assert "status:quarantined" in draft_out["tags"]
        # Unreviewed drafts must NEVER enter eranos.catalog
        assert list_published_kits(backend) == []

        feed_events: list[tuple[str, dict[str, Any]]] = []
        monkeypatch.setattr(
            backend,
            "publish_feed",
            lambda feed, payload, **_kw: feed_events.append((feed, payload)),
            raising=False,
        )

        rev_out = run_review_step(
            backend,
            ReviewDecision.model_validate(bundle["review"]),
            worker="reviewer-02",
            key_id="key_reviewer_02",
        )
        assert rev_out is not None and rev_out["status"] == "published"
        assert len(feed_events) == 1
        assert feed_events[0][0] == "noun.promotions"
        assert feed_events[0][1]["kit_id"] == req.kit_id
        assert feed_events[0][1]["visibility_scope"] == "public_commons"

        stored = get_published_kit(backend, req.kit_id)
        assert stored is not None
        assert stored.kit.drafted_by == "drafter-01"
        assert stored.reviewed_by == "reviewer-02"
        assert stored.visibility_scope == "public_commons"
        assert "status:verified" in stored.tags
        assert "status:quarantined" not in stored.tags
        assert stored.catalog_version == 1
        assert stored.blob_sha256 is not None
        assert len(backend.get_blob(stored.blob_sha256)) > 100
    finally:
        backend.close()


def test_quarantined_records_never_leak_into_public_catalog_queries(backend: TracedBackend) -> None:
    try:
        bundle = load_example_bundles()[0]
        # Simulate a corrupted/unreviewed record written with status:quarantined in the store
        forged_record = {
            "kit": {
                **bundle["draft"],
                "drafted_by": "d-1",
                "drafted_by_key": "k-1",
                "visibility_scope": "surface_only",
                "tags": ["status:quarantined"],
            },
            "verification": {
                "kit_id": bundle["request"]["kit_id"],
                "passed": True,
                "checks_run": ["all"],
                "issues": [],
                "fixture_count": 2,
                "human_only_steps": ["worker_interview"],
            },
            "reviewed_by": "r-2",
            "reviewed_by_key": "k-2",
            "review_notes": "Forged entry",
            "visibility_scope": "surface_only",
            "tags": ["status:quarantined"],
            "catalog_version": 1,
        }
        backend.put_records(
            [
                RecordWrite(
                    store=CATALOG_STORE,
                    key="KIT-QUARANTINE-99",
                    value=forged_record,
                    expected_version=0,
                )
            ]
        )
        assert list_published_kits(backend) == []
        assert get_published_kit(backend, "KIT-QUARANTINE-99") is None
    finally:
        backend.close()


def test_self_review_by_same_worker_or_key_is_refused(backend: TracedBackend) -> None:
    try:
        bundle = load_example_bundles()[0]
        req = KitRequest.model_validate(bundle["request"])
        submit_kit_request(backend, req)
        run_spec_step(backend)
        run_draft_step(backend, bundle["draft"], worker="agent-alpha", key_id="key_alpha")

        with pytest.raises(SelfReviewRefused):
            run_review_step(
                backend,
                ReviewDecision.model_validate(bundle["review"]),
                worker="agent-alpha",
                key_id="key_beta",
            )
        assert list_published_kits(backend) == []
    finally:
        backend.close()


def test_all_three_drafter_reviewer_and_parker_resumer_bypasses_closed(
    backend: TracedBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    try:
        # (a) Key scoping: drafters get eq01/eq02 ONLY; reviewers get eq03 ONLY
        assert DRAFTER_QUEUES == ("eq01", "eq02")
        assert REVIEWER_QUEUES == ("eq03",)
        captured_keys: list[tuple[str, list[str]]] = []

        class FakeKeyStore:
            def issue_key(
                self,
                label: str,
                *,
                queues: list[str],
                effect_classes: list[str] | None = None,
                scopes: list[str] | None = None,
            ) -> tuple[str, Any]:
                assert scopes == ["store", "surface:eranos"]
                assert effect_classes == ["read", "write-internal"]
                captured_keys.append((label, list(queues)))
                return (f"tok_{label}", SimpleNamespace(key_id=f"id_{label}"))

        ks = FakeKeyStore()
        issue_drafter_key(ks, "drafter")
        issue_reviewer_key(ks, "reviewer")
        assert captured_keys == [
            ("drafter", ["eq01", "eq02"]),
            ("reviewer", ["eq03"]),
        ]

        # (b) Spoofed draft payload identity cannot bypass Tessera task completed_by_key / worker check
        bundle = load_example_bundles()[0]
        req = KitRequest.model_validate(bundle["request"])
        graph = submit_kit_request(backend, req, run_id="run-spoof")
        run_spec_step(backend, worker="spec-bot")
        lease = backend.claim("eq02", "colluding-worker")
        assert lease is not None
        spoofed_draft = {
            **bundle["draft"],
            "drafted_by": "innocent-other-worker",
            "drafted_by_key": "innocent-other-key",
        }
        backend.submit(
            lease.task_id,
            lease.fencing_token,
            {
                "node": "draft",
                "draft": spoofed_draft,
                "verification": {
                    "kit_id": req.kit_id,
                    "passed": True,
                    "checks_run": ["all"],
                    "issues": [],
                    "fixture_count": 2,
                },
                "blob_sha256": "b" * 64,
                "needs_steward_signoff": False,
            },
            idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
            ok=True,
        )

        # Colluding worker tries to review its own eq02 task under spoofed draft metadata
        with pytest.raises(SelfReviewError):
            run_review_step(
                backend,
                ReviewDecision(
                    kit_id=req.kit_id,
                    verdict="approved",
                    reviewed_by="colluding-worker",
                    reviewed_by_key="key_rev_99",
                    notes="Self-review attempt.",
                ),
                worker="colluding-worker",
                key_id="key_rev_99",
            )

        # Also verify completed_by_key from backend.results(draft_id) blocks matching reviewer key
        orig_results = backend.results
        monkeypatch.setattr(
            backend,
            "results",
            lambda tid: (
                [SimpleNamespace(completed_by_key="key_collude_77", worker="someone-else")]
                if tid == graph.draft_task_id
                else orig_results(tid)
            ),
            raising=False,
        )
        submit_kit_request(backend, req, run_id="run-key-spoof")
        run_spec_step(backend, worker="spec-bot")
        run_draft_step(backend, bundle["draft"], worker="drafter-clean", key_id="key_drafter_clean")
        # Force results on the new draft task to expose completed_by_key="key_collude_77"
        monkeypatch.setattr(
            backend,
            "results",
            lambda _tid: [SimpleNamespace(completed_by_key="key_collude_77")],
            raising=False,
        )
        with pytest.raises(SelfReviewError):
            run_review_step(
                backend,
                ReviewDecision(
                    kit_id=req.kit_id,
                    verdict="approved",
                    reviewed_by="distinct-worker",
                    reviewed_by_key="key_collude_77",
                    notes="Matching completed_by_key must fail.",
                ),
                worker="distinct-worker",
                key_id="key_collude_77",
            )
    finally:
        backend.close()


def test_a_kit_audited_by_a_different_worker_publishes_with_no_persons_step(
    backend: TracedBackend,
) -> None:
    """Owner, Nov 3: sensitive tracks too, and an old request that still carries the flag."""
    bundle = load_example_bundles()[1]  # KIT-HOTLINE-02, a sensitive track
    request = {**bundle["request"], "needs_steward_signoff": True}
    req = KitRequest.model_validate(request)
    graph = submit_kit_request(backend, req)
    run_spec_step(backend)
    run_draft_step(backend, bundle["draft"], worker="drafter-01", key_id="key_d1")
    _, rev_grant = issue_reviewer_key(backend._inner, "rev-01")  # type: ignore[attr-defined]
    rev_key_id = str(rev_grant.key_id)
    out = run_review_step(
        backend,
        ReviewDecision(
            kit_id=req.kit_id,
            verdict="approved",
            reviewed_by="reviewer-01",
            reviewed_by_key=rev_key_id,
            notes="Audited by a different worker.",
        ),
        worker="reviewer-01",
        key_id=rev_key_id,
    )
    assert out is not None and out["status"] != "parked"
    assert backend.task(graph.review_task_id).parks == 0
    published = get_published_kit(backend, req.kit_id)
    assert published is not None
    assert published.reviewed_by == "reviewer-01"
    assert published.steward_signoff is None


def test_no_track_or_example_holds_a_kit_for_a_person() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in [*root.glob("tracks/*/track.json"), *root.glob("examples/kits/*.json")]:
        text = path.read_text(encoding="utf-8")
        assert '"needs_steward_signoff": true' not in text, path
        assert "park_for_steward" not in text, path


def test_unverified_draft_cannot_be_approved(backend: TracedBackend) -> None:
    try:
        bundle = load_example_bundles()[0]
        req = KitRequest.model_validate(bundle["request"])
        submit_kit_request(backend, req)
        run_spec_step(backend)

        broken_draft = {
            **bundle["draft"],
            "steps": [s for s in bundle["draft"]["steps"] if s["kind"] != "interview"],
        }
        # Layer 1: normal draft step submits ok=False, keeping eq03 blocked in Tessera.
        draft_out = run_draft_step(backend, broken_draft, worker="drafter-01", key_id="key_d1")
        assert draft_out is not None and draft_out["verification"]["passed"] is False
        assert (
            run_review_step(
                backend,
                ReviewDecision.model_validate(bundle["review"]),
                worker="reviewer-02",
                key_id="key_r2",
            )
            is None
        )
        assert list_published_kits(backend) == []

        # Layer 2: even if an untrusted drafter worker bypasses run_draft_step and submits ok=True
        # with a forged verification report, run_review_step re-verifies deterministically.
        submit_kit_request(backend, req, run_id="run-forged")
        run_spec_step(backend)
        forged_lease = backend.claim("eq02", "rogue-drafter")
        assert forged_lease is not None
        forged_draft = {
            **broken_draft,
            "drafted_by": "rogue-drafter",
            "drafted_by_key": "key_rogue",
        }
        backend.submit(
            forged_lease.task_id,
            forged_lease.fencing_token,
            {
                "node": "draft",
                "draft": forged_draft,
                "verification": {
                    "kit_id": req.kit_id,
                    "passed": True,
                    "checks_run": ["boundary_rules"],
                    "issues": [],
                    "fixture_count": 2,
                },
                "blob_sha256": "a" * 64,
                "needs_steward_signoff": False,
            },
            idempotency_key=f"{forged_lease.task_id}:{forged_lease.fencing_token}",
            ok=True,
        )

        with pytest.raises(UnverifiedKitRefused):
            run_review_step(
                backend,
                ReviewDecision.model_validate(bundle["review"]),
                worker="reviewer-02",
                key_id="key_r2",
            )
        assert list_published_kits(backend) == []
    finally:
        backend.close()


def test_cli_practice_and_verify_examples_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli_main(["practice", "examples/kits/01-job-recruitment-triage.json", "--dry-run"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["persisted"] is False
    assert len(payload["receipt_sha256"]) == 64

    rc2 = cli_main(["verify-examples", "--dry-run"])
    assert rc2 == 0
    _ = capsys.readouterr()


def test_donor_worker_refuses_contributor_tier_models() -> None:
    check_donor_model("muse-spark-1.3")
    with pytest.raises(ContributorModelRefused):
        check_donor_model("muse-spark-1.3-contributor")


def test_donor_demo_synthesizes_verifies_and_publishes_with_distinct_keys() -> None:
    out = run_donor_demo(dry_model=True)
    assert out["ok"] is True
    assert out["kit_id"] == "KIT-DONOR-90"
    assert out["drafted_by"] == "opencode-donor-01"
    assert out["reviewed_by"] == "volunteer-reviewer-02"
    assert out["eq03_scope_blocked"] is True
    assert out["catalog_version"] == 1
    assert out["jobs_recorded"] == 1


def test_review_is_bound_and_publication_recovers_after_store_failure(
    backend: TracedBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tessera import NotFound

    from eranos.pipeline.publication import OUTBOX_STORE

    bundle = load_example_bundles()[0]
    req = KitRequest.model_validate(bundle["request"])
    graph = submit_kit_request(backend, req)
    run_spec_step(backend)
    run_draft_step(backend, bundle["draft"], worker="draft-synthetic", key_id="draft-synthetic-key")
    decision = ReviewDecision.model_validate(bundle["review"])
    original = backend.put_records

    def fail_catalog(writes: Any, **kwargs: Any) -> Any:
        if any(w.store == CATALOG_STORE for w in writes):
            raise RuntimeError("SYNTHETIC persistence failure")
        return original(writes, **kwargs)

    monkeypatch.setattr(backend, "put_records", fail_catalog)
    with pytest.raises(RuntimeError, match="persistence failure"):
        run_review_step(backend, decision, worker="review-synthetic", key_id="review-synthetic-key")
    assert backend.task(graph.review_task_id).state == "done"
    assert (
        backend.results(graph.review_task_id)[-1].output["status"] == "approved_pending_publication"
    )
    with pytest.raises(NotFound):
        backend.get_record(CATALOG_STORE, req.kit_id)
    with backend.scope_context(surface="surface:eranos"):
        assert backend.get_record(OUTBOX_STORE, req.kit_id).value["status"] == "pending"
    monkeypatch.setattr(backend, "put_records", original)
    recovered = run_review_step(
        backend, decision, worker="review-synthetic", key_id="review-synthetic-key"
    )
    assert recovered is not None and recovered["status"] == "published"
    assert recovered["published"]["catalog_version"] == 1
    assert (
        run_review_step(backend, decision, worker="review-synthetic", key_id="review-synthetic-key")
        is None
    )


def test_wrong_kit_approval_and_negative_steward_resume_do_not_publish(
    backend: TracedBackend,
) -> None:
    bundle = load_example_bundles()[0]
    req = KitRequest.model_validate(bundle["request"])
    submit_kit_request(backend, req)
    run_spec_step(backend)
    run_draft_step(backend, bundle["draft"], worker="draft-synthetic", key_id="draft-key")
    wrong = ReviewDecision.model_validate({**bundle["review"], "kit_id": "KIT-OTHER-98"})
    with pytest.raises(UnverifiedKitRefused, match="leased kit"):
        run_review_step(backend, wrong, worker="review-synthetic", key_id="review-key")
    assert get_published_kit(backend, req.kit_id) is None

    # A fresh backend avoids the deliberately rejected task's retry ordering.
    backend.close()


def test_a_reviewer_asking_to_park_sends_the_kit_back_and_nothing_publishes(
    backend: TracedBackend,
) -> None:
    bundle = load_example_bundles()[1]
    req = KitRequest.model_validate(bundle["request"])
    graph = submit_kit_request(backend, req)
    run_spec_step(backend)
    run_draft_step(backend, bundle["draft"], worker="drafter-01", key_id="draft-key")
    decision = ReviewDecision(
        kit_id=req.kit_id,
        verdict="park_for_steward",
        reviewed_by="reviewer-01",
        reviewed_by_key="review-key",
        notes="Not sure about this one.",
    )
    out = run_review_step(backend, decision, worker="reviewer-01", key_id="review-key")
    assert out is not None and out["status"] == "needs_revision"
    assert get_published_kit(backend, req.kit_id) is None
    assert backend.task(graph.review_task_id).parks == 0
