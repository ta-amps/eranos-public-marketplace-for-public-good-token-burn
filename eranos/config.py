"""Runtime settings from environment variables. No secrets are stored in code."""

from __future__ import annotations

import os

MODEL_API_KEY_ENV = "MODEL_API_KEY"
BACKEND_ENV = "ERANOS_BACKEND"
LOCAL_DB_ENV = "ERANOS_LOCAL_DB"
FABRIC_NAME_ENV = "ERANOS_FABRIC_NAME"
TRACE_ENV = "ERANOS_TRACE"


def backend_name() -> str:
    return os.environ.get(BACKEND_ENV, "local")


def local_db_path() -> str:
    return os.environ.get(LOCAL_DB_ENV, ".eranos/local.db")


def fabric_display_name() -> str:
    return os.environ.get(FABRIC_NAME_ENV, "Tessera")


def trace_path() -> str:
    return os.environ.get(TRACE_ENV, "traces/run.jsonl")
