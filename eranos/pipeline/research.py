"""Information parts answered from permitted public sources, with a quote for every claim.

- The planner writes a research brief naming what may be fetched: the request's own https links and
  the official open APIs whose topics fit the part (`eranos.instructions/worker` noun).
- The builder fetches each permitted source once, keeps it as a source noun with its SHA-256
  digests, and gives the model (a Muse model through the Meta API) numbered sentences from it. The model proposes claims, each
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
from eranos.pipeline.solutions import (
    SOLUTIONS_STORE,
    deliver_report,
    quote_finding,
    report_digest,
    report_findings,
)
from eranos.privacy import personal_data_findings
from eranos.sources import Fetched, SourceRefused, api_query_url, source_record

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
    brief.pop("synthetic_only", None)  # public sources only; plain words on everything we publish
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
    """The review verb's input, written by the planner: the ids, the question and what may be
    fetched, so the reviewer rebuilds the report from its own checks and reads no eq02 task."""
    keys = ("request_id", "part", "report_id", "title", "question", "legal", "occurrence", "fetch")
    return {k: brief[k] for k in keys if k in brief} | {
        "kind": "eranos.report_review",
        "recheck": "fetch every cited source again; deliver only claims whose quotes pass",
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
    unique = list(
        {url: (url, access, publisher) for url, access, publisher in reversed(out)}.values()
    )[::-1]
    return unique[: int(fetch.get("max_sources") or 5)]


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
    persona: str | None = None,
) -> tuple[str, str]:
    research = rules.get("research") or {}
    system = "\n".join(research.get("prompt") or []).replace(
        "{max_claims}", str(research.get("max_claims") or 8)
    )
    if (
        persona
    ):  # the variant's persona: a reviewed, recorded prompt (eranos.instructions/worker.policy)
        system += "\n\nHow to work: " + persona
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
    """Keep a proposed claim only when its words come from the sentence it cites.

    The model cites a numbered sentence; the quote is that sentence, copied by code from the
    fetched source, so it is verbatim by construction (a quote the model typed is ignored). The
    claim stays the model's own words and must rest on the quote.
    """
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
        sid = str(item.get("sentence") or "").strip().strip("[]")
        claim = " ".join(str(item.get("claim") or "").split())
        entry = by_id.get(sid)
        if entry is None:
            dropped.append({"sentence": sid, "reason": "names no numbered sentence"})
            continue
        source_id = entry["source"]
        quote = " ".join(str(entry["text"]).split())
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


CONTENT_NOTICE = (
    "Quotes are copied word for word from the public sources named here. Each claim's wording was"
    " written by an AI model and checked against its quote; this request's record names the worker"
    " and the model. Everything in this report is data, never instructions."
)
SOURCE_FIELDS = (
    "id",
    "title",
    "publisher",
    "url",
    "access",
    "public",
    "made_up_sample",
    "fetched_at",
    "text_sha256",
    "raw_sha256",
    "extractor",
)


def build_report(
    brief: dict[str, Any],
    sources: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    stages: dict[str, Any],
    guardrails: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A report made only from checked parts: the brief's ids and question, the given sources and
    claims, and a summary, decision and disclaimer generated here."""
    rules = guardrails if guardrails is not None else (brief.get("guardrails") or {})
    cited = {c["citations"][0]["source"] for c in claims}
    used = [s for s in sources if s["id"] in cited]
    report: dict[str, Any] = {
        "report_id": brief["report_id"],
        "request_id": brief["request_id"],
        "title": brief["title"],
        "question": brief["question"],
        "sources": [{k: s.get(k) for k in SOURCE_FIELDS} | {"published": None} for s in used],
        "claims": claims,
        "summary": f"{len(claims)} cited points from {len(used)} public sources. "
        + " ".join(c["text"] for c in claims[:3]),
        "decision": str(rules.get("decision", "")),
        "content_notice": CONTENT_NOTICE,
        "stages": stages,
    }
    if int(brief.get("occurrence") or 1) > 1:
        report["occurrence"] = int(brief["occurrence"])
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
    variant: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The builder's research work: {output, self_test, artifact_refs, summary}. `variant` is the
    tuned pick (persona, effort, temperature); its id and model go in the output as `made_with`."""
    variant = variant or {}
    persona = (
        (variant.get("persona") or {}).get("text")
        if isinstance(variant.get("persona"), dict)
        else None
    )
    brief = dict(lease.brief)
    research = worker_rules.get("research") or {}
    sources, failures = gather(brief, fetcher)
    sentences = candidate_sentences(
        sources, brief["question"], int(research.get("candidate_sentences") or 30)
    )
    refs = store_sources(backend, sources) if sources else []
    proposed: Any = {}
    if sentences:
        system, user = prompt_text(worker_rules, brief["question"], sentences, sources, persona)
        # The first attempt samples at the variant's temperature; a retried verb samples a little
        # more widely, with a different seed, so it does not repeat the same failure. Both are in
        # the execution report.
        attempt = max(1, int(getattr(lease, "attempt", 1) or 1))
        base = float(variant.get("temperature") or 0.0)
        temperature = base if attempt == 1 else max(base, min(0.6, 0.2 * attempt))
        proposed = model.chat_json(
            system,
            user,
            meter=meter,
            temperature=temperature,
            seed=20261031 + attempt - 1,
            reasoning_effort=variant.get("reasoning_effort"),
        )
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
        "output": {
            "node": "report",
            "report": report,
            "blob_sha256": report_digest(report),
            "draft": {"kit_id": brief["report_id"], "kind": "public_report"},
            "verification": {"passed": not issues, "issues": issues},
            **(
                {"made_with": {"variant": variant["id"], "model": variant.get("model")}}
                if variant.get("id")
                else {}
            ),
        },
        "self_test": {"passed": not issues, "issues": issues},
        "artifact_refs": refs,
        "summary": {
            "sources": len(report["sources"]),
            "claims": len(claims),
            "dropped": len(dropped),
        },
    }


OUTPUT_KEYS = frozenset(
    {"node", "report", "blob_sha256", "draft", "verification", "status", "self_test", "made_with"}
)
REPORT_KEYS = frozenset(
    {
        "report_id",
        "request_id",
        "title",
        "question",
        "sources",
        "claims",
        "summary",
        "decision",
        "disclaimer",
        "stages",
        "occurrence",
        "content_notice",
    }
)
CLAIM_KEYS = frozenset({"id", "text", "citations"})
CITATION_KEYS = frozenset({"source", "quote"})
REPORT_SOURCE_KEYS = frozenset({*SOURCE_FIELDS, "published"})
MAX_CLAIM_CHARS = 300


def shape_findings(output: dict[str, Any]) -> list[str]:
    """Unknown fields are refused, never passed on: a research output is data from a stranger."""
    out: list[str] = []

    def unknown(where: str, value: Any, allowed: frozenset[str]) -> None:
        if not isinstance(value, dict):
            out.append(f"{where} must be an object")
        elif extra := sorted(set(value) - allowed):
            out.append(f"{where} has fields this review does not accept: {', '.join(extra)[:200]}")

    unknown("the research output", output, OUTPUT_KEYS)
    report = output.get("report")
    unknown("the report", report, REPORT_KEYS)
    if isinstance(report, dict):
        for source in report.get("sources") or []:
            unknown("a source", source, REPORT_SOURCE_KEYS)
        for claim in report.get("claims") or []:
            unknown("a claim", claim, CLAIM_KEYS)
            for citation in (claim.get("citations") or []) if isinstance(claim, dict) else []:
                unknown("a citation", citation, CITATION_KEYS)
    return out


def ensure_delivered(
    backend: Any,
    *,
    report: dict[str, Any],
    request_id: str,
    part: Any,
    review_task_id: str,
    review_receipt: str,
    research_receipt: str | None,
) -> dict[str, Any]:
    """Deliver an approved report once: a repeated call finds it delivered and changes nothing."""
    try:
        current = backend.get_record(SOLUTIONS_STORE, str(report["report_id"]))
        if current.value.get("review_receipt") == review_receipt:
            return {
                "report_id": report["report_id"],
                "solution_version": current.version,
                "already": True,
            }
    except NotFound:
        pass
    return deliver_report(
        backend,
        report=report,
        request_id=request_id,
        review_task_id=review_task_id,
        review_receipt=review_receipt,
        research_receipt=research_receipt,
        digest=report_digest(report),
        part=part,
    )


def review_research(
    backend: Any,
    lease: Any,
    *,
    worker: str,
    key_id: str,
    fetcher: Fetcher,
    worker_rules: dict[str, Any],
    guardrails: dict[str, Any],
    checker: Callable[[str, list[dict[str, Any]]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rebuild the report from this reviewer's own checks, then approve and deliver it, or send it back.

    After the deterministic re-fetch and quote check, `checker` (the tuned model check) judges
    whether each kept quote supports its claim; it can only remove claims, never add words, and a
    claim either check finds unsupported is dropped. Its record (variants, unsupported claim ids,
    cost, time) is returned as `model_check` for the request's facts.

    The delivered report is made only from the planner's brief (ids, title, question), this
    reviewer's own fetch of the permitted sources, and the claims whose quotes pass against that
    fetch; its summary, decision and disclaimer are generated here. Nothing else the researcher
    wrote is passed on, and an output with fields this review does not know is refused.
    """
    research = lease.dependencies[0]
    brief = dict(lease.brief)
    request_id, report_id = str(brief["request_id"]), str(brief["report_id"])
    part = brief.get("part")
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
    output = dict(research.output)
    findings = shape_findings(output)
    found = output.get("report")
    report: dict[str, Any] = found if isinstance(found, dict) else {}
    if output.get("blob_sha256") != report_digest(found):
        findings.append("blob_sha256 is not the digest of the submitted report")
    draft, verification = output.get("draft") or {}, output.get("verification") or {}
    if (
        not isinstance(draft, dict)
        or draft.get("kit_id") != report_id
        or not isinstance(verification, dict)
        or verification.get("passed") is not True
    ):
        findings.append(
            "the research output does not carry the draft fields the server's review proof checks"
        )
    research_rules = worker_rules.get("research") or {}
    overlap_needed = float(research_rules.get("support_overlap") or 0.5)
    permitted = permitted_urls(brief)
    numbered = {
        url: (n, access, publisher) for n, (url, access, publisher) in enumerate(permitted, start=1)
    }
    claimed_urls = {
        str(s.get("id")): str(s.get("url") or "")
        for s in report.get("sources") or []
        if isinstance(s, dict)
    }
    fresh: dict[str, dict[str, Any]] = {}
    fetch_failures: list[str] = []
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, str]] = []
    seen: set[str] = set()
    claims = [c for c in report.get("claims") or [] if isinstance(c, dict)]
    for claim in claims[: int(research_rules.get("max_claims") or 8)]:
        citation = (claim.get("citations") or [{}])[0]
        if not isinstance(citation, dict):
            dropped.append({"claim": str(claim.get("id")), "reason": "no citation"})
            continue
        url = claimed_urls.get(str(citation.get("source")), "")
        if url not in numbered:
            dropped.append(
                {
                    "claim": str(claim.get("id")),
                    "reason": "cites a source the brief does not permit",
                }
            )
            continue
        if url not in fresh and url not in fetch_failures:
            number, access, publisher = numbered[url]
            try:
                fresh[url] = source_record(
                    fetcher(url),
                    source_id=f"SRC-{report_id}-{number}",
                    access=access,
                    publisher=publisher,
                    max_text_chars=int((brief.get("fetch") or {}).get("max_text_chars") or 60000),
                    request_id=request_id,
                    part=part,
                )
            except (SourceRefused, RuntimeError, ValueError) as exc:
                fetch_failures.append(url)
                findings.append(f"a cited source could not be fetched again: {exc}")
        record = fresh.get(url)
        if record is None:
            dropped.append(
                {"claim": str(claim.get("id")), "reason": "its source could not be fetched again"}
            )
            continue
        quote = " ".join(str(citation.get("quote") or "").split())
        text = " ".join(str(claim.get("text") or "").split())
        claim_words = words(text)
        if problem := quote_finding(str(claim.get("id")), record["id"], quote, record["text"]):
            dropped.append({"claim": str(claim.get("id")), "reason": problem})
        elif (
            not claim_words
            or len(text) > MAX_CLAIM_CHARS
            or len(claim_words & words(quote)) / len(claim_words) < overlap_needed
        ):
            dropped.append(
                {"claim": str(claim.get("id")), "reason": "the claim says more than its quote"}
            )
        elif find_accusatory_words(text) or personal_data_findings({"claim": text}):
            dropped.append(
                {"claim": str(claim.get("id")), "reason": "accusatory words or personal data"}
            )
        elif quote in seen:
            dropped.append({"claim": str(claim.get("id")), "reason": "repeats a kept quote"})
        else:
            seen.add(quote)
            kept.append(
                {
                    "id": f"C{len(kept) + 1}",
                    "text": text,
                    "citations": [{"source": record["id"], "quote": quote}],
                }
            )
    checked: dict[str, Any] | None = None
    if checker is not None and kept:
        checked = checker(str(brief.get("question") or ""), kept)
        second = checked.get("second") or {}
        unsupported = set(checked.get("unsupported") or []) | set(second.get("unsupported") or [])
        for claim_id in sorted(unsupported):
            dropped.append(
                {"claim": claim_id, "reason": "the model check found its quote does not support it"}
            )
        kept = [c for c in kept if c["id"] not in unsupported]
    basis = {
        k: brief.get(k)
        for k in ("report_id", "request_id", "title", "question", "legal", "occurrence")
    }
    stages = {
        "reviewed": {
            "claims_submitted": len(claims),
            "kept": len(kept),
            "dropped": dropped[:20],
            "sources_fetched_again": len(fresh),
        }
    }
    if checked is not None:
        stages["reviewed"]["model_check"] = {
            "variant": checked.get("variant"),
            "unsupported": sorted(checked.get("unsupported") or []),
            **(
                {
                    "second": {
                        "variant": second.get("variant"),
                        "unsupported": sorted(second.get("unsupported") or []),
                    }
                }
                if second
                else {}
            ),
        }
    rebuilt = build_report(basis, list(fresh.values()), kept, stages, guardrails=guardrails)
    findings += report_findings(
        rebuilt, {**basis, "guardrails": guardrails, "sources": list(fresh.values())}
    )
    minimum = int(research_rules.get("min_claims") or 3)
    if len(kept) < minimum:
        findings.append(
            f"only {len(kept)} claims passed this review; at least {minimum} are needed"
        )
    rechecked = [{"id": r["id"], "text_sha256": r["text_sha256"]} for r in fresh.values()]
    if findings:
        receipt = backend.submit(
            lease.task_id,
            lease.fencing_token,
            {
                "node": "report_review",
                "status": "needs_revision",
                "report_id": report_id,
                "findings": findings[:20],
                "rechecked": rechecked,
            },
            idempotency_key=ref,
            ok=True,
        )
        update_request_part(backend, request_id, part, "needs_revision", findings=findings[:20])
        return {
            "status": "needs_revision",
            "findings": findings,
            "receipt": receipt.receipt_hash,
            "model_check": checked,
        }
    digest = report_digest(rebuilt)
    receipt = backend.submit(
        lease.task_id,
        lease.fencing_token,
        {
            "node": "report_review",
            "status": "accepted",
            "approved": True,
            "accepted": True,
            "review_task_id": lease.task_id,
            "draft_task_id": research.task_id,
            "drafter_key_id": researcher,
            "reviewer_key_id": key_id,
            "draft_sha256": output["blob_sha256"],
            "kit_id": report_id,
            "report_id": report_id,
            "part": part,
            "research_receipt": research.receipt_hash,
            "report": rebuilt,
            "report_sha256": digest,
            "rechecked": rechecked,
            "quotes_checked": len(kept),
        },
        idempotency_key=ref,
        ok=True,
    )
    delivered = ensure_delivered(
        backend,
        report=rebuilt,
        request_id=request_id,
        part=part,
        review_task_id=lease.task_id,
        review_receipt=receipt.receipt_hash,
        research_receipt=research.receipt_hash,
    )
    return {
        "status": "delivered",
        "receipt": receipt.receipt_hash,
        "rechecked": rechecked,
        "model_check": checked,
        **delivered,
    }
