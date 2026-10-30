"""Example needs and recorded example runs: the nouns the marketplace shows about its example kits.

A need is the organization's own plain words, read from the kit's seed pack through its example
(`example_request` in a composed bundle). An example run is an evidence noun in `examples/runs/`,
written by `eranos record-example-runs`: the receipts of checking, building and reviewing one
example kit with this repository's own pipeline on a throwaway local store, with the input
digest, source commits and the kind of machine it ran on. The payload built here is what the web
shows; its wording comes from these nouns, not from page code.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tessera.receipts import canonical_json

from eranos.jsonfile import load_json

RUNS_DIR = Path(__file__).resolve().parents[2] / "examples" / "runs"
RUN_SCHEMA = "eranos.example-run.v1"


def bundle_sha256(bundle: dict[str, Any]) -> str:
    """The digest of a composed example bundle: what an example run took as its input."""
    return hashlib.sha256(canonical_json(bundle).encode("utf-8")).hexdigest()


def load_example_runs(runs_dir: Path | None = None) -> list[dict[str, Any]]:
    folder = runs_dir or RUNS_DIR
    runs = [load_json(p) for p in sorted(folder.glob("*.json"))]
    return [run for run in runs if isinstance(run, dict) and run.get("schema") == RUN_SCHEMA]


def example_needs(bundles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    needs = []
    for bundle in bundles:
        asked = bundle.get("example_request")
        if not isinstance(asked, dict):
            continue
        needs.append(
            {
                "kit_id": bundle["request"]["kit_id"],
                "kit_title": bundle["request"]["title"],
                "title": asked["title"],
                "says": asked["says"],
                "mark": asked["mark"],
                "noun": asked["noun"],
            }
        )
    return needs


def runs_summary(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not runs:
        return None
    labels = sorted({str(run["summary_label"]) for run in runs})
    commits = sorted({str(run["source"]["commit"]) for run in runs})
    return {
        "count": len(runs),
        "label": "; ".join(labels),
        "kits": [run["kit_id"] for run in runs],
        "outcomes": sorted({str(run["outcome"]) for run in runs}),
        "recorded_at": max(str(run["recorded_at"]) for run in runs),
        "source_commits": commits,
        "model_calls": sum(int(run["model_calls"]) for run in runs),
    }


def examples_payload(bundles: list[dict[str, Any]], runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"synthetic": True, "needs": example_needs(bundles), "runs": runs_summary(runs)}


__all__ = [
    "RUNS_DIR",
    "RUN_SCHEMA",
    "bundle_sha256",
    "example_needs",
    "examples_payload",
    "load_example_runs",
    "runs_summary",
]
