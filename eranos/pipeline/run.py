"""Two-step volunteer agent pipeline on Tessera (`eq01` spec -> `eq02` draft -> `eq03` review -> CAS catalog).

Enforces:
- quarantine (`visibility_scope="surface_only"`, `status:quarantined`) on unreviewed `eq01`/`eq02` items;
- `drafter != reviewer` across worker IDs, payload keys, and Tessera task result `completed_by_key`;
- deterministic verification before any review approval can publish;
- human nonprofit steward sign-off via Tessera `park` and `resume` (`by != parked_by` always enforced);
- atomic compare-and-set batch publish (`eranos.catalog` + `eranos.index`), governance metadata stamping,
  and `noun.promotions` feed publication.
"""

from __future__ import annotations

import inspect
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tessera import Forbidden, NotFound, RecordWrite, TaskSpec, TaskView

from eranos.jsonfile import load_json
from eranos.queues import QUEUE_CONFIGS
from eranos.schemas import (
    KitDraft,
    KitRequest,
    PublishedKit,
    ReviewDecision,
    TrackPack,
    VerificationReport,
    VisibilityScope,
    normalize_tags,
)
from eranos.tracks import get_track
from eranos.verifier import practice_verify_kit, verify_kit

CATALOG_STORE = "eranos.catalog"
INDEX_STORE = "eranos.index"
INDEX_KEY = "kits"


class SelfReviewError(PermissionError):
    """The agent or key that drafted a kit may never approve its review."""

    status_code: int = 403


class SelfReviewRefused(SelfReviewError):
    """Alias preserving backwards-compatible SelfReviewRefused catches alongside SelfReviewError."""


class UnverifiedKitRefused(ValueError):
    """A kit failing deterministic verification cannot be approved or published."""


@dataclass(frozen=True)
class KitGraph:
    run_id: str
    kit_id: str
    spec_task_id: str
    draft_task_id: str
    review_task_id: str


def new_run_id() -> str:
    return f"er_{uuid.uuid4().hex[:12]}"


def ensure_queues(backend: Any) -> None:
    for cfg in QUEUE_CONFIGS:
        backend.define_queue(cfg)


def enrich_governance_tags(
    tags: list[str],
    *,
    status: str,
    domain: str | None = None,
    track_id: str | None = None,
    deliverable_kind: str | None = None,
    spdx_license: str | None = None,
) -> list[str]:
    filtered = [t for t in tags if not t.strip().lower().startswith("status:")]
    candidates = [f"status:{status}", *filtered]
    if domain:
        candidates.append(f"domain:{domain}")
    if track_id:
        candidates.append(f"track:{track_id}")
    if deliverable_kind:
        candidates.append(f"kind:{deliverable_kind}")
    if spdx_license:
        candidates.append(f"spdx:{spdx_license}")
    return normalize_tags(candidates)


def _model_accepted_fields(cls_or_callable: Any) -> set[str]:
    model_fields = getattr(cls_or_callable, "model_fields", None)
    if isinstance(model_fields, dict) and model_fields:
        return set(model_fields.keys())
    try:
        return set(inspect.signature(cls_or_callable).parameters.keys())
    except (TypeError, ValueError):
        return set()


def _build_task_spec(
    *,
    queue: str,
    task_id: str,
    kind: str,
    effect_class: Any,
    brief: dict[str, Any],
    depends_on: list[str] | None = None,
    governance: dict[str, Any] | None = None,
) -> TaskSpec:
    accepted = _model_accepted_fields(TaskSpec)
    kwargs: dict[str, Any] = {
        "queue": queue,
        "task_id": task_id,
        "kind": kind,
        "effect_class": effect_class,
        "brief": brief,
    }
    if depends_on is not None:
        kwargs["depends_on"] = depends_on
    if governance:
        for key, val in governance.items():
            if key in accepted:
                kwargs[key] = val
    return TaskSpec(**kwargs)


def _build_record_write(
    *,
    store: str,
    key: str,
    value: Any,
    expected_version: int | None,
    governance: dict[str, Any] | None = None,
) -> RecordWrite:
    accepted = _model_accepted_fields(RecordWrite)
    kwargs: dict[str, Any] = {
        "store": store,
        "key": key,
        "value": value,
        "expected_version": expected_version,
    }
    if governance:
        for gov_key, gov_val in governance.items():
            if gov_key in accepted:
                kwargs[gov_key] = gov_val
    return RecordWrite(**kwargs)


def _claim_with_key(
    backend: Any,
    queue: str,
    worker: str,
    *,
    key_id: str | None = None,
) -> Any:
    try:
        param_names: set[str] = set(inspect.signature(backend.claim).parameters.keys())
    except (TypeError, ValueError):
        param_names = set()
    if key_id is not None and "key_id" in param_names:
        return backend.claim(queue, worker, key_id=key_id)
    return backend.claim(queue, worker)


def submit_kit_request(
    backend: Any,
    request: KitRequest,
    *,
    run_id: str | None = None,
    tracks_root: Path | None = None,
) -> KitGraph:
    ensure_queues(backend)
    track = get_track(request.track_id, tracks_root)
    rid = run_id or new_run_id()
    spec_id = f"{rid}:{request.kit_id}:spec"
    draft_id = f"{rid}:{request.kit_id}:draft"
    review_id = f"{rid}:{request.kit_id}:review"

    requested_scope: VisibilityScope = (
        "allowlist_surfaces"
        if request.visibility_scope == "allowlist_surfaces"
        else "public_commons"
    )
    quarantined_tags = enrich_governance_tags(
        request.tags,
        status="quarantined",
        domain=track.domain,
        track_id=request.track_id,
        deliverable_kind=request.deliverable_kind,
        spdx_license=request.spdx_license,
    )
    quarantined_req = request.model_copy(
        update={
            "visibility_scope": "surface_only",
            "tags": quarantined_tags,
        }
    )
    quarantine_gov: dict[str, Any] = {
        "spdx_license": quarantined_req.spdx_license,
        "tags": quarantined_req.tags,
        "target_cohorts": quarantined_req.target_cohorts,
        "producer_surface": quarantined_req.producer_surface,
        "visibility_scope": "surface_only",
        "allowed_surfaces": quarantined_req.allowed_surfaces,
    }
    brief_payload: dict[str, Any] = {
        "run_id": rid,
        "request": quarantined_req.model_dump(mode="json"),
        "requested_visibility_scope": requested_scope,
        "visibility_scope": "surface_only",
        "tags": quarantined_tags,
    }

    backend.enqueue(
        _build_task_spec(
            queue="eq01",
            task_id=spec_id,
            kind="spec",
            effect_class="read",
            brief=brief_payload,
            governance=quarantine_gov,
        )
    )
    backend.enqueue(
        _build_task_spec(
            queue="eq02",
            task_id=draft_id,
            kind="draft",
            effect_class="write-internal",
            depends_on=[spec_id],
            brief=brief_payload,
            governance=quarantine_gov,
        )
    )
    backend.enqueue(
        _build_task_spec(
            queue="eq03",
            task_id=review_id,
            kind="review",
            effect_class="write-internal",
            depends_on=[draft_id],
            brief=brief_payload,
            governance=quarantine_gov,
        )
    )
    return KitGraph(
        run_id=rid,
        kit_id=request.kit_id,
        spec_task_id=spec_id,
        draft_task_id=draft_id,
        review_task_id=review_id,
    )


def run_spec_step(
    backend: Any,
    *,
    worker: str = "spec-gate-01",
    key_id: str | None = None,
    tracks_root: Path | None = None,
) -> dict[str, Any] | None:
    lease = _claim_with_key(backend, "eq01", worker, key_id=key_id)
    if lease is None:
        return None
    req = KitRequest.model_validate(lease.brief["request"])
    track = get_track(req.track_id, tracks_root)
    quarantined_tags = enrich_governance_tags(
        req.tags,
        status="quarantined",
        domain=track.domain,
        track_id=req.track_id,
        deliverable_kind=req.deliverable_kind,
        spdx_license=req.spdx_license,
    )
    requested_scope = str(lease.brief.get("requested_visibility_scope") or "public_commons")
    output: dict[str, Any] = {
        "node": "spec",
        "kit_id": req.kit_id,
        "track": track.model_dump(mode="json"),
        "needs_steward_signoff": req.needs_steward_signoff,
        "spdx_license": req.spdx_license,
        "tags": quarantined_tags,
        "target_cohorts": req.target_cohorts,
        "producer_surface": req.producer_surface,
        "visibility_scope": "surface_only",
        "allowed_surfaces": req.allowed_surfaces,
        "requested_visibility_scope": requested_scope,
    }
    backend.submit(
        lease.task_id,
        lease.fencing_token,
        output,
        idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
        ok=True,
    )
    return output


def run_draft_step(
    backend: Any,
    draft_payload: dict[str, Any] | KitDraft,
    *,
    worker: str,
    key_id: str,
) -> dict[str, Any] | None:
    lease = _claim_with_key(backend, "eq02", worker, key_id=key_id)
    if lease is None:
        return None
    dep_out = lease.dependencies[0].output
    if dep_out is None:
        raise RuntimeError(f"upstream spec output missing for {lease.task_id}")
    track = TrackPack.model_validate(dep_out["track"])
    req_data = lease.brief.get("request") if isinstance(lease.brief, dict) else None
    raw = (
        draft_payload.model_dump(mode="json")
        if isinstance(draft_payload, KitDraft)
        else dict(draft_payload)
    )
    if isinstance(req_data, dict):
        for gov_field in (
            "spdx_license",
            "target_cohorts",
            "producer_surface",
            "allowed_surfaces",
        ):
            if gov_field not in raw and gov_field in req_data:
                raw[gov_field] = req_data[gov_field]
        if "tags" not in raw and "tags" in req_data:
            raw["tags"] = list(req_data["tags"])

    raw["drafted_by"] = worker
    raw["drafted_by_key"] = key_id
    raw["visibility_scope"] = "surface_only"
    raw["tags"] = enrich_governance_tags(
        list(raw.get("tags") or []),
        status="quarantined",
        domain=str(raw.get("domain") or track.domain),
        track_id=str(raw.get("track_id") or track.id),
        deliverable_kind=str(raw.get("deliverable_kind") or "full_kit"),
        spdx_license=str(raw.get("spdx_license") or "Apache-2.0"),
    )
    draft = KitDraft.model_validate(raw)
    report = verify_kit(draft, track)

    canonical_bytes = json.dumps(draft.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    blob_sha256: str = backend.put_blob(canonical_bytes)

    requested_scope = str(
        dep_out.get("requested_visibility_scope")
        or (
            lease.brief.get("requested_visibility_scope") if isinstance(lease.brief, dict) else None
        )
        or "public_commons"
    )
    provisional: dict[str, Any] = {
        "node": "draft",
        "draft": draft.model_dump(mode="json"),
        "verification": report.model_dump(mode="json"),
        "blob_sha256": blob_sha256,
        "needs_steward_signoff": bool(dep_out.get("needs_steward_signoff", False)),
        "visibility_scope": "surface_only",
        "tags": draft.tags,
        "requested_visibility_scope": requested_scope,
    }
    receipt = backend.submit(
        lease.task_id,
        lease.fencing_token,
        provisional,
        idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
        ok=report.passed,
        error=None if report.passed else "; ".join(report.issues),
    )
    return {**provisional, "draft_receipt": receipt.receipt_hash}


@contextmanager
def _eranos_surface_scope(backend: Any) -> Iterator[None]:
    if hasattr(backend, "scope_context") and hasattr(backend, "current_scope"):
        cur = backend.current_scope()
        if getattr(cur, "surface", None) is None:
            with backend.scope_context(surface="surface:eranos"):
                yield
            return
    yield


def _publish_to_catalog(
    backend: Any,
    published: PublishedKit,
    *,
    requested_visibility_scope: str | None = None,
) -> PublishedKit:
    with _eranos_surface_scope(backend):
        return _publish_to_catalog_scoped(
            backend,
            published,
            requested_visibility_scope=requested_visibility_scope,
        )


def _publish_to_catalog_scoped(
    backend: Any,
    published: PublishedKit,
    *,
    requested_visibility_scope: str | None = None,
) -> PublishedKit:
    kit_id = published.kit.kit_id
    try:
        existing_kit = backend.get_record(CATALOG_STORE, kit_id)
        expected_kit_ver: int | None = existing_kit.version
    except NotFound:
        expected_kit_ver = None

    try:
        existing_idx = backend.get_record(INDEX_STORE, INDEX_KEY)
        expected_idx_ver: int | None = existing_idx.version
        kit_ids: list[str] = list(existing_idx.value.get("kit_ids", []))
    except NotFound:
        expected_idx_ver = None
        kit_ids = []

    if kit_id not in kit_ids:
        kit_ids.append(kit_id)
    kit_ids.sort()

    final_scope: VisibilityScope = (
        "allowlist_surfaces"
        if (
            requested_visibility_scope == "allowlist_surfaces"
            or published.visibility_scope == "allowlist_surfaces"
            or published.kit.visibility_scope == "allowlist_surfaces"
        )
        else "public_commons"
    )
    merged_tags = [*published.tags, *published.kit.tags]
    verified_tags = enrich_governance_tags(
        merged_tags,
        status="verified",
        domain=published.kit.domain,
        track_id=published.kit.track_id,
        deliverable_kind=published.kit.deliverable_kind,
        spdx_license=published.kit.spdx_license,
    )
    promoted_kit = published.kit.model_copy(
        update={
            "visibility_scope": final_scope,
            "tags": verified_tags,
        }
    )

    next_ver = (expected_kit_ver or 0) + 1
    payload = published.model_copy(
        update={
            "kit": promoted_kit,
            "spdx_license": promoted_kit.spdx_license,
            "tags": verified_tags,
            "target_cohorts": promoted_kit.target_cohorts,
            "producer_surface": promoted_kit.producer_surface,
            "visibility_scope": final_scope,
            "allowed_surfaces": promoted_kit.allowed_surfaces,
            "catalog_version": next_ver,
        }
    )
    catalog_governance: dict[str, Any] = {
        "spdx_license": payload.spdx_license,
        "tags": payload.tags,
        "target_cohorts": payload.target_cohorts,
        "producer_surface": payload.producer_surface,
        "visibility_scope": payload.visibility_scope,
        "allowed_surfaces": payload.allowed_surfaces,
    }
    index_governance: dict[str, Any] = {
        "spdx_license": "Apache-2.0",
        "tags": ["status:verified", "store:eranos.index"],
        "target_cohorts": ["all"],
        "producer_surface": payload.producer_surface,
        "visibility_scope": "public_commons",
        "allowed_surfaces": payload.allowed_surfaces,
    }
    backend.put_records(
        [
            _build_record_write(
                store=CATALOG_STORE,
                key=kit_id,
                value=payload.model_dump(mode="json"),
                expected_version=expected_kit_ver,
                governance=catalog_governance,
            ),
            _build_record_write(
                store=INDEX_STORE,
                key=INDEX_KEY,
                value={"kit_ids": kit_ids},
                expected_version=expected_idx_ver,
                governance=index_governance,
            ),
        ]
    )

    if hasattr(backend, "publish_feed"):
        feed_payload: dict[str, Any] = {
            "store": CATALOG_STORE,
            "key": kit_id,
            "kit_id": kit_id,
            "track_id": payload.kit.track_id,
            "domain": payload.kit.domain,
            "catalog_version": payload.catalog_version,
            "spdx_license": payload.spdx_license,
            "visibility_scope": payload.visibility_scope,
            "producer_surface": payload.producer_surface,
            "allowed_surfaces": payload.allowed_surfaces,
            "target_cohorts": payload.target_cohorts,
            "tags": payload.tags,
            "reviewed_by": payload.reviewed_by,
            "blob_sha256": payload.blob_sha256,
        }
        try:
            feed_param_names: set[str] = set(
                inspect.signature(backend.publish_feed).parameters.keys()
            )
        except (TypeError, ValueError):
            feed_param_names = set()
        feed_kwargs: dict[str, Any] = {}
        if "kind" in feed_param_names:
            feed_kwargs["kind"] = "promotion"
        if "summary" in feed_param_names:
            feed_kwargs["summary"] = (
                f"Promoted {kit_id} v{payload.catalog_version} ({payload.spdx_license}) to {CATALOG_STORE}"
            )
        backend.publish_feed("noun.promotions", feed_payload, **feed_kwargs)

    return payload


def _events_for_task(backend: Any, target_task_id: str) -> list[Any]:
    if not hasattr(backend, "events"):
        return []
    try:
        param_names: set[str] = set(inspect.signature(backend.events).parameters.keys())
    except (TypeError, ValueError):
        param_names = set()
    try:
        if "task_id" in param_names:
            raw = backend.events(task_id=target_task_id)
        elif "limit" in param_names:
            raw = backend.events(limit=1000)
        else:
            raw = backend.events()
    except Exception:
        return []
    return [ev for ev in (raw or []) if getattr(ev, "task_id", None) == target_task_id]


def _collect_drafter_identities(
    backend: Any, dep_res: Any, draft: KitDraft
) -> tuple[set[str], set[str]]:
    drafter_workers: set[str] = {draft.drafted_by.strip()} if draft.drafted_by.strip() else set()
    drafter_keys: set[str] = (
        {draft.drafted_by_key.strip()} if draft.drafted_by_key.strip() else set()
    )

    for attr_w in ("worker", "completed_by"):
        val_w = getattr(dep_res, attr_w, None)
        if isinstance(val_w, str) and val_w.strip():
            drafter_workers.add(val_w.strip())
    for attr_k in ("completed_by_key", "key_id"):
        val_k = getattr(dep_res, attr_k, None)
        if isinstance(val_k, str) and val_k.strip():
            drafter_keys.add(val_k.strip())

    draft_task_id = getattr(dep_res, "task_id", None)
    if isinstance(draft_task_id, str) and draft_task_id:
        if hasattr(backend, "results"):
            try:
                task_results = backend.results(draft_task_id)
            except Exception:
                task_results = []
            for item in task_results or []:
                if isinstance(item, dict):
                    w = item.get("worker") or item.get("completed_by")
                    k = item.get("completed_by_key") or item.get("key_id")
                else:
                    w = getattr(item, "worker", None) or getattr(item, "completed_by", None)
                    k = getattr(item, "completed_by_key", None) or getattr(item, "key_id", None)
                if isinstance(w, str) and w.strip():
                    drafter_workers.add(w.strip())
                if isinstance(k, str) and k.strip():
                    drafter_keys.add(k.strip())
        for ev in _events_for_task(backend, draft_task_id):
            ev_kind = (
                getattr(ev, "type", None) or getattr(ev, "kind", None) or getattr(ev, "event", None)
            )
            if ev_kind in {"claimed", "submitted"}:
                ev_worker = getattr(ev, "worker", None)
                if isinstance(ev_worker, str) and ev_worker.strip():
                    drafter_workers.add(ev_worker.strip())
    return drafter_workers, drafter_keys


def run_review_step(
    backend: Any,
    decision: ReviewDecision,
    *,
    worker: str,
    key_id: str,
    tracks_root: Path | None = None,
) -> dict[str, Any] | None:
    lease = _claim_with_key(backend, "eq03", worker, key_id=key_id)
    if lease is None:
        return None
    dep_res = lease.dependencies[0]
    if dep_res.output is None:
        raise UnverifiedKitRefused(
            f"draft task for {decision.kit_id} did not produce a verified draft"
        )

    draft = KitDraft.model_validate(dep_res.output["draft"])
    upstream_report = VerificationReport.model_validate(dep_res.output["verification"])
    reverified = verify_kit(draft, get_track(draft.track_id, tracks_root))
    blob_sha256 = str(dep_res.output["blob_sha256"])
    needs_steward = bool(dep_res.output.get("needs_steward_signoff", False))

    drafter_workers, drafter_keys = _collect_drafter_identities(backend, dep_res, draft)
    reviewer_workers = {w.strip() for w in (worker, decision.reviewed_by) if w and w.strip()}
    reviewer_keys = {k.strip() for k in (key_id, decision.reviewed_by_key) if k and k.strip()}

    if (
        not worker.strip()
        or not key_id.strip()
        or bool(reviewer_workers & drafter_workers)
        or bool(reviewer_keys & drafter_keys)
    ):
        backend.submit(
            lease.task_id,
            lease.fencing_token,
            {"node": "review", "status": "rejected_self_review", "kit_id": draft.kit_id},
            idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
            ok=False,
            error="two-step rule violated: drafter may not review own kit",
        )
        raise SelfReviewRefused(
            f"reviewer ({worker!r}, key {key_id!r}) matches drafter "
            f"(workers={sorted(drafter_workers)!r}, keys={sorted(drafter_keys)!r})"
        )

    if decision.verdict == "approved" and (not upstream_report.passed or not reverified.passed):
        issues = reverified.issues or upstream_report.issues
        backend.submit(
            lease.task_id,
            lease.fencing_token,
            {"node": "review", "status": "rejected_unverified", "kit_id": draft.kit_id},
            idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
            ok=False,
            error=f"unverified draft refused: {'; '.join(issues)}",
        )
        raise UnverifiedKitRefused(
            f"cannot approve {draft.kit_id}: failed deterministic checks ({'; '.join(issues)})"
        )
    report = reverified

    steward_input = lease.inputs[-1] if lease.inputs else None
    if (needs_steward or decision.verdict == "park_for_steward") and steward_input is None:
        parked: TaskView = backend.park(
            lease.task_id,
            lease.fencing_token,
            reason=f"waiting for human nonprofit steward sign-off on {draft.kit_id}",
            resume_within=604800.0,
        )
        return {
            "node": "review",
            "status": "parked",
            "kit_id": draft.kit_id,
            "park": parked.parks,
        }

    if decision.verdict == "needs_revision":
        receipt = backend.submit(
            lease.task_id,
            lease.fencing_token,
            {
                "node": "review",
                "status": "needs_revision",
                "kit_id": draft.kit_id,
                "notes": decision.notes,
            },
            idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
            ok=True,
        )
        return {
            "node": "review",
            "status": "needs_revision",
            "kit_id": draft.kit_id,
            "review_receipt": receipt.receipt_hash,
        }

    steward_label = (
        str(steward_input.get("steward") or steward_input.get("by"))
        if isinstance(steward_input, dict)
        and (steward_input.get("steward") or steward_input.get("by"))
        else None
    )
    requested_scope = str(
        dep_res.output.get("requested_visibility_scope")
        or (
            lease.brief.get("requested_visibility_scope") if isinstance(lease.brief, dict) else None
        )
        or "public_commons"
    )
    promoted_scope: VisibilityScope = (
        "allowlist_surfaces" if requested_scope == "allowlist_surfaces" else "public_commons"
    )
    verified_tags = enrich_governance_tags(
        draft.tags,
        status="verified",
        domain=draft.domain,
        track_id=draft.track_id,
        deliverable_kind=draft.deliverable_kind,
        spdx_license=draft.spdx_license,
    )
    promoted_draft = draft.model_copy(
        update={
            "visibility_scope": promoted_scope,
            "tags": verified_tags,
        }
    )
    provisional_pub = PublishedKit(
        kit=promoted_draft,
        verification=report,
        reviewed_by=worker,
        reviewed_by_key=key_id,
        review_notes=decision.notes,
        steward_signoff=steward_label,
        draft_receipt=dep_res.receipt_hash,
        blob_sha256=blob_sha256,
        spdx_license=promoted_draft.spdx_license,
        tags=verified_tags,
        target_cohorts=promoted_draft.target_cohorts,
        producer_surface=promoted_draft.producer_surface,
        visibility_scope=promoted_scope,
        allowed_surfaces=promoted_draft.allowed_surfaces,
    )
    receipt = backend.submit(
        lease.task_id,
        lease.fencing_token,
        {
            "node": "review",
            "status": "published",
            "kit_id": draft.kit_id,
            "reviewed_by": worker,
            "steward_signoff": steward_label,
            "visibility_scope": promoted_scope,
            "tags": verified_tags,
        },
        idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
        ok=True,
    )
    stored = _publish_to_catalog(
        backend,
        provisional_pub.model_copy(update={"review_receipt": receipt.receipt_hash}),
        requested_visibility_scope=promoted_scope,
    )
    return {
        "node": "review",
        "status": "published",
        "kit_id": draft.kit_id,
        "published": stored.model_dump(mode="json"),
    }


def resume_steward_signoff(
    backend: Any,
    review_task_id: str,
    *,
    by: str | None = None,
    steward: str | None = None,
    notes: str = "",
    park: int | None = None,
) -> TaskView:
    if by is not None:
        if not by or not by.strip():
            raise ValueError("steward sign-off requires a non-empty 'by' identifier")
        if steward is not None and not steward.strip():
            raise ValueError("steward sign-off requires a non-empty 'steward' identifier")
        resumer = by.strip()
        steward_name = steward.strip() if steward else resumer
    else:
        if not steward or not steward.strip():
            raise ValueError("steward sign-off requires a non-empty 'by' steward identifier")
        resumer = steward.strip()
        steward_name = resumer

    # Enforce parker != resumer across both key_id (parked_by) and parking worker name
    if hasattr(backend, "task"):
        try:
            t_view = backend.task(review_task_id)
        except Exception:
            t_view = None
        parked_by = getattr(t_view, "parked_by", None) if t_view is not None else None
        if (
            isinstance(parked_by, str)
            and parked_by.strip()
            and (resumer == parked_by.strip() or steward_name == parked_by.strip())
        ):
            raise Forbidden("the key that parked this task may not resume it")
    evs = _events_for_task(backend, review_task_id)
    if evs:
        park_workers = {
            ev.worker.strip()
            for ev in evs
            if (getattr(ev, "type", None) or getattr(ev, "kind", None)) == "parked"
            and isinstance(getattr(ev, "worker", None), str)
            and ev.worker.strip()
        }
        if resumer in park_workers or steward_name in park_workers:
            raise Forbidden("the worker that parked this task may not resume it")

    try:
        resume_param_names: set[str] = set(inspect.signature(backend.resume).parameters.keys())
    except (TypeError, ValueError):
        resume_param_names = set()
    resume_kwargs: dict[str, Any] = {"park": park}
    if "by" in resume_param_names:
        resume_kwargs["by"] = resumer

    view: TaskView = backend.resume(
        review_task_id,
        {"steward": steward_name, "by": resumer, "notes": notes},
        **resume_kwargs,
    )
    return view


def _is_quarantined(entry: PublishedKit) -> bool:
    if entry.visibility_scope == "surface_only" or entry.kit.visibility_scope == "surface_only":
        return True
    lower_tags = {t.lower() for t in [*entry.tags, *entry.kit.tags]}
    return "status:quarantined" in lower_tags


def list_published_kits(backend: Any) -> list[PublishedKit]:
    with _eranos_surface_scope(backend):
        try:
            idx = backend.get_record(INDEX_STORE, INDEX_KEY)
        except NotFound:
            return []
        out: list[PublishedKit] = []
        for kit_id in idx.value.get("kit_ids", []):
            try:
                rec = backend.get_record(CATALOG_STORE, kit_id)
            except NotFound:
                continue
            raw_val = rec.value
            if isinstance(raw_val, dict):
                raw_tags = [
                    *(raw_val.get("tags") or []),
                    *((raw_val.get("kit") or {}).get("tags") or []),
                ]
                if any(str(t).lower() == "status:quarantined" for t in raw_tags):
                    continue
                if (
                    raw_val.get("visibility_scope") == "surface_only"
                    or (raw_val.get("kit") or {}).get("visibility_scope") == "surface_only"
                ):
                    continue
            entry = PublishedKit.model_validate(raw_val)
            if not _is_quarantined(entry):
                out.append(entry)
        return out


def filter_published_kits(
    kits: list[PublishedKit],
    *,
    domain: str | None = None,
    track: str | None = None,
    tag: str | None = None,
    cohort: str | None = None,
    spdx: str | None = None,
    q: str | None = None,
) -> list[PublishedKit]:
    dom_q = (domain or "").strip().lower()
    track_q = (track or "").strip().lower()
    tag_parts = [t.strip().lower() for t in (tag or "").split(",") if t.strip()]
    cohort_q = (cohort or "").strip().lower()
    spdx_q = (spdx or "").strip().lower()
    text_q = (q or "").strip().lower()

    filtered: list[PublishedKit] = []
    for entry in kits:
        if _is_quarantined(entry):
            continue
        kit = entry.kit
        all_tags = list(dict.fromkeys([*entry.tags, *kit.tags]))
        lower_tags = {t.lower() for t in all_tags}
        cohorts = [c.lower() for c in (entry.target_cohorts or kit.target_cohorts or ["all"])]

        # Cohort rule:
        # - When ?cohort= is omitted: ONLY return kits whose target_cohorts contains "all".
        # - When ?cohort=X is passed: return kits whose target_cohorts contains "all" OR X.
        if not cohort_q:
            if "all" not in cohorts:
                continue
        else:
            bare_cohort = cohort_q[7:] if cohort_q.startswith("cohort:") else cohort_q
            if not (
                "all" in cohorts
                or cohort_q in cohorts
                or bare_cohort in cohorts
                or f"cohort:{bare_cohort}" in cohorts
            ):
                continue

        if dom_q and kit.domain.lower() != dom_q:
            continue
        if track_q and kit.track_id.lower() != track_q:
            continue
        if tag_parts and not all(tp in lower_tags for tp in tag_parts):
            continue
        kit_spdx = (entry.spdx_license or kit.spdx_license or "Apache-2.0").lower()
        if spdx_q and kit_spdx != spdx_q:
            continue

        if text_q:
            haystack_parts = [
                kit.kit_id,
                kit.title,
                kit.summary,
                kit.target_org,
                kit.track_id,
                kit.domain,
                kit.deliverable_kind,
                entry.spdx_license,
                *all_tags,
                *cohorts,
                *(s.name for s in kit.all_skills()),
                *(s.description for s in kit.all_skills()),
                *(t.name for t in kit.all_tools()),
                *(t.description for t in kit.all_tools()),
                *(a.name for a in kit.artifacts),
                *(a.title for a in kit.artifacts),
                *(a.summary for a in kit.artifacts),
            ]
            if text_q not in " ".join(haystack_parts).lower():
                continue

        filtered.append(entry)
    return filtered


def get_published_kit(backend: Any, kit_id: str) -> PublishedKit | None:
    with _eranos_surface_scope(backend):
        try:
            rec = backend.get_record(CATALOG_STORE, kit_id)
        except NotFound:
            return None
    raw_val = rec.value
    if isinstance(raw_val, dict):
        raw_tags = [
            *(raw_val.get("tags") or []),
            *((raw_val.get("kit") or {}).get("tags") or []),
        ]
        if any(str(t).lower() == "status:quarantined" for t in raw_tags):
            return None
        if (
            raw_val.get("visibility_scope") == "surface_only"
            or (raw_val.get("kit") or {}).get("visibility_scope") == "surface_only"
        ):
            return None
    entry = PublishedKit.model_validate(raw_val)
    if _is_quarantined(entry):
        return None
    return entry


def load_example_bundles(examples_dir: Path | None = None) -> list[dict[str, Any]]:
    folder = examples_dir or (Path(__file__).resolve().parents[2] / "examples" / "kits")
    return [load_json(p) for p in sorted(folder.glob("*.json"))]


__all__ = [
    "CATALOG_STORE",
    "INDEX_KEY",
    "INDEX_STORE",
    "KitGraph",
    "SelfReviewError",
    "SelfReviewRefused",
    "UnverifiedKitRefused",
    "enrich_governance_tags",
    "ensure_queues",
    "filter_published_kits",
    "get_published_kit",
    "list_published_kits",
    "load_example_bundles",
    "new_run_id",
    "practice_verify_kit",
    "resume_steward_signoff",
    "run_draft_step",
    "run_review_step",
    "run_spec_step",
    "submit_kit_request",
]
