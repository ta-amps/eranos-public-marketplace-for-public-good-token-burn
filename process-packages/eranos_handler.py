"""B4's process handler for the volunteer worker loop (B1): point ERANOS_PROCESS_HANDLER at this file.

    expected_records(request, plan_part) -> {pack_id, kit_id, reuse_key, request_id, catalog_record, task_template_record}
    build_process(request, plan_part)    -> {bundle_path, bundle_sha256, catalog_record, task_template_record, test_report, ids}
    review_process(package, request, plan_part, *, bundle_path, records, builder_key_id, ...) -> {passed, checks, notes, verified}
    reuse_signature(text)                -> {key, class, operations, ...}   (0 tokens; the planner's exact reuse match)
    record_digest(value)                 -> SHA-256 the worker compares with `verified[...]["value_sha256"]`
    finalize_catalog_value(value, review) -> the public catalog value, validated as the marketplace's PublishedKit

Trust rules (reviews M3 and B4): the reviewer never trusts the build output.
- Every id, store and key comes from `expected_records(request, plan_part)`, a pure function of the request.
- The bundle is read only from `bundle_path`, a file the reviewer fetched by digest into its own folder.
- Its files must be exactly the generator's list for the derived pack and role (no compose override,
  .env or other extra file), all plain files and folders.
- The runner, its tests, the sample files, the Dockerfile and compose.yaml are byte-identical to this
  handler's own copies. No package-supplied config is ever read by Docker: the vetted tests run with
  plain `docker run` and flags set here (no network, read-only, no capabilities, non-root, limits, a
  tmpfs for /tmp, a time limit, and `docker rm -f` in `finally`).
- `records` must have been written by the build's own key (and trusted key and account, when given),
  carry exactly one reuse tag and one request tag, and equal the values rebuilt from the bundle and
  the request; `verified` returns those rebuilt values, which the worker publishes.

The worker loop's shapes: `request` is {request_id, text, organization_type, links, output_type,
frequency, ...}; `plan_part` is {part, route, text, legal, ...}.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from process_packages import checks as _checks  # noqa: E402
from process_packages import handler as _handler  # noqa: E402
from process_packages import pack as _pack  # noqa: E402
from process_packages import package as _package  # noqa: E402
from process_packages import scans as _scans  # noqa: E402
from process_packages.reuse import signature as _signature  # noqa: E402

name = "B4 process-package handler (process_packages)"
OUT = Path(os.environ.get("B4_OUT_DIR") or HERE / "out").resolve()
DRAFT_CATALOG_STORE = os.environ.get("B4_DRAFT_CATALOG_STORE", "eranos.processes")
DRAFT_TEMPLATE_STORE = os.environ.get("B4_DRAFT_TEMPLATE_STORE", "eranos.process_templates")
REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,80}")
MAX_BUNDLE_BYTES, MAX_MEMBERS, MAX_MEMBER_BYTES = 5 * 1024 * 1024, 400, 1024 * 1024
PIECES = (
    ("p1-profile", "Profile the columns", None),
    ("p2-dedupe", "Remove duplicate rows", "dedupe"),
    ("p3-formats", "Fix date and phone formats", ("dates", "phones")),
    ("p4-missing", "Flag missing contact fields", "missing_contact"),
    ("p5-report", "Write a short report", None),
)


class ReviewRefused(ValueError):
    """The bundle or the records do not belong to the request under review; nothing is published."""


def reuse_signature(text: str) -> dict[str, Any]:
    return _signature(text)


def _canonical(value: Any) -> str:
    """Canonical JSON identical to Tessera's (integral floats written as integers), so a value read back
    from the fabric compares equal to the same value built here."""
    return _pack.library_scripts()[0].canonical_json(value)


def record_digest(value: Any) -> str:
    """SHA-256 of a record value as Tessera-canonical JSON; the worker compares it with `verified` digests."""
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _description(request: dict[str, Any], plan_part: dict[str, Any]) -> str:
    part_text = str(plan_part.get("text") or "").strip()
    whole = str(request.get("text") or request.get("description") or "").strip()
    return part_text if part_text and _signature(part_text).get("key") else whole


def _request_id(request: dict[str, Any]) -> str:
    rid = str(request.get("request_id") or request.get("id") or "")
    if not REQUEST_ID.fullmatch(rid):
        raise ReviewRefused("the request has no usable request_id")
    return rid


def expected_records(request: dict[str, Any], plan_part: dict[str, Any]) -> dict[str, Any]:
    """Where this request's records must be, derived from the request alone (never from build output)."""
    rid = _request_id(request)
    sig = _signature(_description(request, plan_part))
    if not sig.get("key") or sig.get("class") not in _handler.DEFAULT_TRACK:
        raise ReviewRefused(f"no process class fits this request ({sig.get('text')})")
    short = sig["key"].split("-", 1)[1][:6]
    pack_id = _scans.pack_id_for(sig) if sig["class"] == _scans.CLASS_ID else f"process-sheet-cleaning-{short}"
    kit_id = f"PRC-{short.upper()}-01"
    part = re.sub(r"[^A-Za-z0-9]", "", str(plan_part.get("part") or 1))[:8] or "1"
    return {"request_id": rid, "part": part, "pack_id": pack_id, "kit_id": kit_id, "reuse_key": sig["key"],
            "catalog_record": {"store": DRAFT_CATALOG_STORE, "key": f"{rid}.{part}.{kit_id}"},
            "task_template_record": {"store": DRAFT_TEMPLATE_STORE, "key": f"{rid}.{part}.{pack_id}"},
            "listed_catalog_record": {"store": "eranos.catalog", "key": kit_id}}


def split_pieces(sig: dict[str, Any], claimant: str) -> dict[str, Any]:
    """The build verb's own split of a process, with depends_on fan-in."""
    if sig.get("class") == _scans.CLASS_ID:
        return _scans.split_pieces(claimant)
    ops = set(sig.get("operations") or [])
    pieces = []
    for pid, title, needs in PIECES:
        wanted = needs is None or (isinstance(needs, str) and needs in ops) or (isinstance(needs, tuple) and bool(ops & set(needs)))
        if not wanted:
            continue
        if pid == "p3-formats" and not {"dates", "phones"} <= ops:
            title = "Fix date formats" if "dates" in ops else "Fix phone formats"
        pieces.append({"id": pid, "title": title, "claimed_by": claimant})
    middle = [p["id"] for p in pieces if p["id"] not in ("p1-profile", "p5-report")]
    for piece in pieces:
        if piece["id"] == "p1-profile":
            piece["depends_on"] = []
        elif piece["id"] == "p5-report":
            piece["depends_on"] = middle or ["p1-profile"]
        else:
            piece["depends_on"] = ["p1-profile"]
    return {"pieces": pieces}


def _inside(path: Path, root: Path) -> Path:
    """`path` resolved, refused unless it is inside `root` and not a symbolic link."""
    if path.is_symlink():
        raise ReviewRefused(f"{path.name} is a symbolic link")
    resolved = path.resolve(strict=True)
    if resolved != root and root not in resolved.parents:
        raise ReviewRefused(f"{resolved} is outside {root}")
    return resolved


def _own_request(ids: dict[str, Any], request: dict[str, Any], plan_part: dict[str, Any]) -> dict[str, Any]:
    return {"id": ids["request_id"], "description": _description(request, plan_part), "output_type": "reusable_process",
            "frequency": request.get("cadence") or request.get("frequency")}


def build_process(request: dict[str, Any], plan_part: dict[str, Any]) -> dict[str, Any]:
    ids = expected_records(request, plan_part)
    claimant = os.environ.get("ERANOS_WORKER_LABEL") or "eranos-process-builder"
    mine = _own_request(ids, request, plan_part)
    plan = split_pieces(_signature(mine["description"]), claimant)
    run_dir = OUT / "runs" / f"{ids['request_id']}.{ids['part']}"
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    result = _handler.build_process(
        mine, plan, out_dir=run_dir,
        builder={"id": claimant, "key_id": os.environ.get("ERANOS_WORKER_KEY_ID") or claimant},
        run_docker=os.environ.get("B4_DOCKER_TEST", "1") != "0", extra_tags=[f"request:{ids['request_id']}"])
    _inside(Path(result["bundle_path"]), run_dir.resolve())
    report = result["test_report"]
    if report["pack_id"] != ids["pack_id"] or result["catalog_record"]["key"] != ids["kit_id"]:
        raise ReviewRefused("the built ids differ from the ids the request derives")
    report["issues"] = [f"{n}: {json.dumps(report['checks'].get(n), default=str)[:300]}" for n in report["failures"]]
    report["tests"] = {"runner_unit_tests": report["checks"].get("unit_tests", {}).get("tests"),
                       "container_tests": report["checks"].get("docker_compose_test", {}).get("tests"),
                       "checks_passed": sum(1 for v in report["checks"].values() if v.get("passed")),
                       "checks_run": len(report["checks"])}
    report["plan"] = plan
    result["catalog_record"] = {"store": ids["catalog_record"]["store"], "key": ids["catalog_record"]["key"],
                                "value": result["catalog_record"]["value"]}
    template_value = {**result["task_template_record"]["value"], "request_id": ids["request_id"], "part": ids["part"]}
    result["task_template_record"] = {"store": ids["task_template_record"]["store"], "key": ids["task_template_record"]["key"],
                                      "value": template_value}
    result["ids"] = ids
    return result


def _members(data: bytes, pack_id: str, slug: str | None = None, runner_dir: Path | None = None) -> list[tarfile.TarInfo]:
    """Every member of the bundle, refused unless the files are exactly the generator's list for this
    pack (no extra file, such as a compose override or .env) and every member is a plain file or folder."""
    if len(data) > MAX_BUNDLE_BYTES:
        raise ReviewRefused("the bundle is larger than 5 MB")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = tar.getmembers()
    if not members or len(members) > MAX_MEMBERS:
        raise ReviewRefused("the bundle has no members or too many")
    for m in members:
        parts = Path(m.name).parts
        if m.name.startswith("/") or ".." in parts or not parts or parts[0] != pack_id:
            raise ReviewRefused(f"bundle member {m.name!r} is outside {pack_id}/")
        if not (m.isfile() or m.isdir()):
            raise ReviewRefused(f"bundle member {m.name!r} is not a plain file or folder")
        if m.size > MAX_MEMBER_BYTES:
            raise ReviewRefused(f"bundle member {m.name!r} is larger than 1 MB")
    if slug is None:
        agents = [m.name for m in members if re.fullmatch(rf"{re.escape(pack_id)}/code/\.claude/agents/[a-z0-9-]+\.md", m.name)]
        if len(agents) != 1:
            raise ReviewRefused("the bundle does not name exactly one agent role")
        slug = Path(agents[0]).stem
    expected = _package.expected_paths(pack_id, slug, runner_dir)
    files = {m.name for m in members if m.isfile()}
    folders = {m.name.rstrip("/") for m in members if m.isdir()}
    allowed = {str(parent) for f in expected for parent in Path(f).parents if str(parent) != "."}
    if files != expected or not folders <= allowed:
        extra = sorted((files - expected) | (folders - allowed))
        missing = sorted(expected - files)
        raise ReviewRefused(f"the bundle's files are not the generated list (extra {extra[:5]}, missing {missing[:5]})")
    return members


def _same(a: Path, b: Path) -> bool:
    return a.is_file() and not a.is_symlink() and a.read_bytes() == b.read_bytes()


def review_process(package: dict[str, Any], request: dict[str, Any], plan_part: dict[str, Any], *,
                   bundle_path: str | Path | None = None, records: dict[str, Any] | None = None,
                   builder_key_id: str | None = None, trusted_builder_keys: set[str] | None = None,
                   builder_account_id: str | None = None, trusted_account_id: str | None = None) -> dict[str, Any]:
    """The reviewer's own re-check; refuses (passed False) on any mismatch. See the module docstring.

    `records` maps catalog_record and task_template_record to {"value", "owner_key_id"} as read at the
    derived keys; `builder_key_id` is the build lease's completing key. `trusted_builder_keys` is
    required (the worker reads it from ERANOS_PROCESS_BUILDER_KEYS): the build's key must be one of
    them, both drafts must have been written by it, and, when given, it must belong to the trusted account."""
    try:
        writer = {"key_id": builder_key_id, "trusted_keys": trusted_builder_keys,
                  "account_id": builder_account_id, "trusted_account_id": trusted_account_id}
        return _review(package, request, plan_part, bundle_path, records, writer)
    except (ReviewRefused, tarfile.TarError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        return {"passed": False, "checks": [f"refused: {type(exc).__name__}: {exc}"[:400]], "notes": "not approved", "verified": None}


def _regenerate(pack_dir: Path, ids: dict[str, Any], sha: str, process_class: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The catalog and template values this bundle and request produce, rebuilt by the reviewer."""
    track = _handler.DEFAULT_TRACK[process_class]
    envelope = {"kit_id": ids["kit_id"], "track_id": track, "deliverable_kind": "full_kit", "spdx_license": "MIT",
                "tags": ["domain:nonprofit_ops", f"track:{track}", "kind:process_package", f"reuse:{ids['reuse_key']}",
                         f"package:{ids['pack_id']}", "spdx:MIT", "cohort:nonprofit_ops", f"request:{ids['request_id']}"],
                "target_cohorts": ["all", "nonprofit_ops"], "producer_surface": _handler.PRODUCER,
                "visibility_scope": "public_commons", "allowed_surfaces": ["surface:eranos", "surface:herma"],
                "drafted_by": "builder", "drafted_by_key": "builder"}
    kit = _pack.kit_draft(pack_dir, envelope, _handler.TRACKS_ROOT)
    report = {"checks": {"verify_kit": _checks.verify_kit(kit, track)}}
    if not report["checks"]["verify_kit"].get("passed"):
        raise ReviewRefused("the marketplace's kit checks fail on the bundle's own nouns")
    catalog = _handler.pending_catalog_record(kit, report, {"sha256": sha})["value"]
    source = json.loads((pack_dir / "source.json").read_text(encoding="utf-8"))
    template = _handler.task_template_record(pack_dir, ids["pack_id"], {"title": source["title"]})["value"]
    template = {**template, "request_id": ids["request_id"], "part": ids["part"]}
    return catalog, template


def _builderless(value: dict[str, Any]) -> dict[str, Any]:
    """A catalog value without the builder's own identity fields, which the review replaces anyway."""
    kit = {**(value.get("kit") or {}), "drafted_by": "builder", "drafted_by_key": "builder"}
    return {k: v for k, v in {**value, "kit": kit}.items() if k not in ("draft_sha256", "drafter_key_id")}


def _review(package: dict[str, Any], request: dict[str, Any], plan_part: dict[str, Any],
            bundle_path: str | Path | None, records: dict[str, Any] | None, writer: dict[str, Any]) -> dict[str, Any]:
    ids = expected_records(request, plan_part)
    if not writer.get("trusted_keys"):
        raise ReviewRefused("the reviewer names no trusted builder keys (ERANOS_PROCESS_BUILDER_KEYS is required)")
    if writer.get("key_id") not in writer["trusted_keys"]:
        raise ReviewRefused("the build's key is not one of the trusted builder keys")
    sig = _signature(_description(request, plan_part))
    reading_scans = sig["class"] == _scans.CLASS_ID
    slug = _scans.SLUG if reading_scans else _handler.subject_words(sig)[0]
    runner_dir = _scans.RUNNER_DIR if reading_scans else _package.RUNNER
    if bundle_path is None:
        raise ReviewRefused("the reviewer must fetch the blob by digest into its own folder and pass bundle_path")
    path = Path(bundle_path)
    if path.is_symlink() or not path.is_file():
        raise ReviewRefused("bundle_path must be a regular file, not a link")
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha != str(package.get("blob_sha256") or ""):
        raise ReviewRefused("the bundle's SHA-256 differs from the digest the reviewer fetched it by")
    checks = [f"bundle SHA-256 {sha[:16]}... matches the fetched blob"]
    members = _members(data, ids["pack_id"], slug, runner_dir)
    checks.append(f"{len(members)} bundle members: exactly the generated file list for {ids['pack_id']}, plain files and folders only")
    with tempfile.TemporaryDirectory(prefix="b4-review-") as tmp:
        root = Path(tmp).resolve()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            tar.extractall(root, filter="data")
        _checks.open_folders(root)
        pack_dir = _inside(root / ids["pack_id"], root)
        code = pack_dir / "code"
        vetted = [("run_process.py", runner_dir / "run_process.py"),
                  ("tests/test_process.py", runner_dir / "tests" / "test_process.py")]
        vetted += [(f"samples/{p.relative_to(runner_dir / 'samples').as_posix()}", p)
                   for p in sorted((runner_dir / "samples").rglob("*")) if p.is_file()]
        changed = [rel for rel, mine in vetted if not _same(code / rel, mine)]
        images = json.loads((HERE / "images.lock.json").read_text(encoding="utf-8"))
        for rel, text in (("Dockerfile", _package.dockerfile()), ("compose.yaml", _package.compose_yaml(ids["pack_id"])),
                          ("launch.sh", _scans.LAUNCH_SCANS if reading_scans else _package.LAUNCH_SH), ("Makefile", _package.MAKEFILE)):
            if not (code / rel).is_file() or (code / rel).is_symlink() or (code / rel).read_text(encoding="utf-8") != text:
                changed.append(rel)
        if changed:
            raise ReviewRefused("vetted files differ from the handler's own copies: " + ", ".join(changed[:6]))
        checks.append(f"{len(vetted) + 4} vetted files byte-identical to the handler's (runner, tests, samples, containers)")
        if reading_scans:
            own = _handler.regenerate_scan_pack(_own_request(ids, request, plan_part), root / "reviewer-copy")
            differ = sorted(p.relative_to(own).as_posix() for p in own.rglob("*") if p.is_file()
                            and (pack_dir / p.relative_to(own)).read_bytes() != p.read_bytes())
            if differ:
                raise ReviewRefused("files differ from the reviewer's own copy of this package: " + ", ".join(differ[:6]))
            checks.append("every file equals the reviewer's own copy, written from the request and the fixed text")
        spec = json.loads((code / "process.json").read_text(encoding="utf-8"))
        # The vetted runner of this class, identical to the bundle's.
        run_process = _pack.load_module(f"vetted_runner_{sig['class']}", runner_dir / "run_process.py")
        run_process.load_spec(code / "process.json")
        ops = {s["operation"] for s in spec["steps"]}
        need = {"deduplicate": "dedupe", "normalize_dates": "dates", "normalize_phones": "phones",
                "flag_missing_fields": "missing_contact"}
        if reading_scans:
            need = {"check_readings": "transcribe", "fill_spreadsheet": "transcribe", "list_for_person": "transcribe"}
        asked_ops = _signature(_description(request, plan_part))["operations"]
        missing = [op for op, r in need.items() if r in asked_ops and op not in ops]
        if spec.get("process_id") != ids["pack_id"] or missing:
            raise ReviewRefused(f"process.json does not do what the request asks (process_id {spec.get('process_id')}, missing {missing})")
        source = json.loads((pack_dir / "source.json").read_text(encoding="utf-8"))
        asked = next((n["value"] for n in source.get("nouns", []) if n.get("slug") == "request"), {})
        if source.get("pack_id") != ids["pack_id"] or asked.get("request_id") != ids["request_id"]:
            raise ReviewRefused("the pack was built for a different request")
        checks.append(f"process.json and the pack's request noun belong to {ids['request_id']}")
        scan = _checks.supply_chain_scan(code, images)
        if not scan["passed"]:
            raise ReviewRefused("config supply-chain scan failed: " + str([r["rule"] for r in scan["rules"] if not r["passed"]]))
        checks.append("config supply-chain scan: clean")
        catalog_value, template_value = _regenerate(pack_dir, ids, sha, sig["class"])
        checks.append("catalog and template values rebuilt from the bundle and the request")
        if os.environ.get("B4_DOCKER_TEST", "1") != "0":
            base = images["images"]["python:3.12.13-slim"]["pinned_ref"]
            run = _checks.sandbox_test(code, base)
            if not run.get("passed"):
                raise ReviewRefused(f"the vetted tests failed in the sandbox: {run.get('log_tail') or run.get('reason')}")
            checks.append(f"vetted tests in a reviewer-set container: {run.get('tests')} tests OK ({run.get('limits')}); "
                          f"container removed: {run.get('removed')}")
        else:
            checks.append("container test skipped (B4_DOCKER_TEST=0)")
    verified = {"request_id": ids["request_id"], "pack_id": ids["pack_id"], "kit_id": ids["kit_id"], "bundle_sha256": sha,
                "catalog_record": dict(ids["catalog_record"]), "task_template_record": dict(ids["task_template_record"]),
                "listed_catalog_record": dict(ids["listed_catalog_record"])}
    verified["catalog_value"], verified["template_value"] = catalog_value, template_value
    if records is not None:
        for name in ("catalog_record", "task_template_record"):
            rec = records.get(name)
            if not isinstance(rec, dict) or "value" not in rec:
                raise ReviewRefused(f"{name}: the worker must pass the record with its value and writer")
            owner = rec.get("owner_key_id")
            if not writer.get("key_id") or owner != writer["key_id"]:
                raise ReviewRefused(f"{name} was written by {owner!r}, not by the build's own key")
        if writer.get("trusted_account_id") is not None and writer.get("account_id") != writer["trusted_account_id"]:
            raise ReviewRefused("the build's key belongs to another account")
        cat, tpl = records["catalog_record"]["value"], records["task_template_record"]["value"]
        kit = (cat or {}).get("kit") or {}
        tags = list(kit.get("tags") or [])
        reuse_tags = [t for t in tags if t.startswith("reuse:")]
        request_tags = [t for t in tags if t.startswith("request:")]
        if reuse_tags != [f"reuse:{ids['reuse_key']}"] or request_tags != [f"request:{ids['request_id']}"]:
            raise ReviewRefused("the catalog record must carry exactly this request's one reuse tag and one request tag")
        if not isinstance(cat, dict) or _canonical(_builderless(cat)) != _canonical(_builderless(catalog_value)):
            raise ReviewRefused("the catalog record differs from the value the bundle and request produce")
        if not isinstance(tpl, dict) or _canonical(tpl) != _canonical(template_value):
            raise ReviewRefused("the task template record differs from the value the bundle and request produce")
        verified["catalog_record"]["value_sha256"] = record_digest(cat)
        verified["task_template_record"]["value_sha256"] = record_digest(tpl)
        checks.append("both records were written by the build's key and equal the rebuilt values")
    notes = "Re-ran the package's tests in a clean folder and matched its SHA-256; flags stay with people."
    if reading_scans:
        notes = "Ran the package's tests again in a clean folder and matched every file; a person checks every listed field."
    return {"passed": True, "checks": checks, "verified": verified, "notes": notes}


def finalize_catalog_value(value: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    """The catalog value made public after an approved review, with the fabric's own keys and receipt.

    `review` holds reviewed_by, reviewed_by_key, review_receipt (None until submitted),
    review_task_id, draft_task_id, drafter_key_id, drafted_by and draft_sha256 (from the build lease
    and the fetched blob). Validated as the marketplace's PublishedKit."""
    kit = dict(value["kit"])
    kit["drafted_by"] = str(review.get("drafted_by") or kit.get("drafted_by"))[:80]
    kit["drafted_by_key"] = str(review.get("drafter_key_id") or kit.get("drafted_by_key"))[:80]
    published = {
        **value, "kit": kit,
        "reviewed_by": str(review["reviewed_by"])[:80], "reviewed_by_key": str(review["reviewed_by_key"])[:80],
        "review_notes": str(review.get("review_notes") or "Re-ran the package's tests in a clean folder and matched its SHA-256.")[:500],
        "review_receipt": review.get("review_receipt"), "review_task_id": review.get("review_task_id"),
        "draft_sha256": review.get("draft_sha256") or value.get("draft_sha256"),
        "draft_task_id": review.get("draft_task_id"), "drafter_key_id": kit["drafted_by_key"],
        "reviewer_key_id": str(review["reviewed_by_key"])[:80],
        "tags": [t for t in kit.get("tags", []) if t != "status:quarantined"] + ["status:verified"],
    }
    script = ("import json,sys; sys.path.insert(0, %r)\nfrom eranos.schemas import PublishedKit\n"
              "print(json.dumps(PublishedKit.model_validate(json.load(sys.stdin)).model_dump(mode='json')))")
    result = subprocess.run([str(_checks.VENV_PYTHON), "-c", script % str(HERE / "vendor" / "eranos_verify")],
                            input=json.dumps(published), capture_output=True, text=True, check=False,
                            env=_checks.minimal_env(), timeout=120)
    if result.returncode != 0:
        raise ValueError("the catalog value is not a valid PublishedKit: " + result.stderr.strip()[-400:])
    return json.loads(result.stdout)
