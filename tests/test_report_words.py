"""Report titles end on a whole word, and counts of one read as singular."""

from __future__ import annotations

from eranos.contributor import research_report
from eranos.pipeline.requests import _short_title


def test_short_title_leaves_a_title_that_fits() -> None:
    assert _short_title("Food pantry: a short title") == "Food pantry: a short title"
    exact = "x" * 140
    assert _short_title(exact) == exact


def test_short_title_cuts_between_words_within_the_limit() -> None:
    text = "Volunteer center: " + "word " * 40
    title = _short_title(text)
    assert len(title) <= 140
    assert title.endswith("word…")


def test_short_title_never_breaks_a_word() -> None:
    title = _short_title("Volunteer center: " + "a" * 118 + " without turning away")
    assert title.endswith("…")
    assert title.split()[-1].rstrip("…") in {"without", "a" * 118}


def _brief(sources: int) -> dict[str, object]:
    return {
        "report_id": "RPT-TEST",
        "request_id": "rq-test",
        "title": "A title",
        "question": "What do tenant deposit rules say",
        "guardrails": {},
        "sources": [
            {
                "id": f"S{i}",
                "title": "Source",
                "publisher": "Publisher",
                "url": "https://example.org",
                "access": "public",
                "public": True,
                "synthetic": False,
                "topics": ["tenant"],
                "text": f"Tenant deposit rule number {i} applies.",
            }
            for i in range(sources)
        ],
    }


def test_summary_counts_read_as_singular_for_one() -> None:
    assert research_report(_brief(1))["summary"].startswith("1 cited point from 1 public source. ")


def test_summary_counts_read_as_plural_for_two() -> None:
    assert research_report(_brief(2))["summary"].startswith(
        "2 cited points from 2 public sources. "
    )
