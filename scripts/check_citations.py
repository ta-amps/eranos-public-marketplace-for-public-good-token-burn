#!/usr/bin/env python3
"""Independent citation check for a delivered report: fetch every cited URL, find every quote verbatim.

Standard library only, and it imports nothing from Eranos, so it does not share the worker's code.
Give it a report as a file (the delivered noun, its `value`, or the bare report) or as an address
(for example https://eranos.ta-amps.workers.dev/api/nouns/eranos.solutions/<report_id>):

    python3 scripts/check_citations.py <file-or-url> [--min-claims 3]

Text rules (the same documented rules the worker uses, written again here): HTML drops script,
style, noscript, template, svg and head content except the title, and block tags end a line; JSON
contributes every string value; whitespace collapses. A quote passes when it appears, with its
whitespace collapsed, in the fetched text. Exit 0 only when every quote passes, there are at least
--min-claims claims, and no source is marked synthetic.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from typing import Any

BLOCK = set(
    [
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    ]
)
SKIP = {"script", "style", "noscript", "template", "svg", "head"}
UA = "eranos-citation-check/0.1"


class Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in SKIP and tag != "title":
            self.skip += 1
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP and tag != "title":
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def strings(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            strings(item, out)
    elif isinstance(value, list):
        for item in value:
            strings(item, out)


def collapse(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def get(url: str) -> tuple[str, bytes]:
    if not url.startswith("https://"):
        raise ValueError("only https addresses are checked")
    request = urllib.request.Request(url, headers={"User-Agent": UA})  # noqa: S310 - https only
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - https only
        return str(response.headers.get("content-type") or "").lower(), response.read(4_000_000)


def page_text(content_type: str, raw: bytes) -> str:
    charset = re.search(r"charset=([\w.-]+)", content_type)
    text = raw.decode(charset.group(1) if charset else "utf-8", errors="replace")
    if content_type.startswith("application/json"):
        out: list[str] = []
        strings(json.loads(text), out)
        return collapse("\n".join(out))
    if content_type.startswith("text/plain"):
        return collapse(text)
    parser = Text()
    parser.feed(text)
    return collapse("".join(parser.parts))


def load(target: str) -> dict[str, Any]:
    if target.startswith("https://"):
        data = json.loads(get(target)[1])
    else:
        with open(target, encoding="utf-8") as fh:
            data = json.load(fh)
    for key in ("value", "report"):
        if isinstance(data, dict) and isinstance(data.get(key), dict) and "claims" not in data:
            data = data[key]
    return dict(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("report")
    parser.add_argument("--min-claims", type=int, default=3)
    args = parser.parse_args()
    report = load(args.report)
    sources = {str(s["id"]): s for s in report.get("sources") or []}
    texts: dict[str, str] = {}
    problems: list[str] = []
    for sid, source in sources.items():
        if source.get("synthetic") is True:
            problems.append(f"source {sid} is marked synthetic")
        try:
            texts[sid] = page_text(*get(str(source["url"])))
        except Exception as exc:
            problems.append(f"source {sid} could not be fetched: {type(exc).__name__}")
    rows = []
    for claim in report.get("claims") or []:
        for citation in claim.get("citations") or []:
            sid, quote = str(citation.get("source")), collapse(str(citation.get("quote") or ""))
            found = bool(quote) and quote in texts.get(sid, "")
            rows.append({"claim": claim.get("id"), "source": sid, "verbatim": found})
            if not found:
                problems.append(f"claim {claim.get('id')}: quote not found at source {sid}")
    claims = len(report.get("claims") or [])
    if claims < args.min_claims:
        problems.append(f"{claims} claims; at least {args.min_claims} are needed")
    passed = sum(r["verbatim"] for r in rows)
    print(
        json.dumps(
            {
                "report_id": report.get("report_id"),
                "claims": claims,
                "quotes": len(rows),
                "verbatim": passed,
                "sources": len(sources),
                "problems": problems,
                "rows": rows,
            },
            indent=1,
        )
    )
    return 0 if not problems and rows and passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
