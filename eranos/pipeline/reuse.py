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


def _process_text(value: dict[str, Any]) -> str:
    return " ".join(
        str(value.get(k) or "") for k in ("title", "summary", "description", "request_text")
    )


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
                made_up = value.get("made_up_sample") or value.get("synthetic")
                if receipt and not made_up and not value.get("reused_from"):
                    out.append((store, record, _report_text(value), "report", receipt))
            elif store in ("eranos.processes", "eranos.catalog"):
                # Process packages only (they carry a reuse key); kits are not offered as answers.
                receipt = str(value.get("review_receipt") or "")
                tags = [str(t) for t in value.get("tags") or []]
                if (
                    receipt
                    and value.get("review_task_id")
                    and any(t.startswith("reuse:") for t in tags)
                ):
                    out.append(
                        (
                            store,
                            record,
                            _process_text(value) + " " + _process_text(value.get("kit") or {}),
                            "process",
                            receipt,
                        )
                    )
    return out


def verified(backend: Any, value: dict[str, Any], receipt: str) -> bool:
    """Tessera, not the record, says the review happened: its result carries this receipt."""
    task_id = str(value.get("review_task_id") or "")
    if not task_id:
        return False
    try:
        results = backend.results(task_id)
    except Exception:
        return False
    for result in results:
        out = result.output if isinstance(result.output, dict) else {}
        if result.receipt_hash == receipt and result.ok and out.get("approved") is True:
            return True
    return False


def keyed_reuse(
    backend: Any, text: str, rules: dict[str, Any], keyed: Any, output_type: str | None
) -> Match | None:
    """An exact match on a process package's reuse key (`reuse:<key>` among a reviewed catalog
    entry's tags), from the process handler's deterministic signature; 0 tokens."""
    if keyed is None or output_type == "information":
        return None
    key = (keyed(text) or {}).get("key")
    if not key:
        return None
    for store, record, _text, kind, receipt in candidates(backend, rules):
        value = record.value if isinstance(record.value, dict) else {}
        if (
            store == "eranos.catalog"
            and f"reuse:{key}" in (value.get("tags") or [])
            and verified(backend, value, receipt)
        ):
            title = str((value.get("kit") or {}).get("title") or value.get("title") or "")
            return Match(store, str(record.key), int(record.version), 1.0, kind, receipt, title)
    return None


def find_reuse(
    backend: Any, text: str, rules: dict[str, Any], *, output_type: str | None, keyed: Any = None
) -> Match | None:
    """The best reviewed result for this request at or above the threshold, or None."""
    exact = keyed_reuse(backend, text, rules, keyed, output_type)
    if exact is not None:
        return exact
    wanted = terms(text, rules)
    if len(wanted) < 3:
        return None
    threshold = float(rules.get("threshold") or 0.6)
    scored: list[tuple[float, str, Any, str, str]] = []
    for store, record, have_text, kind, receipt in candidates(backend, rules):
        if output_type == "information" and kind != "report":
            continue
        if output_type == "process" and kind == "report":
            continue
        value = score(wanted, terms(have_text, rules))
        if value >= threshold:
            scored.append((value, store, record, kind, receipt))
    for value, store, record, kind, receipt in sorted(scored, key=lambda item: -item[0]):
        body = record.value if isinstance(record.value, dict) else {}
        if not verified(backend, body, receipt):
            continue
        title = str((body.get("report") or body.get("kit") or body).get("title") or "")
        return Match(store, str(record.key), int(record.version), value, kind, receipt, title)
    return None
