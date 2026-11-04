"""The hosted practice check and page text treat the MADE-UP mark as the Python check does."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_worker_and_web_accept_the_made_up_mark() -> None:
    worker = (ROOT / "deploy/cloudflare/worker.js").read_text(encoding="utf-8")
    shown = (ROOT / "web/src/lib/shown.ts").read_text(encoding="utf-8")
    assert '!sample.includes("MADE-UP")' in worker
    for text in (worker, shown):
        assert "MADE-UP:" in text
