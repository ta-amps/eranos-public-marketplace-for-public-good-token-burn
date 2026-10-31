"""Information parts answered from permitted public sources, with a quote for every claim.

- The planner writes a research brief naming what may be fetched: the request's own https links and
  the official open APIs whose topics fit the part (`eranos.instructions/worker` noun).
- The builder fetches each permitted source once, keeps it as a source noun with its SHA-256
  digests, and gives the local model numbered sentences from it. The model proposes claims, each
  resting on one sentence with an exact quote. A deterministic checker keeps a claim only when its
  quote is verbatim in the fetched text, its own words come from that quote, and it carries no
  personal data or accusation. The report passes the same `report_findings` rules as any report.
- The reviewer, a different key, fetches every cited source again and re-checks every quote and
  guardrail against the fresh text before the report is delivered (`deliver_report`).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from tessera import NotFound

from eranos.copy import find_accusatory_words
from eranos.model_client import ChatModel, UsageMeter
from eranos.pipeline.request_noun import PRODUCER, update_request_part
from eranos.pipeline.requests import INSTRUCTIONS_STORE, _common_brief
from eranos.pipeline.run import SelfReviewRefused
from eranos.pipeline.solutions import deliver_report, quote_finding, report_digest, report_findings
from eranos.privacy import personal_data_findings
from eranos.sources import Fetched, SourceRefused, api_query_url, permitted_api, source_record

SOURCES_STORE = "eranos.sources"
BRIEF_KIND = "eranos.public_research"
Fetcher = Callable[[str], Fetched]
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-z0-9][a-z0-9()'-]*")
_STOP = frozenset(
    [
        "about",
        "after",
        "also",
        "because",
        "before",
        "being",
        "between",
        "both",
        "could",
        "does",
        "each",
        "every",
        "from",
        "have",
        "into",
        "just",
        "like",
        "make",
        "many",
        "more",
        "most",
        "must",
        "need",
        "only",
        "other",
        "over",
        "please",
        "same",
        "should",
        "some",
        "such",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "very",
        "want",
        "what",
        "when",
        "where",
        "which",
        "while",
        "will",
        "with",
        "would",
        "your",
        "under",
        "also",
        "shall",
        "such",
        "were",
        "been",
        "here",
        "http",
        "https",
        "www",
        "summarize",
        "summary",
        "citation",
        "citations",
        "point",
        "points",
        "overview",
        "explain",
        "month",
        "monthly",
        "week",
        "weekly",
        "list",
        "relevant",
        "link",
        "links",
        "quote",
        "quotes",
        "source",
        "sources",
    ]
)


def words(text: str) -> set[str]:
    out = set()
    for word in _WORD.findall(text.lower()):
        word = word.strip("'-()")
        if len(word) < 4 or word in _STOP:
            continue
        for suffix in ("ing", "ies", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[: -len(suffix)]
                break
        out.add(word)
    return out


def select_apis(text: str, apis: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wanted = words(text)
    return [api for api in apis if wanted & words(" ".join(api.get("topics") or []))]


def query_terms(text: str, limit: int = 6) -> list[str]:
    seen: list[str] = []
    for word in _WORD.findall(text.lower()):
        word = word.strip("'-") if "(" in word else word.strip("'-()")
        if len(word) >= 4 and word not in _STOP and word not in seen and not word.isdigit():
            seen.append(word)
    return seen[:limit]


def research_brief(
    request_id: str,
    part: dict[str, Any],
    org: str,
    guardrails: dict[str, Any],
    worker_rules: dict[str, Any],
    links: list[str],
    terms: dict[str, Any] | None = None,
    occurrence: int = 1,
) -> dict[str, Any]:
    """A research verb's whole input: the question, the guardrails and what may be fetched."""
    brief = {**(terms or {}), **_common_brief(request_id, part, org, "RPT")}
    report_id = str(brief.pop("noun_id")) + (f"-O{occurrence}" if occurrence > 1 else "")
    rules = worker_rules.get("sources") or {}
    apis = select_apis(part["text"], list(rules.get("official_apis") or []))
    return {
        **brief,
        "report_id": report_id,
        "occurrence": occurrence,
        "kind": BRIEF_KIND,
        "question": part["text"][:600],
        "legal": bool(part.get("legal")),
        "guardrails": guardrails,
        "fetch": {
            "links": [link for link in links if link.startswith("https://")][:10],
            "apis": [
                {k: api[k] for k in ("id", "publisher", "host", "path_prefixes", "access", "query")}
                for api in apis
            ],
            "query_terms": query_terms(part["text"]),
            "max_sources": int(rules.get("max_sources") or 5),
            "max_text_chars": int(rules.get("max_text_chars") or 60000),
        },
        "stages": [
            "fetch the permitted sources",
            "propose claims with exact quotes",
            "keep verbatim quotes only",
            "summarize",
        ],
        "output": {
            "node": "report",
            "report": "report_id, request_id, title, question, sources (with url and SHA-256), claims (each with citations: source and exact quote), summary, decision, and the disclaimer when legal",
            "blob_sha256": "sha256 of the report as canonical JSON: sorted keys, no spaces, UTF-8",
        },
        "instructions": {"store": INSTRUCTIONS_STORE, "key": "public-research"},
    }


def review_brief(brief: dict[str, Any]) -> dict[str, Any]:
    keys = ("request_id", "part", "report_id", "title", "legal", "occurrence")
    return {k: brief[k] for k in keys if k in brief} | {
        "kind": "eranos.report_review",
        "recheck": "fetch every cited source again",
    }


def permitted_urls(brief: dict[str, Any]) -> list[tuple[str, str, str | None]]:
    """(url, access, publisher) the brief lets this verb fetch, in order."""
    fetch = brief.get("fetch") or {}
    out: list[tuple[str, str, str | None]] = [
        (link, "public_web_page", None) for link in fetch.get("links") or []
    ]
    for api in fetch.get("apis") or []:
        url = api_query_url(api, list(fetch.get("query_terms") or []))
        out.append((url, str(api.get("access") or "official_api"), api.get("publisher")))
    return out[: int(fetch.get("max_sources") or 5)]


def is_permitted(url: str, brief: dict[str, Any], allowlist: list[dict[str, Any]]) -> bool:
    fetch = brief.get("fetch") or {}
    if url in (fetch.get("links") or []):
        return True
    return (
        permitted_api(url, allowlist) is not None
        and permitted_api(url, list(fetch.get("apis") or [])) is not None
    )


def gather(brief: dict[str, Any], fetcher: Fetcher) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch every permitted source once; failures are kept as reasons, never hidden."""
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    for number, (url, access, publisher) in enumerate(permitted_urls(brief), start=1):
        try:
            fetched = fetcher(url)
        except (SourceRefused, RuntimeError, ValueError) as exc:
            failures.append(f"source {number}: {exc}")
            continue
        record = source_record(
            fetched,
            source_id=f"SRC-{brief['report_id']}-{number}",
            access=access,
            publisher=publisher,
            max_text_chars=int((brief.get("fetch") or {}).get("max_text_chars") or 60000),
            request_id=str(brief["request_id"]),
            part=brief.get("part"),
        )
        if record["text"].strip():
            records.append(record)
        else:
            failures.append(f"source {number}: no text could be extracted")
    return records, failures


def candidate_sentences(
    sources: list[dict[str, Any]], question: str, limit: int
) -> list[dict[str, Any]]:
    """Numbered sentences that share words with the question, best first, at most 12 per source."""
    wanted = words(question)
    picked: list[tuple[int, int, int, dict[str, Any]]] = []
    for s_index, source in enumerate(sources, start=1):
        scored = []
        position = 0
        seen: set[str] = set()
        for line in str(source["text"]).split("\n"):
            for sentence in _SENTENCE.split(line):
                sentence = sentence.strip()
                position += 1
                if not 40 <= len(sentence) <= 400 or len(sentence.split()) < 6:
                    continue
                if sentence in seen or not sentence.rstrip("\"')").endswith((".", "!", "?")):
                    continue  # headings and repeated lines are not claims
                seen.add(sentence)
                overlap = len(wanted & words(sentence))
                if overlap:
                    scored.append((overlap, position, sentence))
        scored.sort(key=lambda item: (-item[0], item[1]))
        for rank, (overlap, position, sentence) in enumerate(scored[:12]):
            picked.append(
                (
                    overlap,
                    s_index,
                    position,
                    {"source": source["id"], "s": s_index, "text": sentence, "rank": rank},
                )
            )
    picked.sort(key=lambda item: (-item[0], item[1], item[2]))
    chosen = sorted(picked[:limit], key=lambda item: (item[1], item[2]))
    counters: dict[int, int] = {}
    out = []
    for _, s_index, _, entry in chosen:
        counters[s_index] = counters.get(s_index, 0) + 1
        out.append({**entry, "id": f"S{s_index}-{counters[s_index]}"})
    return out


def prompt_text(
    rules: dict[str, Any],
    question: str,
    sentences: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> tuple[str, str]:
    research = rules.get("research") or {}
    system = "\n".join(research.get("prompt") or []).replace(
        "{max_claims}", str(research.get("max_claims") or 8)
    )
    titles = {s["id"]: s.get("title") or s.get("publisher") for s in sources}
    lines = [f"Question: {question}", "", "Sentences:"]
    lines += [f"[{s['id']}] ({titles.get(s['source'])}) {s['text']}" for s in sentences]
    return system, "\n".join(lines)


def check_claims(
    proposed: Any,
    sentences: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    rules: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Keep a proposed claim only when its quote is verbatim and its words come from the quote."""
    research = rules.get("research") or {}
    overlap_needed = float(research.get("support_overlap") or 0.5)
    by_id = {s["id"]: s for s in sentences}
    texts = {s["id"]: str(s["text"]) for s in sources}
    items = proposed.get("claims") if isinstance(proposed, dict) else None
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            dropped.append({"sentence": "?", "reason": "not an object"})
            continue
        sid = str(item.get("sentence") or "")
        quote = " ".join(str(item.get("quote") or "").split())
        claim = " ".join(str(item.get("claim") or "").split())
        entry = by_id.get(sid)
        if entry is None:
            dropped.append({"sentence": sid, "reason": "names no numbered sentence"})
            continue
        source_id = entry["source"]
        if problem := quote_finding(sid, source_id, quote, texts[source_id]):
            dropped.append({"sentence": sid, "reason": "quote not verbatim: " + problem})
            continue
        claim_words = words(claim)
        if not claim or not claim_words:
            dropped.append({"sentence": sid, "reason": "no claim text"})
            continue
        if len(claim_words & words(quote)) / len(claim_words) < overlap_needed:
            dropped.append({"sentence": sid, "reason": "the claim says more than its quote"})
            continue
        if find_accusatory_words(claim) or personal_data_findings({"claim": claim}):
            dropped.append({"sentence": sid, "reason": "accusatory words or personal data"})
            continue
        if quote in seen:
            dropped.append({"sentence": sid, "reason": "repeats a kept quote"})
            continue
        seen.add(quote)
        kept.append(
            {
                "id": f"C{len(kept) + 1}",
                "text": claim,
                "citations": [{"source": source_id, "quote": quote}],
            }
        )
        if len(kept) >= int(research.get("max_claims") or 8):
            break
    return kept, dropped


def build_report(
    brief: dict[str, Any],
    sources: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    stages: dict[str, Any],
) -> dict[str, Any]:
    rules = brief.get("guardrails") or {}
    cited = {c["citations"][0]["source"] for c in claims}
    used = [s for s in sources if s["id"] in cited]
    report: dict[str, Any] = {
        "report_id": brief["report_id"],
        "request_id": brief["request_id"],
        "title": brief["title"],
        "question": brief["question"],
        "sources": [
            {
                k: s[k]
                for k in (
                    "id",
                    "title",
                    "publisher",
                    "url",
                    "access",
                    "public",
                    "synthetic",
                    "fetched_at",
                    "text_sha256",
                    "raw_sha256",
                    "extractor",
                )
            }
            | {"published": None}
            for s in used
        ],
        "claims": claims,
        "summary": f"{len(claims)} cited points from {len(used)} public sources. "
        + " ".join(c["text"] for c in claims[:3]),
        "decision": str(rules.get("decision", "")),
        "stages": stages,
    }
    if brief.get("occurrence", 1) > 1:
        report["occurrence"] = brief["occurrence"]
    if brief.get("legal"):
        report["disclaimer"] = str(rules.get("disclaimer_text", "This is not legal advice."))
    return report


def store_sources(backend: Any, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep each fetched source as a noun for provenance (surface-only: the public report quotes it)."""
    refs = []
    for source in sources:
        try:
            version = backend.get_record(SOURCES_STORE, source["id"]).version
        except NotFound:
            version = 0
        saved = backend.put_record(
            SOURCES_STORE,
            source["id"],
            source,
            expected_version=version,
            producer_surface=PRODUCER,
            visibility_scope="surface_only",
            tags=["kind:source_observation", "access:" + str(source["access"])],
        )
        refs.append({"store": SOURCES_STORE, "key": source["id"], "version": int(saved.version)})
    return refs


def do_research(
    backend: Any,
    lease: Any,
    *,
    fetcher: Fetcher,
    model: ChatModel,
    meter: UsageMeter,
    worker_rules: dict[str, Any],
) -> dict[str, Any]:
    """The builder's research work: {output, self_test, artifact_refs, summary}."""
    brief = dict(lease.brief)
    research = worker_rules.get("research") or {}
    sources, failures = gather(brief, fetcher)
    sentences = candidate_sentences(
        sources, brief["question"], int(research.get("candidate_sentences") or 30)
    )
    refs = store_sources(backend, sources) if sources else []
    proposed: Any = {}
    if sentences:
        system, user = prompt_text(worker_rules, brief["question"], sentences, sources)
        proposed = model.chat_json(system, user, meter=meter)
    claims, dropped = check_claims(proposed, sentences, sources, worker_rules)
    stages = {
        "fetch": {
            "permitted": len(permitted_urls(brief)),
            "fetched": len(sources),
            "failed": failures,
        },
        "candidates": len(sentences),
        "proposed": len((proposed or {}).get("claims") or []) if isinstance(proposed, dict) else 0,
        "kept": len(claims),
        "dropped": dropped[:20],
    }
    report = build_report(brief, sources, claims, stages)
    checked = {**brief, "sources": sources}
    issues = report_findings(report, checked)
    minimum = int(research.get("min_claims") or 3)
    if len(claims) < minimum:
        issues.append(
            f"only {len(claims)} claims kept a verbatim quote; at least {minimum} are needed"
        )
    return {
        "output": {"node": "report", "report": report, "blob_sha256": report_digest(report)},
        "self_test": {"passed": not issues, "issues": issues},
        "artifact_refs": refs,
        "summary": {
            "sources": len(report["sources"]),
            "claims": len(claims),
            "dropped": len(dropped),
        },
    }


def review_research(
    backend: Any,
    lease: Any,
    *,
    worker: str,
    key_id: str,
    fetcher: Fetcher,
    worker_rules: dict[str, Any],
) -> dict[str, Any]:
    """Re-fetch every cited source, re-check every quote and guardrail, then deliver or send back."""
    research = lease.dependencies[0]
    request_id, report_id = str(lease.brief["request_id"]), str(lease.brief["report_id"])
    part = lease.brief.get("part")
    ref = f"{lease.task_id}:{lease.fencing_token}"
    researcher = getattr(research, "completed_by_key", None)
    if research.state != "done" or not isinstance(research.output, dict):
        receipt = backend.submit(
            lease.task_id,
            lease.fencing_token,
            {
                "node": "report_review",
                "status": "nothing_to_review",
                "report_id": report_id,
                "research_state": research.state,
            },
            idempotency_key=ref,
            ok=True,
        )
        update_request_part(
            backend,
            request_id,
            part,
            "needs_revision",
            findings=["the research verb did not finish"],
        )
        return {
            "status": "nothing_to_review",
            "receipt": receipt.receipt_hash,
            "reason": f"the research verb ended {research.state}",
        }
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
    brief = dict(backend.task(research.task_id).brief)
    found = research.output.get("report")
    report: dict[str, Any] = found if isinstance(found, dict) else {}
    findings: list[str] = []
    if research.output.get("blob_sha256") != report_digest(report):
        findings.append("blob_sha256 is not the digest of the submitted report")
    allowlist = list((worker_rules.get("sources") or {}).get("official_apis") or [])
    fresh: list[dict[str, Any]] = []
    rechecked: list[dict[str, Any]] = []
    for source in (report or {}).get("sources") or []:
        url = str(source.get("url") or "")
        if not is_permitted(url, brief, allowlist):
            findings.append(f"source {source.get('id')} is not an address the brief permits")
            continue
        try:
            fetched = fetcher(url)
        except (SourceRefused, RuntimeError, ValueError) as exc:
            findings.append(f"source {source.get('id')} could not be fetched again: {exc}")
            continue
        again = source_record(
            fetched,
            source_id=str(source["id"]),
            access=str(source.get("access")),
            publisher=source.get("publisher"),
            max_text_chars=int((brief.get("fetch") or {}).get("max_text_chars") or 60000),
            request_id=request_id,
            part=part,
        )
        fresh.append(again)
        rechecked.append(
            {
                "id": again["id"],
                "text_sha256": again["text_sha256"],
                "same_text": again["text_sha256"] == source.get("text_sha256"),
            }
        )
    findings += report_findings(report, {**brief, "sources": fresh})
    overlap_needed = float((worker_rules.get("research") or {}).get("support_overlap") or 0.5)
    for claim in (report or {}).get("claims") or []:
        quote = " ".join(str(c.get("quote") or "") for c in claim.get("citations") or [])
        claim_words = words(str(claim.get("text") or ""))
        if not claim_words or len(claim_words & words(quote)) / len(claim_words) < overlap_needed:
            findings.append(f"claim {claim.get('id')} says more than its quote")
    if findings:
        receipt = backend.submit(
            lease.task_id,
            lease.fencing_token,
            {
                "node": "report_review",
                "status": "needs_revision",
                "report_id": report_id,
                "findings": findings,
                "rechecked": rechecked,
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
            "rechecked": rechecked,
            "quotes_checked": sum(len(c.get("citations") or []) for c in report["claims"]),
        },
        idempotency_key=ref,
        ok=True,
    )
    delivered = deliver_report(
        backend,
        report=dict(report),
        request_id=request_id,
        review_task_id=lease.task_id,
        review_receipt=receipt.receipt_hash,
        research_receipt=research.receipt_hash,
        digest=digest,
        part=part,
    )
    return {
        "status": "delivered",
        "receipt": receipt.receipt_hash,
        "rechecked": rechecked,
        **delivered,
    }
