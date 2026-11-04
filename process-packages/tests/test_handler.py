"""Tests for the B4 handler (no model, no Docker, no network).

    python3 -m unittest discover -s tests -v        (from the process-packages folder)
"""

from __future__ import annotations

import hashlib
import itertools
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from process_packages import (  # noqa: E402
    ProcessRequestError,
    SelfReviewRefused,
    build_process,
    draft_piece,
    finalize_catalog_record,
    review_package,
    reuse_match,
    reuse_signature,
)
from process_packages import tabular  # noqa: E402

FIRST = json.loads((ROOT / "requests" / "first-process.json").read_text(encoding="utf-8"))
REWORDED = ("We need something reusable that tidies our volunteer registration sheets: get rid of double entries, "
            "standardize the dates and phone numbers, and point out anyone missing an email or phone, plus a brief summary.")


class RunnerTestsForEveryStepChoice(unittest.TestCase):
    """A package ships the runner's tests with its own process.json, so they must hold for any steps a request can ask for."""

    def test_the_shipped_runner_tests_pass_for_every_choice_of_operations(self) -> None:
        reuse_ops = sorted(tabular.REUSE_TO_OPERATION)
        for size in range(len(reuse_ops) + 1):
            for chosen in itertools.combinations(reuse_ops, size):
                with self.subTest(operations=chosen), tempfile.TemporaryDirectory() as folder:
                    code = Path(folder) / "code"
                    shutil.copytree(ROOT / "runner", code, ignore=shutil.ignore_patterns("__pycache__"))
                    steps, _ = tabular.combine_steps("clean our list", [], list(chosen))
                    spec = tabular.process_spec("process-test", "Test list", steps)
                    (code / "process.json").write_text(json.dumps(spec), encoding="utf-8")
                    done = subprocess.run([sys.executable, "-W", "error", "-B", "-m", "unittest", "discover", "-s", "tests"],
                                          cwd=code, capture_output=True, text=True, check=False, timeout=300)
                    self.assertEqual(done.returncode, 0, done.stderr[-1500:])


class ReuseKeyTests(unittest.TestCase):
    def test_reworded_request_gets_the_same_key(self) -> None:
        a = reuse_signature(FIRST["request"]["description"])
        b = reuse_signature(REWORDED)
        self.assertIsNotNone(a["key"])
        self.assertEqual(a["key"], b["key"])
        self.assertEqual(reuse_match(b, a)["decision"], "exact")

    def test_different_steps_change_the_key_and_a_superset_is_reusable(self) -> None:
        full = reuse_signature(FIRST["request"]["description"])
        dedupe_only = reuse_signature("Clean up our volunteer sign-up spreadsheet: just remove the duplicates please")
        donor = reuse_signature(FIRST["request"]["description"].replace("volunteer sign-up", "donor"))
        self.assertNotEqual(donor["key"], full["key"], "the subject is part of the key")
        self.assertEqual(reuse_match(donor, full)["decision"], "none")
        self.assertNotEqual(full["key"], dedupe_only["key"])
        self.assertEqual(reuse_match(dedupe_only, full), {"decision": "superset", "score": 0.25,
                                                          "extra_operations": ["dates", "missing_contact", "phones"]})
        self.assertEqual(reuse_match(full, dedupe_only)["decision"], "none")

    def test_unrelated_requests_get_no_key(self) -> None:
        self.assertIsNone(reuse_signature("Translate our flyer into Spanish")["key"])
        hand = reuse_signature("A process to read, summarize and analyze handwritten case files")
        self.assertEqual(hand["class"], "handwritten_case_files")


class RequestAndPlanTests(unittest.TestCase):
    def test_personal_data_in_the_request_is_refused_before_anything_is_built(self) -> None:
        req = dict(FIRST["request"], description="Clean our sheets of duplicates; my email is pat.doe@realmail.com, call 212-555-0199")
        with self.assertRaises(ProcessRequestError) as ctx:
            build_process(req, FIRST["plan_part"], out_dir=Path(tempfile.mkdtemp()), run_docker=False)
        self.assertEqual(ctx.exception.outcome, "refused")

    def test_plan_cycles_and_unknown_dependencies_are_refused(self) -> None:
        cyc = {"pieces": [{"id": "a", "title": "Profile", "depends_on": ["b"]}, {"id": "b", "title": "Report", "depends_on": ["a"]}]}
        unknown = {"pieces": [{"id": "a", "title": "Profile", "depends_on": ["z"]}]}
        for plan in (cyc, unknown):
            with self.assertRaises(ProcessRequestError):
                build_process(FIRST["request"], plan, out_dir=Path(tempfile.mkdtemp()), run_docker=False)

    def test_information_requests_are_not_process_requests(self) -> None:
        req = dict(FIRST["request"], output_type="information")
        with self.assertRaises(ProcessRequestError):
            build_process(req, FIRST["plan_part"], out_dir=Path(tempfile.mkdtemp()), run_docker=False)

    def test_each_piece_maps_to_the_operations_its_own_words_name(self) -> None:
        names = {p["id"]: [s["operation"] for s in draft_piece(FIRST["request"], p)["steps"]] for p in FIRST["plan_part"]["pieces"]}
        self.assertEqual(names, {"p1-profile": ["profile_columns"], "p2-dedupe": ["deduplicate"],
                                 "p3-formats": ["normalize_dates", "normalize_phones"],
                                 "p4-missing": ["flag_missing_fields"], "p5-report": ["write_report"]})
        piece = draft_piece(FIRST["request"], FIRST["plan_part"]["pieces"][1])
        self.assertEqual(piece["steps"][0]["instruction"], tabular.DEFAULT_INSTRUCTIONS["deduplicate"])
        self.assertEqual(piece["steps"][0]["written_by"], "fixed template")


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="b4-handler-"))

        def refuse(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("the build opened a network connection")

        with mock.patch.object(socket, "socket", refuse), mock.patch.object(socket, "create_connection", refuse):
            cls.result = build_process(FIRST["request"], FIRST["plan_part"], out_dir=cls.tmp / "a", run_docker=False,
                                       builder={"id": "builder-1", "key_id": "builder-1-key"})

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_returns_the_stable_interface(self) -> None:
        for key in ("bundle_path", "bundle_sha256", "catalog_record", "task_template_record", "test_report"):
            self.assertIn(key, self.result)
        self.assertEqual(hashlib.sha256(Path(self.result["bundle_path"]).read_bytes()).hexdigest(), self.result["bundle_sha256"])
        self.assertTrue(self.result["test_report"]["passed"], self.result["test_report"]["failures"])
        catalog = self.result["catalog_record"]
        self.assertEqual(catalog["store"], "eranos.catalog")
        self.assertIn("status:quarantined", catalog["tags"], "nothing is public before an independent review")
        self.assertEqual(catalog["value"]["blob_sha256"], self.result["bundle_sha256"])
        spec = self.result["task_template_record"]["value"]["task_spec"]
        self.assertTrue(spec["brief"]["template_id"].endswith(".run-cleaning-process"))
        self.assertEqual(spec["brief"]["execution"]["model_use"], "none")
        self.assertIn(f"reuse:{self.result['reuse']['key']}", self.result["solution_record"]["tags"])

    def test_no_model_is_called_and_the_report_says_so(self) -> None:
        report = self.result["test_report"]
        self.assertEqual(report["model_calls"], 0)
        self.assertEqual(report["text_written_by"], "fixed templates; no model was called")
        for key in ("model_receipts", "model_usage", "model_written"):
            self.assertNotIn(key, report)
        self.assertEqual({p["claimed_by"] for p in report["pieces"]}, {"local-worker"})

    def test_every_check_ran(self) -> None:
        checks = self.result["test_report"]["checks"]
        for name in ("library_pack_checks", "instantiate", "verify_kit", "unit_tests", "persona_lint", "supply_chain_scan", "public_check"):
            self.assertTrue(checks[name]["passed"], name)
        self.assertGreaterEqual(checks["persona_lint"]["targets_passing"], 8)
        self.assertEqual(checks["unit_tests"]["tests"], 10)

    def test_rebuild_is_byte_identical(self) -> None:
        again = build_process(FIRST["request"], FIRST["plan_part"], out_dir=self.tmp / "b", run_docker=False,
                              builder={"id": "builder-1", "key_id": "builder-1-key"})
        self.assertEqual(again["bundle_sha256"], self.result["bundle_sha256"])

    def test_self_review_is_refused_and_a_different_reviewer_publishes(self) -> None:
        build = json.loads((Path(self.result["package_dir"]).parents[1] / (self.result["test_report"]["pack_id"] + ".build.json")).read_text())
        build["bundle_sha256"] = self.result["bundle_sha256"]
        for reviewer in ({"id": "builder-1", "key_id": "other-key"}, {"id": "other", "key_id": "builder-1-key"}):
            with self.assertRaises(SelfReviewRefused):
                review_package(Path(self.result["bundle_path"]), build, reviewer, run_docker=False)
        review = review_package(Path(self.result["bundle_path"]), build, {"id": "reviewer-2", "key_id": "reviewer-2-key"}, run_docker=False)
        self.assertEqual(review["verdict"], "approved")
        public = finalize_catalog_record(build["catalog_record"], review)
        self.assertEqual(public["visibility_scope"], "public_commons")
        self.assertIn("status:verified", public["tags"])
        self.assertNotEqual(public["value"]["reviewed_by"], public["value"]["kit"]["drafted_by"])

    def test_a_workers_piece_output_is_used(self) -> None:
        plan = json.loads(json.dumps(FIRST["plan_part"]))
        plan["pieces"][1]["output"] = {"steps": [{"operation": "deduplicate", "instruction": "The process removes repeated rows.",
                                                  "written_by": "worker"}]}
        res = build_process(FIRST["request"], plan, out_dir=self.tmp / "d", run_docker=False)
        piece = next(p for p in res["test_report"]["pieces"] if p["piece_id"] == "p2-dedupe")
        self.assertEqual(piece["output"]["notes"], ["drafted by the piece's own worker"])
        self.assertEqual(piece["output"]["steps"][0]["instruction"], "The process removes repeated rows.")


if __name__ == "__main__":
    unittest.main()
