"""Tests for `.claude/hooks/guard.py` enforcing protected paths and banned flags."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / ".claude" / "hooks" / "guard.py"


def run_guard(tool: str, tool_input: dict[str, object]) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": str(REPO)})
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=payload,
        capture_output=True,
        text=True,
        env={"CLAUDE_PROJECT_DIR": str(REPO)},
        check=False,
    )


def test_guard_blocks_reading_dotenv_and_allows_dotenv_example() -> None:
    assert run_guard("Read", {"file_path": ".env"}).returncode == 2
    assert run_guard("Read", {"file_path": ".env.example"}).returncode == 0


def test_guard_blocks_sandbox_bypass_and_contributor_mode() -> None:
    assert run_guard("Bash", {"command": "muse exec --yolo"}).returncode == 2
    assert run_guard("Bash", {"command": "muse exec --contributor-mode on"}).returncode == 2
    assert run_guard("Bash", {"command": "uv run pytest -q"}).returncode == 0
