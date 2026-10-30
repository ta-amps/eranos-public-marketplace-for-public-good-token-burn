"""Example runs: one evidence noun per example kit, written by the repository's own pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from eranos.cli import main as cli_main
from eranos.pipeline import load_example_bundles
from eranos.pipeline.examples import bundle_sha256, load_example_runs


@pytest.fixture
def local_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ERANOS_LOCAL_DB", str(tmp_path / "runs.db"))
    monkeypatch.setenv("ERANOS_TRACE", str(tmp_path / "trace.jsonl"))
    for name in ("TESSERA_URL", "TESSERA_TOKEN", "TESSERA_KEY"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_recording_writes_one_evidence_noun_per_example_kit(local_store: Path) -> None:
    out = local_store / "runs"
    assert cli_main(["record-example-runs", str(out)]) == 0
    bundles = {b["request"]["kit_id"]: b for b in load_example_bundles()}
    runs = load_example_runs(out)
    assert [run["kit_id"] for run in runs] == sorted(bundles)
    for run in runs:
        assert run["synthetic"] is True and run["data"] == "synthetic"
        assert run["inputs_sha256"] == bundle_sha256(bundles[run["kit_id"]])
        assert [v["verb"] for v in run["verbs"]] == ["check", "build", "review"]
        assert all(v["ok"] is True and len(v["receipt_sha256"]) == 64 for v in run["verbs"])
        build, review = run["verbs"][1], run["verbs"][2]
        assert build["worker"] != review["worker"] and build["key_id"] != review["key_id"]
        assert build["verification"]["passed"] is True
        assert run["outcome"] == "published" and run["model_calls"] == 0
        assert run["summary_label"] == f"example runs on {run['where']}, synthetic data"
        steward = bundles[run["kit_id"]]["request"].get("needs_steward_signoff", False)
        assert review["parked_for_steward"] is bool(steward)
