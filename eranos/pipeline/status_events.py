"""Status facts for a request's public record: every state change is a new version of the request noun.

Each fact is appended to `eranos.requests/<request_id>`'s `events` list in the request-status page's
own shape (web/src/lib/status/types.ts `StatusEvent`): `type`, `at` (Unix seconds), `part`, and a
`receipt` hash Tessera wrote or, where Tessera writes none, a `ref` to the record that holds the fact;
plus `worker`, `model`, `lease_ends`, `places`, `queue`, `summary`, `reason`, `findings` and
`result_id` where they apply. Types used here, in the order a request meets them:

    received, plan_claimed, planned, blocked, reused, work_claimed, heartbeat, work_submitted,
    work_failed, work_released, check_claimed, check_approved, check_sent_back, signoff_required,
    delivered, published, added, scheduled, closed

`reused`, `work_failed`, `added` and `scheduled` are additions to the page's list: an existing
reviewed answer was delivered, a verb failed (its ok=false receipt), the result's nouns entered the
library, and a recurring request was parked until its next occurrence. A fact is written with the
request's other fields (status, parts) in one compare-and-set write, retried on a version conflict
and never overwritten. The newest MAX_EVENTS facts are kept; the noun's history keeps every version.
"""

from __future__ import annotations

import random
import time
from typing import Any

from tessera import NotFound, VersionConflict

from eranos.pipeline.request_noun import FINAL, REQUESTS_STORE, read_request, write_request

MAX_EVENTS = 300
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
    """Append facts (and optionally a status, part updates or fields) as one new noun version."""
    for attempt in range(_ATTEMPTS):
        current = read_request(backend, request_id)
        if current is None:
            return None
        value, version = current
        value = dict(value)
        stamped = [{**event, "version": version + 1} for event in events]
        value["events"] = [*(value.get("events") or []), *stamped][-MAX_EVENTS:]
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
        f"{REQUESTS_STORE}/{request_id} kept changing; {len(events)} facts not recorded"
    )


def has_event(value: dict[str, Any], kind: str, **match: Any) -> bool:
    return any(
        e.get("type") == kind and all(e.get(k) == v for k, v in match.items())
        for e in value.get("events") or []
    )
