"""Process parts: a request for a reusable process becomes a generated, tested process package.

The package itself is built by a handler (build B4) behind one interface, loaded from the file named
by ERANOS_PROCESS_HANDLER:

    build_process(request, plan_part) -> {bundle_path, catalog_record, task_template_record, test_report}
    review_process(package, request, plan_part) -> {passed, checks, notes}      # optional

The full contract is build B4's (`process-packages/INTERFACE-B1.md`): `expected_records` derives a
request's own record ids from the planner's brief; the builder refuses records anywhere else; the
reviewer fetches the bundle by its digest into its own folder, reads the records at the derived
keys, runs `review_process` in a separate process that holds no keys, compares `record_digest`
just before publishing, and lists the entry `finalize_catalog_value` made, with the
`publication_sha256` Tessera's publication guard recomputes. Without a handler, process verbs are
not claimed at all: they wait for a worker that can build them. Nothing is faked.
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
from tessera.receipts import canonical_json

from eranos.pipeline.request_noun import PRODUCER, update_request_part
from eranos.pipeline.run import SelfReviewRefused

HANDLER_ENV = "ERANOS_PROCESS_HANDLER"
# Required for any reviewer that runs a process handler: the builder key ids it trusts.
BUILDER_KEYS_ENV = "ERANOS_PROCESS_BUILDER_KEYS"
BUILDER_KEYS_REQUIRED = (
    f"{BUILDER_KEYS_ENV} must name the builder key ids this reviewer trusts (comma-separated) "
    "before a reviewer runs the process handler"
)


class BuilderKeysMissing(RuntimeError):
    """A reviewer with a process handler was started without its trusted builder keys."""


def trusted_builder_keys(raw: str | None = None) -> frozenset[str]:
    """The builder key ids named in ERANOS_PROCESS_BUILDER_KEYS (or `raw`), without blanks."""
    text = os.environ.get(BUILDER_KEYS_ENV, "") if raw is None else raw
    return frozenset(k.strip() for k in text.split(",") if k.strip())


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


DRAFT_STORES = ("eranos.processes", "eranos.process_templates")
NO_REBUILT_VALUES = (
    "the process check returned no rebuilt catalog and template values; nothing was published "
    "(a draft's own text is never published)"
)


def _has_rebuilt(verified: dict[str, Any]) -> bool:
    return isinstance(verified.get("catalog_value"), dict) and isinstance(
        verified.get("template_value"), dict
    )


CATALOG_STORE = "eranos.catalog"
_PACK_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_KIT_ID = re.compile(r"[A-Z]{2,4}-[A-Z0-9]{2,8}-[0-9]{2}")
# Package code never sees this worker's keys: only these variables reach the review process.
_PASS_ENV = ("PATH", "LANG", "LC_ALL", "HOME", "DOCKER_HOST", "XDG_RUNTIME_DIR")
_RUNNER = """
import json, sys, importlib.util, pathlib
handler, package, request, part, records, bundle, extra = sys.argv[1:8]
sys.path.insert(0, str(pathlib.Path(handler).parent))
spec = importlib.util.spec_from_file_location("eranos_process_handler", handler)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
load = lambda p: json.loads(pathlib.Path(p).read_text())
review = module.review_process
kwargs = {"bundle_path": pathlib.Path(bundle), "records": load(records), **load(extra)}
print(json.dumps(review(load(package), load(request), load(part), **kwargs), default=str))
"""


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def expected_ids(
    handler: Any, request: dict[str, Any], plan_part: dict[str, Any]
) -> dict[str, Any]:
    """A request's own record ids: the handler's `expected_records`, or the same scheme without one.

    Drafts live only in the two draft stores under keys that start with `<request>.<part>.`; the
    listed entry is `eranos.catalog/<kit_id>`. Anything else is refused, whoever derived it.
    """
    request_id, part = str(request.get("request_id") or ""), int(plan_part.get("part") or 1)
    expected = getattr(handler, "expected_records", None)
    if callable(expected):
        ids = dict(expected(dict(request), dict(plan_part)))
    else:
        digest = hashlib.sha256(f"{request_id}:{part}".encode()).hexdigest()[:8].upper()
        kit_id = f"PRC-{digest}-{part:02d}"
        ids = {
            "kit_id": kit_id,
            "pack_id": "process",
            "catalog_record": {"store": DRAFT_STORES[0], "key": f"{request_id}.{part}.{kit_id}"},
            "task_template_record": {
                "store": DRAFT_STORES[1],
                "key": f"{request_id}.{part}.process",
            },
            "listed_catalog_record": {"store": CATALOG_STORE, "key": kit_id},
        }
    prefix = f"{request_id}.{part}."
    for name, store in (
        ("catalog_record", DRAFT_STORES[0]),
        ("task_template_record", DRAFT_STORES[1]),
    ):
        ref = ids.get(name) or {}
        if ref.get("store") != store or not str(ref.get("key") or "").startswith(prefix):
            raise ValueError(f"the derived {name} is not this request's own draft record")
    if not _KIT_ID.fullmatch(str(ids.get("kit_id") or "")) or not _PACK_ID.fullmatch(
        str(ids.get("pack_id") or "")
    ):
        raise ValueError("the derived package ids are not plain ids")
    return ids


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
        "made_up_data_only": True,
        "request": request,
        "plan_part": {k: part[k] for k in ("part", "route", "text", "legal") if k in part},
        "output": {
            "node": "process_package",
            "contract": "build_process(request, plan_part) -> {bundle_path, catalog_record, task_template_record, test_report}",
        },
        "acceptance": [
            "The package's tests pass on made-up sample files only (no real data).",
            "Its bundle SHA-256 is its identity; the catalog record names it.",
            "A different key re-runs the checks in a clean environment before anything is public.",
        ],
    }


def process_review_brief(brief: dict[str, Any]) -> dict[str, Any]:
    """Everything the reviewer needs, written by the planner, so it reads no eq02 task."""
    keys = ("request_id", "part", "occurrence", "title", "request", "plan_part")
    return {k: brief[k] for k in keys if k in brief} | {"kind": "eranos.process_review"}


def _put(
    backend: Any, store: str, key: str, value: Any, *, public: bool, tags: list[str] | None = None
) -> dict[str, Any]:
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
        tags=tags
        or ["kind:process_package", "status:verified" if public else "status:quarantined"],
    )
    return {"store": store, "key": key, "version": int(saved.version)}


def do_process(backend: Any, lease: Any, *, handler: Any) -> dict[str, Any]:
    """The builder's process work: {output, self_test, artifact_refs, summary}.

    The handler's records must be exactly at the request's own derived ids, or the build is refused.
    """
    brief = dict(lease.brief)
    request, plan_part = dict(brief["request"]), dict(brief["plan_part"])
    ids = expected_ids(handler, request, plan_part)
    built = handler.build_process(request, plan_part)
    missing = [
        k
        for k in ("bundle_path", "catalog_record", "task_template_record", "test_report")
        if k not in built
    ]
    if missing:
        raise ValueError(f"the process handler returned no {', '.join(missing)}")
    for name in ("catalog_record", "task_template_record"):
        got = (built[name].get("store"), built[name].get("key"))
        if got != (ids[name]["store"], ids[name]["key"]):
            raise ValueError(
                f"the process handler named {got} for {name}, not the request's own record"
            )
    bundle = Path(str(built["bundle_path"])).read_bytes()
    digest = str(backend.put_blob(bundle))
    if digest != hashlib.sha256(bundle).hexdigest():
        raise ValueError("Tessera stored the bundle under a different digest")
    catalog = _put(
        backend,
        ids["catalog_record"]["store"],
        ids["catalog_record"]["key"],
        built["catalog_record"].get("value"),
        public=False,
    )
    template = _put(
        backend,
        ids["task_template_record"]["store"],
        ids["task_template_record"]["key"],
        built["task_template_record"].get("value"),
        public=False,
    )
    report = dict(built["test_report"])
    issues = [str(i) for i in report.get("issues") or []]
    passed = bool(report.get("passed")) and not issues
    # The kit-draft fields let Tessera's own eq03 rule prove the approval is independent.
    output = {
        "node": "process_package",
        "draft": {"kit_id": ids["kit_id"], "kind": "process_package"},
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
        "summary": {"bundle_sha256": digest, "kit_id": ids["kit_id"]},
    }


def _clean_review(
    handler_file: str,
    package: dict[str, Any],
    request: dict[str, Any],
    plan_part: dict[str, Any],
    records: dict[str, Any],
    bundle: Path,
    workdir: Path,
    extra: dict[str, Any],
) -> dict[str, Any]:
    """Run the handler's review_process in a separate process with no worker keys or settings."""
    for name, value in (
        ("package", package),
        ("request", request),
        ("plan_part", plan_part),
        ("records", records),
        ("extra", extra),
    ):
        (workdir / f"{name}.json").write_text(json.dumps(value))
    env = {k: os.environ[k] for k in _PASS_ENV if k in os.environ}
    env.update({k: v for k, v in os.environ.items() if k.startswith("B4_")})
    env.update(TMPDIR=str(workdir), PYTHONDONTWRITEBYTECODE="1")
    args = [str(workdir / f"{n}.json") for n in ("package", "request", "plan_part", "records")]
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            _RUNNER,
            handler_file,
            *args,
            str(bundle),
            str(workdir / "extra.json"),
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


def publication_digest_value(value: Any) -> str:
    """The digest Tessera's publication guard recomputes: the value without its receipt or digest."""
    doc = (
        {**value, "review_receipt": None, "catalog_version": 1}
        if isinstance(value, dict)
        else value
    )
    if isinstance(doc, dict):
        doc.pop("publication_sha256", None)
    return _canonical_digest(doc)


def reviewed_value(handler: Any, value: Any, review: dict[str, Any]) -> Any:
    """The catalog value as published: the handler's own finalizer when it has one."""
    finalize = getattr(handler, "finalize_catalog_value", None)
    if callable(finalize) and isinstance(value, dict):
        return finalize(dict(value), review)
    if not isinstance(value, dict):
        return value
    tags = [t for t in value.get("tags") or [] if t != "status:quarantined"]
    keep = ("review_task_id", "draft_task_id", "drafter_key_id", "draft_sha256", "review_receipt")
    return {
        **value,
        **{k: review[k] for k in keep},
        "reviewer_key_id": review["reviewed_by_key"],
        "tags": [*tags, "status:verified"],
    }


def _digest_of(handler: Any, value: Any) -> str:
    digest = getattr(handler, "record_digest", None)
    return str(digest(value)) if callable(digest) else _canonical_digest(value)


def ensure_published(
    backend: Any,
    review: dict[str, Any],
    *,
    review_task_id: str,
    review_receipt: str,
    request_id: str,
    part: Any,
    handler: Any = None,
) -> list[dict[str, Any]]:
    """Publish an approved package once: its own drafts, then the listed catalog entry.

    The drafts are read again and must still have the digests the review verified; a repeated call
    finds everything published and changes nothing.
    """
    ids, verified = review["ids"], review.get("verified") or {}
    if not isinstance(review.get("catalog_value"), dict) or not isinstance(
        review.get("template_value"), dict
    ):
        raise ValueError(NO_REBUILT_VALUES)  # the recorded approval lacks them: publish nothing
    final = {
        **review["catalog_value"],
        "review_receipt": review_receipt,
        "publication_sha256": review["publication_sha256"],
    }
    published = []
    for name in ("catalog_record", "task_template_record"):
        ref = ids[name]
        current = backend.get_record(ref["store"], ref["key"])
        value = current.value
        if (value or {}).get("review_receipt") == review_receipt and name == "catalog_record":
            published.append(
                {"store": ref["store"], "key": ref["key"], "version": int(current.version)}
            )
            continue
        want = (verified.get(name) or {}).get("value_sha256")
        if want and _digest_of(handler, value) != want:
            raise ValueError(f"the {name} changed after the review; nothing was published")
        published.append(
            _put(
                backend,
                ref["store"],
                ref["key"],
                final if name == "catalog_record" else review["template_value"],
                public=True,
            )
        )
    listed = ids.get("listed_catalog_record")
    if (
        listed
        and isinstance(final.get("kit"), dict)
        and final["kit"].get("kit_id") == ids["kit_id"]
    ):
        try:
            done = (
                backend.get_record(CATALOG_STORE, ids["kit_id"]).value.get("review_receipt")
                == review_receipt
            )
        except NotFound:
            done = False
        if not done:
            tags = [t for t in final.get("tags") or [] if isinstance(t, str)] or ["status:verified"]
            published.append(
                _put(backend, CATALOG_STORE, ids["kit_id"], final, public=True, tags=tags)
            )
    update_request_part(
        backend,
        request_id,
        part,
        "published",
        kit_id=ids["kit_id"],
        catalog_version=published[0]["version"],
        review_receipt=review_receipt,
        bundle_sha256=review["bundle_sha256"],
    )
    return published


def review_package(
    backend: Any,
    lease: Any,
    *,
    handler: Any,
    key_id: str,
    trusted_keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    """A different key checks the package it fetched itself, in a clean process, then publishes it.

    The handler is told who completed the build and which builder keys this reviewer trusts, and it
    sees who wrote each draft record, so a package written by any other key is never approved.
    """
    build = lease.dependencies[0]
    brief = dict(lease.brief)
    request_id, part = str(brief["request_id"]), brief.get("part")
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
    request, plan_part = dict(brief.get("request") or {}), dict(brief.get("plan_part") or {})
    findings: list[str] = []
    try:
        ids = expected_ids(handler, request, plan_part)
    except (ValueError, KeyError, TypeError) as exc:
        ids, findings = {}, [f"the request's own record ids could not be derived: {exc}"]
    for name in ("catalog_record", "task_template_record"):
        named = package.get(name) or {}
        if ids and (
            not isinstance(named, dict)
            or (named.get("store"), named.get("key")) != (ids[name]["store"], ids[name]["key"])
        ):
            findings.append(f"the build names a {name} this request does not own")
    if ids and (package.get("draft") or {}).get("kit_id") != ids.get("kit_id"):
        findings.append("the build names a different package than the request derives")
    digest = str(package.get("bundle_sha256") or "")
    if package.get("blob_sha256") != digest or not re.fullmatch(r"[0-9a-f]{64}", digest):
        findings.append("the build gives no bundle digest")
    handler_file = getattr(handler, "__file__", None)
    trusted = trusted_keys if trusted_keys is not None else trusted_builder_keys()
    if not findings and (
        is_stub(handler)
        or not callable(getattr(handler, "review_process", None))
        or not handler_file
    ):
        findings.append("no independent process check is installed (review_process)")
    elif not findings and not trusted:
        findings.append(BUILDER_KEYS_REQUIRED)
    records: dict[str, Any] = {}
    if not findings:
        for name in ("catalog_record", "task_template_record"):
            current = backend.get_record(ids[name]["store"], ids[name]["key"])
            if int(current.version) != int((package.get(name) or {}).get("version") or 0):
                findings.append(f"the {name} changed after the build")
            # The handler checks who wrote each draft (the build's own key), not only what it says.
            records[name] = {
                "value": current.value,
                "owner_key_id": getattr(current, "owner_key_id", None),
            }
    verdict: dict[str, Any] = {}
    if not findings:
        with tempfile.TemporaryDirectory(prefix="eranos-process-review-") as tmp:
            workdir = Path(tmp)
            bundle = backend.get_blob(digest)
            if hashlib.sha256(bundle).hexdigest() != digest:
                findings.append("the stored bundle does not match its digest")
            else:
                path = workdir / "bundle.tar.gz"
                path.write_bytes(bundle)
                extra = {
                    "builder_key_id": build.completed_by_key,
                    "trusted_builder_keys": sorted(trusted),
                }
                verdict = _clean_review(
                    str(handler_file), package, request, plan_part, records, path, workdir, extra
                )
        if not findings and verdict.get("passed") is not True:
            findings += [str(c) for c in verdict.get("checks") or []][:10] or [
                "the package's checks did not pass"
            ]
        verified = verdict.get("verified") or {}
        if not findings and any(
            _digest_of(handler, records[name]["value"])
            != (verified.get(name) or {}).get("value_sha256")
            for name in records
        ):
            findings.append("the records the review verified are not the records stored now")
        if not findings and not _has_rebuilt(verified):
            # Never fall back to the draft's own text: without rebuilt values nothing is published.
            findings.append(NO_REBUILT_VALUES)
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
    # Publish what the reviewer rebuilt from the bundle and the request, never the draft's own text.
    rebuilt = verdict.get("verified") or {}
    value = reviewed_value(
        handler,
        rebuilt["catalog_value"],
        {
            "reviewed_by": key_id,
            "reviewed_by_key": key_id,
            "reviewer_key_id": key_id,
            "review_receipt": None,
            "review_task_id": lease.task_id,
            "draft_task_id": build.task_id,
            "drafter_key_id": build.completed_by_key,
            "drafted_by": build.completed_by_key,
            "draft_sha256": digest,
            "review_notes": verdict.get("notes"),
        },
    )
    publication = publication_digest_value(value)
    review = {
        "node": "process_review",
        "status": "approved",
        "approved": True,
        "review_task_id": lease.task_id,
        "draft_task_id": build.task_id,
        "drafter_key_id": build.completed_by_key,
        "reviewer_key_id": key_id,
        "draft_sha256": digest,
        "kit_id": ids["kit_id"],
        "bundle_sha256": digest,
        "publication_sha256": publication,
        "ids": ids,
        "verified": verdict.get("verified") or {},
        "catalog_value": value,
        "template_value": rebuilt["template_value"],
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
        handler=handler,
    )
    return {
        "status": "published",
        "receipt": receipt.receipt_hash,
        "published": published,
        "bundle_sha256": digest,
        "kit_id": ids["kit_id"],
    }
