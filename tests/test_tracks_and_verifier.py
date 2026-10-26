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
