"""The planner's work on one claimed request verb (`eq01`, kind `request`).

A fresh request is checked (personal data, accusations, prohibited topics), then compared with
reviewed results that already exist (reuse: a match is delivered as a pointer, no new verbs and no
model call). Otherwise it is split into parts by what the nonprofit asked for (`output_type`
information, process or both; without one, by the classify noun's markers): information parts
become research verbs with permitted public sources, process parts become process-package builds,
and kit parts (requests from the earlier one-box form) become kit builds; each with its own review
verb. When every part has resolved, a one-off request is closed with its final receipt; a recurring
one records the occurrence and is parked for its period, then planned again when it wakes.

This is ordinary work by an authorized worker holding the verb: no new queue, authority or service.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import Any

from tessera import ChildSpec, NotFound, VersionConflict

from eranos import __version__
from eranos.pipeline import process as process_part
from eranos.pipeline import research
from eranos.pipeline.request_noun import read_request, update_request_status, write_request
from eranos.pipeline.requests import (
    _CONTROL,
    _LINK,
    OPEN_VERB_TAG,
    PLANS_STORE,
    _close,
    _write_plan,
    check_findings,
    classify_parts,
)
from eranos.pipeline.reuse import find_reuse
from eranos.pipeline.status_events import fact, queue_snapshot, record_events

OUTPUT_TYPES = ("process", "information", "both")
FREQUENCIES = ("one-off", "recurring")


def request_terms(brief: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """The requester's own choices, kept only when they are known values; a period is bounded."""
    terms: dict[str, Any] = {}
    output_type = str(brief.get("output_type") or "")
    frequency = str(brief.get("frequency") or "")
    if output_type in OUTPUT_TYPES:
        terms["output_type"] = output_type
    if frequency in FREQUENCIES:
        terms["frequency"] = frequency
    if frequency == "recurring":
        recurring = rules.get("recurring") or {}
        cadences: dict[str, int] = recurring.get("cadences") or {}
        cadence = str(brief.get("cadence") or "")
        period = cadences.get(cadence)
        if isinstance(brief.get("period_s"), int | float):
            period = int(brief["period_s"])
        if cadence in cadences:
            terms["cadence"] = cadence
        if period:
            terms["period_s"] = max(int(recurring.get("min_period_seconds") or 900), int(period))
    return terms


def _parts(text: str, rules: dict[str, Any], output_type: str | None) -> list[dict[str, Any]]:
    """Parts by the nonprofit's choice first, then by the classify noun's markers."""
    if output_type == "process":
        whole = " ".join(text.split())
        return [{"route": "private-files", "text": whole, "part": 1, "legal": False}]
    parts = classify_parts(text, rules)
    if output_type == "information":
        # The nonprofit chose Information: every part is researched from public sources, even one
        # that mentions donors, clients or personal information (FB1-025). Personal data in the
        # request itself is refused by the privacy check, never by sending the part elsewhere.
        for part in parts:
            if part["route"] == "private-files":
                part["route"] = "public-only"
    return parts


class Planner:
    """Planner work for one lease; `backend` is the lease gate the worker loop hands it."""

    def __init__(
        self,
        backend: Any,
        lease: Any,
        *,
        worker: str,
        nouns: dict[str, dict[str, Any]],
        tracks_root: Path | None = None,
        handler: Any = None,
        who: dict[str, Any] | None = None,
    ) -> None:
        self.b = backend
        self.handler = handler
        self.who = dict(who or {"worker": worker})
        self.lease = lease
        self.worker = worker
        self.rules = nouns["worker"]
        self.classify = nouns["classify"]
        self.guardrails = nouns.get("public-research")
        self.tracks_root = tracks_root
        self.request_id = str(lease.task_id)
        brief = lease.brief if isinstance(lease.brief, dict) else {}
        self.brief = brief
        text = str(brief.get("text") or brief.get("description") or "")
        self.text = _CONTROL.sub("", text).strip()[:4000]
        org = _CONTROL.sub("", str(brief.get("organization_type") or "")).strip()[:120]
        # The type of organization is published with the plan, so it passes the same screen.
        self.org = org if org and not check_findings({"organization_type": org}) else "Nonprofit"
        self.links = [str(x) for x in brief.get("links") or [] if _LINK.match(str(x))][:10]
        self.terms = request_terms(brief, self.rules)

    # facts ----------------------------------------------------------------------------------
    def _facts(self, events: list[dict[str, Any]], **kwargs: Any) -> None:
        record_events(self.b, self.request_id, events, **kwargs)

    def _claimed_fact(self) -> dict[str, Any]:
        return fact(
            "plan_claimed",
            at=self.lease.claimed_at,
            receipt=self.lease.claim_receipt,
            **self.who,
            method="deterministic planner (no model)",
            harness="eranos-worker",
            harness_version=__version__,
            lease_ends=self.lease.expires_at,
            queue=queue_snapshot(self.b, [self.worker]),
        )

    def _ensure_noun(self) -> dict[str, Any]:
        current = read_request(self.b, self.request_id)
        if current is None:
            source = (
                self.brief.get("source") if isinstance(self.brief.get("source"), dict) else None
            )
            value = {
                "schema_version": 1,
                "request_id": self.request_id,
                "status": "received",
                "text": self.text,
                "source": source,
                **{k: v for k, v in self.terms.items() if k != "period_s"},
            }
            with contextlib.suppress(VersionConflict):
                write_request(self.b, self.request_id, value, expected_version=0)
            current = read_request(self.b, self.request_id)
        return current[0] if current else {}

    # entry ----------------------------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        noun = self._ensure_noun()
        events = (
            []
            if any(e.get("type") == "received" for e in noun.get("events") or [])
            else [
                fact(
                    "received",
                    at=self._created_at(),
                    ref=self.request_id,
                    queue=queue_snapshot(self.b),
                )
            ]
        )
        self._facts([*events, self._claimed_fact()])
        occurrences = list(noun.get("occurrences") or [])
        if not self.lease.children and not occurrences:
            return self.plan(1, reuse=self.terms.get("frequency") != "recurring")
        latest = (
            occurrences[-1]
            if occurrences
            else {"n": 1, "status": "planned", "children": [c.task_id for c in self.lease.children]}
        )
        if latest.get("status") == "planned":
            return self.finish(latest)
        return self.wake(latest)

    def _created_at(self) -> float | None:
        try:
            return float(self.b.task(self.request_id).created_at)
        except Exception:
            return None

    # planning -------------------------------------------------------------------------------
    def plan(self, occurrence: int, *, reuse: bool) -> dict[str, Any]:
        findings = check_findings({"text": self.text, "links": " ".join(self.links)})
        if len(self.text) < 10:
            findings.append("the request needs at least a sentence describing the job")
        if findings:
            return self.block(findings)
        if reuse:
            match = find_reuse(
                self.b,
                self.text,
                self.rules.get("reuse") or {},
                output_type=self.terms.get("output_type"),
                keyed=getattr(self.handler, "reuse_signature", None),
            )
            if match is not None:
                return self.reuse(match)
        parts = _parts(self.text, self.classify, self.terms.get("output_type"))
        children, plan = self.children(parts, occurrence)
        if not children:
            return self.block(["no part can start yet; a person looks at the request first"])
        before = queue_snapshot(self.b)
        ids = self.b.split(self.lease.task_id, self.lease.fencing_token, children)
        places: dict[str, int] = {}
        for entry in plan:
            if "children" in entry:
                work, review = entry.pop("children")
                entry["work_task_id"], entry["review_task_id"] = ids[work], ids[review]
                places[str(entry["part"])] = int((before or {}).get("waiting", 0)) + len(places) + 1
        plain = [
            f"Part {p['part']}: {self.classify['plain_words'].get(p['route'], p['route'])}"
            for p in plan
        ]
        if occurrence == 1:
            _write_plan(self.b, self.request_id, self.lease, plan, plain, **self.terms)
        else:
            self._plan_noun_occurrence(occurrence, plan, plain)
        noun = read_request(self.b, self.request_id)
        occurrences = list((noun[0] if noun else {}).get("occurrences") or [])
        occurrences.append(
            {
                "n": occurrence,
                "status": "planned",
                "children": ids,
                "planned_at": round(time.time(), 3),
            }
        )
        self._facts(
            [
                fact(
                    "planned",
                    receipt=self.lease.claim_receipt,
                    **self.who,
                    parts=plan,
                    places=places,
                    summary={
                        "places": "estimated from the number of verbs waiting when this was planned"
                    }
                    if places
                    else None,
                    queue=queue_snapshot(self.b),
                    occurrence=occurrence if self.terms.get("frequency") == "recurring" else None,
                    ref=f"{PLANS_STORE}/{self.request_id}",
                ),
                fact(
                    "queued",
                    **self.who,
                    places=places,
                    ref=f"{PLANS_STORE}/{self.request_id}",
                    summary={"places": "estimated", "parts": len(places)},
                ),
            ],
            status="open_for_build",
            parts={
                str(p["part"]): {
                    "route": p["route"],
                    "status": "open" if p["route"] != "held" else "held",
                    "occurrence": occurrence,
                }
                for p in plan
            },
            fields={
                "plan": {"store": PLANS_STORE, "key": self.request_id},
                "occurrences": occurrences,
            },
        )
        return {
            "node": "check",
            "status": "split",
            "request_id": self.request_id,
            "plan": plan,
            "occurrence": occurrence,
            "claim_receipt": self.lease.claim_receipt,
        }

    def children(
        self, parts: list[dict[str, Any]], occurrence: int
    ) -> tuple[list[ChildSpec], list[dict[str, Any]]]:
        out: list[ChildSpec] = []
        plan: list[dict[str, Any]] = []
        request = {
            "request_id": self.request_id,
            "text": self.text,
            "organization_type": self.org,
            "links": self.links,
            **self.terms,
        }
        for part in parts:
            entry: dict[str, Any] = {k: part[k] for k in ("part", "route", "text", "legal")} | dict(
                self.terms
            )
            if part["route"] == "public-only" and self.guardrails is not None:
                brief = research.research_brief(
                    self.request_id,
                    part,
                    self.org,
                    self.guardrails,
                    self.rules,
                    self.links,
                    self.terms,
                    occurrence,
                )
                entry.update(report_id=brief["report_id"])
                kinds, review = ("research", "report_review"), research.review_brief(brief)
            elif part["route"] == "private-files":
                # Work on the nonprofit's own files becomes a process package its agent runs.
                brief = process_part.process_brief(
                    self.request_id, part, self.org, request, occurrence
                )
                entry.update(route="process")
                kinds = (process_part.BUILD_KIND, process_part.REVIEW_KIND)
                review = process_part.process_review_brief(brief)
            else:
                entry["route"] = "held"
                plan.append(entry)
                continue
            entry["children"] = [len(out), len(out) + 1]
            tags = [f"part:{part['part']}"]
            out.append(
                ChildSpec(
                    queue="eq02",
                    kind=kinds[0],
                    effect_class="write-internal",
                    brief=brief,
                    tags=[*tags, f"kind:{kinds[0]}", OPEN_VERB_TAG],
                )
            )
            out.append(
                ChildSpec(
                    queue="eq03",
                    kind=kinds[1],
                    effect_class="write-internal",
                    brief=review,
                    tags=[*tags, f"kind:{kinds[1]}"],
                    after=[len(out) - 1],
                )
            )
            plan.append(entry)
        return out, plan

    def _plan_noun_occurrence(
        self, occurrence: int, plan: list[dict[str, Any]], plain: list[str]
    ) -> None:
        current = self.b.get_record(PLANS_STORE, self.request_id)
        value = dict(current.value)
        value.setdefault("occurrences", []).append(
            {
                "n": occurrence,
                "parts": plan,
                "plain": plain,
                "claim_receipt": self.lease.claim_receipt,
            }
        )
        value["parts"], value["plain"] = plan, plain
        self.b.put_record(
            PLANS_STORE,
            self.request_id,
            value,
            expected_version=current.version,
            producer_surface="surface:eranos",
            visibility_scope="public_commons",
            tags=["kind:plan"],
        )

    def block(self, findings: list[str]) -> dict[str, Any]:
        update_request_status(self.b, self.request_id, "blocked", text=None, findings=findings)
        _write_plan(
            self.b,
            self.request_id,
            self.lease,
            [],
            [self.classify["plain_words"]["blocked"]],
            findings=findings,
        )
        receipt = self.b.submit(
            self.lease.task_id,
            self.lease.fencing_token,
            {
                "node": "check",
                "request_id": self.request_id,
                "status": "blocked",
                "findings": findings,
            },
            idempotency_key=f"{self.lease.task_id}:{self.lease.fencing_token}",
            ok=True,
        )
        self._facts(
            [
                fact(
                    "blocked",
                    receipt=receipt.receipt_hash,
                    **self.who,
                    findings=findings,
                    ref=f"{PLANS_STORE}/{self.request_id}",
                )
            ]
        )
        return {"status": "blocked", "findings": findings, "receipt": receipt.receipt_hash}

    def reuse(self, match: Any) -> dict[str, Any]:
        pointer = {
            "store": match.store,
            "key": match.key,
            "version": match.version,
            "score": match.score,
            "kind": match.kind,
            "review_receipt": match.review_receipt,
            "title": match.title,
        }
        plain = [
            f"Found an existing reviewed answer: {match.title or match.key}. No new work was needed."
        ]
        _write_plan(
            self.b,
            self.request_id,
            self.lease,
            [{"part": 1, "route": "reused", "text": self.text, "reused_from": pointer}],
            plain,
        )
        receipt = self.b.submit(
            self.lease.task_id,
            self.lease.fencing_token,
            {
                "node": "close",
                "status": "reused",
                "request_id": self.request_id,
                "reused": pointer,
                "new_verbs": 0,
                "model_tokens": 0,
            },
            idempotency_key=f"{self.lease.task_id}:{self.lease.fencing_token}",
            ok=True,
        )
        result_ref = f"{match.store}/{match.key}"
        part = {
            "route": "reused",
            "status": "delivered" if match.kind == "report" else "published",
            "review_receipt": match.review_receipt,
            "reused_from": pointer,
        }
        if match.kind == "report":
            part["solution"] = {"store": match.store, "key": match.key, "version": match.version}
        else:
            part["kit_id"] = match.key
        self._facts(
            [
                fact(
                    "delivered" if match.kind == "report" else "published",
                    part=1,
                    receipt=receipt.receipt_hash,
                    **self.who,
                    ref=result_ref,
                    result_id=match.key,
                    reason="Found an existing reviewed answer: no new work and no new tokens.",
                    summary={
                        "reused": True,
                        "score": match.score,
                        "new_verbs": 0,
                        "model_tokens": 0,
                    },
                ),
                fact("closed", receipt=receipt.receipt_hash, **self.who),
            ],
            status="closed",
            parts={"1": part},
            fields={
                "close_receipt": receipt.receipt_hash,
                "reused_from": pointer,
                "plan": {"store": PLANS_STORE, "key": self.request_id},
            },
        )
        return {"status": "reused", "receipt": receipt.receipt_hash, "reused": pointer}

    # after the parts resolve ----------------------------------------------------------------
    def _outcomes(self, ids: list[str]) -> list[dict[str, Any]]:
        mine = [c for c in self.lease.children if c.task_id in set(ids)] or list(
            self.lease.children
        )
        return [
            {
                "task_id": c.task_id,
                "state": c.state,
                "status": (c.output or {}).get("status") if isinstance(c.output, dict) else None,
                "receipt": c.receipt_hash,
            }
            for c in mine
        ]

    def _store_occurrences(
        self,
        occurrences: list[dict[str, Any]],
        events: list[dict[str, Any]],
        status: str | None = None,
    ) -> None:
        self._facts(events, status=status, fields={"occurrences": occurrences})

    def recover(self, ids: list[str]) -> list[dict[str, Any]]:
        """Finish an approved review whose delivery or publication was cut short (a crash, a lost
        connection): the review's recorded output holds everything needed, and both steps are
        idempotent, so a result that was already delivered is left as it is."""
        done: list[dict[str, Any]] = []
        for child in self.lease.children:
            out = child.output if isinstance(child.output, dict) else {}
            if (
                child.task_id not in set(ids)
                or child.state != "done"
                or out.get("approved") is not True
            ):
                continue
            try:
                if out.get("node") == "report_review" and isinstance(out.get("report"), dict):
                    mine = out["report"].get("request_id") == self.request_id
                    if mine:
                        research.ensure_delivered(
                            self.b,
                            report=out["report"],
                            request_id=self.request_id,
                            part=out.get("part"),
                            review_task_id=child.task_id,
                            review_receipt=str(child.receipt_hash),
                            research_receipt=out.get("research_receipt"),
                        )
                    done.append({"task_id": child.task_id, "delivered": mine})
                elif out.get("node") == "process_review" and isinstance(out.get("records"), dict):
                    process_part.ensure_published(
                        self.b,
                        out,
                        handler=self.handler,
                        review_task_id=child.task_id,
                        review_receipt=str(child.receipt_hash),
                        request_id=self.request_id,
                        part=out.get("part"),
                    )
                    done.append({"task_id": child.task_id, "published": True})
            except Exception as exc:
                done.append(
                    {
                        "task_id": child.task_id,
                        "part": out.get("part"),
                        "error": f"{type(exc).__name__}: {exc}"[:400],
                    }
                )
        return done

    def finish(self, latest: dict[str, Any]) -> dict[str, Any]:
        noun = read_request(self.b, self.request_id)
        value = noun[0] if noun else {}
        occurrences = list(value.get("occurrences") or [latest])
        failed = [d for d in self.recover(list(latest.get("children") or [])) if d.get("error")]
        if (
            failed
        ):  # an approved result that could not be delivered or published stays on the record
            self._facts(
                [
                    fact(
                        "check_sent_back",
                        part=d.get("part"),
                        ref=f"{d['task_id']} publication",
                        **self.who,
                        reason=f"approved, but not published: {d['error']}",
                        summary={"role": "planner"},
                    )
                    for d in failed
                ]
            )
        outcomes = self._outcomes(list(latest.get("children") or []))
        latest = {
            **latest,
            "status": "finished",
            "outcomes": outcomes,
            "finished_at": round(time.time(), 3),
        }
        occurrences[-1] = latest
        recurring = self.terms.get("frequency") == "recurring" and self.terms.get("period_s")
        limit = int((self.rules.get("recurring") or {}).get("max_occurrences") or 12)
        if recurring and int(latest["n"]) < limit:
            return self.park(occurrences, int(self.terms["period_s"]))
        closed = _close(self.b, self.lease)
        self._store_occurrences(
            occurrences,
            [
                fact(
                    "closed",
                    receipt=closed["receipt"],
                    **self.who,
                    summary={"parts": len(outcomes)},
                )
            ],
        )
        return closed

    def park(
        self, occurrences: list[dict[str, Any]], period: int, wait: float | None = None
    ) -> dict[str, Any]:
        limit = int((self.rules.get("recurring") or {}).get("max_park_seconds") or 2_592_000)
        due = occurrences[-1].get("next_at") or (time.time() + period)
        resume_within = max(1.0, min(float(wait if wait is not None else period), float(limit)))
        view = self.b.park(
            self.lease.task_id,
            self.lease.fencing_token,
            reason=f"recurring request: next occurrence due at {int(due)}",
            resume_within=resume_within,
        )
        occurrences[-1] = {
            **occurrences[-1],
            "status": "scheduled",
            "next_at": round(float(due), 3),
            "park": int(view.parks),
        }
        self._store_occurrences(
            occurrences,
            [
                fact(
                    "queued",
                    reason=f"Recurring: the next occurrence starts at {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(float(due)))}.",
                    ref=f"{self.request_id} park {view.parks}",
                    **self.who,
                    summary={
                        "next_at": round(float(due), 3),
                        "occurrence": int(occurrences[-1]["n"]) + 1,
                    },
                )
            ],
        )
        return {
            "status": "scheduled",
            "next_at": due,
            "park": view.parks,
            "occurrence": occurrences[-1]["n"],
        }

    def wake(self, latest: dict[str, Any]) -> dict[str, Any]:
        noun = read_request(self.b, self.request_id)
        occurrences = list((noun[0] if noun else {}).get("occurrences") or [latest])
        recurring = self.terms.get("frequency") == "recurring" and self.terms.get("period_s")
        limit = int((self.rules.get("recurring") or {}).get("max_occurrences") or 12)
        if not recurring or int(latest["n"]) >= limit:
            closed = _close(self.b, self.lease)
            self._store_occurrences(
                occurrences, [fact("closed", receipt=closed["receipt"], **self.who)]
            )
            return closed
        due = float(latest.get("next_at") or 0)
        # An operator may re-run a parked occurrence now (resume input {"rerun": true}); recorded.
        rerun = any(
            isinstance(i, dict) and i.get("rerun") is True for i in (self.lease.inputs or [])[-1:]
        )
        if rerun:
            self._facts(
                [
                    fact(
                        "queued",
                        **self.who,
                        ref=f"{self.request_id} park {latest.get('park')}",
                        reason="An operator re-ran this recurring request's occurrence now instead of at its next date.",
                        summary={"rerun": True, "occurrence": int(latest["n"]) + 1},
                    )
                ]
            )
        if due and time.time() < due - 5 and not rerun:
            return self.park(occurrences, int(self.terms["period_s"]), wait=due - time.time())
        return self.plan(int(latest["n"]) + 1, reuse=False)


def load_nouns(backend: Any) -> dict[str, dict[str, Any]]:
    """The instructions the planner follows, read from Tessera; a missing rule stops the verb."""
    out: dict[str, dict[str, Any]] = {}
    for key in ("classify", "worker", "public-research"):
        try:
            out[key] = dict(backend.get_record("eranos.instructions", key).value)
        except NotFound:
            if key != "public-research":
                raise RuntimeError(
                    f"the eranos.instructions/{key} noun is missing; nothing was planned"
                ) from None
    return out
