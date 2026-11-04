"""Strict JSON loader: rejects repeated object keys and NaN/Infinity so track and kit files stay unambiguous."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key: {key!r}")
        out[key] = value
    return out


def _no_nan(token: str) -> Any:
    raise ValueError(f"non-finite JSON constant refused: {token!r}")


def loads_strict(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_no_nan)


def load_json(path: Path) -> Any:
    return loads_strict(path.read_text(encoding="utf-8"))
