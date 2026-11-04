#!/usr/bin/env python3
"""Fill a spreadsheet from reading files, and list everything a person must check, on your own computer.

    python3 run_process.py --show-fields
    python3 run_process.py --input FOLDER --write-reading '{"document_id": ..., "source_file": ..., "fields": {...}}'
    python3 run_process.py --input FOLDER --output RESULTS_FOLDER

This process does not read images or handwriting, and it calls no model. Your own agent, or a local OCR
tool you choose, reads each scan and leaves one small file in FOLDER/readings/. This process then
compares those files with the field list in process.json. It writes to RESULTS_FOLDER:
spreadsheet.csv (one row per scan), person-check.csv (every unclear, low-confidence or missing field,
and all client text), report.md, report.json (counts only) and record.json (digests of the files, with
numbers in place of their names).

FOLDER holds the scans and is only read, except that --write-reading adds files to FOLDER/readings/.
A value is never corrected or guessed. A value that is unclear or low-confidence stays out of the
spreadsheet and waits in person-check.csv. This runner sends nothing anywhere; where a scan goes during the
reading step depends on the model or tool that reads it. Python standard library only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

RUNNER_VERSION = "1.0.0"
SPEC_FORMAT = "ta-amps.process-spec.v1"
REPORT_FORMAT = "ta-amps.scan-report.v1"
READING_FORMAT = "ta-amps.scan-reading.v1"
PROCESS_CLASS = "handwritten_case_files"
OPERATIONS = ("check_readings", "fill_spreadsheet", "list_for_person", "write_report")
KINDS = ("text", "case_text", "date", "number")
READINGS = "readings"
SCAN_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".heic", ".pdf")
MAX_READING_BYTES = 256 * 1024
MAX_VALUE_CHARS = 20000
LOWEST_ALLOWED_CONFIDENCE = 0.5
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")
FIELD_RE = re.compile(r"[a-z][a-z0-9_]{0,47}")
UNCLEAR_VALUE_RE = re.compile(r"\?|\[[^\]]*\]|\b(?:illegible|unreadable|unclear|cannot read|can't read)\b", re.IGNORECASE)
DATE_RE = re.compile(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"
                     r"|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\.?,?\s+\d{2,4}|[A-Za-z]{3,9}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{2,4}")
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\uff1d", "\uff0b", "\uff0d", "\uff20")
CHECK_COLUMNS = ("document_id", "source_file", "field", "issue", "value_read", "confidence", "note")
# Issues that keep a value out of the spreadsheet until a person has looked at it.
HOLD_ISSUES = frozenset({"unclear", "no_confidence", "low_confidence", "check_format", "starts_like_formula"})
NOTES = {
    "no_reading": "No reading file for this scan yet, so its row is empty. Read it, or type it by hand.",
    "no_scan": "This reading names a scan that is not in the folder. Find the scan before using the row.",
    "bad_reading": "This reading file cannot be used as written.",
    "duplicate_source": "Two readings name the same scan. Decide which one is right.",
    "unknown_field": "This field is not on the process's field list, so it is not in the spreadsheet.",
    "missing": "The reading has no value for this field. Look at the scan.",
    "unclear": "The reader marked this unclear. Look at the scan and type what it says.",
    "no_confidence": "The reader gave no confidence for this value. Look at the scan.",
    "low_confidence": "The reader was not sure enough. Look at the scan.",
    "check_format": "This does not look like the kind of value the field expects. Look at the scan.",
    "starts_like_formula": "A spreadsheet could run this as a formula, so it is held here. Look at the scan.",
    "case_text": "Client text: a person always checks it against the scan.",
}


class ProcessError(ValueError):
    """The spec, the folders or a reading cannot be used as given."""


def load_spec(path: Path) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    name = path.name
    if spec.get("format") != SPEC_FORMAT or spec.get("process_class") != PROCESS_CLASS:
        raise ProcessError(f"{name}: format must be {SPEC_FORMAT!r} and process_class {PROCESS_CLASS!r}")
    steps = spec.get("steps")
    if not isinstance(steps, list) or [s.get("operation") for s in steps if isinstance(s, dict)] != list(OPERATIONS):
        raise ProcessError(f"{name}: the steps must be exactly {', '.join(OPERATIONS)}, in that order")
    params = steps[0].get("params") or {}
    if set(params) != {"fields", "min_confidence"} or any(s.get("params") for s in steps[1:]):
        raise ProcessError(f"{name}: only check_readings takes params: fields and min_confidence")
    confidence = params["min_confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not LOWEST_ALLOWED_CONFIDENCE <= confidence <= 1:
        raise ProcessError(f"{name}: min_confidence must be from {LOWEST_ALLOWED_CONFIDENCE} to 1")
    fields = params["fields"]
    if not isinstance(fields, list) or not fields:
        raise ProcessError(f"{name}: fields must be a non-empty list")
    seen: set[str] = set()
    for field in fields:
        if not isinstance(field, dict) or set(field) != {"name", "kind", "label"}:
            raise ProcessError(f"{name}: every field has exactly a name, a kind and a label")
        if not FIELD_RE.fullmatch(str(field["name"])) or field["name"] in seen or field["kind"] not in KINDS:
            raise ProcessError(f"{name}: field {field['name']!r} has a bad or repeated name, or a kind not in {KINDS}")
        seen.add(field["name"])
    return spec


def fields_of(spec: dict[str, Any]) -> list[dict[str, str]]:
    return spec["steps"][0]["params"]["fields"]


def min_confidence(spec: dict[str, Any]) -> float:
    return float(spec["steps"][0]["params"]["min_confidence"])


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def input_digests(paths: list[Path]) -> dict[str, str]:
    """Each input's digest under a plain number: a file name can hold a client's name, and record.json must not."""
    return {f"input-{number:05d}": sha256_file(path) for number, path in enumerate(paths, 1)}


def list_files(folder: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if not folder.is_dir() or folder.is_symlink():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and not p.is_symlink()
                  and not p.name.startswith(".") and p.suffix.lower() in suffixes)


def valid_confidence(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def reading_problems(doc: Any, stem: str | None = None) -> list[str]:
    """Why a reading's outer shape cannot be used; the fields are judged one by one later."""
    if not isinstance(doc, dict):
        return ["a reading is one JSON object"]
    problems = []
    if doc.get("format", READING_FORMAT) != READING_FORMAT:
        problems.append(f"format must be {READING_FORMAT}")
    doc_id = doc.get("document_id")
    if not isinstance(doc_id, str) or not ID_RE.fullmatch(doc_id):
        problems.append("document_id must be letters, digits, dots, dashes or underscores")
    elif stem is not None and doc_id != stem:
        problems.append("document_id must match the reading's file name")
    source = doc.get("source_file")
    if not isinstance(source, str) or not ID_RE.fullmatch(source):
        problems.append("source_file must be a scan's plain file name, with no folder")
    if not isinstance(doc.get("fields"), dict):
        problems.append("fields must be an object")
    return problems


class Checker:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.fields = fields_of(spec)
        self.floor = min_confidence(spec)
        self.rows: list[list[str]] = []

    def flag(self, doc: str, source: str, field: str, issue: str, value: str = "", confidence: Any = "", note: str = "") -> None:
        self.rows.append([doc, source, field, issue, value, "" if confidence is None else str(confidence), note or NOTES[issue]])

    def judge(self, entry: Any, field: dict[str, str]) -> tuple[str, str, Any, list[str]]:
        """(value to show a person, value for the spreadsheet, confidence, issues) for one field."""
        if entry is None:
            return "", "", "", ["missing"]
        if not isinstance(entry, dict) or not isinstance(entry.get("value", ""), str) or len(entry.get("value", "")) > MAX_VALUE_CHARS:
            return "", "", "", ["bad_reading"]
        value, confidence = entry.get("value", "").strip(), entry.get("confidence")
        issues: list[str] = []
        if entry.get("unclear") is True or (value and UNCLEAR_VALUE_RE.search(value)):
            issues.append("unclear")
        elif not value:
            return "", "", confidence, ["missing"]
        elif not valid_confidence(confidence):
            issues.append("no_confidence")
        elif confidence < self.floor:
            issues.append("low_confidence")
        if value:
            shape = {"date": DATE_RE, "number": NUMBER_RE}.get(field["kind"])
            if shape is not None and not shape.fullmatch(value) and "unclear" not in issues:
                issues.append("check_format")
            if value.startswith(FORMULA_START):
                issues.append("starts_like_formula")
        cell = "" if HOLD_ISSUES & set(issues) else value
        if field["kind"] == "case_text" and value:
            issues.append("case_text")
        return value, cell, confidence, issues

    def document(self, doc_id: str, source: str, doc: dict[str, Any]) -> dict[str, str]:
        entries = doc["fields"]
        known = {f["name"] for f in self.fields}
        row = {"document_id": doc_id, "source_file": source}
        for field in self.fields:
            value, cell, confidence, issues = self.judge(entries.get(field["name"]), field)
            row[field["name"]] = cell
            for issue in issues:
                self.flag(doc_id, source, field["name"], issue, value, confidence)
        for name in sorted(set(entries) - known):
            entry = entries[name]
            value = entry.get("value", "") if isinstance(entry, dict) else ""
            self.flag(doc_id, source, str(name)[:60], "unknown_field", value if isinstance(value, str) else "")
        return row

    def empty_row(self, doc_id: str, source: str) -> dict[str, str]:
        return {"document_id": doc_id, "source_file": source, **{f["name"]: "" for f in self.fields}}


def load_reading(path: Path) -> tuple[Any, list[str]]:
    if path.stat().st_size > MAX_READING_BYTES:
        return None, [f"the file is larger than {MAX_READING_BYTES} bytes"]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return None, [f"not valid JSON ({type(exc).__name__})"]
    return doc, reading_problems(doc, path.stem)


def safe_cell(cell: Any) -> str:
    """A cell a spreadsheet program shows as text: a leading quote stops it running as a formula, and a person still sees it all."""
    text = str(cell)
    return "'" + text if text.lstrip(" \t\r\n").startswith(FORMULA_START) or text.startswith(("\t", "\r", "\n")) else text


def write_csv(path: Path, header: list[str] | tuple[str, ...], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([safe_cell(cell) for cell in header])
        writer.writerows([safe_cell(cell) for cell in row] for row in rows)


def render_markdown(report: dict[str, Any]) -> str:
    totals = report["totals"]
    lines = [f"# {report['title']}", "",
             "This process did not read the scans. It used the reading files from your own agent or OCR tool.", "",
             f"- Scans in the folder: {totals['scans']}",
             f"- Reading files: {totals['readings']}",
             f"- Rows in spreadsheet.csv: {totals['documents']}",
             f"- Fields filled: {totals['fields_filled']} of {totals['fields_total']}",
             f"- Rows that wait for a person in person-check.csv: {totals['rows_for_a_person']}",
             f"- Spreadsheet rows with something to check: {totals['documents_for_a_person']}",
             f"- Input files unchanged during the run: {'yes' if report['inputs_unchanged'] else 'NO'}", ""]
    if report["issues"]:
        lines += ["| What a person checks | Rows |", "| --- | --- |"]
        lines += [f"| {name} | {count} |" for name, count in sorted(report["issues"].items())] + [""]
    lines += ["A person checks every row in person-check.csv against the scan before anyone uses the spreadsheet.",
              "This report holds counts only, never names or values.", ""]
    return "\n".join(lines)


def run(input_dir: Path, output_dir: Path, spec_path: Path, overwrite: bool = False) -> dict[str, Any]:
    spec = load_spec(spec_path)
    if not input_dir.is_dir():
        raise ProcessError(f"{input_dir} is not a folder")
    source, target = input_dir.resolve(), output_dir.resolve()
    if target == source or source in target.parents:
        raise ProcessError("the results folder must be outside the input folder")
    if (output_dir / "spreadsheet.csv").exists() and not overwrite:
        raise ProcessError(f"{output_dir} already holds a spreadsheet, maybe with a person's changes; "
                           "name a new results folder, or add --overwrite")
    scans = list_files(input_dir, SCAN_SUFFIXES)
    readings = list_files(input_dir / READINGS, (".json",))
    inputs = [*scans, *readings]
    before = input_digests(inputs)

    checker = Checker(spec)
    scan_names = {p.name for p in scans}
    rows: dict[str, dict[str, str]] = {}
    seen_sources: dict[str, str] = {}
    for path in readings:
        doc, problems = load_reading(path)
        if problems:
            rows[path.stem] = checker.empty_row(path.stem, "")
            checker.flag(path.stem, "", "*", "bad_reading", note="This reading file cannot be used: " + "; ".join(problems)[:300])
            continue
        doc_id, scan = doc["document_id"], doc["source_file"]
        rows[doc_id] = checker.document(doc_id, scan, doc)
        if scan not in scan_names:
            checker.flag(doc_id, scan, "*", "no_scan")
        if scan in seen_sources:
            checker.flag(doc_id, scan, "*", "duplicate_source", note=f"{seen_sources[scan]} also names this scan. Decide which one is right.")
        seen_sources.setdefault(scan, doc_id)
    for path in scans:
        if path.name not in seen_sources:
            doc_id = path.stem if path.stem not in rows else path.name
            rows[doc_id] = checker.empty_row(doc_id, path.name)
            checker.flag(doc_id, path.name, "*", "no_reading")

    names = [f["name"] for f in checker.fields]
    to_check: dict[str, list[str]] = {}
    for flag in checker.rows:
        to_check.setdefault(flag[0], [])
        if flag[2] not in to_check[flag[0]]:
            to_check[flag[0]].append(flag[2])
    sheet = [[row["document_id"], row["source_file"], *[row[n] for n in names],
              "yes" if doc_id in to_check else "no", "; ".join(to_check.get(doc_id, []))]
             for doc_id, row in sorted(rows.items())]
    flags = sorted(checker.rows, key=lambda r: (r[0], r[2], r[3]))

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "spreadsheet.csv", ["document_id", "source_file", *names, "person_check", "fields_to_check"], sheet)
    write_csv(output_dir / "person-check.csv", CHECK_COLUMNS, flags)
    after = input_digests(inputs)
    filled = sum(1 for row in rows.values() for n in names if row[n])
    report = {
        "format": REPORT_FORMAT, "process_id": spec.get("process_id"), "title": spec.get("title", "Scan reading report"),
        "runner_version": RUNNER_VERSION, "model_calls": 0,
        "totals": {"scans": len(scans), "readings": len(readings), "documents": len(rows), "fields_total": len(rows) * len(names),
                   "fields_filled": filled, "rows_for_a_person": len(flags), "documents_for_a_person": len(to_check)},
        "issues": dict(sorted(Counter(flag[3] for flag in flags).items())),
        "inputs_unchanged": before == after,
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    outputs = {name: sha256_file(output_dir / name) for name in ("spreadsheet.csv", "person-check.csv", "report.json", "report.md")}
    record = {"format": "ta-amps.scan-run-record.v1", "runner_sha256": sha256_file(Path(__file__).resolve()),
              "python": platform.python_version(), "inputs_before": before, "inputs_after": after, "outputs": outputs}
    (output_dir / "record.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def write_reading(input_dir: Path, text: str, spec_path: Path) -> Path:
    """Save one reading in FOLDER/readings/ after checking it, so an agent needs no general write access."""
    spec = load_spec(spec_path)
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise ProcessError(f"the reading is not valid JSON: {exc}") from exc
    problems = reading_problems(doc)
    if problems:
        raise ProcessError("; ".join(problems))
    if doc["source_file"] not in {p.name for p in list_files(input_dir, SCAN_SUFFIXES)}:
        raise ProcessError(f"{doc['source_file']} is not a scan in {input_dir}")
    known = {f["name"] for f in fields_of(spec)}
    for name, entry in doc["fields"].items():
        if name not in known:
            raise ProcessError(f"{name} is not on the field list; see --show-fields")
        if not isinstance(entry, dict) or not isinstance(entry.get("value", ""), str):
            raise ProcessError(f"{name}: each field is an object with a text value")
        if entry.get("unclear") is not True and not valid_confidence(entry.get("confidence")):
            raise ProcessError(f"{name}: give a confidence from 0 to 1, or mark it \"unclear\": true")
        if "confidence" in entry and not valid_confidence(entry["confidence"]):
            raise ProcessError(f"{name}: confidence must be a number from 0 to 1")
    folder = input_dir / READINGS
    if folder.is_symlink():
        raise ProcessError(f"{folder} is a symbolic link")
    folder.mkdir(exist_ok=True)
    target = folder / f"{doc['document_id']}.json"
    if target.is_symlink():
        raise ProcessError(f"{target} is a symbolic link")
    temporary = folder / f".{doc['document_id']}.tmp"
    temporary.write_text(json.dumps({"format": READING_FORMAT, **doc}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def show_fields(spec_path: Path) -> dict[str, Any]:
    spec = load_spec(spec_path)
    return {"reading_format": READING_FORMAT, "min_confidence": min_confidence(spec), "fields": fields_of(spec),
            "example": {"document_id": "my-scan-01", "source_file": "my-scan-01.png", "read_by": "what did the reading",
                        "fields": {fields_of(spec)[0]["name"]: {"value": "the words as written", "confidence": 0.95},
                                   fields_of(spec)[-1]["name"]: {"value": "my best try", "unclear": True}}}}


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", type=Path, help="folder with the scans; its readings/ subfolder holds the reading files")
    parser.add_argument("--output", type=Path, help="folder for the results (outside the input folder)")
    parser.add_argument("--spec", type=Path, default=here / "process.json", help="the process steps (default: process.json)")
    parser.add_argument("--overwrite", action="store_true", help="replace results already in the results folder")
    parser.add_argument("--write-reading", metavar="JSON", help="check one reading and save it in the input folder's readings/")
    parser.add_argument("--show-fields", action="store_true", help="print the field list and an example reading")
    args = parser.parse_args(argv)
    try:
        if args.show_fields:
            print(json.dumps(show_fields(args.spec), indent=2))
            return 0
        if args.input is None:
            parser.error("--input is required")
        if args.write_reading is not None:
            print(f"Saved {write_reading(args.input, args.write_reading, args.spec)}")
            return 0
        if args.output is None:
            parser.error("--output is required")
        report = run(args.input, args.output, args.spec, args.overwrite)
    except (ProcessError, OSError, ValueError) as exc:
        print(f"run_process: {exc}", file=sys.stderr)
        return 2
    totals = report["totals"]
    print(f"Filled {totals['fields_filled']} of {totals['fields_total']} fields for {totals['documents']} scans; "
          f"{totals['rows_for_a_person']} rows wait for a person. Results: {args.output / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
