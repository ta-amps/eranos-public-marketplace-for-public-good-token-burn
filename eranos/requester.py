"""A nonprofit's side of the marketplace over plain HTTP, with no operator step.

Sign up for a requester key (Tessera's `/v1/session/requester`; the key is shown once and kept in
memory here), browse ready-made kits and examples of public research, say what the organization
needs in one plain request, follow it, and receive the delivered reports and published kits as
nouns in the organization's own namespace. The request is a noun and travels as one verb; the
worker that claims it decides which parts are public research and which become a kit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import httpx
from tessera.receipts import canonical_json

USER_AGENT = "eranos-requester/0.1"
SHARED = {"x-namespace": "main"}


class RequestRefused(RuntimeError):
    """Tessera or the check refused the request; the reason says why."""


@dataclass
class Requester:
    tessera_url: str
    eranos_url: str
    transport: httpx.BaseTransport | None = None
    principal: dict[str, Any] = field(default_factory=dict)
    _key: str = ""

    def __post_init__(self) -> None:
        self._fabric = httpx.Client(
            base_url=self.tessera_url.rstrip("/"),
            headers={"user-agent": USER_AGENT},
            timeout=30.0,
            transport=self.transport,
        )
        self._site = httpx.Client(
            base_url=self.eranos_url.rstrip("/"),
            headers={"user-agent": USER_AGENT},
            timeout=30.0,
            transport=self.transport,
        )

    def close(self) -> None:
        self._fabric.close()
        self._site.close()

    def call(
        self, method: str, path: str, *, shared: bool = False, **kwargs: Any
    ) -> httpx.Response:
        headers = {**kwargs.pop("headers", {}), **(SHARED if shared else {})}
        if self._key:
            headers["authorization"] = f"Bearer {self._key}"
        return self._fabric.request(method, path, headers=headers, **kwargs)

    def sign_up(self, profile: dict[str, Any]) -> dict[str, Any]:
        response = self._fabric.post("/v1/session/requester", json={"profile": profile})
        if response.status_code != 201:
            raise RequestRefused(f"sign-up refused: {response.status_code} {response.text[:200]}")
        body = dict(response.json())
        self._key = str(body.pop("key"))
        self.principal = body
        return body

    def browse(self) -> dict[str, Any]:
        """Ready-made kits (nouns) and requestable verbs (verb template nouns), from the surface."""
        kits = self._site.get("/api/catalog").json()["kits"]
        verbs = self._site.get("/api/nouns/eranos.verb_templates").json()["records"]
        return {
            "kits": [{"kit_id": k["kit"]["kit_id"], "title": k["kit"]["title"]} for k in kits],
            "verbs": [r["value"] for r in verbs],
        }

    def _file(self, brief: dict[str, Any]) -> dict[str, Any]:
        """Keep the request as a noun in our own namespace, then file it as a request verb."""
        digest = hashlib.sha256(canonical_json(brief).encode()).hexdigest()[:12]
        task_id = f"rq-{self.principal['principal_id']}-{digest}"
        noun = self.call(
            "POST",
            f"/v1/stores/org.requests/records/{task_id}",
            json={"value": {"schema_version": 1, **brief}, "expected_version": 0},
        )
        if noun.status_code != 200:
            raise RequestRefused(f"request noun refused: {noun.status_code} {noun.text[:200]}")
        filed = self.call(
            "POST",
            "/v1/tasks",
            shared=True,
            json={
                "queue": "eq01",
                "kind": "request",
                "effect_class": "write-internal",
                "task_id": task_id,
                "brief": {
                    **brief,
                    "request_ref": {
                        "namespace": self.principal["namespace"],
                        "store": "org.requests",
                        "key": task_id,
                        "version": noun.json()["version"],
                    },
                },
            },
        )
        if filed.status_code != 201:
            raise RequestRefused(f"request verb refused: {filed.status_code} {filed.text[:200]}")
        return {"task_id": task_id, "noun_version": noun.json()["version"]}

    def ask(self, text: str, links: list[str] | None = None) -> dict[str, Any]:
        """The one plain box: what the organization needs, with optional public links."""
        profile = self.principal.get("profile", {})
        return self._file(
            {
                "text": text,
                "links": list(links or []),
                "organization_type": str(profile.get("organization_type", "")),
            }
        )

    def follow(self, task_id: str) -> dict[str, Any]:
        """Our request verb's state and receipts, its plan in plain words and each part's state."""
        verb = self.call("GET", f"/v1/tasks/{task_id}", shared=True).json()
        results = self.call("GET", f"/v1/tasks/{task_id}/results", shared=True).json()["results"]
        plan = self._site.get(f"/api/nouns/eranos.plans/{task_id}")
        request = self._site.get(f"/api/nouns/eranos.requests/{task_id}")
        return {
            "verb_state": verb.get("state"),
            "receipts": [r["receipt_hash"] for r in results],
            "plan": plan.json()["value"] if plan.status_code == 200 else None,
            "request": request.json()["value"] if request.status_code == 200 else None,
        }

    def receive(self, task_id: str) -> list[dict[str, Any]]:
        """Copy every delivered report and published kit into our own namespace as nouns."""
        followed = self.follow(task_id)
        request = followed["request"] or {}
        received = []
        for number, part in sorted((request.get("parts") or {}).items()):
            if part.get("status") == "delivered":
                ref = part["solution"]
                found = self._site.get(f"/api/nouns/{ref['store']}/{ref['key']}")
                found.raise_for_status()
                key, value = ref["key"], {"kind": "report", **found.json()["value"]}
            elif part.get("status") == "published":
                found = self._site.get(f"/api/catalog/{part['kit_id']}")
                found.raise_for_status()
                kit = found.json()
                key = part["kit_id"]
                value = {
                    "kind": "kit",
                    "kit_id": key,
                    "nouns": {
                        name: kit["kit"].get(name)
                        for name in (
                            "steps",
                            "skills",
                            "tools",
                            "artifacts",
                            "checklist",
                            "fixtures",
                            "sources",
                        )
                    },
                    "review_receipt": kit.get("review_receipt"),
                    "publication_sha256": kit.get("publication_sha256"),
                }
            else:
                continue
            saved = self.call(
                "POST",
                f"/v1/stores/org.deliveries/records/{key}",
                json={
                    "value": {"request_id": task_id, "part": number, **value},
                    "expected_version": 0,
                },
            )
            if saved.status_code != 200:
                raise RequestRefused(
                    f"delivery noun refused: {saved.status_code} {saved.text[:200]}"
                )
            received.append({"store": "org.deliveries", "key": key, "part": number, **value})
        return received
