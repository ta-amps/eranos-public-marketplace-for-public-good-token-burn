"""Referenced example kits: composed from the seed-pack library, pinned by digest, and refused on drift."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from eranos.jsonfile import load_json
from eranos.pipeline import SeedPackError, compose_bundle, example_paths, library_root
from eranos.pipeline.seed_packs import LIBRARY_DIRNAME, LIBRARY_ENV, value_sha256
from eranos.schemas import KitDraft, KitRequest
from eranos.tracks import get_track
from eranos.verifier import verify_kit

ROOT = Path(__file__).resolve().parents[1]


def referenced() -> list[tuple[Path, dict[str, Any]]]:
    found = [(p, load_json(p)) for p in example_paths()]
    return [(p, raw) for p, raw in found if "seed_pack" in raw]


def copy_pack(tmp_path: Path, raw: dict[str, Any]) -> Path:
    pack_id = raw["seed_pack"]["pack_id"]
    target = tmp_path / "library" / "packs" / pack_id
    target.mkdir(parents=True)
    for name in ("nouns.json", "verbs.json"):
        shutil.copy(library_root() / "packs" / pack_id / name, target / name)
    return target


def test_there_are_referenced_examples() -> None:
    assert referenced(), "at least one example kit points at a seed pack"


@pytest.mark.parametrize("path", [p for p, _ in referenced()], ids=lambda p: p.name)
def test_referenced_example_composes_from_its_pack_and_verifies(path: Path) -> None:
    raw = load_json(path)
    bundle = compose_bundle(raw)
    kit_pin = raw["seed_pack"]["kit"]
    records = load_json(library_root() / "packs" / raw["seed_pack"]["pack_id"] / "nouns.json")[
        "records"
    ]
    kit_value = next(r["value"] for r in records if r["key"] == kit_pin["key"])
    assert value_sha256(kit_value) == kit_pin["value_sha256"]

    request = KitRequest.model_validate(bundle["request"])
    draft = KitDraft.model_validate(
        {**bundle["draft"], "drafted_by": "vol-a", "drafted_by_key": "k-a"}
    )
    assert request.title == draft.title == kit_value["title"]
    assert [s.id for s in draft.steps] == [s["id"] for s in kit_value["step_map"]]
    report = verify_kit(draft, get_track(draft.track_id))
    assert report.passed, report.issues

    asked = bundle["example_request"]
    assert asked["mark"] == "MADE-UP"
    assert asked["says"].startswith("We need ")
    assert "request a kit" not in asked["says"].lower()
    assert asked["noun"] == raw["seed_pack"]["request"]
    # The example itself repeats no kit content: only catalog fields and pins.
    assert set(raw["request"]) <= {
        "kit_id",
        "track_id",
        "deliverable_kind",
        "needs_steward_signoff",
        "spdx_license",
        "tags",
        "target_cohorts",
        "producer_surface",
        "visibility_scope",
        "allowed_surfaces",
    }
    assert "draft" not in raw


def test_a_changed_library_noun_is_refused(tmp_path: Path) -> None:
    _, raw = referenced()[0]
    folder = copy_pack(tmp_path, raw)
    nouns = load_json(folder / "nouns.json")
    for record in nouns["records"]:
        if record["value"]["role"] == "kit":
            record["value"]["summary"] += " Changed without review."
    (folder / "nouns.json").write_text(json.dumps(nouns), encoding="utf-8")
    with pytest.raises(SeedPackError, match="changed in the library"):
        compose_bundle(raw, root=tmp_path / "library")


def test_a_missing_library_fails_loudly(tmp_path: Path) -> None:
    _, raw = referenced()[0]
    with pytest.raises(SeedPackError, match=LIBRARY_ENV):
        compose_bundle(raw, root=tmp_path / "nowhere")


def test_the_example_cannot_carry_kit_content() -> None:
    _, raw = referenced()[0]
    tampered = copy.deepcopy(raw)
    tampered["request"]["title"] = "A second definition of the kit"
    with pytest.raises(SeedPackError, match="come from the pack"):
        compose_bundle(tampered)
    tampered = copy.deepcopy(raw)
    tampered["seed_pack"]["kit"]["version"] = 2
    with pytest.raises(SeedPackError, match="version 1"):
        compose_bundle(tampered)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"claimant": "agent"}, "claimant"),
        ({"title": "A different title"}, "title differs"),
    ],
)
def test_each_step_must_match_its_verb_template(
    tmp_path: Path, change: dict[str, str], message: str
) -> None:
    _, raw = referenced()[0]
    folder = copy_pack(tmp_path, raw)
    verbs = load_json(folder / "verbs.json")
    person_verbs = [t for t in verbs["tasks"] if t["brief"]["claimant"] == "human"]
    assert person_verbs, "every kit keeps at least one step for a person"
    person_verbs[0]["brief"].update(change)
    (folder / "verbs.json").write_text(json.dumps(verbs), encoding="utf-8")
    with pytest.raises(SeedPackError, match=message):
        compose_bundle(raw, root=tmp_path / "library")


def test_library_root_comes_from_the_environment_or_a_sibling_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(LIBRARY_ENV, str(tmp_path))
    assert library_root() == tmp_path
    monkeypatch.delenv(LIBRARY_ENV)
    assert library_root() == ROOT.parent / LIBRARY_DIRNAME
