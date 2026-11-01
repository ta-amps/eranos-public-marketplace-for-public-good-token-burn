"""Process parts: a request for a reusable process becomes a generated, tested process package.

The package itself is built by a handler (build B4) behind one interface, loaded from the file named
by ERANOS_PROCESS_HANDLER:

    build_process(request, plan_part) -> {bundle_path, catalog_record, task_template_record, test_report}
    review_process(package, request, plan_part) -> {passed, checks, notes}      # optional

`catalog_record` and `task_template_record` are `{store, key, value}`. The builder stores the bundle as
a blob (its SHA-256 is the package's identity), writes both records quarantined, and submits; a
different key reviews it with `review_process` and only then makes the records public. Until a
handler is installed, the stub raises `NotImplementedError`: the verb fails with ok=false and the
failure stays on the request's record. Nothing is faked.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Protocol

from tessera import NotFound

from eranos.pipeline.request_noun import PRODUCER, update_request_part
from eranos.pipeline.run import SelfReviewRefused

HANDLER_ENV = "ERANOS_PROCESS_HANDLER"
BUILD_KIND, REVIEW_KIND = "process", "process_review"
NOT_IMPLEMENTED = "process packages are not built yet: no process handler (build B4) is installed"


class ProcessHandler(Protocol):
    def build_process(
        self, request: dict[str, Any], plan_part: dict[str, Any]
    ) -> dict[str, Any]: ...


class StubHandler:
    """Used until build B4's handler is installed; it never produces output."""

    name = "stub (no process handler installed)"

    def build_process(self, request: dict[str, Any], plan_part: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(NOT_IMPLEMENTED)


def load_handler(path: str | None = None) -> Any:
    """The handler module named by ERANOS_PROCESS_HANDLER, or the stub when none is set or it fails."""
    target = path or os.environ.get(HANDLER_ENV)
    if not target:
        return StubHandler()
    file = Path(target)
    if not file.is_file():
        raise FileNotFoundError(f"{HANDLER_ENV} names {target}, which is not a file")
    spec = importlib.util.spec_from_file_location("eranos_process_handler", file)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {target}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "build_process", None)):
        raise ImportError(f"{target} defines no build_process(request, plan_part)")
    module.__dict__.setdefault("name", file.name)
    return module


def is_stub(handler: Any) -> bool:
    return isinstance(handler, StubHandler)


STORES = {"catalog": "eranos.processes", "template": "eranos.process_templates"}
_PACK_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
# Package code never sees this worker's keys: only these variables reach the review subprocess.
_PASS_ENV = ("PATH", "LANG", "LC_ALL")
_RUNNER = """
import json, sys, importlib.util, pathlib
handler, package, request, part = sys.argv[1:5]
sys.path.insert(0, str(pathlib.Path(handler).parent))
spec = importlib.util.spec_from_file_location("eranos_process_handler", handler)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
load = lambda p: json.loads(pathlib.Path(p).read_text())
print(json.dumps(module.review_process(load(package), load(request), load(part))))
"""


def record_refs(request_id: str, part: Any) -> dict[str, dict[str, str]]:
    """The only records a request's process part may write and publish, derived from its own ids."""
    digest = hashlib.sha256(f"{request_id}:{part}".encode()).hexdigest()[:10].upper()
    return {
        name: {"store": store, "key": f"PROC-{digest}-{int(part):02d}"}
        for name, store in STORES.items()
    }


def process_brief(
    request_id: str, part: dict[str, Any], org: str, request: dict[str, Any], occurrence: int
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "eranos.process_build",
        "request_id": request_id,
        "part": part["part"],
        "occurrence": occurrence,
        "title": f"{org}: a reusable process"[:140],
        "made_up_samples_only": True,
        "request": request,
        "plan_part": {k: part[k] for k in ("part", "route", "text", "legal") if k in part},
        "records": record_refs(request_id, part["part"]),
        "output": {
            "node": "process_package",
            "contract": "build_process(request, plan_part) -> {bundle_path, catalog_record, task_template_record, test_report}",
        },
        "acceptance": [
            "The package's tests pass on made-up samples only, never on real people's data.",
            "Its bundle SHA-256 is its identity; the catalog record names it.",
            "A different key re-runs the checks in a clean environment before anything is public.",
        ],
    }


def process_review_brief(brief: dict[str, Any]) -> dict[str, Any]:
    """Everything the reviewer needs, written by the planner, so it reads no eq02 task."""
    keys = ("request_id", "part", "occurrence", "title", "request", "plan_part", "records")
    return {k: brief[k] for k in keys if k in brief} | {"kind": "eranos.process_review"}


def _put(backend: Any, store: str, key: str, value: Any, *, public: bool) -> dict[str, Any]:
    try:
        version = backend.get_record(store, key).version
    except NotFound:
        version = 0
    saved = backend.put_record(
        store,
        key,
        value,
        expected_version=version,
        producer_surface=PRODUCER,
        visibility_scope="public_commons" if public else "surface_only",
        tags=["kind:process_package", "status:verified" if public else "status:quarantined"],
    )
    return {"store": store, "key": key, "version": int(saved.version)}


def do_process(backend: Any, lease: Any, *, handler: Any) -> dict[str, Any]:
    """The builder's process work: {output, self_test, artifact_refs, summary}; raises when not built.

    The records go only where the planner's brief says (`records`), whatever the handler names.
    """
    brief = dict(lease.brief)
    built = handler.build_process(dict(brief["request"]), dict(brief["plan_part"]))
    missing = [
        k
        for k in ("bundle_path", "catalog_record", "task_template_record", "test_report")
        if k not in built
    ]
    if missing:
        raise ValueError(f"the process handler returned no {', '.join(missing)}")
    bundle = Path(str(built["bundle_path"])).read_bytes()
    digest = str(backend.put_blob(bundle))
    if digest != hashlib.sha256(bundle).hexdigest():
        raise ValueError("Tessera stored the bundle under a different digest")
    refs = brief["records"]
    catalog_value = {**dict(built["catalog_record"].get("value") or {}), "bundle_sha256": digest}
    template_value = {
        **dict(built["task_template_record"].get("value") or {}),
        "bundle_sha256": digest,
    }
    catalog = _put(
        backend, refs["catalog"]["store"], refs["catalog"]["key"], catalog_value, public=False
    )
    template = _put(
        backend, refs["template"]["store"], refs["template"]["key"], template_value, public=False
    )
    report = dict(built["test_report"])
    issues = [str(i) for i in report.get("issues") or []]
    passed = bool(report.get("passed")) and not issues
    # The kit-draft fields let Tessera's own eq03 rule prove the approval is independent.
    output = {
        "node": "process_package",
        "draft": {"kit_id": catalog["key"], "kind": "process_package"},
        "verification": {"passed": passed, "issues": issues, "tests": report.get("tests")},
        "bundle_sha256": digest,
        "bundle_bytes": len(bundle),
        "catalog_record": catalog,
        "task_template_record": template,
        "test_report": report,
        "blob_sha256": digest,
    }
    return {
        "output": output,
        "self_test": {"passed": passed, "issues": issues},
        "artifact_refs": [catalog, template],
        "summary": {"bundle_sha256": digest},
    }


def _clean_review(
    handler_file: str,
    package: dict[str, Any],
    request: dict[str, Any],
    plan_part: dict[str, Any],
    workdir: Path,
) -> dict[str, Any]:
    """Run the handler's review_process in a separate process with no keys and no worker settings."""
    for name, value in (("package", package), ("request", request), ("plan_part", plan_part)):
        (workdir / f"{name}.json").write_text(json.dumps(value))
    env = {k: os.environ[k] for k in _PASS_ENV if k in os.environ}
    env.update({k: v for k, v in os.environ.items() if k.startswith("B4_")})
    env.update(HOME=str(workdir), TMPDIR=str(workdir), PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            _RUNNER,
            handler_file,
            *(str(workdir / f"{n}.json") for n in ("package", "request", "plan_part")),
        ],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    if done.returncode != 0:
        return {
            "passed": False,
            "checks": [f"the review process exited {done.returncode}: {done.stderr[-300:]}"],
        }
    try:
        return dict(json.loads(done.stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        return {"passed": False, "checks": ["the review process printed no verdict"]}


def ensure_published(
    backend: Any,
    review: dict[str, Any],
    *,
    review_task_id: str,
    review_receipt: str,
    request_id: str,
    part: Any,
) -> list[dict[str, Any]]:
    """Make an approved package's own records public once; a repeated call changes nothing."""
    published = []
    for name in ("catalog", "template"):
        ref = review["records"][name]
        current = backend.get_record(ref["store"], ref["key"])
        value = dict(current.value)
        if (
            value.get("review_receipt") == review_receipt
            and getattr(current, "visibility_scope", "public_commons") == "public_commons"
        ):
            published.append(
                {"store": ref["store"], "key": ref["key"], "version": int(current.version)}
            )
            continue
        value.update(
            review_task_id=review_task_id,
            review_receipt=review_receipt,
            bundle_sha256=review["bundle_sha256"],
        )
        published.append(_put(backend, ref["store"], ref["key"], value, public=True))
    update_request_part(
        backend,
        request_id,
        part,
        "published",
        kit_id=review["records"]["catalog"]["key"],
        catalog_version=published[0]["version"],
        review_receipt=review_receipt,
        bundle_sha256=review["bundle_sha256"],
    )
    return published


def review_package(backend: Any, lease: Any, *, handler: Any, key_id: str) -> dict[str, Any]:
    """A different key checks the package it fetched itself, in a clean process, then publishes it."""
    build = lease.dependencies[0]
    brief = dict(lease.brief)
    request_id, part = str(brief["request_id"]), brief.get("part")
    refs = brief.get("records") or record_refs(request_id, part)
    ref = f"{lease.task_id}:{lease.fencing_token}"
    if build.state != "done" or not isinstance(build.output, dict):
        receipt = backend.submit(
            lease.task_id,
            lease.fencing_token,
            {"node": "process_review", "status": "nothing_to_review", "build_state": build.state},
            idempotency_key=ref,
            ok=True,
        )
        update_request_part(
            backend,
            request_id,
            part,
            "needs_revision",
            findings=[f"the process build ended {build.state}"],
        )
        return {
            "status": "nothing_to_review",
            "receipt": receipt.receipt_hash,
            "reason": f"the process build ended {build.state}",
        }
    if not key_id.strip() or build.completed_by_key in (None, key_id):
        backend.submit(
            lease.task_id,
            lease.fencing_token,
            {"node": "process_review", "status": "rejected_self_review"},
            idempotency_key=ref,
            ok=False,
            error="the key that built a package may not review it",
        )
        raise SelfReviewRefused(f"reviewer key {key_id!r} built this package")
    package = dict(build.output)
    findings: list[str] = []
    for name, field in (("catalog", "catalog_record"), ("template", "task_template_record")):
        named = package.get(field) or {}
        if not isinstance(named, dict) or (named.get("store"), named.get("key")) != (
            refs[name]["store"],
            refs[name]["key"],
        ):
            findings.append(f"the build names a {name} record this request does not own")
    digest = str(package.get("bundle_sha256") or "")
    if package.get("blob_sha256") != digest or not re.fullmatch(r"[0-9a-f]{64}", digest):
        findings.append("the build gives no bundle digest")
    given = package.get("test_report")
    report: dict[str, Any] = given if isinstance(given, dict) else {}
    pack_id = str(report.get("pack_id") or "process")
    if not _PACK_ID.fullmatch(pack_id):
        findings.append("the package id is not a plain name")
    verdict: dict[str, Any] = {}
    handler_file = getattr(handler, "__file__", None)
    if not findings and (
        is_stub(handler)
        or not callable(getattr(handler, "review_process", None))
        or not handler_file
    ):
        findings.append("no independent process check is installed (review_process)")
    if not findings:
        for name in ("catalog", "template"):
            current = backend.get_record(refs[name]["store"], refs[name]["key"])
            named = package["catalog_record" if name == "catalog" else "task_template_record"]
            if (
                int(current.version) != int(named.get("version") or 0)
                or current.value.get("bundle_sha256") != digest
            ):
                findings.append(
                    f"the {name} record changed after the build, or names another bundle"
                )
    if not findings:
        with tempfile.TemporaryDirectory(prefix="eranos-process-review-") as tmp:
            workdir = Path(tmp)
            bundle = backend.get_blob(digest)
            if hashlib.sha256(bundle).hexdigest() != digest:
                findings.append("the stored bundle does not match its digest")
            else:
                path = workdir / "bundle.tgz"
                path.write_bytes(bundle)
                mine = {
                    "bundle_path": str(path),
                    "bundle_sha256": digest,
                    "pack_id": pack_id,
                    "test_report": report,
                }
                verdict = _clean_review(
                    str(handler_file),
                    mine,
                    dict(brief.get("request") or {}),
                    dict(brief.get("plan_part") or {}),
                    workdir,
                )
                if verdict.get("passed") is not True:
                    findings += [str(c) for c in verdict.get("checks") or []][:10] or [
                        "the package's checks did not pass"
                    ]
    if findings:
        receipt = backend.submit(
            lease.task_id,
            lease.fencing_token,
            {"node": "process_review", "status": "needs_revision", "findings": findings},
            idempotency_key=ref,
            ok=True,
        )
        update_request_part(backend, request_id, part, "needs_revision", findings=findings)
        return {"status": "needs_revision", "findings": findings, "receipt": receipt.receipt_hash}
    review = {
        "node": "process_review",
        "status": "approved",
        "approved": True,
        "review_task_id": lease.task_id,
        "draft_task_id": build.task_id,
        "drafter_key_id": build.completed_by_key,
        "reviewer_key_id": key_id,
        "draft_sha256": digest,
        "kit_id": refs["catalog"]["key"],
        "bundle_sha256": digest,
        "records": refs,
        "part": part,
        "checks": [str(c) for c in verdict.get("checks") or []][:20],
    }
    receipt = backend.submit(
        lease.task_id, lease.fencing_token, review, idempotency_key=ref, ok=True
    )
    published = ensure_published(
        backend,
        review,
        review_task_id=lease.task_id,
        review_receipt=receipt.receipt_hash,
        request_id=request_id,
        part=part,
    )
    return {
        "status": "published",
        "receipt": receipt.receipt_hash,
        "published": published,
        "bundle_sha256": digest,
        "kit_id": refs["catalog"]["key"],
    }
