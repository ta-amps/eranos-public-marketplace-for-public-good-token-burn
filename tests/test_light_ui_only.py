"""Mechanical light-UI-only conformance gate for Eranos.

Ensures Eranos always renders the warm Paper & Ink light palette (#f5f2ea / #fffdf8)
regardless of OS prefers-color-scheme settings, across source and built bundles.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCANNED_EXTENSIONS = {".html", ".css", ".ts", ".tsx", ".js", ".mjs", ".svg"}

FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "prefers-color-scheme: dark media query",
        re.compile(r"prefers-color-scheme\s*:\s*dark", re.I),
    ),
    ("color-scheme: light dark declaration", re.compile(r"color-scheme\s*:\s*light\s+dark", re.I)),
    ("dark data-theme selector or attribute", re.compile(r"data-theme\s*=\s*[\"']?dark\b", re.I)),
    (
        "legacy dark navy surface/background declaration",
        re.compile(
            r"(?:--bg|--surface|--sunken|--agent-banner-bg|background(?:-color)?)\s*:\s*#(?:11161f|0b0f16|1b2230)\b",
            re.I,
        ),
    ),
)


def _iter_ui_files() -> list[Path]:
    files: list[Path] = [
        ROOT / "web" / "index.html",
        ROOT / "deploy" / "cloudflare" / "worker.js",
    ]
    for folder in ("src", "public", "dist", "dist-live"):
        target = ROOT / "web" / folder
        if not target.exists():
            continue
        for path in sorted(target.rglob("*")):
            if path.is_file() and path.suffix.lower() in SCANNED_EXTENSIONS:
                files.append(path)
    return files


def test_index_html_pins_light_only_theme_and_color_scheme() -> None:
    index_html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<html\b[^>]*\bdata-theme="light"', index_html), (
        'web/index.html <html> must declare data-theme="light"'
    )
    assert re.search(r'<meta\s+name="color-scheme"\s+content="only light"\s*/?>', index_html), (
        'web/index.html must declare <meta name="color-scheme" content="only light" />'
    )


def test_tokens_css_sets_light_only_color_scheme_and_paper_palette() -> None:
    tokens_css = (ROOT / "web" / "src" / "styles" / "tokens-v4.css").read_text(encoding="utf-8")
    assert re.search(r"color-scheme\s*:\s*only light\s*;", tokens_css), (
        "tokens-v4.css must declare color-scheme: only light;"
    )
    assert re.search(r"--bg\s*:\s*#f5f2ea\s*;", tokens_css, re.I), (
        "tokens-v4.css must keep --bg: #f5f2ea;"
    )
    assert re.search(r"--surface\s*:\s*#fffdf8\s*;", tokens_css, re.I), (
        "tokens-v4.css must keep --surface: #fffdf8;"
    )


def test_no_dark_mode_css_or_background_declarations_in_source_or_bundles() -> None:
    violations: list[str] = []
    for path in _iter_ui_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        for label, pattern in FORBIDDEN_PATTERNS:
            match = pattern.search(text)
            if match:
                violations.append(f"{rel}: {label} ({match.group(0)!r})")
    assert not violations, "Dark-mode UI declarations are forbidden:\n" + "\n".join(violations)
