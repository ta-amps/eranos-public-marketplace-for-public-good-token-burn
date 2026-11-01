"""A local Tessera on workerd for the worker-loop tests, with locally generated keys only.

Set ERANOS_WORKERD_TESSERA to a Tessera checkout that has its node_modules (esbuild, miniflare);
the tests are skipped without it. Every key here is minted by this local instance and dies with it.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from tessera import QueueConfig
from tessera.client import Client

from eranos.model_client import ModelCall, UsageMeter
from eranos.nouns import seed_nouns
from eranos.queues import QUEUE_CONFIGS
from eranos.sources import Fetched
from eranos.worker_keys import issue_key
from eranos.worker_loop import Worker, WorkerClient, WorkerConfig

HERE = Path(__file__).resolve().parent
CHECKOUT_ENV = "ERANOS_WORKERD_TESSERA"


def available() -> bool:
    checkout = os.environ.get(CHECKOUT_ENV)
    return bool(
        checkout
        and (Path(checkout) / "node_modules" / "miniflare").is_dir()
        and shutil.which("node")
    )


@dataclass
class LocalTessera:
    url: str
    admin: str = field(repr=False)
    keys: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    trace_dir: Path = Path(".")
    _requesters: list[list[Any]] = field(default_factory=list, repr=False)

    def requester(self) -> tuple[str, str]:
        """A requester key with request verbs left this hour (5 per key; 3 sign-ups per address)."""
        for entry in self._requesters:
            if entry[1] < 5:
                entry[1] += 1
                return entry[0]
        self._requesters.append([self.sign_up(f"Requester {len(self._requesters) + 1}"), 1])
        return self._requesters[-1][0]

    def http(self) -> httpx.Client:
        return httpx.Client(base_url=self.url, timeout=30.0)

    def admin_client(self) -> Client:
        return Client(self.url, key=self.admin, surface_id="eranos", namespace="main")

    def client(self, name: str) -> WorkerClient:
        return WorkerClient(
            self.url,
            key=self.keys[name]["key"],
            surface_id="eranos",
            namespace="main",
            max_retries=0,
        )

    def worker(self, name: str, role: str | None = None, **kwargs: Any) -> Worker:
        issued = self.keys[name]
        dedicated, number = bool(kwargs.pop("dedicated", False)), kwargs.pop("number", None)
        config = WorkerConfig(
            role=role or issued["role"],
            label=f"test-{name}",
            tessera_url=self.url,
            key=issued["key"],
            key_id=issued["key_id"],
            trace_path=str(self.trace_dir / f"worker-{name}.jsonl"),
            min_empty_seconds=float(kwargs.pop("min_empty_seconds", 0.0)),
            dedicated=dedicated,
            display_name=f"dedicated worker {number} (run by ta-amps)" if dedicated else "",
            our_key_ids=tuple(k["key_id"] for k in self.keys.values()),
        )
        return Worker(config, **kwargs)

    def sign_up(self, name: str) -> tuple[str, str]:
        with self.http() as http:
            response = http.post(
                "/v1/session/requester",
                json={
                    "profile": {
                        "display_name": f"Made-up sample {name}",
                        "organization_type": "Food pantry",
                        "causes": ["food security"],
                    }
                },
            )
        assert response.status_code == 201, response.text[:300]
        body = response.json()
        return str(body["key"]), str(body["principal_id"])

    def file_request(self, requester: tuple[str, str], brief: dict[str, Any], suffix: str) -> str:
        """The request box's two calls: the request noun in the org's namespace, then one eq01 verb."""
        key, principal = requester
        task_id = f"rq-{principal}-{suffix}"
        headers = {"authorization": f"Bearer {key}"}
        with self.http() as http:
            noun = http.post(
                f"/v1/stores/org.requests/records/{task_id}",
                json={"value": {"schema_version": 1, **brief}, "expected_version": 0},
                headers=headers,
            )
            assert noun.status_code == 200, noun.text[:300]
            verb = http.post(
                "/v1/tasks",
                json={
                    "queue": "eq01",
                    "kind": "request",
                    "effect_class": "write-internal",
                    "task_id": task_id,
                    "brief": brief,
                },
                headers={**headers, "x-namespace": "main"},
            )
            assert verb.status_code == 201, verb.text[:300]
        return task_id

    def reap(self) -> None:
        with self.http() as http:
            http.post(
                "/v1/admin/reap",
                headers={"authorization": f"Bearer {self.admin}", "x-namespace": "main"},
            ).raise_for_status()

    def get(self, path: str) -> Any:
        with self.http() as http:
            response = http.get(
                path, headers={"authorization": f"Bearer {self.admin}", "x-namespace": "main"}
            )
            response.raise_for_status()
            return response.json()


@contextmanager
def local_tessera(
    trace_dir: Path, *, worker_noun: dict[str, Any] | None = None
) -> Iterator[LocalTessera]:
    checkout = os.environ[CHECKOUT_ENV]
    boot = secrets.token_hex(32)
    log = (trace_dir / "workerd.log").open("w+")
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG")}
    env.update(TESSERA_CHECKOUT=checkout, TESSERA_TEST_BOOTSTRAP=boot)
    proc = subprocess.Popen(
        ["nice", "-n", "10", "node", str(HERE / "local_tessera.mjs")],
        env=env,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
    try:
        url = None
        for _ in range(600):
            if proc.poll() is not None:
                raise RuntimeError(
                    "local workerd exited during startup: "
                    + (trace_dir / "workerd.log").read_text()[-500:]
                )
            for line in (trace_dir / "workerd.log").read_text().splitlines():
                if line.startswith("{") and json.loads(line).get("ready"):
                    url = str(json.loads(line)["url"]).rstrip("/")
            if url:
                break
            time.sleep(0.1)
        assert url, "local workerd did not become ready"
        with httpx.Client(base_url=url, timeout=30.0) as http:
            minted = http.post(
                "/v1/admin/keys",
                json={
                    "label": "local-operator",
                    "queues": ["*"],
                    "scopes": ["admin", "store"],
                    "effect_classes": ["read", "write-internal"],
                    "days": 1,
                },
                headers={"x-bootstrap-secret": boot},
            )
            assert minted.status_code == 201, minted.text[:300]
            fabric = LocalTessera(url=url, admin=str(minted.json()["key"]), trace_dir=trace_dir)
            admin = fabric.admin_client()
            for cfg in QUEUE_CONFIGS:  # the production queues, with short retry backoff for tests
                admin.define_queue(
                    QueueConfig(
                        **{
                            **cfg.model_dump(),
                            "backoff_base_seconds": 0.2,
                            "backoff_cap_seconds": 1.0,
                        }
                    )
                )
            seed_nouns(admin)
            if worker_noun is not None:
                current = admin.get_record("eranos.instructions", "worker")
                admin.put_record(
                    "eranos.instructions",
                    "worker",
                    worker_noun,
                    expected_version=current.version,
                    producer_surface="surface:eranos",
                    visibility_scope="public_commons",
                    tags=["kind:instructions", "status:verified"],
                )
            admin.close()
            for name in ("planner", "builder", "reviewer", "reviewer2"):
                fabric.keys[name] = issue_key(http, fabric.admin, name, days=1)
        yield fabric
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
        log.close()


# Test fixtures (SYNTHETIC, made up for these tests): a public-rules page and a stand-in model --------------------------------------
RULES_URL = "https://rules.example.org/made-up/charity-political-activity"
# The page's visible test mark is its heading, which is never quoted; the title and every sentence
# use plain words, because nothing the workers publish may say "synthetic" (owner's rule).
RULES_HTML = """<!doctype html><html><head><title>Made-up rules page, a test we wrote: charities and political campaigns</title>
<script>var tracking = "never extracted";</script></head><body><nav>Home | Rules</nav>
<h1>SYNTHETIC rules page used only in tests</h1>
<p>Under these made-up rules, a charity registered under section 501(c)(3) may not take part in any political campaign for or against a candidate for public office.</p>
<p>A charity may hold nonpartisan voter registration drives when the drives do not favor any candidate or party.</p>
<p>Contributions to a political campaign fund from a charity's own money are not allowed under these made-up rules.</p>
<p>A charity may publish candidate questionnaires only when every candidate is asked the same questions in a neutral way.</p>
<p>Violating the campaign rule can cost a charity its tax-exempt status under these made-up rules.</p>
</body></html>"""


def fixture_fetcher(pages: dict[str, str]) -> Any:
    def fetch(url: str) -> Fetched:
        if url not in pages:
            raise RuntimeError(f"{url.split('/')[2]} is not a test fixture")
        return Fetched(url, url, 200, "text/html; charset=utf-8", pages[url].encode(), time.time())

    return fetch


class FakeModel:
    """Stands in for the local model: claims from the first numbered sentences, plus one bad quote."""

    def __init__(self, bad: bool = True) -> None:
        self.bad = bad
        self.calls = 0

    def describe(self) -> dict[str, Any]:
        return {
            "provider": "test",
            "id": "fake-llama-for-tests",
            "digest": "0" * 64,
            "adapter": None,
            "invocation_origin": "worker_local",
        }

    def healthy(self) -> None:
        return None

    def chat_json(
        self, system: str, user: str, *, meter: UsageMeter, max_tokens: int = 900
    ) -> dict[str, Any]:
        self.calls += 1
        meter.add(
            self.describe(), ModelCall(input_tokens=len(user) // 4, output_tokens=150, seconds=0.01)
        )
        claims = []
        for line in user.splitlines():
            if line.startswith("[S"):
                sid, rest = line[1:].split("] ", 1)
                sentence = rest.split(") ", 1)[1]
                claims.append({"sentence": sid, "quote": sentence, "claim": sentence})
        if self.bad:
            claims.append(
                {
                    "sentence": claims[0]["sentence"] if claims else "S1-1",
                    "quote": "A sentence that the source never said at all.",
                    "claim": "Invented.",
                }
            )
        return {"claims": claims[:5] + claims[-1:] if self.bad else claims[:5]}
