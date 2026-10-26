"""Structured JSON Lines run logger (ts, level, event, task_id, kit_id, queue, lease_id, cost_usd)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eranos import config


class TraceWriter:
    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path or config.trace_path())

    def write(self, event: str, *, level: str = "info", **fields: Any) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": level,
            "event": event,
            "task_id": fields.pop("task_id", None),
            "kit_id": fields.pop("kit_id", None),
            "queue": fields.pop("queue", None),
            "lease_id": fields.pop("lease_id", None),
            "cost_usd": fields.pop("cost_usd", None),
            **fields,
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
