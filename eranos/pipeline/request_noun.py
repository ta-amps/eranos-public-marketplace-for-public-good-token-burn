"""The nonprofit request noun (`eranos.requests/<request_id>`) and its recorded states.

A request is a versioned noun. Its state changes are new versions written by the verbs that move it:
intake (`received`, quarantined), the `eq01` classify step (`open_for_build` with one entry per part,
or `blocked`), each part's review (`in_review`, `awaiting_steward`, `needs_revision`, then
`published` for a kit or `delivered` for a report) and the request's close (`closed`). Who did each
step lives in the verbs' receipts.
"""

from __future__ import annotations

from typing import Any

from tessera import NotFound, VersionConflict

REQUESTS_STORE = "eranos.requests"
PRODUCER = "surface:eranos"
STATES = (
    "received",
    "blocked",
    "open_for_build",
    "in_review",
    "awaiting_steward",
    "needs_revision",
    "published",
    "delivered",
    "closed",
)
FINAL = frozenset({"published", "delivered", "closed"})
PART_STATES = frozenset(
    {
        "open",
        "held",
        "in_review",
        "awaiting_steward",
        "needs_revision",
        "published",
        "delivered",
        "delivered_unaudited",
    }
)


def request_governance(status: str, track_id: str | None = None) -> dict[str, Any]:
    """Received requests stay quarantined; every later state is public, like the request form."""
    tags = ["status:quarantined" if status == "received" else f"state:{status}", "kind:ngo_request"]
    if track_id:
        tags.append(f"track:{track_id}")
    return {
        "producer_surface": PRODUCER,
        "visibility_scope": "surface_only" if status == "received" else "public_commons",
        "tags": tags,
    }


def write_request(
    backend: Any, request_id: str, value: dict[str, Any], *, expected_version: int
) -> int:
    governance = request_governance(str(value["status"]), value.get("track_id"))
    saved = backend.put_record(
        REQUESTS_STORE, request_id, value, expected_version=expected_version, **governance
    )
    return int(saved.version)


def read_request(backend: Any, request_id: str) -> tuple[dict[str, Any], int] | None:
    try:
        record = backend.get_record(REQUESTS_STORE, request_id)
    except NotFound:
        return None
    return dict(record.value), int(record.version)


def update_request_status(backend: Any, request_id: str, status: str, **fields: Any) -> int | None:
    """Record a new state as a new version; a concurrent writer is retried, never overwritten."""
    if status not in STATES:
        raise ValueError(f"unknown request state {status!r}")
    for _ in range(3):
        current = read_request(backend, request_id)
        if current is None:
            return None
        value, version = current
        if value.get("status") in FINAL and status not in FINAL:
            return version
        value.pop("event", None)  # a version without a new fact carries no event (status page)
        try:
            return write_request(
                backend, request_id, {**value, **fields, "status": status}, expected_version=version
            )
        except VersionConflict:
            continue
    raise VersionConflict(f"request {request_id} kept changing; state {status!r} not recorded")


def update_request_part(
    backend: Any, request_id: str, part: Any, status: str, **fields: Any
) -> int | None:
    """Record one part's new state as a new version of the request noun."""
    if status not in PART_STATES:
        raise ValueError(f"unknown part state {status!r}")
    for _ in range(3):
        current = read_request(backend, request_id)
        if current is None:
            return None
        value, version = current
        value.pop("event", None)  # a version without a new fact carries no event (status page)
        parts = dict(value.get("parts") or {})
        entry = dict(parts.get(str(part)) or {})
        if entry.get("status") in {"published", "delivered"}:
            return version
        parts[str(part)] = {**entry, **fields, "status": status}
        try:
            return write_request(
                backend, request_id, {**value, "parts": parts}, expected_version=version
            )
        except VersionConflict:
            continue
    raise VersionConflict(f"request {request_id} kept changing; part {part} not recorded")
