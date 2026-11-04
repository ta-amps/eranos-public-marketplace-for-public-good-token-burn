"""Every test's wake files live in its own folder (the review's F5): a test run never touches the
live workers' ~/.local/state/eranos-worker/wake, so it can never wake them."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _private_wake_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ERANOS_WAKE_DIR", str(tmp_path / "wake"))
