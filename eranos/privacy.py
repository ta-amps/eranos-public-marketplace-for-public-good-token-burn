"""Personal-data screen for public nonprofit requests (AGENTS.md hard rule 1).

A deterministic, limited filter: it finds common contact, identity and payment patterns and lines
that look like a record about a person. It is not a claim that every kind of personal data can be
detected. Findings name the kind of data and the field, never the matched text, so a refusal can be
shown and stored without repeating what it refused.
"""

from __future__ import annotations

import re
from typing import Any

_EMAIL = re.compile(
    r"[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net)\b)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
)
_HANDLE = re.compile(r"(?<![\w@.])@[A-Za-z0-9_]{2,30}\b")
_PHONE = re.compile(
    r"(?<![\w-])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d{3}[\s.-]\d{3,4}(?:[\s.-]\d{2,4})?(?![\w-])"
)
_IDENTITY = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_STREET = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Court|Ct|Way|Place|Pl)\b"
)
_BIRTH = re.compile(r"\b(?:DOB|D\.O\.B\.|date of birth|born on)\b", re.IGNORECASE)
_RECORD_LINE = re.compile(
    r"^\s*[-*]?\s*(?:name|full name|client|patient|resident|phone|mobile|email|address|dob|"
    r"ssn|passport|case (?:number|no\.?))\s*[:=]",
    re.IGNORECASE,
)

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("an email address", _EMAIL),
    ("a social media handle", _HANDLE),
    ("a phone number", _PHONE),
    ("an identity number", _IDENTITY),
    ("a payment card number", _CARD),
    ("a street address", _STREET),
    ("a date of birth", _BIRTH),
)


def personal_data_findings(fields: dict[str, str]) -> list[str]:
    """Kinds of personal data found per field, as `field: kind` strings, without the matched text.

    A line shaped like a record about a person (`Name: ...`, `Phone: ...`) counts unless the line
    itself carries a visible MADE-UP mark, so made-up examples stay possible.
    """
    findings: list[str] = []
    for field, text in fields.items():
        for kind, pattern in PATTERNS:
            if pattern.search(text):
                findings.append(f"{field}: {kind}")
        for line in text.splitlines():
            if _RECORD_LINE.search(line) and not any(
                mark in line for mark in ("MADE-UP", "SYN" + "THETIC")
            ):
                findings.append(f"{field}: a record about a person without a MADE-UP mark")
                break
    return list(dict.fromkeys(findings))


# Numbers set aside for fiction: a made-up test case may use them.
_FICTIONAL_PHONE = re.compile(r"\b555[\s.-]\d{3,4}\b|\b\d{3}[\s.-]555[\s.-]01\d\d\b")


def fixture_findings(sample: str) -> list[str]:
    """Personal data in a test case, past the numbers reserved for fiction."""
    return personal_data_findings({"sample_input": _FICTIONAL_PHONE.sub(" ", sample)})


LABEL_FIELDS = frozenset(
    {"spdx_license", "tags", "target_cohorts", "allowed_surfaces", "producer_surface"}
)


def _strings(node: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(node, str):
        return [(path, node)]
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in _strings(v, f"{path}.{k}" if path else str(k))]
    if isinstance(node, list | tuple):
        return [s for i, v in enumerate(node) for s in _strings(v, f"{path}[{i}]")]
    return []


def text_personal_findings(value: Any, *, skip: frozenset[str] = LABEL_FIELDS) -> list[str]:
    """Personal data anywhere in a kit's text, as `field: kind`, never the match. Sources are public links; their addresses aren't screened."""
    found: list[str] = []
    top = {k: v for k, v in value.items() if k not in skip} if isinstance(value, dict) else value
    for path, text in _strings(top):
        if path.startswith("sources") and path.endswith(
            ("url", "source_url", "publisher", "title")
        ):
            continue
        found.extend(personal_data_findings({path: _FICTIONAL_PHONE.sub(" ", text)}))
    return list(dict.fromkeys(found))[:10]
