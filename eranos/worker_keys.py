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
REVIEW_KINDS = ["report_review", "process_review", "review"]
# Least privilege per role: the planner needs eq02 and eq03 only to split a request into them; the
# builder works eq02 only; a reviewer reads everything it needs from its own eq03 brief and lease.
# The kit kinds (spec, draft, review) let the dedicated workers rebuild the example kits; the
# kit-intake key may only queue those kit verbs: it claims nothing and writes no record.
ROLE_KEYS: dict[str, dict[str, Any]] = {
    "planner": {
        "queues": ["eq01", "eq02", "eq03"],
        "kinds": ["request", "spec", "tune"],
        "role": "planner",
    },
    "builder": {"queues": ["eq02"], "kinds": ["research", "process", "draft"], "role": "builder"},
    "builder2": {"queues": ["eq02"], "kinds": ["research", "process", "draft"], "role": "builder"},
    "reviewer": {"queues": ["eq03"], "kinds": REVIEW_KINDS, "role": "reviewer"},
    "reviewer2": {"queues": ["eq03"], "kinds": REVIEW_KINDS, "role": "reviewer"},
}
# The volunteer mode, started only for a take: research on eq02 and research checks on eq03, with
# its own principal (account) so it is never mistaken for a dedicated worker.
VOLUNTEER_KEY: dict[str, Any] = {
    "queues": ["eq02", "eq03"],
    "kinds": ["research", "report_review"],
    "role": "volunteer",
    "account_id": "eranos-volunteer",
}
INTAKE_KEY: dict[str, Any] = {
    "queues": ["eq01", "eq02", "eq03"],
    "kinds": ["spec", "draft", "review"],
    "role": "intake",
    "scopes": ["nouns:read", "verbs:submit", "namespace:main", "surface:eranos"],
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
    spec = (
        INTAKE_KEY
        if name == "kit-intake"
        else VOLUNTEER_KEY
        if name == "volunteer"
        else ROLE_KEYS[name]
    )
    response = http.post(
        "/v1/admin/keys",
        json={
            "label": f"eranos-{name}",
            "account_id": spec.get("account_id") or f"{account_prefix}-{name}",
            "queues": spec["queues"],
            "kinds": spec["kinds"],
            "effect_classes": ["read", "write-internal"],
            "scopes": spec.get("scopes", SCOPES),
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
    """The worker's environment file: written to a new 0600 file, then moved into place.

    The new file is created exclusively (never through a link) under a 0077 umask, so the key is
    never in a file anyone else can read, even for a moment, and an old file's mode cannot leak.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lines = {
        "ERANOS_BACKEND": "tessera",
        "TESSERA_URL": tessera_url,
        "TESSERA_KEY": issued["key"],
        "ERANOS_KEY_ID": issued["key_id"],
        "ERANOS_WORKER_ROLE": issued["role"],
        "ERANOS_WORKER_LABEL": f"eranos-{issued['name']}",
        **(extra or {}),
    }
    if any("\n" in str(v) or "\r" in str(v) for v in lines.values()):
        raise ValueError("an environment value may not contain a line break")
    temp = path.with_name(f".{path.name}.{os.getpid()}.new")
    old_mask = os.umask(0o077)
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    finally:
        os.umask(old_mask)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            os.fchmod(fh.fileno(), 0o600)
            fh.write("".join(f"{k}={v}\n" for k, v in lines.items()))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def key_ids_in(directory: Path) -> dict[str, str]:
    """The key ids named in a folder's env files (not secrets), for revoking before replacing."""
    out = {}
    for path in sorted(directory.glob("*.env")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("ERANOS_KEY_ID="):
                out[path.name] = line.split("=", 1)[1].strip()
    return out


def public_summary(issued: dict[str, Any]) -> dict[str, Any]:
    """What may be shown about an issued key: everything except the secret."""
    return {k: v for k, v in issued.items() if k != "key"}
