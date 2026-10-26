"""Two-step volunteer agent pipeline on Tessera (`eq01` spec -> `eq02` draft -> `eq03` review -> CAS catalog).

Enforces:
- `drafter != reviewer` across both worker IDs and Tessera key IDs;
- deterministic verification before any review approval can publish;
- optional human nonprofit steward sign-off via Tessera `park` and `resume` (`parker != resumer`);
- atomic compare-and-set batch publish (`eranos.catalog` + `eranos.index`) and content-addressed blobs.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tessera import NotFound, RecordWrite, TaskSpec, TaskView

from eranos.jsonfile import load_json
from eranos.queues import QUEUE_CONFIGS
from eranos.schemas import (
    KitDraft,
    KitRequest,
    PublishedKit,
    ReviewDecision,
    TrackPack,
    VerificationReport,
)
from eranos.tracks import get_track
from eranos.verifier import verify_kit

CATALOG_STORE = "eranos.catalog"
INDEX_STORE = "eranos.index"
INDEX_KEY = "kits"


class SelfReviewRefused(PermissionError):
    """The agent or key that drafted a kit may never approve its review."""


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


def submit_kit_request(
    backend: Any,
    request: KitRequest,
    *,
    run_id: str | None = None,
    tracks_root: Path | None = None,
) -> KitGraph:
    ensure_queues(backend)
    # Validate track exists up front before queueing work
    get_track(request.track_id, tracks_root)
    rid = run_id or new_run_id()
    spec_id = f"{rid}:{request.kit_id}:spec"
    draft_id = f"{rid}:{request.kit_id}:draft"
    review_id = f"{rid}:{request.kit_id}:review"

    backend.enqueue(
        TaskSpec(
            queue="eq01",
            task_id=spec_id,
            kind="spec",
            effect_class="read",
            brief={"run_id": rid, "request": request.model_dump(mode="json")},
        )
    )
    backend.enqueue(
        TaskSpec(
            queue="eq02",
            task_id=draft_id,
            kind="draft",
            effect_class="write-internal",
            depends_on=[spec_id],
            brief={"run_id": rid, "request": request.model_dump(mode="json")},
        )
    )
    backend.enqueue(
        TaskSpec(
            queue="eq03",
            task_id=review_id,
            kind="review",
            effect_class="write-internal",
            depends_on=[draft_id],
            brief={"run_id": rid, "request": request.model_dump(mode="json")},
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
    backend: Any, *, worker: str = "spec-gate-01", tracks_root: Path | None = None
) -> dict[str, Any] | None:
    lease = backend.claim("eq01", worker)
    if lease is None:
        return None
    req = KitRequest.model_validate(lease.brief["request"])
    track = get_track(req.track_id, tracks_root)
    output: dict[str, Any] = {
        "node": "spec",
        "kit_id": req.kit_id,
        "track": track.model_dump(mode="json"),
        "needs_steward_signoff": req.needs_steward_signoff,
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
    lease = backend.claim("eq02", worker)
    if lease is None:
        return None
    dep_out = lease.dependencies[0].output
    if dep_out is None:
        raise RuntimeError(f"upstream spec output missing for {lease.task_id}")
    track = TrackPack.model_validate(dep_out["track"])
    raw = (
        draft_payload.model_dump(mode="json")
        if isinstance(draft_payload, KitDraft)
        else dict(draft_payload)
    )
    raw["drafted_by"] = worker
    raw["drafted_by_key"] = key_id
    draft = KitDraft.model_validate(raw)
    report = verify_kit(draft, track)

    canonical_bytes = json.dumps(draft.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    blob_sha256: str = backend.put_blob(canonical_bytes)

    provisional: dict[str, Any] = {
        "node": "draft",
        "draft": draft.model_dump(mode="json"),
        "verification": report.model_dump(mode="json"),
        "blob_sha256": blob_sha256,
        "needs_steward_signoff": bool(dep_out.get("needs_steward_signoff", False)),
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


def _publish_to_catalog(backend: Any, published: PublishedKit) -> PublishedKit:
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

    next_ver = (expected_kit_ver or 0) + 1
    payload = published.model_copy(update={"catalog_version": next_ver})
    backend.put_records(
        [
            RecordWrite(
                store=CATALOG_STORE,
                key=kit_id,
                value=payload.model_dump(mode="json"),
                expected_version=expected_kit_ver,
            ),
            RecordWrite(
                store=INDEX_STORE,
                key=INDEX_KEY,
                value={"kit_ids": kit_ids},
                expected_version=expected_idx_ver,
            ),
        ]
    )
    return payload


def run_review_step(
    backend: Any,
    decision: ReviewDecision,
    *,
    worker: str,
    key_id: str,
    tracks_root: Path | None = None,
) -> dict[str, Any] | None:
    lease = backend.claim("eq03", worker)
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

    if worker == draft.drafted_by or key_id == draft.drafted_by_key:
        backend.submit(
            lease.task_id,
            lease.fencing_token,
            {"node": "review", "status": "rejected_self_review", "kit_id": draft.kit_id},
            idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
            ok=False,
            error="two-step rule violated: drafter may not review own kit",
        )
        raise SelfReviewRefused(
            f"reviewer ({worker!r}, key {key_id!r}) matches drafter ({draft.drafted_by!r}, key {draft.drafted_by_key!r})"
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
        str(steward_input.get("steward"))
        if isinstance(steward_input, dict) and steward_input.get("steward")
        else None
    )
    provisional_pub = PublishedKit(
        kit=draft,
        verification=report,
        reviewed_by=worker,
        reviewed_by_key=key_id,
        review_notes=decision.notes,
        steward_signoff=steward_label,
        draft_receipt=dep_res.receipt_hash,
        blob_sha256=blob_sha256,
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
        },
        idempotency_key=f"{lease.task_id}:{lease.fencing_token}",
        ok=True,
    )
    stored = _publish_to_catalog(
        backend, provisional_pub.model_copy(update={"review_receipt": receipt.receipt_hash})
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
    steward: str,
    notes: str,
    park: int | None = None,
) -> TaskView:
    view: TaskView = backend.resume(
        review_task_id,
        {"steward": steward, "notes": notes},
        park=park,
    )
    return view


def list_published_kits(backend: Any) -> list[PublishedKit]:
    try:
        idx = backend.get_record(INDEX_STORE, INDEX_KEY)
    except NotFound:
        return []
    out: list[PublishedKit] = []
    for kit_id in idx.value.get("kit_ids", []):
        rec = backend.get_record(CATALOG_STORE, kit_id)
        out.append(PublishedKit.model_validate(rec.value))
    return out


def get_published_kit(backend: Any, kit_id: str) -> PublishedKit | None:
    try:
        rec = backend.get_record(CATALOG_STORE, kit_id)
    except NotFound:
        return None
    return PublishedKit.model_validate(rec.value)


def load_example_bundles(examples_dir: Path | None = None) -> list[dict[str, Any]]:
    folder = examples_dir or (Path(__file__).resolve().parents[2] / "examples" / "kits")
    return [load_json(p) for p in sorted(folder.glob("*.json"))]
