"""Information parts answered from permitted public sources, with a quote for every claim.

- The planner writes a research brief naming what may be fetched: the request's own https links and
  the official open APIs whose topics fit the part (`eranos.instructions/worker` noun).
- The builder fetches each permitted source once, keeps it as a source noun with its SHA-256
  digests, and gives the model (a Muse model through the Meta API) numbered sentences from it. The model proposes claims, each
  resting on one sentence with an exact quote. A deterministic checker keeps a claim only when its
  quote is verbatim in the fetched text, its own words come from that quote, and it carries no
  personal data or accusation. The report passes the same `report_findings` rules as any report.
- The reviewer, a different key, fetches every cited source again and re-checks every quote and
  guardrail against the fresh text before the report is delivered (`deliver_report`).
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import re
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any
from urllib.parse import quote_plus, urlsplit

from tessera import NotFound

from eranos.copy import find_accusatory_words
from eranos.model_client import ChatModel, ModelUnavailable, UsageMeter
from eranos.pipeline.request_noun import PRODUCER, update_request_part
from eranos.pipeline.requests import INSTRUCTIONS_STORE, _common_brief
from eranos.pipeline.run import SelfReviewRefused
from eranos.pipeline.solutions import (
    SOLUTIONS_STORE,
    deliver_report,
    quote_finding,
    report_digest,
    report_findings,
)
from eranos.privacy import personal_data_findings
from eranos.sources import Fetched, SourceRefused, _lines, api_query_url, source_record

SOURCES_STORE = "eranos.sources"
BRIEF_KIND = "eranos.public_research"
Fetcher = Callable[[str], Fetched]
FETCH_RETRY_SECONDS = 2.0
MAX_SEARCH_PHRASES = 3
MAX_PHRASE_CHARS = 80
# Source numbers: the brief's searches stay under this, repeated phrases above it, and a source the
# reviewer fetches directly by address above that, so two sources never share an id.
PHRASE_NUMBERS_FROM = 100
DIRECT_NUMBERS_FROM = 1000
_PLAIN_PHRASE = re.compile(r"[^\W_][\w '-]*")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-z0-9][a-z0-9()'-]*")
_STOP = frozenset(
    [
        "about",
        "after",
        "also",
        "because",
        "before",
        "being",
        "between",
        "both",
        "could",
        "does",
        "each",
        "every",
        "from",
        "have",
        "into",
        "just",
        "like",
        "make",
        "many",
        "more",
        "most",
        "must",
        "need",
        "only",
        "other",
        "over",
        "please",
        "same",
        "should",
        "some",
        "such",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "very",
        "want",
        "what",
        "when",
        "where",
        "which",
        "while",
        "will",
        "with",
        "would",
        "your",
        "under",
        "also",
        "shall",
        "such",
        "were",
        "been",
        "here",
        "http",
        "https",
        "www",
        "summarize",
        "summary",
        "citation",
        "citations",
        "point",
        "points",
        "overview",
        "explain",
        "month",
        "monthly",
        "week",
        "weekly",
        "list",
        "relevant",
        "link",
        "links",
        "quote",
        "quotes",
        "source",
        "sources",
    ]
)


# Words about the asking, not the subject: searching for them finds nothing useful.
_QUERY_STOP = frozenset(
    [
        "example",
        "request",
        "showcase",
        "eranos",
        "organization",
        "organizations",
        "short",
        "brief",
        "literature",
        "review",
        "research",
        "public",
        "using",
        "helps",
        "help",
        "helping",
        "small",
        "real",
        "what",
        "ways",
        "best",
        "good",
        "guidance",
    ]
)


# Everyday words for what a question is after, as research papers say it.
_QUERY_MEANS = {
    "keep": "retention",
    "keeps": "retention",
    "keeping": "retention",
    "retain": "retention",
    "stay": "retention",
    "leave": "turnover",
    "quit": "turnover",
    "recruit": "recruitment",
    "find": "recruitment",
    "train": "training",
    "raise": "fundraising",
    "donate": "donation",
}
# "Keep", "stay", "leave" and "find" mean retention or recruitment only when the question is about
# people: keeping a spreadsheet accurate is not retention, and that word sent a search to green roofs.
_ABOUT_PEOPLE = frozenset(
    {
        "volunteer",
        "volunteers",
        "staff",
        "employee",
        "employees",
        "worker",
        "workers",
        "donor",
        "donors",
        "member",
        "members",
        "people",
        "clients",
        "tutor",
        "tutors",
        "mentor",
        "mentors",
    }
)
_PEOPLE_MEANS = frozenset({"retention", "turnover", "recruitment"})
# A label says who is asking or why, not what about: it never goes into a search.
_LABEL_START = re.compile(
    r"^\s*(?:example request:\s*|(?:practice case:|test run\b)[^.?!\n]*[.?!]\s+(?=\S))",
    re.IGNORECASE,
)
# Its own sentence at the end, with at most a date: "...? Test run, Nov 4."
_LABEL_END = re.compile(
    r"(?:^|(?<=[.?!])\s+)test run(?:,\s*[a-z]{3,9}\.?\s+\d{1,2}(?:,\s*\d{4})?)?[.?!]?\s*$",
    re.IGNORECASE,
)


def subject_text(text: str) -> str:
    """The question without a test, example or practice label at its start or end. The same words
    inside a question ("a test run of our disaster plan") are the question."""
    subject = " ".join(_LABEL_END.sub("", _LABEL_START.sub("", text)).split())
    return subject or " ".join(text.split())


def words(text: str) -> set[str]:
    out = set()
    for word in _WORD.findall(text.lower()):
        word = word.strip("'-()")
        if len(word) < 4 or word in _STOP:
            continue
        for suffix in ("ing", "ies", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[: -len(suffix)]
                break
        out.add(word)
    return out


def select_apis(text: str, apis: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The sources whose topics a request names, best first. A source that also lists `requires`
    (context words, such as food or pantry for the food-safety pages) is chosen only when the request
    names one of them, so an unrelated request that shares a common word (donation, safety, code)
    never gets it (the review's T2)."""
    wanted = words(text)
    scored: list[tuple[int, int, int, dict[str, Any]]] = []
    for order, api in enumerate(apis):
        context = words(" ".join(api.get("requires") or []))
        if context and not wanted & context:
            continue
        matched = wanted & words(" ".join(api.get("topics") or []))
        if matched:
            scored.append((-int(bool(context)), -len(matched), order, api))
    # Pages the request's own subject calls for come first, then the best topic match, then the
    # noun's order, so a pantry question with filing words still gets its food pages (the review's T3).
    return [api for *_, api in sorted(scored, key=lambda s: s[:3])]


def general_apis(apis: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The open research sources for a request no official page or API fits by topic, so that a
    question about anything still has somewhere public to look. They search published abstracts."""
    return [api for api in apis if api.get("general")]


def query_terms(text: str, limit: int = 6) -> list[str]:
    seen: list[str] = []
    found = _WORD.findall(subject_text(text).lower())
    about_people = bool(_ABOUT_PEOPLE & {w.strip("'-()") for w in found})
    for word in found:
        word = word.strip("'-") if "(" in word else word.strip("'-()")
        if word in _QUERY_STOP:
            continue
        means = _QUERY_MEANS.get(word, word)
        if means != word and means in _PEOPLE_MEANS and not about_people:
            continue
        word = means
        if len(word) >= 4 and word not in _STOP and word not in seen and not word.isdigit():
            seen.append(word)
    return seen[:limit]


def research_brief(
    request_id: str,
    part: dict[str, Any],
    org: str,
    guardrails: dict[str, Any],
    worker_rules: dict[str, Any],
    links: list[str],
    terms: dict[str, Any] | None = None,
    occurrence: int = 1,
) -> dict[str, Any]:
    """A research verb's whole input: the question, the guardrails and what may be fetched."""
    brief = {**(terms or {}), **_common_brief(request_id, part, org, "RPT")}
    brief.pop("synthetic_only", None)  # public sources only; plain words on everything we publish
    report_id = str(brief.pop("noun_id")) + (f"-O{occurrence}" if occurrence > 1 else "")
    rules = worker_rules.get("sources") or {}
    apis = select_apis(part["text"], list(rules.get("official_apis") or []))
    pages = select_apis(part["text"], list(rules.get("official_pages") or []))
    # Open research searches come after any official source that fits, so a narrow topic list never leaves a
    # question with nothing to read.
    if not links:
        extra = general_apis(list(rules.get("official_apis") or []))
        apis = [*apis, *[a for a in extra if a not in apis]]
    if part.get("legal"):  # a legal answer rests on official text and research, never an open wiki
        apis = [a for a in apis if a.get("results") != "wikipedia"]
    return {
        **brief,
        "report_id": report_id,
        "occurrence": occurrence,
        "kind": BRIEF_KIND,
        "question": part["text"][:600],
        "legal": bool(part.get("legal")),
        "guardrails": guardrails,
        "fetch": {
            "links": [link for link in links if link.startswith("https://")][:10],
            "apis": [
                {
                    k: api[k]
                    for k in (
                        "id",
                        "publisher",
                        "host",
                        "path_prefixes",
                        "access",
                        "query",
                        "results",
                    )
                    if k in api
                }
                for api in apis
            ],
            "pages": [
                {k: page[k] for k in ("id", "publisher", "url", "access", "caveat") if k in page}
                for page in pages
                if str(page.get("url") or "").startswith("https://")
            ],
            "query_terms": query_terms(part["text"]),
            "max_sources": int(rules.get("max_sources") or 5),
            "max_text_chars": int(rules.get("max_text_chars") or 60000),
        },
        "stages": [
            "fetch the permitted sources",
            "propose claims with exact quotes",
            "keep verbatim quotes only",
            "summarize",
        ],
        "output": {
            "node": "report",
            "report": "report_id, request_id, title, question, sources (with url and SHA-256), claims (each with citations: source and exact quote), summary, decision, and the disclaimer when legal",
            "blob_sha256": "sha256 of the report as canonical JSON: sorted keys, no spaces, UTF-8",
        },
        "instructions": {"store": INSTRUCTIONS_STORE, "key": "public-research"},
    }


def review_brief(brief: dict[str, Any]) -> dict[str, Any]:
    """The review verb's input, written by the planner: the ids, the question and what may be
    fetched, so the reviewer rebuilds the report from its own checks and reads no eq02 task."""
    keys = (
        "request_id",
        "part",
        "report_id",
        "title",
        "question",
        "legal",
        "occurrence",
        "fetch",
        "limits",
        "accept_unaudited",
    )
    return {k: brief[k] for k in keys if k in brief} | {
        "kind": "eranos.report_review",
        "recheck": "fetch every cited source again; deliver only claims whose quotes pass",
    }


def permitted_urls(brief: dict[str, Any]) -> list[tuple[str, str, str | None]]:
    """(url, access, publisher) the brief lets this verb fetch, in order."""
    fetch = brief.get("fetch") or {}
    out: list[tuple[str, str, str | None]] = [
        (link, "public_web_page", None) for link in fetch.get("links") or []
    ]
    for page in fetch.get("pages") or []:  # official pages chosen by topic (the worker noun)
        out.append(
            (str(page["url"]), str(page.get("access") or "public_web_page"), page.get("publisher"))
        )
    for api in fetch.get("apis") or []:
        url = api_query_url(api, list(fetch.get("query_terms") or []))
        out.append((url, str(api.get("access") or "official_api"), api.get("publisher")))
    unique = list(
        {url: (url, access, publisher) for url, access, publisher in reversed(out)}.values()
    )[::-1]
    return unique[: int(fetch.get("max_sources") or 5)]


_TAG = re.compile(r"<[^>]+>")
MAX_ARTICLES_PER_SEARCH = 4
# A search answer carries each article's opening; its full text takes one more call, same host.
WIKIPEDIA_PAGE = (
    "https://en.wikipedia.org/w/api.php?action=query&format=json&formatversion=2"
    "&prop=extracts&explaintext=1&redirects=1&titles={title}"
)


def _plain(text: Any) -> str:
    return " ".join(_TAG.sub(" ", str(text or "")).split())


def search_articles(kind: str, raw: bytes) -> list[dict[str, str]]:
    """The articles in a research search answer that have an abstract: title, abstract and the
    address of the article itself. Authors and affiliations are left out."""
    data = json.loads(raw.decode("utf-8", errors="replace"))
    out: list[dict[str, str]] = []
    if kind == "europe_pmc":
        for item in (data.get("resultList") or {}).get("result") or []:
            abstract, source, ident = (
                _plain(item.get("abstractText")),
                item.get("source"),
                item.get("id"),
            )
            if abstract and source and ident:
                out.append(
                    {
                        "title": _plain(item.get("title")),
                        "abstract": abstract,
                        "url": f"https://europepmc.org/article/{source}/{ident}",
                    }
                )
    elif kind == "openalex":
        for item in data.get("results") or []:
            inverted = item.get("abstract_inverted_index") or {}
            places = sorted((at, word) for word, spots in inverted.items() for at in spots)
            abstract = _plain(" ".join(word for _, word in places))
            url = item.get("doi") or item.get("id")
            if abstract and url and str(url).startswith("https://"):
                out.append(
                    {"title": _plain(item.get("title")), "abstract": abstract, "url": str(url)}
                )
    elif kind == "doaj":
        for item in data.get("results") or []:
            bib = item.get("bibjson") or {}
            doi = next(
                (i.get("id") for i in bib.get("identifier") or [] if i.get("type") == "doi"), None
            )
            link = next((x.get("url") for x in bib.get("link") or [] if x.get("url")), None)
            url = f"https://doi.org/{doi}" if doi else link
            abstract = _plain(bib.get("abstract"))
            if abstract and url and str(url).startswith("https://"):
                out.append(
                    {"title": _plain(bib.get("title")), "abstract": abstract, "url": str(url)}
                )
    elif kind == "wikipedia":
        pages = (data.get("query") or {}).get("pages") or []
        for item in sorted(
            (p for p in pages if isinstance(p, dict)) if isinstance(pages, list) else [],
            key=lambda p: int(p.get("index") or 0),
        ):
            title, abstract = _plain(item.get("title")), _lines(str(item.get("extract") or ""))
            url = str(item.get("fullurl") or "")
            if abstract and title and url.startswith("https://en.wikipedia.org/wiki/"):
                out.append(
                    {
                        "title": title,
                        "abstract": abstract,
                        "url": url,
                        "full_text": WIKIPEDIA_PAGE.format(title=quote_plus(title)),
                    }
                )
    return out[:MAX_ARTICLES_PER_SEARCH]


def wikipedia_text(raw: bytes) -> str:
    """The plain text of one article from its full-text answer, or nothing."""
    pages = (json.loads(raw.decode("utf-8", errors="replace")).get("query") or {}).get("pages")
    first = pages[0] if isinstance(pages, list) and pages else {}
    return _lines(str(first.get("extract") or "")) if isinstance(first, dict) else ""


def _result_kind(brief: dict[str, Any], url: str) -> str | None:
    """How to read this search address's answer, for a source the brief marks as a research search."""
    host = urlsplit(url).hostname
    for api in (brief.get("fetch") or {}).get("apis") or []:
        if api.get("results") and api.get("host") == host:
            return str(api["results"])
    return None


def _fetch_again(fetcher: Fetcher, url: str) -> Fetched:
    """One fetch, asked once more after a short wait: public search services drop calls now and
    then, and one dropped call shouldn't cost a nonprofit its answer. A refused address isn't asked
    again."""
    try:
        return fetcher(url)
    except SourceRefused:
        raise
    except (RuntimeError, ValueError):
        time.sleep(FETCH_RETRY_SECONDS)
        return fetcher(url)


def _names_an_ip(url: str) -> bool:
    try:
        ipaddress.ip_address(urlsplit(url).hostname or "")
    except ValueError:
        return False
    return True


def clean_phrases(value: Any) -> list[str]:
    """The search phrases a maker's output may carry: plain words only, few and short. Anything
    else is left out. They only ever fill the query of an allowlisted search, URL-encoded."""
    out: list[str] = []
    for item in value if isinstance(value, list) else []:
        phrase = " ".join(str(item).split()) if isinstance(item, str) else ""
        if (
            phrase
            and len(phrase) <= MAX_PHRASE_CHARS
            and _PLAIN_PHRASE.fullmatch(phrase)
            and phrase.lower() not in [p.lower() for p in out]
        ):
            out.append(phrase)
    return out[:MAX_SEARCH_PHRASES]


def phrase_urls(brief: dict[str, Any], phrases: list[str]) -> list[tuple[str, str, str | None]]:
    """(url, access, publisher) for a second search: each phrase on each research search the brief
    already permits, and nothing else. A brief with no research search searches nothing."""
    apis = [a for a in (brief.get("fetch") or {}).get("apis") or [] if a.get("results")]
    return [
        (
            api_query_url(api, [phrase]),
            str(api.get("access") or "official_api"),
            api.get("publisher"),
        )
        for phrase in phrases
        for api in apis
    ]


def gather(
    brief: dict[str, Any],
    fetcher: Fetcher,
    *,
    phrases: list[str] | None = None,
    known_urls: frozenset[str] = frozenset(),
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch every permitted source once; failures are kept as reasons, never hidden. A research
    search becomes one source per article, each citing the article's own address. With `phrases`,
    it runs those searches instead of the brief's sources, numbered apart from them, leaving out
    articles already in `known_urls`."""
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    fetch_rules = brief.get("fetch") or {}
    number = PHRASE_NUMBERS_FROM if phrases else 0
    seen = set(known_urls)

    def keep(
        fetched: Fetched, access: str, publisher: str | None, title: str | None = None
    ) -> None:
        nonlocal number
        number += 1
        record = source_record(
            fetched,
            source_id=f"SRC-{brief['report_id']}-{number}",
            access=access,
            publisher=publisher,
            max_text_chars=int(fetch_rules.get("max_text_chars") or 60000),
            request_id=str(brief["request_id"]),
            part=brief.get("part"),
        )
        if title:
            record["title"] = title[:300]
        if record["text"].strip():
            records.append(record)
        else:
            failures.append(f"source {number}: no text could be extracted")

    addresses = phrase_urls(brief, phrases) if phrases else permitted_urls(brief)
    for index, (url, access, publisher) in enumerate(addresses, start=1):
        try:
            fetched = _fetch_again(fetcher, url)
        except (SourceRefused, RuntimeError, ValueError) as exc:
            failures.append(f"source {index}: {exc}")
            continue
        kind = _result_kind(brief, url)
        if not kind:
            keep(fetched, access, publisher)
            continue
        try:
            articles = search_articles(kind, fetched.raw)
        except (ValueError, AttributeError, TypeError) as exc:
            failures.append(f"source {index}: its answer could not be read: {exc}")
            continue
        if not articles:
            failures.append(f"source {index}: its search found no articles with an abstract")
        for article in articles:
            if article["url"] in seen or _names_an_ip(article["url"]):
                continue
            seen.add(article["url"])
            abstract = article["abstract"]
            if article.get("full_text"):
                # When the full text can't be read, the opening the search gave still counts.
                with contextlib.suppress(
                    SourceRefused, RuntimeError, ValueError, AttributeError, TypeError
                ):
                    abstract = (
                        wikipedia_text(_fetch_again(fetcher, article["full_text"]).raw) or abstract
                    )
            page = replace(
                fetched,
                url=article["url"],
                final_url=article["url"],
                content_type="text/plain",
                raw=(article["title"].rstrip(".") + ".\n" + abstract).encode("utf-8"),
            )
            keep(page, access, publisher, article["title"])
    return records, failures


# A sentence a reader can act on: a number with its unit (a temperature, a time, a size, an
# amount), a time limit, or who is protected or required to do what. General, not tied to a topic.
_UNIT = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:\u00b0\s*[fc]\b|degrees?\b|percent\b|%|hours?\b|minutes?\b|days?\b|"
    r"weeks?\b|months?\b|years?\b|seconds?\b|inch(?:es)?\b|feet\b|foot\b|pounds?\b|lbs?\b|"
    r"ounces?\b|oz\b|gallons?\b|quarts?\b|miles?\b|dollars?\b)|\$\s?\d|\b\d+\s*\u00b0",
    re.IGNORECASE,
)
_LIMIT = re.compile(
    r"\b(?:within|no (?:more|later|longer) than|at (?:least|most)|up to|until)\s+\$?\d",
    re.IGNORECASE,
)
_DUTY = re.compile(
    r"\b(?:must|shall|required|requires|requirement|may not|prohibited|liable|liability|"
    r"protects?|protected|protection|immune|immunity|exempt)\b",
    re.IGNORECASE,
)


def specificity(sentence: str) -> int:
    """How much a sentence says that a reader can act on (0 to 3): a number with a unit counts
    two, a time limit one, and who is protected or required to do what one."""
    return min(
        3,
        2 * bool(_UNIT.search(sentence))
        + bool(_LIMIT.search(sentence))
        + bool(_DUTY.search(sentence)),
    )


def candidate_sentences(
    sources: list[dict[str, Any]], question: str, limit: int
) -> list[dict[str, Any]]:
    """Numbered sentences that share words with the question, at most 12 per source, taken from
    every source in turn (each one's best first)."""
    wanted = words(subject_text(question))
    picked: list[tuple[int, int, int, dict[str, Any]]] = []
    for s_index, source in enumerate(sources, start=1):
        scored = []
        position = 0
        seen: set[str] = set()
        for sentence in standalone_sentences(str(source["text"])):
            position += 1
            if not 40 <= len(sentence) <= 400 or len(sentence.split()) < 6:
                continue
            if sentence in seen or not sentence.rstrip("\"')").endswith((".", "!", "?")):
                continue  # headings and repeated lines are not claims
            seen.add(sentence)
            overlap = len(wanted & words(sentence))
            if overlap:  # it must share a word with the question; then specific ones rank higher
                scored.append((overlap + specificity(sentence), position, sentence))
        scored.sort(key=lambda item: (-item[0], item[1]))
        for rank, (overlap, position, sentence) in enumerate(scored[:12]):
            picked.append(
                (
                    overlap,
                    s_index,
                    position,
                    {"source": source["id"], "s": s_index, "text": sentence, "rank": rank},
                )
            )
    # Every source gets its turn: each source's best sentence first, then each one's second best,
    # and so on, so one long page cannot crowd the others out of the model's view (the review's S2:
    # the film's question once gave the model sentences from three of its five sources).
    picked.sort(key=lambda item: (item[3]["rank"], -item[0], item[1], item[2]))
    chosen = sorted(picked[:limit], key=lambda item: (item[1], item[2]))
    counters: dict[int, int] = {}
    out = []
    for _, s_index, _, entry in chosen:
        counters[s_index] = counters.get(s_index, 0) + 1
        out.append({**entry, "id": f"S{s_index}-{counters[s_index]}"})
    return out


def prompt_text(
    rules: dict[str, Any],
    question: str,
    sentences: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    persona: str | None = None,
) -> tuple[str, str]:
    research = rules.get("research") or {}
    system = "\n".join(research.get("prompt") or []).replace(
        "{max_claims}", str(research.get("max_claims") or 8)
    )
    if (
        persona
    ):  # the variant's persona: a reviewed, recorded prompt (eranos.instructions/worker.policy)
        system += "\n\nHow to work: " + persona
    titles = {s["id"]: s.get("title") or s.get("publisher") for s in sources}
    lines = [f"Question: {question}", "", "Sentences:"]
    lines += [f"[{s['id']}] ({titles.get(s['source'])}) {s['text']}" for s in sentences]
    return system, "\n".join(lines)


def check_claims(
    proposed: Any,
    sentences: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    rules: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Keep a proposed claim only when its words come from the sentence it cites.

    The model cites a numbered sentence; the quote is that sentence, copied by code from the
    fetched source, so it is verbatim by construction (a quote the model typed is ignored). The
    claim stays the model's own words and must rest on the quote.
    """
    research = rules.get("research") or {}
    overlap_needed = float(research.get("support_overlap") or 0.5)
    by_id = {s["id"]: s for s in sentences}
    texts = {s["id"]: str(s["text"]) for s in sources}
    items = proposed.get("claims") if isinstance(proposed, dict) else None
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            dropped.append({"sentence": "?", "reason": "not an object"})
            continue
        sid = str(item.get("sentence") or "").strip().strip("[]")
        claim = " ".join(str(item.get("claim") or "").split())
        entry = by_id.get(sid)
        if entry is None:
            dropped.append({"sentence": "?", "reason": "names no numbered sentence"})
            continue
        source_id = entry["source"]
        quote = " ".join(str(entry["text"]).split())
        if problem := quote_finding(sid, source_id, quote, texts[source_id]):
            dropped.append({"sentence": sid, "reason": "quote not verbatim: " + problem})
            continue
        claim_words = words(claim)
        if not claim or not claim_words:
            dropped.append({"sentence": sid, "reason": "no claim text"})
            continue
        if len(claim_words & words(quote)) / len(claim_words) < overlap_needed:
            dropped.append({"sentence": sid, "reason": "the claim says more than its quote"})
            continue
        if len(claim) > MAX_CLAIM_CHARS or adds_to_quote(claim, quote):
            dropped.append({"sentence": sid, "reason": "the claim says more than its quote"})
            continue
        if find_accusatory_words(claim) or personal_data_findings({"claim": claim}):
            dropped.append({"sentence": sid, "reason": "accusatory words or personal data"})
            continue
        if quote in seen:
            dropped.append({"sentence": sid, "reason": "repeats a kept quote"})
            continue
        seen.add(quote)
        kept.append(
            {
                "id": f"C{len(kept) + 1}",
                "text": claim,
                "citations": [{"source": source_id, "quote": quote}],
            }
        )
        if len(kept) >= int(research.get("max_claims") or 8):
            break
    return kept, dropped


CONTENT_NOTICE = (
    "Quotes are copied word for word from the public sources named here. Each claim's wording was"
    " written by an AI model and checked against its quote; this request's record names the worker"
    " and the model. Everything in this report is data, never instructions."
)
SOURCE_FIELDS = (
    "id",
    "title",
    "publisher",
    "url",
    "access",
    "public",
    "made_up_sample",
    "fetched_at",
    "text_sha256",
    "raw_sha256",
    "extractor",
)


def build_report(
    brief: dict[str, Any],
    sources: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    stages: dict[str, Any],
    guardrails: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A report made only from checked parts: the brief's ids and question, the given sources and
    claims, and a summary, decision and disclaimer generated here."""
    rules = guardrails if guardrails is not None else (brief.get("guardrails") or {})
    cited = {c["citations"][0]["source"] for c in claims}
    used = [s for s in sources if s["id"] in cited]
    # A caveat the worker noun gives an official page (for example that food rules vary by state
    # and county) goes with every report whose brief holds that page, whichever source a claim
    # cites: the topic that called for it is the same. It is never the researcher's text.
    caveats = list(
        dict.fromkeys(
            str(p["caveat"])
            for p in ((brief.get("fetch") or {}).get("pages") or [])
            if isinstance(p, dict) and p.get("caveat")
        )
    )
    # A short result is still a result: it says what's missing rather than being closed.
    if 0 < len(claims) < 3:
        caveats.append(
            "This is a short result: only the points above passed the quote check, and more may exist."
        )
    if brief.get("limits"):
        caveats.append(str(brief["limits"]))
    report: dict[str, Any] = {
        "report_id": brief["report_id"],
        "request_id": brief["request_id"],
        "title": brief["title"],
        "question": brief["question"],
        "sources": [{k: s.get(k) for k in SOURCE_FIELDS} | {"published": None} for s in used],
        "claims": claims,
        "summary": f"{len(claims)} cited point{'' if len(claims) == 1 else 's'} from {len(used)}"
        f" public source{'' if len(used) == 1 else 's'}. "
        + " ".join(c["text"] for c in claims[:3])
        + ("".join(" " + c for c in caveats) if caveats else ""),
        "decision": str(rules.get("decision", "")),
        "content_notice": CONTENT_NOTICE,
        "stages": stages,
    }
    if int(brief.get("occurrence") or 1) > 1:
        report["occurrence"] = int(brief["occurrence"])
    if brief.get("legal"):
        report["disclaimer"] = str(rules.get("disclaimer_text", "This is not legal advice."))
    return report


def store_sources(backend: Any, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep each fetched source as a noun for provenance (surface-only: the public report quotes it)."""
    refs = []
    for source in sources:
        try:
            version = backend.get_record(SOURCES_STORE, source["id"]).version
        except NotFound:
            version = 0
        saved = backend.put_record(
            SOURCES_STORE,
            source["id"],
            source,
            expected_version=version,
            producer_surface=PRODUCER,
            visibility_scope="surface_only",
            tags=["kind:source_observation", "access:" + str(source["access"])],
        )
        refs.append({"store": SOURCES_STORE, "key": source["id"], "version": int(saved.version)})
    return refs


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_ADDRESS = re.compile(r"https?://\S+|www\.\S+|\b[\w-]{2,}\.[a-z]{2,}\b(?:/\S*)?", re.IGNORECASE)
_NEGATION = re.compile(
    r"\b(?:not|never|no(?! more| later| longer| fewer| less)|none|without|cannot|avoid|stop|refuse|prohibit\w*|forbid\w*|\w+n't|\w+n\u2019t)\b",
    re.IGNORECASE,
)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(text)}


def adds_to_quote(claim: str, quote: str) -> bool:
    """A claim's wording may be the model's; its figures, web addresses and negation may not: every
    number and address must be in the quote, and a quote that opens with "never" stays negative."""
    opening, head = _NEGATION.search(quote), len(" ".join(quote.split()[:6]))
    return (
        bool(_numbers(claim) - _numbers(quote))
        or any(a.lower().rstrip(".,;)") not in quote.lower() for a in _ADDRESS.findall(claim))
        or bool(opening and opening.start() < head and not _NEGATION.search(claim))
    )


_ABBREVIATED = re.compile(r"(?:\b[A-Z]\.|\b(?:e\.g|i\.e|etc|vs|Dr|Mr|Mrs|Ms|No|St|Inc|Co|cf)\.)$")
_CUT_OFF_LINE = re.compile(r"(?::|\b(?:not|never|no|don't|do not|must not|cannot))$", re.IGNORECASE)


def standalone_sentences(text: str) -> list[str]:
    """The sentences a claim may quote, in order. A piece that may have lost its start isn't one: it
    starts in lowercase, follows an abbreviation ("the U.S. states..."), or follows a line that
    ends in a colon or a "never", so a quote can't drop the word that gives a sentence its meaning."""
    out: list[str] = []
    before = ""
    for line in text.split("\n"):
        for piece in _SENTENCE.split(line):
            piece = piece.strip()
            cut = _ABBREVIATED.search(before) or _CUT_OFF_LINE.search(before)
            if piece and not cut and not piece[0].islower():
                out.append(piece)
            if piece:
                before = piece
    return out


def whole_sentences(text: str) -> set[str]:
    return {" ".join(piece.split()) for piece in standalone_sentences(text)}


def on_subject(claim: dict[str, Any], sources: list[dict[str, Any]], question: str) -> bool:
    """A claim from a search in other words still has to be about the question: its quote or its
    article's title shares a word with it. Search phrases choose where to look, never the subject."""
    wanted = words(subject_text(question))
    citation = claim["citations"][0]
    title = next((str(s.get("title") or "") for s in sources if s["id"] == citation["source"]), "")
    return bool(wanted & (words(str(citation["quote"])) | words(title)))


def _model_id(model: Any) -> str:
    described = model.describe() if hasattr(model, "describe") else {}
    return str((described or {}).get("id") or "")


def search_round(
    model: ChatModel,
    brief: dict[str, Any],
    question: str,
    research: dict[str, Any],
    fetcher: Fetcher,
    meter: UsageMeter,
    sources: list[dict[str, Any]],
    tried: list[str],
) -> tuple[list[str], list[dict[str, Any]], list[str]] | None:
    """One more search in the model's words: (phrases, new sources, failures); None when it gave
    no new usable phrase or the brief has no research search to run them on."""
    if not phrase_urls(brief, ["x"]):
        return None
    user = f"Question: {subject_text(question)}"
    if tried:
        user += "\nAlready searched, with nothing useful: " + "; ".join(tried)
    asked = model.chat_json(
        "\n".join(research.get("search_prompt") or []),
        user,
        meter=meter,
        temperature=0.0,
        seed=20261104,
    )
    wanted = clean_phrases(asked.get("searches") if isinstance(asked, dict) else None)
    phrases = [p for p in wanted if p.lower() not in [t.lower() for t in tried]]
    if not phrases:
        return None
    more, lost = gather(
        brief,
        fetcher,
        phrases=phrases,
        known_urls=frozenset(str(s["url"]) for s in sources),
    )
    return phrases, more, lost


def do_research(
    backend: Any,
    lease: Any,
    *,
    fetcher: Fetcher,
    model: ChatModel,
    meter: UsageMeter,
    worker_rules: dict[str, Any],
    variant: dict[str, Any] | None = None,
    escalate: ChatModel | None = None,
    second_look: bool = True,
) -> dict[str, Any]:
    """The builder's research work: {output, self_test, artifact_refs, summary}. `variant` is the
    tuned pick (persona, effort, temperature); its id and model go in the output as `made_with`.
    `escalate` is the stronger model that gets a turn when `model` keeps no claim, and `second_look`
    says whether this maker's search phrases would be repeated by a reviewer at all."""
    variant = variant or {}
    persona = (
        (variant.get("persona") or {}).get("text")
        if isinstance(variant.get("persona"), dict)
        else None
    )
    brief = dict(lease.brief)
    research = worker_rules.get("research") or {}
    sources, failures = gather(brief, fetcher)
    question = str(brief["question"])
    limit = int(research.get("candidate_sentences") or 30)
    sentences = candidate_sentences(sources, question, limit)
    refs = store_sources(backend, sources) if sources else []
    # The first attempt samples at the variant's temperature; a retried verb samples a little
    # more widely, with a different seed, so it does not repeat the same failure. Both are in
    # the execution report.
    attempt = max(1, int(getattr(lease, "attempt", 1) or 1))
    base = float(variant.get("temperature") or 0.0)
    temperature = base if attempt == 1 else max(base, min(0.6, 0.2 * attempt))
    effort = variant.get("reasoning_effort")

    def ask(using: ChatModel, among: list[dict[str, Any]], seen: list[dict[str, Any]]) -> Any:
        system, user = prompt_text(worker_rules, question, among, seen, persona)
        return using.chat_json(
            system,
            user,
            meter=meter,
            temperature=temperature,
            seed=20261031 + attempt - 1,
            reasoning_effort=effort,
        )

    proposed: Any = ask(model, sentences, sources) if sentences else {}
    claims, dropped = check_claims(proposed, sentences, sources, worker_rules)
    search_again: dict[str, Any] = {}
    if not claims and second_look and research.get("search_prompt"):
        # Nothing the first search found answers the question. The model may say so; it may also
        # look again, in other words, on the same permitted searches. From the second attempt a
        # stronger model gets one turn too. Every claim still rests on a sentence copied by code
        # from a source, and the reviewer runs the same searches itself.
        rounds: list[ChatModel] = [model]
        if escalate is not None and escalate is not model and attempt >= 2:
            rounds.append(escalate)
        tried: list[str] = []
        records: list[dict[str, Any]] = []
        for using in rounds:
            record: dict[str, Any] = {"model": _model_id(using)}
            records.append(record)
            try:
                found = search_round(
                    using, brief, question, research, fetcher, meter, sources, tried
                )
                if found is None:
                    record["phrases"] = []
                    continue
                phrases, more, lost = found
                tried += phrases
                all_sources = sources + more
                among = candidate_sentences(all_sources, f"{question} {' '.join(phrases)}", limit)
                record.update(
                    phrases=phrases, fetched=len(more), failed=lost[:10], candidates=len(among)
                )
                answer: Any = ask(using, among, all_sources) if among else {}
            except (ModelUnavailable, RuntimeError, ValueError, TypeError, AttributeError) as exc:
                record["error"] = type(exc).__name__  # its kind only: a message can carry spend
                continue
            checked_claims, found_dropped = check_claims(answer, among, all_sources, worker_rules)
            dropped += found_dropped
            found_claims: list[dict[str, Any]] = []
            for claim in checked_claims:
                if on_subject(claim, all_sources, question):
                    found_claims.append({**claim, "id": f"C{len(found_claims) + 1}"})
                else:
                    dropped.append({"sentence": claim["id"], "reason": "not about the question"})
            record["kept"] = len(found_claims)
            if found_claims:
                claims, sentences, proposed = found_claims, among, answer
                cited = {c["citations"][0]["source"] for c in claims}
                refs += store_sources(backend, [m for m in more if m["id"] in cited])
                sources = all_sources
                search_again = {
                    "phrases": phrases,
                    "model": record["model"],
                    "kept": len(claims),
                }
                if using is not model:
                    search_again["escalated"] = True
                    variant = {**variant, "model": record["model"]}
                break
        search_again["rounds"] = records
    stages = {
        "fetch": {
            "permitted": len(permitted_urls(brief)),
            "fetched": len(sources),
            "failed": failures,
        },
        "candidates": len(sentences),
        "proposed": len((proposed or {}).get("claims") or []) if isinstance(proposed, dict) else 0,
        # "no_claims": the model answered with an empty list; the tuner charges that to a variant
        # only when another attempt on the same part found claims (FB1-024).
        "answer": "no_call"
        if not sentences and not any(r.get("candidates") for r in search_again.get("rounds") or [])
        else "no_claims"
        if not sentences
        else "claims"
        if isinstance(proposed, dict) and proposed.get("claims")
        else "no_claims"
        if isinstance(proposed, dict) and isinstance(proposed.get("claims"), list)
        else "unparsed",
        "kept": len(claims),
        "dropped": dropped[:20],
        **({"search_again": search_again} if search_again else {}),
    }
    report = build_report(brief, sources, claims, stages)
    checked = {**brief, "sources": sources}
    issues = report_findings(report, checked)
    minimum = int(research.get("min_claims") or 3)
    if len(claims) < minimum:
        issues.append(
            f"only {len(claims)} claims kept a verbatim quote; at least {minimum} are needed"
        )
    return {
        "output": {
            "node": "report",
            "report": report,
            "blob_sha256": report_digest(report),
            "draft": {"kit_id": brief["report_id"], "kind": "public_report"},
            "verification": {"passed": not issues, "issues": issues},
            **(
                {"made_with": {"variant": variant["id"], "model": variant.get("model")}}
                if variant.get("id")
                else {}
            ),
        },
        "self_test": {"passed": not issues, "issues": issues},
        "artifact_refs": refs,
        "summary": {
            "sources": len(report["sources"]),
            "claims": len(claims),
            "dropped": len(dropped),
            **({"made_by_model": search_again["model"]} if search_again.get("escalated") else {}),
        },
    }


OUTPUT_KEYS = frozenset(
    {"node", "report", "blob_sha256", "draft", "verification", "status", "self_test", "made_with"}
)
REPORT_KEYS = frozenset(
    {
        "report_id",
        "request_id",
        "title",
        "question",
        "sources",
        "claims",
        "summary",
        "decision",
        "disclaimer",
        "stages",
        "occurrence",
        "content_notice",
    }
)
CLAIM_KEYS = frozenset({"id", "text", "citations"})
CITATION_KEYS = frozenset({"source", "quote"})
REPORT_SOURCE_KEYS = frozenset({*SOURCE_FIELDS, "published"})
MAX_CLAIM_CHARS = 300


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def shape_findings(output: dict[str, Any]) -> list[str]:
    """Unknown fields are refused, never passed on: a research output is data from a stranger."""
    out: list[str] = []

    def unknown(where: str, value: Any, allowed: frozenset[str]) -> None:
        if not isinstance(value, dict):
            out.append(f"{where} must be an object")
        elif extra := sorted(set(value) - allowed):
            # A stranger chooses these names, so public records give only how many.
            out.append(f"{where} has {len(extra)} field(s) this review does not accept")

    unknown("the research output", output, OUTPUT_KEYS)
    report = output.get("report")
    unknown("the report", report, REPORT_KEYS)
    if isinstance(report, dict):
        for name in ("sources", "claims"):
            if not isinstance(report.get(name), list):
                out.append(f"the report's {name} must be a list")
        for source in _items(report.get("sources")):
            unknown("a source", source, REPORT_SOURCE_KEYS)
        for claim in _items(report.get("claims")):
            unknown("a claim", claim, CLAIM_KEYS)
            for citation in _items(claim.get("citations")) if isinstance(claim, dict) else []:
                unknown("a citation", citation, CITATION_KEYS)
    return out


def ensure_delivered(
    backend: Any,
    *,
    report: dict[str, Any],
    request_id: str,
    part: Any,
    review_task_id: str,
    review_receipt: str,
    research_receipt: str | None,
) -> dict[str, Any]:
    """Deliver an approved report once: a repeated call finds it delivered and changes nothing."""
    try:
        current = backend.get_record(SOLUTIONS_STORE, str(report["report_id"]))
        if current.value.get("review_receipt") == review_receipt:
            return {
                "report_id": report["report_id"],
                "solution_version": current.version,
                "already": True,
            }
    except NotFound:
        pass
    return deliver_report(
        backend,
        report=report,
        request_id=request_id,
        review_task_id=review_task_id,
        review_receipt=review_receipt,
        research_receipt=research_receipt,
        digest=report_digest(report),
        part=part,
    )


DRAFTS_STORE = "eranos.drafts"
NOT_AUDITED = "not_audited_yet"


def save_unaudited(
    backend: Any,
    report: dict[str, Any],
    *,
    request_id: str,
    part: Any,
    maker_receipt: str,
    deliver: bool,
) -> None:
    """The maker's report, readable at once and labeled: a different worker has not checked it yet.
    It's always kept as a draft; a request that asked for unaudited results also gets it as its result."""
    report_id = str(report["report_id"])
    value = {
        "schema_version": 1,
        "request_id": request_id,
        "part": part,
        "report": report,
        "report_sha256": report_digest(report),
        "research_receipt": maker_receipt,
        "audit_status": NOT_AUDITED,
        "next_step": "A different worker hasn't checked this yet. A person at the nonprofit decides what to use.",
    }
    for store in (DRAFTS_STORE, SOLUTIONS_STORE) if deliver else (DRAFTS_STORE,):
        try:
            current = backend.get_record(store, report_id)
            version = current.version
            if store == SOLUTIONS_STORE and (current.value or {}).get("audit_status") == "audited":
                continue
        except NotFound:
            version = 0
        backend.put_record(
            store,
            report_id,
            value,
            expected_version=version,
            producer_surface=PRODUCER,
            visibility_scope="public_commons",
            tags=["state:not_audited_yet", "kind:public_report"],
        )
    if deliver:
        update_request_part(backend, request_id, part, "delivered_unaudited", report_id=report_id)


def mark_audit_failed(backend: Any, report_id: str, findings: list[str]) -> None:
    """A result already shown before its audit now says the audit didn't pass, and why."""
    for store in (SOLUTIONS_STORE, DRAFTS_STORE):
        try:
            current = backend.get_record(store, report_id)
        except NotFound:
            continue
        if (current.value or {}).get("audit_status") != NOT_AUDITED:
            continue
        backend.put_record(
            store,
            report_id,
            {**current.value, "audit_status": "audit_failed", "audit_findings": findings},
            expected_version=current.version,
            producer_surface=PRODUCER,
            visibility_scope="public_commons",
            tags=["state:audit_failed", "kind:public_report"],
        )


def review_research(
    backend: Any,
    lease: Any,
    *,
    worker: str,
    key_id: str,
    fetcher: Fetcher,
    worker_rules: dict[str, Any],
    guardrails: dict[str, Any],
    checker: Callable[[str, list[dict[str, Any]]], dict[str, Any]] | None = None,
    trusted_makers: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Rebuild the report from this reviewer's own checks, then approve and deliver it, or send it back.

    After the deterministic re-fetch and quote check, `checker` (the tuned model check) judges
    whether each kept quote supports its claim; it can only remove claims, never add words, and a
    claim either check finds unsupported is dropped. Its record (variants, unsupported claim ids,
    cost, time) is returned as `model_check` for the request's facts.

    The delivered report is made only from the planner's brief (ids, title, question), this
    reviewer's own fetch of the permitted sources, and the claims whose quotes pass against that
    fetch; its summary, decision and disclaimer are generated here. Nothing else the researcher
    wrote is passed on, and an output with fields this review does not know is refused.

    A maker's search phrases are repeated only for `trusted_makers`, our own dedicated keys: words
    from an outsider would let it choose an article (anyone can edit an encyclopedia) for a real
    nonprofit's answer, so an outsider's second-look claims find no article here and are dropped.
    """
    research = lease.dependencies[0]
    brief = dict(lease.brief)
    request_id, report_id = str(brief["request_id"]), str(brief["report_id"])
    part = brief.get("part")
    ref = f"{lease.task_id}:{lease.fencing_token}"
    researcher = getattr(research, "completed_by_key", None)
    if research.state != "done" or not isinstance(research.output, dict):
        receipt = backend.submit(
            lease.task_id,
            lease.fencing_token,
            {
                "node": "report_review",
                "status": "nothing_to_review",
                "report_id": report_id,
                "research_state": research.state,
            },
            idempotency_key=ref,
            ok=True,
        )
        update_request_part(
            backend,
            request_id,
            part,
            "needs_revision",
            findings=["the research verb did not finish"],
        )
        return {
            "status": "nothing_to_review",
            "receipt": receipt.receipt_hash,
            "reason": f"the research verb ended {research.state}",
        }
    if not key_id.strip() or not researcher or researcher == key_id:
        backend.submit(
            lease.task_id,
            lease.fencing_token,
            {"node": "report_review", "status": "rejected_self_review", "report_id": report_id},
            idempotency_key=ref,
            ok=False,
            error="the worker that researched a report may not review it",
        )
        raise SelfReviewRefused(f"reviewer key {key_id!r} researched {report_id}")
    output = dict(research.output)
    findings = shape_findings(output)
    found = output.get("report")
    report: dict[str, Any] = found if isinstance(found, dict) else {}
    if output.get("blob_sha256") != report_digest(found):
        findings.append("blob_sha256 is not the digest of the submitted report")
    draft, verification = output.get("draft") or {}, output.get("verification") or {}
    if (
        not isinstance(draft, dict)
        or draft.get("kit_id") != report_id
        or not isinstance(verification, dict)
        or verification.get("passed") is not True
    ):
        findings.append(
            "the research output does not carry the draft fields the server's review proof checks"
        )
    research_rules = worker_rules.get("research") or {}
    overlap_needed = float(research_rules.get("support_overlap") or 0.5)
    # A research search's own address is never citable: its answer holds text the article reader
    # leaves out on purpose, such as authors' details. Only an article it returned can be cited.
    permitted = [p for p in permitted_urls(brief) if not _result_kind(brief, p[0])]
    numbered = {
        url: (DIRECT_NUMBERS_FROM + n, access, publisher)
        for n, (url, access, publisher) in enumerate(permitted, start=1)
    }
    source_ids = [str(s.get("id")) for s in _items(report.get("sources")) if isinstance(s, dict)]
    if len(set(source_ids)) != len(source_ids):
        findings.append("two sources in the report share an id")
    claimed_urls = {
        str(s.get("id")): str(s.get("url") or "")
        for s in _items(report.get("sources"))
        if isinstance(s, dict)
    }
    fresh: dict[str, dict[str, Any]] = {}
    fetch_failures: list[str] = []
    # A research search answers with articles: this reviewer runs the same searches itself, and a
    # claim may cite only an article that its own search returned, with the quote in that text.
    if any(api.get("results") for api in (brief.get("fetch") or {}).get("apis") or []):
        searched, search_failures = gather(brief, fetcher)
        # A maker that looked again says in which words; this reviewer runs those same searches on
        # the same permitted services. The words choose where to look, never what a source says.
        stages_in = report.get("stages") if isinstance(report.get("stages"), dict) else {}
        again = stages_in.get("search_again") if isinstance(stages_in, dict) else None
        phrases = clean_phrases(again.get("phrases") if isinstance(again, dict) else None)
        if researcher not in trusted_makers:
            phrases = []
        if phrases:
            more, more_failures = gather(
                brief,
                fetcher,
                phrases=phrases,
                known_urls=frozenset(str(s["url"]) for s in searched),
            )
            searched, search_failures = searched + more, search_failures + more_failures
        fresh.update({str(s["url"]): s for s in searched})
        numbered.update(
            {str(s["url"]): (0, str(s["access"]), s.get("publisher")) for s in searched}
        )
        if not searched:
            findings.extend(f"the review's own search failed: {f}" for f in search_failures)
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, str]] = []
    seen: set[str] = set()
    claims = [c for c in _items(report.get("claims")) if isinstance(c, dict)]
    # Records name a claim by its place in the report: its id is a stranger's text.
    for place, claim in enumerate(claims[: int(research_rules.get("max_claims") or 8)], start=1):
        where = f"claim {place}"
        cited_list = _items(claim.get("citations"))
        citation = cited_list[0] if cited_list else None
        if not isinstance(citation, dict):
            dropped.append({"claim": where, "reason": "no citation"})
            continue
        url = claimed_urls.get(str(citation.get("source")), "")
        if url not in numbered:
            dropped.append(
                {
                    "claim": where,
                    "reason": "cites a source the brief does not permit",
                }
            )
            continue
        if url not in fresh and url not in fetch_failures:
            number, access, publisher = numbered[url]
            try:
                fresh[url] = source_record(
                    fetcher(url),
                    source_id=f"SRC-{report_id}-{number}",
                    access=access,
                    publisher=publisher,
                    max_text_chars=int((brief.get("fetch") or {}).get("max_text_chars") or 60000),
                    request_id=request_id,
                    part=part,
                )
            except (SourceRefused, RuntimeError, ValueError) as exc:
                fetch_failures.append(url)
                findings.append(f"a cited source could not be fetched again: {exc}")
        record = fresh.get(url)
        if record is None:
            dropped.append({"claim": where, "reason": "its source could not be fetched again"})
            continue
        quote = " ".join(str(citation.get("quote") or "").split())
        text = " ".join(str(claim.get("text") or "").split())
        claim_words = words(text)
        if not on_subject(
            {"citations": [{"source": record["id"], "quote": quote}]},
            [record],
            str(brief.get("question") or ""),
        ):
            dropped.append({"claim": where, "reason": "not about the question"})
        elif problem := quote_finding(str(place), record["id"], quote, record["text"]):
            dropped.append({"claim": where, "reason": problem})
        elif quote not in whole_sentences(str(record["text"])):
            # A piece of a sentence can drop its "never"; our maker always quotes whole sentences.
            dropped.append({"claim": where, "reason": "the quote is not a whole sentence"})
        elif (
            not claim_words
            or len(text) > MAX_CLAIM_CHARS
            or len(claim_words & words(quote)) / len(claim_words) < overlap_needed
            or adds_to_quote(text, quote)
        ):
            dropped.append({"claim": where, "reason": "the claim says more than its quote"})
        elif find_accusatory_words(text) or personal_data_findings({"claim": text}):
            dropped.append({"claim": where, "reason": "accusatory words or personal data"})
        elif quote in seen:
            dropped.append({"claim": where, "reason": "repeats a kept quote"})
        else:
            seen.add(quote)
            kept.append(
                {
                    "id": f"C{len(kept) + 1}",
                    "text": text,
                    "citations": [{"source": record["id"], "quote": quote}],
                }
            )
    checked: dict[str, Any] | None = None
    if checker is not None and kept:
        checked = checker(str(brief.get("question") or ""), kept)
        second = checked.get("second") or {}
        unsupported = set(checked.get("unsupported") or []) | set(second.get("unsupported") or [])
        for claim_id in sorted(unsupported):
            dropped.append(
                {
                    "claim": claim_id,
                    "reason": "the model check found its quote does not support it or it doesn't help",
                }
            )
        kept = [c for c in kept if c["id"] not in unsupported]
    basis = {
        k: brief.get(k)
        for k in (
            "report_id",
            "request_id",
            "title",
            "question",
            "legal",
            "occurrence",
            "fetch",
            "limits",
        )
    }
    stages = {
        "reviewed": {
            "claims_submitted": len(claims),
            "kept": len(kept),
            "dropped": dropped[:20],
            "sources_fetched_again": len(fresh),
        }
    }
    if checked is not None:
        stages["reviewed"]["model_check"] = {
            "variant": checked.get("variant"),
            "unsupported": sorted(checked.get("unsupported") or []),
            **(
                {
                    "second": {
                        "variant": second.get("variant"),
                        "unsupported": sorted(second.get("unsupported") or []),
                    }
                }
                if second
                else {}
            ),
        }
    rebuilt = build_report(basis, list(fresh.values()), kept, stages, guardrails=guardrails)
    findings += report_findings(
        rebuilt, {**basis, "guardrails": guardrails, "sources": list(fresh.values())}
    )
    minimum = int(research_rules.get("min_claims") or 3)
    if len(kept) < minimum:
        findings.append(
            f"only {len(kept)} claims passed this review; at least {minimum} are needed"
        )
    rechecked = [{"id": r["id"], "text_sha256": r["text_sha256"]} for r in fresh.values()]
    if findings:
        receipt = backend.submit(
            lease.task_id,
            lease.fencing_token,
            {
                "node": "report_review",
                "status": "needs_revision",
                "report_id": report_id,
                "findings": findings[:20],
                "rechecked": rechecked,
            },
            idempotency_key=ref,
            ok=True,
        )
        update_request_part(backend, request_id, part, "needs_revision", findings=findings[:20])
        mark_audit_failed(backend, report_id, findings[:20])
        return {
            "status": "needs_revision",
            "findings": findings,
            "receipt": receipt.receipt_hash,
            "model_check": checked,
        }
    digest = report_digest(rebuilt)
    receipt = backend.submit(
        lease.task_id,
        lease.fencing_token,
        {
            "node": "report_review",
            "status": "accepted",
            "approved": True,
            "accepted": True,
            "review_task_id": lease.task_id,
            "draft_task_id": research.task_id,
            "drafter_key_id": researcher,
            "reviewer_key_id": key_id,
            "draft_sha256": output["blob_sha256"],
            "kit_id": report_id,
            "report_id": report_id,
            "part": part,
            "research_receipt": research.receipt_hash,
            "report": rebuilt,
            "report_sha256": digest,
            "rechecked": rechecked,
            "quotes_checked": len(kept),
        },
        idempotency_key=ref,
        ok=True,
    )
    delivered = ensure_delivered(
        backend,
        report=rebuilt,
        request_id=request_id,
        part=part,
        review_task_id=lease.task_id,
        review_receipt=receipt.receipt_hash,
        research_receipt=research.receipt_hash,
    )
    return {
        "status": "delivered",
        "receipt": receipt.receipt_hash,
        "rechecked": rechecked,
        "model_check": checked,
        **delivered,
    }
