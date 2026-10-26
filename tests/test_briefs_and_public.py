"""Tests for volunteer briefs, public-name/secret scan, and shared script byte-identity."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from eranos.schemas import TaskBrief

REPO = Path(__file__).resolve().parent.parent
BRIEFS = sorted((REPO / "briefs").glob("*.json"))


@pytest.mark.parametrize("path", BRIEFS, ids=lambda p: p.stem)
def test_every_brief_is_valid_and_non_public(path: Path) -> None:
    brief = TaskBrief.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert brief.task_id == path.stem
    assert brief.owner_type == "human" or brief.effect_class != "public"


def test_agent_brief_refuses_public_effect() -> None:
    raw = json.loads(BRIEFS[0].read_text(encoding="utf-8"))
    raw.update(effect_class="public", owner_type="muse-code")
    with pytest.raises(ValidationError, match="public effect"):
        TaskBrief.model_validate(raw)


def test_check_public_passes_cleanly() -> None:
    res = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "check_public.py"), str(REPO)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stdout + res.stderr


def test_shared_scripts_match_hackathon_context() -> None:
    kit = REPO.parent / "hackathon-context"
    if not kit.exists():
        pytest.skip("hackathon-context sibling not present")
    pairs = [
        (REPO / "scripts" / "check_public.py", kit / "scripts" / "check_public.py"),
        (REPO / "scripts" / "build_index.py", kit / "scripts" / "build_index.py"),
        (REPO / "scripts" / "check_architecture.py", kit / "scripts" / "check_architecture.py"),
        (REPO / "scripts" / "private-names.sha256", kit / "scripts" / "private-names.sha256"),
        (REPO / "deploy" / "bootstrap-hosting.sh", kit / "scripts" / "bootstrap-hosting.sh"),
    ]
    for ours, theirs in pairs:
        assert (
            hashlib.sha256(ours.read_bytes()).hexdigest()
            == hashlib.sha256(theirs.read_bytes()).hexdigest()
        ), ours.name
