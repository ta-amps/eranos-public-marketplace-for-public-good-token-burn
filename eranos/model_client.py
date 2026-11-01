"""A local model for workers: Llama 3.2 3B Instruct served by Ollama on this machine ($0, no cloud).

The client only talks to a loopback address. It records what each call used (prompt and output
tokens from Ollama's own counters) and identifies the exact weights (the manifest digest and the
GGUF blob digest), so every execution report can name the model it ran. A contributor-tier model id
is refused, as everywhere in Eranos. No call is retried silently: a failure is raised to the verb.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.2:3b"
_BLOB = re.compile(r"sha256[-:]([0-9a-f]{64})")


class ModelUnavailable(RuntimeError):
    """The local model did not answer; the verb records a failure instead of guessing."""


class ContributorTierRefused(PermissionError):
    """Eranos never sends material to a contributor-tier model."""


@dataclass
class ModelCall:
    input_tokens: int
    output_tokens: int
    seconds: float
    temperature: float = 0.0
    seed: int | None = None


@dataclass
class UsageMeter:
    """What one verb's work used. Zero tokens is recorded only when no model was called."""

    model: dict[str, Any] | None = None
    calls: list[ModelCall] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, model: dict[str, Any], call: ModelCall) -> None:
        with self._lock:
            self.model = model
            self.calls.append(call)

    @property
    def input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def usage(self) -> dict[str, Any]:
        if not self.calls:
            return {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "source": "no model was called; deterministic code only",
            }
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "source": "ollama response counters (prompt_eval_count, eval_count)",
        }

    def model_report(self) -> dict[str, Any] | None:
        if self.model is None:
            return None
        sampling = [{"temperature": c.temperature, "seed": c.seed} for c in self.calls]
        return {**self.model, "calls": len(self.calls), "cost_usd": 0.0, "sampling": sampling}


class ChatModel(Protocol):
    def describe(self) -> dict[str, Any]: ...

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        meter: UsageMeter,
        max_tokens: int = 900,
        temperature: float = 0.0,
        seed: int | None = None,
    ) -> dict[str, Any]: ...


def refuse_contributor(model_id: str) -> None:
    if model_id.endswith("-contributor") or model_id == "contributor":
        raise ContributorTierRefused(f"{model_id!r} is a contributor-tier model; refused")


class OllamaModel:
    """Ollama's /api/chat in JSON mode, temperature 0 and a fixed seed, on a loopback address only."""

    def __init__(
        self,
        url: str = DEFAULT_URL,
        model: str = DEFAULT_MODEL,
        *,
        seed: int = 20261031,
        num_ctx: int = 8192,
        timeout: float = 600.0,
        adapter: dict[str, Any] | None = None,
    ) -> None:
        host = (urlsplit(url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError(
                "the worker's model must be served on this machine (a loopback address)"
            )
        refuse_contributor(model)
        self.url = url.rstrip("/")
        self.model = model
        self.seed = seed
        self.num_ctx = num_ctx
        self.adapter = adapter
        self._http = httpx.Client(base_url=self.url, timeout=timeout, trust_env=False)
        self._described: dict[str, Any] | None = None

    def close(self) -> None:
        self._http.close()

    def healthy(self) -> None:
        """Raise ModelUnavailable unless the local server answers now (a cheap check before a claim)."""
        try:
            self._http.get("/api/version", timeout=5.0).raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelUnavailable(f"the local model server at {self.url} did not answer") from exc

    def describe(self) -> dict[str, Any]:
        """The exact weights in use: Ollama's manifest digest and the GGUF blob it loads."""
        if self._described is not None:
            return self._described
        try:
            tags = self._http.get("/api/tags", timeout=10.0).json().get("models") or []
            shown = self._http.post("/api/show", json={"model": self.model}, timeout=10.0).json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelUnavailable(f"the local model server at {self.url} did not answer") from exc
        entry = next((m for m in tags if m.get("name") == self.model), None)
        if entry is None:
            raise ModelUnavailable(f"{self.model} is not pulled on this machine")
        blob = _BLOB.search(str(shown.get("modelfile") or ""))
        details = shown.get("details") or {}
        self._described = {
            "provider": "ollama",
            "id": self.model,
            "family": str(details.get("family") or ""),
            "parameter_size": str(details.get("parameter_size") or ""),
            "quantization": str(details.get("quantization_level") or ""),
            "digest": str(entry.get("digest") or ""),
            "weights_sha256": blob.group(1) if blob else None,
            "adapter": self.adapter,
            "adapter_note": None if self.adapter else "base weights; no LoRA adapter loaded",
            "location": "this machine (loopback), local GPU",
            "invocation_origin": "worker_local",
            "payer": "the volunteer running this worker; $0 in API charges",
            "temperature": 0,
            "seed": self.seed,
        }
        return self._described

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        meter: UsageMeter,
        max_tokens: int = 900,
        temperature: float = 0.0,
        seed: int | None = None,
    ) -> dict[str, Any]:
        described = self.describe()
        seed = self.seed if seed is None else seed
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "format": "json",
            "keep_alive": "15m",
            "options": {
                "temperature": temperature,
                "seed": seed,
                "num_ctx": self.num_ctx,
                "num_predict": max_tokens,
            },
        }
        try:
            response = self._http.post("/api/chat", json=body)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ModelUnavailable(f"{self.model} did not answer: {type(exc).__name__}") from exc
        meter.add(
            described,
            ModelCall(
                input_tokens=int(data.get("prompt_eval_count") or 0),
                output_tokens=int(data.get("eval_count") or 0),
                seconds=round(float(data.get("total_duration") or 0) / 1e9, 3),
                temperature=temperature,
                seed=seed,
            ),
        )
        content = str((data.get("message") or {}).get("content") or "")
        try:
            parsed = json.loads(content)
        except ValueError:
            return {"unparsed": content[:2000]}
        return parsed if isinstance(parsed, dict) else {"unparsed": content[:2000]}
