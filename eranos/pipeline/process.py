"""Process parts: a request for a reusable process becomes a generated, tested process package.

The package itself is built by a handler (build B4) behind one interface, loaded from the file named
by ERANOS_PROCESS_HANDLER:

    build_process(request, plan_part) -> {bundle_path, catalog_record, task_template_record, test_report}
    review_process(package, request, plan_part) -> {passed, checks, notes}      # optional
    finalize_catalog_value(value, review) -> value                               # optional
    reuse_signature(text) -> {key, ...}                                           # optional, 0 tokens

`catalog_record` and `task_template_record` are `{store, key, value}`. The builder stores the bundle as
a blob (its SHA-256 is the package's identity), writes both records quarantined, and submits; a
different key reviews it with `review_process` and only then makes the records public. Until a
handler is installed, the stub raises `NotImplementedError`: the verb fails with ok=false and the
failure stays on the request's record. Nothing is faked.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import tempfile
from pathlib import Path
from typing import Any, Protocol

from tessera import NotFound
from tessera.receipts import canonical_json

from eranos.pipeline.request_noun import PRODUCER, update_request_part
from eranos.pipeline.run import SelfReviewRefused

HANDLER_ENV = "ERANOS_PROCESS_HANDLER"
CATALOG_STORE = "eranos.catalog"
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
    return module


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
            "A different key re-runs the checks before anything is public.",
        ],
    }


def _put(backend: Any, record: dict[str, Any], *, public: bool) -> dict[str, Any]:
    store, key = str(record["store"]), str(record["key"])
    try:
        version = backend.get_record(store, key).version
    except NotFound:
        version = 0
    saved = backend.put_record(
        store,
        key,
        record["value"],
        expected_version=version,
        producer_surface=PRODUCER,
        visibility_scope="public_commons" if public else "surface_only",
        tags=["kind:process_package", "status:verified" if public else "status:quarantined"],
    )
    return {"store": store, "key": key, "version": int(saved.version)}


def do_process(backend: Any, lease: Any, *, handler: Any) -> dict[str, Any]:
    """The builder's process work: {output, self_test, artifact_refs, summary}; raises when not built."""
    brief = dict(lease.brief)
    built = handler.build_process(dict(brief["request"]), dict(brief["plan_part"]))
    missing = [
        k
        for k in ("bundle_path", "catalog_record", "task_template_record", "test_report")
        if k not in built
    ]
    if missing:
        raise ValueError(f"the process handler returned no {', '.join(missing)}")
    expected = getattr(handler, "expected_records", None)
    if callable(expected):
        ids = expected(dict(brief["request"]), dict(brief["plan_part"]))
        for name in ("catalog_record", "task_template_record"):
            got = (built[name]["store"], built[name]["key"])
            if got != (ids[name]["store"], ids[name]["key"]):
                raise ValueError(
                    f"the process handler named {got} for {name}, not the request's own record"
                )
    bundle = Path(str(built["bundle_path"])).read_bytes()
    digest = str(backend.put_blob(bundle))
    catalog = _put(backend, built["catalog_record"], public=False)
    template = _put(backend, built["task_template_record"], public=False)
    report = dict(built["test_report"])
    issues = [str(i) for i in report.get("issues") or []]
    passed = bool(report.get("passed")) and not issues
    # The kit-draft fields let Tessera's own eq03 rule prove the approval is independent.
    output = {
        "node": "process_package",
        "draft": {
            "kit_id": (built.get("ids") or {}).get("kit_id") or catalog["key"],
            "kind": "process_package",
        },
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


def publication_digest_value(value: Any) -> str:
    """The digest Tessera's publication guard recomputes: the value without its receipt or digest."""
    doc = (
        {**value, "review_receipt": None, "catalog_version": 1}
        if isinstance(value, dict)
        else value
    )
    if isinstance(doc, dict):
        doc.pop("publication_sha256", None)
    return hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()


def reviewed_value(handler: Any, value: Any, review: dict[str, Any]) -> Any:
    """The catalog value as published: the handler's own finalizer when it has one, so the entry
    carries its review receipt and the reviewer and builder keys (the reuse check needs both)."""
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


def review_package(
    backend: Any,
    lease: Any,
    *,
    handler: Any,
    key_id: str,
    trusted_keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    """A different key checks the package with the handler's own review, then publishes it."""
    build = lease.dependencies[0]
    request_id, part = str(lease.brief["request_id"]), lease.brief.get("part")
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
    review = getattr(handler, "review_process", None)
    expected = getattr(handler, "expected_records", None)
    verdict: dict[str, Any] = {}
    ids: dict[str, Any] = {}
    records: dict[str, Any] = {}
    trusted = trusted_keys if trusted_keys is not None else trusted_builder_keys()
    if not callable(review) or not callable(expected):
        findings.append(
            "no independent process check is installed (review_process, expected_records)"
        )
    elif not trusted:
        findings.append(BUILDER_KEYS_REQUIRED)
    else:
        # Nothing in the build output is trusted: ids, stores and keys come from the planner's brief,
        # and the bundle is fetched by its digest into this reviewer's own folder.
        brief = dict(backend.task(build.task_id).brief)
        request_, plan_part_ = dict(brief["request"]), dict(brief["plan_part"])
        ids = dict(expected(request_, plan_part_))
        if (package.get("draft") or {}).get("kit_id") != ids["kit_id"]:
            findings.append("the build names a different package than the request derives")
        else:
            stored = {
                name: backend.get_record(ids[name]["store"], ids[name]["key"])
                for name in ("catalog_record", "task_template_record")
            }
            # The handler checks who wrote each draft (the build's own key), not only what it says.
            records = {
                name: {"value": rec.value, "owner_key_id": getattr(rec, "owner_key_id", None)}
                for name, rec in stored.items()
            }
            with tempfile.TemporaryDirectory(prefix="eranos-process-review-") as tmp:
                fetched = Path(tmp) / "bundle.tar.gz"
                fetched.write_bytes(backend.get_blob(str(package.get("blob_sha256") or "")))
                verdict = dict(
                    review(
                        package,
                        request_,
                        plan_part_,
                        bundle_path=fetched,
                        records=records,
                        builder_key_id=build.completed_by_key,
                        trusted_builder_keys=trusted,
                    )
                )
            digest_of = getattr(handler, "record_digest", None)
            verified = verdict.get("verified") or {}
            if verdict.get("passed") is not True:
                findings += [str(c) for c in verdict.get("checks") or []] or [
                    "the package's checks did not pass"
                ]
            elif not callable(digest_of) or any(
                digest_of(records[name]["value"]) != (verified.get(name) or {}).get("value_sha256")
                for name in records
            ):
                findings.append("the records changed between the review and publication")
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
    # The reviewed catalog value is fixed before the receipt exists, so Tessera can check that what is
    # published is exactly what was approved (publication_sha256), the same proof kits carry.
    catalog_ref = dict(ids["catalog_record"])
    # Publish what the reviewer rebuilt from the bundle and the request, never the draft's own text.
    rebuilt = verdict.get("verified") or {}
    draft_value = rebuilt.get("catalog_value", records["catalog_record"]["value"])
    value = reviewed_value(
        handler,
        draft_value,
        {
            "reviewed_by": key_id,
            "reviewed_by_key": key_id,
            "review_receipt": None,
            "review_task_id": lease.task_id,
            "draft_task_id": build.task_id,
            "drafter_key_id": build.completed_by_key,
            "drafted_by": build.completed_by_key,
            "draft_sha256": package["blob_sha256"],
            "review_notes": verdict.get("notes"),
        },
    )
    digest = publication_digest_value(value)
    receipt = backend.submit(
        lease.task_id,
        lease.fencing_token,
        {
            "node": "process_review",
            "status": "approved",
            "approved": True,
            "review_task_id": lease.task_id,
            "draft_task_id": build.task_id,
            "drafter_key_id": build.completed_by_key,
            "reviewer_key_id": key_id,
            "draft_sha256": package["blob_sha256"],
            "kit_id": ids["kit_id"],
            "bundle_sha256": package["bundle_sha256"],
            "publication_sha256": digest,
            "checks": verdict.get("checks"),
        },
        idempotency_key=ref,
        ok=True,
    )
    final = (
        {**value, "review_receipt": receipt.receipt_hash, "publication_sha256": digest}
        if isinstance(value, dict)
        else value
    )
    template_ref = dict(ids["task_template_record"])
    template = rebuilt.get("template_value", records["task_template_record"]["value"])
    published = [
        _put(
            backend,
            {"store": catalog_ref["store"], "key": catalog_ref["key"], "value": final},
            public=True,
        ),
        _put(
            backend,
            {"store": template_ref["store"], "key": template_ref["key"], "value": template},
            public=True,
        ),
    ]
    kit_shaped = isinstance(final, dict) and (final.get("kit") or {}).get("kit_id") == ids["kit_id"]
    if catalog_ref["store"] != CATALOG_STORE and kit_shaped:
        # The reviewer holds the eq03 grant the catalog needs, so the reviewed entry is listed in the
        # marketplace's catalog too, where search and the reuse check find it.
        listed = {"store": CATALOG_STORE, "key": ids["kit_id"], "value": final}
        published.append(_put(backend, listed, public=True))
    update_request_part(
        backend,
        request_id,
        part,
        "published",
        kit_id=package["catalog_record"]["key"],
        catalog_version=published[0]["version"],
        review_receipt=receipt.receipt_hash,
        bundle_sha256=package["bundle_sha256"],
    )
    return {
        "status": "published",
        "receipt": receipt.receipt_hash,
        "published": published,
        "bundle_sha256": package["bundle_sha256"],
    }
