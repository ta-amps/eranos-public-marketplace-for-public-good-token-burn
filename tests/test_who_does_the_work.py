"""Eranos never says or implies that outside volunteers did work its own workers did (honesty fix, Nov 2).

Static page text names the work neutrally ("an AI worker", "a different worker", "waiting for a worker"). Only the
request page, reading a claim that is marked as an outside volunteer (worker_kind "volunteer"), says "a volunteer's
AI". Text about people who want to help (the "I want to help" door, how to volunteer, volunteer keys) stays.
"""

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# The reviewer's rule (scratchpad volunteer_claims.py, review of 443595b), ported as it is ...
REVIEWER_RULE = (
    r"volunteer[\u2019']?s?[\u2019']? (?:AI|agents?)\b[^.]{0,60}\b(?:pick|picked|start|started|splits?|made|make|makes|does|do"
    r"|did|research|researched|check|checked|checks|review|reviewed|reviews|plan|planning|reading|built|build|wrote)"
    r"|(?:checked|researched|built|reviewed|made|planned) by (?:two different |a (?:different |second )?)?volunteer"
    r"|different volunteer[\u2019']?s?[\u2019']? (?:agent )?(?:checks|reviews|checked|reviewed)"
    r"|second volunteer"
    r"|a volunteer[\u2019']?s (?:AI|agent) (?:is|has)"
    r"|volunteers[\u2019'] agents (?:do|research|pick up|build|made|make|check)"
    r"|waiting for a volunteer"
)
# ... plus the forms this fix found that it does not catch.
MORE = (
    r"|\bvolunteers (?:never |also )?(?:build|builds|make|makes|do|does|check|checks|research|review|reviews)\b"
    r"|\bthe volunteer (?:stopped|couldn|claimed|made|checked|reviewed|is|was)\b"
    r"|different volunteer will\b"
    r"|\b(?:one|a different|a second|another) volunteer[\u2019']s key\b"
    r"|\bvolunteer will check\b"
    r"|\bvolunteer[\u2019']s (?:AI|agent)\b[^.]{0,30}\b(?:sorts|reads|claims)\b"
)
CLAIM = re.compile(REVIEWER_RULE + MORE, re.IGNORECASE)

# Shown only when the claim is marked as an outside volunteer; PlainStatus.tsx picks them through outsideVolunteer().
CLAIM_DERIVED = {
    ("request-status.json", "/plain/happened/work_claimed_volunteer"),
    ("request-status.json", "/plain/happened/work_claimed_changes_volunteer"),
    ("request-status.json", "/plain/happened/check_claimed_volunteer"),
    ("request-status.json", "/plain/happened/check_claimed_changes_volunteer"),
    ("request-status.json", "/plain/bands/checked/checking_volunteer"),
}


def _strings(value: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        return [row for key, item in value.items() for row in _strings(item, f"{path}/{key}")]
    if isinstance(value, list):
        return [row for i, item in enumerate(value) for row in _strings(item, f"{path}[{i}]")]
    return [(path, value)] if isinstance(value, str) else []


def _page_text_claims() -> list[str]:
    found = []
    for file in sorted((ROOT / "instructions").glob("*.json")):
        for path, text in _strings(json.loads(file.read_text(encoding="utf-8"))):
            if (file.name, path) in CLAIM_DERIVED:
                continue
            match = CLAIM.search(text)
            if match:
                found.append(f"{file.name}{path}: {match.group(0)!r} in {text[:120]!r}")
    return found


def _code_text(path: Path) -> str:
    """A source file's words without its comments, entities decoded and whitespace folded (JSX wraps lines)."""
    text = re.sub(r"/\*.*?\*/", " ", path.read_text(encoding="utf-8"), flags=re.S)
    text = re.sub(r"(^|\s)//[^\n]*", r"\1", text)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    for entity, char in (("&apos;", "'"), ("&rsquo;", "\u2019"), ("&quot;", '"'), ("&amp;", "&")):
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text)


def test_the_rule_catches_the_reviewers_examples_and_keeps_how_to_help() -> None:
    for claim in (
        "A volunteer\u2019s AI splits it into parts it can make.",
        "Checked by a second volunteer",
        "A volunteer\u2019s AI started making it.",
        "Researched and checked by two different volunteers\u2019 agents",
        "A different volunteer reviewed this",
        "Waiting for a volunteer",
        "Every deliverable is built by one agent and checked by a different volunteer\u2019s agent (maker != checker)",
        "Volunteers never build kits for these.",
        "The volunteer stopped before finishing.",
        "A volunteer will check your request before it becomes work.",
    ):
        assert CLAIM.search(claim), claim
    for helping in (
        "I want to help",
        "Pick up open Tasks as a volunteer",
        "## Help as a volunteer",
        "How to get a volunteer key",
        "Volunteers get the first pick. A task nobody takes by its time is picked up by a dedicated worker run by ta-amps.",
        "No volunteer was free, so a dedicated worker run by ta-amps started making it.",
        "Draft weekly reminders for open volunteer shifts",
        "{workers} volunteer and dedicated workers",
        "Nonprofits ask for help in plain words; volunteers lend the spare capacity of their own AI agents",
    ):
        assert not CLAIM.search(helping), helping


def test_no_page_text_says_a_volunteer_did_the_work() -> None:
    assert _page_text_claims() == []


def test_the_volunteer_wording_is_only_for_claims_marked_as_volunteers() -> None:
    status = json.loads((ROOT / "instructions" / "request-status.json").read_text(encoding="utf-8"))
    rows = dict(_strings(status))
    plain = _code_text(ROOT / "web" / "src" / "components" / "status" / "PlainStatus.tsx")
    for _, path in CLAIM_DERIVED:
        key = path.rsplit("/", 1)[1]
        assert CLAIM.search(rows[path]), f"{path} no longer needs its exemption"
        # Each is read only behind outsideVolunteer() / agent.volunteer, never as a default.
        uses = re.findall(rf"(\S+)\s*\?\s*\(?\s*\w+(?:\.\w+)*\.{key}\b", plain)
        assert uses and all(use.endswith(("volunteer", ".volunteer")) for use in uses), (key, uses)
    # The neutral lines the volunteer ones replace, and the derived helper label, say no volunteer.
    for path in (
        "/plain/happened/work_claimed",
        "/plain/happened/check_claimed",
        "/plain/bands/sorted/waiting",
        "/plain/bands/made/helper_worker",
        "/plain/bands/checked/checking",
        "/chips/agent",
    ):
        assert "volunteer" not in rows[path].lower(), path


def test_no_hand_written_page_text_or_served_file_says_a_volunteer_did_the_work() -> None:
    sources = [
        ROOT / "web" / "index.html",
        ROOT / "deploy" / "cloudflare" / "worker.js",
        *sorted((ROOT / "web" / "src" / "pages").glob("*.tsx")),
        *sorted((ROOT / "web" / "src" / "components").rglob("*.tsx")),
        *sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml")),
    ]
    found = [
        f"{path.relative_to(ROOT)}: {match.group(0)!r}"
        for path in sources
        for match in CLAIM.finditer(_code_text(path))
    ]
    assert found == []
