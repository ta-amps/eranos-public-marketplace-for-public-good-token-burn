"""Scoped keys for Eranos's volunteer workers: one per role, each its own principal and account.

The same shapes are issued in the local tests and at go-live, so what the tests prove is what runs.
A key is written only into a 0600 environment file; it is never printed, logged or returned to a
caller that would print it. `ERANOS_KEY_ID` (not a secret) lets a reviewer prove it differs from
the builder whose work it checks.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

SCOPES = [
    "nouns:read",
    "cas:write",
    "verbs:claim",
    "verbs:submit",
    "namespace:main",
    "surface:eranos",
]
REVIEW_KINDS = ["report_review", "review", "process_review"]
ROLE_KEYS: dict[str, dict[str, Any]] = {
    "planner": {"queues": ["eq01", "eq02", "eq03"], "kinds": ["request"], "role": "planner"},
    "builder": {"queues": ["eq02"], "kinds": ["research", "build", "process"], "role": "builder"},
    "reviewer": {"queues": ["eq02", "eq03"], "kinds": REVIEW_KINDS, "role": "reviewer"},
    "reviewer2": {"queues": ["eq02", "eq03"], "kinds": REVIEW_KINDS, "role": "reviewer"},
}


def issue_key(
    http: httpx.Client,
    admin_key: str,
    name: str,
    *,
    days: float,
    account_prefix: str = "eranos-worker",
) -> dict[str, Any]:
    """Issue one role's key; the returned dict holds the secret, so callers must not print it."""
    spec = ROLE_KEYS[name]
    response = http.post(
        "/v1/admin/keys",
        json={
            "label": f"eranos-{name}",
            "account_id": f"{account_prefix}-{name}",
            "queues": spec["queues"],
            "kinds": spec["kinds"],
            "effect_classes": ["read", "write-internal"],
            "scopes": SCOPES,
            "days": days,
        },
        headers={"authorization": f"Bearer {admin_key}"},
    )
    if response.status_code != 201:
        raise RuntimeError(
            f"issuing the {name} key failed: {response.status_code} {response.text[:200]}"
        )
    body = dict(response.json())
    return {
        "name": name,
        "role": spec["role"],
        "key": str(body["key"]),
        "key_id": str(body["key_id"]),
        "expires_at": body.get("expires_at"),
        "queues": spec["queues"],
        "kinds": spec["kinds"],
    }


def write_env_file(
    path: Path, issued: dict[str, Any], *, tessera_url: str, extra: dict[str, str] | None = None
) -> None:
    """The worker's environment file, created 0600 before the secret is written into it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = {
        "ERANOS_BACKEND": "tessera",
        "TESSERA_URL": tessera_url,
        "TESSERA_KEY": issued["key"],
        "ERANOS_KEY_ID": issued["key_id"],
        "ERANOS_WORKER_ROLE": issued["role"],
        "ERANOS_WORKER_LABEL": f"eranos-{issued['name']}",
        **(extra or {}),
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("".join(f"{k}={v}\n" for k, v in lines.items()))
    path.chmod(0o600)


def public_summary(issued: dict[str, Any]) -> dict[str, Any]:
    """What may be shown about an issued key: everything except the secret."""
    return {k: v for k, v in issued.items() if k != "key"}
