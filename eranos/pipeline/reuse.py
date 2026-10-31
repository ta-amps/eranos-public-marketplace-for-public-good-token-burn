"""Reuse before work: answer a request from a reviewed result that already exists, with no model call.

Before a request is split, the planner compares it with delivered reports (`eranos.solutions`) and
published kits (`eranos.catalog`). The comparison is deterministic and follows the
`eranos.instructions/worker` noun's `reuse` rules: words are lowercased, stopwords dropped, plurals
and common endings trimmed, and synonyms mapped to one canonical word; the score is the weighted
share of the new request's words found in a candidate (numbers and acronyms weigh more). Only a
reviewed candidate can match: a report with its review receipt, or a kit with its review receipt.
A match is delivered as a pointer; nothing is copied, re-run or re-reviewed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_TOKEN = re.compile(r"501\(c\)\(\d+\)|[a-z0-9][a-z0-9'-]*")


@dataclass(frozen=True)
class Match:
    store: str
    key: str
    version: int
    score: float
    kind: str
    review_receipt: str
    title: str


def _stem(word: str) -> str:
    for suffix, keep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)] + keep
    return word


def terms(text: str, rules: dict[str, Any]) -> set[str]:
    stop = set(rules.get("stopwords") or [])
    canonical: dict[str, str] = rules.get("canonical") or {}
    out: set[str] = set()
    for raw in _TOKEN.findall(text.lower()):
        word = raw.strip("'-")
        if not word or word in stop:
            continue
        word = canonical.get(word, word)
        word = canonical.get(_stem(word), _stem(word)) if word not in canonical.values() else word
        if len(word) >= 3 or any(c.isdigit() for c in word):
            out.add(word)
    return out


def _weight(word: str) -> float:
    return 3.0 if any(c.isdigit() for c in word) or word in {"irs", "cfr", "fema", "hud"} else 1.0


def score(wanted: set[str], have: set[str]) -> float:
    total = sum(_weight(w) for w in wanted)
    if not total:
        return 0.0
    return round(sum(_weight(w) for w in wanted & have) / total, 4)


def _report_text(value: dict[str, Any]) -> str:
    report = value.get("report") or {}
    claims = " ".join(str(c.get("text") or "") for c in report.get("claims") or [])
    return " ".join(str(report.get(k) or "") for k in ("title", "question")) + " " + claims


def _kit_text(value: dict[str, Any]) -> str:
    kit = value.get("kit") or {}
    return " ".join(str(kit.get(k) or "") for k in ("title", "summary", "target_org", "track_id"))


def candidates(backend: Any, rules: dict[str, Any]) -> list[tuple[str, Any, str, str, str]]:
    """(store, record, text, kind, review receipt) for every reviewed result in the reuse stores."""
    limit = int(rules.get("max_candidates") or 200)
    out: list[tuple[str, Any, str, str, str]] = []
    for store in rules.get("stores") or []:
        try:
            records = backend.list_records(store, limit=limit)
        except Exception:  # noqa: S112 - a store this key cannot list has no candidates
            continue
        for record in records:
            value = record.value if isinstance(record.value, dict) else {}
            if store == "eranos.solutions":
                receipt = str(value.get("review_receipt") or "")
                if receipt and not value.get("synthetic") and not value.get("reused_from"):
                    out.append((store, record, _report_text(value), "report", receipt))
            elif store == "eranos.catalog":
                receipt = str(value.get("review_receipt") or "")
                if receipt and "status:verified" in (value.get("tags") or []):
                    out.append((store, record, _kit_text(value), "kit", receipt))
    return out


def find_reuse(
    backend: Any, text: str, rules: dict[str, Any], *, output_type: str | None
) -> Match | None:
    """The best reviewed result for this request at or above the threshold, or None."""
    wanted = terms(text, rules)
    if len(wanted) < 3:
        return None
    threshold = float(rules.get("threshold") or 0.6)
    best: Match | None = None
    for store, record, have_text, kind, receipt in candidates(backend, rules):
        if output_type == "information" and kind != "report":
            continue
        if output_type == "process" and kind == "report":
            continue
        value = score(wanted, terms(have_text, rules))
        if value >= threshold and (best is None or value > best.score):
            title = str(
                ((record.value or {}).get("report") or (record.value or {}).get("kit") or {}).get(
                    "title"
                )
                or ""
            )
            best = Match(store, str(record.key), int(record.version), value, kind, receipt, title)
    return best
