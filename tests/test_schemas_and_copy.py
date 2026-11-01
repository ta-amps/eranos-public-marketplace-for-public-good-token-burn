"""Tests for Ring 0 copy rules, governance envelope, human_only step invariants, synthetic marks, and strict JSON."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from eranos.copy import check_non_accusatory, check_safe_topic, find_accusatory_words
from eranos.jsonfile import loads_strict
from eranos.pipeline import load_example_bundles
from eranos.schemas import (
    OPEN_SPDX_ALLOWLIST,
    KitDraft,
    KitRequest,
    PublishedKit,
    SyntheticFixture,
    VerificationReport,
    WorkflowStep,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_accusatory_words_are_blocked() -> None:
    assert find_accusatory_words("Check whether the fee exceeds 10%.") == []
    assert find_accusatory_words("This firm is a scammer and criminal.") == ["criminal", "scammer"]
    with pytest.raises(ValueError, match="non-accusatory"):
        check_non_accusatory("Label the recruiter a trafficker.")


def test_prohibited_collection_topics_are_blocked() -> None:
    assert (
        check_safe_topic("Route caller to a verified public hotline.")
        == "Route caller to a verified public hotline."
    )
    with pytest.raises(ValueError, match="prohibited topic"):
        check_safe_topic("Build a grooming kit sample archive.")


def test_interviews_and_decisions_must_stay_human_only() -> None:
    for kind in ("interview", "crisis_safety_plan", "individual_decision", "external_send"):
        with pytest.raises(ValidationError, match="human_only"):
            WorkflowStep(
                id="bad_step",
                title="Automated client interview",
                kind=kind,
                boundary="drafts",
                actor="Agent",
                guidance="Ask the person questions directly.",
            )


def test_synthetic_fixture_requires_synthetic_mark() -> None:
    with pytest.raises(ValidationError, match="practice-case mark"):
        SyntheticFixture(
            id="FX-NO-MARK",
            scenario="Missing synthetic prefix",
            sample_input="Contract states monthly salary HKD 5,000.",
            expected_indicators=[],
            expected_human_escalation=False,
        )


def test_published_kit_refuses_same_drafter_and_reviewer() -> None:
    bundle = load_example_bundles()[0]
    draft = KitDraft.model_validate(
        {**bundle["draft"], "drafted_by": "worker-01", "drafted_by_key": "key-01"}
    )
    report = VerificationReport(
        kit_id=draft.kit_id,
        passed=True,
        checks_run=["all"],
        fixture_count=2,
        human_only_steps=["worker_interview"],
    )
    with pytest.raises(ValidationError, match="two-step rule violated"):
        PublishedKit(
            kit=draft,
            verification=report,
            reviewed_by="worker-01",
            reviewed_by_key="key-02",
            review_notes="Looks fine to me.",
        )
    with pytest.raises(ValidationError, match="two-step rule violated"):
        PublishedKit(
            kit=draft,
            verification=report,
            reviewed_by="worker-02",
            reviewed_by_key="key-01",
            review_notes="Same key used twice.",
        )


def test_governance_envelope_spdx_allowlist_and_quarantine_guard() -> None:
    assert set(OPEN_SPDX_ALLOWLIST) == {
        "Apache-2.0",
        "MIT",
        "BSD-3-Clause",
        "CC-BY-4.0",
        "CC0-1.0",
    }
    bundle = load_example_bundles()[0]
    req = KitRequest.model_validate(bundle["request"])
    assert req.spdx_license in OPEN_SPDX_ALLOWLIST
    assert "all" in req.target_cohorts
    assert req.producer_surface == "surface:eranos"
    assert req.visibility_scope == "public_commons"
    assert "surface:eranos" in req.allowed_surfaces

    with pytest.raises(ValidationError, match="spdx_license"):
        KitRequest.model_validate({**bundle["request"], "spdx_license": "GPL-3.0-only"})

    with pytest.raises(ValidationError, match="key:value"):
        KitRequest.model_validate({**bundle["request"], "tags": ["malformed_tag_without_colon"]})

    quarantined_draft = KitDraft.model_validate(
        {
            **bundle["draft"],
            "drafted_by": "worker-01",
            "drafted_by_key": "key-01",
            "visibility_scope": "surface_only",
            "tags": ["status:quarantined", "domain:anti_exploitation"],
        }
    )
    report = VerificationReport(
        kit_id=quarantined_draft.kit_id,
        passed=True,
        checks_run=["all"],
        fixture_count=2,
        human_only_steps=["worker_interview"],
    )
    with pytest.raises(ValidationError, match=r"quarantined|surface_only"):
        PublishedKit(
            kit=quarantined_draft,
            verification=report,
            reviewed_by="worker-02",
            reviewed_by_key="key-02",
            review_notes="Attempted publish without clearing quarantine.",
        )


def test_strict_json_rejects_duplicate_keys_and_nan() -> None:
    with pytest.raises(ValueError, match="duplicate JSON key"):
        loads_strict('{"a": 1, "a": 2}')
    with pytest.raises(ValueError, match="non-finite"):
        loads_strict('{"a": NaN}')


def test_zero_em_dashes_across_repository() -> None:
    em_dash = chr(0x2014)
    escaped_em = "\\" + "u2014"
    skip_dirs = {
        ".git",
        ".venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".eranos",
    }
    offenders: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if em_dash in text or escaped_em in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"Em-dash characters found in: {offenders}"
