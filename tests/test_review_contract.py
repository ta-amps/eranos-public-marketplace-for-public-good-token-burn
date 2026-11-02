"""Review and practice use the candidate, schema and provider identity they advertise."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from eranos.donor_worker import _call_chat_model, synthesize_review_decision
from eranos.pipeline import load_example_bundles
from eranos.schemas import KitDraft
from eranos.tracks import get_track
from eranos.verifier import practice_verify_kit, verify_kit

ROOT = Path(__file__).resolve().parents[1]


def test_live_call_needs_its_configured_endpoint_and_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is no default provider: without an endpoint, or without a key, no request leaves."""
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    calls: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda request: calls.append(request))  # type: ignore[arg-type,func-returns-value]
    with pytest.raises(ValueError, match="endpoint"):
        _call_chat_model(
            model="muse-spark-1.3",
            prompt_payload={"practice": True},
            api_key="practice-marker",
            transport=transport,
        )
    with pytest.raises(RuntimeError, match="MODEL_API_KEY"):
        _call_chat_model(
            model="muse-spark-1.3",
            prompt_payload={"practice": True},
            base_url="https://models.example/v1",
            transport=transport,
        )
    assert calls == []


def test_review_receives_candidate_and_can_reject_without_fabricating_usage() -> None:
    draft = KitDraft.model_validate(
        {
            **load_example_bundles()[0]["draft"],
            "drafted_by": "synthetic-drafter",
            "drafted_by_key": "synthetic-draft-key",
        }
    )
    report = verify_kit(draft, get_track(draft.track_id))
    seen: list[dict[str, object]] = []

    def provider(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(json.loads(request.content)["messages"][1]["content"])
        seen.append(prompt)
        answer = {
            "kit_id": draft.kit_id,
            "draft_sha256": prompt.get("draft_sha256"),
            "verdict": "needs_revision",
            "notes": "SYNTHETIC reviewer requests stronger provenance.",
        }
        return httpx.Response(
            200,
            json={
                "id": "synthetic-review",
                "choices": [{"message": {"content": json.dumps(answer)}}],
            },
        )

    transport = httpx.MockTransport(provider)
    decision = synthesize_review_decision(
        draft,
        report,
        worker="synthetic-reviewer",
        key_id="synthetic-review-key",
        dry_model=False,
        base_url="https://models.example/v1",
        api_key="synthetic-marker",
        transport=transport,
    )
    assert decision.verdict == "needs_revision"
    assert seen[0]["draft"] == draft.model_dump(mode="json")
    assert seen[0]["verification"] == report.model_dump(mode="json")
    _, _, input_tokens, output_tokens = _call_chat_model(
        model="muse-spark-1.3",
        prompt_payload={"SYNTHETIC": True},
        base_url="https://models.example/v1",
        api_key="synthetic-marker",
        transport=transport,
    )
    assert input_tokens is None and output_tokens is None


def test_worker_schema_matches_python_and_invalid_skill_is_rejected() -> None:
    schema = json.loads((ROOT / "deploy/cloudflare/kit-draft.schema.json").read_text())
    assert schema == KitDraft.model_json_schema()
    draft = {
        **load_example_bundles()[0]["draft"],
        "title": "",
        "skill": {},
        "tools": [],
        "tool": None,
    }
    assert practice_verify_kit(draft)["passed"] is False
    script = f"""
import worker from {json.dumps((ROOT / "deploy/cloudflare/worker.js").as_uri())};
const r=await worker.fetch(new Request('https://eranosforgood.org/api/practice',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{draft:{json.dumps(draft)}}})}}),{{}});
console.log(JSON.stringify(await r.json()));
"""
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True
    )
    result = json.loads(run.stdout)
    assert result["passed"] is False
    assert result["persisted"] is False
    assert any("skill" in issue for issue in result["issues"])


def test_practice_receipt_is_explicitly_an_outcome_not_a_content_digest() -> None:
    original = load_example_bundles()[0]["draft"]
    revised = {**original, "summary": "SYNTHETIC revised public-good workflow summary."}
    first = practice_verify_kit(original)
    second = practice_verify_kit(revised)
    assert first["passed"] is True and second["passed"] is True
    assert first["receipt_sha256"] == second["receipt_sha256"]
    assert first["receipt_scope"] == second["receipt_scope"] == "validation_outcome"
    assert first["artifact_bound"] is second["artifact_bound"] is False
    script = """
import worker from WORKER;
const out=[];
for (const draft of DRAFTS) {
 const response=await worker.fetch(new Request("https://eranosforgood.org/api/practice",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({draft})}),{});
 out.push(await response.json());
}
console.log(JSON.stringify(out));
""".replace("WORKER", json.dumps((ROOT / "deploy/cloudflare/worker.js").as_uri())).replace(
        "DRAFTS", json.dumps([original, revised])
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True
    )
    results = json.loads(run.stdout)
    assert all(item["passed"] and item["persisted"] is False for item in results)
    assert all(
        item["receipt_scope"] == "validation_outcome" and item["artifact_bound"] is False
        for item in results
    )
    assert results[0]["receipt_sha256"] == results[1]["receipt_sha256"]
