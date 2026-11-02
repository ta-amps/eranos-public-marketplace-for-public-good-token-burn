"""Runtime settings from environment variables. No secrets are stored in code."""

from __future__ import annotations

import os

MODEL_API_KEY_ENV = "MODEL_API_KEY"
BACKEND_ENV = "ERANOS_BACKEND"
LOCAL_DB_ENV = "ERANOS_LOCAL_DB"
FABRIC_NAME_ENV = "ERANOS_FABRIC_NAME"
SURFACE_NAME_ENV = "ERANOS_SURFACE_NAME"
PUBLIC_URL_ENV = "ERANOS_PUBLIC_URL"
SIBLING_DETECTION_NAME_ENV = "ERANOS_SIBLING_NAME"
SIBLING_DETECTION_URL_ENV = "ERANOS_SIBLING_URL"
PUBLIC_TESSERA_URL_ENV = "ERANOS_PUBLIC_TESSERA_URL"
TRACE_ENV = "ERANOS_TRACE"


def backend_name() -> str:
    return os.environ.get(BACKEND_ENV, "local")


def local_db_path() -> str:
    return os.environ.get(LOCAL_DB_ENV, ".eranos/local.db")


def fabric_display_name() -> str:
    return os.environ.get(FABRIC_NAME_ENV, "Tessera")


def surface_display_name() -> str:
    return os.environ.get(SURFACE_NAME_ENV, "Eranos")


def surface_public_url() -> str:
    return os.environ.get(PUBLIC_URL_ENV, "https://eranosforgood.org")


def sibling_detection_name() -> str:
    return os.environ.get(SIBLING_DETECTION_NAME_ENV, "Shamash")


def sibling_detection_url() -> str:
    return os.environ.get(SIBLING_DETECTION_URL_ENV, "https://shamash.ta-amps.workers.dev")


def public_tessera_url() -> str:
    return os.environ.get(PUBLIC_TESSERA_URL_ENV, "https://tessera.ta-amps.workers.dev")


def trace_path() -> str:
    return os.environ.get(TRACE_ENV, "traces/run.jsonl")
