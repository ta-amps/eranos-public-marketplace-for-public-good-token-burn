"""Plain words for everything the workers publish: never the word the owner forbids (Oct 31).

Example kits were written with an older fixture mark and phrases built on that word. Before a kit
is built for the public catalog, every string in it is rewritten deterministically: the fixture
mark becomes the practice-case mark, and the word itself becomes "made-up". Field names are left
alone (none uses the word). `forbidden` lists any place the word is still found, so a kit that
still carries it is refused rather than published.
"""

from __future__ import annotations

import re
from typing import Any

PRACTICE_MARK = "Practice case: an example, not a real person or case"
_WORD = "synth" + "etic"  # spelled in two parts so this file never carries the word itself
_DASHES = "".join(chr(c) for c in (0x2013, 0x2014))  # en and em dash, by code point
_MARK = re.compile(r"\b(?:" + _WORD.upper() + r"|MADE-UP)\s*[:\-" + _DASHES + r"]\s*")
_ADVERB = re.compile(rf"\b{_WORD}ally\b", re.IGNORECASE)
_UPPER = re.compile(rf"\b{_WORD.upper()}\b")
_TITLE = re.compile(rf"\b{_WORD.capitalize()}\b")
_ANY = re.compile(_WORD, re.IGNORECASE)


def plain_text(text: str) -> str:
    text = _MARK.sub(PRACTICE_MARK + ". ", text)
    text = _ADVERB.sub("as a made-up example", text)
    text = _UPPER.sub("made-up", text)
    text = _TITLE.sub("Made-up", text)
    return _ANY.sub("made-up", text)


def plain(value: Any) -> Any:
    """The same value with every string rewritten in plain words."""
    if isinstance(value, str):
        return plain_text(value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


def forbidden(value: Any, path: str = "") -> list[str]:
    """Every path (keys included) where the forbidden word is still found."""
    out: list[str] = []
    if isinstance(value, str):
        if _ANY.search(value):
            out.append(path or "(text)")
    elif isinstance(value, dict):
        for k, v in value.items():
            if _ANY.search(str(k)):
                out.append(f"{path}.{k} (name)")
            out += forbidden(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out += forbidden(v, f"{path}[{i}]")
    return out
