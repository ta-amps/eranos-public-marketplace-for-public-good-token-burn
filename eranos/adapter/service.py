"""Service backend: reaches the Tessera HTTP service with a scoped worker key."""

from __future__ import annotations

import os

from tessera.client import Client


def create() -> Client:
    url = os.environ.get("TESSERA_URL")
    if not url:
        raise RuntimeError("ERANOS_BACKEND=tessera needs TESSERA_URL (and TESSERA_KEY in .env)")
    return Client(url, key=os.environ.get("TESSERA_KEY"))
