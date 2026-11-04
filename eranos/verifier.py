"""Deterministic verifier for volunteer-submitted kits: checks track fit, human-only lines, synthetic
fixtures, non-accusatory language, open SPDX licensing, primary source citations, and deliverable
schemas in memory without calling any model or writing storage."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from eranos.copy import PROHIBITED_COLLECTION_TOPICS, find_accusatory_words
from eranos.privacy import fixture_findings, text_personal_findings
from eranos.schemas import (
    HUMAN_ONLY_KINDS,
    OPEN_SPDX_ALLOWLIST,
    KitDraft,
    TrackPack,
    VerificationReport,
)
from eranos.tracks import get_track
from eranos.visible import has_example_mark

PRACTICE_CHECKS: list[str] = [
    "track_alignment",
    "human_only_boundaries",
    "practice_case_fixtures",
    "non_accusatory_copy",
    "prohibited_topics",
    "spdx_license_allowlist",
    "cited_sources",
    "deliverable_alignment",
    "model_free_by_default",
]
# Kits ship no model: no local model service or compose entry for one, no model download, model
# file, Modelfile or tuned adapter. The agent that uses a kit brings its own model. An open model
# family whose licence asks for attribution wherever its files or derivatives ship is never shipped,
# so no kit names it either (owner direction, Nov 1).
MODEL_SHIPPING = re.compile(
    r"\bo[l]lama\b|(?<![a-z])l[l]ama|\bmodelfile\b|\.gguf\b|\.safetensors\b|\bggml\b"
    r"|\badapter_(?:model|config)\b|\b(?:q?lora|peft) adapters?\b"
    r"|\b(?:vllm|localai|text-generation-inference|koboldcpp|lm studio)\b"
    r"|\b(?:huggingface-cli|hf) download\b|\bfrom_pretrained\(",
    re.IGNORECASE,
)
# A worker's own label is not kit content.
_LABEL_FIELDS = ("drafted_by", "drafted_by_key")


def _iter_strings(node: Any) -> list[str]:
    out: list[str] = []
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for val in node.values():
            out.extend(_iter_strings(val))
    elif isinstance(node, list | tuple):
        for item in node:
            out.extend(_iter_strings(item))
    return out


def verify_kit(draft: KitDraft, track: TrackPack) -> VerificationReport:
    issues: list[str] = []
    checks = list(PRACTICE_CHECKS)

    if draft.track_id != track.id:
        issues.append(f"draft track_id {draft.track_id!r} does not match track {track.id!r}")
    if draft.domain != track.domain:
        issues.append(f"draft domain {draft.domain!r} does not match track domain {track.domain!r}")

    if draft.spdx_license not in OPEN_SPDX_ALLOWLIST:
        allowed = ", ".join(sorted(OPEN_SPDX_ALLOWLIST))
        issues.append(f"spdx_license {draft.spdx_license!r} must be in open allowlist ({allowed})")

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
        if not has_example_mark(fx.sample_input):
            issues.append(f"fixture {fx.id!r} lacks the practice-case mark")
        issues.extend(
            f"fixture {fx.id!r} holds personal details: {found}"
            for found in fixture_findings(fx.sample_input)
        )
        bad = find_accusatory_words(fx.sample_input)
        if bad:
            issues.append(f"fixture {fx.id!r} contains accusatory words: {', '.join(bad)}")

    for text in _iter_strings(draft.model_dump(mode="json")):
        matched_topics = sorted(
            {m.group(0).lower() for m in PROHIBITED_COLLECTION_TOPICS.finditer(text)}
        )
        if matched_topics:
            issues.append(f"prohibited collection topic detected: {', '.join(matched_topics)}")
            break

    content = {k: v for k, v in draft.model_dump(mode="json").items() if k not in _LABEL_FIELDS}
    for text in _iter_strings(content):
        shipped = MODEL_SHIPPING.search(text)
        if shipped:
            issues.append(
                "kits ship no model, model service, model download, model file or tuned adapter;"
                f" the agent that uses the kit brings its own model (found {shipped.group(0)!r})"
            )
            break

    issues.extend(
        f"personal details in the kit: {found}" for found in text_personal_findings(content)
    )

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


def _unwrap_draft_payload(draft_payload: dict[str, Any] | KitDraft) -> dict[str, Any]:
    if isinstance(draft_payload, KitDraft):
        return draft_payload.model_dump(mode="json")
    if not isinstance(draft_payload, dict):
        raise TypeError("draft_payload must be a mapping or KitDraft")
    if isinstance(draft_payload.get("draft"), dict):
        raw = dict(draft_payload["draft"])
        req = draft_payload.get("request")
        if isinstance(req, dict):
            for gov_key in (
                "spdx_license",
                "tags",
                "target_cohorts",
                "producer_surface",
                "visibility_scope",
                "allowed_surfaces",
            ):
                if gov_key not in raw and gov_key in req:
                    raw[gov_key] = req[gov_key]
        return raw
    if isinstance(draft_payload.get("kit"), dict):
        raw = dict(draft_payload["kit"])
        for gov_key in (
            "spdx_license",
            "tags",
            "target_cohorts",
            "producer_surface",
            "visibility_scope",
            "allowed_surfaces",
        ):
            if gov_key not in raw and gov_key in draft_payload:
                raw[gov_key] = draft_payload[gov_key]
        return raw
    return dict(draft_payload)


def practice_verify_kit(
    draft_payload: dict[str, Any] | KitDraft,
    track_id: str | None = None,
    *,
    tracks_root: Path | None = None,
) -> dict[str, Any]:
    """Execute full deterministic boundary, copy, prohibited-topic, SPDX allowlist, and fixture
    checks in memory with zero database or blob writes (`persisted: False`).

    The receipt hashes this validation outcome, not the full draft. It is not a
    content identity, independent review, or catalog publication receipt.
    """
    raw = _unwrap_draft_payload(draft_payload)
    raw.setdefault("drafted_by", "practice-dry-run")
    raw.setdefault("drafted_by_key", "practice-dry-run-key")
    if not raw.get("drafted_by"):
        raw["drafted_by"] = "practice-dry-run"
    if not raw.get("drafted_by_key"):
        raw["drafted_by_key"] = "practice-dry-run-key"

    kit_id = str(raw.get("kit_id") or "UNSPECIFIED")
    spdx_license = str(raw.get("spdx_license") or "Apache-2.0").strip()
    payload_track_id = str(raw.get("track_id") or "").strip()
    effective_track_id = (track_id or payload_track_id).strip()
    if track_id and not payload_track_id:
        raw["track_id"] = effective_track_id

    issues: list[str] = []

    def add_issue(msg: str) -> None:
        if msg not in issues:
            issues.append(msg)

    # 1. Open SPDX license allowlist check
    if spdx_license not in OPEN_SPDX_ALLOWLIST:
        allowed = ", ".join(sorted(OPEN_SPDX_ALLOWLIST))
        add_issue(f"spdx_license {spdx_license!r} must be in open SPDX allowlist ({allowed})")

    # 2. Non-accusatory copy & prohibited collection topics across all strings
    all_texts = _iter_strings(raw)
    bad_words: set[str] = set()
    bad_topics: set[str] = set()
    for text in all_texts:
        bad_words.update(find_accusatory_words(text))
        for m in PROHIBITED_COLLECTION_TOPICS.finditer(text):
            bad_topics.add(m.group(0).lower())
    if bad_words:
        add_issue(f"non-accusatory copy rule violated: {', '.join(sorted(bad_words))}")
    if bad_topics:
        add_issue(f"prohibited collection topic refused: {', '.join(sorted(bad_topics))}")

    # 3. Step autonomy boundary checks (drafts / assists / human_only)
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) < 2:
        add_issue("steps must be a list of at least 2 workflow steps")
    else:
        has_any_human_only = False
        for idx, step in enumerate(raw_steps):
            if not isinstance(step, dict):
                add_issue(f"step[{idx}] must be an object")
                continue
            sid = str(step.get("id") or f"step_{idx}")
            skind = str(step.get("kind") or "")
            sbound = str(step.get("boundary") or "")
            if sbound not in {"drafts", "assists", "human_only"}:
                add_issue(
                    f"step {sid!r} boundary must be 'drafts', 'assists', or 'human_only' (got {sbound!r})"
                )
            if sbound == "human_only":
                has_any_human_only = True
            if skind in HUMAN_ONLY_KINDS and sbound != "human_only":
                add_issue(f"step {sid!r} of kind {skind!r} must keep boundary='human_only'")
        if not has_any_human_only:
            add_issue("every kit must declare at least one human_only workflow step")

    # 4. Synthetic fixture checks
    raw_fixtures = raw.get("fixtures")
    if not isinstance(raw_fixtures, list) or len(raw_fixtures) < 2:
        add_issue("fixtures must provide at least 2 practice cases")
    else:
        has_esc = False
        has_rou = False
        for idx, fx in enumerate(raw_fixtures):
            if not isinstance(fx, dict):
                add_issue(f"fixture[{idx}] must be an object")
                continue
            fx_id = str(fx.get("id") or f"FX-{idx}")
            sample = str(fx.get("sample_input") or "")
            if not has_example_mark(sample):
                add_issue(f"fixture {fx_id!r} sample_input must carry the practice-case mark")
            for found in fixture_findings(sample):
                add_issue(f"fixture {fx_id!r} holds personal details: {found}")
            esc = fx.get("expected_human_escalation")
            if esc is True:
                has_esc = True
            elif esc is False:
                has_rou = True
        if not (has_esc and has_rou):
            add_issue(
                "fixtures must cover both a routine agent-assisted case and a human-escalation case"
            )

    # 5. Track lookup & track-required human_only checks
    track_pack: TrackPack | None = None
    if not effective_track_id:
        add_issue("track_id is required to verify track boundaries")
    else:
        if track_id and payload_track_id and payload_track_id != track_id:
            add_issue(
                f"draft track_id {payload_track_id!r} does not match requested track {track_id!r}"
            )
        try:
            track_pack = get_track(effective_track_id, tracks_root)
        except KeyError as exc:
            add_issue(str(exc))

    if track_pack is not None and isinstance(raw_steps, list):
        present_kinds = {str(s.get("kind") or "") for s in raw_steps if isinstance(s, dict)}
        missing_req = [k for k in track_pack.required_human_only if k not in present_kinds]
        if missing_req:
            add_issue(
                f"kit must explicitly declare track-required human_only step kinds: {', '.join(missing_req)}"
            )
        raw_domain = str(raw.get("domain") or "")
        if raw_domain and raw_domain != track_pack.domain:
            add_issue(
                f"draft domain {raw_domain!r} does not match track domain {track_pack.domain!r}"
            )

    # 6. Full strict schema + deterministic verify_kit check
    try:
        validated = KitDraft.model_validate(raw)
        if track_pack is not None:
            report = verify_kit(validated, track_pack)
            for item in report.issues:
                add_issue(item)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()))
            msg = str(err.get("msg", "validation error"))
            formatted = f"{loc}: {msg}" if loc else msg
            add_issue(formatted)

    passed = len(issues) == 0
    canonical_receipt_input = json.dumps(
        {
            "issues": issues,
            "kit_id": kit_id,
            "passed": passed,
            "persisted": False,
            "spdx_license": spdx_license,
            "track_id": effective_track_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    receipt_sha256 = hashlib.sha256(canonical_receipt_input).hexdigest()

    return {
        "passed": passed,
        "persisted": False,
        "kit_id": kit_id,
        "track_id": effective_track_id,
        "spdx_license": spdx_license,
        "issues": issues,
        "checks_run": list(PRACTICE_CHECKS),
        "receipt_sha256": receipt_sha256,
        "receipt_scope": "validation_outcome",
        "artifact_bound": False,
    }
