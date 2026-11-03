"""The reuse check: a library answer answers a request only after another worker's key approves it.

Finding F-REUSE-001: the planner once closed a real request with an unrelated library report, with no
check and no decision. Now a reuse match is only a candidate. The planner queues one `reuse_review`
verb on eq03 for it, and a reviewer (a different key from the planner's, which may not claim eq03
verbs at all) reads the request and the library answer and asks a Muse model whether the answer fits
as it is. Only a yes answers the request from the library; no, unsure, an answer it cannot read, or a
library answer that changed or lost its confirmed review sends it back, and the planner then plans new
work. Every check records its model, verdict and reason.

A wrongly reused request that closed before this check existed, or a request whose parts all ended
without a result, is opened again by a recorded reopen:
the operator writes a `reopened` fact (the request page reads it and keeps the reuse in the history
as a failed attempt) and names a new request verb in the request record, which the planner accepts
only when the record names it, so a forged reopen of another request is refused.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

from tessera import NotFound

from eranos.pipeline import reuse
from eranos.pipeline.plain_words import forbidden, plain_text
from eranos.pipeline.request_noun import read_request, update_request_part
from eranos.pipeline.run import SelfReviewRefused

REUSE_KIND = "reuse_review"
VERDICTS = ("yes", "no", "unsure")
MAX_WHY = 240
REOPEN_SEP = "--reopen-"

Judge = Callable[[str, dict[str, Any]], dict[str, Any]]


def reuse_brief(
    request_id: str,
    text: str,
    terms: dict[str, Any],
    pointer: dict[str, Any],
    *,
    proposed_by_key: str | None,
    considered: dict[str, Any] | None = None,
    max_question_chars: int | None = None,
) -> dict[str, Any]:
    """The reuse check's whole input: the request as written, the candidate and who proposed it."""
    bounded_question = str(text)[:max_question_chars] if max_question_chars else str(text)
    return {
        "kind": "eranos.reuse_review",
        "request_id": request_id,
        "part": 1,
        "question": bounded_question,
        "output_type": terms.get("output_type"),
        "candidate": dict(pointer),
        "proposed_by_key": proposed_by_key,
        "similarity": (considered or {}).get("best"),
        "check": "decide whether the library answer answers this request as it is; send it back when unsure",
    }


def library_view(
    kind: str,
    value: dict[str, Any],
    max_points: int = 6,
    *,
    max_question_chars: int | None = None,
) -> dict[str, Any]:
    """What the check reads of a library answer: the request it answered and its main points."""
    if kind == "report":
        found = value.get("report")
        report: dict[str, Any] = found if isinstance(found, dict) else {}
        report_q = str(report.get("question") or "")
        return {
            "kind": "a cited report",
            "question_it_answered": report_q[:max_question_chars] if max_question_chars else report_q,
            "title": reuse._untitled(str(report.get("title") or ""))[:300],
            "points": [
                str(c.get("text") or "")[:400]
                for c in (report.get("claims") or [])[:max_points]
                if isinstance(c, dict)
            ],
        }
    held = value.get("kit")
    kit: dict[str, Any] = held if isinstance(held, dict) else {}
    kit_q = str(value.get("request_text") or kit.get("request_text") or "")
    return {
        "kind": "a reusable process package",
        "question_it_answered": kit_q[:max_question_chars] if max_question_chars else kit_q,
        "title": str(kit.get("title") or value.get("title") or "")[:300],
        "points": [str(value.get("summary") or kit.get("summary") or "")[:800]],
    }


# Every link-like token: any scheme (hxxps:// too), www., a dotted host with any letter ending
# (short links such as t.me included), an IP address with an optional port or path, and "dot"
# spelled out between words. A reason that still holds "://" or an "@" afterwards is dropped.
_LINKISH = re.compile(
    r"\b[a-z][a-z0-9+.-]*://\S*"
    r"|\bwww\.\S+"
    r"|\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\S*"
    r"|\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b(?:[/:?#]\S*)?"
    r"|\b[a-z0-9-]+\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\s+dot\s+)\s*[a-z]{2,}\b",
    re.I,
)
_LEFTOVER = re.compile(r"://|@")


def clean_why(text: str) -> str:
    """The model's one-sentence reason as it may be published: every link-like token taken out, the
    owner's plain words, and no reason at all if an address shape or the retired word is left; at
    most MAX_WHY characters. The display layer filters published text through the shared word list
    as well (rules/banned-words.json); no copy of that list is kept here."""
    why = " ".join(_LINKISH.sub("", plain_text(str(text or ""))).split())[:MAX_WHY]
    if _LEFTOVER.search(why) or forbidden(why):
        return ""
    return why


def read_judgment(answer: Any) -> dict[str, str]:
    """A model's answer as {answers, why}; anything that is not a clear yes counts as unsure."""
    found = answer if isinstance(answer, dict) else {}
    said = str(found.get("answers") or "").strip().lower()
    why = clean_why(str(found.get("why") or ""))
    if said not in VERDICTS:
        return {"answers": "unsure", "why": why or "the model's answer named no verdict"}
    return {"answers": said, "why": why}


def review_reuse(
    backend: Any,
    lease: Any,
    *,
    key_id: str,
    judge: Judge,
    max_points: int = 6,
    max_question_chars: int | None = None,
) -> dict[str, Any]:
    """Check one reuse candidate, then answer the request from the library or send it back."""
    brief = dict(lease.brief)
    request_id, part = str(brief["request_id"]), brief.get("part") or 1
    pointer = dict(brief.get("candidate") or {})
    ref = f"{lease.task_id}:{lease.fencing_token}"
    proposer = str(brief.get("proposed_by_key") or "")
    if not key_id.strip() or key_id == proposer:
        backend.submit(
            lease.task_id,
            lease.fencing_token,
            {"node": REUSE_KIND, "status": "rejected_self_review", "request_id": request_id},
            idempotency_key=ref,
            ok=False,
            error="the key that proposed a reuse may not check it",
        )
        raise SelfReviewRefused(f"reviewer key {key_id!r} proposed the reuse it was asked to check")
    problem, value = None, {}
    try:
        record = backend.get_record(str(pointer.get("store")), str(pointer.get("key")))
        value = record.value if isinstance(record.value, dict) else {}
        if int(record.version) != int(pointer.get("version") or 0):
            problem = "the library answer changed after it was matched"
        elif not reuse.verified(backend, value, str(pointer.get("review_receipt") or "")):
            problem = "the library answer's review cannot be confirmed"
    except NotFound:
        problem = "the library answer is no longer there"
    question = str(brief.get("question") or "")
    stored_req = read_request(backend, request_id)
    stored_text = str((stored_req[0] if stored_req else {}).get("text") or "").strip()
    if stored_text and len(stored_text) > len(question):
        question = stored_text[:max_question_chars] if max_question_chars else stored_text
    elif max_question_chars:
        question = question[:max_question_chars]
    if not question.strip():
        problem = problem or "the request text for the reuse check was incomplete"
    started = time.time()
    if problem is None:
        verdict = judge(
            question,
            library_view(
                str(pointer.get("kind")),
                value,
                max_points=max_points,
                max_question_chars=max_question_chars,
            ),
        )
    else:
        verdict = {"answers": "no", "why": problem, "model": None}
    judged = read_judgment(verdict)
    check = {
        **judged,
        "model": verdict.get("model"),
        "model_display": verdict.get("model_display"),
        "cost_usd": verdict.get("cost_usd"),
        "seconds": verdict.get("seconds", round(time.time() - started, 1)),
        "similarity": pointer.get("score"),
    }
    accepted = judged["answers"] == "yes"
    output = {
        "node": REUSE_KIND,
        "status": "accepted" if accepted else "sent_back",
        # Not `approved`: on eq03 Tessera reserves that for a draft's review and asks for the draft's
        # proof; a reuse check approves no draft, it decides whether a reviewed answer fits.
        "accepted": accepted,
        "request_id": request_id,
        "part": part,
        "reused": pointer,
        "check": check,
        "reviewer_key_id": key_id,
        "proposed_by_key": proposer or None,
    }
    receipt = backend.submit(
        lease.task_id, lease.fencing_token, output, idempotency_key=ref, ok=True
    )
    if accepted:
        ensure_reuse_delivered(
            backend, request_id, output, str(lease.task_id), receipt.receipt_hash
        )
    else:
        update_request_part(
            backend,
            request_id,
            part,
            "needs_revision",
            route="reuse_check",
            findings=[f"the library answer was not used: {judged['why'] or judged['answers']}"],
        )
    return {
        "status": "delivered" if accepted else "sent_back",
        "receipt": receipt.receipt_hash,
        "reused": pointer,
        "check": check,
        "reason": None if accepted else f"reuse_{judged['answers']}",
    }


def ensure_reuse_delivered(
    backend: Any, request_id: str, output: dict[str, Any], review_task_id: str, receipt: str
) -> None:
    """Record the approved reuse on the request's part once (the planner repeats it after a crash)."""
    pointer = dict(output.get("reused") or {})
    fields: dict[str, Any] = {
        "route": "reused",
        "reused_from": pointer,
        "review_receipt": pointer.get("review_receipt"),
        "reuse_check": {"task_id": review_task_id, "receipt": receipt},
    }
    if pointer.get("kind") == "report":
        fields["solution"] = {k: pointer.get(k) for k in ("store", "key", "version")}
        status = "delivered"
    else:
        fields["kit_id"] = pointer.get("key")
        status = "published"
    update_request_part(backend, request_id, output.get("part") or 1, status, **fields)


# reopening a wrongly reused request ---------------------------------------------------------------
def reopen_task_id(request_id: str, n: int) -> str:
    return f"{request_id}{REOPEN_SEP}{n}"


def reopen_target(backend: Any, lease: Any) -> str | None:
    """The request a reopen verb works for, only when that request's record names this verb; None
    for an ordinary request verb. A reopen the record does not name raises ReopenRefused."""
    brief = lease.brief if isinstance(lease.brief, dict) else {}
    target = brief.get("reopens")
    if not target:
        return None
    current = read_request(backend, str(target))
    named = [
        r
        for r in ((current[0] if current else {}).get("reopens") or [])
        if isinstance(r, dict) and r.get("task_id") == str(lease.task_id)
    ]
    if not named or str(lease.task_id) != reopen_task_id(str(target), int(named[-1].get("n") or 0)):
        raise ReopenRefused(
            f"{lease.task_id} names request {target}, whose record does not list this reopen"
        )
    return str(target)


class ReopenRefused(RuntimeError):
    """A request verb claims to reopen a request whose record does not name it; nothing is written."""


def reopen_fact(
    *, reason: str, task_id: str, n: int, wrong: dict[str, Any], finding: str, at: float
) -> dict[str, Any]:
    """The `reopened` status fact (docs/status-events.schema.json): the page clears the close and the
    reuse it rested on, keeps both in the history as a failed attempt and shows the request in line."""
    summary: dict[str, Any] = {"reopen": n, "finding": finding}
    if wrong:
        summary["wrong_reuse"] = {
            k: wrong.get(k) for k in ("store", "key", "version", "score", "kind")
        }
    return {
        "type": "reopened",
        "at": round(at, 3),
        "ref": task_id,
        "reason": reason[:500],
        "summary": summary,
    }


def reused_pointer(value: dict[str, Any]) -> dict[str, Any]:
    """The library answer a request was closed with: at the request level (before F-REUSE-001) or
    on a part whose route is `reused` (after an accepted check); empty when there is none."""
    if isinstance(value.get("reused_from"), dict):
        return dict(value["reused_from"])
    for part in (value.get("parts") or {}).values():
        if (
            isinstance(part, dict)
            and part.get("route") == "reused"
            and isinstance(part.get("reused_from"), dict)
        ):
            return dict(part["reused_from"])
    return {}


def reopened_value(
    value: dict[str, Any], *, reason: str, n: int, task_id: str, finding: str, at: float
) -> dict[str, Any]:
    """The request record opened again: back to received, the wrong reuse moved to `reuse_withdrawn`,
    its parts cleared for the new plan, and this reopen named in `reopens` for the planner."""
    wrong = reused_pointer(value)
    fact = reopen_fact(reason=reason, task_id=task_id, n=n, wrong=wrong, finding=finding, at=at)
    out = {
        k: v
        for k, v in value.items()
        if k not in ("reused_from", "close_receipt", "event", "parts")
    }
    out["status"] = "received"
    out["parts"] = {}
    if wrong:
        out["reuse_withdrawn"] = [*(value.get("reuse_withdrawn") or []), {**wrong, "reopen": n}]
    else:  # a request whose parts all ended without a result: its earlier parts stay on the record
        out["parts_before_reopen"] = [
            *(value.get("parts_before_reopen") or []),
            {"reopen": n, "parts": value.get("parts") or {}},
        ]
    out["reopens"] = [
        *(value.get("reopens") or []),
        {
            "n": n,
            "task_id": task_id,
            "at": round(at, 3),
            "reason": reason[:500],
            "finding": finding,
        },
    ]
    out["event"] = fact
    out["events"] = [*(value.get("events") or []), fact][-100:]
    return out


def judge_user(question: str, library: dict[str, Any]) -> str:
    return json.dumps({"request": question, "library_answer": library}, ensure_ascii=False)
