"""The reference volunteer: one tracked anonymous session that claims one open verb, does it, checks
it and submits it, over plain HTTP with no key and no model call.

Contributing is ordinary work: claim a verb, do it, report it. A build verb returns a kit draft; a
research verb returns a report with a citation for every claim. The deterministic builders here are
stand-ins for the reasoning a volunteer's own agent would do; they show the contract, not quality.
The session token stays in memory and is never printed or stored.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from tessera.receipts import canonical_json

from eranos.donor_worker import synthesize_draft
from eranos.pipeline.solutions import report_digest, report_findings
from eranos.schemas import KitDraft, KitRequest, TrackPack
from eranos.verifier import verify_kit

USER_AGENT = "eranos-reference-volunteer/0.1"
OPEN_NAMESPACE = {"x-namespace": "main"}
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-z]{4,}")


class NoOpenWork(RuntimeError):
    """No open verb was ready to claim."""


@dataclass
class OpenSession:
    """One tracked anonymous session working open verbs in the shared namespace."""

    tessera_url: str
    label: str = "reference-volunteer"
    transport: httpx.BaseTransport | None = None
    principal: dict[str, Any] = field(default_factory=dict)
    _token: str = ""

    def __post_init__(self) -> None:
        self._http = httpx.Client(
            base_url=self.tessera_url.rstrip("/"),
            headers={"user-agent": USER_AGENT},
            timeout=30.0,
            transport=self.transport,
        )

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {**kwargs.pop("headers", {})}
        if self._token:
            headers["authorization"] = f"Bearer {self._token}"
        return self._http.request(method, path, headers=headers, **kwargs)

    def open(self) -> dict[str, Any]:
        response = self._call("POST", "/v1/session/anonymous", json={"agent_label": self.label})
        response.raise_for_status()
        body = dict(response.json())
        self._token = str(body.pop("session_token"))
        self.principal = body
        return body

    def open_verbs(self, queue: str = "eq02") -> list[dict[str, Any]]:
        response = self._call(
            "GET", "/v1/verbs", params={"queue": queue, "status": "ready"}, headers=OPEN_NAMESPACE
        )
        response.raise_for_status()
        return list(response.json()["verbs"])

    def claim(self, queue: str = "eq02", kinds: list[str] | None = None) -> httpx.Response:
        body: dict[str, Any] = {"queue": queue, "worker": self.label}
        if kinds:
            body["kinds"] = kinds
        return self._call("POST", "/v1/tasks/claim", json=body, headers=OPEN_NAMESPACE)

    def heartbeat(self, lease: dict[str, Any]) -> None:
        ref = {"task_id": lease["task_id"], "fencing_token": lease["fencing_token"]}
        self._call(
            "POST", "/v1/tasks/heartbeat", json=ref, headers=OPEN_NAMESPACE
        ).raise_for_status()

    def submit(
        self, lease: dict[str, Any], output: dict[str, Any], report: dict[str, Any]
    ) -> dict[str, Any]:
        response = self._call(
            "POST",
            "/v1/tasks/submit",
            json={
                "task_id": lease["task_id"],
                "fencing_token": lease["fencing_token"],
                "output": output,
                "execution_report": report,
            },
            headers={
                **OPEN_NAMESPACE,
                "idempotency-key": f"{lease['task_id']}:{lease['fencing_token']}",
            },
        )
        response.raise_for_status()
        return dict(response.json())

    def get(self, path: str, *, shared: bool = True) -> httpx.Response:
        return self._call("GET", path, headers=OPEN_NAMESPACE if shared else {})


def draft_digest(draft: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(draft).encode("utf-8")).hexdigest()


def build_kit(brief: dict[str, Any], *, worker: str, principal_id: str) -> dict[str, Any]:
    """A schema-valid, track-conformant kit draft for the checked brief (deterministic template)."""
    track = TrackPack.model_validate(brief["track"])
    request = KitRequest(
        kit_id=brief["kit_id"],
        track_id=track.id,
        title=brief["title"],
        goal=brief["goal"],
        target_org=brief["target_org"],
        needs_steward_signoff=bool(brief.get("needs_steward_signoff")),
    )
    draft, _ = synthesize_draft(request, track, worker=worker, key_id=principal_id, dry_model=True)
    return draft.model_dump(mode="json")


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in _WORD.findall(text.lower())}


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def research_report(brief: dict[str, Any]) -> dict[str, Any]:
    """Scan the brief's public sources, extract quoted claims and summarize them (deterministic)."""
    rules = brief.get("guardrails") or {}
    wanted = _words(brief["question"]) - {"with", "every", "point", "summarize", "citation"}
    scanned = [
        s for s in brief.get("sources") or [] if wanted & _words(" ".join(s.get("topics", [])))
    ]
    claims: list[dict[str, Any]] = []
    for source in scanned:
        for sentence in _SENTENCE.split(str(source.get("text", ""))):
            if sentence.startswith(("SYNTHETIC", "MADE-UP")) or not (wanted & _words(sentence)):
                continue
            claims.append(
                {
                    "id": f"C{len(claims) + 1}",
                    "text": sentence,
                    "citations": [{"source": source["id"], "quote": sentence}],
                }
            )
    report = {
        "report_id": brief["report_id"],
        "request_id": brief["request_id"],
        "title": brief["title"],
        "question": brief["question"],
        "sources": [
            {k: s[k] for k in ("id", "title", "publisher", "url", "access", "public", "synthetic")}
            | {"published": s.get("published")}
            for s in scanned
        ],
        "claims": claims,
        "summary": f"{_count(len(claims), 'cited point')} from "
        f"{_count(len(scanned), 'public source')}. " + " ".join(c["text"] for c in claims[:3]),
        "decision": str(rules.get("decision", "")),
        "stages": {
            "scan": {"considered": len(brief.get("sources") or []), "kept": len(scanned)},
            "extract": {"claims": len(claims)},
            "summarize": {"claims_in_summary": min(3, len(claims))},
        },
    }
    if brief.get("legal"):
        report["disclaimer"] = str(rules.get("disclaimer_text", "This is not legal advice."))
    return report


def do_verb(lease: dict[str, Any], *, worker: str, principal_id: str) -> dict[str, Any]:
    """The verb's output and the self-test result, from its brief alone."""
    brief = lease["brief"]
    if lease["kind"] == "build":
        draft = build_kit(brief, worker=worker, principal_id=principal_id)
        report = verify_kit(
            KitDraft.model_validate(draft), TrackPack.model_validate(brief["track"])
        )
        return {
            "output": {
                "node": "draft",
                "draft": draft,
                "verification": report.model_dump(mode="json"),
                "blob_sha256": draft_digest(draft),
            },
            "self_test": {"passed": report.passed, "issues": report.issues},
        }
    if lease["kind"] == "research":
        built = research_report(brief)
        issues = report_findings(built, brief)
        return {
            "output": {"node": "report", "report": built, "blob_sha256": report_digest(built)},
            "self_test": {"passed": not issues, "issues": issues},
        }
    raise ValueError(f"the reference volunteer does not know verbs of kind {lease['kind']!r}")


def contribute_once(
    tessera_url: str,
    *,
    label: str = "reference-volunteer",
    kinds: list[str] | None = None,
    practice_url: str | None = None,
    transport: httpx.BaseTransport | None = None,
    session: OpenSession | None = None,
) -> dict[str, Any]:
    """Open a session, claim one open verb, do it, self-test, submit; return the receipts."""
    worker = session or OpenSession(tessera_url, label=label, transport=transport)
    try:
        if not worker.principal:
            worker.open()
        visible = worker.open_verbs()
        response = worker.claim(kinds=kinds)
        if response.status_code == 204:
            raise NoOpenWork("no open verb is ready")
        response.raise_for_status()
        lease = dict(response.json())
        principal_id = str(worker.principal["principal_id"])
        done = do_verb(lease, worker=worker.label, principal_id=principal_id)
        practice = None
        if practice_url and lease["kind"] == "build":
            # The surface's practice check stores nothing; it must agree on the pass and the digest.
            with httpx.Client(headers={"user-agent": USER_AGENT}, transport=transport) as http:
                checked = http.post(
                    practice_url,
                    json={
                        "draft": done["output"]["draft"],
                        "track_id": lease["brief"]["track"]["id"],
                    },
                    timeout=30.0,
                )
            checked.raise_for_status()
            practice = checked.json()
            if not practice.get("passed"):
                raise RuntimeError(f"practice check failed: {practice.get('issues')}")
            if practice.get("draft_sha256") not in (None, done["output"]["blob_sha256"]):
                raise RuntimeError("the practice check computed a different draft digest")
        if not done["self_test"]["passed"]:
            raise RuntimeError(f"self-test failed: {done['self_test']['issues']}")
        worker.heartbeat(lease)
        receipt = worker.submit(
            lease,
            done["output"],
            {
                "version": 1,
                "harness": {"name": "eranos-reference-volunteer", "kind": "deterministic"},
                "model": None,
                "summaries": {
                    "problem": str(lease["brief"].get("title", ""))[:4000],
                    "solution": f"{lease['kind']} result for {lease['task_id']}",
                },
            },
        )
        state = worker.get(f"/v1/tasks/{lease['task_id']}").json().get("state")
        return {
            "principal_id": principal_id,
            "labels": worker.principal.get("labels"),
            "open_verbs_seen": [v["task_id"] for v in visible],
            "task_id": lease["task_id"],
            "kind": lease["kind"],
            "claim_receipt": lease.get("claim_receipt"),
            "digest": done["output"]["blob_sha256"],
            "self_test": done["self_test"],
            "practice": practice,
            "receipt": receipt,
            "state": state,
        }
    finally:
        if session is None:
            worker.close()
