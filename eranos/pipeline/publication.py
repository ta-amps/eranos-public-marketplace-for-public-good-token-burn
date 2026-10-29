"""Durable review intent, independent proof and retryable catalog publication."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from tessera import NotFound
from tessera.receipts import canonical_json

from eranos.schemas import PublishedKit

OUTBOX_STORE = "eranos.publication_outbox"


def publication_digest(published: PublishedKit) -> str:
    """Hash the immutable approved content, excluding receipt/version/digest assigned later."""
    value = published.model_dump(mode="json")
    value.pop("publication_sha256", None)
    value["review_receipt"] = None
    value["catalog_version"] = 1
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def prepare_publication(backend: Any, published: PublishedKit, fencing_token: int) -> str:
    key = published.kit.kit_id
    try:
        prior = backend.get_record(OUTBOX_STORE, key)
        version = prior.version
    except NotFound:
        version = 0
    backend.put_record(
        OUTBOX_STORE,
        key,
        {
            "status": "pending",
            "fencing_token": fencing_token,
            "publication": published.model_dump(mode="json"),
        },
        expected_version=version,
        producer_surface="surface:eranos",
        visibility_scope="surface_only",
        tags=["status:quarantined", "kind:publication_intent"],
    )
    return key


def recover_publications(
    backend: Any,
    publish: Callable[..., PublishedKit],
    *,
    kit_id: str,
    key_id: str,
) -> PublishedKit | None:
    """Only a completed, matching approval can release a prepared intent to the catalog."""
    try:
        pending = [backend.get_record(OUTBOX_STORE, kit_id)]
    except NotFound:
        return None
    for intent in pending:
        if intent.value.get("status") != "pending":
            continue
        candidate = PublishedKit.model_validate(intent.value["publication"])
        if candidate.reviewer_key_id != key_id:
            continue
        for result in backend.results(candidate.review_task_id):
            proof = result.output or {}
            if not result.ok or result.state_after != "done" or proof.get("approved") is not True:
                continue
            if result.fencing_token != intent.value["fencing_token"]:
                continue
            if any(
                proof.get(field) != getattr(candidate, field)
                for field in (
                    "review_task_id",
                    "draft_task_id",
                    "draft_sha256",
                    "drafter_key_id",
                    "reviewer_key_id",
                    "publication_sha256",
                )
            ):
                continue
            if (
                proof.get("kit_id") != kit_id
                or publication_digest(candidate) != candidate.publication_sha256
            ):
                continue
            if result.completed_by_key and result.completed_by_key != candidate.reviewer_key_id:
                continue
            approved = candidate.model_copy(update={"review_receipt": result.receipt_hash})
            stored = publish(
                backend, approved, requested_visibility_scope=approved.visibility_scope
            )
            backend.put_record(
                OUTBOX_STORE,
                intent.key,
                {**intent.value, "status": "published", "review_receipt": result.receipt_hash},
                expected_version=intent.version,
                producer_surface="surface:eranos",
                visibility_scope="surface_only",
                tags=["status:quarantined", "kind:publication_intent"],
            )
            return stored
    return None
