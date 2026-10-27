"""Tests for the two-step Tessera pipeline: drafter != reviewer, park/resume steward sign-off, and CAS store."""

from __future__ import annotations

from pathlib import Path

import pytest

from eranos.adapter import TracedBackend
from eranos.adapter import local as local_adapter
from eranos.donor_worker import ContributorModelRefused, check_donor_model, run_donor_demo
from eranos.pipeline import (
    SelfReviewRefused,
    UnverifiedKitRefused,
    get_published_kit,
    list_published_kits,
    load_example_bundles,
    resume_steward_signoff,
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


def test_two_step_pipeline_publishes_verified_kit_to_cas_store(backend: TracedBackend) -> None:
    try:
        bundle = load_example_bundles()[0]
        req = KitRequest.model_validate(bundle["request"])
        submit_kit_request(backend, req)

        spec_out = run_spec_step(backend, worker="spec-01")
        assert spec_out is not None and spec_out["kit_id"] == req.kit_id

        draft_out = run_draft_step(
            backend, bundle["draft"], worker="drafter-01", key_id="key_drafter_01"
        )
        assert draft_out is not None and draft_out["verification"]["passed"] is True

        rev_out = run_review_step(
            backend,
            ReviewDecision.model_validate(bundle["review"]),
            worker="reviewer-02",
            key_id="key_reviewer_02",
        )
        assert rev_out is not None and rev_out["status"] == "published"

        stored = get_published_kit(backend, req.kit_id)
        assert stored is not None
        assert stored.kit.drafted_by == "drafter-01"
        assert stored.reviewed_by == "reviewer-02"
        assert stored.catalog_version == 1
        assert stored.blob_sha256 is not None
        assert len(backend.get_blob(stored.blob_sha256)) > 100
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


def test_steward_signoff_parks_and_resumes_on_tessera(backend: TracedBackend) -> None:
    try:
        bundle = load_example_bundles()[1]  # KIT-HOTLINE-02 requires steward signoff
        req = KitRequest.model_validate(bundle["request"])
        graph = submit_kit_request(backend, req)
        run_spec_step(backend)
        run_draft_step(backend, bundle["draft"], worker="drafter-01", key_id="key_d1")

        first = run_review_step(
            backend,
            ReviewDecision.model_validate(bundle["review"]),
            worker="reviewer-01",
            key_id="key_r1",
        )
        assert first is not None and first["status"] == "parked"
        assert list_published_kits(backend) == []

        resume_steward_signoff(
            backend,
            graph.review_task_id,
            steward="helpline-director",
            notes="Verified human-only crisis steps.",
        )
        second = run_review_step(
            backend,
            ReviewDecision(
                kit_id=req.kit_id,
                verdict="approved",
                reviewed_by="reviewer-01",
                reviewed_by_key="key_r1",
                notes="Approved following steward sign-off.",
            ),
            worker="reviewer-01",
            key_id="key_r1",
        )
        assert second is not None and second["status"] == "published"
        published = get_published_kit(backend, req.kit_id)
        assert published is not None and published.steward_signoff == "helpline-director"
    finally:
        backend.close()


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


def test_donor_worker_refuses_contributor_tier_models() -> None:
    check_donor_model("muse-spark-open")
    with pytest.raises(ContributorModelRefused):
        check_donor_model("muse-spark-open-contributor")


def test_donor_demo_synthesizes_verifies_and_publishes_with_distinct_keys() -> None:
    out = run_donor_demo(dry_model=True)
    assert out["ok"] is True
    assert out["kit_id"] == "KIT-DONOR-90"
    assert out["drafted_by"] == "opencode-donor-01"
    assert out["reviewed_by"] == "ollama-reviewer-02"
    assert out["eq03_scope_blocked"] is True
    assert out["catalog_version"] == 1
    assert out["jobs_recorded"] == 1
