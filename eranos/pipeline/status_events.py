"""Status facts for a request's public record: every state change is a new version of the request noun.

Each fact is written as its own version of `eranos.requests/<request_id>`, as that version's
`event`, in the request-status page's own shape (`docs/status-events.schema.json`, `StatusEvent`): `type`, `at` (Unix seconds), `part`, and a
`receipt` hash Tessera wrote or, where Tessera writes none, a `ref` to the record that holds the fact;
plus `worker`, `model` (a model id) with `model_display` (its name in the `models.meta`
catalog) or the `method` of a step that runs no model, `harness` (the worker program, never
called a model), `lease_ends`, `places`, `queue`, `summary`, `reason`, `findings` and `result_id`
where they apply, and `dedicated: true` when one of Eranos's own dedicated workers made the claim. Only the page's own types are used, in the order a request meets them:

    received, plan_claimed, planned, queued, blocked, work_claimed, heartbeat, work_submitted,
    work_released, check_claimed, check_approved, check_sent_back, check_refused,
    signoff_required, delivered, published, library_added, closed

A reused answer is `delivered` with the reuse in its `reason` and `summary`; a failed attempt is
`work_released` (its ok=false receipt, when there is one); a self-approval Tessera or the worker
refused is `check_refused`; a recurring request parked until its next occurrence is `queued` with
`summary.next_at`. Each fact is one compare-and-set write, retried on a version conflict and never
overwritten. The newest MAX_EVENTS facts are also kept in `events`; the history keeps every version.
"""

from __future__ import annotations

import random
import time
from typing import Any

from tessera import NotFound, VersionConflict

from eranos.pipeline.request_noun import FINAL, REQUESTS_STORE, read_request, write_request

MAX_EVENTS = 100
MAX_HEARTBEATS = 3
_ATTEMPTS = 8


def queue_snapshot(backend: Any, agents: list[str] | None = None) -> dict[str, Any] | None:
    """Eranos's queues now: waiting (ready), working (leased eq01/eq02), checking (leased eq03)."""
    try:
        counts = backend.counts()
    except Exception:
        return None

    def get(name: str, field: str) -> int:
        entry = counts.get(name)
        return int(getattr(entry, field, 0) or 0) if entry is not None else 0

    return {
        "waiting": sum(get(q, "ready") for q in ("eq01", "eq02", "eq03")),
        "working": get("eq01", "leased") + get("eq02", "leased"),
        "checking": get("eq03", "leased"),
        "agents": list(agents or []),
    }


def fact(kind: str, **fields: Any) -> dict[str, Any]:
    """One status fact; empty fields are dropped so the record stays small."""
    event: dict[str, Any] = {"type": kind, "at": round(fields.pop("at", None) or time.time(), 3)}
    event.update({k: v for k, v in fields.items() if v is not None and v != [] and v != {}})
    return event


def record_events(
    backend: Any,
    request_id: str,
    events: list[dict[str, Any]],
    *,
    status: str | None = None,
    parts: dict[str, dict[str, Any]] | None = None,
    fields: dict[str, Any] | None = None,
) -> int | None:
    """Record each fact as its own new version of the request noun, carrying it as `event`.

    The request-status page reads the noun's history and draws one fact per version
    (`docs/status-events.schema.json`), so several facts become several versions, in order. The
    status, part updates and fields go with the last of them. `events` keeps the newest facts in
    one place too, for readers of the current version only.
    """
    version: int | None = None
    for index, event in enumerate(events):
        last = index == len(events) - 1
        version = _record_one(
            backend,
            request_id,
            event,
            status=status if last else None,
            parts=parts if last else None,
            fields=fields if last else None,
        )
        if version is None:
            return None
    return version


def _record_one(
    backend: Any,
    request_id: str,
    event: dict[str, Any],
    *,
    status: str | None,
    parts: dict[str, dict[str, Any]] | None,
    fields: dict[str, Any] | None,
) -> int | None:
    for attempt in range(_ATTEMPTS):
        current = read_request(backend, request_id)
        if current is None:
            return None
        value, version = current
        value = dict(value)
        stamped = {**event, "version": version + 1}
        history = [*(value.get("events") or []), stamped]
        if stamped.get("type") == "heartbeat":
            # Liveness, not history: keep only the newest few heartbeats so the record stays small.
            beats = [i for i, e in enumerate(history) if e.get("type") == "heartbeat"]
            drop = set(beats[:-MAX_HEARTBEATS])
            history = [e for i, e in enumerate(history) if i not in drop]
        value["events"] = history[-MAX_EVENTS:]
        value["event"] = stamped
        if fields:
            value.update(fields)
        if parts:
            merged = dict(value.get("parts") or {})
            for number, update in parts.items():
                entry = dict(merged.get(str(number)) or {})
                if entry.get("status") in {"published", "delivered"} and update.get(
                    "status"
                ) not in {
                    None,
                    "published",
                    "delivered",
                }:
                    update = {k: v for k, v in update.items() if k != "status"}
                merged[str(number)] = {**entry, **update}
            value["parts"] = merged
        if status is not None and not (value.get("status") in FINAL and status not in FINAL):
            value["status"] = status
        try:
            return write_request(backend, request_id, value, expected_version=version)
        except VersionConflict:
            time.sleep(0.05 * (attempt + 1) + random.random() * 0.05)  # noqa: S311
            continue
        except NotFound:
            return None
    raise VersionConflict(
        f"{REQUESTS_STORE}/{request_id} kept changing; a {event.get('type')} fact was not recorded"
    )


def has_event(value: dict[str, Any], kind: str, **match: Any) -> bool:
    return any(
        e.get("type") == kind and all(e.get(k) == v for k, v in match.items())
        for e in value.get("events") or []
    )
