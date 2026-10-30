"""The solution path for public-only requests: an independent review that re-checks every citation
of a research report, then delivers it to the requester as a noun (`eranos.solutions/<report_id>`).

Guardrails, from the `eranos.instructions/public-research` noun the check verb copied into the
brief: no personal data; no platform reached against its terms (for example, Facebook and Instagram
only through Meta's official tools, never scraping); every claim cites a public source with an exact
quote; legal summaries say they are not legal advice; a person decides what to do with the result.
"""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlsplit

from tessera import NotFound
from tessera.receipts import canonical_json

from eranos.copy import find_accusatory_words
from eranos.pipeline.request_noun import PRODUCER, update_request_part
from eranos.pipeline.run import SelfReviewRefused, _claim_with_key
from eranos.privacy import personal_data_findings

SOLUTIONS_STORE = "eranos.solutions"


def report_digest(report: Any) -> str:
    return hashlib.sha256(canonical_json(report).encode("utf-8")).hexdigest()


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _strings(value: Any, path: str) -> dict[str, str]:
    """Every string in a report, keys included, by its path (`sources.0.title`)."""
    if isinstance(value, str):
        return {path: value}
    if isinstance(value, dict):
        out: dict[str, str] = {}
        for key, item in value.items():
            out[f"{path}.{key}:key"] = str(key)
            out.update(_strings(item, f"{path}.{key}"))
        return out
    if isinstance(value, list):
        return {
            k: v for i, item in enumerate(value) for k, v in _strings(item, f"{path}.{i}").items()
        }
    return {}


def report_findings(report: Any, brief: dict[str, Any]) -> list[str]:
    """Every reason this report cannot be delivered; an empty list means it may be."""
    if not isinstance(report, dict):
        return ["the report must be an object"]
    rules = brief.get("guardrails") or {}
    access = rules.get("access") or {}
    allowed = set(access.get("allowed") or [])
    platforms: dict[str, list[str]] = access.get("platforms") or {}
    known = {str(s.get("id")): s for s in brief.get("sources") or [] if isinstance(s, dict)}
    findings: list[str] = []
    if report.get("report_id") != brief.get("report_id"):
        findings.append("the report does not answer this brief")
    sources = {str(s.get("id")): s for s in report.get("sources") or [] if isinstance(s, dict)}
    for sid, source in sources.items():
        url, how = str(source.get("url") or ""), str(source.get("access") or "")
        # Only the brief's sources can be checked: their address and text came with the brief.
        if sid not in known:
            findings.append(
                f"source {sid} is not one of the brief's sources, so its quotes cannot be checked;"
                " a person must review it"
            )
        elif url.strip() != str(known[sid].get("url") or "").strip():
            findings.append(f"source {sid} does not point where the brief's source {sid} does")
        if urlsplit(url).scheme != "https" or source.get("public") is False:
            findings.append(f"source {sid} is not a public https source")
        host = _host(url)
        platform = next((p for p in platforms if host == p or host.endswith("." + p)), None)
        if platform is not None and how not in platforms[platform]:
            findings.append(
                f"source {sid} reaches {platform} without its permitted official access"
            )
        elif how not in allowed:
            findings.append(f"source {sid} uses access {how!r}, which is not permitted")
    claims = report.get("claims")
    if not isinstance(claims, list) or not claims:
        findings.append("the report makes no cited claims")
        claims = []
    for claim in claims:
        cid = str(claim.get("id") if isinstance(claim, dict) else "?")
        citations = claim.get("citations") if isinstance(claim, dict) else None
        if not isinstance(citations, list) or not citations:
            findings.append(f"claim {cid} cites no source")
            continue
        for citation in citations:
            sid = str(citation.get("source") if isinstance(citation, dict) else "")
            quote = str(citation.get("quote") or "") if isinstance(citation, dict) else ""
            if sid not in sources:
                findings.append(f"claim {cid} cites unknown source {sid!r}")
            elif sid not in known:
                findings.append(f"claim {cid} cites source {sid}, which the brief did not give")
            elif not quote or quote not in str(known[sid].get("text", "")):
                findings.append(f"claim {cid}: the quote is not in source {sid}")
    # The report is delivered to the public commons, so every string in it is screened.
    strings = _strings(report, "report")
    findings += personal_data_findings(strings)
    own_words = " ".join(v for k, v in strings.items() if not k.endswith(".quote"))
    if words := find_accusatory_words(own_words):
        findings.append(f"report uses accusatory words ({', '.join(words)})")
    disclaimer = str(rules.get("legal_disclaimer") or "not legal advice")
    if brief.get("legal") and disclaimer.lower() not in str(report.get("disclaimer") or "").lower():
        findings.append("a legal summary must say it is not legal advice")
    decision = str(rules.get("decision") or "A person decides")
    if decision.lower() not in str(report.get("decision") or "").lower():
        findings.append("the report must say that a person decides what to do with it")
    return findings


def run_report_review(backend: Any, *, worker: str, key_id: str) -> dict[str, Any] | None:
    """Claim one report review, re-check every citation and guardrail, then deliver or return it."""
    lease = _claim_with_key(backend, "eq03", worker, key_id=key_id, kinds=["report_review"])
    if lease is None:
        return None
    research = lease.dependencies[0]
    out = research.output if isinstance(research.output, dict) else {}
    brief = dict(backend.task(research.task_id).brief)
    request_id, report_id = str(lease.brief["request_id"]), str(lease.brief["report_id"])
    part = lease.brief.get("part")
    researcher = getattr(research, "completed_by_key", None)
    ref = f"{lease.task_id}:{lease.fencing_token}"
    if not key_id.strip() or not researcher or researcher == key_id:
        backend.submit(
            lease.task_id,
            lease.fencing_token,
            {"node": "report_review", "status": "rejected_self_review", "report_id": report_id},
            idempotency_key=ref,
            ok=False,
            error="the worker that researched a report may not review it",
        )
        raise SelfReviewRefused(f"reviewer key {key_id!r} researched {report_id}")
    report = out.get("report")
    findings = report_findings(report, brief)
    if out.get("blob_sha256") != report_digest(report):
        findings.append("blob_sha256 is not the digest of the submitted report")
    if findings:
        receipt = backend.submit(
            lease.task_id,
            lease.fencing_token,
            {
                "node": "report_review",
                "status": "needs_revision",
                "report_id": report_id,
                "findings": findings,
            },
            idempotency_key=ref,
            ok=True,
        )
        update_request_part(backend, request_id, part, "needs_revision", findings=findings)
        return {"status": "needs_revision", "findings": findings, "receipt": receipt.receipt_hash}
    digest = report_digest(report)
    receipt = backend.submit(
        lease.task_id,
        lease.fencing_token,
        {
            "node": "report_review",
            "status": "accepted",
            "accepted": True,
            "report_id": report_id,
            "research_task_id": research.task_id,
            "research_receipt": research.receipt_hash,
            "report_sha256": digest,
        },
        idempotency_key=ref,
        ok=True,
    )
    delivered = deliver_report(
        backend,
        report=dict(report) if isinstance(report, dict) else {},
        request_id=request_id,
        review_task_id=lease.task_id,
        review_receipt=receipt.receipt_hash,
        research_receipt=research.receipt_hash,
        digest=digest,
        part=part,
    )
    return {"status": "delivered", "receipt": receipt.receipt_hash, **delivered}


def deliver_report(
    backend: Any,
    *,
    report: dict[str, Any],
    request_id: str,
    review_task_id: str,
    review_receipt: str,
    research_receipt: str | None,
    digest: str,
    part: Any = None,
) -> dict[str, Any]:
    """Deliver the reviewed report to the requester as a public noun, bound to its receipts."""
    report_id = str(report["report_id"])
    value = {
        "schema_version": 1,
        "request_id": request_id,
        "report": report,
        "report_sha256": digest,
        "review_task_id": review_task_id,
        "review_receipt": review_receipt,
        "research_receipt": research_receipt,
        "next_step": "A person at the nonprofit decides what to do with this result.",
    }
    sources = [s for s in report.get("sources") or [] if isinstance(s, dict)]
    value["synthetic"] = bool(sources) and all(s.get("synthetic") is True for s in sources)
    try:
        version = backend.get_record(SOLUTIONS_STORE, report_id).version
    except NotFound:
        version = 0
    saved = backend.put_record(
        SOLUTIONS_STORE,
        report_id,
        value,
        expected_version=version,
        producer_surface=PRODUCER,
        visibility_scope="public_commons",
        tags=["state:delivered", "kind:public_report"],
    )
    update_request_part(
        backend,
        request_id,
        part,
        "delivered",
        solution={"store": SOLUTIONS_STORE, "key": report_id, "version": saved.version},
        review_receipt=review_receipt,
    )
    return {"report_id": report_id, "solution_version": saved.version}
