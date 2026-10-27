"""Export the Python kit schema used by the Worker practice validator."""

from __future__ import annotations

import json
from pathlib import Path

from eranos.schemas import KitDraft

if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "deploy/cloudflare/kit-draft.schema.json"
    target.write_text(json.dumps(KitDraft.model_json_schema(), indent=2) + "\n", encoding="utf-8")
