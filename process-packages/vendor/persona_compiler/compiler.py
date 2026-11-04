"""Compile portable agent role definitions across harnesses while stripping accuracy-degrading fluff."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SUPPORTED_HARNESS_TARGETS: tuple[str, ...] = (
    "claude_code",
    "codex",
    "cursor",
    "vscode_copilot",
    "gemini_cli",
    "opencode",
    "roo_code",
    "kiro",
)

_FLUFF_PATTERNS: dict[str, re.Pattern[str]] = {
    "expert_fluff": re.compile(
        r"\b(?:world[- ]class|10x|20x|rockstar|ninja|legendary|iq of \d+|nobel|phd[- ]level|"
        r"(?:\d+\+?\s+years? of experience)|renowned expert|unmatched genius)\b",
        re.IGNORECASE,
    ),
    "novice_framing": re.compile(
        r"\b(?:act as a (?:confused|clueless|novice|junior) beginner|pretend you know very little|"
        r"low[- ]knowledge persona)\b",
        re.IGNORECASE,
    ),
    "irrelevant_backstory": re.compile(
        r"\b(?:in your spare time|you live in|favorite (?:coffee|drink|band|hobby|movie)|"
        r"drink(?:ing)? espresso|love(?:s)? jazz|childhood dream|weekend hiker)\b",
        re.IGNORECASE,
    ),
    "demographic_attributes": re.compile(
        r"\b(?:\d{2}[- ]year[- ]old\s+(?:man|woman|male|female|person)|"
        r"married\s+(?:father|mother|husband|wife)|born and raised in)\b",
        re.IGNORECASE,
    ),
}

_IMPLICIT_CAPABILITY_CLAIMS: dict[str, re.Pattern[str]] = {
    "shell": re.compile(r"\b(?:run (?:any )?(?:bash|shell|terminal) commands?|execute arbitrary shell|sudo )\b", re.IGNORECASE),
    "write": re.compile(r"\b(?:modify any file|overwrite repository files|write directly to main|delete files)\b", re.IGNORECASE),
    "network": re.compile(r"\b(?:fetch arbitrary external urls|open outbound sockets|post to external webhooks)\b", re.IGNORECASE),
    "privilege_escalation": re.compile(
        r"\b(?:bypass(?:es)? all permissions|ignore tool restrictions|act with admin authority|pre-authorized to override)\b",
        re.IGNORECASE,
    ),
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def strip_degrading_fluff(instructions: str) -> dict[str, Any]:
    """Remove empirically accuracy-degrading persona fluff while keeping operational rules intact."""
    raw_segments = [s.strip() for s in _SENTENCE_SPLIT_RE.split(instructions) if s.strip()]
    kept: list[str] = []
    removed: list[dict[str, str]] = []
    flagged_categories: set[str] = set()

    for seg in raw_segments:
        matched_cats = [cat for cat, pat in _FLUFF_PATTERNS.items() if pat.search(seg)]
        if matched_cats:
            flagged_categories.update(matched_cats)
            removed.append({"sentence": seg, "reasons": sorted(matched_cats)})
        else:
            kept.append(seg)

    cleaned = "\n".join(kept)
    orig_words = len(re.findall(r"\S+", instructions))
    clean_words = len(re.findall(r"\S+", cleaned))
    return {
        "cleaned_instructions": cleaned,
        "removed_count": len(removed),
        "removed_segments": removed,
        "categories_flagged": sorted(flagged_categories),
        "words_removed": max(0, orig_words - clean_words),
    }


def score_delegation_description(description: str) -> dict[str, Any]:
    """Score a routing description on trigger clarity, concrete artifacts, boundary scope, and concision."""
    words = re.findall(r"[A-Za-z0-9_-]+", description)
    word_count = len(words)
    reasons: list[str] = []
    score = 0.0

    has_trigger = bool(
        re.search(r"\b(?:use when|invoke when|delegate|audits?|scans?|compiles?|verifies?|extracts?|aligns?)\b", description, re.IGNORECASE)
    )
    if has_trigger:
        score += 0.30
    else:
        reasons.append("Add an explicit routing trigger or concrete lead verb (for example 'Use when auditing...').")

    has_artifact = bool(
        re.search(
            r"\b(?:json|jsonl|yaml|toml|diff|ast|schema|test|log|trace|mask|transcript|config|repo|file|module)s?\b",
            description,
            re.IGNORECASE,
        )
    )
    if has_artifact:
        score += 0.25
    else:
        reasons.append("Name concrete input and output artifacts so the parent router knows what data to pass.")

    has_boundary = bool(
        re.search(r"\b(?:read[- ]only|without|never|do not|only|isolated|scoped|local)\b", description, re.IGNORECASE)
    )
    if has_boundary:
        score += 0.25
    else:
        reasons.append("State an explicit scope boundary or exclusion (for example 'read-only; never edits files').")

    fluff_hit = any(pat.search(description) for pat in _FLUFF_PATTERNS.values())
    if 10 <= word_count <= 75 and not fluff_hit:
        score += 0.20
    else:
        reasons.append("Keep routing description between 10 and 75 words with zero role-play superlatives.")

    return {
        "score": round(score, 2),
        "word_count": word_count,
        "has_trigger": has_trigger,
        "has_artifact": has_artifact,
        "has_boundary": has_boundary,
        "contains_fluff": fluff_hit,
        "suggestions": reasons,
    }


def verify_permission_separation(spec: dict[str, Any]) -> dict[str, Any]:
    """Verify natural-language routing and instructions never claim undeclared permissions."""
    allowed_caps = {str(c).lower() for c in (spec.get("allowed_capabilities") or [])}
    prose = "\n".join(
        str(spec.get(k) or "")
        for k in ("description", "instructions", "handoff_notes")
    )
    leaks: list[dict[str, str]] = []
    for cap, pat in _IMPLICIT_CAPABILITY_CLAIMS.items():
        m = pat.search(prose)
        if not m:
            continue
        if cap == "privilege_escalation" or cap not in allowed_caps:
            leaks.append(
                {
                    "capability": cap,
                    "matched_phrase": m.group(0),
                    "reason": f"Prose claims {cap!r} while allowed_capabilities={sorted(allowed_caps)}.",
                }
            )
    return {
        "separated": len(leaks) == 0,
        "allowed_capabilities": sorted(allowed_caps),
        "permission_leaks": leaks,
    }


def _yaml_list(items: list[str]) -> str:
    return "[" + ", ".join(json.dumps(x) for x in items) + "]"


def compile_portable_role(
    spec: dict[str, Any],
    targets: list[str] | tuple[str, ...] = SUPPORTED_HARNESS_TARGETS,
    strip_fluff: bool = True,
) -> dict[str, Any]:
    """Compile one portable role spec into deterministic harness-specific agent files."""
    slug = str(spec["slug"]).strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,62}", slug):
        raise ValueError(f"Invalid role slug: {slug!r}")

    description = str(spec["description"]).strip()
    raw_instructions = str(spec["instructions"]).strip()
    fluff_report = strip_degrading_fluff(raw_instructions) if strip_fluff else {
        "cleaned_instructions": raw_instructions,
        "removed_count": 0,
        "removed_segments": [],
        "categories_flagged": [],
        "words_removed": 0,
    }
    perm_report = verify_permission_separation(spec)
    if not perm_report["separated"]:
        raise ValueError(f"Permission separation check failed: {perm_report['permission_leaks']}")

    desc_score = score_delegation_description(description)
    allowed_tools = [str(t) for t in (spec.get("allowed_tools") or ["Read", "Grep", "Glob"])]
    disallowed_tools = [str(t) for t in (spec.get("disallowed_tools") or [])]
    allowed_caps = {str(c).lower() for c in (spec.get("allowed_capabilities") or ["read"])}
    readonly = "write" not in allowed_caps and "shell" not in allowed_caps
    max_turns = int(spec.get("max_turns") or 8)
    drift_budget = min(8, int(spec.get("drift_checkpoint_rounds") or 8))

    body_lines = [
        fluff_report["cleaned_instructions"],
        "",
        f"Constraint checkpoint: re-verify scope and output schema every {drift_budget} rounds.",
        "Routing note: agent hierarchy routes work only and never grants extra tool permissions.",
    ]
    if disallowed_tools:
        body_lines.append(f"Disallowed tools: {', '.join(disallowed_tools)}.")
    canonical_body = "\n".join(ln for ln in body_lines if ln is not None).strip()

    artifacts: dict[str, dict[str, Any]] = {}
    for target in targets:
        if target not in SUPPORTED_HARNESS_TARGETS:
            raise ValueError(f"Unsupported harness target: {target!r}")
        warnings: list[str] = []

        if target == "claude_code":
            path = f".claude/agents/{slug}.md"
            fm = [
                "---",
                f"name: {json.dumps(slug)}",
                f"description: {json.dumps(description)}",
                f"tools: {_yaml_list(allowed_tools)}",
            ]
            if disallowed_tools:
                fm.append(f"disallowedTools: {_yaml_list(disallowed_tools)}")
            fm.append(f"maxTurns: {max_turns}")
            fm.append("---")
            rendered = "\n".join(fm) + "\n\n" + canonical_body + "\n"

        elif target == "codex":
            path = f".codex/agents/{slug}.toml"
            if disallowed_tools:
                warnings.append("Codex TOML lacks native disallowedTools field; echoed into developer_instructions.")
            rendered = (
                f"name = {json.dumps(slug)}\n"
                f"description = {json.dumps(description)}\n"
                f"developer_instructions = {json.dumps(canonical_body)}\n"
            )

        elif target == "cursor":
            path = f".cursor/agents/{slug}.md"
            if disallowed_tools:
                warnings.append("Cursor agent frontmatter relies on readonly flag rather than explicit disallowedTools.")
            rendered = (
                "---\n"
                f"name: {json.dumps(slug)}\n"
                f"description: {json.dumps(description)}\n"
                f"readonly: {'true' if readonly else 'false'}\n"
                "---\n\n"
                f"{canonical_body}\n"
            )

        elif target == "vscode_copilot":
            path = f".github/agents/{slug}.agent.md"
            rendered = (
                "---\n"
                f"name: {json.dumps(slug)}\n"
                f"description: {json.dumps(description)}\n"
                f"tools: {_yaml_list(allowed_tools)}\n"
                "---\n\n"
                f"{canonical_body}\n"
            )

        elif target == "gemini_cli":
            path = f".gemini/agents/{slug}.md"
            rendered = (
                "---\n"
                f"name: {json.dumps(slug)}\n"
                f"description: {json.dumps(description)}\n"
                f"tools: {_yaml_list(allowed_tools)}\n"
                f"max_turns: {max_turns}\n"
                "---\n\n"
                f"{canonical_body}\n"
            )

        elif target == "opencode":
            path = f".opencode/agents/{slug}.json"
            payload = {
                "description": description,
                "mode": "subagent",
                "prompt": canonical_body,
                "permission": {
                    "edit": "deny" if readonly else "ask",
                    "bash": "allow" if "shell" in allowed_caps else "deny",
                },
            }
            rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"

        elif target == "roo_code":
            path = f".roomodes.{slug}.json"
            groups = ["read"] + (["edit"] if "write" in allowed_caps else []) + (["command"] if "shell" in allowed_caps else [])
            payload = {
                "slug": slug,
                "name": str(spec.get("title") or slug),
                "description": description,
                "whenToUse": description,
                "roleDefinition": canonical_body,
                "groups": groups,
            }
            rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"

        else:  # kiro
            path = f".kiro/agents/{slug}.json"
            payload = {
                "name": slug,
                "description": description,
                "prompt": canonical_body,
                "tools": allowed_tools,
            }
            rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"

        artifacts[target] = {
            "target": target,
            "path": path,
            "content_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
            "warnings": warnings,
            "content": rendered,
        }

    bundle_sha = hashlib.sha256(
        json.dumps({k: v["content_sha256"] for k, v in sorted(artifacts.items())}, sort_keys=True).encode("utf-8")
    ).hexdigest()

    return {
        "slug": slug,
        "bundle_sha256": bundle_sha,
        "delegation_description_audit": desc_score,
        "fluff_stripping": fluff_report,
        "permission_separation": perm_report,
        "drift_checkpoint_rounds": drift_budget,
        "targets_compiled": len(artifacts),
        "artifacts": artifacts,
    }
