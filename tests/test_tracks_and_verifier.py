"""Tests for public-good tracks, neutral engine code scan, and deterministic kit verification."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from eranos.pipeline import load_example_bundles
from eranos.schemas import KitDraft
from eranos.tracks import get_track, load_tracks
from eranos.verifier import verify_kit

CODE_DIR = Path(__file__).resolve().parent.parent / "eranos"


def test_all_six_tracks_load_across_both_domains() -> None:
    tracks = load_tracks()
    assert len(tracks) == 6
    domains = {t.domain for t in tracks.values()}
    assert domains == {"anti_exploitation", "nonprofit_ops"}
    for pack in tracks.values():
        assert pack.sources
        assert pack.required_human_only


def test_neutral_code_names_no_track_or_kit_id() -> None:
    tracks = load_tracks()
    kits = {b["request"]["kit_id"] for b in load_example_bundles()}
    forbidden_literals = set(tracks) | kits
    hits: list[str] = []
    for path in sorted(CODE_DIR.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for kit_id in kits:
            if re.search(rf"(?<![\w-]){re.escape(kit_id)}(?![\w-])", source):
                hits.append(f"{path.name}: {kit_id}")
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in forbidden_literals
            ):
                hits.append(f"{path.name}:{node.lineno}: {node.value!r}")
    assert not hits, hits


def test_every_example_kit_passes_deterministic_verifier() -> None:
    for bundle in load_example_bundles():
        draft = KitDraft.model_validate(
            {**bundle["draft"], "drafted_by": "vol-a", "drafted_by_key": "k-a"}
        )
        track = get_track(draft.track_id)
        report = verify_kit(draft, track)
        assert report.passed, report.issues


def test_verifier_catches_missing_track_required_human_only_kind() -> None:
    bundle = load_example_bundles()[0]
    draft = KitDraft.model_validate(
        {
            **bundle["draft"],
            "steps": [s for s in bundle["draft"]["steps"] if s["kind"] != "interview"],
            "drafted_by": "vol-a",
            "drafted_by_key": "k-a",
        }
    )
    report = verify_kit(draft, get_track(draft.track_id))
    assert not report.passed
    assert any("interview" in issue for issue in report.issues)
