"""The reuse key: a normalized description signature, computed with no model (0 tokens).

How it is computed (stable contract, `proc1`):

1. Lowercase the request description, fold accents, turn every non-letter or digit into a space.
2. Find the process class by its words (for example `tabular_cleaning` needs a word for a sheet,
   such as spreadsheet, sheet, csv, excel or list, and a word for cleaning, such as clean, tidy,
   fix, standardize, duplicate or format). No class means no key: the request is not a process
   this generator knows. When two classes fit, the first with an operation names the process.
   A request `handwritten_case_files` would refuse gets no key (`scan_request_problem`), so it can never
   match a real package.
3. Find the class's operations by synonym phrases (duplicates, double entries and dedupe all mean
   `dedupe`; date or dates means `dates`, phone, mobile or cell means `phones`; missing, blank or
   empty near contact, email, phone or fields means `missing_contact`). Steps every package of
   the class always has (profile the columns, write the report) are not part of the key.
4. Find the subjects (volunteer sign-ups, donors, members, participants, cases) by their words.
5. The key is `proc2-` plus the first 16 hex characters of SHA-256 over the canonical JSON
   {"class": ..., "operations": [sorted], "subjects": [sorted]}. The subject is part of the key, so
   a donor-list request never matches the volunteer sign-up package even with the same steps.

`match(request, stored)` says `exact` when the keys are equal, `superset` when the stored package
has the same class and subjects and every operation the request needs, plus more (reusable, with
the extra step turned off), and `none` otherwise. A wording change keeps the key; a change in what
the process must do, or for whom, changes it.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

KEY_VERSION = "proc2"

CLASSES: dict[str, dict[str, Any]] = {
    "tabular_cleaning": {
        "needs_all": [
            ("spreadsheet", "spreadsheets", "sheet", "sheets", "csv", "csvs", "excel", "xlsx", "workbook",
             "table", "tables", "list", "lists", "roster", "rosters", "export", "exports", "records",
             "google sheets", "sign up sheet", "signup sheet"),
            ("clean", "cleans", "cleaning", "cleanup", "clean up", "tidy", "tidies", "tidying", "fix", "fixes",
             "standardize", "standardise", "standardizes", "normalize", "normalise", "dedupe", "deduplicate",
             "duplicate", "duplicates", "format", "formats", "validate", "flag"),
        ],
        "operations": {
            "dedupe": ("duplicate", "duplicates", "dedupe", "de dupe", "deduplicate", "de duplicate",
                       "deduplication", "double entries", "double entry", "repeated rows", "repeated entries",
                       "same person twice", "repeats"),
            "dates": ("date", "dates", "date format", "date formats"),
            "phones": ("phone", "phones", "phone number", "phone numbers", "telephone", "mobile", "mobiles",
                       "cell", "cell numbers"),
            "missing_contact": ("missing", "blank", "blanks", "empty", "incomplete", "no email", "no phone",
                                "without contact", "lacking"),
        },
        "operation_context": {"missing_contact": ("contact", "contacts", "email", "emails", "phone", "phones",
                                                   "field", "fields", "details", "info", "information")},
    },
    "handwritten_case_files": {
        "needs_all": [
            ("handwritten", "handwriting", "hand written", "scanned", "scans", "scan", "photos of",
             "paper", "written notes", "notes written"),
            ("case file", "case files", "casefile", "casefiles", "file", "files", "page", "pages", "form",
             "forms", "statement", "statements", "notes", "records"),
        ],
        "operations": {
            "transcribe": ("read", "reads", "transcribe", "transcribes", "transcription", "type up", "ocr",
                           "digitize", "digitise", "text"),
            "summarize": ("summarize", "summarise", "summary", "summaries", "summarizes", "summarises"),
            "analyze": ("analyze", "analyse", "analysis", "analyzes", "analyses", "themes", "patterns",
                        "trends", "insights"),
        },
        "operation_context": {},
    },
}
SUBJECTS = {
    "volunteer_signups": ("volunteer", "volunteers", "sign up", "sign ups", "signup", "signups",
                          "registration", "registrations"),
    "donors": ("donor", "donors", "donation", "donations"),
    "members": ("member", "members", "membership"),
    "participants": ("client", "clients", "participant", "participants", "attendee", "attendees"),
    "cases": ("case", "cases", "caseworker", "case worker"),
}
# What a request must say before it gets the scan class's key. The class's words above are broad on purpose
# ("paper", "text", "file"), so a key needs these too.
SCAN_SOURCE = ("handwritten", "handwriting", "hand written", "scanned", "scans", "scan of", "photos of", "written notes",
               "notes written", "paper form", "paper forms", "paper file", "paper files", "paper record", "paper records",
               "paper notes", "paper page", "paper pages", "paper statement", "paper statements")
# A bare "read" can mean reading aloud, so it needs a sheet to read into or the shape of a form to read.
FORM_SHAPE = ("intake form", "intake forms", "case form", "case forms", "case file", "case files", "casefile", "casefiles")
TYPING = ("transcribe", "transcribes", "transcription", "type up", "ocr", "digitize", "digitise")
READING = ("read", "reads")
SHEET = ("spreadsheet", "spreadsheets", "sheet", "sheets", "csv", "excel", "xlsx", "table", "tables")
SCAN_REFUSALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("it reads scanned documents, not websites or links",
     ("website", "websites", "web site", "web sites", "web page", "web pages", "webpage", "webpages", "the web", "url", "urls",
      "link", "links", "hyperlink", "hyperlinks", "browser", "online", "internet", "crawl", "crawls", "scrape", "scrapes", "scraping")),
    ("it does not check computers for security problems",
     ("virus", "viruses", "antivirus", "anti virus", "malware", "ransomware", "vulnerability", "vulnerabilities",
      "security scan", "network scan", "port scan")),
    ("it never decides about a person; people make those decisions",
     ("qualifies", "qualify", "qualified", "qualifying", "eligibility", "eligible", "approve", "approves", "approval", "approvals",
      "deny", "denies", "denial", "reject", "rejects", "rejection", "prioritize", "prioritizes", "prioritise", "prioritises",
      "triage", "triages", "rank", "ranks", "ranking", "risk score", "decide who", "decide whether", "decide if", "decides who",
      "decides whether", "decides if", "who gets", "who should", "who can")),
    ("it sends nothing to an outside service or anyone else",
     ("upload", "uploads", "uploading", "send", "sends", "sending", "email", "emails", "emailing", "e mail", "share", "shares", "sharing",
      "post", "posts", "posting", "publish", "publishes", "sync", "syncs", "syncing", "api", "webhook", "portal", "crm", "salesforce",
      "hubspot", "airtable", "dropbox", "google drive", "google sheets", "onedrive", "one drive", "sharepoint", "to the cloud",
      "cloud service")),
    ("it never contacts anyone or submits anything; people do that",
     ("aloud", "out loud", "call", "calls", "calling", "call back", "reply", "replies", "replying", "submit", "submits", "submitting",
      "over the phone", "by phone", "on the phone", "phone them", "phone each", "phone every", "phone the", "phone our", "phone client",
      "phone clients", "fill them out", "fill it out", "fill out the form", "fill out the forms", "fill out forms")),
    ("it keeps a person's words as written and does not translate them", ("translate", "translates", "translation", "translating")),
)
# Words that say the opposite of a refusal: "never upload", "without sending", "a person approves", or name a kind of document: "call notes".
SCAN_ALLOWED_PHRASES = re.compile(r" (?:never|not|t|without|no) (?:send|sending|upload|uploading|share|sharing|email|emailing|post|posting"
                                  r"|call|calling|reply|replying|submit|submitting)(?= )"
                                  r"| call (?:notes?|logs?|sheets?)(?= )"
                                  r"| person (?:decides? (?:who|whether|if)|approves?|rejects?)(?= )")


def scan_request_problem(text: str, operations: list[str]) -> str | None:
    """Why the scan class must not answer this normalized text, or None when it honestly can."""
    if not operations:
        return None
    if operations != ["transcribe"]:
        return "it only moves readings into a spreadsheet; it does not summarize or analyze a person's words"
    stripped = SCAN_ALLOWED_PHRASES.sub(" ", text)
    for reason, phrases in SCAN_REFUSALS:
        if has(stripped, phrases):
            return reason
    if not has(text, SCAN_SOURCE):
        return "the request does not name scans or handwriting"
    if not (has(text, TYPING) or (has(text, READING) and (has(text, SHEET) or has(text, FORM_SHAPE)))):
        return "the request does not ask to type scans up or read them"
    return None


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " " + re.sub(r"\s+", " ", text).strip() + " "


def has(text: str, phrases: tuple[str, ...]) -> bool:
    return any(f" {phrase} " in text for phrase in phrases)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def key_for(process_class: str, operations: list[str], subjects: list[str]) -> str:
    body = canonical_json({"class": process_class, "operations": sorted(operations), "subjects": sorted(subjects)})
    return f"{KEY_VERSION}-" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def signature(description: str) -> dict[str, Any]:
    """The reuse signature of a request description; `key` is None when no class fits."""
    text = normalize(description)
    subjects = sorted(name for name, words in SUBJECTS.items() if has(text, words))
    fitting = [name for name, spec in CLASSES.items() if all(has(text, group) for group in spec["needs_all"])]
    if not fitting:
        return {"version": KEY_VERSION, "class": None, "operations": [], "subjects": subjects, "key": None,
                "text": "no known process class"}

    def class_operations(name: str) -> list[str]:
        spec = CLASSES[name]
        found_ops = []
        for op, words in spec["operations"].items():
            context = spec["operation_context"].get(op)
            if has(text, words) and (context is None or has(text, context)):
                found_ops.append(op)
        return sorted(found_ops)

    # The first fitting class with an operation names the process, so a later class still gets its turn when
    # an earlier one only matched on broad words and has nothing to do. A request that has a key never changes.
    found = next((name for name in fitting if class_operations(name)), fitting[0])
    operations = class_operations(found)
    problem = scan_request_problem(text, operations) if found == "handwritten_case_files" else None
    return {
        "version": KEY_VERSION,
        "class": found,
        "operations": operations,
        "subjects": subjects,
        "key": key_for(found, operations, subjects) if operations and not problem else None,
        "text": f"{found}: " + (" + ".join(operations) if operations else "no operations found") + (f"; {problem}" if problem else ""),
    }


def match(request: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    """Can a stored package answer this request? exact, superset (reusable) or none."""
    if (not request.get("key") or not stored.get("key") or request.get("class") != stored.get("class")
            or sorted(request.get("subjects") or []) != sorted(stored.get("subjects") or [])):
        return {"decision": "none", "score": 0.0, "extra_operations": []}
    want, have = set(request["operations"]), set(stored["operations"])
    score = round(len(want & have) / len(want | have), 3) if want | have else 0.0
    if request["key"] == stored["key"]:
        return {"decision": "exact", "score": 1.0, "extra_operations": []}
    if want <= have:
        return {"decision": "superset", "score": score, "extra_operations": sorted(have - want)}
    return {"decision": "none", "score": score, "extra_operations": []}
