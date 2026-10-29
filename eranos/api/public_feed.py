"""Project a service-readable feed into an explicitly public response."""

from __future__ import annotations

import re
from typing import Any, TypeGuard

SURFACE = re.compile(r"^surface:[a-z0-9][a-z0-9_-]{1,39}$")
MAX_CURSOR = 2**53 - 1
PUBLIC_ENTRY_FIELDS = (
    "seq",
    "feed",
    "kind",
    "summary",
    "payload",
    "created_at",
    "namespace",
    "producer_surface",
    "visibility_scope",
    "allowed_surfaces",
    "target_cohorts",
    "tags",
)


def _cursor(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_CURSOR


def public_feed_payload(payload: Any, *, after: int) -> dict[str, Any]:
    """Service authority is never inherited by the public HTTP caller.

    This route has no cohort selector, so only universal public entries qualify.
    Advance over hidden entries using the upstream cursor without returning them.
    """
    out: dict[str, Any] = {
        "synthetic": True,
        "feed": "noun.promotions",
        "entries": [],
        "next_cursor": after,
    }
    if not isinstance(payload, dict) or payload.get("feed") != "noun.promotions":
        return {**out, "degraded": True, "reason": "invalid upstream feed response"}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return {**out, "degraded": True, "reason": "invalid upstream feed entries"}
    next_cursor = payload.get("next_cursor")
    if _cursor(next_cursor):
        out["next_cursor"] = max(after, next_cursor)
    for entry in entries:
        if not isinstance(entry, dict) or not _cursor(entry.get("seq")):
            continue
        out["next_cursor"] = max(out["next_cursor"], entry["seq"])
        tags = entry.get("tags")
        cohorts = entry.get("target_cohorts")
        allowed = entry.get("allowed_surfaces")
        if (
            entry["seq"] <= after
            or entry.get("namespace") != "main"
            or entry.get("visibility_scope") != "public_commons"
            or not isinstance(entry.get("producer_surface"), str)
            or not SURFACE.fullmatch(entry["producer_surface"])
            or not isinstance(tags, list)
            or not all(isinstance(tag, str) for tag in tags)
            or "status:verified" not in tags
            or "status:quarantined" in {tag.strip().lower() for tag in tags}
            or not isinstance(allowed, list)
            or not all(
                isinstance(surface, str) and SURFACE.fullmatch(surface) for surface in allowed
            )
            or not isinstance(cohorts, list)
            or not all(isinstance(cohort, str) for cohort in cohorts)
            or "all" not in cohorts
        ):
            continue
        out["entries"].append({key: entry[key] for key in PUBLIC_ENTRY_FIELDS if key in entry})
    return out
