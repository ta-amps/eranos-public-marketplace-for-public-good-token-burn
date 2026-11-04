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


def test_an_official_source_comes_first_and_open_research_follows():
    fetch = brief("What federal rule covers uniform allowable cost for a grant?")["fetch"]
    ids = [a["id"] for a in fetch["apis"]]
    assert ids.index("europe-pmc") > ids.index("federal-register")


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
