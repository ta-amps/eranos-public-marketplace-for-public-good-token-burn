"""Local backend: Tessera's in-process SQLite store."""

from __future__ import annotations

from tessera import Store
from tessera.clock import Clock

from eranos import config
from eranos.adapter.traced import TracedBackend


def create(db_path: str | None = None) -> Store:
    return Store(db_path or config.local_db_path())


def conformance_factory(db_path: str, clock: Clock) -> TracedBackend:
    return TracedBackend(Store(db_path, clock=clock), backend="local", clock=clock)
