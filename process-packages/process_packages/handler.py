"""build_process(request, plan_part) -> dict: a process request becomes a generated, tested package.

Stable interface for the worker loop (B1). See README.md for the contract; this module is the code.
Nothing here writes to a hosted service, posts a request or calls any model: the text comes from
fixed templates, and the only outside process is the local Docker daemon for the container test.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from . import checks, pack, package, reuse, scans, tabular

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "out"
TRACKS_ROOT = ROOT / "vendor" / "eranos_verify" / "tracks"
DEFAULT_TRACK = {"tabular_cleaning": "donor-stewardship-and-privacy", "handwritten_case_files": "statement-transcription"}
INTERFACE_VERSION = "b4.build_process.v1"
PRODUCER = "surface:eranos"
CATALOG_STORE, SOLUTIONS_STORE, TEMPLATES_STORE = "eranos.catalog", "eranos.solutions", "eranos.verb_templates"
BUCKET = "eranos-process-packages"


class ProcessRequestError(ValueError):
    """The request or plan cannot become a process package; nothing was built. `reason` is safe to show."""

    def __init__(self, reason: str, outcome: str = "blocked") -> None:
        super().__init__(reason)
        self.reason, self.outcome = reason, outcome


class SelfReviewRefused(PermissionError):
    """The reviewer is the builder (same id or same key); the review is not recorded."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def privacy_findings(text: str) -> list[str]:
    sys.path.insert(0, str(ROOT / "vendor" / "eranos_verify"))
    from eranos.privacy import personal_data_findings  # noqa: PLC0415 (vendored, stdlib only)

    return personal_data_findings({"description": text})


def check_request(request: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise ProcessRequestError("request must be an object {id, description, output_type, frequency}")
    rid, text = str(request.get("id") or "").strip(), str(request.get("description") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,80}", rid):
        raise ProcessRequestError("request.id must be 3 to 81 letters, digits, dots, colons, dashes or underscores")
    if not 20 <= len(text) <= 2000:
        raise ProcessRequestError("request.description must be 20 to 2000 characters")
    output_type = str(request.get("output_type") or "reusable_process")
    if output_type not in ("reusable_process", "process"):
        raise ProcessRequestError(f"output_type {output_type!r} is not a reusable process; information requests go to research")
    found = privacy_findings(text)
    if found:
        raise ProcessRequestError("the description holds personal data (" + "; ".join(found) + "); nothing was built", "refused")
    return {"id": rid, "description": text, "output_type": "reusable_process",
            "frequency": (str(request.get("frequency")).strip() or None) if request.get("frequency") else None}


def check_plan(plan_part: dict[str, Any]) -> list[dict[str, Any]]:
    """The pieces in dependency order; ids unique, depends_on known, no cycles."""
    pieces = (plan_part or {}).get("pieces")
    if not isinstance(pieces, list) or not pieces:
        raise ProcessRequestError("plan_part.pieces must be a non-empty list of {id, title, depends_on}")
    by_id: dict[str, dict[str, Any]] = {}
    for piece in pieces:
        pid = str(piece.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,80}", pid) or pid in by_id:
            raise ProcessRequestError(f"piece id {pid!r} is missing, malformed or repeated")
        if not str(piece.get("title") or "").strip():
            raise ProcessRequestError(f"piece {pid} needs a title")
        by_id[pid] = piece
    order, state = [], {}

    def visit(pid: str) -> None:
        if state.get(pid) == "done":
            return
        if state.get(pid) == "active":
            raise ProcessRequestError(f"plan_part has a dependency cycle through {pid}")
        state[pid] = "active"
        for dep in by_id[pid].get("depends_on") or []:
            if dep not in by_id:
                raise ProcessRequestError(f"piece {pid} depends on unknown piece {dep}")
            visit(dep)
        state[pid] = "done"
        order.append(by_id[pid])

    for pid in by_id:
        visit(pid)
    return order


def piece_output_ok(output: Any, operations: dict[str, str] = tabular.OPERATIONS) -> bool:
    if not isinstance(output, dict) or not isinstance(output.get("steps"), list) or not output["steps"]:
        return False
    return all(isinstance(s, dict) and s.get("operation") in operations
               and not tabular.instruction_problems(str(s.get("instruction", ""))) for s in output["steps"])


def draft_piece(request: dict[str, Any], piece: dict[str, Any]) -> dict[str, Any]:
    """One piece's step logic, for a piece worker (B1 can run pieces on different workers, then pass
    each result back as piece['output'] to build_process). Fixed templates; no model is called."""
    req = check_request(request)
    sig = reuse.signature(req["description"])
    return (scans if scans.fits(sig) else tabular).fixed_piece(piece)


def subject_words(sig: dict[str, Any]) -> tuple[str, str, str]:
    """(slug, title, phrase) from the reuse signature; deterministic."""
    if "volunteer_signups" in sig["subjects"]:
        return ("signup-sheet-cleaner", "Volunteer sign-up sheet cleaning process",
                "cleaning volunteer sign-up spreadsheets")
    subject = sig["subjects"][0].replace("_", " ") if sig["subjects"] else "contact"
    return (f"{subject.split()[0]}-sheet-cleaner".replace("contact-", ""), f"{subject.capitalize()} spreadsheet cleaning process",
            f"cleaning {subject} spreadsheets")


def _tabular_context(req: dict[str, Any], sig: dict[str, Any], steps: list[dict[str, Any]], builder: dict[str, str]) -> dict[str, Any]:
    """Everything the generator writes for the spreadsheet-cleaning class."""
    slug, title, phrase = subject_words(sig)
    pack_id = "process-sheet-cleaning-" + sig["key"].split("-", 1)[1][:6]
    kit_id = "PRC-" + sig["key"].split("-", 1)[1][:6].upper() + "-01"
    ops_text = {"dedupe": "removes duplicates", "dates": "puts dates in one format", "phones": "puts phone numbers in one format",
                "missing_contact": "flags missing contact details"}
    did = [ops_text[o] for o in ["dedupe", "dates", "phones", "missing_contact"] if o in sig["operations"]]
    summary_tail = ", ".join(did[:-1]) + (" and " if len(did) > 1 else "") + did[-1] + ", and writes a short report"
    description = (f"A reusable data-cleaning pipeline for {phrase.removeprefix('cleaning ')}: it {summary_tail}. "
                   "It runs on the organization's own computer or cloud account, so the files never leave it; "
                   "a person decides every flagged row.")
    skill_title = phrase
    skill_description = (f"Use when a coordinator asks to clean {phrase.removeprefix('cleaning ')} (CSV or TSV files) in a local "
                         f"folder: {summary_tail.replace('writes', 'write').replace('removes', 'remove').replace('puts', 'put').replace('flags', 'flag')}; "
                         "reads the files without changing them.")
    howto = {"text": tabular.howto_text(steps), "written_by": "fixed template"}
    skill = {"text": tabular.SKILL_TEXT, "written_by": "fixed template"}
    process_spec = tabular.process_spec(pack_id, title, steps)
    launch_steps = [
        "Docker: ./launch.sh /path/to/your/sheets (or DATA_DIR=/path/to/your/sheets docker compose run --rm run).",
        "Python 3.10 or newer: python3 run_process.py --input /path/to/your/sheets --output results.",
        "Your own agent: open the code folder in Claude Code, Codex, OpenCode, Cursor, Copilot, Gemini CLI, Roo Code or Kiro and ask it to clean the sheets.",
        "Your own cloud account: copy the code folder and the sheets to a VM you control and run the Docker step there.",
        "Check first on the made-up sample sheets (no real data): docker compose run --rm test.",
        "Read results/report.md, then decide every row in results/flags.csv marked needs_person = yes.",
    ]
    ctx = {
        "pack_id": pack_id, "kit_id": kit_id, "slug": slug, "title": title, "pack_phrase": phrase,
        "summary_tail": summary_tail, "description": description, "summary": description,
        "goal": f"Give the organization a reusable, tested process for {phrase} that it runs itself, with every decision about a person left to a person.",
        "target_org": "Small nonprofit that collects volunteer sign-ups in spreadsheets",
        "skill_title": skill_title, "skill_description": skill_description, "skill_text": skill["text"],
        "howto_text": howto["text"], "steps": steps,
        "howto_credit": "Every sentence of this how-to comes from the generator's fixed templates; no model wrote any of it.",
        "process_spec": process_spec, "launch_steps": launch_steps,
        "request": req, "reuse": sig, "kit_content": tabular.kit_content("volunteer sign-up"),
        "provenance_notes": [{"kind": "process_request", "request_id": req["id"],
                              "note": "Built by the process-package generator from a public request with no private information."},
                             {"kind": "builder", "builder": builder["id"],
                              "note": "Built from fixed templates; no model was called, and the process itself uses no model."}],
    }
    return ctx


def build_process(request: dict[str, Any], plan_part: dict[str, Any], *, out_dir: Path | None = None,
                  builder: dict[str, str] | None = None,
                  track_id: str | None = None, run_docker: bool = True,
                  extra_tags: list[str] | None = None) -> dict[str, Any]:
    """Generate, package and test one process. Returns bundle_path, bundle_sha256, catalog_record,
    task_template_record and test_report (plus the documented extras reuse, solution_record, package_dir).

    Raises ProcessRequestError (outcome blocked or refused) when the request or plan cannot be built;
    a failing test does not raise: test_report.passed is False and every failure is listed."""
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    req = check_request(request)
    pieces = check_plan(plan_part)
    sig = reuse.signature(req["description"])
    reading_scans = sig["class"] == scans.CLASS_ID
    if not sig["key"] or sig["class"] not in DEFAULT_TRACK:
        raise ProcessRequestError(f"no tested process class fits this request yet ({sig['text']}); "
                                  "the generator knows spreadsheet cleaning and filling a spreadsheet from readings of scans", "unknown")
    driver = scans if reading_scans else tabular
    builder = builder or {"id": "local-builder", "key_id": "local-builder-key"}
    out = Path(out_dir or DEFAULT_OUT)

    piece_records = []
    for piece in pieces:
        given = piece.get("output")
        if given is not None and piece_output_ok(given, driver.OPERATIONS):
            output = {"piece_id": piece["id"], "title": piece["title"], "steps": given["steps"],
                      "accepted": True, "notes": ["drafted by the piece's own worker"]}
        else:
            output = driver.fixed_piece(piece)
            if given is not None:
                output["notes"].insert(0, "the worker's output failed the checks and was rewritten from the fixed templates")
        piece_records.append({"piece_id": piece["id"], "title": piece["title"], "depends_on": piece.get("depends_on") or [],
                              "claimed_by": piece.get("claimed_by") or builder["id"], "output": output})
    steps, combine_notes = driver.combine_steps(req["description"], [p["output"] for p in piece_records], sig["operations"])
    ctx = scans.context(req, sig, steps) if reading_scans else _tabular_context(req, sig, steps, builder)
    pack_id, kit_id = ctx["pack_id"], ctx["kit_id"]

    packages = out / "packages"
    pack_dir = packages / pack_id
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True)
    images_lock = json.loads((ROOT / "images.lock.json").read_text(encoding="utf-8"))
    harness = write_pack_folder(pack_dir, ctx)
    report: dict[str, Any] = {"format": "ta-amps.process-package-test-report.v1", "interface": INTERFACE_VERSION,
                              "pack_id": pack_id, "kit_id": kit_id, "request_id": req["id"], "started_at": started,
                              "builder": builder["id"], "checks": {}, "failures": []}

    def record(name: str, result: dict[str, Any]) -> None:
        report["checks"][name] = result
        if not result.get("passed"):
            report["failures"].append(name)

    try:
        pack.build_pack_files(pack_dir)
        stage = pack.stage_library(out / "stage" / pack_id, pack_dir)
        record("library_pack_checks", pack.validate_pack(stage, pack_id))
        template_id = f"{pack_id}.{ctx.get('run_verb', 'run-cleaning-process')}"
        instance = pack.instantiate_cli(stage, template_id, {"params": ctx.get("instance_params") or
                                                             {"input_folder": "/data", "results_folder": "/results",
                                                              "summary": "none"}}, "nonprofit-local")
        task = instance["task"]
        record("instantiate", {"passed": instance["enqueued"] is False and task["brief"]["instantiation"]["status"] == "instance",
                               "command": f"python3 scripts/build_packs.py --instantiate {template_id} --inputs inputs.json --queue nonprofit-local",
                               "idempotency_key": task["idempotency_key"], "enqueued": instance["enqueued"]})
    except Exception as exc:  # a library check failure is a test failure, never hidden
        record("library_pack_checks", {"passed": False, "error": f"{type(exc).__name__}: {exc}"[:800]})
        task = None
    track = track_id or DEFAULT_TRACK[sig["class"]]
    envelope = {"kit_id": kit_id, "track_id": track, "deliverable_kind": "full_kit", "spdx_license": "MIT",
                "tags": ["domain:nonprofit_ops", f"track:{track}", "kind:process_package", f"reuse:{sig['key']}",
                         f"package:{pack_id}", "spdx:MIT", "cohort:nonprofit_ops", *(extra_tags or [])],
                "target_cohorts": ["all", "nonprofit_ops"], "producer_surface": PRODUCER,
                "visibility_scope": "public_commons", "allowed_surfaces": ["surface:eranos", "surface:herma"],
                "drafted_by": builder["id"], "drafted_by_key": builder["key_id"]}
    draft = None
    try:
        draft = pack.kit_draft(pack_dir, envelope, TRACKS_ROOT)
        record("verify_kit", checks.verify_kit(draft, track))
    except Exception as exc:
        record("verify_kit", {"passed": False, "error": f"{type(exc).__name__}: {exc}"[:800]})
    record("unit_tests", checks.unit_tests(pack_dir / "code"))
    record("persona_lint", checks.persona_lint(pack_dir / "code", harness["lint"], harness["configs"]))
    record("supply_chain_scan", checks.supply_chain_scan(pack_dir / "code", images_lock))
    record("public_check", checks.public_check(pack_dir))
    bundle_info = package.bundle(pack_dir, out / f"{pack_id}.tar.gz")
    if run_docker:
        record("docker_compose_test", checks.docker_test(Path(bundle_info["path"]), pack_id, workdir=out))
    else:
        report["checks"]["docker_compose_test"] = {"passed": None, "ran": False, "reason": "run_docker=False"}
    report.update({
        "passed": not report["failures"] and (report["checks"]["docker_compose_test"].get("passed") is not False),
        "bundle": bundle_info,
        "reuse": sig,
        "pieces": piece_records,
        "combine_notes": combine_notes,
        "text_written_by": "fixed templates; no model was called",
        "model_calls": 0,
        "harness_configs": harness["configs"],
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    })
    catalog_record = pending_catalog_record(draft, report, bundle_info) if draft else None
    template_record = task_template_record(pack_dir, pack_id, ctx)
    solution = solution_record(ctx, bundle_info, catalog_record, template_record, report)
    (out / f"{pack_id}.build.json").write_text(json.dumps({"test_report": report, "catalog_record": catalog_record,
                                                           "task_template_record": template_record,
                                                           "solution_record": solution}, indent=2, ensure_ascii=False) + "\n",
                                                encoding="utf-8")
    return {"bundle_path": bundle_info["path"], "bundle_sha256": bundle_info["sha256"], "catalog_record": catalog_record,
            "task_template_record": template_record, "test_report": report,
            "reuse": sig, "solution_record": solution, "package_dir": str(pack_dir)}


def write_pack_folder(pack_dir: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """The code folder, the README and the source a pack is built from."""
    authored = scans if ctx["reuse"]["class"] == scans.CLASS_ID else pack
    harness = package.write_code_folder(pack_dir / "code", ctx)
    (pack_dir / "README.md").write_text(authored.readme(ctx), encoding="utf-8")
    (pack_dir / "source.json").write_text(json.dumps(authored.source_json(ctx), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return harness


def regenerate_scan_pack(request: dict[str, Any], dest: Path) -> Path:
    """A reviewer's own copy of a scan-reading pack, from the request and the fixed text alone."""
    req = check_request(request)
    sig = reuse.signature(req["description"])
    plan = scans.split_pieces("reviewer")["pieces"]
    steps, _ = scans.combine_steps(req["description"], [scans.fixed_piece(p) for p in plan], sig["operations"])
    pack_dir = dest / scans.pack_id_for(sig)
    pack_dir.mkdir(parents=True)
    write_pack_folder(pack_dir, scans.context(req, sig, steps))
    pack.build_pack_files(pack_dir)
    return pack_dir


def pending_catalog_record(draft: dict[str, Any], report: dict[str, Any], bundle_info: dict[str, Any]) -> dict[str, Any]:
    """The catalog entry, waiting for an independent review: quarantined until finalize_catalog_record."""
    vk = report["checks"].get("verify_kit", {})
    verification = {"kit_id": draft["kit_id"], "passed": bool(vk.get("passed")), "checks_run": vk.get("checks_run", []),
                    "issues": vk.get("issues", []), "fixture_count": vk.get("fixture_count", 0),
                    "human_only_steps": vk.get("human_only_steps", [])}
    return {"store": CATALOG_STORE, "key": draft["kit_id"], "expected_version": 0,
            "producer_surface": PRODUCER, "visibility_scope": "surface_only", "allowed_surfaces": [],
            "tags": ["status:quarantined", "awaiting:review", *draft["tags"]],
            "value": {"kit": draft, "verification": verification, "blob_sha256": bundle_info["sha256"],
                      "draft_sha256": digest(draft), "drafter_key_id": draft["drafted_by_key"]},
            "status": "awaiting_review"}


def task_template_record(pack_dir: Path, pack_id: str, ctx: dict[str, Any]) -> dict[str, Any]:
    verbs = json.loads((pack_dir / "verbs.json").read_text(encoding="utf-8"))
    manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    run = next(t for t in verbs["tasks"] if t["brief"]["template_id"].endswith((".run-cleaning-process", f".{scans.RUN_VERB}")))
    return {"store": TEMPLATES_STORE, "key": pack_id, "expected_version": 0, "producer_surface": PRODUCER,
            "visibility_scope": "public_commons", "tags": ["kind:verb_template", f"pack:{pack_id}", "route:process-package"],
            "value": {"pack": pack_id, "pack_version": manifest["version"], "status": manifest["status"],
                      "title": ctx["title"], "summary": manifest["summary"], "route": "process-package",
                      "steps": [{"title": t["brief"]["title"], "claimant": t["brief"]["claimant"]} for t in verbs["tasks"]],
                      "task_spec": run, "source": {"bundle": f"{pack_id}.tar.gz", "path": f"{pack_id}/verbs.json"}}}


def solution_record(ctx: dict[str, Any], bundle_info: dict[str, Any], catalog: dict[str, Any] | None,
                    template: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """The searchable noun B1's reuse check finds: what the package does, its reuse key, where it is."""
    return {"store": SOLUTIONS_STORE, "key": ctx["pack_id"], "expected_version": 0, "producer_surface": PRODUCER,
            "visibility_scope": "surface_only", "tags": ["status:quarantined", "kind:process_package",
                                                          f"reuse:{ctx['reuse']['key']}", f"package:{ctx['pack_id']}"],
            "value": {"kind": "process_package", "title": ctx["title"], "summary": ctx["description"],
                      "request_id": ctx["request"]["id"], "reuse": ctx["reuse"],
                      "search_text": ctx.get("search_text") or f"{ctx['title']}. data cleaning pipeline, data-cleaning pipeline. {ctx['description']}",
                      "bundle": {"sha256": bundle_info["sha256"], "bytes": bundle_info["bytes"], "bucket": BUCKET,
                                 "key": f"{ctx['pack_id']}.tar.gz", "url": None},
                      "catalog": {"store": CATALOG_STORE, "key": catalog["key"] if catalog else None},
                      "task_template": {"store": TEMPLATES_STORE, "key": template["key"]},
                      "launch": ctx["launch_steps"][:2],
                      "harnesses": sorted({c["target"] for c in report["harness_configs"]}),
                      "tests": {k: bool(v.get("passed")) for k, v in report["checks"].items()},
                      "model_tokens_per_run": 0, **ctx.get("solution_extra", {})}}


def review_package(bundle_path: Path, build: dict[str, Any], reviewer: dict[str, str], *, run_docker: bool = True,
                   workdir: Path | None = None) -> dict[str, Any]:
    """An independent review: a different worker re-checks the bundle digest and re-runs the tests in a
    clean folder. Refuses (SelfReviewRefused) when the reviewer is the builder by id or by key."""
    report, catalog = build["test_report"], build["catalog_record"]
    builder_id, builder_key = report["builder"], catalog["value"]["drafter_key_id"]
    if reviewer["id"] == builder_id or reviewer["key_id"] == builder_key:
        raise SelfReviewRefused(f"reviewer {reviewer['id']!r} built this package; a different worker must review it")
    data = Path(bundle_path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    results = {"bundle_sha256_matches": sha == build["bundle_sha256"] == catalog["value"]["blob_sha256"]}
    if run_docker:
        results["docker_compose_test"] = checks.docker_test(Path(bundle_path), report["pack_id"], workdir=workdir)
    passed = results["bundle_sha256_matches"] and (not run_docker or results["docker_compose_test"]["passed"])
    review = {"kit_id": catalog["key"], "verdict": "approved" if passed else "needs_revision",
              "reviewed_by": reviewer["id"], "reviewed_by_key": reviewer["key_id"],
              "notes": ("Re-ran docker compose run --rm test from a clean folder and matched the bundle SHA-256; "
                        "flags stay with people and nothing reaches out to anyone.") if passed else
                       "The re-run or the digest check failed; see checks.",
              "checks": results, "reviewed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    review["review_sha256"] = digest({k: v for k, v in review.items() if k != "reviewed_at"})
    return review


def finalize_catalog_record(catalog_record: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    """The publishable catalog entry after an approved review; validated as the marketplace's PublishedKit."""
    if review["verdict"] != "approved":
        raise ValueError("only an approved review publishes a catalog entry")
    value = copy.deepcopy(catalog_record["value"])
    published = {**value, "reviewed_by": review["reviewed_by"], "reviewed_by_key": review["reviewed_by_key"],
                 "review_notes": review["notes"][:500], "review_receipt": review["review_sha256"],
                 "reviewer_key_id": review["reviewed_by_key"]}
    sys.path.insert(0, str(ROOT / "vendor" / "eranos_verify"))
    script = ("import json,sys; sys.path.insert(0, %r)\nfrom eranos.schemas import PublishedKit\n"
              "print(json.dumps(PublishedKit.model_validate(json.load(sys.stdin)).model_dump(mode='json')))")
    import subprocess  # noqa: PLC0415

    result = subprocess.run([str(checks.VENV_PYTHON), "-c", script % str(ROOT / "vendor" / "eranos_verify")],
                            input=json.dumps(published), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ValueError("the catalog entry is not a valid PublishedKit: " + result.stderr.strip()[-400:])
    tags = [t for t in catalog_record["tags"] if t not in ("status:quarantined", "awaiting:review")] + ["status:verified"]
    return {"store": catalog_record["store"], "key": catalog_record["key"], "expected_version": 0,
            "producer_surface": PRODUCER, "visibility_scope": "public_commons",
            "allowed_surfaces": ["surface:eranos", "surface:herma"], "tags": tags, "value": json.loads(result.stdout)}
