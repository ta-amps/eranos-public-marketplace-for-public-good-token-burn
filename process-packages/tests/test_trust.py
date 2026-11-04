"""Review M3 and the owner's wording rule, for the worker-loop handler (eranos_handler.py).

No network, no Docker: the local model is scripted and the container test is off (B4_DOCKER_TEST=0);
the container test's own environment and limits are checked by capturing its command.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_handler import FIRST  # noqa: E402

from process_packages import checks  # noqa: E402

REQUEST = {"request_id": "rq-film-0001", "text": FIRST["request"]["description"], "organization_type": "Volunteer center",
           "links": [], "output_type": "process", "frequency": "one-off"}
PART = {"part": 1, "route": "process", "text": FIRST["request"]["description"], "legal": False}
BANNED = re.compile(r"synthetic", re.IGNORECASE)
# The retired model family, stored only as SHA-256 hashes of its names so this file never spells them.
RETIRED_MODEL_HASHES = frozenset({"fc5a1047f5919892fcdf8aa79ea5d6bb6531b5c176939ef0110906cb225941c1",
                                   "76e3c7bfe641ea125c0c2e1c5f89349e17b352ed128d528de2443794e7acf870"})


def names_retired_model(text: str) -> bool:
    return any(hashlib.sha256(t.encode()).hexdigest() in RETIRED_MODEL_HASHES for t in re.findall(r"[a-z]+", text.lower()))


def load_handler(out: Path):
    os.environ["B4_OUT_DIR"] = str(out)
    os.environ["B4_DOCKER_TEST"] = "0"
    spec = importlib.util.spec_from_file_location(f"b4_handler_{os.getpid()}", ROOT / "eranos_handler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tar_bytes(entries: list[tuple[tarfile.TarInfo, bytes | None]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for info, data in entries:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return buf.getvalue()


def file_info(name: str, data: bytes) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    return info


class TrustTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="b4-trust-"))
        cls.h = load_handler(cls.tmp / "out")
        cls.built = cls.h.build_process(REQUEST, PART)
        cls.bundle = Path(cls.built["bundle_path"]).read_bytes()
        cls.sha = hashlib.sha256(cls.bundle).hexdigest()
        cls.records = {"catalog_record": {"value": cls.built["catalog_record"]["value"], "owner_key_id": "k-builder"},
                       "task_template_record": {"value": cls.built["task_template_record"]["value"], "owner_key_id": "k-builder"}}

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def reviewer_copy(self, data: bytes | None = None) -> Path:
        folder = Path(tempfile.mkdtemp(prefix="reviewer-", dir=self.tmp))
        path = folder / "fetched.tar.gz"
        path.write_bytes(self.bundle if data is None else data)
        return path

    def package(self, data: bytes | None = None) -> dict:
        return {"blob_sha256": hashlib.sha256(self.bundle if data is None else data).hexdigest(),
                "test_report": {"bundle": {"path": "/etc/passwd"}, "pack_id": "../../evil"}}

    def review(self, data: bytes | None = None, **kw):
        kw.setdefault("bundle_path", self.reviewer_copy(data))
        kw.setdefault("builder_key_id", "k-builder")
        kw.setdefault("trusted_builder_keys", {"k-builder"})
        return self.h.review_process(self.package(data), kw.pop("request", REQUEST), PART, **kw)

    # ids, stores and keys come from the request, never from build output
    def test_ids_stores_and_keys_derive_from_the_request(self) -> None:
        ids = self.h.expected_records(REQUEST, PART)
        self.assertEqual(self.built["ids"], ids)
        self.assertEqual(self.built["catalog_record"]["store"], "eranos.processes")
        self.assertEqual(self.built["catalog_record"]["key"], f"rq-film-0001.1.{ids['kit_id']}")
        self.assertEqual(self.built["task_template_record"]["key"], f"rq-film-0001.1.{ids['pack_id']}")
        self.assertIn("request:rq-film-0001", self.built["catalog_record"]["value"]["kit"]["tags"])
        self.assertEqual(self.built["task_template_record"]["value"]["request_id"], "rq-film-0001")

    def test_review_of_the_real_bundle_passes_and_returns_record_digests(self) -> None:
        verdict = self.review(records=self.records)
        self.assertTrue(verdict["passed"], verdict["checks"])
        v = verdict["verified"]
        self.assertEqual(v["bundle_sha256"], self.sha)
        self.assertEqual(v["catalog_record"]["key"], self.built["catalog_record"]["key"])
        self.assertEqual(v["catalog_record"]["value_sha256"], self.h.record_digest(self.records["catalog_record"]["value"]))
        self.assertEqual(self.h._builderless(v["catalog_value"]), self.h._builderless(self.records["catalog_record"]["value"]))
        self.assertEqual(v["template_value"], self.records["task_template_record"]["value"])

    def test_review_ignores_paths_and_ids_in_build_output(self) -> None:
        verdict = self.review()
        self.assertTrue(verdict["passed"], verdict["checks"])  # the /etc/passwd and ../../evil in the output were never used

    def test_review_needs_a_bundle_the_reviewer_fetched(self) -> None:
        verdict = self.h.review_process(self.package(), REQUEST, PART, builder_key_id="k-builder", trusted_builder_keys={"k-builder"})
        self.assertFalse(verdict["passed"])

    def test_review_needs_trusted_builder_keys(self) -> None:
        for trusted in (None, set()):
            verdict = self.review(trusted_builder_keys=trusted)
            self.assertFalse(verdict["passed"])
            self.assertIn("ERANOS_PROCESS_BUILDER_KEYS", verdict["checks"][0])
        self.assertFalse(self.review(builder_key_id="k-intruder")["passed"])

    def test_review_refuses_a_symlinked_bundle_path(self) -> None:
        real = self.reviewer_copy()
        link = real.with_name("link.tar.gz")
        link.symlink_to(real)
        self.assertFalse(self.review(bundle_path=link)["passed"])

    def test_review_refuses_a_digest_mismatch(self) -> None:
        verdict = self.h.review_process({"blob_sha256": "0" * 64}, REQUEST, PART, bundle_path=self.reviewer_copy(),
                                        builder_key_id="k-builder", trusted_builder_keys={"k-builder"})
        self.assertFalse(verdict["passed"])

    def test_review_refuses_traversal_links_and_another_folder(self) -> None:
        pack = self.built["ids"]["pack_id"]
        link = tarfile.TarInfo(f"{pack}/code/run_process.py")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        for data in (tar_bytes([(file_info(f"{pack}/../evil.txt", b"x"), b"x")]),
                     tar_bytes([(link, None)]),
                     tar_bytes([(file_info("process-sheet-cleaning-000000/README.md", b"x"), b"x")])):
            verdict = self.review(data)
            self.assertFalse(verdict["passed"], verdict["checks"])

    def test_review_refuses_a_changed_runner(self) -> None:
        with tarfile.open(fileobj=io.BytesIO(self.bundle), mode="r:gz") as tar:
            members = [(m, tar.extractfile(m).read() if m.isfile() else None) for m in tar.getmembers()]
        changed = []
        for info, data in members:
            if info.name.endswith("code/run_process.py"):
                data = data + b"\nimport socket\n"
                info = copy.copy(info)
                info.size = len(data)
            changed.append((info, data))
        verdict = self.review(tar_bytes(changed))
        self.assertFalse(verdict["passed"])
        self.assertIn("vetted files differ", verdict["checks"][0])

    def test_review_refuses_records_or_bundles_of_another_request(self) -> None:
        other = copy.deepcopy(self.records)
        kit = other["catalog_record"]["value"]["kit"]
        kit["tags"] = [t.replace("rq-film-0001", "rq-other") for t in kit["tags"]]
        self.assertFalse(self.review(records=other)["passed"])
        other = copy.deepcopy(self.records)
        other["task_template_record"]["value"]["request_id"] = "rq-other"
        self.assertFalse(self.review(records=other)["passed"])
        self.assertFalse(self.review(request={**REQUEST, "request_id": "rq-other-0002"})["passed"])

    # review B4: package config can never reach Docker, and the files are exactly the generated list
    def test_override_and_env_files_fail_closed(self) -> None:
        pack = self.built["ids"]["pack_id"]
        with tarfile.open(fileobj=io.BytesIO(self.bundle), mode="r:gz") as tar:
            members = [(m, tar.extractfile(m).read() if m.isfile() else None) for m in tar.getmembers()]
        override = b"services:\n  test:\n    network_mode: host\n    volumes: ['/etc/hostname:/canary:ro']\n"
        for extra_name, data in ((f"{pack}/code/compose.override.yaml", override), (f"{pack}/code/.env", b"COMPOSE_FILE=x.yaml\n"),
                                 (f"{pack}/code/notes.txt", b"anything extra")):
            bad = tar_bytes([*members, (file_info(extra_name, data), data)])
            verdict = self.review(bad)
            self.assertFalse(verdict["passed"], extra_name)
            self.assertIn("not the generated list", verdict["checks"][0])
            with self.assertRaises(self.h.ReviewRefused):
                self.h._members(bad, pack)  # the reviewer probe's own call fails closed too
        scan_dir = Path(tempfile.mkdtemp(prefix="scan-", dir=self.tmp))
        with tarfile.open(fileobj=io.BytesIO(self.bundle), mode="r:gz") as tar:
            tar.extractall(scan_dir, filter="data")
        (scan_dir / pack / "code" / "compose.override.yaml").write_bytes(override)
        images = json.loads((ROOT / "images.lock.json").read_text(encoding="utf-8"))
        self.assertFalse(checks.supply_chain_scan(scan_dir / pack / "code", images)["passed"])

    def test_the_reviewer_runs_plain_docker_with_its_own_flags(self) -> None:
        seen = []

        class Done:
            returncode, stdout, stderr = 0, "", "Ran 9 tests in 0.1s\n\nOK\n"

        real_run = checks.subprocess.run

        def fake_run(cmd, **kw):
            if "docker" not in cmd:
                return real_run(cmd, **kw)  # the kit checks run for real
            seen.append(list(cmd))
            return Done()

        with mock.patch.object(checks.subprocess, "run", fake_run), mock.patch.object(checks.shutil, "which", lambda _: "/usr/bin/docker"), \
                mock.patch.dict(os.environ, {"B4_DOCKER_TEST": "1"}):
            verdict = self.review()
        self.assertTrue(verdict["passed"], verdict["checks"])
        runs = [c for c in seen if "run" in c and "docker" in c]
        self.assertTrue(runs)
        joined = " ".join(runs[0])
        self.assertNotIn("compose", joined)
        for flag in ("--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges", "--pids-limit 256",
                     "--memory 1g", "--cpus 1", "--user 65534:65534", "--pull never", "/process,readonly"):
            self.assertIn(flag, joined)
        self.assertTrue(any(c[:3] == ["docker", "rm", "-f"] for c in seen), "the container is always removed")

    def test_a_timeout_kills_and_removes_the_container(self) -> None:
        seen = []

        def fake_run(cmd, **kw):
            seen.append(list(cmd))
            if "run" in cmd and "--network" in cmd:
                raise checks.subprocess.TimeoutExpired(cmd, kw.get("timeout"))

            class Done:
                returncode, stdout, stderr = 0, "", ""
            return Done()

        with mock.patch.object(checks.subprocess, "run", fake_run), mock.patch.object(checks.shutil, "which", lambda _: "/usr/bin/docker"):
            result = checks.sandbox_test(Path(self.built["package_dir"]) / "code", "python@sha256:" + "0" * 64, timeout=60)
            built = checks.docker_test(Path(self.built["bundle_path"]), self.built["ids"]["pack_id"], workdir=self.tmp, timeout=60)
        self.assertFalse(result["passed"])
        self.assertTrue(result["timed_out"])
        self.assertTrue(any(c[:3] == ["docker", "rm", "-f"] for c in seen))
        self.assertTrue(any("down" in c for c in seen), "compose down runs in finally for the builder's check too")
        self.assertIn("passed", built)

    def test_records_must_be_written_by_the_builds_key(self) -> None:
        other = copy.deepcopy(self.records)
        other["catalog_record"]["owner_key_id"] = "k-somebody-else"
        self.assertFalse(self.review(records=other)["passed"])
        self.assertFalse(self.review(records=self.records, builder_key_id="k-other")["passed"])
        self.assertFalse(self.review(records=self.records, trusted_builder_keys={"k-trusted"})["passed"])
        self.assertTrue(self.review(records=self.records, trusted_builder_keys={"k-builder"})["passed"])
        self.assertFalse(self.review(records=self.records, builder_account_id="acct-a", trusted_account_id="acct-b")["passed"])

    def test_values_read_back_with_integral_floats_still_match(self) -> None:
        def as_tessera(value):
            if isinstance(value, float) and value.is_integer():
                return int(value)
            if isinstance(value, dict):
                return {k: as_tessera(v) for k, v in value.items()}
            if isinstance(value, list):
                return [as_tessera(v) for v in value]
            return value

        read_back = {n: {**r, "value": as_tessera(r["value"])} for n, r in self.records.items()}
        self.assertTrue(self.review(records=read_back)["passed"])

    def test_a_planted_or_edited_draft_is_refused(self) -> None:
        other = copy.deepcopy(self.records)
        other["catalog_record"]["value"]["kit"]["summary"] = "A different promise than the bundle makes."
        self.assertFalse(self.review(records=other)["passed"])
        other = copy.deepcopy(self.records)
        other["task_template_record"]["value"]["title"] = "Another title"
        self.assertFalse(self.review(records=other)["passed"])

    def test_extra_reuse_or_request_tags_are_refused(self) -> None:
        for extra in ("reuse:proc2-0000000000000000", "request:rq-other"):
            other = copy.deepcopy(self.records)
            other["catalog_record"]["value"]["kit"]["tags"].append(extra)
            verdict = self.review(records=other)
            self.assertFalse(verdict["passed"])
            self.assertIn("exactly", verdict["checks"][0])

    def test_a_donor_request_gets_its_own_reuse_key(self) -> None:
        donor = dict(REQUEST, text=REQUEST["text"].replace("volunteer sign-up", "donor"))
        self.assertNotEqual(self.h.expected_records(donor, {**PART, "text": donor["text"]})["reuse_key"], self.built["ids"]["reuse_key"])

    # package tests never see the caller's environment
    def test_package_tests_get_only_a_minimal_environment(self) -> None:
        seen = []

        class Done:
            returncode, stdout, stderr = 0, "", "Ran 9 tests in 0.1s\n\nOK\n"

        def fake_run(cmd, **kw):
            seen.append((cmd, kw.get("env"), kw.get("timeout")))
            return Done()

        with mock.patch.dict(os.environ, {"TESSERA_KEY": "never-passed", "HERMA_ADMIN_KEY": "never-passed"}), \
                mock.patch.object(checks.subprocess, "run", fake_run), mock.patch.object(checks.shutil, "which", lambda _: "/usr/bin/docker"):
            checks.unit_tests(Path(self.built["package_dir"]) / "code")
            checks.docker_test(Path(self.built["bundle_path"]), self.built["ids"]["pack_id"], workdir=self.tmp)
        self.assertTrue(seen)
        for cmd, env, timeout in seen:
            self.assertIsNotNone(env, cmd)
            self.assertNotIn("TESSERA_KEY", env)
            self.assertNotIn("HERMA_ADMIN_KEY", env)
            self.assertLessEqual(set(env), {"PATH", "HOME", "LANG", "PYTHONDONTWRITEBYTECODE", "COMPOSE_PROJECT_NAME", "DOCKER_BUILDKIT"})
            self.assertIsNotNone(timeout)

    def test_the_container_test_has_no_network_and_has_limits(self) -> None:
        compose = (Path(self.built["package_dir"]) / "code" / "compose.yaml").read_text(encoding="utf-8")
        block = compose.split("\n  test:\n", 1)[1]
        for needed in ("network_mode: none", "read_only: true", "cap_drop: [ALL]", "mem_limit: 1g", "cpus: 1.0",
                       "pids_limit: 256", "pull_policy: build"):
            self.assertIn(needed, block)

    # owner, Nov 1: the package is model-free by default and never names a vendor model
    def bundle_texts(self) -> list[tuple[str, str]]:
        with tarfile.open(fileobj=io.BytesIO(self.bundle), mode="r:gz") as tar:
            return [(m.name, tar.extractfile(m).read().decode("utf-8", "replace") if m.isfile() else "") for m in tar.getmembers()]

    def test_the_retired_model_family_is_named_nowhere_in_the_bundle(self) -> None:
        hits = [name for name, text in self.bundle_texts() if names_retired_model(name) or names_retired_model(text)]
        self.assertEqual(hits, [])

    def test_no_build_record_names_the_retired_model_family(self) -> None:
        for name in ("catalog_record", "task_template_record", "test_report", "solution_record", "ids"):
            self.assertFalse(names_retired_model(json.dumps(self.built[name], default=str)), name)
        written = list((self.tmp / "out" / "runs").rglob("*.build.json"))
        self.assertTrue(written)
        for path in written:
            self.assertFalse(names_retired_model(path.read_text(encoding="utf-8")), path.name)
        self.assertEqual(self.built["test_report"]["model_calls"], 0)
        self.assertTrue(names_retired_model("built " + "ol" + "lama run"), "the detector itself works")

    def test_the_package_is_model_free_by_default(self) -> None:
        code = Path(self.built["package_dir"]) / "code"
        compose = (code / "compose.yaml").read_text(encoding="utf-8")
        services = re.findall(r"(?m)^  ([a-z][a-z0-9-]*):\s*$", compose)
        self.assertEqual(services, ["run", "test"])
        self.assertNotIn("networks:", compose)
        spec = json.loads((code / "process.json").read_text(encoding="utf-8"))
        self.assertNotIn("model", spec)
        self.assertEqual(spec["summary_hook"]["default"], "off")
        install = (code / "INSTALL.md").read_text(encoding="utf-8")
        self.assertIn("--summary-command", install)
        self.assertIn("your own agent", install)

    def test_visible_docs_say_task_objects_and_tasks(self) -> None:
        words = re.compile(r"\b(?:nouns?|verbs?)\b", re.IGNORECASE)
        hits = [f"{name}: {words.search(text).group(0)}" for name, text in self.bundle_texts()
                if name.endswith(".md") and words.search(text)]
        self.assertEqual(hits, [])

    # the owner's rule: the word never appears in anything a user or agent reads
    def test_the_banned_word_appears_nowhere_in_the_bundle_or_records(self) -> None:
        hits = []
        with tarfile.open(fileobj=io.BytesIO(self.bundle), mode="r:gz") as tar:
            for m in tar.getmembers():
                if BANNED.search(m.name):
                    hits.append(m.name)
                if m.isfile() and BANNED.search(tar.extractfile(m).read().decode("utf-8", "replace")):
                    hits.append(f"{m.name} (content)")
        for name in ("catalog_record", "task_template_record", "test_report"):
            if BANNED.search(json.dumps(self.built[name], default=str)):
                hits.append(name)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
