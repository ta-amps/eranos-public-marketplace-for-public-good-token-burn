"""End-to-end check of the two-sided marketplace, printed as a short transcript.

Local mode (`make e2e`) runs an in-process Tessera HTTP service and the local Eranos API, then drives
the whole flow with nouns and verbs only. Nonprofits sign up for narrow requester keys, browse, and
type what they need into one box; each request becomes exactly one verb on `eq01`. The classify
step, claimed by an authorized worker, refuses personal data, records a plan noun and splits the
verb: public-only parts become research for donated agents, parts that touch the nonprofit's files
become kits its own agent runs. Tracked anonymous sessions claim and submit the open verbs; the
results stay quarantined; a different keyed reviewer, and a person for a sensitive kit, reviews
them; reports are delivered and kits published; the nonprofit receives both as nouns in its own
namespace; every step leaves receipts. Abuse cases run along the way. No model is called.

Live mode (`make e2e-live`, opt-in) only reads the hosted sites and works a private demo verb in its
own anonymous session. It never claims or writes anything outside the demo queues.
"""

from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from tessera import Store, TaskSpec
from tessera.access import ServiceSettings
from tessera.client import Client
from tessera.service import create_app as create_tessera_app

from eranos import config
from eranos.contributor import OPEN_NAMESPACE, USER_AGENT, OpenSession, contribute_once
from eranos.donor_worker import synthesize_review_decision
from eranos.intake import parse_issue_form
from eranos.nouns import seed_nouns
from eranos.pipeline import run_review_step
from eranos.pipeline.requests import (
    OPEN_VERB_TAG,
    PersonalDataRefused,
    run_request_check,
    submit_request,
)
from eranos.pipeline.solutions import run_report_review
from eranos.queues import QUEUE_CONFIGS
from eranos.requester import Requester
from eranos.schemas import KitDraft, VerificationReport

ROOT = Path(__file__).resolve().parents[1]
REQUESTS = ROOT / "examples" / "requests"
Say = Callable[[str], None]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def _serve(app: Any, port: int, health: str) -> Iterator[str]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(url + health, timeout=2.0).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


@dataclass
class Fabric:
    """The local stack and the keyed workers' clients. Secrets never leave this object."""

    store: Store
    tessera_url: str
    eranos_url: str
    intake: Client
    checker: Client
    reviewer: Client
    steward: Client
    operator: Client
    reviewer_key_id: str
    steward_key_id: str


@contextmanager
def local_fabric() -> Iterator[Fabric]:
    """In-process Tessera (anonymous sessions on) and the local Eranos API reading it over HTTP."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(f"{tmp}/tessera.db")
        for cfg in QUEUE_CONFIGS:
            store.define_queue(
                cfg if cfg.name != "eq02" else cfg.model_copy(update={"max_attempts": 10})
            )
        eranos = ["store", "surface:eranos"]
        admin, _ = store.issue_key("operator", queues=["*"], scopes=["admin", "store"])
        intake, _ = store.issue_key(
            "eranos-intake", queues=["eq01"], kinds=["request"], scopes=eranos
        )
        # The classify worker claims request verbs and splits them into eq02/eq03 children.
        checker, _ = store.issue_key(
            "eranos-classifier", queues=["eq01", "eq02", "eq03"], kinds=["request"], scopes=eranos
        )
        # A reviewer reads the work it reviews (eq02) but can only claim review verbs (kinds).
        reviewer, rev = store.issue_key(
            "volunteer-reviewer",
            queues=["eq02", "eq03"],
            kinds=["review", "report_review"],
            scopes=eranos,
        )
        steward, stw = store.issue_key(
            "nonprofit-steward", queues=["eq03"], kinds=["signoff"], scopes=eranos
        )
        reader, _ = store.issue_key("eranos-site", queues=["eranos.read"], scopes=eranos)
        port = _free_port()
        settings = ServiceSettings(
            db_path=f"{tmp}/tessera.db",
            anonymous_access_enabled=True,
            requester_signup_enabled=True,
            reaper_seconds=3600,
            public_url=f"http://127.0.0.1:{port}",
        )
        with _serve(create_tessera_app(store, settings), port, "/v1/health") as tessera_url:
            saved = {k: os.environ.get(k) for k in ("ERANOS_BACKEND", "TESSERA_URL", "TESSERA_KEY")}
            os.environ.update(ERANOS_BACKEND="tessera", TESSERA_URL=tessera_url, TESSERA_KEY=reader)
            from eranos.api.app import app as eranos_app

            try:
                with _serve(eranos_app, _free_port(), "/healthz") as eranos_url:
                    clients = {
                        name: Client(tessera_url, key=secret, surface_id="eranos")
                        for name, secret in (
                            ("intake", intake),
                            ("checker", checker),
                            ("reviewer", reviewer),
                            ("steward", steward),
                            ("operator", admin),
                        )
                    }
                    try:
                        yield Fabric(
                            store=store,
                            tessera_url=tessera_url,
                            eranos_url=eranos_url,
                            reviewer_key_id=rev.key_id,
                            steward_key_id=stw.key_id,
                            **clients,
                        )
                    finally:
                        for client in clients.values():
                            client.close()
            finally:
                for name, value in saved.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value
        store.close()


def _short(value: str | None) -> str:
    return (value or "-")[:12]


ASKS = {
    "public": (
        "Summarize new state laws affecting tenants, with a citation for every point, so our"
        " clinic staff can update their plain-language handouts."
    ),
    "private": (
        "Compare this week's pantry shift sign-ups with our volunteer roster and draft a shift"
        " handoff checklist, role cards and a reminder list for the on-duty coordinator, with a"
        " clear escalation path for urgent safety questions."
    ),
    "mixed": (
        "Tell us which new state laws on tenant security deposits took effect this year, citing"
        " each one. Then help us compare our client intake notes with the referral rules so"
        " caseworkers can draft warm-referral summaries and decide eligibility themselves."
    ),
}


def review_kit(fabric: Fabric, task_id: str) -> dict[str, Any] | None:
    """The keyed reviewer's verb: re-verify the build and decide (deterministic stand-in)."""
    view = fabric.reviewer.task(task_id)
    draft_out = fabric.reviewer.results(view.depends_on[0])[-1].output
    decision = synthesize_review_decision(
        KitDraft.model_validate(draft_out["draft"]),
        VerificationReport.model_validate(draft_out["verification"]),
        worker="volunteer-reviewer",
        key_id=fabric.reviewer_key_id,
    )
    return run_review_step(
        fabric.reviewer, decision, worker="volunteer-reviewer", key_id=fabric.reviewer_key_id
    )


def _publish_examples(store: Store) -> int:
    """The five synthetic example kits pass the existing pipeline, so there is a catalog to browse."""
    from eranos.cli import _run_all_examples

    return len(_run_all_examples(store))


def _work(fabric: Fabric, plan: list[dict[str, Any]], label: str, say: Say) -> list[dict[str, Any]]:
    """Tracked anonymous sessions claim and submit every open work verb of one plan."""
    done = []
    for entry in plan:
        if entry["route"] == "held":
            continue
        kind = "research" if entry["route"] == "public-only" else "build"
        result = contribute_once(
            fabric.tessera_url,
            label=f"volunteer-{label}-{entry['part']}",
            kinds=[kind],
            practice_url=fabric.eranos_url + "/api/practice",
        )
        done.append(result)
        say(
            f"     part {entry['part']}: anonymous {_short(result['principal_id'])} did the {kind},"
        )
        say(
            f"       receipt {_short(result['receipt']['receipt_hash'])} ({result['receipt']['labels']['origin']}, untrusted)"
        )
    return done


def _review(fabric: Fabric, entry: dict[str, Any], say: Say) -> dict[str, Any]:
    """A different keyed worker reviews one part; a sensitive kit also waits for a person."""
    if entry["route"] == "public-only":
        outcome = run_report_review(
            fabric.reviewer, worker="volunteer-reviewer", key_id=fabric.reviewer_key_id
        )
    else:
        outcome = review_kit(fabric, entry["review_task_id"])
    if outcome is None:
        raise RuntimeError(f"no review verb was ready for part {entry['part']}")
    if outcome["status"] != "published":
        raise RuntimeError(f"part {entry['part']} did not publish: {outcome}")
    say(f"     part {entry['part']}: a different keyed reviewer -> {outcome['status']}")
    return outcome


def run_local(say: Say = print) -> dict[str, Any]:
    """The whole two-sided flow on a local stack; returns what it observed for the tests."""
    seen: dict[str, Any] = {"asks": {}, "abuse": {}}
    with local_fabric() as fabric:
        api = httpx.Client(base_url=fabric.eranos_url, headers={"user-agent": USER_AGENT})
        seeded = seed_nouns(fabric.intake)
        examples = _publish_examples(fabric.store)
        seen["examples"] = examples
        help_noun = api.get("/api/nouns/eranos.instructions/help").json()["value"]
        say(
            f"[01] stack: Tessera + Eranos API; {len(seeded)} nouns seeded (page text, starting brief,"
        )
        say(
            f"     classify rules, research rules, sources); {examples} example kits in the catalog;"
        )
        say(f"     /help renders {len(help_noun['steps'])} steps from Tessera")

        ngo = Requester(fabric.tessera_url, fabric.eranos_url)
        other = Requester(fabric.tessera_url, fabric.eranos_url)
        me = ngo.sign_up(
            {
                "display_name": "Synthetic Tenant Help Desk",
                "organization_type": "Legal-aid or rights clinic",
                "causes": ["housing", "tenant rights"],
            }
        )
        other.sign_up(
            {
                "display_name": "Synthetic Food Bank",
                "organization_type": "Food pantry",
                "causes": [],
            }
        )
        profile = ngo.call("GET", "/v1/stores/org.profile/records/profile").json()
        seen["signup"] = {
            "namespace": me["namespace"],
            "scopes": me["scopes"],
            "queues": me["queues"],
        }
        say("[02] sign-up: two nonprofits got requester keys (shown once, stored hashed); NGO A")
        say(
            f"     works in {me['namespace'][:20]}..., profile noun '{profile['value']['display_name']}'"
        )
        say(f"     ({profile['visibility_scope']})")

        browsed = ngo.browse()
        seen["browse"] = browsed
        say(
            f"[03] browse: {len(browsed['kits'])} ready-made kits and {len(browsed['verbs'])} examples of public"
        )
        say("     research, all rendered from nouns")

        before = fabric.operator.counts()["eq01"].ready
        for name, text in ASKS.items():
            filed = ngo.ask(text)
            seen["asks"][name] = {"task_id": filed["task_id"]}
        seen["one_verb_each"] = fabric.operator.counts()["eq01"].ready - before
        pii = ngo.call(
            "POST",
            "/v1/tasks",
            shared=True,
            json={
                "queue": "eq01",
                "kind": "request",
                "effect_class": "write-internal",
                "brief": {"text": "Call our client at 555-201-3344 or card 4111 1111 1111 1111"},
            },
        )
        seen["abuse"]["personal_data_request_verb"] = pii.status_code
        try:
            refused = parse_issue_form((REQUESTS / "personal-data.md").read_text())
            submit_request(fabric.intake, refused, source={"kind": "file"})
            raise RuntimeError("a request with personal data was stored")
        except PersonalDataRefused as exc:
            seen["abuse"]["personal_data_request"] = exc.findings
        hotline = submit_request(
            fabric.intake,
            parse_issue_form((REQUESTS / "hotline-routing.md").read_text()),
            source={"kind": "file"},
        )
        seen["asks"]["form"] = {"task_id": hotline.request_id}
        say(
            f"[04] NGO A typed three needs into the one box: {seen['one_verb_each']} request verbs on eq01,"
        )
        say(
            f"     one each; its text with a phone and card number was refused by Tessera ({pii.status_code});"
        )
        say(
            "     the public form brought a hotline request; a form with contact details was refused"
        )
        say(f"     before storage ({'; '.join(seen['abuse']['personal_data_request'])})")

        for name, info in seen["asks"].items():
            checked = run_request_check(fabric.checker, worker="eranos-classifier")
            if checked is None or checked["request_id"] != info["task_id"]:
                raise RuntimeError(f"the classify step did not answer {name}: {checked}")
            info["plan"] = checked["plan"]
            plain = api.get(f"/api/nouns/eranos.plans/{info['task_id']}").json()["value"]["plain"]
            info["plain"] = plain
            routes = ", ".join(f"part {p['part']} {p['route']}" for p in checked["plan"])
            say(f"[05] classify + split ({name}): {routes}")
            for line in plain:
                say(f"     '{line[:96]}'")

        say("[06] donated agents work the open verbs (tracked anonymous sessions):")
        for name, info in seen["asks"].items():
            info["work"] = _work(fabric, info["plan"], name, say)

        private = next(p for p in seen["asks"]["private"]["plan"] if p["route"] == "private-files")
        catalog = api.get("/api/catalog").json()["kits"]
        stranger = httpx.get(
            f"{fabric.tessera_url}/ns/main/v1/tasks/{private['work_task_id']}/results"
        )
        peek_session = OpenSession(fabric.tessera_url, label="other-volunteer")
        peek_session.open()
        peek = peek_session.get(f"/v1/tasks/{private['work_task_id']}/results").status_code
        mine = ngo.call(
            "GET", f"/v1/tasks/{private['work_task_id']}/results", shared=True
        ).status_code
        verb = fabric.operator.task(private["work_task_id"])
        seen["quarantine"] = {
            "in_catalog": any(k["kit"]["kit_id"] == private["kit_id"] for k in catalog),
            "public_read": api.get(f"/api/catalog/{private['kit_id']}").status_code,
            "stranger": stranger.status_code,
            "other_session": peek,
            "requester_child": mine,
            "other_ngo_request": other.call(
                "GET", f"/v1/tasks/{seen['asks']['private']['task_id']}", shared=True
            ).status_code,
            "other_ngo_namespace": other.call(
                "GET",
                "/v1/stores/org.requests/records/x",
                headers={"x-namespace": me["namespace"]},
            ).status_code,
            "verb_visibility": verb.visibility_scope,
            "completed_by": fabric.operator.results(private["work_task_id"])[-1].completed_by_key,
        }
        q = seen["quarantine"]
        say(
            f"[07] quarantine: {private['kit_id']} in catalog={q['in_catalog']}, public read {q['public_read']},"
        )
        say(f"     stranger {q['stranger']}, another session {q['other_session']}, the NGO itself")
        say(
            f"     {q['requester_child']} until review; NGO B on NGO A's request {q['other_ngo_request']}"
        )
        say(f"     and namespace {q['other_ngo_namespace']}")

        abuser = OpenSession(fabric.tessera_url, label="volunteer-private-2")
        abuser.open()
        seen["abuse"]["anonymous_publish"] = abuser._call(
            "POST",
            f"/v1/stores/eranos.catalog/records/{private['kit_id']}",
            json={"value": {"kit": "self-published"}, "expected_version": 0},
            headers={"x-namespace": "main"},
        ).status_code
        seen["abuse"]["anonymous_review_claim"] = abuser.claim(queue="eq03").status_code
        seen["abuse"]["requester_claim"] = ngo.call(
            "POST", "/v1/tasks/claim", shared=True, json={"queue": "eq03", "worker": "ngo"}
        ).status_code
        # Open-claim limits count granted leases, never empty polls: claims are granted until the
        # session's or this address's hourly allowance is spent (earlier volunteers here share the
        # address), while the empty polls between them cost nothing.
        for i in range(6):
            fabric.store.enqueue(
                TaskSpec(
                    queue="eq02",
                    task_id=f"cap-check-{i}",
                    kind="cap_check",
                    effect_class="write-internal",
                    brief={"title": "SYNTHETIC claim-cap check"},
                    tags=[OPEN_VERB_TAG, "status:quarantined"],
                    producer_surface="surface:eranos",
                    visibility_scope="surface_only",
                )
            )
        granted, polls = 0, []
        for _ in range(6):
            polls.append(abuser.claim(kinds=["nothing_waiting"]).status_code)
            claimed = abuser.claim(kinds=["cap_check"])
            if claimed.status_code != 200:
                break
            granted += 1
            ref = {
                "task_id": claimed.json()["task_id"],
                "fencing_token": claimed.json()["fencing_token"],
            }
            abuser._call(
                "POST",
                "/v1/tasks/submit",
                json={**ref, "output": {"node": "cap_check", "note": "SYNTHETIC"}},
                headers={
                    **OPEN_NAMESPACE,
                    "idempotency-key": f"{ref['task_id']}:{ref['fencing_token']}",
                },
            ).raise_for_status()
        seen["abuse"]["anonymous_quota"] = claimed.status_code
        seen["abuse"]["open_claims_before_cap"] = granted
        # The poll before each granted claim was made with allowance left; once it is spent, any
        # claim, empty or not, is refused.
        seen["abuse"]["polls_before_granted"] = polls[:granted]
        for i in range(granted, 6):
            fabric.store.cancel(f"cap-check-{i}", "claim-cap check done")
        codes = [
            other.ask(f"Summarize public budget documents for program {i}.")["task_id"] and 201
            for i in range(5)
        ]
        sixth = other.call(
            "POST",
            "/v1/tasks",
            shared=True,
            json={
                "queue": "eq01",
                "kind": "request",
                "effect_class": "write-internal",
                "brief": {"text": "Summarize public budget documents for program six."},
            },
        )
        seen["abuse"]["requester_quota"] = [*codes, sixth.status_code]
        a = seen["abuse"]
        say(f"[08] abuse: anonymous publish {a['anonymous_publish']}, anonymous review claim")
        say(
            f"     {a['anonymous_review_claim']}, NGO claim {a['requester_claim']}, open claim after"
            f" {a['open_claims_before_cap']} granted this hour {a['anonymous_quota']}"
        )
        say(
            f"     (the empty poll before each granted claim answered"
            f" {sorted(set(a['polls_before_granted']))} and cost nothing),"
            f" NGO B's 6th request in an hour {sixth.status_code}"
        )
        abuser.close()
        peek_session.close()

        say("[09] reviews by a different keyed worker:")
        for name in ("public", "private", "mixed", "form"):
            for entry in seen["asks"][name]["plan"]:
                if entry["route"] != "held":
                    entry["review"] = _review(fabric, entry, say)
        for _ in seen["asks"]:
            closed = run_request_check(fabric.checker, worker="eranos-classifier")
            if closed is None or closed["status"] != "closed":
                raise RuntimeError(f"a request did not close: {closed}")

        received: dict[str, Any] = {}
        for name in ("public", "private", "mixed"):
            task_id = seen["asks"][name]["task_id"]
            received[name] = {"followed": ngo.follow(task_id), "nouns": ngo.receive(task_id)}
        seen["received"] = received
        kept = ngo.call("GET", "/v1/stores/org.deliveries/records").json()["records"]
        say("[10] NGO A follows its requests and receives the results as nouns in its namespace:")
        for name, got in received.items():
            states = {
                k: v["status"]
                for k, v in (got["followed"]["request"] or {}).get("parts", {}).items()
            }
            kinds = [f"{n['kind']} {n['key']}" for n in got["nouns"]]
            say(
                f"     {name}: request {got['followed']['request']['status']}, parts {states}; got {kinds}"
            )
        report = next(n for n in received["public"]["nouns"] if n["kind"] == "report")
        say(
            f"     a report has {len(report['report']['claims'])} cited claims and says '{report['report']['disclaimer']}'"
        )
        say(f"     -> org.deliveries holds {len(kept)} nouns")

        say("[11] receipts (who did what):")
        for name, info in seen["asks"].items():
            closing = fabric.operator.results(info["task_id"])[-1]
            say(
                f"     {name}: request ...{info['task_id'][-12:]}, closed with receipt {_short(closing.receipt_hash)}"
            )
            for entry in info["plan"]:
                if entry["route"] == "held":
                    continue
                work = fabric.operator.results(entry["work_task_id"])[-1]
                review = fabric.operator.results(entry["review_task_id"])[-1]
                say(
                    f"       part {entry['part']}: work by {_short(work.completed_by_key)} ({work.labels.get('origin')}),"
                )
                say(
                    f"         review {_short(review.receipt_hash)} by {_short(review.completed_by_key)}"
                )
        seen["catalog_size"] = len(api.get("/api/catalog").json()["kits"])
        seen["reviewer_key_id"] = fabric.reviewer_key_id
        api.close()
        ngo.close()
        other.close()
    say(
        "[12] done: nonprofits typed what they need; classify + split routed public parts to donated"
    )
    say(
        "     research and private parts to kits; different workers reviewed; results came back as nouns"
    )
    return seen


def run_live(say: Say = print) -> dict[str, Any]:
    """Read the hosted sites, then work one private demo verb; nothing outside the demo queues."""
    tessera = config.public_tessera_url().rstrip("/")
    eranos = config.surface_public_url().rstrip("/")
    seen: dict[str, Any] = {}
    with httpx.Client(headers={"user-agent": USER_AGENT}, timeout=30.0) as http:
        health = http.get(f"{tessera}/v1/health")
        contract = http.get(f"{tessera}/connect.json").json()
        open_rule = (contract.get("anonymous") or {}).get("open_verbs")
        seen["open_verbs_deployed"] = open_rule is not None
        say(
            f"[L1] {tessera} health {health.status_code}; open-verb rule deployed: {open_rule is not None}"
        )
        catalog = http.get(f"{eranos}/api/catalog")
        helped = http.get(f"{eranos}/api/nouns/eranos.instructions/help")
        seen["catalog_kits"] = len(catalog.json().get("kits", [])) if catalog.is_success else None
        seen["help_noun"] = helped.status_code
        say(
            f"[L2] {eranos} catalog {catalog.status_code} ({seen['catalog_kits']} kits); help noun {helped.status_code}"
        )
    session = OpenSession(tessera, label="eranos-live-smoke")
    try:
        minted = session.open()
        say(
            f"[L3] anonymous session {_short(minted['principal_id'])} in {minted['namespace'][:18]}..."
        )
        lease = session._call(
            "POST", "/v1/tasks/claim", json={"queue": "demo.ping", "worker": "eranos-live-smoke"}
        )
        lease.raise_for_status()
        ref = {"task_id": lease.json()["task_id"], "fencing_token": lease.json()["fencing_token"]}
        session._call("POST", "/v1/tasks/heartbeat", json=ref).raise_for_status()
        saved = session._call(
            "POST",
            "/v1/stores/demo.artifacts/records/eranos-live-smoke",
            json={
                "value": {"synthetic": True, "message": "SYNTHETIC smoke"},
                "expected_version": 0,
            },
        )
        receipt = session._call(
            "POST",
            "/v1/tasks/submit",
            json={**ref, "output": {"record": "eranos-live-smoke", "version": 1}},
            headers={"idempotency-key": f"{ref['task_id']}:{ref['fencing_token']}"},
        )
        receipt.raise_for_status()
        seen["demo_receipt"] = receipt.json()["receipt_hash"]
        say(f"[L4] demo.ping claimed, heartbeat, record {saved.status_code}, submitted: receipt")
        say(f"     {_short(seen['demo_receipt'])} labels {receipt.json()['labels']}")
        if open_rule is not None:
            verbs = session.open_verbs()
            seen["open_verbs"] = len(verbs)
            say(
                f"[L5] {len(verbs)} open verbs listed in the shared namespace (read only, none claimed)"
            )
        audit = session.get("/v1/me/audit", shared=False).json()["events"]
        say(f"[L6] own audit: {sorted({e['action'] for e in audit})}")
    finally:
        session.close()
    return seen
