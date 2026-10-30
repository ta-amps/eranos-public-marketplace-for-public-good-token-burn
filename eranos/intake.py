"""Read a request from the public GitHub issue form (`.github/ISSUE_TEMPLATE/request-a-kit.yml`).

The form is the noun that defines a request's fields; this reads its labels and ids rather than
keeping a second copy. GitHub renders a submitted form as `### <label>` sections. Only the form's
fields are kept: the issue's author, comments and anything else on the issue are never read.
"""

from __future__ import annotations

import re
from pathlib import Path

FORM = Path(__file__).resolve().parents[1] / ".github" / "ISSUE_TEMPLATE" / "request-a-kit.yml"
_FIELD = re.compile(
    r"^\s*id:\s*(?P<id>[a-z-]+)\s*\n\s*attributes:\s*\n\s*label:\s*(?P<label>.+?)\s*$", re.M
)
_SECTION = re.compile(r"^###\s+(?P<label>.+?)\s*$", re.M)


class FormIncomplete(ValueError):
    """The body is not a completed request form; nothing was read into a request."""


def form_fields(form: Path = FORM) -> dict[str, str]:
    """The form's field labels mapped to request field names (`person-only` -> `person_only`)."""
    text = form.read_text(encoding="utf-8")
    return {m["label"].strip("'\""): m["id"].replace("-", "_") for m in _FIELD.finditer(text)}


def parse_issue_form(body: str, form: Path = FORM) -> dict[str, str]:
    """The request fields of a submitted form body; both confirmations must be ticked."""
    labels = form_fields(form)
    sections: dict[str, str] = {}
    matches = list(_SECTION.finditer(body))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        name = labels.get(match["label"])
        if name:
            value = body[match.end() : end].strip()
            sections[name] = "" if value == "_No response_" else value
    confirm = sections.pop("confirm", "")
    ticked = re.findall(r"^- \[[xX]\] ", confirm, re.M)
    if len(ticked) < 2:
        raise FormIncomplete("both confirmations on the request form must be ticked")
    missing = [n for n in ("organization_type", "job", "person_only") if not sections.get(n)]
    if missing:
        raise FormIncomplete(f"the request form is missing: {', '.join(missing)}")
    return sections
