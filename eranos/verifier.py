"""Deterministic verifier for volunteer-submitted kits: checks track fit, human-only lines, synthetic
fixtures, non-accusatory language, primary source citations, and deliverable schemas without calling any model."""

from __future__ import annotations

from eranos.copy import find_accusatory_words
from eranos.schemas import HUMAN_ONLY_KINDS, KitDraft, TrackPack, VerificationReport


def verify_kit(draft: KitDraft, track: TrackPack) -> VerificationReport:
    issues: list[str] = []
    checks = [
        "track_alignment",
        "human_only_boundaries",
        "synthetic_fixtures",
        "non_accusatory_copy",
        "cited_sources",
        "deliverable_alignment",
    ]

    if draft.track_id != track.id:
        issues.append(f"draft track_id {draft.track_id!r} does not match track {track.id!r}")
    if draft.domain != track.domain:
        issues.append(f"draft domain {draft.domain!r} does not match track domain {track.domain!r}")

    step_kinds = {step.kind for step in draft.steps}
    missing_human = [kind for kind in track.required_human_only if kind not in step_kinds]
    if missing_human:
        issues.append(
            f"kit must explicitly declare track-required human_only step kinds: {', '.join(missing_human)}"
        )

    for step in draft.steps:
        if step.kind in HUMAN_ONLY_KINDS and step.boundary != "human_only":
            issues.append(f"step {step.id!r} ({step.kind}) must be human_only")

    has_escalation_fixture = any(fx.expected_human_escalation for fx in draft.fixtures)
    has_routine_fixture = any(not fx.expected_human_escalation for fx in draft.fixtures)
    if not (has_escalation_fixture and has_routine_fixture):
        issues.append(
            "fixtures must cover both a routine agent-assisted case and a human-escalation case"
        )

    for fx in draft.fixtures:
        if "SYNTHETIC" not in fx.sample_input:
            issues.append(f"fixture {fx.id!r} lacks SYNTHETIC mark")
        bad = find_accusatory_words(fx.sample_input)
        if bad:
            issues.append(f"fixture {fx.id!r} contains accusatory words: {', '.join(bad)}")

    if not draft.sources:
        issues.append("at least one HTTPS primary source is required")

    tools = draft.all_tools()
    skills = draft.all_skills()
    if not (tools or skills or draft.artifacts):
        issues.append("at least one skill, MCP tool, or custom artifact is required")

    for tool in tools:
        props = tool.input_schema.get("properties")
        if not isinstance(props, dict) or not props:
            issues.append(
                f"tool {tool.name!r} input_schema.properties must define at least one field"
            )

    for art in draft.artifacts:
        if not art.spec:
            issues.append(f"artifact {art.name!r} spec must not be empty")

    human_steps = [step.id for step in draft.steps if step.boundary == "human_only"]
    return VerificationReport(
        kit_id=draft.kit_id,
        passed=not issues,
        checks_run=checks,
        issues=issues,
        fixture_count=len(draft.fixtures),
        human_only_steps=human_steps,
    )
