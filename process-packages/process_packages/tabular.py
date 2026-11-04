"""Process class `tabular_cleaning`: clean spreadsheet exports (CSV or TSV) with the tested runner.

Everything here is deterministic. Each plan piece maps to the vetted operations its own words name,
and the step sentences, how-to and skill text come from fixed templates. No model is called while
building, and the package itself uses no model. Executable code always comes from the tested runner.
"""

from __future__ import annotations

import copy
import re
from typing import Any


CLASS_ID = "tabular_cleaning"
OPERATIONS: dict[str, str] = {
    "profile_columns": "find which columns hold names, emails, phone numbers and dates",
    "normalize_dates": "write every date as YYYY-MM-DD and flag dates that could be read two ways",
    "normalize_phones": "write every phone number as + and the country code, and flag numbers it cannot read",
    "deduplicate": "remove duplicate rows (the same row, the same email, or the same name and phone)",
    "flag_missing_fields": "flag rows that have no email and no phone, or miss a required field",
    "write_report": "write a short report with counts and the list of rows a person should check",
}
ORDER = list(OPERATIONS)
# Which operations a piece needs, read from its own words.
PIECE_WORDS: dict[str, tuple[str, ...]] = {
    "profile_columns": ("profile", "column", "columns", "inspect", "understand"),
    "normalize_dates": ("date", "dates"),
    "normalize_phones": ("phone", "phones", "telephone", "mobile"),
    "deduplicate": ("duplicate", "duplicates", "dedupe", "deduplicate", "double"),
    "flag_missing_fields": ("missing", "required", "blank", "empty", "validate", "incomplete"),
    "write_report": ("report", "summary", "summarize", "summarise"),
}
REUSE_TO_OPERATION = {"dedupe": "deduplicate", "dates": "normalize_dates", "phones": "normalize_phones",
                      "missing_contact": "flag_missing_fields"}
DEFAULT_INSTRUCTIONS: dict[str, str] = {
    "profile_columns": "Find which columns hold names, emails, phone numbers and dates, so later steps know what to clean.",
    "normalize_dates": "Write every date as YYYY-MM-DD; dates that could be read two ways are flagged for a person.",
    "normalize_phones": "Write every phone number with a plus sign and country code; numbers it cannot read are flagged.",
    "deduplicate": "Remove rows that repeat the same row, email, or name and phone; same-name rows with other details go to a person.",
    "flag_missing_fields": "Flag every row with no email and no phone, or without a name, so a person can decide what to do.",
    "write_report": "Write a short report with the counts and the rows a person should check.",
}
LOCALES = {
    "GB": ("uk", "u k", "united kingdom", "britain", "british", "england", "scotland", "wales", "london"),
    "CA": ("canada", "canadian", "ontario", "quebec", "toronto", "vancouver"),
    "US": ("us", "u s", "usa", "united states", "american"),
}
DAY_FIRST = ("day first", "dd mm", "dd/mm", "european dates", "day month year")


def default_params(country: str, order: str) -> dict[str, dict[str, Any]]:
    return {
        "profile_columns": {"min_share": 0.6},
        "normalize_dates": {"output_format": "YYYY-MM-DD", "assume_order": order, "two_digit_year_pivot": 69},
        "normalize_phones": {"default_country": country, "output": "E.164"},
        "deduplicate": {"match_on": ["exact_row", "email", "name_and_phone"], "fill_blanks": True,
                        "flag_same_name": True, "tidy_emails": True},
        "flag_missing_fields": {"contact_any": ["email", "phone"], "required_roles": ["name"],
                                "check_email_format": True},
        "write_report": {"summary": "deterministic"},
    }


def words(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", text.lower()).strip() + " "


def locale(description: str) -> tuple[str, str, str]:
    """(country, date order, why): read only from the request's own words, else the US default."""
    text = words(description)
    for country, hints in LOCALES.items():
        if any(f" {h} " in text for h in hints):
            order = "DMY" if country == "GB" else "MDY"
            if any(f" {h} " in text for h in DAY_FIRST):
                order = "DMY"
            return country, order, f"the request mentions {country}"
    order = "DMY" if any(f" {h} " in text for h in DAY_FIRST) else "MDY"
    return "US", order, "no country in the request; US phone numbers and month-first dates are the default, and process.json can change both"


def expected_ops(title: str) -> set[str]:
    text = words(title)
    return {op for op, hints in PIECE_WORDS.items() if any(f" {h} " in text for h in hints)}


def clean_sentence(text: str, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip().strip('"')
    if len(text) > limit:
        cut = text[:limit].rsplit(" ", 1)[0]
        text = cut.rstrip(",;:") + "."
    return text


def instruction_problems(text: str) -> list[str]:
    problems = []
    if not 12 <= len(text) <= 240:
        problems.append("instruction length outside 12 to 240 characters")
    if re.search(r"https?://|`|\$ |\bsudo\b", text):
        problems.append("instruction holds a link or a command")
    if re.search(r"(?i)\b(upload|e-?mail (?:them|the|it)|send (?:them|the|it)|share (?:them|the|it)|cloud|internet)\b", text):
        problems.append("instruction sends data somewhere")
    return problems


def fixed_piece(piece: dict[str, Any]) -> dict[str, Any]:
    """One plan piece's step logic from fixed templates: the operations its own words name, each with
    its fixed sentence. No model is called."""
    title = str(piece.get("title", ""))
    ops = sorted(expected_ops(title) or {"write_report"}, key=ORDER.index)
    return {
        "piece_id": piece.get("id"),
        "title": title,
        "steps": [{"operation": op, "instruction": DEFAULT_INSTRUCTIONS[op], "written_by": "fixed template"} for op in ops],
        "accepted": True,
        "notes": [],
    }


def combine_steps(description: str, piece_outputs: list[dict[str, Any]], reuse_ops: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """The process steps in the runner's order, one per operation, with each step's source piece."""
    country, order, why = locale(description)
    params = default_params(country, order)
    by_op: dict[str, dict[str, Any]] = {}
    notes = [f"locale: {country}, {order} ({why})"]
    for output in piece_outputs:
        for step in output["steps"]:
            op = step["operation"]
            if op in by_op:
                notes.append(f"{op}: also drafted by piece {output['piece_id']}; the first piece's sentence is kept")
                continue
            by_op[op] = {"id": op.replace("_", "-"), "operation": op, "piece": output["piece_id"],
                         "params": copy.deepcopy(params[op]), "instruction": step["instruction"],
                         "written_by": step["written_by"]}
    for need in [REUSE_TO_OPERATION[r] for r in reuse_ops if r in REUSE_TO_OPERATION] + ["profile_columns", "write_report"]:
        if need not in by_op:
            by_op[need] = {"id": need.replace("_", "-"), "operation": need, "piece": "combine",
                           "params": copy.deepcopy(params[need]), "instruction": DEFAULT_INSTRUCTIONS[need],
                           "written_by": "fixed default"}
            notes.append(f"{need}: the request needs it and no piece covered it; added by the combine step")
    return [by_op[op] for op in ORDER if op in by_op], notes


def process_spec(pack_id: str, title: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "format": "ta-amps.process-spec.v1",
        "process_id": pack_id,
        "process_class": CLASS_ID,
        "title": title + " report",
        "summary_hook": {"default": "off", "how": "--summary-command, your own agent's command; it gets the counts only"},
        "steps": [{k: s[k] for k in ("id", "operation", "params", "instruction", "piece")} for s in steps],
    }


# ---------------------------------------------------------------------------
# Model-written prose: the how-to and the skill text
# ---------------------------------------------------------------------------

HOWTO_CLOSING = (
    "Your spreadsheets stay on your computer and are never changed: the process only reads them. Cleaned copies, "
    "flags.csv and report.md go into a separate results folder. Before anyone uses the cleaned sheet, a person checks "
    "every row marked needs_person = yes: possible duplicates, details that disagree, dates or phone numbers the "
    "process could not read, and missing contact details."
)


SKILL_TEXT = (
    "Run the process on the folder the person names, and ask for the folder only when none was named. Put the results "
    "in a separate folder. Read report.md and flags.csv when it finishes. Explain in plain words which rows "
    "need a person and why. Leave the original files exactly as they are. Let the person decide about every "
    "possible duplicate and every flagged row. Never contact volunteers, and never send the files or the "
    "results anywhere."
)


def howto_text(steps: list[dict[str, Any]]) -> str:
    """The how-to's "How it works" section from the steps' fixed sentences; no model wrote any of it."""
    return ("The process works through these steps by itself, in order. "
            + " ".join(s["instruction"] for s in steps) + "\n\n" + HOWTO_CLOSING)


# ---------------------------------------------------------------------------
# Kit content for the seed pack (deterministic)
# ---------------------------------------------------------------------------


def kit_content(subject_label: str) -> dict[str, Any]:
    """Checklist, sources, test cases, tool card and file specs that every package of the class shares."""
    return {
        "checklist": [
            "A person checks every row in flags.csv marked needs_person = yes before the cleaned sheet is used.",
            "Possible duplicates and duplicates whose details disagree are decided by a person, never by the agent.",
            "Nobody is contacted about missing details unless a person decides to, through the organization's own channels.",
            "The original spreadsheets stay where they are and are never changed; only the results folder is new.",
        ],
        "sources": [
            {"title": "ISO 8601: Date and time format", "url": "https://www.iso.org/iso-8601-date-and-time-format.html",
             "checked_date": "2026-10-31"},
            {"title": "ITU-T Recommendation E.164: The international public telecommunication numbering plan",
             "url": "https://www.itu.int/rec/T-REC-E.164/en", "checked_date": "2026-10-31"},
            {"title": "RFC 2606: Reserved Top Level DNS Names (example.org for made-up addresses)",
             "url": "https://www.rfc-editor.org/rfc/rfc2606", "checked_date": "2026-10-31"},
        ],
        "cases": [
            {"id": "FX-CLEAN-ROUTINE", "scenario": f"Three {subject_label} exports with mixed date and phone formats",
             "sample_input": "MADE-UP SAMPLE (no real data): 23 rows in four files (comma, tab and semicolon) with dates written five ways "
                             "and phone numbers written with and without country codes, extensions and dots.",
             "expected_indicators": ["dates_in_iso_form", "phones_in_e164_form", "inputs_unchanged"],
             "expected_human_escalation": False},
            {"id": "FX-CLEAN-POSSIBLE-DUP", "scenario": "Two rows share a name but have different emails and phones",
             "sample_input": "MADE-UP SAMPLE (no real data): rows 11 and 12 of spring-signups-sample.csv carry the same made-up name "
                             "with different made-up addresses and phone numbers.",
             "expected_indicators": ["possible_duplicate_flagged", "both_rows_kept"],
             "expected_human_escalation": True},
            {"id": "FX-CLEAN-AMBIGUOUS-DATE", "scenario": "A sheet whose dates could be read day-first or month-first",
             "sample_input": "MADE-UP SAMPLE (no real data): winter-signups-sample.csv has 01/02/2026 and 02/03/2026 and no day above 12.",
             "expected_indicators": ["ambiguous_date_flagged", "read_as_assumed_order"],
             "expected_human_escalation": True},
            {"id": "FX-CLEAN-NO-CONTACT", "scenario": "A sign-up with no email and no phone",
             "sample_input": "MADE-UP SAMPLE (no real data): row 9 of spring-signups-sample.csv has a name and a date but no contact details.",
             "expected_indicators": ["missing_contact_flagged", "nobody_contacted"],
             "expected_human_escalation": True},
        ],
        "tool": {
            "name": "profile_sheet_columns",
            "description": "Lists each column of the spreadsheet exports in a folder with its role (name, email, phone, date or other) and how many cells are filled, without changing any file.",
            "input_schema": {"type": "object", "required": ["folder"],
                             "properties": {"folder": {"type": "string", "description": "folder with .csv or .tsv files"}}},
            "output_fields": ["files", "columns", "roles", "filled", "empty"],
            "read_only": True,
        },
        "files": {
            "flags": {"name": "flags_sheet", "title": "Flags Sheet", "artifact_format": "csv_template",
                      "summary": "One row per change or question: file, row, column, issue, original and cleaned value, and whether a person must check it.",
                      "spec": {"columns": ["file", "row", "column", "issue", "original", "cleaned", "needs_person", "note"],
                               "stays_local": True}},
            "launch": {"name": "launch_steps", "title": "Launch Steps", "artifact_format": "markdown_sop",
                       "summary": "How to run the process on a folder of spreadsheets: with Docker, with Python, or through an agent harness.",
                       "spec": []},
        },
    }
