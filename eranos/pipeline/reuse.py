"""Reuse before work: a reviewed result that already exists may answer a request, after a check.

Before a request is split, the planner compares it with delivered reports (`eranos.solutions`) and
reviewed process packages (`eranos.catalog`). The comparison is deterministic and follows the
`eranos.instructions/worker` noun's `reuse` rules. It compares the new request with the request each
candidate answered (a report's question, a package's request text), never with a title that carries
the organization's name or with the claims. Shared request phrasing (the form's "a source for every
point", an organization's description) is stripped first, words are lowercased, stopwords dropped,
plurals and common endings trimmed, synonyms mapped to one canonical word, and words too generic to
tell two requests apart dropped. The score is the harmonic mean of the two weighted coverages (each
request's words found in the other; numbers and acronyms weigh more), so a long candidate cannot
match by covering everything. Only a reviewed candidate can match: a report or package whose review
receipt Tessera confirms.

A match never closes a request on its own (finding F-REUSE-001): the planner queues a reuse check, a
verb another worker's key claims, and only an approved check answers the request from the library.
The same question word for word, apart from a test label, is approved by that key with no model call.
Every decision records the best candidate, its score and the threshold.
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


# The bar in code: a noun may raise the reuse threshold, never lower it below this. A match is only a
# candidate, and the reuse check decides, so this bar sets how many checks run, not what gets reused.
MIN_THRESHOLD = 0.5
MIN_TERMS = 3


def _sub_all(patterns: Any, text: str) -> str:
    out = text
    for pattern in patterns or []:
        try:
            out = re.sub(str(pattern), " ", out, flags=re.IGNORECASE)
        except re.error:
            continue
    return out


def strip_labels(text: str, rules: dict[str, Any]) -> str:
    """The request without a test label (the noun's `labels` patterns). Our own labeled requests
    stay in the library, so left in, a label's words make unrelated labeled questions look alike and
    keep a person's own repeat, which has no label, from matching at all."""
    return _sub_all(rules.get("labels"), text)


def strip_shared(text: str, rules: dict[str, Any]) -> str:
    """The request without a label or the phrasing many requests share (the noun's `strip`)."""
    return _sub_all(rules.get("strip"), strip_labels(text, rules))


def _plain_words(text: str) -> str:
    return " ".join(re.sub(r"[^\w$€£%]+", " ", text.casefold()).split())


def same_question(first: str, second: str, rules: dict[str, Any]) -> bool:
    """The same words, apart from a test label, capitals and punctuation."""
    one = _plain_words(strip_labels(first, rules))
    return bool(one) and one == _plain_words(strip_labels(second, rules))


def terms(text: str, rules: dict[str, Any]) -> set[str]:
    stop = set(rules.get("stopwords") or [])
    generic = set(rules.get("generic") or [])
    canonical: dict[str, str] = rules.get("canonical") or {}
    out: set[str] = set()
    for raw in _TOKEN.findall(strip_shared(text, rules).lower()):
        word = raw.strip("'-")
        if not word or word in stop:
            continue
        # A hyphenated word counts as its parts ("food-safety" is "food" and "safety"), unless the
        # noun maps the whole word ("sign-up" is "signup").
        pieces = [word] if word in canonical or "-" not in word else word.split("-")
        for piece in pieces:
            if not piece or piece in stop:
                continue
            piece = canonical.get(piece, piece)
            if piece not in canonical.values():
                piece = canonical.get(_stem(piece), _stem(piece))
            if piece in generic:
                continue
            if len(piece) >= 3 or any(c.isdigit() for c in piece):
                out.add(piece)
    return out


def _weight(word: str) -> float:
    return 3.0 if any(c.isdigit() for c in word) or word in {"irs", "cfr", "fema", "hud"} else 1.0


def score(wanted: set[str], have: set[str]) -> float:
    total = sum(_weight(w) for w in wanted)
    if not total:
        return 0.0
    return round(sum(_weight(w) for w in wanted & have) / total, 4)


def similarity(wanted: set[str], have: set[str]) -> float:
    """Both ways at once: the harmonic mean of each side's weighted share found in the other."""
    forward, back = score(wanted, have), score(have, wanted)
    if not forward or not back:
        return 0.0
    return round(2 * forward * back / (forward + back), 4)


def _untitled(title: str) -> str:
    """A title without the organization prefix the planner gives it ("Food pantry: ...")."""
    head, sep, rest = title.partition(": ")
    return rest if sep and len(head) <= 80 else title


def _report_text(value: dict[str, Any]) -> str:
    """The request a report answered: its question (its title only when it has none)."""
    report = value.get("report") or {}
    return str(report.get("question") or _untitled(str(report.get("title") or "")))


def _process_text(value: dict[str, Any]) -> str:
    """The request a package answered: its request text, or its title and summary."""
    if value.get("request_text"):
        return str(value["request_text"])
    return " ".join(str(value.get(k) or "") for k in ("title", "summary", "description"))


def candidates(backend: Any, rules: dict[str, Any]) -> list[tuple[str, Any, str, str, str]]:
    """(store, record, text, kind, review receipt) for every reviewed result in the reuse stores."""
    limit = int(rules.get("max_candidates") or 200)
    out: list[tuple[str, Any, str, str, str]] = []
    for store in rules.get("stores") or []:
        try:
            records = backend.list_records(store, limit=limit)
        except Exception:  # noqa: S112 - a store this key cannot list has no candidates
            continue
        not_reused = set(rules.get("not_reused") or [])  # taken off display: never offered again
        for record in records:
            if record.key in not_reused:
                continue
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
    expected_kit = f"PRC-{key.split('-', 1)[1][:6].upper()}-01" if "-" in key else ""
    for store, record, _text, kind, receipt in candidates(backend, rules):
        value = record.value if isinstance(record.value, dict) else {}
        tags = [str(t) for t in value.get("tags") or []]
        # Exactly this package: one reuse tag, the kit id the key derives, and a process package.
        if (
            store == "eranos.catalog"
            and [t for t in tags if t.startswith("reuse:")] == [f"reuse:{key}"]
            and str(record.key) == expected_kit
            and (value.get("kit") or {}).get("kit_id") == expected_kit
            and "kind:process_package" in tags
            and verified(backend, value, receipt)
        ):
            title = str((value.get("kit") or {}).get("title") or value.get("title") or "")
            return Match(store, str(record.key), int(record.version), 1.0, kind, receipt, title)
    return None


def find_reuse(
    backend: Any,
    text: str,
    rules: dict[str, Any],
    *,
    output_type: str | None,
    keyed: Any = None,
    considered: dict[str, Any] | None = None,
) -> Match | None:
    """The best reviewed result for this request at or above the threshold, or None. A match is a
    candidate for a reuse check, never an answer by itself. `considered`, when given, receives the
    decision for the record: the best candidate and its score, the threshold, how many were compared."""
    note = considered if considered is not None else {}
    threshold = max(float(rules.get("threshold") or MIN_THRESHOLD), MIN_THRESHOLD)
    note.update({"threshold": threshold, "compared": 0, "best": None})
    exact = keyed_reuse(backend, text, rules, keyed, output_type)
    if exact is not None:
        note.update(best=_brief_match(exact), outcome="exact package key: a reuse check decides")
        return exact
    if output_type != "process":
        for store, record, have_text, kind, receipt in candidates(backend, rules):
            body = record.value if isinstance(record.value, dict) else {}
            if (
                kind == "report"
                and same_question(text, have_text, rules)
                and verified(backend, body, receipt)
            ):
                title = str((body.get("report") or {}).get("title") or "")
                same = Match(store, str(record.key), int(record.version), 1.0, kind, receipt, title)
                note.update(
                    best=_brief_match(same), outcome="the same question: a reuse check decides"
                )
                return same
    wanted = terms(text, rules)
    if len(wanted) < MIN_TERMS:
        note["outcome"] = "too few distinctive words to compare"
        return None
    scored: list[tuple[float, str, Any, str, str]] = []
    for store, record, have_text, kind, receipt in candidates(backend, rules):
        if output_type == "information" and kind != "report":
            continue
        if output_type == "process" and kind == "report":
            continue
        have = terms(have_text, rules)
        if len(have) < MIN_TERMS:
            continue
        note["compared"] += 1
        scored.append((similarity(wanted, have), store, record, kind, receipt))
    scored.sort(key=lambda item: -item[0])
    if scored:
        value, store, record, kind, _ = scored[0]
        note["best"] = {"store": store, "key": str(record.key), "score": value, "kind": kind}
    for value, store, record, kind, receipt in scored:
        if value < threshold:
            break
        body = record.value if isinstance(record.value, dict) else {}
        if not verified(backend, body, receipt):
            continue
        title = str((body.get("report") or body.get("kit") or body).get("title") or "")
        match = Match(store, str(record.key), int(record.version), value, kind, receipt, title)
        note.update(best=_brief_match(match), outcome="above the threshold: a reuse check decides")
        return match
    note["outcome"] = "no reviewed result reaches the threshold"
    return None


def _brief_match(match: Match) -> dict[str, Any]:
    return {"store": match.store, "key": match.key, "score": match.score, "kind": match.kind}
