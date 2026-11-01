"""The workers' model: Meta's Muse models through the Meta API, at the standard tier only.

The model id, the API address, the token prices and the spending caps come from the worker noun
(`eranos.instructions/worker`, `model`), never from code; the model's display name comes from the
model catalog noun (`eranos.instructions/models.meta`). The key is read from the file named by
ERANOS_META_KEY_FILE at call time and is never printed or logged. Every call records its tokens
and its cost; a shared ledger keeps the day's spend and the running total against the owner's
caps, and a call that would pass a cap is refused before it is made. A contributor-tier model id
is refused, as everywhere in Eranos. There is no fallback to any other model: a failure is raised
to the verb, recorded there, and the verb is retried later.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

KEY_FILE_ENV = "ERANOS_META_KEY_FILE"
LEDGER_ENV = "ERANOS_META_LEDGER"
META_HOSTS = frozenset({"api.meta.ai"})


class ModelUnavailable(RuntimeError):
    """The model did not answer; the verb records a failure instead of guessing."""


class BudgetExhausted(ModelUnavailable):
    """A spending cap would be passed; nothing was sent."""


class ContributorTierRefused(PermissionError):
    """Eranos never sends material to a contributor-tier model."""


@dataclass
class ModelCall:
    input_tokens: int
    output_tokens: int
    seconds: float
    temperature: float = 0.0
    seed: int | None = None
    cost_usd: float = 0.0
    reasoning_effort: str | None = None


@dataclass
class UsageMeter:
    """What one verb's work used. Zero tokens and zero cost are recorded only when no model was called."""

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

    @property
    def cost_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.calls), 6)

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
            "source": "Meta API response usage (prompt_tokens, completion_tokens)",
        }

    def model_report(self) -> dict[str, Any] | None:
        if self.model is None:
            return None
        sampling = [
            {"temperature": c.temperature, "seed": c.seed}
            | ({"reasoning_effort": c.reasoning_effort} if c.reasoning_effort else {})
            for c in self.calls
        ]
        return {
            **self.model,
            "calls": len(self.calls),
            "cost_usd": self.cost_usd,
            "sampling": sampling,
        }


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
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]: ...


KEY_NAME = "META_API_KEY"
# The owner's caps and Meta's list rates, as ceilings and floors in code: a Task Object can lower
# the caps or raise the rates, never the other way (review M1). A model missing here is not called.
MAX_DAILY_USD, MAX_TOTAL_USD = 5.0, 150.0
MIN_RATES_USD_PER_MILLION = {
    "muse-spark-1.3": {"input": 1.25, "output": 4.25},
    "muse-wonder-1.0": {"input": 4.0, "output": 20.0},
}


def key_from_text(text: str) -> str:
    """The key in a key file: the file's only content, or the value of its `META_API_KEY=` line
    (an 0600 env file). No other name is read, so a worker env file's Tessera key is never taken
    for the Meta key (review M3). Never logged or returned to a caller that prints."""
    for line in text.splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == KEY_NAME:
            return value.strip().strip("'\"")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[0] if len(lines) == 1 and "=" not in lines[0] else ""


def refuse_contributor(model_id: str) -> None:
    if "contributor" in model_id.lower():  # any spelling, case or separator
        raise ContributorTierRefused(f"{model_id!r} is a contributor-tier model; refused")


class Ledger:
    """The owner's Meta spend: one total per UTC day and a running total, shared by every worker on
    this machine. A call reserves its largest possible cost first, under a file lock, and is refused
    when that could pass a cap; the answer's real cost then replaces the reservation. A call that
    was sent but never answered keeps its reservation, since Meta may have billed it."""

    def __init__(self, path: str | Path, *, daily_usd: float, total_usd: float) -> None:
        self.path = Path(path)
        # The noun can only lower the owner's caps (review M1).
        self.daily_usd = min(float(daily_usd), MAX_DAILY_USD)
        self.total_usd = min(float(total_usd), MAX_TOTAL_USD)

    def _update(self, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        """Read, change and write the ledger under a lock on a side file. The new contents go to a
        temporary file in the same folder, are synced, then replace the ledger in one rename, so a
        kill at any moment leaves the old ledger or the new one, never an empty one (review M2)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = os.open(self.path.with_name(self.path.name + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            text = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
            data = json.loads(text) if text.strip() else {"days": {}, "total_usd": 0.0, "calls": 0}
            change(data)  # raising here leaves the ledger as it was
            temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(data, sort_keys=True))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp, self.path)
            return dict(data)
        finally:
            os.close(lock)

    def _refuse(self, data: dict[str, Any], day: str, estimate: float) -> None:
        spent_today = float((data.get("days") or {}).get(day, 0.0))
        spent = float(data.get("total_usd", 0.0))
        if spent_today + estimate > self.daily_usd:
            raise BudgetExhausted(
                f"the daily Meta cap (${self.daily_usd:.2f}) is reached: ${spent_today:.4f} spent today"
            )
        if spent + estimate > self.total_usd:
            raise BudgetExhausted(
                f"the total Meta cap (${self.total_usd:.2f}) is reached: ${spent:.4f} spent"
            )

    def check(self, estimate: float) -> None:
        """Raise BudgetExhausted when a call of this size could pass a cap (nothing is reserved)."""
        day = _today()
        self._update(lambda data: self._refuse(data, day, estimate))

    def reserve(self, estimate: float) -> str:
        """Count a call's largest possible cost before it is sent; returns the UTC day it counts on."""
        day = _today()

        def take(data: dict[str, Any]) -> None:
            self._refuse(data, day, estimate)
            _add(data, day, estimate)

        self._update(take)
        return day

    def settle(
        self, cost: float, *, reserved: float = 0.0, day: str | None = None
    ) -> dict[str, Any]:
        """Replace a reservation with the call's real cost (0 when nothing was billed)."""
        when = day or _today()

        def change(data: dict[str, Any]) -> None:
            _add(data, when, cost - reserved)
            if cost > 0:
                data["calls"] = int(data.get("calls", 0)) + 1

        return self._update(change)


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _add(data: dict[str, Any], day: str, amount: float) -> None:
    days = data.setdefault("days", {})
    days[day] = round(max(0.0, float(days.get(day, 0.0)) + amount), 6)
    data["total_usd"] = round(max(0.0, float(data.get("total_usd", 0.0)) + amount), 6)


class MetaModel:
    """A Muse model through the Meta API's chat completions, asking for a JSON object."""

    def __init__(
        self,
        settings: dict[str, Any],
        *,
        key_file: str | None = None,
        ledger: Ledger | None = None,
        timeout: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = str(settings.get("id") or "")
        refuse_contributor(self.model)
        self.display = str(settings.get("model_display") or self.model)
        self.base_url = str(settings.get("base_url") or "https://api.meta.ai/v1").rstrip("/")
        host = (urlsplit(self.base_url).hostname or "").lower()
        if urlsplit(self.base_url).scheme != "https" or host not in META_HOSTS:
            raise ValueError("the workers' model is reached only through the Meta API over https")
        given = dict(settings.get("prices_usd_per_million") or {})
        floor = MIN_RATES_USD_PER_MILLION.get(self.model)
        if floor is None:
            raise ValueError(f"{self.model} has no rates in code, so it is never called")
        if (
            not {"input", "output"} <= set(given)
            or min(float(given[k]) for k in ("input", "output")) <= 0
        ):
            raise ValueError("the catalog must give the model's positive input and output prices")
        # The catalog can only raise a rate above Meta's list rate, never lower it (review M1).
        self.prices = {k: max(float(given[k]), floor[k]) for k in ("input", "output")}
        if given.get("cached_input"):
            self.prices["cached_input"] = max(float(given["cached_input"]), 0.0)
        self.max_tokens = int(settings.get("max_tokens") or 1500)
        self.reasoning_effort = settings.get("reasoning_effort")
        self.key_file = key_file or os.environ.get(KEY_FILE_ENV, "")
        self.ledger = ledger
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport or httpx.HTTPTransport(retries=0),
            trust_env=False,  # no proxy, netrc or other setting from the environment
        )
        self._described = {
            "provider": "meta",
            "id": self.model,
            "model_display": self.display,
            "tier": "standard",
            "api": self.base_url,
            "invocation_origin": "worker_api",
            "prices_usd_per_million": self.prices,
            "reasoning_effort": self.reasoning_effort,
        }

    def close(self) -> None:
        self._http.close()

    def _key(self) -> str:
        try:
            text = Path(self.key_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise ModelUnavailable("the Meta key file is not readable on this machine") from exc
        key = key_from_text(text)
        if not key:
            raise ModelUnavailable("the Meta key file holds no key")
        return key

    def healthy(self) -> None:
        """Raise ModelUnavailable unless a call could be made now (a key, and room under the caps)."""
        self._key()
        if self.ledger is not None:
            self.ledger.check(self.estimate(4000))

    def describe(self) -> dict[str, Any]:
        return dict(self._described)

    def _settle(self, cost: float, reserved: float, day: str | None) -> None:
        if self.ledger is not None:
            self.ledger.settle(cost, reserved=reserved, day=day)

    def cost(self, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
        p = self.prices
        cached = min(cached_tokens, input_tokens)
        fresh = input_tokens - cached
        return round(
            (
                fresh * float(p["input"])
                + cached * float(p.get("cached_input") or p["input"])
                + output_tokens * float(p["output"])
            )
            / 1e6,
            6,
        )

    def estimate(self, prompt_chars: int, max_tokens: int | None = None) -> float:
        return self.cost(prompt_chars // 3 + 64, max_tokens or self.max_tokens)

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        meter: UsageMeter,
        max_tokens: int = 900,
        temperature: float = 0.0,
        seed: int | None = None,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        budget = max(int(max_tokens), self.max_tokens)  # reasoning models need room to answer
        effort = reasoning_effort or self.reasoning_effort
        key = self._key()
        estimate = self.estimate(len(system) + len(user), budget)
        day = self.ledger.reserve(estimate) if self.ledger is not None else None
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": budget,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if effort:
            body["reasoning_effort"] = effort
        if seed is not None:
            body["seed"] = seed
        started = time.time()
        try:
            response = self._http.post(
                "/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"}
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:  # never sent: nothing billed
            self._settle(0.0, estimate, day)
            raise ModelUnavailable(
                f"{self.model} could not be reached: {type(exc).__name__}"
            ) from exc
        except (
            httpx.HTTPError
        ) as exc:  # sent, no answer: Meta may have billed it, so it stays counted
            raise ModelUnavailable(
                f"{self.model} gave no answer: {type(exc).__name__}; its largest possible cost stays counted"
            ) from exc
        if response.status_code != 200:
            self._settle(0.0, estimate, day)
            raise ModelUnavailable(f"{self.model} answered {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise ModelUnavailable(f"{self.model} sent no JSON") from exc
        usage = data.get("usage") or {}
        cached = int(((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
        input_tokens, output_tokens = (
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
        )
        # An answer without token counts keeps its largest possible cost, so the caps stay safe.
        cost = self.cost(input_tokens, output_tokens, cached) if usage else estimate
        self._settle(cost, estimate, day)
        meter.add(
            self.describe(),
            ModelCall(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                seconds=round(time.time() - started, 3),
                temperature=temperature,
                seed=seed,
                cost_usd=cost,
                reasoning_effort=effort,
            ),
        )
        choice = (data.get("choices") or [{}])[0]
        content = str((choice.get("message") or {}).get("content") or "")
        if not content.strip() and choice.get("finish_reason") == "length":
            raise ModelUnavailable(
                f"{self.model} used all {budget} tokens before answering (finish_reason length)"
            )
        try:
            parsed = json.loads(content)
        except ValueError:
            return {"unparsed": content[:2000]}
        return parsed if isinstance(parsed, dict) else {"unparsed": content[:2000]}
