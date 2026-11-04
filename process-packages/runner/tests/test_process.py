"""Tests for run_process.py on the made-up sample files (no real data); standard library only, no network.

    python3 -m unittest discover -s tests -v      (from the folder that holds run_process.py)

Two kinds of check: the fixed reference steps (samples/reference-process.json) must give exactly
the reviewed outputs in samples/expected/, and this package's own process.json must keep every
invariant (inputs unchanged, one date and phone format or a flag, every gap flagged, no network).
"""

from __future__ import annotations

import csv
import hashlib
import json
import shlex
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


def digests(folder: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="process-test-"))
        self.data = self.tmp / "data"
        shutil.copytree(SAMPLES, self.data)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_spec(self, spec: Path, **kwargs: object) -> tuple[dict, Path]:
        out = self.tmp / ("out-" + spec.stem)
        report = rp.run(self.data, out, spec, **kwargs)
        return report, out

    # -- the fixed reference steps give exactly the reviewed outputs ---------------------------

    def test_reference_steps_match_reviewed_outputs(self) -> None:
        _, out = self.run_spec(REFERENCE)
        for expected in sorted(EXPECTED.rglob("*")):
            if expected.is_file():
                got = out / expected.relative_to(EXPECTED)
                self.assertTrue(got.is_file(), f"missing output {got.name}")
                self.assertEqual(got.read_text(encoding="utf-8"), expected.read_text(encoding="utf-8"),
                                 f"{expected.relative_to(EXPECTED)} differs from the reviewed output")

    def test_reference_rows_people_would_check_by_hand(self) -> None:
        _, out = self.run_spec(REFERENCE)
        spring = read_rows(out / "cleaned" / "spring-signups-sample.csv")
        self.assertEqual(len(spring), 11)
        avery = [r for r in spring if r["First Name"] == "Avery"]
        self.assertEqual(len(avery), 1, "the exact duplicate is removed")
        self.assertEqual(avery[0]["Phone"], "+12125550142")
        self.assertEqual(avery[0]["Signup Date"], "2026-03-14")
        jordan = [r for r in spring if r["Last Name"].lower() == "okafor"]
        self.assertEqual(len(jordan), 1, "same email after tidying is one person")
        self.assertEqual(jordan[0]["Email"], "jordan.okafor@example.org")
        self.assertEqual(jordan[0]["Notes"], "Prefers mornings", "a blank is filled from the duplicate")
        sam = [r for r in spring if r["First Name"] == "Sam"]
        self.assertEqual(len(sam), 1, "same name and phone is one person")
        self.assertEqual(sam[0]["Email"], "sam.rivera@example.org")
        self.assertEqual(len([r for r in spring if r["First Name"] == "Alex"]), 2, "same name only is kept for a person")
        casey = [r for r in spring if r["First Name"] == "Casey"][0]
        self.assertEqual(casey["Phone"], "+16465550110 ext 12")
        flags = read_rows(out / "flags.csv")
        issues = {(f["file"], f["row"], f["issue"]) for f in flags}
        spring_name = "spring-signups-sample.csv"
        for row, issue in (("9", "invalid_date"), ("13", "invalid_date"), ("7", "invalid_phone"),
                           ("8", "invalid_email"), ("9", "missing_contact"), ("14", "missing_required"),
                           ("12", "possible_duplicate"), ("5", "duplicate_conflict")):
            self.assertIn((spring_name, row, issue), issues)
        fall = read_rows(out / "cleaned" / "fall-fair-signups-sample.csv")
        self.assertEqual([r["Date Signed Up"] for r in fall][:3], ["2026-10-25", "2026-11-03", "2026-11-07"],
                         "a day above 12 shows the column is day-first")
        winter = {f["row"]: f["issue"] for f in flags if f["file"] == "winter-signups-sample.csv" and "date" in f["issue"]}
        self.assertEqual(winter, {"1": "ambiguous_date", "2": "ambiguous_date", "3": "date_fixed"})
        self.assertTrue(any(f["issue"] == "also_in_other_file" for f in flags))

    # -- this package's own steps keep every invariant ------------------------------------------

    def test_package_steps_keep_invariants(self) -> None:
        before = digests(self.data)
        report, out = self.run_spec(SPEC)
        self.assertEqual(digests(self.data), before, "input files never change")
        flags = read_rows(out / "flags.csv")
        flagged = {(f["file"], f["column"], f["original"]) for f in flags if f["needs_person"] == "yes"}
        spec = rp.load_spec(SPEC)
        ops = {s["operation"] for s in spec["steps"]}
        for cleaned in sorted((out / "cleaned").glob("*.csv")):
            source = next(p.name for p in self.data.iterdir() if p.stem == cleaned.stem)
            rows = read_rows(cleaned)
            table = rp.read_table(self.data / source)
            roles = rp.column_roles(table["header"], table["rows"], rp.step_params(spec, "profile_columns") or {})
            emails = []
            for row in rows:
                values = list(row.values())
                for header, role, value in zip(table["header"], roles, values):
                    if not value:
                        continue
                    if role == "date" and "normalize_dates" in ops:
                        ok = len(value) == 10 and value[4] == "-" and value[7] == "-"
                        self.assertTrue(ok or (source, header, value) in flagged, f"{source}: date {value!r} neither fixed nor flagged")
                    if role == "phone" and "normalize_phones" in ops:
                        self.assertTrue(value.startswith("+") or (source, header, value) in flagged,
                                        f"{source}: phone {value!r} neither fixed nor flagged")
                    if role == "email":
                        emails.append(value.lower())
                if "flag_missing_fields" in ops:
                    has_contact = any(v for h, r, v in zip(table["header"], roles, values) if r in ("email", "phone"))
                    if not has_contact:
                        self.assertTrue(any(f["file"] == source and f["issue"] == "missing_contact" for f in flags))
            if "deduplicate" in ops:
                valid = [e for e in emails if rp.looks_like_email(e)]
                self.assertEqual(len(valid), len(set(valid)), f"{source}: duplicate email left in the cleaned copy")
        report_text = (out / "report.md").read_text(encoding="utf-8")
        self.assertNotIn("@", report_text, "the report holds counts, never addresses")
        receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
        self.assertTrue(all(i["unchanged"] for i in receipt["inputs"]))
        self.assertEqual(report["totals"]["rows_in"], 23)

    def test_no_network_by_default(self) -> None:
        def refuse(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("the process opened a network connection")

        with mock.patch.object(socket, "socket", refuse), mock.patch.object(socket, "create_connection", refuse):
            self.run_spec(SPEC)

    def test_output_inside_input_is_refused(self) -> None:
        with self.assertRaises(rp.ProcessError):
            rp.run(self.data, self.data / "results", SPEC)

    def test_unknown_operation_is_refused(self) -> None:
        bad = json.loads(SPEC.read_text(encoding="utf-8"))
        bad["steps"].insert(0, {"operation": "upload_to_cloud", "params": {}})
        path = self.tmp / "bad.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(rp.ProcessError):
            rp.load_spec(path)

    # -- the optional summary hook (off by default; the person's own command; counts only) -----------

    def hook(self, script: str) -> str:
        return f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"

    def test_summary_hook_is_off_by_default(self) -> None:
        report, out = self.run_spec(SPEC)
        self.assertIn("fixed template", report["summary"]["written_by"])
        receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
        self.assertFalse(receipt["summary_hook"]["used"])

    def test_summary_hook_gets_counts_only_and_its_text_is_checked(self) -> None:
        # The numbers come from this package's own run, since its steps decide how many rows it keeps.
        totals = self.run_spec(SPEC)[0]["totals"]
        self.assertEqual(totals["rows_in"], 23)
        good = (f"The process read {totals['rows_in']} rows and kept {totals['rows_out']}. "
                "A person should check the flagged rows next.")
        script = ("import sys; data = sys.stdin.read(); "
                  "assert '@' not in data and 'Avery' not in data and 'rows_in' in data; "
                  f"print({good!r})")
        report, out = self.run_spec(SPEC, summary_command=self.hook(script))
        self.assertEqual(report["summary"]["text"], good)
        self.assertIn("your summary command", report["summary"]["written_by"])
        kept = sum(len(read_rows(p)) for p in (out / "cleaned").glob("*.csv"))
        self.assertEqual(totals["rows_out"], kept, "the count given to the command is the rows really kept")
        bad = "The process read 23 rows and found 977 problems for 42 volunteers."
        report, _ = self.run_spec(SPEC, summary_command=self.hook(f"print({bad!r})"))
        self.assertNotEqual(report["summary"]["text"], bad)
        self.assertIn("failed its checks", report["summary"]["written_by"])

    def test_summary_hook_on_the_reference_steps_keeps_the_reviewed_counts(self) -> None:
        good = "The process read 23 rows and kept 19. A person should check the flagged rows next."
        script = ("import sys; data = sys.stdin.read(); "
                  "assert '@' not in data and 'Avery' not in data and 'rows_in' in data; "
                  f"print({good!r})")
        report, _ = self.run_spec(REFERENCE, summary_command=self.hook(script))
        self.assertEqual(report["summary"]["text"], good)

    def test_a_failing_summary_command_leaves_the_fixed_text(self) -> None:
        report, _ = self.run_spec(SPEC, summary_command=self.hook("import sys; sys.exit(3)"))
        self.assertIn("fixed template", report["summary"]["written_by"])
        self.assertIn("exited 3", report["summary"]["written_by"])


if __name__ == "__main__":
    unittest.main()
