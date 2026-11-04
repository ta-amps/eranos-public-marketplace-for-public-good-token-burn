"""A nonprofit's request is one verb on `eq01`; the worker that claims it classifies it and splits it.

- A request arrives as one `request` verb: filed by the nonprofit's requester key from the plain
  "Tell us what you need" box, or by intake from the public issue form. Intake refuses personal
  data before storing anything.
- The classify step is ordinary work by an authorized worker who claims that verb, following the
  `eranos.instructions/classify` noun (its instructions, acceptance checks, route markers and plain
  words). It refuses personal data, then breaks the request into parts:
  - a part that needs only public information becomes a research verb for donated agents (an open
    verb), and a report review by a different worker that re-checks every citation;
  - a part that touches the nonprofit's own files becomes a kit build (an open verb) and a review;
    the nonprofit's own agent runs the kit, so its data stays with it.
  One request may produce both. The worker records the breakdown as a plan noun tied to the
  verb's claim receipt and splits the verb into those children with Tessera's split (waves).
- When every child has resolved, the same verb returns to the queue; closing it records the outcome
  of each part and the final receipt.

No new queue, authority or server-side agent: `eq01` plus split, nouns and receipts.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tessera import ChildSpec, NotFound, VersionConflict
from tessera.receipts import canonical_json

from eranos.copy import PROHIBITED_COLLECTION_TOPICS, find_accusatory_words
from eranos.pipeline.request_noun import (
    PRODUCER,
    read_request,
    update_request_status,
    write_request,
)
from eranos.pipeline.run import _build_task_spec, _claim_with_key
from eranos.privacy import personal_data_findings
from eranos.schemas import TrackPack
from eranos.tracks import load_tracks

REQUEST_FIELDS = ("organization_type", "job", "person_only", "constraints")
FIELD_LIMITS = {
    "organization_type": (3, 120),
    "job": (10, 2000),
    "person_only": (5, 1000),
    "constraints": (0, 1000),
}
OPEN_VERB_TAG = "open:anonymous"
DIGEST_RULE = "sha256 of the object as canonical JSON: sorted keys, no spaces, UTF-8"
INSTRUCTIONS_STORE = "eranos.instructions"
SOURCES_STORE = "eranos.sources"
PLANS_STORE = "eranos.plans"
QUARANTINE = {"producer_surface": PRODUCER, "visibility_scope": "surface_only"}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[a-z]{4,}")
_LINK = re.compile(r"^https://[^\s<>\"']{4,300}$")
_COMMON = frozenset(
    [
        *("about", "after", "also", "because", "before", "being", "between", "both", "could"),
        *("does", "each", "every", "from", "have", "help", "into", "just", "like", "make"),
        *("many", "more", "most", "must", "need", "needs", "only", "other", "over", "please"),
        *("same", "should", "some", "such", "than", "that", "their", "them", "then", "there"),
        *("these", "they", "this", "those", "through", "very", "want", "what", "when", "where"),
        *("which", "while", "will", "with", "work", "would", "your", "agent", "agents", "build"),
    ]
)


class PersonalDataRefused(ValueError):
    """Nothing was stored. Findings name the kind of data and the field, never the text."""

    def __init__(self, findings: list[str]) -> None:
        super().__init__("request refused before storage: " + "; ".join(findings))
        self.findings = findings


@dataclass(frozen=True)
class RequestIntake:
    request_id: str
    version: int
    check_task_id: str


def clean_fields(fields: dict[str, Any]) -> dict[str, str]:
    """Keep only the form's fields, as trimmed plain text within the form's limits."""
    clean: dict[str, str] = {}
    for name in REQUEST_FIELDS:
        text = _CONTROL.sub("", str(fields.get(name) or "")).strip()
        low, high = FIELD_LIMITS[name]
        if len(text) < low:
            raise ValueError(f"{name} needs at least {low} characters")
        clean[name] = text[:high]
    return clean


def request_id_for(fields: dict[str, Any]) -> str:
    return "req-" + hashlib.sha256(canonical_json(fields).encode()).hexdigest()[:12]


def form_text(fields: dict[str, str]) -> str:
    """One plain request text from the issue form's answers."""
    parts = [fields["job"], f"Steps that stay with a person: {fields['person_only']}"]
    if fields.get("constraints"):
        parts.append(f"Constraints: {fields['constraints']}")
    return "\n".join(parts)


def submit_request(
    backend: Any, fields: dict[str, Any], *, source: dict[str, Any] | None = None
) -> RequestIntake:
    """Intake from the public issue form: one request verb, or a refusal before storing anything."""
    clean = clean_fields(fields)
    findings = personal_data_findings(clean)
    if findings:
        raise PersonalDataRefused(findings)
    request_id = request_id_for(clean)
    origin = {k: v for k, v in (source or {}).items() if k in {"kind", "number", "url"}}
    value = {
        "schema_version": 1,
        "request_id": request_id,
        "status": "received",
        "text": form_text(clean),
        "source": origin or {"kind": "form"},
    }
    try:
        version = write_request(backend, request_id, value, expected_version=0)
    except VersionConflict:
        current = read_request(backend, request_id)
        version = current[1] if current else 1
    backend.enqueue(
        _build_task_spec(
            queue="eq01",
            task_id=request_id,
            kind="request",
            effect_class="write-internal",
            brief={
                "text": value["text"],
                "links": [],
                "organization_type": clean["organization_type"],
                "source": value["source"],
            },
            governance={**QUARANTINE, "tags": ["status:quarantined", "kind:request"]},
        )
    )
    return RequestIntake(request_id=request_id, version=version, check_task_id=request_id)


def _words(text: str) -> set[str]:
    out = set()
    for word in _WORD.findall(text.lower()):
        if word in _COMMON:
            continue
        out.add(word[:-1] if len(word) > 4 and word.endswith("s") else word)
    return out


def match_track(fields: dict[str, str], tracks: dict[str, TrackPack]) -> TrackPack | None:
    """The one track whose own words best match the text; none when no track clearly leads."""
    wanted = _words(" ".join(fields.values()))
    scored = []
    for track in tracks.values():
        text = " ".join(
            [track.title, track.summary, track.domain_label or "", *track.allowed_artifacts]
            + [f"{o.org_type} {o.serves} {o.mandate}" for o in track.organizations]
        ).replace("_", " ")
        scored.append((len(wanted & _words(text)), track.id, track))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if not scored or scored[0][0] < 3 or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None
    return scored[0][2]


def _marker(words: list[str]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"\b(?:{alternatives})\b", re.IGNORECASE)


def classify_parts(text: str, rules: dict[str, Any]) -> list[dict[str, Any]]:
    """Break a request into parts with one route each, using the classify noun's markers.

    A stand-in for the authorized worker's reasoning that follows the same noun: a sentence that
    touches the organization's files is private; one that needs only public information is public;
    an unclear sentence joins its neighbour, and an unclear request stays with the organization.
    """
    markers = rules["markers"]
    private, public, legal = (
        _marker(markers["private_files"]),
        _marker(markers["public_only"]),
        _marker(markers["legal"]),
    )
    parts: list[dict[str, Any]] = []
    pending: list[str] = []
    for sentence in (s.strip() for s in _SENTENCE.split(text)):
        if not sentence:
            continue
        route = (
            "private-files"
            if private.search(sentence)
            else "public-only"
            if public.search(sentence)
            else None
        )
        if route is None:
            if parts:
                parts[-1]["text"] += " " + sentence
            else:
                pending.append(sentence)
        elif parts and parts[-1]["route"] == route:
            parts[-1]["text"] += " " + sentence
        else:
            parts.append({"route": route, "text": " ".join([*pending, sentence])})
            pending = []
    if pending:
        parts.append({"route": "private-files", "text": " ".join(pending)})
    for number, part in enumerate(parts, start=1):
        part["part"] = number
        part["legal"] = bool(legal.search(part["text"]))
    return parts


def check_findings(fields: dict[str, str]) -> list[str]:
    """Personal data, accusatory wording and prohibited topics block a request."""
    findings = personal_data_findings(fields)
    text = " ".join(fields.values())
    if words := find_accusatory_words(text):
        findings.append(
            f"uses accusatory words ({', '.join(words)}); describe warning signs instead"
        )
    if PROHIBITED_COLLECTION_TOPICS.search(text):
        findings.append("asks for a kind of kit volunteers never build")
    return findings


def _first_sentence(text: str) -> str:
    sentence = _SENTENCE.split(text.strip(), maxsplit=1)[0]
    return sentence.rstrip(".!?")


def _common_brief(request_id: str, part: dict[str, Any], org: str, prefix: str) -> dict[str, Any]:
    digest = hashlib.sha256(f"{request_id}:{part['part']}".encode()).hexdigest()
    title = f"{org}: {_first_sentence(part['text'])}"[:140]
    return {
        "schema_version": 1,
        "request_id": request_id,
        "part": part["part"],
        "noun_id": f"{prefix}-R{digest[:7].upper()}-{part['part']:02d}",
        "title": title if len(title) >= 5 else f"For {org}"[:140],
        "goal": part["text"][:600],
        "target_org": org[:140],
        "synthetic_only": True,
        "spdx_license": "Apache-2.0",
        "requested_visibility_scope": "public_commons",
    }


def kit_brief(request_id: str, part: dict[str, Any], org: str, track: TrackPack) -> dict[str, Any]:
    """A kit build's whole input: an anonymous claimant sees this brief and nothing else."""
    brief = _common_brief(request_id, part, org, "KIT")
    brief["kit_id"] = brief.pop("noun_id")
    return {
        **brief,
        "kind": "eranos.kit_build",
        "track": track.model_dump(mode="json"),
        "needs_steward_signoff": track.needs_steward_signoff,
        "acceptance": [
            "Every fixture's sample_input carries a visible MADE-UP mark; no real person's data.",
            "Steps of the track's required person-only kinds keep boundary human_only.",
            "Words name warning signs and checklist questions, never accusations.",
            "The draft passes the practice check, which stores nothing.",
        ],
        "output": {
            "node": "draft",
            "draft": "the KitDraft object, with kit_id and track_id from this brief",
            "verification": "the VerificationReport from the practice check",
            "blob_sha256": DIGEST_RULE + ", of the draft",
        },
        "instructions": {"store": INSTRUCTIONS_STORE, "key": "help"},
    }


def research_brief(
    request_id: str,
    part: dict[str, Any],
    org: str,
    guardrails: dict[str, Any],
    sources: list[dict[str, Any]],
    links: list[str],
) -> dict[str, Any]:
    """A research verb's whole input, including the public sources it may cite."""
    brief = _common_brief(request_id, part, org, "RPT")
    brief["report_id"] = brief.pop("noun_id")
    return {
        **brief,
        "kind": "eranos.public_research",
        "question": part["text"][:600],
        "legal": bool(part.get("legal")),
        "guardrails": guardrails,
        "sources": sources,
        "suggested_links": links,
        "stages": ["scan the sources", "extract claims with exact quotes", "summarize"],
        "output": {
            "node": "report",
            "report": "report_id, request_id, title, question, sources, claims (each with"
            " citations: source and exact quote), summary, decision, and the disclaimer when legal",
            "blob_sha256": DIGEST_RULE + ", of the report",
        },
        "instructions": {"store": INSTRUCTIONS_STORE, "key": "public-research"},
    }


def _noun(backend: Any, store: str, key: str) -> dict[str, Any] | None:
    try:
        return dict(backend.get_record(store, key).value)
    except NotFound:
        return None


def _stand_in_sources(backend: Any, text: str) -> list[dict[str, Any]]:
    """Public sources to cite: here the seeded synthetic stand-ins whose topics match the part."""
    wanted = _words(text)
    out = []
    for record in backend.list_records(SOURCES_STORE, limit=100):
        value = dict(record.value)
        if wanted & _words(" ".join(value.get("topics", [])) + " " + str(value.get("title", ""))):
            out.append(value)
    return sorted(out, key=lambda source: str(source.get("id")))


def plan_children(
    backend: Any,
    request_id: str,
    parts: list[dict[str, Any]],
    org: str,
    links: list[str],
    tracks_root: Path | None = None,
) -> tuple[list[ChildSpec], list[dict[str, Any]]]:
    """The work and review verbs for every part, in waves, and each part's plan entry."""
    guardrails = _noun(backend, INSTRUCTIONS_STORE, "public-research")
    tracks = load_tracks(tracks_root)
    children: list[ChildSpec] = []
    plan: list[dict[str, Any]] = []
    for part in parts:
        entry: dict[str, Any] = {k: part[k] for k in ("part", "route", "text", "legal")}
        review: dict[str, Any]
        if part["route"] == "public-only" and guardrails is not None:
            sources = _stand_in_sources(backend, part["text"])
            brief = research_brief(request_id, part, org, guardrails, sources, links)
            entry.update(report_id=brief["report_id"])
            review = {k: brief[k] for k in ("request_id", "part", "report_id", "title", "legal")}
            work_kind, review_kind = "research", "report_review"
        else:
            track = match_track({"organization_type": org, "job": part["text"]}, tracks)
            if part["route"] == "public-only" or track is None:
                entry["route"] = "held"
                plan.append(entry)
                continue
            brief = kit_brief(request_id, part, org, track)
            entry.update(
                kit_id=brief["kit_id"],
                track_id=track.id,
                needs_person_signoff=track.needs_steward_signoff,
            )
            keys = ("request_id", "part", "kit_id", "title", "needs_steward_signoff")
            review = {k: brief[k] for k in keys} | {
                "track_id": track.id,
                "requested_visibility_scope": "public_commons",
            }
            work_kind, review_kind = "build", "review"
        entry["children"] = [len(children), len(children) + 1]
        tags = [f"part:{part['part']}"]
        children.append(
            ChildSpec(
                queue="eq02",
                kind=work_kind,
                effect_class="write-internal",
                brief=brief,
                tags=[*tags, f"kind:{work_kind}", OPEN_VERB_TAG],
            )
        )
        children.append(
            ChildSpec(
                queue="eq03",
                kind=review_kind,
                effect_class="write-internal",
                brief=review,
                tags=[*tags, f"kind:{review_kind}"],
                after=[len(children) - 1],
            )
        )
        plan.append(entry)
    return children, plan


def _plain(rules: dict[str, Any], plan: list[dict[str, Any]]) -> list[str]:
    words = rules["plain_words"]
    return [f"Part {p['part']}: {words[p['route']]}" for p in plan]


def run_request_check(
    backend: Any,
    *,
    worker: str,
    key_id: str | None = None,
    tracks_root: Path | None = None,
) -> dict[str, Any] | None:
    """Claim one request verb: classify and split it, or, once its parts resolve, close it."""
    lease = _claim_with_key(backend, "eq01", worker, key_id=key_id, kinds=["request"])
    if lease is None:
        return None
    if lease.children:
        return _close(backend, lease)
    rules = _noun(backend, INSTRUCTIONS_STORE, "classify")
    if rules is None:
        raise RuntimeError("the eranos.instructions/classify noun is missing; nothing was split")
    brief = lease.brief if isinstance(lease.brief, dict) else {}
    request_id = str(lease.task_id)
    text = _CONTROL.sub("", str(brief.get("text") or "")).strip()[:4000]
    org = _CONTROL.sub("", str(brief.get("organization_type") or "")).strip()[:120] or "Nonprofit"
    links = [str(link) for link in brief.get("links") or [] if _LINK.match(str(link))][:10]
    if read_request(backend, request_id) is None:
        source = brief.get("source") if isinstance(brief.get("source"), dict) else None
        value = {
            "schema_version": 1,
            "request_id": request_id,
            "status": "received",
            "text": text,
            "source": source or {"kind": "requester"},
        }
        with contextlib.suppress(VersionConflict):  # a retried claim finds its noun written
            write_request(backend, request_id, value, expected_version=0)
    findings = check_findings({"text": text, "links": " ".join(links)})
    if len(text) < 10:
        findings.append("the request needs at least a sentence describing the job")
    output: dict[str, Any] = {"node": "check", "request_id": request_id}
    children: list[ChildSpec] = []
    plan: list[dict[str, Any]] = []
    if not findings:
        parts = classify_parts(text, rules)
        children, plan = plan_children(backend, request_id, parts, org, links, tracks_root)
        if not children:
            findings.append("no part can start yet; a person looks at the request first")
    if findings:
        # Block: the noun keeps the reasons and its source, never the text that was refused.
        update_request_status(backend, request_id, "blocked", text=None, findings=findings)
        _write_plan(
            backend, request_id, lease, [], [rules["plain_words"]["blocked"]], findings=findings
        )
        receipt = backend.submit(
            lease.task_id,
            lease.fencing_token,
            {**output, "status": "blocked", "findings": findings},
            idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
            ok=True,
        )
        return {
            **output,
            "status": "blocked",
            "findings": findings,
            "receipt": receipt.receipt_hash,
        }
    ids = backend.split(lease.task_id, lease.fencing_token, children)
    for entry in plan:
        if "children" in entry:
            work, review = entry.pop("children")
            entry["work_task_id"], entry["review_task_id"] = ids[work], ids[review]
    _write_plan(backend, request_id, lease, plan, _plain(rules, plan))
    update_request_status(
        backend,
        request_id,
        "open_for_build",
        parts={str(p["part"]): {"route": p["route"], "status": "open"} for p in plan},
        plan={"store": PLANS_STORE, "key": request_id},
    )
    return {**output, "status": "split", "plan": plan, "claim_receipt": lease.claim_receipt}


def _write_plan(
    backend: Any,
    request_id: str,
    lease: Any,
    plan: list[dict[str, Any]],
    plain: list[str],
    **extra: Any,
) -> int:
    """The classification and breakdown as a public noun, tied to the verb's claim receipt."""
    value = {
        "schema_version": 1,
        "request_id": request_id,
        "receipt": {"task_id": lease.task_id, "claim_receipt": lease.claim_receipt},
        "parts": plan,
        "plain": plain,
        "next_step": "A person on your team decides what to do with every result.",
        **extra,
    }
    try:
        version = backend.get_record(PLANS_STORE, request_id).version
    except NotFound:
        version = 0
    saved = backend.put_record(
        PLANS_STORE,
        request_id,
        value,
        expected_version=version,
        producer_surface=PRODUCER,
        visibility_scope="public_commons",
        tags=["kind:plan"],
    )
    return int(saved.version)


def _close(backend: Any, lease: Any, request_id: str | None = None) -> dict[str, Any]:
    """Every part resolved: record each child's outcome and the request's final receipt. A reopen
    verb closes the request it was opened for (`request_id`), not a request of its own."""
    request = str(request_id or lease.task_id)
    outcomes = [
        {
            "task_id": child.task_id,
            "state": child.state,
            "status": (child.output or {}).get("status")
            if isinstance(child.output, dict)
            else None,
            "receipt": child.receipt_hash,
        }
        for child in lease.children
    ]
    output = {"node": "close", "request_id": request, "children": outcomes}
    receipt = backend.submit(
        lease.task_id,
        lease.fencing_token,
        output,
        idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
        ok=True,
    )
    update_request_status(backend, request, "closed", close_receipt=receipt.receipt_hash)
    with contextlib.suppress(NotFound):
        current = backend.get_record(PLANS_STORE, request)
        backend.put_record(
            PLANS_STORE,
            request,
            {**current.value, "closed": {"receipt": receipt.receipt_hash, "children": outcomes}},
            expected_version=current.version,
            producer_surface=PRODUCER,
            visibility_scope="public_commons",
            tags=["kind:plan"],
        )
    return {**output, "status": "closed", "receipt": receipt.receipt_hash}
