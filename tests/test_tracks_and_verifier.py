"""Tests for public-good tracks, neutral engine code scan, deterministic verifier, and zero-storage practice gate."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from eranos.pipeline import load_example_bundles, practice_verify_kit
from eranos.schemas import KitDraft
from eranos.tracks import get_track, load_tracks
from eranos.verifier import verify_kit

CODE_DIR = Path(__file__).resolve().parent.parent / "eranos"


def test_every_track_loads_across_both_domains() -> None:
    tracks = load_tracks()
    files = sorted((CODE_DIR.parent / "tracks").glob("*/track.json"))
    assert len(tracks) == len(files) >= 6
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


MODEL_SHIPPING_CASES = [
    (
        "artifact",
        "services:\n  model:\n    image: ol" "lama/ol" "lama:latest\n    ports: ['11434:11434']",
    ),
    ("step", "Before the first shift, run `ol" "lama pull` to download the model this kit uses."),
    ("artifact", "A Modelfile: FROM base-model, PARAMETER temperature 0."),
    ("artifact", "Copy adapter_model.safetensors and adapter_config.json from the tuned run."),
    ("skill", "Load the weights with AutoModel.from_pretrained(path) before answering."),
    ("artifact", "Download weights.gguf with hf download before you start."),
]


@pytest.mark.parametrize(("where", "text"), MODEL_SHIPPING_CASES)
def test_a_kit_that_ships_a_model_or_model_service_is_refused(where: str, text: str) -> None:
    """Kits are model-free: the agent that uses a kit brings its own model (owner, Nov 1)."""
    bundle = load_example_bundles()[0]
    raw = {**bundle["draft"], "drafted_by": "vol-a", "drafted_by_key": "k-a"}
    if where == "artifact":
        raw["artifacts"] = [
            *raw.get("artifacts", []),
            {
                "name": "local-model-setup",
                "title": "Local model setup",
                "artifact_format": "markdown_sop",
                "summary": "How to start the local model this kit would use.",
                "spec": text,
            },
        ]
    elif where == "step":
        step = dict(raw["steps"][0])
        raw["steps"] = [{**step, "guidance": text}, *raw["steps"][1:]]
    else:
        skill = dict(raw.get("skill") or {})
        raw["skill"] = {**skill, "instructions": f"{skill.get('instructions', '')} {text}"}
    draft = KitDraft.model_validate(raw)
    assert draft.model_hook.model_dump() == {"default": "none", "uses": "your own agent's model"}
    report = verify_kit(draft, get_track(draft.track_id))
    assert not report.passed and "model_free_by_default" in report.checks_run
    assert any("kits ship no model" in issue for issue in report.issues), report.issues


def test_a_kit_names_no_model_of_its_own_and_cannot_point_at_one() -> None:
    bundle = load_example_bundles()[0]
    raw = {**bundle["draft"], "drafted_by": "vol-a", "drafted_by_key": "k-a"}
    assert KitDraft.model_validate(raw).model_hook.default == "none"
    with pytest.raises(ValidationError):
        KitDraft.model_validate({**raw, "model_hook": {"default": "muse-wonder-1.0"}})
    # A worker's own label is not kit content: it is never refused for its name.
    labelled = KitDraft.model_validate({**raw, "drafted_by": "ol" "lama-volunteer"})
    assert verify_kit(labelled, get_track(labelled.track_id)).passed


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


def test_practice_verify_kit_zero_storage_pass_and_failure_modes(tmp_path: Path) -> None:
    bundle = load_example_bundles()[0]
    ok_res = practice_verify_kit(bundle["draft"])
    assert ok_res["passed"] is True
    assert ok_res["persisted"] is False
    assert ok_res["spdx_license"] == "Apache-2.0"
    assert ok_res["issues"] == []
    assert len(ok_res["receipt_sha256"]) == 64
    assert practice_verify_kit(bundle["draft"])["receipt_sha256"] == ok_res["receipt_sha256"]
    assert list(tmp_path.iterdir()) == []

    # 1. Closed / non-allowlisted SPDX license rejected
    bad_spdx = practice_verify_kit({**bundle["draft"], "spdx_license": "Proprietary-1.0"})
    assert bad_spdx["passed"] is False
    assert bad_spdx["persisted"] is False
    assert any("spdx_license" in issue for issue in bad_spdx["issues"])

    # 2. Accusatory copy rejected
    bad_copy = practice_verify_kit(
        {**bundle["draft"], "summary": "Flag the recruiter as a scammer immediately."}
    )
    assert bad_copy["passed"] is False
    assert bad_copy["persisted"] is False
    assert any("non-accusatory" in issue for issue in bad_copy["issues"])

    # 3. Prohibited surveillance / harvesting topic rejected
    bad_topic = practice_verify_kit(
        {**bundle["draft"], "summary": "Build a grooming kit sample archive."}
    )
    assert bad_topic["passed"] is False
    assert bad_topic["persisted"] is False
    assert any("prohibited topic" in issue for issue in bad_topic["issues"])

    # 4. Autonomy boundary violation (interview marked drafts) rejected
    bad_steps = [
        {**s, "boundary": "drafts"} if s["kind"] == "interview" else s
        for s in bundle["draft"]["steps"]
    ]
    bad_boundary = practice_verify_kit({**bundle["draft"], "steps": bad_steps})
    assert bad_boundary["passed"] is False
    assert bad_boundary["persisted"] is False
    assert any("human_only" in issue for issue in bad_boundary["issues"])

    # 5. Fixture escalation coverage missing rejected
    no_escalation_fx = [
        {**fx, "expected_human_escalation": False} for fx in bundle["draft"]["fixtures"]
    ]
    bad_fx = practice_verify_kit({**bundle["draft"], "fixtures": no_escalation_fx})
    assert bad_fx["passed"] is False
    assert bad_fx["persisted"] is False
    assert any("human-escalation" in issue for issue in bad_fx["issues"])


def test_custom_domains_step_kinds_and_deliverable_artifacts_need_no_code_changes() -> None:
    """New public-good domains (e.g. humanitarian_aid), custom workflow step kinds, and standalone
    SOP/schema/CSV deliverable packs validate cleanly without editing engine enums."""
    from eranos.schemas import TrackPack

    custom_track = TrackPack.model_validate(
        {
            "id": "disaster-water-point-triage",
            "title": "Disaster Water & Sanitation Field Checklist Track",
            "domain": "humanitarian_aid",
            "domain_label": "Humanitarian Response",
            "summary": "Builds zero-PII field checklists and supply calculators for local water-point volunteers.",
            "organizations": [
                {
                    "org_type": "Community water and disaster response committee",
                    "serves": "Households checking potable water distribution hours",
                    "mandate": "Publish verified distribution schedules while keeping safety triage human-only",
                }
            ],
            "allowed_artifacts": ["sop_playbook", "csv_template"],
            "required_human_only": ["individual_decision"],
            "never": ["Collect household personal identifiers"],
            "sources": [
                {
                    "title": "Sphere Handbook WASH Standards",
                    "url": "https://spherestandards.org/handbook/",
                    "checked_date": "2026-10-26",
                }
            ],
        }
    )
    custom_draft = KitDraft.model_validate(
        {
            "kit_id": "KIT-WASH-01",
            "track_id": "disaster-water-point-triage",
            "domain": "humanitarian_aid",
            "deliverable_kind": "sop_playbook",
            "title": "Field Water-Point Supply & Escalation SOP Pack",
            "summary": "Calculates daily chlorine and tank buffer needs while routing contamination alerts to a human engineer.",
            "target_org": "Community WASH committee",
            "steps": [
                {
                    "id": "calc_tank_buffer",
                    "title": "Compute daily litre buffer from household count",
                    "kind": "tank_arithmetic_prep",
                    "boundary": "drafts",
                    "actor": "Field calculator sheet",
                    "guidance": "Multiply Sphere 15L/person/day baseline with 20% reserve.",
                },
                {
                    "id": "water_quality_decision",
                    "title": "Shut down or clear a water point after turbidity alert",
                    "kind": "individual_decision",
                    "boundary": "human_only",
                    "actor": "Certified WASH field engineer",
                    "guidance": "Only a human WASH technician clears or closes a distribution tap.",
                },
            ],
            "artifacts": [
                {
                    "name": "wash_buffer_table",
                    "title": "Potable Buffer CSV Formula Pack",
                    "artifact_format": "csv_template",
                    "boundary": "drafts",
                    "summary": "Offline spreadsheet template computing Sphere minimum water buffers.",
                    "spec": {"columns": ["site_code", "served_estimate", "litres_required"]},
                }
            ],
            "checklist": [
                "Verify free residual chlorine test strip date before opening distribution.",
                "Record site code only; never log household names.",
                "Escalate any turbidity or odour report immediately to the human WASH engineer.",
            ],
            "sources": [
                {
                    "title": "Sphere Handbook WASH Standards",
                    "url": "https://spherestandards.org/handbook/",
                    "checked_date": "2026-10-26",
                }
            ],
            "fixtures": [
                {
                    "id": "FX-WASH-ROUTINE",
                    "scenario": "Routine daily buffer calculation for 200 households",
                    "sample_input": "SYNTHETIC: Site W-04 plans distribution for 200 households over 6 hours.",
                    "expected_indicators": ["buffer_litres_computed"],
                    "expected_human_escalation": False,
                },
                {
                    "id": "FX-WASH-ALERT",
                    "scenario": "Cloudy tank sample reported at morning setup",
                    "sample_input": "SYNTHETIC: Volunteer reports cloudy water sample at Site W-04 intake tap.",
                    "expected_indicators": ["escalate_to_wash_engineer"],
                    "expected_human_escalation": True,
                },
            ],
            "drafted_by": "vol-agent-01",
            "drafted_by_key": "key_vol_01",
        }
    )
    report = verify_kit(custom_draft, custom_track)
    assert report.passed, report.issues
