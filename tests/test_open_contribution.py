"""The two-sided marketplace end to end on a local Tessera and Eranos (`make e2e`), plus the abuse
cases: nothing is published without review by a different worker, no namespace leaks, personal data
is refused and quotas hold. Everything here is SYNTHETIC; no model is called."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from eranos.e2e import run_local
from eranos.intake import FormIncomplete, parse_issue_form
from eranos.nouns import instruction_nouns
from eranos.pipeline.requests import classify_parts
from eranos.pipeline.solutions import report_findings
from eranos.privacy import personal_data_findings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def flow() -> tuple[dict[str, Any], list[str]]:
    lines: list[str] = []
    seen = run_local(lines.append)
    return seen, lines


def test_typing_a_request_enqueues_exactly_one_verb(flow: tuple[dict[str, Any], list[str]]) -> None:
    seen, lines = flow
    assert seen["one_verb_each"] == 3
    assert any(line.startswith("[12] done") for line in lines)


def test_classify_then_split_routes_public_private_and_mixed_requests(
    flow: tuple[dict[str, Any], list[str]],
) -> None:
    seen, _ = flow
    routes = {name: [p["route"] for p in info["plan"]] for name, info in seen["asks"].items()}
    assert routes == {
        "public": ["public-only"],
        "private": ["private-files"],
        "mixed": ["public-only", "private-files"],
        "form": ["private-files"],
    }
    for info in seen["asks"].values():
        for part in info["plan"]:
            assert part["work_task_id"] != part["review_task_id"]
            assert ("report_id" in part) == (part["route"] == "public-only")
            assert ("kit_id" in part) == (part["route"] == "private-files")
    assert seen["asks"]["form"]["plan"][0]["needs_person_signoff"] is True
    plain = " ".join(seen["asks"]["mixed"]["plain"])
    assert "We'll do this part from public information" in plain
    assert "This part touches your files, so we'll build a kit your own agent runs" in plain


def test_only_reviewed_work_is_published_or_delivered(
    flow: tuple[dict[str, Any], list[str]],
) -> None:
    seen, _ = flow
    q = seen["quarantine"]
    assert q["in_catalog"] is False and q["public_read"] == 404
    assert q["stranger"] == 401 and q["other_session"] == 404 and q["requester_child"] == 404
    assert q["verb_visibility"] == "allowlist_surfaces"
    assert q["completed_by"].startswith("a_")
    for info in seen["asks"].values():
        for part in info["plan"]:
            assert part["review"]["status"] in {"published", "delivered"}
    assert seen["catalog_size"] == seen["examples"] + 3  # the examples plus three reviewed kits


def test_abuse_cases_hold(flow: tuple[dict[str, Any], list[str]]) -> None:
    seen, _ = flow
    abuse = seen["abuse"]
    assert abuse["anonymous_publish"] == 403
    assert abuse["anonymous_review_claim"] == 403
    assert abuse["requester_claim"] == 403
    assert abuse["anonymous_quota"] == 429
    assert abuse["requester_quota"][-1] == 429
    assert abuse["personal_data_request_verb"] == 400
    assert abuse["personal_data_request"] == ["job: an email address", "job: a phone number"]
    assert seen["quarantine"]["other_ngo_request"] == 404
    assert seen["quarantine"]["other_ngo_namespace"] == 403


def test_the_nonprofit_receives_results_as_nouns_in_its_namespace(
    flow: tuple[dict[str, Any], list[str]],
) -> None:
    seen, _ = flow
    received = seen["received"]
    assert received["public"]["followed"]["request"]["status"] == "closed"
    report = next(n for n in received["public"]["nouns"] if n["kind"] == "report")
    claims = report["report"]["claims"]
    assert claims and all(c["citations"] for c in claims)
    assert "not legal advice" in report["report"]["disclaimer"]
    assert "A person decides" in report["report"]["decision"]
    kit = next(n for n in received["private"]["nouns"] if n["kind"] == "kit")
    assert kit["nouns"]["steps"] and kit["nouns"]["fixtures"]
    assert all("SYNTHETIC" in f["sample_input"] for f in kit["nouns"]["fixtures"])
    assert sorted(n["kind"] for n in received["mixed"]["nouns"]) == ["kit", "report"]


def test_report_guardrails_refuse_scraping_uncited_claims_and_missing_disclaimers() -> None:
    rules = instruction_nouns()["public-research"]
    source = {
        "id": "S1",
        "title": "SYNTHETIC bill",
        "url": "https://example.org/synthetic/bill",
        "access": "official_download",
        "public": True,
        "synthetic": True,
        "text": "SYNTHETIC stand-in text. Landlords must give 60 days of notice.",
    }
    brief = {"report_id": "RPT-X-01", "legal": True, "guardrails": rules, "sources": [source]}
    good = {
        "report_id": "RPT-X-01",
        "sources": [source],
        "claims": [
            {
                "id": "C1",
                "text": "Landlords must give 60 days of notice.",
                "citations": [{"source": "S1", "quote": "Landlords must give 60 days of notice."}],
            }
        ],
        "summary": "One cited point.",
        "decision": rules["decision"],
        "disclaimer": rules["disclaimer_text"],
    }
    assert report_findings(good, brief) == []
    scraped = {"id": "S2", "url": "https://www.facebook.com/somepage", "access": "scrape"}
    cases = {
        "scraping a platform": {**good, "sources": [source, scraped]},
        "an uncited claim": {**good, "claims": [{"id": "C1", "text": "x", "citations": []}]},
        "a quote not in the source": {
            **good,
            "claims": [
                {"id": "C1", "text": "x", "citations": [{"source": "S1", "quote": "invented"}]}
            ],
        },
        "no disclaimer": {**good, "disclaimer": ""},
        "no person decides": {**good, "decision": ""},
        "personal data": {**good, "summary": "Ask person@real.invalid"},
    }
    for name, report in cases.items():
        assert report_findings(report, brief), name


def test_personal_data_screen_names_kinds_never_text() -> None:
    found = personal_data_findings(
        {
            "job": "Write to person@mail.invalid or 555-201-3344, @somebody, 123-45-6789,"
            " 4111 1111 1111 1111, 12 Main Street, DOB 1990",
            "notes": "Name: Someone\nName: SYNTHETIC Person",
        }
    )
    assert len(found) == 8 and not any("person@" in f or "555" in f for f in found)
    clean = {"job": "SYNTHETIC: write to help@example.org about 60 days of notice in 2026."}
    assert personal_data_findings(clean) == []


def test_classify_routes_unclear_text_to_the_nonprofit() -> None:
    rules = instruction_nouns()["classify"]
    assert [p["route"] for p in classify_parts("Make our week easier.", rules)] == ["private-files"]
    parts = classify_parts(
        "Summarize new laws on deposits. Then compare our donor records with them.", rules
    )
    assert [(p["route"], p["legal"]) for p in parts] == [
        ("public-only", True),
        ("private-files", False),
    ]


def test_issue_form_needs_both_confirmations() -> None:
    body = (ROOT / "examples" / "requests" / "tenant-laws.md").read_text()
    assert parse_issue_form(body)["organization_type"] == "Legal-aid or rights clinic"
    with pytest.raises(FormIncomplete):
        parse_issue_form(body.replace("- [X]", "- [ ]"))


def test_nonprofit_page_text_never_asks_to_pick_a_verb_or_a_kit() -> None:
    noun = instruction_nouns()["nonprofits"]
    form = noun["form"]
    shown = " ".join(str(v) for v in form.values() if isinstance(v, str))
    assert form["label"] == "Tell us what you need"
    assert "verb" not in shown.lower()
    page = (ROOT / "web" / "src" / "pages" / "Nonprofits.tsx").read_text(encoding="utf-8")
    for choice in ("Request a verb", "Request a kit", "request a verb", "request a kit"):
        assert choice not in page


@pytest.mark.parametrize("tamper", ["digest", "kit"])
def test_a_review_refuses_a_build_whose_digest_or_kit_does_not_match(
    tmp_path: Path, tamper: str
) -> None:
    from tessera import Store

    from eranos.contributor import build_kit, draft_digest
    from eranos.nouns import seed_nouns
    from eranos.pipeline import run_review_step
    from eranos.pipeline.requests import run_request_check, submit_request
    from eranos.pipeline.run import UnverifiedKitRefused, ensure_queues
    from eranos.schemas import ReviewDecision

    store = Store(str(tmp_path / "review.db"))
    try:
        ensure_queues(store)
        with store.scope_context(surface="surface:eranos"):
            seed_nouns(store)
        body = (ROOT / "examples" / "requests" / "shift-reminders.md").read_text()
        submit_request(store, parse_issue_form(body))
        split = run_request_check(store, worker="classifier", key_id="k_classifier")
        assert split is not None and split["status"] == "split"
        lease = store.claim("eq02", "builder", kinds=["build"], key_id="a_builder")
        assert lease is not None
        draft = build_kit(lease.brief, worker="builder", principal_id="a_builder")
        if tamper == "kit":
            draft = {**draft, "kit_id": "KIT-OTHER-01"}
        report = {
            "kit_id": draft["kit_id"],
            "passed": True,
            "checks_run": ["all"],
            "issues": [],
            "fixture_count": 2,
        }
        digest = "0" * 64 if tamper == "digest" else draft_digest(draft)
        store.submit(
            lease.task_id,
            lease.fencing_token,
            {"node": "draft", "draft": draft, "verification": report, "blob_sha256": digest},
            idempotency_key="build",
            completed_by_key="a_builder",
        )
        decision = ReviewDecision(
            kit_id=draft["kit_id"],
            verdict="approved",
            reviewed_by="reviewer",
            reviewed_by_key="k_reviewer",
            notes="SYNTHETIC review.",
        )
        with pytest.raises(UnverifiedKitRefused):
            run_review_step(store, decision, worker="reviewer", key_id="k_reviewer")
        assert store.list_records("eranos.catalog") == []
    finally:
        store.close()
