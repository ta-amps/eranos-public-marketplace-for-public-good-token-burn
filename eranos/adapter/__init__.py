"""Fabric adapter: selects `local` (Tessera SQLite Store) or `tessera` (Tessera HTTP service)."""

from __future__ import annotations

from eranos import config
from eranos.adapter import local, service
from eranos.adapter.traced import TracedBackend


def get_adapter(db_path: str | None = None) -> TracedBackend:
    kind = config.backend_name()
    if kind == "local":
        return TracedBackend(local.create(db_path), backend="local")
    if kind == "tessera":
        return TracedBackend(service.create(), backend="tessera")
    raise ValueError(f"unknown ERANOS_BACKEND={kind!r}; expected 'local' or 'tessera'")


__all__ = ["TracedBackend", "get_adapter"]
