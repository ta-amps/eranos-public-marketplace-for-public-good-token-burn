"""Scan agent definitions, rule files, MCP configs, and evolving memory for supply-chain risks."""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
import re
from typing import Any

DEFAULT_RESERVED_AGENT_NAMES: frozenset[str] = frozenset(
    {
        "bash",
        "default",
        "explore",
        "general-purpose",
        "main",
        "plan",
        "research",
        "self",
        "statusline-setup",
    }
)

_AGENT_CONFIG_PREFIXES: tuple[str, ...] = (
    ".claude/",
    ".codex/",
    ".cursor/",
    ".github/agents/",
    ".github/copilot-instructions.md",
    ".gemini/",
    ".agents/",
    ".kiro/",
    ".opencode/",
    ".windsurf/",
    ".devin/",
)
_AGENT_CONFIG_FILENAMES: frozenset[str] = frozenset(
    {
        ".cursorrules",
        ".goosehints",
        ".mcp.json",
        ".roomodes",
        "agents.md",
        "claude.md",
        "custom_modes.yaml",
        "identity.md",
        "mcp.json",
        "opencode.json",
        "soul.md",
        "user.md",
    }
)

_BIDI_CODEPOINTS: frozenset[int] = frozenset(
    set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A)) | {0x061C}
)
_ZERO_WIDTH_CODEPOINTS: frozenset[int] = frozenset(
    set(range(0x200B, 0x2010)) | set(range(0x2060, 0x2065)) | {0xFEFF}
)

_BYPASS_RE = re.compile(
    r"\b(?:bypassPermissions|dangerously-skip-permissions|autoApprove|yolo_mode|trust_all_projects)\b",
    re.IGNORECASE,
)
_HOOK_KEY_RE = re.compile(
    r"(?:^|\s|\"|')(?:hooks|PreToolUse|PostToolUse|SessionStart|UserPromptSubmit)\s*[:=]",
    re.MULTILINE,
)
_AUTHORITY_SPOOF_RE = re.compile(
    r"\b(?:acting as (?:the )?(?:ceo|ciso|root|system administrator)|"
    r"override all (?:prior|previous) (?:safety|security|system) (?:rules|policies|instructions)|"
    r"pre-authorized by security to bypass|ignore all tool restrictions)\b",
    re.IGNORECASE,
)
_FRONTMATTER_NAME_RE = re.compile(
    r"^\s*(?:name|slug)\s*[:=]\s*[\"']?([A-Za-z0-9_-]+)[\"']?\s*$",
    re.MULTILINE,
)
_SHELL_PIPE_RE = re.compile(r"\b(?:curl|wget)\b[^\n]*\|\s*(?:sh|bash|zsh)\b|\bbash\s+-c\b", re.IGNORECASE)
_OUTBOUND_URL_RE = re.compile(r"https?://(?!(?:localhost|127\.0\.0\.1)\b)[^\s\"')>]+", re.IGNORECASE)


def discover_agent_config_files(repo_root: Path) -> list[Path]:
    """Return sorted paths of agent, rule, MCP, and persona memory files under repo_root."""
    matched: list[Path] = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in {".git", "node_modules", ".venv", "__pycache__"} for part in path.parts):
            continue
        rel = path.relative_to(repo_root).as_posix()
        low_rel = rel.lower()
        low_name = path.name.lower()
        if low_name in _AGENT_CONFIG_FILENAMES or any(low_rel.startswith(p) for p in _AGENT_CONFIG_PREFIXES):
            matched.append(path)
    return matched


def scan_hidden_unicode(text: str, rel_path: str = "<memory>") -> list[dict[str, Any]]:
    """Detect Trojan Source bidi overrides, Unicode Tag ASCII smuggling, and zero-width characters."""
    findings: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        tag_chars: list[str] = []
        tag_col: int | None = None
        for col_no, ch in enumerate(line, start=1):
            cp = ord(ch)
            if 0xE0000 <= cp <= 0xE007F:
                if tag_col is None:
                    tag_col = col_no
                if 0xE0020 <= cp <= 0xE007E:
                    tag_chars.append(chr(cp - 0xE0000))
                continue
            if cp in _BIDI_CODEPOINTS:
                findings.append(
                    {
                        "vector": "unicode_bidi_override",
                        "severity": "critical",
                        "path": rel_path,
                        "line": line_no,
                        "column": col_no,
                        "codepoint": f"U+{cp:04X}",
                        "detail": "Bidirectional control character can visually disguise instructions.",
                    }
                )
            elif cp in _ZERO_WIDTH_CODEPOINTS and not (line_no == 1 and col_no == 1 and cp == 0xFEFF):
                findings.append(
                    {
                        "vector": "invisible_zero_width",
                        "severity": "high",
                        "path": rel_path,
                        "line": line_no,
                        "column": col_no,
                        "codepoint": f"U+{cp:04X}",
                        "detail": "Zero-width character detected in rule or agent configuration.",
                    }
                )
        if tag_col is not None:
            decoded = "".join(tag_chars)
            findings.append(
                {
                    "vector": "unicode_tag_smuggling",
                    "severity": "critical",
                    "path": rel_path,
                    "line": line_no,
                    "column": tag_col,
                    "codepoint": "U+E0000..U+E007F",
                    "decoded_hidden_ascii": decoded[:200],
                    "detail": "Rules File Backdoor style Unicode tag characters smuggling hidden text.",
                }
            )
    return findings


def _audit_mcp_json(
    text: str,
    rel_path: str,
    allowlisted_commands: set[str],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return findings
    if not isinstance(doc, dict):
        return findings

    servers = doc.get("mcpServers") or doc.get("servers") or {}
    if not isinstance(servers, dict):
        return findings

    for srv_name, cfg in sorted(servers.items()):
        if not isinstance(cfg, dict):
            continue
        cmd = str(cfg.get("command") or "").strip()
        args = [str(a) for a in (cfg.get("args") or [])]
        url = str(cfg.get("url") or "").strip()
        full_cmd = " ".join([cmd, *args]).strip()

        if _SHELL_PIPE_RE.search(full_cmd):
            findings.append(
                {
                    "vector": "mcp_shell_execution",
                    "severity": "critical",
                    "path": rel_path,
                    "server": srv_name,
                    "detail": f"MCP server {srv_name!r} invokes shell execution pattern: {full_cmd[:120]}",
                }
            )
        elif cmd and allowlisted_commands and cmd not in allowlisted_commands:
            findings.append(
                {
                    "vector": "unapproved_mcp_server",
                    "severity": "high",
                    "path": rel_path,
                    "server": srv_name,
                    "detail": f"MCP command {cmd!r} is not in allowlisted_mcp_commands (CVE-2025-54135 class).",
                }
            )
        elif "npx" in cmd and ("-y" in args or "--yes" in args):
            findings.append(
                {
                    "vector": "unpinned_npx_auto_install",
                    "severity": "high",
                    "path": rel_path,
                    "server": srv_name,
                    "detail": f"MCP server {srv_name!r} uses npx -y auto-install on clone without digest pin.",
                }
            )
        if url and _OUTBOUND_URL_RE.match(url):
            findings.append(
                {
                    "vector": "remote_mcp_endpoint",
                    "severity": "medium",
                    "path": rel_path,
                    "server": srv_name,
                    "detail": f"MCP server {srv_name!r} connects to external endpoint {url[:120]}.",
                }
            )
    return findings


def _audit_single_file(
    text: str,
    rel_path: str,
    allowlisted_mcp_commands: set[str],
    reserved_names: set[str],
) -> list[dict[str, Any]]:
    findings = scan_hidden_unicode(text, rel_path=rel_path)

    for m in _BYPASS_RE.finditer(text):
        findings.append(
            {
                "vector": "permission_bypass_flag",
                "severity": "critical",
                "path": rel_path,
                "detail": f"Config requests permission bypass via {m.group(0)!r}.",
            }
        )

    if _HOOK_KEY_RE.search(text) and not rel_path.endswith(".json"):
        findings.append(
            {
                "vector": "executable_clone_hook",
                "severity": "high",
                "path": rel_path,
                "detail": "Agent or rule frontmatter binds lifecycle hooks that execute on repository use.",
            }
        )
    elif rel_path.endswith(".json") and '"hooks"' in text:
        findings.append(
            {
                "vector": "executable_clone_hook",
                "severity": "high",
                "path": rel_path,
                "detail": "JSON agent or harness config declares lifecycle hooks.",
            }
        )

    for nm in _FRONTMATTER_NAME_RE.finditer(text):
        candidate_name = nm.group(1).strip().lower()
        if candidate_name in reserved_names:
            findings.append(
                {
                    "vector": "builtin_name_shadowing",
                    "severity": "high",
                    "path": rel_path,
                    "detail": f"Agent definition shadows reserved built-in subagent name {candidate_name!r}.",
                }
            )

    for sm in _AUTHORITY_SPOOF_RE.finditer(text):
        findings.append(
            {
                "vector": "inter_agent_authority_spoofing",
                "severity": "high",
                "path": rel_path,
                "detail": f"Text claims elevated organizational or override authority: {sm.group(0)!r}.",
            }
        )

    if rel_path.endswith(".json"):
        findings.extend(_audit_mcp_json(text, rel_path, allowlisted_mcp_commands))

    return findings


def scan_repository_configs(
    repo_root: Path,
    allowlisted_mcp_commands: set[str] | None = None,
    reserved_agent_names: set[str] | None = None,
) -> dict[str, Any]:
    """Scan all discovered agent, rule, MCP, and memory files under repo_root."""
    mcp_allow = set(allowlisted_mcp_commands) if allowlisted_mcp_commands is not None else set()
    reserved = (
        {n.lower() for n in reserved_agent_names}
        if reserved_agent_names is not None
        else set(DEFAULT_RESERVED_AGENT_NAMES)
    )

    files = discover_agent_config_files(repo_root)
    inventory: list[dict[str, Any]] = []
    all_findings: list[dict[str, Any]] = []

    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        raw_bytes = path.read_bytes()
        text = raw_bytes.decode("utf-8", errors="replace")
        inventory.append(
            {
                "path": rel,
                "bytes": len(raw_bytes),
                "sha256": hashlib.sha256(raw_bytes).hexdigest(),
            }
        )
        all_findings.extend(_audit_single_file(text, rel, mcp_allow, reserved))

    severity_counts = {"critical": 0, "high": 0, "medium": 0}
    for f in all_findings:
        sev = str(f.get("severity", "medium"))
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    verdict = (
        "block"
        if severity_counts["critical"] > 0 or severity_counts["high"] > 0
        else "review"
        if severity_counts["medium"] > 0
        else "clean"
    )
    inv_sha = hashlib.sha256(
        json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return {
        "scanned_files_count": len(inventory),
        "inventory_sha256": inv_sha,
        "verdict": verdict,
        "severity_counts": severity_counts,
        "findings": all_findings,
        "inventory": inventory,
    }


def diff_self_editing_memory(
    before_text: str,
    after_text: str,
    file_label: str = "SOUL.md",
) -> dict[str, Any]:
    """Gate self-edited persona or memory updates (SOUL.md / MemFS) before persistence."""
    before_lines = before_text.splitlines()
    after_lines = after_text.splitlines()
    diff_lines = list(
        difflib.unified_diff(before_lines, after_lines, fromfile=f"a/{file_label}", tofile=f"b/{file_label}", lineterm="")
    )
    added_lines = [ln[1:] for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++")]
    added_blob = "\n".join(added_lines)

    risks = scan_hidden_unicode(added_blob, rel_path=file_label)
    for sm in _AUTHORITY_SPOOF_RE.finditer(added_blob):
        risks.append(
            {
                "vector": "memory_authority_injection",
                "severity": "critical",
                "path": file_label,
                "detail": f"Self-edited memory adds override directive: {sm.group(0)!r}.",
            }
        )
    for pm in _SHELL_PIPE_RE.finditer(added_blob):
        risks.append(
            {
                "vector": "memory_shell_payload",
                "severity": "critical",
                "path": file_label,
                "detail": f"Self-edited memory injects shell execution snippet: {pm.group(0)!r}.",
            }
        )
    for um in _OUTBOUND_URL_RE.finditer(added_blob):
        risks.append(
            {
                "vector": "memory_new_external_url",
                "severity": "high",
                "path": file_label,
                "detail": f"Self-edited memory introduces external endpoint {um.group(0)!r}.",
            }
        )

    return {
        "file_label": file_label,
        "changed": before_text != after_text,
        "added_line_count": len(added_lines),
        "before_sha256": hashlib.sha256(before_text.encode("utf-8")).hexdigest(),
        "after_sha256": hashlib.sha256(after_text.encode("utf-8")).hexdigest(),
        "approved_for_auto_persist": len(risks) == 0,
        "risks": risks,
        "unified_diff": diff_lines,
    }
