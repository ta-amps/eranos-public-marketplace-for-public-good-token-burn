"""The agent banner is one shared file: Agora and Eranos serve the same bytes, so the two sites never drift."""

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BANNER = ROOT / "web" / "public" / "agent-banner.js"
# Agora's site/assets/agent-banner.js at commit 83a615e (review N2 to N4).
SHARED_SHA256 = "fd51472c4ab130983996925b64d8934d775be243f3221df50181a8a9c72cdf5b"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_banner_is_the_shared_file() -> None:
    assert _sha(BANNER) == SHARED_SHA256, (
        "web/public/agent-banner.js differs from the shared banner; copy Agora's file byte for byte"
    )


def _committed(path: Path) -> bytes:
    """The file as Agora last committed it, so Agora's unfinished edits don't break this repo's checks."""
    run = subprocess.run(
        ["git", "-C", str(path.parent), "show", f"HEAD:./{path.name}"],
        capture_output=True,
        check=False,
    )
    return run.stdout if run.returncode == 0 else path.read_bytes()


def test_banner_matches_the_agora_worktree_when_it_is_beside_this_checkout() -> None:
    candidates = [
        os.environ.get("AGORA_BANNER_PATH", ""),
        str(ROOT.parent.parent / "agora" / "agora-src" / "site" / "assets" / "agent-banner.js"),
    ]
    for candidate in filter(None, candidates):
        path = Path(candidate)
        if path.is_file():
            agora = hashlib.sha256(_committed(path)).hexdigest()
            assert agora == _sha(BANNER), (
                f"{path} (as committed) and web/public/agent-banner.js have drifted apart"
            )
            return
    pytest.skip("no Agora worktree beside this checkout; the pinned hash above still applies")
