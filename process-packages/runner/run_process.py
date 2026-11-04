#!/usr/bin/env python3
"""Clean spreadsheet exports on your own computer, following the steps in process.json.

    python3 run_process.py --input DATA_FOLDER --output RESULTS_FOLDER

Reads every .csv and .tsv file in DATA_FOLDER and never changes them. Writes to RESULTS_FOLDER:
cleaned/<file>.csv (duplicates removed, dates and phone numbers in one format), flags.csv (every
change and every question for a person), report.md, report.json and receipt.json.

The process needs no model and nothing leaves the computer. An optional summary hook, off by default
(--summary-command), runs a command you choose on your own computer, for example your own agent's
command-line tool. It gives that command the counts only, never rows, and keeps its paragraph only
when every number in it appears in the counts. Python standard library only.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import platform
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

RUNNER_VERSION = "1.0.0"
SPEC_FORMAT = "ta-amps.process-spec.v1"
REPORT_FORMAT = "ta-amps.process-report.v1"
INPUT_SUFFIXES = (".csv", ".tsv")
MAX_INPUT_BYTES = 50 * 1024 * 1024
SUMMARY_TIMEOUT_S = 180
CANONICAL_ORDER = (
    "profile_columns",
    "normalize_dates",
    "normalize_phones",
    "deduplicate",
    "flag_missing_fields",
    "write_report",
)
OPERATION_PARAMS: dict[str, dict[str, Any]] = {
    "profile_columns": {"role_overrides": dict, "min_share": float},
    "normalize_dates": {"output_format": str, "assume_order": str, "two_digit_year_pivot": int},
    "normalize_phones": {"default_country": str, "output": str},
    "deduplicate": {"match_on": list, "fill_blanks": bool, "flag_same_name": bool, "tidy_emails": bool},
    "flag_missing_fields": {"contact_any": list, "required_roles": list, "check_email_format": bool},
    "write_report": {"summary": str, "title": str},
}
ROLE_HEADERS: dict[str, tuple[str, ...]] = {
    "email": ("email", "e mail", "email address", "e mail address", "mail", "email addr"),
    "phone": ("phone", "phone number", "mobile", "mobile number", "cell", "cell phone", "telephone",
              "tel", "contact number", "phone no", "mobile phone"),
    "first_name": ("first name", "first", "given name", "firstname", "forename"),
    "last_name": ("last name", "last", "surname", "family name", "lastname"),
    "name": ("name", "full name", "volunteer name", "volunteer", "your name"),
}
DATE_HEADER_WORDS = ("date", "signed up", "sign up", "signup", "registered", "joined", "available from",
                     "start", "dob", "birthday", "submitted", "timestamp")
EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}$")
PHONE_CHARS_RE = re.compile(r"^[\d\s().+\-/]*(?:\s*(?:ext\.?|extension|x|#)\s*\d{1,6})?\s*$", re.IGNORECASE)
EXT_RE = re.compile(r"\s*(?:ext\.?|extension|x|#)\s*(\d{1,6})\s*$", re.IGNORECASE)
TIME_TAIL_RE = re.compile(r"[ T]+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?$")
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
    "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
ISO_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
NUMERIC_RE = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})$")
MONTH_FIRST_RE = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})$")
DAY_FIRST_RE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[\s-]+([A-Za-z]{3,9})\.?,?[\s-]+(\d{2}|\d{4})$")
FLAG_FIELDS = ("file", "row", "column", "issue", "original", "cleaned", "needs_person", "note")
# Issues a person has to look at; everything else is a change the process made and recorded.
PERSON_ISSUES = frozenset({
    "possible_duplicate", "duplicate_conflict", "ambiguous_date", "invalid_date", "invalid_phone",
    "invalid_email", "missing_contact", "missing_required", "row_length",
})


class ProcessError(ValueError):
    """The spec, the folders or an input file cannot be used as given."""


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


def load_spec(path: Path) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("format") != SPEC_FORMAT:
        raise ProcessError(f"{path.name}: format must be {SPEC_FORMAT!r}")
    steps = spec.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ProcessError(f"{path.name}: steps must be a non-empty list")
    seen: set[str] = set()
    for step in steps:
        op = step.get("operation")
        if op not in OPERATION_PARAMS:
            raise ProcessError(f"{path.name}: unknown operation {op!r}; known: {sorted(OPERATION_PARAMS)}")
        if op in seen:
            raise ProcessError(f"{path.name}: operation {op!r} appears twice")
        seen.add(op)
        params = step.get("params", {})
        if not isinstance(params, dict):
            raise ProcessError(f"{path.name}: params of {op} must be an object")
        for name, value in params.items():
            kind = OPERATION_PARAMS[op].get(name)
            if kind is None:
                raise ProcessError(f"{path.name}: {op} has no parameter {name!r}")
            if kind is float and isinstance(value, int) and not isinstance(value, bool):
                continue
            if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
                raise ProcessError(f"{path.name}: {op}.{name} must be {kind.__name__}")
    if "write_report" not in seen:
        raise ProcessError(f"{path.name}: the steps must end with write_report")
    return spec


def step_params(spec: dict[str, Any], operation: str) -> dict[str, Any] | None:
    for step in spec["steps"]:
        if step["operation"] == operation:
            return dict(step.get("params", {}))
    return None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def list_inputs(folder: Path) -> list[Path]:
    files = sorted(
        p for p in folder.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in INPUT_SUFFIXES
    )
    for path in files:
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ProcessError(f"{path.name} is larger than {MAX_INPUT_BYTES // (1024 * 1024)} MB")
    return files


def read_table(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        text, encoding = raw.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        text, encoding = raw.decode("cp1252", errors="replace"), "cp1252"
    lines = text.splitlines(keepends=True)
    comments: list[str] = []
    while lines and (not lines[0].strip() or lines[0].lstrip().startswith("#")):
        line = lines.pop(0).strip()
        if line:
            comments.append(line)
    body = "".join(lines)
    if path.suffix.lower() == ".tsv":
        delimiter = "\t"
    else:
        try:
            delimiter = csv.Sniffer().sniff(body[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    rows = [row for row in csv.reader(io.StringIO(body), delimiter=delimiter) if any(c.strip() for c in row)]
    if not rows:
        return {"header": [], "rows": [], "comments": comments, "encoding": encoding,
                "delimiter": delimiter, "length_issues": []}
    header = [h.strip() for h in rows[0]]
    data: list[list[str]] = []
    length_issues: list[int] = []
    for i, row in enumerate(rows[1:], start=1):
        if len(row) != len(header):
            length_issues.append(i)
            row = (row + [""] * len(header))[: len(header)]
        data.append([cell.strip() for cell in row])
    return {"header": header, "rows": data, "comments": comments, "encoding": encoding,
            "delimiter": delimiter, "length_issues": length_issues}


# ---------------------------------------------------------------------------
# Column roles
# ---------------------------------------------------------------------------


def norm_header(text: str) -> str:
    text = re.sub(r"[_\-/]+", " ", text.lower())
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def looks_like_email(value: str) -> bool:
    return bool(EMAIL_RE.match(value.strip().lower().removeprefix("mailto:").strip("<>")))


def looks_like_phone(value: str) -> bool:
    return bool(PHONE_CHARS_RE.match(value)) and len(re.sub(r"\D", "", EXT_RE.sub("", value))) >= 7


def column_roles(header: list[str], rows: list[list[str]], params: dict[str, Any]) -> list[str]:
    overrides = {norm_header(k): v for k, v in (params.get("role_overrides") or {}).items()}
    min_share = float(params.get("min_share", 0.6))
    roles: list[str] = []
    for index, raw in enumerate(header):
        name = norm_header(raw)
        if name in overrides:
            roles.append(str(overrides[name]))
            continue
        role = next((r for r, names in ROLE_HEADERS.items() if name in names), None)
        if role is None and any(word in name for word in DATE_HEADER_WORDS):
            role = "date"
        if role is None:
            values = [row[index] for row in rows if row[index]]
            if values:
                for candidate, test in (("email", looks_like_email), ("phone", looks_like_phone),
                                        ("date", lambda v: parse_date_parts(v) is not None)):
                    if sum(1 for v in values if test(v)) / len(values) >= min_share:
                        role = candidate
                        break
        roles.append(role or "other")
    return roles


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def parse_date_parts(value: str) -> tuple[str, tuple[int, int, int]] | None:
    """('ymd'|'numeric'|'named', parts) for a recognised date shape, else None."""
    text = TIME_TAIL_RE.sub("", value.strip())
    if m := ISO_RE.match(text):
        return "ymd", (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if m := NUMERIC_RE.match(text):
        return "numeric", (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if (m := MONTH_FIRST_RE.match(text)) and m.group(1).lower() in MONTHS:
        return "named", (int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    if (m := DAY_FIRST_RE.match(text)) and m.group(2).lower() in MONTHS:
        return "named", (int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    return None


def full_year(year: int, pivot: int) -> int:
    if year >= 100:
        return year
    return 2000 + year if year <= pivot else 1900 + year


def column_date_order(values: list[str]) -> str | None:
    """'DMY' or 'MDY' when the column's own values settle it, None when they do not or disagree."""
    first_big = second_big = False
    for value in values:
        parsed = parse_date_parts(value)
        if parsed and parsed[0] == "numeric":
            a, b, _ = parsed[1]
            first_big |= a > 12
            second_big |= b > 12
    if first_big and not second_big:
        return "DMY"
    if second_big and not first_big:
        return "MDY"
    return None


def clean_date(value: str, order: str | None, assume: str, pivot: int) -> tuple[str, str | None]:
    """(cleaned, issue): cleaned is ISO 8601 when the value could be read."""
    parsed = parse_date_parts(value)
    if parsed is None:
        return value, "invalid_date"
    shape, parts = parsed
    issue = None
    if shape == "numeric":
        a, b, year = parts
        if a > 12 >= b:
            use = "DMY"
        elif b > 12 >= a:
            use = "MDY"
        else:
            use = order or assume
            if order is None and a != b:
                issue = "ambiguous_date"
        day, month = (a, b) if use == "DMY" else (b, a)
        year = full_year(year, pivot)
    else:
        year, month, day = parts
        year = full_year(year, pivot)
    try:
        return dt.date(year, month, day).isoformat(), issue
    except ValueError:
        return value, "invalid_date"


# ---------------------------------------------------------------------------
# Phones
# ---------------------------------------------------------------------------


def clean_phone(value: str, country: str) -> tuple[str, str | None]:
    text = value.strip()
    ext_match = EXT_RE.search(text)
    ext = ext_match.group(1) if ext_match else None
    if ext_match:
        text = text[: ext_match.start()]
    if re.search(r"[A-Za-z]", text) or not text:
        return value, "invalid_phone"
    international = text.lstrip().startswith(("+", "00"))
    digits = re.sub(r"\D", "", text)
    if text.lstrip().startswith("00"):
        digits = digits[2:]
    number: str | None = None
    if international:
        if 8 <= len(digits) <= 15 and not (digits.startswith("1") and len(digits) != 11):
            number = digits
    elif country in ("US", "CA"):
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10 and digits[0] in "23456789" and digits[3] in "23456789":
            number = "1" + digits
    elif country == "GB":
        if digits.startswith("0") and len(digits) in (10, 11):
            number = "44" + digits[1:]
    if number is None:
        return value, "invalid_phone"
    cleaned = "+" + number
    return (f"{cleaned} ext {ext}" if ext else cleaned), None


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def simple(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def tidy_email(value: str) -> str:
    return value.strip().lower().removeprefix("mailto:").strip("<>").strip()


def row_name(row: list[str], roles: list[str]) -> str:
    full = " ".join(row[i] for i, r in enumerate(roles) if r == "name" and row[i])
    if not full:
        full = " ".join(row[i] for r in ("first_name", "last_name") for i, x in enumerate(roles) if x == r and row[i])
    return simple(full)


def first_value(row: list[str], roles: list[str], role: str) -> str:
    return next((row[i] for i, r in enumerate(roles) if r == role and row[i]), "")


class Flags:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []

    def add(self, file: str, row: int | str, column: str, issue: str, original: str = "",
            cleaned: str = "", note: str = "") -> None:
        self.rows.append({
            "file": file, "row": str(row), "column": column, "issue": issue, "original": original,
            "cleaned": cleaned, "needs_person": "yes" if issue in PERSON_ISSUES else "no", "note": note,
        })

    def count(self, file: str, issue: str) -> int:
        return sum(1 for f in self.rows if f["file"] == file and f["issue"] == issue)


def process_file(path: Path, spec: dict[str, Any], flags: Flags) -> dict[str, Any]:
    table = read_table(path)
    header, rows = table["header"], table["rows"]
    name = path.name
    profile = step_params(spec, "profile_columns") or {}
    roles = column_roles(header, rows, profile)
    numbers = list(range(1, len(rows) + 1))  # data row numbers in the original file, header excluded
    for i in table["length_issues"]:
        flags.add(name, i, "", "row_length", note="the row had a different number of cells than the header")
    stats: dict[str, Any] = {"dates_fixed": 0, "phones_fixed": 0, "emails_tidied": 0}

    dates = step_params(spec, "normalize_dates")
    if dates is not None:
        assume = str(dates.get("assume_order", "MDY")).upper()
        if assume not in ("MDY", "DMY"):
            raise ProcessError("normalize_dates.assume_order is MDY or DMY")
        pivot = int(dates.get("two_digit_year_pivot", 69))
        for c, role in enumerate(roles):
            if role != "date":
                continue
            order = column_date_order([r[c] for r in rows if r[c]])
            for r, row in enumerate(rows):
                if not row[c]:
                    continue
                cleaned, issue = clean_date(row[c], order, assume, pivot)
                if issue:
                    note = (f"read as {assume}; check against the original" if issue == "ambiguous_date"
                            else "not a date the process can read")
                    flags.add(name, numbers[r], header[c], issue, row[c], cleaned if cleaned != row[c] else "", note)
                if cleaned != row[c]:
                    if issue is None:
                        flags.add(name, numbers[r], header[c], "date_fixed", row[c], cleaned)
                        stats["dates_fixed"] += 1
                    elif issue == "ambiguous_date":
                        stats["dates_fixed"] += 1
                    row[c] = cleaned

    phones = step_params(spec, "normalize_phones")
    if phones is not None:
        country = str(phones.get("default_country", "US")).upper()
        for c, role in enumerate(roles):
            if role != "phone":
                continue
            for r, row in enumerate(rows):
                if not row[c]:
                    continue
                cleaned, issue = clean_phone(row[c], country)
                if issue:
                    flags.add(name, numbers[r], header[c], issue, row[c], "", "not a phone number the process can read")
                elif cleaned != row[c]:
                    flags.add(name, numbers[r], header[c], "phone_fixed", row[c], cleaned)
                    stats["phones_fixed"] += 1
                    row[c] = cleaned

    dedupe = step_params(spec, "deduplicate")
    removed = possible = conflicts = 0
    if dedupe is not None:
        if dedupe.get("tidy_emails", True):
            for c, role in enumerate(roles):
                if role != "email":
                    continue
                for r, row in enumerate(rows):
                    tidy = tidy_email(row[c]) if row[c] else ""
                    if tidy != row[c]:
                        flags.add(name, numbers[r], header[c], "email_tidied", row[c], tidy)
                        stats["emails_tidied"] += 1
                        row[c] = tidy
        match_on = [str(x) for x in dedupe.get("match_on", ["exact_row", "email", "name_and_phone"])]
        fill = bool(dedupe.get("fill_blanks", True))
        kept: list[int] = []
        seen_exact: dict[tuple[str, ...], int] = {}
        seen_email: dict[str, int] = {}
        seen_name_phone: dict[tuple[str, str], int] = {}
        seen_name: dict[str, int] = {}
        for r, row in enumerate(rows):
            exact = tuple(simple(c) for c in row)
            email = tidy_email(first_value(row, roles, "email"))
            email = email if looks_like_email(email) else ""
            phone = re.sub(r"\D", "", EXT_RE.sub("", first_value(row, roles, "phone")))
            person = row_name(row, roles)
            target, reason = None, ""
            if "exact_row" in match_on and exact in seen_exact:
                target, reason = seen_exact[exact], "exact_duplicate"
            elif "email" in match_on and email and email in seen_email:
                target, reason = seen_email[email], "same_email"
            elif "name_and_phone" in match_on and person and phone and (person, phone) in seen_name_phone:
                target, reason = seen_name_phone[(person, phone)], "same_name_and_phone"
            if target is not None:
                keep = rows[target]
                for c, cell in enumerate(row):
                    if not cell:
                        continue
                    if not keep[c] and fill:
                        keep[c] = cell
                        flags.add(name, numbers[target], header[c], "filled_from_duplicate", "", cell,
                                  f"taken from row {numbers[r]}, a duplicate")
                    elif keep[c] and simple(keep[c]) != simple(cell):
                        conflicts += 1
                        flags.add(name, numbers[target], header[c], "duplicate_conflict", cell, keep[c],
                                  f"row {numbers[r]} is a duplicate with a different value; the first was kept")
                removed += 1
                flags.add(name, numbers[r], "", "duplicate_removed", note=f"{reason}; kept row {numbers[target]}")
                continue
            kept.append(r)
            seen_exact.setdefault(exact, r)
            if email:
                seen_email.setdefault(email, r)
            if person and phone:
                seen_name_phone.setdefault((person, phone), r)
            if person and dedupe.get("flag_same_name", True):
                if person in seen_name:
                    possible += 1
                    flags.add(name, numbers[r], "", "possible_duplicate",
                              note=f"same name as row {numbers[seen_name[person]]} with different contact details; a person decides")
                else:
                    seen_name[person] = r
        rows = [rows[r] for r in kept]
        numbers = [numbers[r] for r in kept]

    missing = step_params(spec, "flag_missing_fields")
    missing_contact = missing_required = invalid_emails = 0
    if missing is not None:
        contact_any = [str(x) for x in missing.get("contact_any", ["email", "phone"])]
        required = [str(x) for x in missing.get("required_roles", ["name"])]
        for r, row in enumerate(rows):
            if contact_any and not any(first_value(row, roles, role) for role in contact_any):
                missing_contact += 1
                flags.add(name, numbers[r], "", "missing_contact",
                          note="no " + " and no ".join(contact_any) + "; a person decides whether to follow up")
            for role in required:
                if role == "name":
                    present = bool(row_name(row, roles))
                else:
                    present = bool(first_value(row, roles, role))
                if not present and (role != "name" or any(x in roles for x in ("name", "first_name", "last_name"))):
                    missing_required += 1
                    flags.add(name, numbers[r], "", "missing_required", note=f"no {role}")
            if missing.get("check_email_format", True):
                for c, role in enumerate(roles):
                    if role == "email" and row[c] and not looks_like_email(row[c]):
                        invalid_emails += 1
                        flags.add(name, numbers[r], header[c], "invalid_email", row[c], "",
                                  "not an email address the process can read")

    columns = []
    for c, h in enumerate(header):
        filled = sum(1 for row in rows if row[c])
        columns.append({"header": h, "role": roles[c], "filled": filled, "empty": len(rows) - filled})
    return {
        "file": name,
        "header": header,
        "rows": rows,
        "summary": {
            "file": name,
            "encoding": table["encoding"],
            "delimiter": {"\t": "tab", ",": "comma", ";": "semicolon", "|": "pipe"}.get(table["delimiter"], "other"),
            "rows_in": len(table["rows"]),
            "rows_out": len(rows),
            "duplicates_removed": removed,
            "possible_duplicates": possible,
            "duplicate_conflicts": conflicts,
            "dates_fixed": stats["dates_fixed"],
            "dates_ambiguous": flags.count(name, "ambiguous_date"),
            "dates_unreadable": flags.count(name, "invalid_date"),
            "phones_fixed": stats["phones_fixed"],
            "phones_unreadable": flags.count(name, "invalid_phone"),
            "emails_tidied": stats["emails_tidied"],
            "emails_unreadable": invalid_emails,
            "rows_missing_contact": missing_contact,
            "rows_missing_required": missing_required,
            "columns": columns,
        },
    }


def cross_file_notes(results: list[dict[str, Any]], flags: Flags) -> int:
    """Note contacts that appear in more than one file; nothing is removed across files."""
    where: dict[str, list[str]] = {}
    for result in results:
        roles = [c["role"] for c in result["summary"]["columns"]]
        for row in result["rows"]:
            email = tidy_email(first_value(row, roles, "email"))
            if looks_like_email(email):
                where.setdefault(email, [])
                if result["file"] not in where[email]:
                    where[email].append(result["file"])
    shared = {k: v for k, v in where.items() if len(v) > 1}
    for files in sorted(shared.values()):
        flags.add(files[0], "", "", "also_in_other_file", note="the same email address is also in " + ", ".join(files[1:]))
    return len(shared)


# ---------------------------------------------------------------------------
# The optional summary hook (off by default; counts only)
# ---------------------------------------------------------------------------


def summary_numbers(report: dict[str, Any]) -> set[str]:
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, bool):
            return
        if isinstance(value, int):
            found.add(str(value))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(report["totals"])
    walk([{k: v for k, v in f.items() if k != "columns"} for f in report["files"]])
    return found


def check_summary(text: str, allowed: set[str]) -> list[str]:
    problems = []
    if not 40 <= len(text) <= 900:
        problems.append("length outside 40 to 900 characters")
    if "@" in text or re.search(r"https?://", text):
        problems.append("contains an address or link")
    stray = sorted({n for n in re.findall(r"\d+", text) if n not in allowed})
    if stray:
        problems.append("numbers not in the counts: " + ", ".join(stray))
    return problems


def summary_prompt(counts: dict[str, Any]) -> str:
    return (
        "Counts from cleaning a volunteer sign-up spreadsheet, as JSON:\n"
        + json.dumps(counts, sort_keys=True)
        + "\nWrite three short plain sentences for the volunteer coordinator about what changed and what a "
        "person should check next. Use only numbers that appear in the counts. Do not invent names, "
        "addresses or numbers."
    )


def hook_summary(counts: dict[str, Any], command: str) -> dict[str, Any]:
    """Run the person's own summary command with the prompt on its input; it never sees a row."""
    import shlex
    import subprocess

    argv = shlex.split(command)
    if not argv:
        raise ProcessError("--summary-command is empty")
    prompt = summary_prompt(counts)
    try:
        done = subprocess.run(argv, input=prompt, capture_output=True, text=True, timeout=SUMMARY_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"used": False, "command": Path(argv[0]).name, "reason": f"the summary command did not finish: {type(exc).__name__}"}
    text = done.stdout.strip()
    if done.returncode != 0 or not text:
        return {"used": False, "command": Path(argv[0]).name, "reason": f"the summary command exited {done.returncode}"}
    return {
        "used": True,
        "command": Path(argv[0]).name,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "text": text,
    }


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

LABELS = (
    ("rows_in", "Rows read"),
    ("rows_out", "Rows in the cleaned copy"),
    ("duplicates_removed", "Duplicates removed"),
    ("possible_duplicates", "Possible duplicates for a person"),
    ("duplicate_conflicts", "Duplicate details that disagree"),
    ("dates_fixed", "Dates put in YYYY-MM-DD form"),
    ("dates_ambiguous", "Dates that could be read two ways"),
    ("dates_unreadable", "Dates the process could not read"),
    ("phones_fixed", "Phone numbers put in +country form"),
    ("phones_unreadable", "Phone numbers the process could not read"),
    ("emails_tidied", "Email addresses trimmed or lowercased"),
    ("emails_unreadable", "Email addresses the process could not read"),
    ("rows_missing_contact", "Rows with no email and no phone"),
    ("rows_missing_required", "Rows missing a required field"),
)


def render_markdown(report: dict[str, Any]) -> str:
    files = report["files"]
    lines = [f"# {report['title']}", "", "This report holds counts only, never rows from your files.", ""]
    lines.append(f"Files read: {len(files)}. Flags for a person: {report['totals']['flags_for_a_person']}. "
                 f"Changes recorded: {report['totals']['changes_recorded']}.")
    lines += ["", "| What | " + " | ".join(f["file"] for f in files) + " | Total |",
              "|---|" + "---|" * (len(files) + 1)]
    for key, label in LABELS:
        lines.append(f"| {label} | " + " | ".join(str(f[key]) for f in files) + f" | {report['totals'][key]} |")
    lines += ["", "## What a person checks", ""]
    person = report["person_checks"]
    if person:
        for issue, count in sorted(person.items()):
            lines.append(f"- {count} x `{issue}`: see flags.csv rows with needs_person = yes.")
    else:
        lines.append("- Nothing needs a person this time.")
    lines += ["", "## Summary", ""]
    summary = report["summary"]
    lines.append(summary["text"])
    lines += ["", f"Summary written by: {summary['written_by']}.",
              "", "The input files were read and never changed. Nothing was sent anywhere.", ""]
    return "\n".join(lines)


def deterministic_summary(totals: dict[str, Any], files: int) -> str:
    return (
        f"The process read {totals['rows_in']} rows in {files} file(s) and kept {totals['rows_out']}, "
        f"removing {totals['duplicates_removed']} duplicates. It put {totals['dates_fixed']} dates and "
        f"{totals['phones_fixed']} phone numbers in one format. {totals['flags_for_a_person']} flags need a "
        f"person, including {totals['rows_missing_contact']} row(s) with no email and no phone."
    )


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def run(input_dir: Path, output_dir: Path, spec_path: Path, summary_command: str | None = None) -> dict[str, Any]:
    input_dir, output_dir = input_dir.resolve(), output_dir.resolve()
    if not input_dir.is_dir():
        raise ProcessError(f"input folder {input_dir} does not exist")
    if output_dir == input_dir or input_dir in output_dir.parents:
        raise ProcessError("the output folder must be outside the input folder, so inputs stay untouched")
    spec = load_spec(spec_path)
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    inputs = list_inputs(input_dir)
    if not inputs:
        raise ProcessError(f"no .csv or .tsv files in {input_dir}")
    before = {p.name: sha256_file(p) for p in inputs}
    flags = Flags()
    results = [process_file(p, spec, flags) for p in inputs]
    shared = cross_file_notes(results, flags)

    (output_dir / "cleaned").mkdir(parents=True, exist_ok=True)
    for result in results:
        write_csv(output_dir / "cleaned" / (Path(result["file"]).stem + ".csv"), result["header"], result["rows"])
    write_csv(output_dir / "flags.csv", list(FLAG_FIELDS), [[f[k] for k in FLAG_FIELDS] for f in flags.rows])

    summaries = [r["summary"] for r in results]
    totals = {key: sum(s[key] for s in summaries) for key, _ in LABELS}
    totals["contacts_in_more_than_one_file"] = shared
    totals["flags_for_a_person"] = sum(1 for f in flags.rows if f["needs_person"] == "yes")
    totals["changes_recorded"] = sum(1 for f in flags.rows if f["needs_person"] == "no")
    person: dict[str, int] = {}
    for f in flags.rows:
        if f["needs_person"] == "yes":
            person[f["issue"]] = person.get(f["issue"], 0) + 1
    report_params = step_params(spec, "write_report") or {}
    report: dict[str, Any] = {
        "format": REPORT_FORMAT,
        "title": str(report_params.get("title") or spec.get("title") or "Cleaning report"),
        "process": spec.get("process_id", ""),
        "steps": [s["operation"] for s in sorted(spec["steps"], key=lambda s: CANONICAL_ORDER.index(s["operation"]))],
        "files": summaries,
        "totals": totals,
        "person_checks": person,
    }
    text = deterministic_summary(totals, len(summaries))
    written_by = "the process's fixed template (no model)"
    hook: dict[str, Any] = {"used": False, "reason": "summary hook off (the default)"}
    if summary_command:
        hook = hook_summary({"totals": totals, "person_checks": person}, summary_command)
        if hook.get("used"):
            problems = check_summary(hook["text"], summary_numbers(report))
            hook["checks"] = problems or ["passed"]
            if not problems:
                text = hook["text"]
                written_by = f"your summary command ({hook['command']}), checked: every number appears in the counts"
            else:
                written_by = "the process's fixed template; the summary command's text failed its checks"
        else:
            written_by = "the process's fixed template; " + str(hook.get("reason"))
    report["summary"] = {"text": text, "written_by": written_by}
    (output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")

    after = {p.name: sha256_file(p) for p in inputs}
    if after != before:
        raise ProcessError("an input file changed while the process ran")
    outputs = sorted(p for p in output_dir.rglob("*") if p.is_file() and p.name != "receipt.json")
    receipt = {
        "format": "ta-amps.process-run-receipt.v1",
        "runner_version": RUNNER_VERSION,
        "runner_sha256": sha256_file(Path(__file__)),
        "spec_sha256": sha256_file(spec_path),
        "python": platform.python_version(),
        "started_at": started,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "inputs": [{"file": n, "sha256": before[n], "unchanged": True} for n in sorted(before)],
        "outputs": [{"file": p.relative_to(output_dir).as_posix(), "sha256": sha256_file(p)} for p in outputs],
        "summary_hook": {k: v for k, v in hook.items() if k != "text"},
        "network": "none",
    }
    (output_dir / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", type=Path, required=True, help="folder with the .csv or .tsv files")
    parser.add_argument("--output", type=Path, required=True, help="folder for the results (outside the input folder)")
    parser.add_argument("--spec", type=Path, default=here / "process.json", help="the process steps (default: process.json)")
    parser.add_argument("--summary-command", default=None,
                        help="optional: a command on this computer (for example your own agent's) that reads the counts "
                             "on its input and prints a short paragraph; off by default")
    args = parser.parse_args(argv)
    try:
        report = run(args.input, args.output, args.spec, args.summary_command)
    except (ProcessError, OSError, json.JSONDecodeError) as exc:
        print(f"run_process: {exc}", file=sys.stderr)
        return 2
    totals = report["totals"]
    print(f"Cleaned {totals['rows_in']} rows into {totals['rows_out']}; {totals['flags_for_a_person']} flags need a "
          f"person. Results: {args.output / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
