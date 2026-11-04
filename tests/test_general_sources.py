"""A question no official page fits still gets public sources: open research searches, cited per article."""

from __future__ import annotations

import json
import time
from pathlib import Path

from eranos.pipeline import research as R
from eranos.sources import Fetched

ROOT = Path(__file__).resolve().parents[1]
RULES = json.loads((ROOT / "instructions" / "worker.json").read_text())
GUARD = json.loads((ROOT / "instructions" / "public-research.json").read_text())
QUESTION = (
    "Example request: a short literature review on what helps small nonprofits keep their volunteers, "
    "using public research and with a source for each point."
)
EPMC = {
    "resultList": {
        "result": [
            {
                "id": "111",
                "source": "MED",
                "title": "Volunteer retention in community groups.",
                "abstractText": "<h4>Abstract</h4>Volunteers stayed longer when nonprofits gave them clear roles and regular thanks.",
                "authorString": "A Person, B Person",
            },
            {"id": "222", "source": "MED", "title": "No abstract here"},
        ]
    }
}
DOAJ = {
    "results": [
        {
            "bibjson": {
                "title": "Why volunteers leave nonprofits",
                "abstract": "Nonprofits that trained volunteers for 2 hours or more kept more volunteers after one year.",
                "identifier": [{"type": "doi", "id": "10.1234/x"}],
                "author": [{"name": "C Person"}],
            }
        }
    ]
}


OPENALEX = {
    "results": [
        {
            "doi": "https://doi.org/10.5555/y",
            "title": "Volunteer motivation",
            "abstract_inverted_index": {
                "Thanks": [0],
                "keep": [1],
                "volunteers": [2],
                "coming": [3],
                "back.": [4],
            },
        }
    ]
}


def fetcher(url: str) -> Fetched:
    body = EPMC if "europepmc" in url else DOAJ if "doaj" in url else OPENALEX
    raw = json.dumps(body).encode()
    return Fetched(
        url=url,
        final_url=url,
        status=200,
        content_type="application/json",
        raw=raw,
        fetched_at=time.time(),
    )


def brief(text: str = QUESTION) -> dict:
    return R.research_brief(
        "rq-test", {"text": text, "part": 1, "n": 1}, "Example", GUARD, RULES, []
    )


def test_query_is_about_the_subject_not_the_asking():
    assert R.query_terms(QUESTION) == ["nonprofits", "retention", "volunteers"]


def test_a_question_no_official_page_fits_gets_the_research_searches():
    assert [a["id"] for a in brief()["fetch"]["apis"]] == ["openalex", "doaj", "europe-pmc"]


def test_a_question_an_official_source_fits_keeps_only_that_source():
    fetch = brief("What federal rule covers uniform allowable cost for a grant?")["fetch"]
    assert "europe-pmc" not in [a["id"] for a in fetch["apis"]]
    assert fetch["apis"]


def test_each_article_is_its_own_source_with_its_own_address_and_no_authors():
    sources, failures = R.gather(brief(), fetcher)
    assert failures == []
    assert [s["url"] for s in sources] == [
        "https://doi.org/10.5555/y",
        "https://doi.org/10.1234/x",
        "https://europepmc.org/article/MED/111",
    ]
    assert sources[0]["title"] == "Volunteer motivation"
    assert "Thanks keep volunteers coming back." in sources[0]["text"]
    joined = " ".join(s["text"] for s in sources)
    assert "<h4>" not in joined and "Person" not in joined
    assert "clear roles and regular thanks." in joined


def test_two_gathers_agree_so_the_reviewers_fetch_finds_the_makers_quotes():
    b = brief()
    one, _ = R.gather(b, fetcher)
    two, _ = R.gather(b, fetcher)
    assert [(s["id"], s["url"], s["text"]) for s in one] == [
        (s["id"], s["url"], s["text"]) for s in two
    ]


def test_a_search_with_no_abstracts_is_a_recorded_reason():
    def empty(url: str) -> Fetched:
        return Fetched(
            url=url,
            final_url=url,
            status=200,
            content_type="application/json",
            raw=b"{}",
            fetched_at=time.time(),
        )

    sources, failures = R.gather(brief(), empty)
    assert sources == []
    assert len(failures) == 3 and "no articles" in failures[0]
