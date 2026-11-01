"""The words visitors and agents see: never "synthetic".

Owner, October 31, 2026: "DO NOT INCLUDE SYNTHETIC." The site says "example" instead, uses general names ("tests",
"evaluations") for checks, and marks a practice case with ``Practice case: an example, not a real person or case.``
Records and the verifier may still hold the former internal mark; ``visible`` translates on the way out (snapshot
files, the Worker's answers) and the verifier accepts either mark, so the site and the checks agree. The Worker
(deploy/cloudflare/worker.js, visibleWords) applies the same rules.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

CASE_MARK = "Practice case: an example, not a real person or case."
_WORD = re.compile("synthetic", re.IGNORECASE)
_RULES: list[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]] = [
    (re.compile(r"SYNTHETIC:\s*"), CASE_MARK + " "),
    (re.compile(r"\bSYNTHETIC\b"), "practice-case"),
    (re.compile(r"synthetic_example"), "example"),
    (re.compile(r"synthetic_"), "example_"),
    (re.compile(r"_synthetic\b"), "_example"),
    (re.compile(r"\bSynthetic (examples?)\b"), lambda m: m.group(1).capitalize()),
    (re.compile(r"\bsynthetic (examples?)\b"), r"\1"),
    (re.compile(r"Synthetic"), "Example"),
    (_WORD, "example"),
]


def has_example_mark(text: str) -> bool:
    """A practice case carries its mark: the current one, or the former internal mark older fixtures still hold."""
    return CASE_MARK in text or "SYNTHETIC" in text


def visible_text(text: str) -> str:
    """One string in visitors' words."""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text


def visible_key(key: str) -> str:
    return "is_example" if key.lower() == "synthetic" else visible_text(key)


def visible(value: Any) -> Any:
    """A JSON value in visitors' words: keys and strings, all the way down."""
    if isinstance(value, str):
        return visible_text(value)
    if isinstance(value, list):
        return [visible(item) for item in value]
    if isinstance(value, dict):
        return {visible_key(key): visible(item) for key, item in value.items()}
    return value


def visible_tree(root: Path) -> int:
    """Rewrite every JSON file under ``root`` in visitors' words; returns how many files changed."""
    changed = 0
    for path in sorted(root.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        shown = visible(data)
        if shown != data:
            path.write_text(
                json.dumps(shown, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            changed += 1
    return changed
