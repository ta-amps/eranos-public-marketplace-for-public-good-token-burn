"""The solution path for public-only requests: an independent review that re-checks every citation
of a research report, then delivers it to the requester as a noun (`eranos.solutions/<report_id>`).

Guardrails, from the `eranos.instructions/public-research` noun the check verb copied into the
brief: no personal data; no platform reached against its terms (for example, Facebook and Instagram
only through Meta's official tools, never scraping); every claim cites a public source with an exact
quote; legal summaries say they are not legal advice; a person decides what to do with the result.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

from tessera import NotFound
from tessera.receipts import canonical_json

from eranos.copy import find_accusatory_words
from eranos.pipeline.request_noun import PRODUCER, update_request_part
from eranos.pipeline.run import SelfReviewRefused, _claim_with_key
from eranos.privacy import personal_data_findings

SOLUTIONS_STORE = "eranos.solutions"
# A quote shorter than this must be a whole sentence of its source, so that a fragment such as
# "be" cannot "verify" a claim; every quote must match whole words of the source.
MIN_QUOTE = 20
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_DIGEST = re.compile(r"[0-9a-f]{64}")
# Public contact details a verified source quote may carry into a report; nothing else personal.
CONTACT_KINDS = frozenset({"a phone number", "a street address"})


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


def quote_finding(cid: str, sid: str, quote: str, text: str) -> str | None:
    """Why a quote cannot verify a claim from source text, or None when it can."""
    quote = quote.strip()
    if not quote:
        return f"claim {cid} gives no quote from source {sid}"
    sentences = {sentence.strip() for sentence in _SENTENCE_END.split(text)}
    if len(quote) < MIN_QUOTE and quote not in sentences:
        return (
            f"claim {cid}: the quote from source {sid} is too short to check; quote at least"
            f" {MIN_QUOTE} characters or a whole sentence"
        )
    if not re.search(rf"(?<!\w){re.escape(quote)}(?!\w)", text):
        return f"claim {cid}: the quote is not in source {sid}"
    return None


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
    verified: set[str] = set()
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
            elif problem := quote_finding(cid, sid, quote, str(known[sid].get("text", ""))):
                findings.append(problem)
            else:
                verified.add(quote.strip())
    # The report is delivered to the public commons, so every string in it is screened. Text that
    # repeats a verified source quote is the source's own words: it may carry the source's public
    # phone numbers and addresses, never any other personal data.
    quoted = sorted(verified, key=len, reverse=True)

    def own(text: str) -> str:
        for quote in quoted:
            text = text.replace(quote, " ")
        return text

    # A source's SHA-256 digests are identifiers, not personal data: a 64-hex value under a
    # `*_sha256` key is not screened, so a digest that starts with 13 digits is not a card number.
    strings = {
        k: v
        for k, v in _strings(report, "report").items()
        if not (k.endswith("_sha256") and _DIGEST.fullmatch(v))
        # A DOI's digits are an article's address, not a card number.
        and not (k.endswith(".url") and v.startswith("https://doi.org/10."))
    }
    findings += personal_data_findings({k: own(v) for k, v in strings.items()})
    findings += [
        finding
        for finding in personal_data_findings(
            {f"cited quote {i + 1}": q for i, q in enumerate(quoted)}
        )
        if finding.split(": ", 1)[1] not in CONTACT_KINDS
    ]
    own_words = " ".join(
        own(v) for k, v in strings.items() if not k.endswith((".quote", ".question", ".title"))
    )
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
        "audit_status": "audited",
        "next_step": "A person at the nonprofit decides what to do with this result.",
    }
    sources = [s for s in report.get("sources") or [] if isinstance(s, dict)]
    # Plain words on public records: a report built only from made-up samples says so.
    value["made_up_sample"] = bool(sources) and all(
        s.get("made_up_sample") is True or s.get("synthetic") is True for s in sources
    )
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
