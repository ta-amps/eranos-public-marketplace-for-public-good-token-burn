"""The two-sided marketplace site: Worker routes, the request-a-kit form and the wording it shows."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "deploy" / "cloudflare" / "worker.js"
ISSUE_FORM = ROOT / ".github" / "ISSUE_TEMPLATE" / "request-a-kit.yml"
OLD_NAMES = re.compile(r"shamash|kinema|kothar", re.IGNORECASE)

# Simulates the Cloudflare asset binding: real files from web/public, and index.html for any other path,
# which is what `"not_found_handling": "single-page-application"` does for the deployed Worker.
WORKER_SCRIPT = r"""
import fs from "node:fs";
import path from "node:path";
import worker from WORKER;

const publicDir = PUBLIC_DIR;
const shell = fs.readFileSync(INDEX_HTML, "utf8");
const env = {
  ASSETS: {
    async fetch(req) {
      const url = new URL(typeof req === "string" ? req : req.url);
      const target = path.join(publicDir, url.pathname.replace(/^\//, ""));
      if (url.pathname !== "/" && fs.existsSync(target) && fs.statSync(target).isFile()) {
        const type = target.endsWith(".json") ? "application/json" : "image/svg+xml";
        return new Response(fs.readFileSync(target), { status: 200, headers: { "content-type": type } });
      }
      return new Response(shell, { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
    },
  },
};

const requests = REQUESTS;
const out = {};
for (const [name, method, pathname, body] of requests) {
  const init = { method };
  if (body !== null) {
    init.body = JSON.stringify(body);
    init.headers = { "content-type": "application/json" };
  }
  const response = await worker.fetch(new Request("https://eranos.ta-amps.workers.dev" + pathname, init), env);
  out[name] = {
    status: response.status,
    type: response.headers.get("content-type") || "",
    csp: response.headers.get("content-security-policy") || "",
    frame: response.headers.get("x-frame-options") || "",
    body: method === "HEAD" ? "" : await response.text(),
  };
}
console.log(JSON.stringify(out));
"""


def _worker(requests: list[tuple[str, str, str, Any]]) -> dict[str, dict[str, Any]]:
    script = (
        WORKER_SCRIPT.replace("WORKER", json.dumps(WORKER.as_uri()))
        .replace("PUBLIC_DIR", json.dumps((ROOT / "web" / "public").as_posix()))
        .replace("INDEX_HTML", json.dumps((ROOT / "web" / "index.html").as_posix()))
        .replace("REQUESTS", json.dumps(requests))
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True
    )
    result: dict[str, dict[str, Any]] = json.loads(run.stdout)
    return result


def test_marketplace_pages_load_directly_and_on_refresh() -> None:
    wrangler = (ROOT / "deploy" / "cloudflare" / "wrangler.jsonc").read_text(encoding="utf-8")
    assert '"not_found_handling": "single-page-application"' in wrangler
    assert '"run_worker_first": true' in wrangler
    out = _worker(
        [
            ("home", "GET", "/", None),
            ("help", "GET", "/help", None),
            ("help_slash", "GET", "/help/", None),
            ("nonprofits", "GET", "/nonprofits", None),
            ("nonprofits_query", "GET", "/nonprofits?from=home", None),
            ("help_head", "HEAD", "/help", None),
            ("help_post", "POST", "/help", {}),
        ]
    )
    for name in ("home", "help", "help_slash", "nonprofits", "nonprofits_query", "help_head"):
        page = out[name]
        assert page["status"] == 200, name
        assert page["type"].startswith("text/html"), name
        assert "script-src 'self'" in page["csp"], name
        assert page["frame"] == "DENY", name
    for name in ("home", "help", "nonprofits"):
        assert 'href="/help"' in out[name]["body"]
        assert 'href="/nonprofits"' in out[name]["body"]
    assert out["help_post"]["status"] == 405


def test_home_page_opens_on_the_two_doors_without_an_injected_banner() -> None:
    out = _worker([("home", "GET", "/", None), ("help", "GET", "/help", None)])
    for name in ("home", "help"):
        assert "data-agent-start" not in out[name]["body"], name
        assert "/agent-start.js" not in out[name]["body"], name


def test_connect_agent_mcp_and_api_routes_still_answer() -> None:
    out = _worker(
        [
            ("connect", "GET", "/connect", None),
            ("connect_json", "GET", "/connect.json", None),
            ("start_json", "GET", "/agent-start.json", None),
            ("start_js", "GET", "/agent-start.js", None),
            ("card", "GET", "/.well-known/agent-card.json", None),
            ("llms", "GET", "/llms.txt", None),
            ("health", "GET", "/api/health", None),
            ("catalog", "GET", "/api/catalog", None),
            ("examples", "GET", "/api/examples", None),
            ("missing_api", "GET", "/api/help", None),
            ("mcp", "POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
        ]
    )
    assert out["connect"]["status"] == 200 and "Connect to eranos" in out["connect"]["body"]
    assert json.loads(out["connect_json"]["body"])["surface_persistence"] is False
    start = json.loads(out["start_json"]["body"])
    assert start["version"] == "agent.onboarding.v1"
    assert start["activates_work"] is False
    assert "https://eranos.ta-amps.workers.dev/connect.json" in start["modes"]["any"]
    assert out["start_js"]["status"] == 200 and "javascript" in out["start_js"]["type"]
    card = json.loads(out["card"]["body"])
    assert "agent kits" in card["description"]
    assert not re.search(r"\btools?\b", card["description"])
    llms = out["llms"]["body"]
    assert "/help: I want to help." in llms
    assert "/nonprofits: I'm an NGO looking for agentic solutions." in llms
    assert json.loads(out["health"]["body"])["surface"] == "eranos"
    snapshot_kits = json.loads(
        (ROOT / "web" / "public" / "snapshot" / "catalog.json").read_text(encoding="utf-8")
    )["kits"]
    assert len(json.loads(out["catalog"]["body"])["kits"]) == len(snapshot_kits) >= 5
    shown = json.loads(
        (ROOT / "web" / "public" / "snapshot" / "examples.json").read_text(encoding="utf-8")
    )
    assert json.loads(out["examples"]["body"]) == shown
    assert shown["runs"]["count"] >= 5 and shown["needs"]
    assert out["missing_api"]["status"] == 404
    assert "json" in out["missing_api"]["type"]
    tools = json.loads(out["mcp"]["body"])["result"]["tools"]
    assert {t["name"] for t in tools} >= {"list_tracks", "search_catalog", "get_kit"}


def test_request_form_warns_first_and_asks_the_four_questions() -> None:
    text = ISSUE_FORM.read_text(encoding="utf-8")
    assert text.startswith("name: Tell us what you need\n")
    assert not re.search(r"request a (kit|verb)", text, re.IGNORECASE)
    warning = "Don't include anyone's personal information. Requests are public."
    assert warning in text.splitlines()[1], "the chooser description leads with the warning"
    body = text.split("\nbody:\n", 1)[1]
    first_item = ("\n" + body).split("\n  - type: ")[1]
    assert first_item.startswith("markdown") and f"## {warning}" in first_item
    fields = re.findall(
        r"^  - type: (\w+)\n    id: ([\w-]+)\n    attributes:\n      label: (.+)$", body, re.M
    )
    assert [(kind, label) for kind, _, label in fields] == [
        ("dropdown", "Organization type"),
        ("textarea", "The job to be done"),
        ("textarea", "Steps that must stay with a person"),
        ("textarea", "Constraints"),
        ("checkboxes", "Before you submit"),
    ]
    assert len({field_id for _, field_id, _ in fields}) == len(fields)
    assert "A volunteer will check your request before it becomes work." in text
    assert "Kits are reviewed, not certified." in text
    assert "required: true" in text
    assert not re.search(r"\btools?\b", text, re.IGNORECASE)
    assert not OLD_NAMES.search(text)


def test_data_the_site_shows_never_names_a_retired_pack() -> None:
    snapshot = ROOT / "web" / "snapshot"
    tracks = json.loads((snapshot / "tracks.json").read_text(encoding="utf-8"))["tracks"]
    shown: list[str] = []
    for track in tracks:
        shown += [track["title"], track["summary"], *track["never"]]
        shown += [org["mandate"] for org in track["organizations"]]
    for entry in json.loads((snapshot / "catalog.json").read_text(encoding="utf-8"))["kits"]:
        kit = entry["kit"]
        shown += [
            kit["title"],
            kit["summary"],
            kit["target_org"],
            entry["review_notes"],
            *kit["checklist"],
        ]
        shown += [f"{step['title']} {step['actor']} {step['guidance']}" for step in kit["steps"]]
        shown += [f"{fixture['scenario']} {fixture['sample_input']}" for fixture in kit["fixtures"]]
        shown += [source["title"] for source in kit["sources"]]
    assert [line for line in shown if OLD_NAMES.search(line)] == []
    for path in [ROOT / "web" / "index.html", *sorted((ROOT / "web" / "src").rglob("*.ts*"))]:
        assert not OLD_NAMES.search(path.read_text(encoding="utf-8")), path.name


def test_worker_serves_public_nouns_and_the_practice_digest() -> None:
    import hashlib

    from tessera.receipts import canonical_json

    bundle = json.loads(
        (ROOT / "examples" / "kits" / "05-volunteer-shift-sop-pack.json").read_text()
    )
    draft = bundle["draft"]
    out = _worker(
        [
            ("help", "GET", "/api/nouns/eranos.instructions/help", None),
            ("listing", "GET", "/api/nouns/eranos.instructions", None),
            ("private_store", "GET", "/api/nouns/eranos.steward_requests/x", None),
            ("catalog_store", "GET", "/api/nouns/eranos.catalog/KIT-SHIFT-05", None),
            ("missing", "GET", "/api/nouns/eranos.plans/rq-none", None),
            ("practice", "POST", "/api/practice", {"draft": draft}),
        ]
    )
    help_noun = json.loads(out["help"]["body"])
    assert out["help"]["status"] == 200 and help_noun["value"]["title"] == "Help in six steps"
    keys = [r["key"] for r in json.loads(out["listing"]["body"])["records"]]
    assert keys == ["classify", "help", "nonprofits", "public-research", "site"]
    for name in ("private_store", "catalog_store", "missing"):
        assert out[name]["status"] == 404, name
    practice = json.loads(out["practice"]["body"])
    expected = hashlib.sha256(canonical_json(draft).encode("utf-8")).hexdigest()
    assert practice["draft_sha256"] == expected
    assert "connect-src 'self' https://tessera.ta-amps.workers.dev" in out["help"]["csp"]


def test_static_page_and_readme_match_the_site_noun() -> None:
    """index.html shows the headline before the app loads the site noun; it must not drift from it."""
    site = json.loads((ROOT / "instructions" / "site.json").read_text(encoding="utf-8"))
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert f"<title>Eranos · {site['title']}</title>" in html
    assert f"<h1>{site['headline']}</h1>" in html
    assert f"<span>{site['brand_sub']}</span>" in html
    readme = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    assert readme[2] == f"{site['headline']} {site['subline']}"


def test_starting_brief_noun_is_the_canonical_brief() -> None:
    """The help noun's brief is the onboarding module's text for the home origin, which is also
    Agora's site/agent-brief.txt without its final newline."""
    script = (
        "import { buildAgentPrompt } from "
        + json.dumps((ROOT / "deploy" / "cloudflare" / "agent_start.js").as_uri())
        + "; console.log(JSON.stringify(buildAgentPrompt('https://home.ta-amps.workers.dev', 'any')));"
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True
    )
    noun = json.loads((ROOT / "instructions" / "help.json").read_text(encoding="utf-8"))
    assert noun["brief"] == json.loads(run.stdout)
    assert not re.search(r"\btools?\b", " ".join(s["title"] + s["detail"] for s in noun["steps"]))
