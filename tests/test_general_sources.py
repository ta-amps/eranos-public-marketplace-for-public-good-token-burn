"""A question no official page fits still gets public sources: open research searches, cited per article."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

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
    assert [a["id"] for a in brief()["fetch"]["apis"]] == [
        "openalex",
        "doaj",
        "europe-pmc",
        "wikipedia",
    ]


def test_an_ordinary_question_can_read_the_encyclopedia_and_the_research_searches():
    ids = [a["id"] for a in brief("How should a shelter welcome new helpers?")["fetch"]["apis"]]
    assert ids == ["openalex", "wikipedia", "doaj", "europe-pmc"]


def test_an_official_source_comes_first_and_open_research_follows():
    fetch = brief("What federal rule covers uniform allowable cost for a grant?")["fetch"]
    ids = [a["id"] for a in fetch["apis"]]
    assert ids.index("europe-pmc") > ids.index("federal-register")


def test_each_article_is_its_own_source_with_its_own_address_and_no_authors():
    sources, failures = R.gather(brief(), fetcher)
    assert len(failures) == 1 and "no articles" in failures[0]  # this fixture has no encyclopedia
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
    assert len(failures) == 4 and "no articles" in failures[0]


class _Mem:
    def __init__(self):
        self.records = {}

    def get_record(self, store, key):

        from tessera import NotFound

        if (store, key) not in self.records:
            raise NotFound("none")
        return self.records[(store, key)]

    def put_record(self, store, key, value, expected_version=0, **kw):
        from types import SimpleNamespace

        rec = SimpleNamespace(value=value, version=expected_version + 1, **kw)
        self.records[(store, key)] = rec
        return rec


def _report(report_id="RPT-X"):
    return {"report_id": report_id, "claims": [{"id": "C1"}]}


def test_a_maker_report_is_kept_as_a_labeled_draft_and_delivered_only_when_asked(monkeypatch):
    monkeypatch.setattr(R, "update_request_part", lambda *a, **k: None)
    mem = _Mem()
    R.save_unaudited(mem, _report(), request_id="rq", part=1, maker_receipt="r", deliver=False)
    assert mem.records[(R.DRAFTS_STORE, "RPT-X")].value["audit_status"] == "not_audited_yet"
    assert (R.SOLUTIONS_STORE, "RPT-X") not in mem.records
    R.save_unaudited(mem, _report(), request_id="rq", part=1, maker_receipt="r", deliver=True)
    assert mem.records[(R.SOLUTIONS_STORE, "RPT-X")].value["audit_status"] == "not_audited_yet"


def test_a_failed_audit_changes_the_label_and_an_audited_result_is_never_overwritten(monkeypatch):
    monkeypatch.setattr(R, "update_request_part", lambda *a, **k: None)
    mem = _Mem()
    R.save_unaudited(mem, _report(), request_id="rq", part=1, maker_receipt="r", deliver=True)
    R.mark_audit_failed(mem, "RPT-X", ["a quote did not match"])
    assert mem.records[(R.SOLUTIONS_STORE, "RPT-X")].value["audit_status"] == "audit_failed"
    mem.records[(R.SOLUTIONS_STORE, "RPT-Y")] = __import__("types").SimpleNamespace(
        value={"audit_status": "audited"}, version=1
    )
    R.save_unaudited(
        mem, _report("RPT-Y"), request_id="rq", part=1, maker_receipt="r", deliver=True
    )
    assert mem.records[(R.SOLUTIONS_STORE, "RPT-Y")].value["audit_status"] == "audited"


def test_a_label_and_a_false_friend_stay_out_of_the_search():
    text = "How can a shelter keep its bed-list spreadsheet accurate? Test run, Nov 4."
    terms = R.query_terms(text)
    assert "retention" not in terms and "keep" not in terms
    assert not {"test", "run"} & set(terms)
    assert "spreadsheet" in terms
    assert "retention" in R.query_terms("How do small nonprofits keep their volunteers?")


WIKI = {
    "query": {
        "pages": [
            {
                "index": 2,
                "title": "Second article",
                "extract": "Second opening sentence about volunteers and nonprofits.",
                "fullurl": "https://en.wikipedia.org/wiki/Second_article",
            },
            {
                "index": 1,
                "title": "First article",
                "extract": "First opening sentence about volunteers and nonprofits.",
                "fullurl": "https://en.wikipedia.org/wiki/First_article",
            },
            {"index": 3, "title": "Not https", "extract": "x", "fullurl": "http://x.example/"},
        ]
    }
}


def _wiki_brief() -> dict:
    return {
        "report_id": "RPT-W",
        "request_id": "rq-w",
        "part": 1,
        "fetch": {
            "links": [],
            "pages": [],
            "query_terms": ["volunteers"],
            "max_sources": 5,
            "apis": [a for a in RULES["sources"]["official_apis"] if a["id"] == "wikipedia"],
        },
    }


def test_wikipedia_gives_one_source_per_article_with_its_full_text_and_own_address():
    def answer(url: str) -> Fetched:
        body = (
            {
                "query": {
                    "pages": [{"extract": "Whole article text about volunteers and nonprofits."}]
                }
            }
            if "generator=search" not in url
            else WIKI
        )
        return Fetched(url, url, 200, "application/json", json.dumps(body).encode(), time.time())

    sources, failures = R.gather(_wiki_brief(), answer)
    assert not failures
    assert [s["url"] for s in sources] == [
        "https://en.wikipedia.org/wiki/First_article",
        "https://en.wikipedia.org/wiki/Second_article",
    ]
    assert "Whole article text" in sources[0]["text"]
    assert sources[0]["publisher"].startswith("Wikipedia")


def test_a_failed_full_text_still_leaves_the_opening_the_search_gave(monkeypatch):
    monkeypatch.setattr(R, "FETCH_RETRY_SECONDS", 0)

    def answer(url: str) -> Fetched:
        if "generator=search" not in url:
            raise RuntimeError("no answer")
        return Fetched(url, url, 200, "application/json", json.dumps(WIKI).encode(), time.time())

    sources, _ = R.gather(_wiki_brief(), answer)
    assert "First opening sentence" in sources[0]["text"]


def test_a_dropped_search_is_asked_once_more_and_a_refused_address_never(monkeypatch):
    monkeypatch.setattr(R, "FETCH_RETRY_SECONDS", 0)
    calls = {"n": 0}

    def flaky(url: str) -> Fetched:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("answered 503")
        return fetcher(url)

    assert R._fetch_again(flaky, "https://x.example/").status == 200
    assert calls["n"] == 2
    calls["n"] = 0

    def refused(url: str) -> Fetched:
        calls["n"] += 1
        raise R.SourceRefused("no")

    with pytest.raises(R.SourceRefused):
        R._fetch_again(refused, "https://x.example/")
    assert calls["n"] == 1


def test_search_phrases_stay_plain_few_and_short():
    assert R.clean_phrases(
        ["data quality", "DATA  quality", "a" * 81, "https://x.example/a", "a;b"]
    ) == ["data quality"]
    assert R.clean_phrases("data quality") == []
    assert R.clean_phrases([1, None, {"x": 1}]) == []
    assert len(R.clean_phrases(["a b", "c d", "e f", "g h"])) == R.MAX_SEARCH_PHRASES


def test_phrases_only_fill_the_query_of_a_search_the_brief_permits():
    urls = [u for u, _, _ in R.phrase_urls(brief(), ["a b&host=evil.example"])]
    assert len(urls) == 4
    assert all("%26host%3Devil.example" in u for u in urls)
    assert {u.split("/")[2] for u in urls} == {
        "api.openalex.org",
        "en.wikipedia.org",
        "doaj.org",
        "www.ebi.ac.uk",
    }
    part = {"text": "What does this page say?", "part": 1, "n": 1}
    with_links = R.research_brief("rq-test", part, "Example", GUARD, RULES, ["https://x.example/"])
    assert R.phrase_urls(with_links, ["a b"]) == []


def test_label_words_inside_a_question_are_the_question():
    text = (
        "We ran a test run of our disaster plan; what should evacuation drills for seniors cover?"
    )
    assert R.subject_text(text) == text
    assert "evacuation" in R.query_terms(text)
    assert (
        R.subject_text("Practice case: an example, not a real person or case. How do we plan?")
        == "How do we plan?"
    )
    assert R.subject_text("Practice case: How do we plan?") == "How do we plan?"
    assert (
        R.subject_text("Test run: How do we plan? We have 20 bins.")
        == "How do we plan? We have 20 bins."
    )
    assert (
        R.subject_text(
            "How do we plan? Test run, Nov 4, 2026, our own example, not a real organization's request."
        )
        == "How do we plan?"
    )
    assert R.subject_text("How do we plan? (Test run, Nov 4.)") == "How do we plan?"
    assert R.subject_text("How do we plan? Test run, Nov 4.") == "How do we plan?"
    start = (
        "Test run, Nov 4, 2026, our own example, not a real organization's request. How do we plan?"
    )
    assert R.subject_text(start) == "How do we plan?"
    assert not {"test", "organization's"} & set(R.query_terms(start + " Budget plans."))


def test_more_label_shapes_leave_the_question_whole():
    for text in (
        "How should we plan an evacuation test run, including wheelchair routes?",
        "We want a plan for our test run, for flood season.",
    ):
        assert R.subject_text(text) == text
    assert (
        R.subject_text("Example request: how do we run a test run?") == "how do we run a test run?"
    )
    assert R.subject_text("Practice case: how can a pantry keep volunteers?").endswith(
        "volunteers?"
    )
    assert R.subject_text("Test run.") == "Test run."


def test_a_claim_may_not_add_a_number_or_an_address():
    quote = "Keep raw chicken cold for no more than 2 hours, says fda.gov today."
    assert not R.adds_to_quote("Keep raw chicken cold for 2 hours, says fda.gov.", quote)
    assert R.adds_to_quote("Keep raw chicken cold for 200 hours.", quote)
    assert R.adds_to_quote("Read more at evil.example/x for details.", quote)
    assert R.adds_to_quote("Donate at paypal.me today.", quote)


def test_a_search_answer_cannot_name_a_bare_ip_as_an_article():
    assert R._names_an_ip("https://169.254.169.254/latest/meta")
    assert not R._names_an_ip("https://doi.org/10.1/x")


def test_a_literal_retention_word_stays_and_only_a_mapped_one_goes():
    assert "retention" in R.query_terms("What are the IRS record retention rules?")
    assert "turnover" in R.query_terms("How do we measure inventory turnover?")


def test_a_legal_question_never_reads_the_open_encyclopedia():
    part = {"text": "What does the law say about tenants?", "part": 1, "n": 1, "legal": True}
    made = R.research_brief("rq-test", part, "Example", GUARD, RULES, [])
    assert "wikipedia" not in [a["id"] for a in made["fetch"]["apis"]]


def test_a_wikipedia_answer_only_cites_wikipedia():
    body = {
        "query": {
            "pages": [
                {"index": 1, "title": "X", "extract": "Y z.", "fullurl": "https://evil.example/x"}
            ]
        }
    }
    assert R.search_articles("wikipedia", json.dumps(body).encode()) == []
    assert (
        R.search_articles("wikipedia", json.dumps({"query": {"pages": {"1": {}}}}).encode()) == []
    )


def test_a_caveat_goes_with_every_report_whose_brief_holds_its_page():
    fetch = {"pages": [{"url": "https://x.example/", "caveat": "Rules vary."}]}
    base = {"report_id": "R", "request_id": "r", "title": "t", "question": "q", "fetch": fetch}
    source = {"id": "S1", "url": "https://en.wikipedia.org/wiki/Milk", "title": "Milk"}
    claim = {"id": "C1", "text": "x", "citations": [{"source": "S1", "quote": "y"}]}
    assert "Rules vary." in R.build_report(base, [source], [claim], {}, guardrails={})["summary"]


def test_two_rounds_of_sources_never_share_a_number():
    made = brief()
    first, _ = R.gather(made, fetcher)
    made["fetch"]["apis"] = [a for a in made["fetch"]["apis"] if a["id"] == "doaj"]
    second, _ = R.gather(made, lambda u: fetcher(u), phrases=["other words"])
    assert not {s["id"] for s in first} & {s["id"] for s in second}


def test_a_less_than_sign_in_an_abstract_is_text_not_a_tag():
    assert (
        R._plain("sites with <10 staff and >50 volunteers")
        == "sites with <10 staff and >50 volunteers"
    )
    assert R._plain("<h4>Abstract</h4>Volunteers stayed.") == "Abstract Volunteers stayed."


def test_a_banned_word_in_the_question_or_a_title_does_not_stop_a_report():
    from eranos.pipeline.solutions import report_findings

    report = {"question": "Do we need criminal background checks?", "title": "Criminal checks"}
    assert not any("accusatory" in f for f in report_findings(report, {"sources": []}))
    assert any(
        "accusatory" in f
        for f in report_findings({"summary": "They are criminals."}, {"sources": []})
    )


def test_sentences_that_lost_their_start_or_end_or_sit_under_a_warning_are_not_quotable():
    for text in (
        "A pantry may not, under Sec. 5 of the code, hand out raw chicken without a license.",
        "Do not follow Gov. Smith who said a pantry can hand out raw chicken.",
        "Do not give more than approx. 40 pounds of raw chicken to any guest.",
    ):
        assert all(
            not s.startswith(("5 of", "Smith", "40 pounds")) for s in R.standalone_sentences(text)
        )
    ended = "Volunteers can hand out raw chicken in most U.S. States only with a permit."
    assert all(not s.endswith("U.S.") for s in R.standalone_sentences(ended))
    for heading in (
        "Don\u2019t",
        "Avoid these mistakes",
        "Common mistakes",
        "Unsafe practices",
        "What not to do",
    ):
        assert R.standalone_sentences(f"{heading}\nLeave raw chicken out for 2 hours.") == []
    assert R.standalone_sentences("Avoid\nLeave it out.\nSafe storage\nKeep it cold.") == [
        "Safe storage",
        "Keep it cold.",
    ]


def test_a_claim_cannot_flip_or_add_a_negation():
    long = "Volunteers who work alone at the food pantry must not handle raw chicken."
    assert R.adds_to_quote(
        "Volunteers who work alone at the food pantry must handle raw chicken.", long
    )
    assert R.adds_to_quote(
        "Volunteers and staff may handle it.", "Neither volunteers nor staff may handle it."
    )
    assert R.adds_to_quote("Do not keep raw chicken cold.", "Keep raw chicken cold.")
    assert not R.adds_to_quote("Keep raw chicken cold.", "Keep raw chicken cold.")


def test_an_icons_title_is_not_the_pages_title():
    from eranos.sources import extract_text

    page = b"<html><head><title>Severe Weather</title></head><body><svg><title>Lock</title></svg><p>Plan now.</p></body></html>"
    assert extract_text("text/html", page) == ("Severe Weather", "Plan now.")
