"""The two-sided marketplace site: Worker routes, the request-a-kit form and the wording it shows."""

from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

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
const extra = EXTRA_ENV;
const env = {
  ...extra,
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
  const response = await worker.fetch(new Request("https://eranosforgood.org" + pathname, init), env);
  const bytes = method === "HEAD" ? new Uint8Array() : new Uint8Array(await response.arrayBuffer());
  const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map((b) => b.toString(16).padStart(2, "0")).join("");
  const binary = (response.headers.get("content-type") || "").includes("gzip");
  out[name] = {
    sha256: digest,
    xsha: response.headers.get("x-content-sha256") || "",
    disposition: response.headers.get("content-disposition") || "",
    status: response.status,
    type: response.headers.get("content-type") || "",
    csp: response.headers.get("content-security-policy") || "",
    frame: response.headers.get("x-frame-options") || "",
    allow: response.headers.get("allow") || "",
    cache: response.headers.get("cache-control") || "",
    cors: response.headers.get("access-control-allow-origin") || "",
    body: binary ? "" : new TextDecoder().decode(bytes),
  };
}
console.log(JSON.stringify(out));
"""


# What machines read and write on the workers.dev alias: published agent pointers, MCP clients, service bindings and
# older CLIs use these, so they answer in place instead of redirecting (alias audit, Nov 2).
ALIAS_MACHINE_PATHS = [
    "/api/health",
    "/api/catalog",
    "/api/tracks",
    "/connect.json",
    "/llms.txt",
    "/llms-full.txt",
    "/agent.md",
    "/.well-known/agent-card.json",
    "/.well-known/agent.json",
    "/.well-known/security.txt",
    "/healthz",
    "/robots.txt",
]


def _worker(
    requests: list[tuple[str, str, str, Any]], extra_env: str = "({})"
) -> dict[str, dict[str, Any]]:
    script = (
        WORKER_SCRIPT.replace("EXTRA_ENV", extra_env)
        .replace("WORKER", json.dumps(WORKER.as_uri()))
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
    # Pages, /api and the agent files run the Worker; the build's static files never do (Free plan request budget).
    routing = re.search(r'"run_worker_first": (\[[^\]]*\])', wrangler)
    assert routing
    patterns = json.loads(routing.group(1))
    assert patterns[0] == "/*"
    assert {"!/assets/*", "!/fonts/*", "!/snapshot/*", "!/agent-banner.js"} <= set(patterns)
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
    assert (
        out["connect"]["status"] == 200
        and "<title>Connect to Eranos</title>" in out["connect"]["body"]
    )
    assert json.loads(out["connect_json"]["body"])["surface_persistence"] is False
    start = json.loads(out["start_json"]["body"])
    assert start["version"] == "agent.onboarding.v1"
    assert start["activates_work"] is False
    assert "https://eranosforgood.org/connect.json" in start["modes"]["any"]
    assert out["start_js"]["status"] == 200 and "javascript" in out["start_js"]["type"]
    card = json.loads(out["card"]["body"])
    assert "agent kits" in card["description"]
    assert not re.search(r"\btools?\b", card["description"])
    llms = out["llms"]["body"]
    # The banner tells every agent to read /llms.txt and follow it: it comes from the eranos.instructions/llms noun.
    noun = json.loads((ROOT / "instructions" / "llms.json").read_text())
    assert noun["text"].strip().splitlines()[0] in llms
    for line in (
        "Ask for help for a nonprofit, without private information",
        "Pick up open Tasks as a volunteer",
        "The worker that makes something never checks it",
        "/connect.json",
    ):
        assert line in llms, line
    assert "github.com" not in llms
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
    assert "A worker will check your request before it becomes work." in text
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


def test_the_worker_code_never_names_a_retired_surface() -> None:
    """Hunt, October 30: access.js still branched on an archived surface's name (MUST-FOLLOW item 9).

    The gitignored word-list module is skipped: it is the shared list itself, built outside the repo's files.
    """
    named = [
        path.name
        for path in sorted((ROOT / "deploy" / "cloudflare").glob("*.js"))
        if path.name != "banned_words.generated.js"
        and OLD_NAMES.search(path.read_text(encoding="utf-8"))
    ]
    assert named == []


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
    assert keys == sorted(p.stem for p in (ROOT / "instructions").glob("*.json"))
    assert {
        "shell",
        "home",
        "nonprofits-page",
        "request-status",
        "help-page",
        "library",
        "agent-banner",
    } <= set(keys)
    for name in ("private_store", "catalog_store", "missing"):
        assert out[name]["status"] == 404, name
    practice = json.loads(out["practice"]["body"])
    expected = hashlib.sha256(canonical_json(draft).encode("utf-8")).hexdigest()
    assert practice["draft_sha256"] == expected
    assert "connect-src 'self' https://fabric.teleionlabs.com" in out["help"]["csp"]


def test_static_page_and_readme_match_the_site_noun() -> None:
    """index.html shows the headline before the app loads the site noun; it must not drift from it."""
    site = json.loads((ROOT / "instructions" / "site.json").read_text(encoding="utf-8"))
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert f"<title>Eranos · {site['title']}</title>" in html
    assert f"<h1>{site['headline']}</h1>" in html
    readme = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    assert readme[2] == f"{site['headline']} {site['subline']}"
    # Readers that run no script get the skip link and the privacy line too.
    assert '<a class="er-skip-link" href="#main">Skip to content</a>' in html
    assert '<main id="main">' in html
    assert f"<p>{site['privacy']}</p>" in html


BRIEF = ROOT / "instructions" / "agent-brief.v3.txt"
# Words a visitor or an agent never reads in the brief or the access sentence (owner, Nov 1).
BRIEF_BANNED = re.compile(
    r"\b(nouns?|verbs?|receipts?|prove[sdn]?)\b|synthetic|l{2}ama|cloud", re.IGNORECASE
)


def test_starting_brief_noun_is_the_shared_brief() -> None:
    """The help noun's brief is the one shared agent brief, instructions/agent-brief.v3.txt (Agora copies the same
    file byte for byte), without its final newline: Tasks and Task Objects, claim · do · report, a record."""
    text = BRIEF.read_text(encoding="utf-8")
    assert text.endswith(".\n") and "\r" not in text
    noun = json.loads((ROOT / "instructions" / "help.json").read_text(encoding="utf-8"))
    assert noun["brief"] == text[:-1]
    assert noun["brief_source"]["sha256"] == hashlib.sha256(BRIEF.read_bytes()).hexdigest()
    assert "claim · do · report" in text and "Task Objects" in text
    # API paths stay exactly as they are, shown as code.
    assert "`https://eranosforgood.org/connect.json`" in text
    connect = json.loads((ROOT / "instructions" / "connect.json").read_text(encoding="utf-8"))
    for words in (
        text,
        noun["brief_interests_goal"],
        connect["authentication"],
        connect["restrictions"],
    ):
        assert not BRIEF_BANNED.search(words), words
    assert not re.search(r"\btools?\b", " ".join(s["title"] + s["detail"] for s in noun["steps"]))


def test_shared_brief_matches_the_notes_copy_when_it_is_beside_this_checkout() -> None:
    """The canonical file lives in the workspace's shared folder; this repo's copy must stay byte for byte equal."""
    for parent in ROOT.parents:
        shared = parent / "shared" / "agent-brief.v3.txt"
        if shared.is_file():
            assert shared.read_bytes() == BRIEF.read_bytes(), (
                f"{shared} and {BRIEF} have drifted apart"
            )
            return
    pytest.skip("the shared agent brief is not beside this checkout")


# Acceptance and accessibility fixes, October 30 ------------------------------------------------------------


def _router_pages() -> set[str]:
    router = (ROOT / "web" / "src" / "router.tsx").read_text(encoding="utf-8")
    table = router.split("const STATIC_ROUTES", 1)[1].split("};", 1)[0]
    return set(re.findall(r'"(/[a-z-]*)": \{ name:', table))


def test_the_worker_knows_the_app_pages_the_router_knows() -> None:
    worker = WORKER.read_text(encoding="utf-8")
    listed = re.search(r"const APP_PAGES = \[([^\]]*)\];", worker)
    assert listed, "the Worker lists the app's pages"
    assert set(re.findall(r'"(/[a-z-]*)"', listed.group(1))) == _router_pages()
    assert "const APP_KIT_PAGE_RE = /^\\/catalog\\/[^/]+$/;" in worker
    assert "/^\\/catalog\\/([^/]+)$/" in (ROOT / "web" / "src" / "router.tsx").read_text(
        encoding="utf-8"
    )


def test_unknown_addresses_answer_404_with_the_app_view() -> None:
    out = _worker(
        [
            ("missing", "GET", "/this-page-does-not-exist-uat", None),
            ("missing_deep", "GET", "/help/more/pages", None),
            ("missing_head", "HEAD", "/no-such-page", None),
            ("missing_api", "GET", "/api/no-such-route", None),
            *[(f"page{n}", "GET", path, None) for n, path in enumerate(sorted(_router_pages()))],
            ("kit", "GET", "/catalog/KIT-SHIFT-05", None),
            ("slash", "GET", "/nonprofits/", None),
            ("asset", "GET", "/snapshot/catalog.json", None),
            ("favicon", "GET", "/favicon.svg", None),
        ]
    )
    for name in ("missing", "missing_deep", "missing_head"):
        assert out[name]["status"] == 404, name
        assert out[name]["type"].startswith("text/html"), name
        assert "script-src 'self'" in out[name]["csp"], name
    # The 404 body is the app shell, so the app's "Page not found" view shows.
    assert '<div id="root">' in out["missing"]["body"]
    assert out["missing_api"]["status"] == 404 and "json" in out["missing_api"]["type"]
    for name in [n for n in out if n.startswith("page")] + ["kit", "slash"]:
        assert out[name]["status"] == 200, name
        assert out[name]["type"].startswith("text/html"), name
    assert out["asset"]["status"] == 200 and "json" in out["asset"]["type"]
    assert out["favicon"]["status"] == 200


def test_broken_escapes_wrong_kit_links_and_read_only_routes_answer_plainly() -> None:
    """Hunt, October 30, all read live first: a broken percent escape in an API path made the Worker throw, so
    Cloudflare answered its bare "error code: 1101" 500 with no CORS headers; every kit address answered 200,
    even one naming no kit; 405s on the read-only API had no Allow header; /connect.json set no cache rule."""
    out = _worker(
        [
            ("kit_escape", "GET", "/api/catalog/%E0%A4%A", None),
            ("noun_escape", "GET", "/api/nouns/eranos.instructions/%E0%A4%A", None),
            ("noun_ok", "GET", "/api/nouns/eranos.instructions/site", None),
            ("kit_page", "GET", "/catalog/KIT-SHIFT-05", None),
            ("kit_page_slash", "GET", "/catalog/KIT-SHIFT-05/", None),
            ("kit_page_missing", "GET", "/catalog/KIT-SHIFT-99", None),
            ("kit_page_lower", "GET", "/catalog/kit-shift-05", None),
            ("kit_page_escape", "GET", "/catalog/%E0%A4%A", None),
            ("kit_page_head", "HEAD", "/catalog/NOPE-KIT-99", None),
            ("post_api", "POST", "/api/catalog", {}),
            ("connect_json", "GET", "/connect.json", None),
            ("post_connect", "POST", "/connect.json", {}),
        ]
    )
    for name in ("kit_escape", "noun_escape"):
        assert out[name]["status"] == 400, name
        assert out[name]["type"] == "application/problem+json", name
        assert json.loads(out[name]["body"])["code"] == "invalid_request", name
        assert out[name]["cors"] == "*", name
    assert out["noun_ok"]["status"] == 200
    for name in ("kit_page", "kit_page_slash"):
        assert out[name]["status"] == 200, name
    for name in ("kit_page_missing", "kit_page_lower", "kit_page_escape", "kit_page_head"):
        assert out[name]["status"] == 404, name
        assert out[name]["type"].startswith("text/html"), name
    # The 404 body is still the app shell, whose "Kit unavailable" view explains and links back.
    assert '<div id="root">' in out["kit_page_missing"]["body"]
    assert out["post_api"]["status"] == 405 and out["post_api"]["allow"] == "GET, HEAD"
    assert out["post_connect"]["status"] == 405 and out["post_connect"]["allow"] == "GET, HEAD"
    assert out["connect_json"]["status"] == 200 and "no-store" in out["connect_json"]["cache"]


def _descriptor() -> dict[str, Any]:
    script = (
        "import { accessDescriptor } from "
        + json.dumps((ROOT / "deploy" / "cloudflare" / "access.js").as_uri())
        + "; console.log(JSON.stringify(accessDescriptor('eranos')));"
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True
    )
    result: dict[str, Any] = json.loads(run.stdout)
    return result


def test_connect_is_a_page_of_the_site_titled_connect_to_eranos() -> None:
    noun = json.loads((ROOT / "instructions" / "connect.json").read_text(encoding="utf-8"))
    out = _worker(
        [
            ("connect", "GET", "/connect", None),
            ("connect_head", "HEAD", "/connect", None),
            ("connect_json", "GET", "/connect.json", None),
            ("connect_post", "POST", "/connect", {}),
        ]
    )
    page = out["connect"]
    assert page["status"] == 200 and page["type"].startswith("text/html")
    assert "script-src 'self'" in page["csp"] and page["frame"] == "DENY"
    body = page["body"]
    # The site's own shell: its title is this page's, and the app that draws the layout loads into it.
    assert body.count("<title>") == 1 and "<title>Connect to Eranos</title>" in body
    assert noun["title"] == "Connect to Eranos"
    assert '<a class="er-skip-link" href="#main">Skip to content</a>' in body
    assert '<nav aria-label="Primary navigation">' in body and '<div id="root">' in body
    assert '<script type="module" src="/src/main.tsx"></script>' in body
    # Its text is the connect noun, readable without a script, and the machine-readable link stays.
    main = html.unescape(body.split('<main id="main">', 1)[1].split("</main>", 1)[0])
    assert f"<h1>{noun['title']}</h1>" in main
    for key in ("authentication", "restrictions", "anonymous_note", "bearer_note"):
        assert noun[key] in main, key
    assert f'<a href="/connect.json">{noun["machine_link"]}</a>' in main
    assert f'<a href="{noun["links"]["fabric_connect"]}">{noun["anonymous_link"]}</a>' in main
    assert out["connect_head"]["status"] == 200 and out["connect_head"]["body"] == ""
    assert out["connect_post"]["status"] == 405
    # The JSON for agents is unchanged: the access descriptor, as before; the page says the same two sentences.
    descriptor = _descriptor()
    assert json.loads(out["connect_json"]["body"]) == descriptor
    assert (noun["authentication"], noun["restrictions"]) == (
        descriptor["authentication"],
        descriptor["restrictions"],
    )
    assert noun["links"]["fabric_connect"] == descriptor["fabric_connect_url"]


def test_snapshot_page_nouns_match_their_source_files() -> None:
    """The static copies the offline site reads are exports of instructions/, never edited by hand."""
    for source in sorted((ROOT / "instructions").glob("*.json")):
        value = json.loads(source.read_text(encoding="utf-8"))
        for folder in (ROOT / "web" / "snapshot", ROOT / "web" / "public" / "snapshot"):
            copy = folder / "nouns" / "eranos.instructions" / source.name
            assert json.loads(copy.read_text(encoding="utf-8"))["value"] == value, copy
            listing = json.loads(
                (folder / "nouns" / "eranos.instructions.json").read_text(encoding="utf-8")
            )
            assert {r["key"]: r["value"] for r in listing["records"]}[source.stem] == value, (
                source.stem
            )


def test_the_nonprofits_page_opens_in_plain_words() -> None:
    noun = json.loads((ROOT / "instructions" / "nonprofits.json").read_text(encoding="utf-8"))
    opening = f"{noun['lede']} {noun['no_agent']}"
    assert not re.search(r"\b(nouns?|verbs?|seed packs?)\b", opening, re.IGNORECASE)
    assert "You don\u2019t need your own AI agent for research requests." in noun["no_agent"]
    assert noun["form"]["label"] == noun["title"] == "Tell us what you need"
    plan = next(step for step in noun["steps"] if step["id"] == "plan")
    assert (
        plan["detail"].startswith("A worker reads it") and "sorts it into parts" in plan["detail"]
    )
    # The redesigned page (the nonprofits-page noun) states its bounds before the box, in plain words.
    redesign = json.loads(
        (ROOT / "instructions" / "nonprofits-page.json").read_text(encoding="utf-8")
    )
    opening = f"{redesign['heading']} {redesign['lead']} {redesign['bounds']['head']} {redesign['bounds']['body']}"
    assert not re.search(r"\b(nouns?|verbs?|seed packs?)\b", opening, re.IGNORECASE)
    assert redesign["bounds"]["head"] == "We don\u2019t accept private information at this stage."
    page = (ROOT / "web" / "src" / "pages" / "Nonprofits.tsx").read_text(encoding="utf-8")
    assert page.index("page.bounds.head") < page.index("<RequestBox")


def test_the_privacy_line_matches_what_the_site_loads() -> None:
    site = json.loads((ROOT / "instructions" / "site.json").read_text(encoding="utf-8"))
    assert (
        site["privacy"].startswith("No analytics, ads or cookies.") and "Teleion Fabric" in site["privacy"]
    )
    # "Every page, script and style comes from this site": the policy the Worker sends allows nothing else,
    # except the request box's calls to Tessera.
    worker = WORKER.read_text(encoding="utf-8")
    policy = re.search(r"const CONTENT_SECURITY_POLICY = \[([\s\S]*?)\]\.join", worker)
    assert policy
    directives = dict(
        d.split(" ", 1) for d in json.loads(f"[{policy.group(1).rstrip().rstrip(',')}]") if " " in d
    )
    for name in ("default-src", "script-src", "style-src", "font-src"):
        assert directives[name] == "'self'", name
    assert directives["img-src"] == "'self' data:"
    assert directives["connect-src"] == "'self' https://fabric.teleionlabs.com"
    # Zero browser storage (owner, Nov 1), except, until request codes replace them (Phase C), a request's private
    # link (lib/status/keys.ts), which the footer names.
    allowed = {"keys.ts"}
    for path in sorted((ROOT / "web" / "src").rglob("*.ts*")):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"document\.cookie|sessionStorage|indexedDB", text), path.name
        if path.name not in allowed:
            assert "localStorage" not in text, path.name
    shell = json.loads((ROOT / "instructions" / "shell.json").read_text(encoding="utf-8"))
    assert shell["footer"]["line"] == "We don\u2019t accept private information at this stage."
    trust = json.loads((ROOT / "instructions" / "trust.json").read_text(encoding="utf-8"))
    privacy = " ".join(" ".join(s["items"]) for s in trust["privacy"]["sections"])
    assert "private links" in privacy
    # F-PRIV-LOGS-001: what Cloudflare keeps is said in the page's own words, and matches wrangler.jsonc.
    assert "request logs and traces are switched off" in privacy
    wrangler = (ROOT / "deploy" / "cloudflare" / "wrangler.jsonc").read_text(encoding="utf-8")
    assert '"invocation_logs": false' in wrangler
    assert re.search(r'"traces":\s*\{\s*"enabled": false', wrangler)
    assert "set-cookie" not in worker.lower()


# Paper & Ink redesign and the request flow, October 31 ----------------------------------------------------------


def test_the_worker_knows_the_request_pages() -> None:
    out = _worker(
        [
            ("status", "GET", "/requests/rq-r_" + "a" * 32 + "-mvwv3xwe", None),
            ("result", "GET", "/requests/example/result", None),
            ("example", "GET", "/requests/example", None),
            ("deep", "GET", "/requests/x/result/more", None),
            ("library", "GET", "/library", None),
        ]
    )
    for name in ("status", "result", "example", "library"):
        assert out[name]["status"] == 200, name
    assert out["deep"]["status"] == 404


FAULTY_DB = """({ FABRIC_DB: { prepare() { throw new Error("no such table: record_heads"); } } })"""


def test_a_mirror_fault_falls_back_to_the_snapshot_instead_of_500() -> None:
    out = _worker(
        [
            ("site", "GET", "/api/nouns/eranos.instructions/site", None),
            ("listing", "GET", "/api/nouns/eranos.instructions", None),
            ("catalog", "GET", "/api/catalog", None),
            ("history", "GET", "/api/nouns/eranos.requests/rq-x/history", None),
        ],
        FAULTY_DB,
    )
    assert out["site"]["status"] == 200
    assert json.loads(out["site"]["body"])["value"]["headline"] == "Spare tokens for good."
    assert json.loads(out["listing"]["body"])["records"]
    assert len(json.loads(out["catalog"]["body"])["kits"]) >= 5
    assert out["history"]["status"] == 404


HISTORY_DB = """({ FABRIC_DB: { prepare(sql) { return { bind() { return { async all() {
  return { results: sql.includes("ORDER BY r.version") ? [
    { version: 2, created_at: 1793474165, value: JSON.stringify({ status: "open_for_build", event: { type: "planned", at: 1793474200, receipt: "e".repeat(64) } }) },
    { version: 3, created_at: 1793474352, value: JSON.stringify({ status: "open_for_build", event: { type: "work_claimed", part: 1, at: 1793474352, receipt: "f".repeat(64), worker: "kestrel-41" } }) },
  ] : [] }; }, async first() { return null; } }; } }; } } })"""


def test_a_request_record_history_is_public_and_only_for_requests_and_plans() -> None:
    out = _worker(
        [
            ("history", "GET", "/api/nouns/eranos.requests/rq-x/history", None),
            ("plans", "GET", "/api/nouns/eranos.plans/rq-x/history", None),
            ("other", "GET", "/api/nouns/eranos.instructions/site/history", None),
            ("escape", "GET", "/api/nouns/eranos.requests/%E0%A4%A/history", None),
        ],
        HISTORY_DB,
    )
    history = json.loads(out["history"]["body"])
    assert out["history"]["status"] == 200
    assert [v["version"] for v in history["versions"]] == [2, 3]
    assert [v["step_index"] for v in history["versions"]] == [1, 2]
    assert history["versions"][0]["skipped_internal_versions"] == 1
    assert history["versions"][1].get("skipped_internal_versions") in (None, 0)
    assert history["total_steps"] == 2
    assert "step_index" in history["history_note"]
    assert history["versions"][1]["value"]["event"]["worker"] == "kestrel-41"
    assert out["plans"]["status"] == 200
    assert out["other"]["status"] == 404
    assert out["escape"]["status"] == 400


OPEN_TASKS = """({ TESSERA_SURFACE_KEY: "test-surface-key", TESSERA: { async fetch(url) {
  const queue = new URL(url).searchParams.get("queue");
  return new Response(JSON.stringify({ verbs: [{ task_id: "t_" + queue, kind: queue === "eq02" ? "research" : "report_review",
    created_at: 1793474000, tags: queue === "eq02" ? ["open:anonymous"] : [], brief: { title: "Clinic: summarize the laws", request_id: "rq-x", part: 1, secret_output: "never shown" },
    output: "never shown" }], next: null }), { headers: { "content-type": "application/json" } });
} } })"""


def test_open_tasks_are_read_with_the_surface_key_and_show_only_the_brief_title() -> None:
    out = _worker([("tasks", "GET", "/api/open-tasks", None)], OPEN_TASKS)
    tasks = json.loads(out["tasks"]["body"])["tasks"]
    assert [t["queue"] for t in tasks] == ["eq02", "eq03"]
    assert tasks[0] == {
        "task_id": "t_eq02",
        "queue": "eq02",
        "kind": "research",
        "title": "Clinic: summarize the laws",
        "request_id": "rq-x",
        "part": 1,
        "created_at": 1793474000,
        "open_to_anonymous": True,
    }
    assert "never shown" not in out["tasks"]["body"]
    unreachable = _worker([("tasks", "GET", "/api/open-tasks", None)])
    assert unreachable["tasks"]["status"] == 503


def test_the_agent_banner_copies_the_llms_line_and_pages_link_no_dead_github_address() -> None:
    banner = json.loads((ROOT / "instructions" / "agent-banner.json").read_text(encoding="utf-8"))
    # AgentBanner board: Copy puts exactly this line on the clipboard, and /llms.txt answers it.
    assert banner["copy_text"] == "Read https://eranosforgood.org/llms.txt and follow it."
    assert banner["chip"] == "Read eranosforgood.org/llms.txt"
    assert all(
        link["href"].startswith(("/", "https://agora.eranosforgood.org/"))
        for link in banner["links"]
    )
    dead = re.compile(r"github\.com/ta-amps")
    allowed_report_links = {
        "https://github.com/ta-amps/eranos-public-marketplace-for-public-good-token-burn/issues",
        "https://github.com/ta-amps/eranos-public-marketplace-for-public-good-token-burn/security/advisories",
    }
    shown = [ROOT / "web" / "index.html", ROOT / "web" / "public" / "agent-banner.js"]
    shown += sorted((ROOT / "instructions").glob("*.json"))
    shown += sorted((ROOT / "web" / "src").rglob("*.ts*"))
    matched = [p for p in shown if dead.search(p.read_text(encoding="utf-8"))]
    assert [p.name for p in matched] == ["trust.json"]
    trust_urls = set(
        re.findall(
            r"https://github\.com/ta-amps/[^\s\"']+",
            (ROOT / "instructions" / "trust.json").read_text(encoding="utf-8"),
        )
    )
    assert trust_urls == allowed_report_links


def test_the_favicon_is_the_tile_mark_without_provenance_metadata() -> None:
    out = _worker([("favicon", "GET", "/favicon.svg", None)])
    svg = out["favicon"]["body"]
    for path in (svg, (ROOT / "web" / "public" / "favicon.svg").read_text(encoding="utf-8")):
        assert 'viewBox="0 0 100 100"' in path
        for x, y in ((0, 0), (56, 0), (0, 56), (56, 56)):
            assert f'x="{x}" y="{y}" width="44" height="44" rx="10"' in path
        assert "metadata" not in path and "155e49" not in path


def test_process_results_are_plain_markdown_for_any_agent() -> None:
    """/p/<id>/agent.md and practice.md render the result's own nouns; nothing else answers there."""
    out = _worker(
        [
            ("agent", "GET", "/p/example-process/agent.md", None),
            ("practice", "GET", "/p/example-process/practice.md", None),
            ("report_only", "GET", "/p/example/practice.md", None),
            ("unknown", "GET", "/p/rq-r_" + "0" * 32 + "-abc/agent.md", None),
            ("requests_page", "GET", "/requests", None),
        ]
    )
    example = json.loads((ROOT / "instructions" / "request-example-process.json").read_text())
    process = example["solution"]["process"]
    agent = out["agent"]
    assert agent["status"] == 200 and "markdown" in agent["type"]
    assert process["task"]["title"] in agent["body"]
    for line in process["task_object"]["how_to"] + process["task_object"]["person_only"]:
        assert line in agent["body"], line
    assert "/p/example-process/practice.md" in agent["body"]
    practice = out["practice"]
    assert practice["status"] == 200
    for case in process["practice"]:
        assert case["input"].startswith("Practice case: an example, not a real person or case.")
        assert case["input"] in practice["body"]
    assert out["unknown"]["status"] == 404
    assert out["requests_page"]["status"] == 200


def test_request_pages_and_the_request_api_show_only_real_records_or_the_example() -> None:
    """Merged from the 22:14Z deploy: /requests/<id> is the plain status page for any id (the page itself says when a
    request is unknown); /api/requests/<id> reads the public record, and REQ-INTAKE-07 (an earlier film's address)
    is the example request and says so. Nothing is made up per id."""
    out = _worker(
        [
            ("req_page", "GET", "/requests/REQ-INTAKE-07", None),
            ("req_live_page", "GET", "/requests/rq-r_" + "0" * 32 + "-abc", None),
            ("req_api", "GET", "/api/requests/REQ-INTAKE-07", None),
            ("req_missing_api", "GET", "/api/requests/rq-r_" + "0" * 32 + "-abc", None),
            ("req_bad_api", "GET", "/api/requests/%E0%A4%A", None),
            ("agent_json", "GET", "/.well-known/agent.json", None),
            ("agent_md", "GET", "/agent.md", None),
            ("llms", "GET", "/llms.txt", None),
        ]
    )
    for name in ("req_page", "req_live_page"):
        assert out[name]["status"] == 200, name
        assert out[name]["type"].startswith("text/html"), name
    payload = json.loads(out["req_api"]["body"])
    assert out["req_api"]["status"] == 200 and payload["example"] is True
    assert payload["page"] == "/requests/REQ-INTAKE-07"
    assert out["req_missing_api"]["status"] == 404
    assert out["req_bad_api"]["status"] == 400
    assert out["agent_json"]["status"] == 200 and json.loads(out["agent_json"]["body"])["name"]
    # /agent.md is the same guide as /llms.txt, plus the access lines.
    assert out["agent_md"]["status"] == 200 and "markdown" in out["agent_md"]["type"]
    guide = (
        json.loads((ROOT / "instructions" / "llms.json").read_text())["text"]
        .strip()
        .splitlines()[0]
    )
    assert guide in out["agent_md"]["body"] and guide in out["llms"]["body"]
    assert "POST /api/handshake" in out["agent_md"]["body"]


def test_nothing_the_site_serves_says_synthetic() -> None:
    from eranos.visible import shown_parts

    """Owner, October 31: "DO NOT INCLUDE SYNTHETIC." Every page shell, API answer, agent text and snapshot file the
    site serves says "made-up" instead (eranos/visible.py and the Worker's visibleWords)."""
    word = re.compile("synthetic", re.IGNORECASE)
    kits = sorted(p.stem for p in (ROOT / "web" / "snapshot" / "catalog").glob("KIT-*.json"))
    nouns = sorted(p.stem for p in (ROOT / "instructions").glob("*.json"))
    stores = [
        "eranos.instructions",
        "eranos.plans",
        "eranos.requests",
        "eranos.solutions",
        "eranos.sources",
        "eranos.verb_templates",
    ]
    pages = [
        "/",
        "/help",
        "/nonprofits",
        "/library",
        "/requests",
        "/requests/example",
        "/requests/REQ-INTAKE-07",
        "/catalog",
        "/contribute",
        "/tracks",
        "/fabric",
        "/about",
        "/connect",
        "/privacy",
        "/terms",
        "/report",
    ]
    pages += [f"/catalog/{kit}" for kit in kits]
    api = [
        "/api/health",
        "/api/catalog",
        "/api/tracks",
        "/api/examples",
        "/api/requests",
        "/api/requests/REQ-INTAKE-07",
        "/api/fabric",
        "/api/open-tasks",
    ]
    api += [f"/api/catalog/{kit}" for kit in kits] + [f"/api/nouns/{store}" for store in stores]
    api += [f"/api/nouns/eranos.instructions/{key}" for key in nouns]
    agent = [
        "/connect.json",
        "/.well-known/agent-card.json",
        "/.well-known/agent.json",
        "/.well-known/security.txt",
        "/llms.txt",
        "/llms-full.txt",
        "/agent.md",
        "/agent-start.json",
        "/robots.txt",
        "/p/example-process/agent.md",
        "/p/example-process/practice.md",
    ]
    calls = [(f"get{i}", "GET", path, None) for i, path in enumerate(pages + api + agent)]
    calls += [
        ("mcp_list", "POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
        (
            "mcp_search",
            "POST",
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "search_catalog", "arguments": {}},
            },
        ),
        (
            "mcp_tracks",
            "POST",
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "list_tracks", "arguments": {}},
            },
        ),
    ]
    out = _worker(calls)

    def own_words(body: str) -> str:
        # Records bound by a digest and verbatim quotes and source text are served exactly as
        # stored (eranos/visible.py); everything else is the site's own words.
        try:
            return json.dumps(shown_parts(json.loads(body)))
        except ValueError:
            return body

    said = sorted(name for name in out if word.search(own_words(out[name]["body"] or "")))
    assert said == [], said[:10]
    # The snapshot files are served as they are, at /snapshot/...
    files = [p for p in (ROOT / "web" / "public" / "snapshot").rglob("*.json")]
    assert files
    assert [
        p.relative_to(ROOT).as_posix()
        for p in files
        if word.search(own_words(p.read_text(encoding="utf-8")))
    ] == []


def test_a_requests_own_words_pass_the_display_filter_but_quotes_do_not() -> None:
    """A request's text is contributed data, shown through the word filter; stored records and a source's own quote
    stay as they are. The Worker and the page hold the same rule."""
    from eranos.visible import visible

    word = "syn" + "thetic"
    shown = visible({"text": f"a {word} case", "quote": f"a {word} case"})
    assert word not in shown["text"]
    assert word in shown["quote"]
    for path in ("deploy/cloudflare/worker.js", "web/src/lib/shown.ts"):
        line = next(x for x in (ROOT / path).read_text(encoding="utf-8").splitlines() if "VERBATIM_KEYS = new Set" in x)
        assert '"text"' not in line, path


def test_a_kit_draft_marked_as_practice_cases_passes_the_practice_check() -> None:
    """Agents only ever see the practice-case mark, so a draft that uses it passes where the former mark passed, and
    a draft with no mark at all is still refused."""
    from eranos.visible import visible

    bundle = json.loads(
        (ROOT / "examples" / "kits" / "05-volunteer-shift-sop-pack.json").read_text()
    )
    draft = {**bundle["draft"], "drafted_by": "volunteer-a", "drafted_by_key": "key-a"}
    shown = visible(draft)
    unmarked = json.loads(
        json.dumps(shown)
        .replace("Practice case: an example, not a real person or case. ", "")
        .replace("practice-case", "")
    )
    out = _worker(
        [
            ("old", "POST", "/api/practice", {"draft": draft}),
            ("shown", "POST", "/api/practice", {"draft": shown}),
            ("unmarked", "POST", "/api/practice", {"draft": unmarked}),
        ]
    )
    assert "Practice case: an example, not a real person or case." in json.dumps(shown)
    assert "synthetic" not in json.dumps(shown).lower()
    old, made_up, refused = (json.loads(out[name]["body"]) for name in ("old", "shown", "unmarked"))
    assert out["shown"]["status"] == out["old"]["status"] == 200
    assert made_up["passed"] is True and old["passed"] is True, (made_up["issues"], old["issues"])
    assert refused["passed"] is False
    assert any("practice-case mark" in issue for issue in refused["issues"]), refused["issues"]
    assert "synthetic" not in (out["shown"]["body"] + out["unmarked"]["body"]).lower()


def test_a_published_process_package_downloads_from_the_local_tessera_and_nothing_else_does() -> (
    None
):
    """/p/<id>/download reads the bundle from Tessera with the site's own key and serves the exact bytes, with the
    catalog's SHA-256; quarantined, self-reviewed, unknown, example and tampered ids are refused."""
    import hashlib
    import io
    import tarfile
    import tempfile

    from tessera import Store
    from tessera.service import ServiceSettings, create_app

    from eranos.e2e import _free_port, _serve

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"#!/bin/sh\necho 'Practice case: an example, not a real person or case.'\n"
        info = tarfile.TarInfo("process/run.sh")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    bundle = buf.getvalue()
    sha = hashlib.sha256(bundle).hexdigest()

    def record(key: str, **over: Any) -> dict[str, Any]:
        value: dict[str, Any] = {
            "kit": {
                "kit_id": key,
                "title": "Clean volunteer sign-up sheets",
                "summary": "A data-cleaning pipeline.",
                "drafted_by_key": "kb_builder",
            },
            "blob_sha256": sha,
            "tags": ["kind:process", "status:verified"],
            "review_receipt": "c" * 64,
            "drafter_key_id": "kb_builder",
            "reviewer_key_id": "kb_reviewer",
            "reviewed_by_key": "kb_reviewer",
        }
        value.update(over)
        return value

    records = {
        "PRC-35DE86-01": record("PRC-35DE86-01"),
        "PRC-QUAR-02": record("PRC-QUAR-02", tags=["kind:process", "status:quarantined"]),
        "PRC-SELF-03": record(
            "PRC-SELF-03", reviewer_key_id="kb_builder", reviewed_by_key="kb_builder"
        ),
        "PRC-NOREV-05": record("PRC-NOREV-05", review_receipt=None),
        "PRC-WRONG-04": record("PRC-WRONG-04", blob_sha256="d" * 64),
    }
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(f"{tmp}/tessera.db")
        reader, _ = store.issue_key(
            "eranos-site", queues=["eranos.read"], scopes=["store", "surface:eranos"]
        )
        assert store.put_blob(bundle) == sha
        port = _free_port()
        settings = ServiceSettings(
            db_path=f"{tmp}/tessera.db", public_url=f"http://127.0.0.1:{port}"
        )
        with _serve(create_app(store, settings), port, "/v1/health") as url:
            env = (
                "({ TESSERA_SURFACE_KEY: " + json.dumps(reader) + ", "
                "TESSERA: { fetch: (target, init) => fetch(String(target).replace('https://fabric.teleionlabs.com', "
                + json.dumps(url)
                + "), init) }, "
                "FABRIC_DB: { prepare() { return { bind(store, key) { return { async first() { "
                "const records = " + json.dumps(records) + "; "
                "return store === 'eranos.catalog' && records[key] ? { value: JSON.stringify(records[key]) } : null; }, "
                "async all() { return { results: [] }; } }; } }; } } })"
            )
            out = _worker(
                [
                    ("ok", "GET", "/p/PRC-35DE86-01/download", None),
                    ("head", "HEAD", "/p/PRC-35DE86-01/download", None),
                    ("quarantined", "GET", "/p/PRC-QUAR-02/download", None),
                    ("self_reviewed", "GET", "/p/PRC-SELF-03/download", None),
                    ("no_review", "GET", "/p/PRC-NOREV-05/download", None),
                    ("tampered", "GET", "/p/PRC-WRONG-04/download", None),
                    ("unknown", "GET", "/p/PRC-NONE-09/download", None),
                    ("example", "GET", "/p/example-process/download", None),
                    ("agent", "GET", "/p/PRC-35DE86-01/agent.md", None),
                ],
                env,
            )
    ok = out["ok"]
    assert ok["status"] == 200 and ok["type"] == "application/gzip"
    assert ok["sha256"] == sha == ok["xsha"] == records["PRC-35DE86-01"]["blob_sha256"]
    assert ok["disposition"] == 'attachment; filename="PRC-35DE86-01.tar.gz"'
    assert out["head"]["status"] == 200 and out["head"]["xsha"] == sha
    for name in ("quarantined", "self_reviewed", "no_review"):
        assert out[name]["status"] == 403, name
    assert out["tampered"]["status"] == 502
    assert out["unknown"]["status"] == 404 and out["example"]["status"] == 404
    assert "/p/PRC-35DE86-01/download" in out["agent"]["body"] and sha in out["agent"]["body"]
    assert reader not in json.dumps(out)


def test_trust_routes_security_txt_and_owner_wording() -> None:
    from fastapi.testclient import TestClient

    from eranos.api.app import app

    out = _worker(
        [
            ("privacy", "GET", "/privacy", None),
            ("terms", "GET", "/terms", None),
            ("report", "GET", "/report", None),
            ("privacy_head", "HEAD", "/privacy", None),
            ("privacy_post", "POST", "/privacy", {}),
            ("sec", "GET", "/.well-known/security.txt", None),
            ("sec_head", "HEAD", "/.well-known/security.txt", None),
            ("sec_post", "POST", "/.well-known/security.txt", {}),
            ("robots", "GET", "/robots.txt", None),
            ("tour", "GET", "/?tour=judge", None),
        ]
    )
    for name in ("privacy", "terms", "report", "privacy_head", "tour"):
        assert out[name]["status"] == 200, name
        assert out[name]["type"].startswith("text/html"), name
        assert "style-src 'self'" in out[name]["csp"], name
    assert out["privacy_post"]["status"] == 405
    sec = out["sec"]
    assert sec["status"] == 200 and sec["type"] == "text/plain; charset=utf-8"
    for line in (
        "Contact: https://github.com/ta-amps/eranos-public-marketplace-for-public-good-token-burn/security/advisories",
        "Expires: 2027-10-31T23:59:59.000Z",
        "Preferred-Languages: en",
        "Canonical: https://eranosforgood.org/.well-known/security.txt",
    ):
        assert line in sec["body"], line
    assert out["sec_head"]["status"] == 200 and out["sec_head"]["body"] == ""
    assert out["sec_post"]["status"] == 405 and out["sec_post"]["allow"] == "GET, HEAD"
    assert "Allow: /.well-known/security.txt" in out["robots"]["body"]

    with TestClient(app) as client:
        api_sec = client.get("/.well-known/security.txt")
        assert api_sec.status_code == 200
        assert api_sec.headers["content-type"] == "text/plain; charset=utf-8"
        assert "Canonical: https://eranosforgood.org/.well-known/security.txt" in api_sec.text

    # Owner, Nov 1: the visible words are "Tasks" and "Task Objects" (this supersedes the earlier lowercase rule),
    # never "tasks (verbs)".
    bad_terms = re.compile(r"\b[Tt]asks \([Vv]erbs\)")
    for path in [ROOT / "README.md", *sorted((ROOT / "instructions").glob("*.json"))]:
        text = path.read_text(encoding="utf-8")
        assert not bad_terms.search(text), path.name
        assert "cloud workers" not in text.lower(), path.name
    trust_text = (ROOT / "instructions" / "trust.json").read_text(encoding="utf-8")
    assert "Task Objects" in trust_text and "tasks (things to do)" in trust_text
    assert "A person decides. Nothing is used before that." in trust_text
    assert "CC BY 4.0" in trust_text and "Apache-2.0" in trust_text
    assert "history.replaceState" in trust_text and "#k=" in trust_text


def test_footer_is_the_shared_standard_footer() -> None:
    """MUST-FOLLOW rule 13 and footer v2 (ta-amps.footer/2, components contract v2): one row of links in the canonical
    order (a link to another host is absolute and carries ↗) plus one short line, the privacy line."""
    shell = json.loads((ROOT / "instructions" / "shell.json").read_text(encoding="utf-8"))
    links = shell["footer"]["links"]
    labels = [link["label"] for link in links]
    assert labels == [
        "Agora ↗",
        "Teleion Labs ↗",
        "Library",
        "Requests",
        "Network ↗",
        "Models used ↗",
        "Status ↗",
        "Source ↗",
        "Privacy",
        "Terms",
        "Report a problem",
    ]
    for link in links:
        external = link["label"].endswith(" ↗")
        assert external == ("href" in link) and external != ("to" in link), link
        if external:
            assert link["href"].startswith("https://"), link
    assert shell["footer"]["line"] == "We don\u2019t accept private information at this stage."
    for parent in ROOT.parents:
        spec_path = parent / "coordination-2026-10-31" / "claude-design-components.v2.json"
        if spec_path.is_file():
            spec = json.loads(spec_path.read_text(encoding="utf-8"))["components"]["SiteFooter"]
            eranos = spec["surfaces"]["eranos"]
            assert [link["label"] for link in eranos["links"]] == labels
            assert [link["href"] for link in eranos["links"]] == [
                link.get("href") or link["to"] for link in links
            ]
            assert shell["footer"]["line"] == eranos["line"]
            break
    page = (ROOT / "web" / "src" / "pages" / "Nonprofits.tsx").read_text(encoding="utf-8")
    assert page.index("page.bounds.head") < page.index("<RequestBox")


def test_the_alias_redirects_page_navigations_and_serves_machine_paths_in_place() -> None:
    """One canonical address for people (Nov 2 design §0.15; alias audit, Nov 2): on the workers.dev alias an HTML page
    navigation answers 301 (GET, HEAD) or 308 (other methods) to eranosforgood.org, keeping path and query, while
    /mcp, /api/*, /connect.json, /llms.txt, /.well-known/* and /healthz answer in place with the apex's own body, so MCP
    clients, service bindings with redirect: "manual" and older CLIs keep working. www redirects everything; a CORS
    preflight, local hosts and version previews are served in place; every page names its own canonical address."""
    script = (
        WORKER_SCRIPT.replace("WORKER", json.dumps(WORKER.as_uri()))
        .replace("PUBLIC_DIR", json.dumps((ROOT / "web" / "public").as_posix()))
        .replace("INDEX_HTML", json.dumps((ROOT / "web" / "index.html").as_posix()))
        .replace("EXTRA_ENV", "({})")
        .replace("REQUESTS", "[]")
        + """
const res = {};
const at = async (name, url, init = {}) => {
  const r = await worker.fetch(new Request(url, init), env);
  res[name] = { status: r.status, location: r.headers.get("location"), cors: r.headers.get("access-control-allow-origin"), body: init.method === "HEAD" ? "" : await r.text() };
};
const ALIAS = "https://eranos.ta-amps.workers.dev";
const APEX = "https://eranosforgood.org";
const json = (body) => ({ method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
for (const path of MACHINE_PATHS) {
  await at(`alias ${path}`, ALIAS + path);
  await at(`apex ${path}`, APEX + path);
}
await at("alias GET /mcp", ALIAS + "/mcp");
await at("apex GET /mcp", APEX + "/mcp");
await at("alias POST /mcp", ALIAS + "/mcp", json({ jsonrpc: "2.0", id: 1, method: "tools/list" }));
await at("apex POST /mcp", APEX + "/mcp", json({ jsonrpc: "2.0", id: 1, method: "tools/list" }));
await at("alias POST /api/practice", ALIAS + "/api/practice", json({ draft: {} }));
await at("apex POST /api/practice", APEX + "/api/practice", json({ draft: {} }));
await at("apex", APEX + "/nonprofits", { headers: { accept: "text/html" } });
await at("apexHome", APEX + "/", { headers: { accept: "text/html" } });
await at("page", ALIAS + "/library?q=grants");
await at("pageHome", ALIAS + "/");
await at("pageSlash", ALIAS + "/help/");
await at("pageHead", ALIAS + "/help", { method: "HEAD" });
await at("pagePost", ALIAS + "/help", { method: "POST", body: "{}" });
await at("pageKit", ALIAS + "/catalog/example-kit");
await at("pageRequest", ALIAS + "/requests/example?moment=decided");
await at("www", "https://www.eranosforgood.org/requests/example?moment=decided");
await at("wwwApi", "https://www.eranosforgood.org/api/health");
await at("preflight", ALIAS + "/mcp", { method: "OPTIONS", headers: { origin: "https://example.org", "access-control-request-method": "POST" } });
await at("local", "http://localhost:8787/help", { headers: { accept: "text/html" } });
await at("preview", "https://6d7470f5-eranos.ta-amps.workers.dev/help", { headers: { accept: "text/html" } });
const card = await (await worker.fetch(new Request(ALIAS + "/.well-known/agent-card.json"), env)).json();
res.card = card.url;
console.log(JSON.stringify(res));
""".replace("MACHINE_PATHS", json.dumps(ALIAS_MACHINE_PATHS))
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    out = json.loads(run.stdout.strip().splitlines()[-1])
    # Machine paths on the alias: served in place, the same status and body as the apex.
    for path in [*ALIAS_MACHINE_PATHS, "POST /mcp", "POST /api/practice"]:
        alias, apex = out[f"alias {path}"], out[f"apex {path}"]
        assert alias["status"] == apex["status"] == 200, (path, alias["status"], apex["status"])
        assert alias["location"] is None, path
        assert alias["body"] == apex["body"], path
    assert '"tools"' in out["alias POST /mcp"]["body"]
    # GET /mcp answers the same as on the apex (MCP takes POST), never a redirect.
    assert out["alias GET /mcp"]["status"] == out["apex GET /mcp"]["status"] != 308
    assert out["alias GET /mcp"]["location"] is None
    assert out["card"] == "https://eranosforgood.org"
    # HTML page navigations on the alias: 301 for GET and HEAD, 308 otherwise, keeping path and query.
    for name, location in [
        ("page", "https://eranosforgood.org/library?q=grants"),
        ("pageHome", "https://eranosforgood.org/"),
        ("pageSlash", "https://eranosforgood.org/help/"),
        ("pageHead", "https://eranosforgood.org/help"),
        ("pageKit", "https://eranosforgood.org/catalog/example-kit"),
        ("pageRequest", "https://eranosforgood.org/requests/example?moment=decided"),
    ]:
        assert (out[name]["status"], out[name]["location"]) == (301, location), name
    assert (out["pagePost"]["status"], out["pagePost"]["location"]) == (
        308,
        "https://eranosforgood.org/help",
    )
    assert out["page"]["cors"] == "*"
    # www redirects everything; apex pages name their own canonical address.
    assert (out["www"]["status"], out["www"]["location"]) == (
        301,
        "https://eranosforgood.org/requests/example?moment=decided",
    )
    assert (out["wwwApi"]["status"], out["wwwApi"]["location"]) == (
        301,
        "https://eranosforgood.org/api/health",
    )
    assert out["apex"]["status"] == 200
    assert (
        '<link rel="canonical" href="https://eranosforgood.org/nonprofits"' in out["apex"]["body"]
    )
    assert (
        '<meta property="og:url" content="https://eranosforgood.org/nonprofits"'
        in out["apex"]["body"]
    )
    assert '<link rel="canonical" href="https://eranosforgood.org/"' in out["apexHome"]["body"]
    assert out["preflight"]["status"] != 308 and out["preflight"]["location"] is None
    assert out["local"]["status"] == 200 and out["preview"]["status"] == 200


def test_the_right_now_strip_data_is_kept_at_the_edge_for_a_minute() -> None:
    """The Right now strip's /api/network answer is one edge entry per minute (Herma's summary updates at most once a
    minute): page views in that minute share one Herma read, whatever their query string; an off answer is kept 10 s;
    browsers still ask each time; with no edge cache every read goes to Herma."""
    herma = """({ HERMA: { calls: 0, mode: "ok", async fetch() {
      this.calls += 1;
      if (this.mode === "fail") return new Response("unavailable", { status: 503, headers: { "content-type": "text/plain" } });
      return Response.json({ generated_at: "2026-11-02T15:00:00Z", recent_minutes: 10,
        totals: { workers: 2, continents: 1, claims: 5, nonprofit_claims: 1 },
        recent_claims: [{ at: "2026-11-02T14:58:00Z", kind_label: "Check", model: { name: "Muse Spark", declared: false }, via: { type: "data_centre", city: "Frankfurt", continent: "Europe" } }] });
    } } })"""
    script = (
        WORKER_SCRIPT.replace("WORKER", json.dumps(WORKER.as_uri()))
        .replace("PUBLIC_DIR", json.dumps((ROOT / "web" / "public").as_posix()))
        .replace("INDEX_HTML", json.dumps((ROOT / "web" / "index.html").as_posix()))
        .replace("EXTRA_ENV", herma)
        .replace("REQUESTS", "[]")
        + """
const store = new Map();
const edge = {
  async match(req) { const hit = store.get(new URL(req.url).toString()); return hit ? new Response(hit.text, { headers: hit.headers }) : undefined; },
  async put(req, res) { store.set(new URL(req.url).toString(), { text: await res.text(), headers: Object.fromEntries(res.headers) }); },
};
const get = async (url) => {
  const r = await worker.fetch(new Request(url), env);
  return { status: r.status, cache: r.headers.get("cache-control"), body: await r.text() };
};
const res = {};
globalThis.caches = { default: edge };
res.first = await get("https://eranosforgood.org/api/network");
res.second = await get("https://eranosforgood.org/api/network");
res.query = await get("https://eranosforgood.org/api/network?t=1");
res.callsCached = env.HERMA.calls;
res.stored = [...store.entries()].map(([key, v]) => [key, v.headers["cache-control"]]);
store.clear();
env.HERMA.mode = "fail";
res.off = await get("https://eranosforgood.org/api/network");
res.offAgain = await get("https://eranosforgood.org/api/network");
res.callsOff = env.HERMA.calls;
res.storedOff = [...store.values()].map((v) => v.headers["cache-control"]);
delete globalThis.caches;
env.HERMA.mode = "ok";
await get("https://eranosforgood.org/api/network");
await get("https://eranosforgood.org/api/network");
res.callsUncached = env.HERMA.calls;
console.log(JSON.stringify(res));
"""
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    out = json.loads(run.stdout.strip().splitlines()[-1])
    first = json.loads(out["first"]["body"])
    assert out["first"]["status"] == 200 and first["available"] is True
    assert first["totals"] == {"workers": 2, "continents": 1, "claims": 5, "nonprofit_claims": 1}
    assert out["second"]["body"] == out["first"]["body"] == out["query"]["body"]
    assert out["callsCached"] == 1
    assert out["stored"] == [["https://eranosforgood.org/api/network", "public, max-age=60"]]
    assert {out[name]["cache"] for name in ("first", "second", "query")} == {"private, no-store"}
    assert json.loads(out["off"]["body"]) == {"available": False}
    assert out["offAgain"]["body"] == out["off"]["body"]
    assert out["callsOff"] == 2 and out["storedOff"] == ["public, max-age=10"]
    assert out["callsUncached"] == 4


def test_the_workers_model_shares_are_read_from_their_noun_for_agora() -> None:
    """GET /api/shares answers the workers' live model shares (eranos.instructions/worker.shares, written by their
    hourly tune) for Agora's Models used page, the way /api/models answers models.meta: the noun's value, or null until
    it is written, with the same open CORS as every /api route."""
    shares = json.loads(
        (ROOT / "tests" / "fixtures" / "made-up-worker-shares.json").read_text(encoding="utf-8")
    )
    db = (
        "({ FABRIC_DB: { prepare() { return { bind(store, key) { return { async first() { "
        "return store === 'eranos.instructions' && key === 'worker.shares' ? { value: "
        + json.dumps(json.dumps(shares))
        + " } : null; } }; } }; } } })"
    )
    written = _worker([("shares", "GET", "/api/shares", None)], db)["shares"]
    assert written["status"] == 200 and written["type"].startswith("application/json")
    assert written["cors"] == "*"
    assert json.loads(written["body"]) == {
        "store": "eranos.instructions",
        "key": "worker.shares",
        "shares": shares,
    }
    empty_db = "({ FABRIC_DB: { prepare() { return { bind() { return { async first() { return null; } }; } }; } } })"
    for env in (empty_db, "({})"):
        unwritten = _worker([("shares", "GET", "/api/shares", None)], env)["shares"]
        assert unwritten["status"] == 200
        assert json.loads(unwritten["body"]) == {
            "store": "eranos.instructions",
            "key": "worker.shares",
            "shares": None,
        }
    card = json.loads(
        _worker([("card", "GET", "/.well-known/agent-card.json", None)])["card"]["body"]
    )
    assert card["endpoints"]["shares"] == "/api/shares"


def test_page_text_comes_from_the_deploy_not_an_older_copy_in_tessera() -> None:
    """The 9fd6e09 rollback (Nov 2): Tessera's mirror held older page-text nouns, so new pages met old words and
    /library crashed. Page text (eranos.instructions) now ships with the deploy and wins over the mirror."""
    old_library = json.dumps({"heading": "Shared library", "tabs": {"all": "All"}})
    fake_db = (
        "({ FABRIC_DB: { prepare() { return { bind() { return { first: async () => ({ value: "
        + json.dumps(old_library)
        + " }), all: async () => ({ results: [] }) }; } }; } } })"
    )
    out = _worker(
        [("library", "GET", "/api/nouns/eranos.instructions/library", None)],
        extra_env=fake_db,
    )
    body = json.loads(out["library"]["body"])
    assert body["value"]["heading"] == "Find a solution" and "tries" in body["value"]


DISPLAY_SCRIPT = r"""
import { makeNeutral } from DISPLAY;
import { displayRules } from LISTER;
import fs from "node:fs";

const list = JSON.parse(fs.readFileSync(FIXTURE_LIST, "utf8"));
const neutral = JSON.parse(fs.readFileSync(FIXTURE_NEUTRAL, "utf8"));
const show = makeNeutral({ displayRules: displayRules(list, neutral) });
const cases = ["a quibbit and two Quibbits", "Zorblat rows go here", "the flumox step", "quibbit", "no listed word here"];
const once = cases.map(show);
console.log(JSON.stringify({ once, twice: once.map(show) }));
"""


def test_the_page_word_filter_shows_plain_words_in_prose_and_leaves_ids_alone() -> None:
    """Rule 16 at display time, with made-up words (the real list lives outside this repo)."""
    fixtures = ROOT / "tests" / "fixtures"
    script = (
        DISPLAY_SCRIPT.replace(
            "DISPLAY", json.dumps((ROOT / "deploy" / "cloudflare" / "display_words.js").as_uri())
        )
        .replace("LISTER", json.dumps((ROOT / "scripts" / "banned_list.mjs").as_uri()))
        .replace("FIXTURE_LIST", json.dumps((fixtures / "made-up-banned-words.json").as_posix()))
        .replace(
            "FIXTURE_NEUTRAL", json.dumps((fixtures / "made-up-neutral-words.json").as_posix())
        )
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True
    )
    out = json.loads(run.stdout)
    assert out["once"] == [
        "a record and two Records",
        "Example rows go here",
        "the … step",
        "quibbit",
        "no listed word here",
    ]
    assert out["twice"] == out["once"]


PAGE_VIEW_SCRIPT = r"""
import fs from "node:fs";
import path from "node:path";
import worker from WORKER;
import list from GENERATED;
import { makeNeutral } from DISPLAY;

const publicDir = PUBLIC_DIR;
const env = {
  ASSETS: {
    async fetch(req) {
      const url = new URL(typeof req === "string" ? req : req.url);
      const target = path.join(publicDir, url.pathname.replace(/^\//, ""));
      if (fs.existsSync(target) && fs.statSync(target).isFile()) {
        return new Response(fs.readFileSync(target), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response("<!doctype html><title>Eranos</title>", { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
    },
  },
};
const read = async (pathname, headers = {}) => {
  const response = await worker.fetch(new Request("https://eranosforgood.org" + pathname, { headers }), env);
  return { status: response.status, cache: response.headers.get("cache-control") || "", body: await response.text() };
};
const rules = (list.displayRules || []).map((rule) => new RegExp(rule.re, rule.flags.includes("g") ? rule.flags : rule.flags + "g"));
const hits = (text) => rules.reduce((n, re) => n + (String(text).match(re) || []).length, 0);
const raw = await read("/api/catalog/KIT-GRANT-04");
const byQuery = await read("/api/catalog/KIT-GRANT-04?view=page");
const byHeader = await read("/api/catalog/KIT-GRANT-04", { "x-eranos-view": "page" });
const summary = (r) => { const d = JSON.parse(r.body); return (d.kit || d.value?.kit || {}).summary; };
const page = await read("/library", { accept: "text/html" });
console.log(JSON.stringify({
  statuses: [raw.status, byQuery.status, byHeader.status],
  raw: summary(raw), query: summary(byQuery), header: summary(byHeader),
  hits: { raw: hits(summary(raw)), query: hits(summary(byQuery)), header: hits(summary(byHeader)) },
  html_cache: page.cache, api_cache: raw.cache,
}));
"""


def test_pages_read_stored_records_in_plain_words_and_the_records_stay_as_stored() -> None:
    """A page's read passes the shared list (rule 16); the record itself, read without it, is exactly as stored."""
    generated = ROOT / "deploy" / "cloudflare" / "banned_words.generated.js"
    assert generated.is_file(), "run node scripts/banned_list.mjs --ensure (make test does)"
    script = (
        PAGE_VIEW_SCRIPT.replace("WORKER", json.dumps(WORKER.as_uri()))
        .replace("GENERATED", json.dumps(generated.as_uri()))
        .replace(
            "DISPLAY", json.dumps((ROOT / "deploy" / "cloudflare" / "display_words.js").as_uri())
        )
        .replace("PUBLIC_DIR", json.dumps((ROOT / "web" / "public").as_posix()))
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True
    )
    out = json.loads(run.stdout.strip().splitlines()[-1])
    stored = json.loads(
        (ROOT / "web" / "public" / "snapshot" / "catalog" / "KIT-GRANT-04.json").read_text(
            encoding="utf-8"
        )
    )
    assert out["statuses"] == [200, 200, 200]
    assert out["raw"] == stored["kit"]["summary"]
    assert out["hits"]["query"] == out["hits"]["header"] == 0
    assert out["query"] == out["header"]
    if out["hits"]["raw"]:
        assert out["query"] != out["raw"]
    # Cloudflare's zone adds nothing to an HTML page that says no-transform (its analytics script would hit the CSP).
    assert "no-transform" in out["html_cache"]
    assert "no-transform" not in out["api_cache"]


PAGE_TEXT_SCAN = r"""
import fs from "node:fs";
const loaded = await import(__GENERATED__);
const config = Array.isArray(loaded.default?.checks) ? loaded.default : loaded.default?.default;
const checks = (config?.checks ?? []).map((c, i) => ({ ...c, i, rx: new RegExp(c.re, c.flags.includes("m") ? c.flags : c.flags + "m") }));
const CODE_KEYS = new Set(__CODE__);
const out = [];
for (const file of __FILES__) {
  const walk = (value, path) => {
    if (typeof value === "string") {
      for (const c of checks) if (c.rx.test(value)) out.push(`${file}${path}: ${c.group} #${c.i}`);
    } else if (Array.isArray(value)) value.forEach((v, i) => walk(v, `${path}[${i}]`));
    else if (value && typeof value === "object") {
      for (const [k, v] of Object.entries(value)) {
        if (CODE_KEYS.has(k) || /_(href|url|to|id|sha256)$/.test(k)) continue;
        walk(v, `${path}.${k}`);
      }
    }
  };
  walk(JSON.parse(fs.readFileSync(file, "utf8")), "");
}
console.log(JSON.stringify({ checks: checks.length, out }));
"""


def test_the_page_text_passes_the_shared_word_list() -> None:
    """Rule 16 at the source: every visible string of the page text the site ships passes the ONE shared list (read from
    outside the repo through the generated module; code fields such as API examples are allowed by the list)."""
    generated = ROOT / "deploy" / "cloudflare" / "banned_words.generated.js"
    assert generated.is_file(), "run node scripts/banned_list.mjs --ensure (make test does)"
    nouns = [
        "agent-banner",
        "connect",
        "help-page",
        "home",
        "library",
        "llms",
        "nonprofits-page",
        "nonprofits",
    ]
    nouns += ["request-status", "shell", "site", "trust"]
    files = [(ROOT / "instructions" / f"{name}.json").as_posix() for name in nouns]
    code = [
        "example",
        "command",
        "state",
        "type",
        "href",
        "to",
        "url",
        "match",
        "key",
        "kind",
        "store",
        "schema",
    ]
    code += ["receipt", "ref", "id", "spec", "path"]
    script = (
        PAGE_TEXT_SCAN.replace("__GENERATED__", json.dumps(generated.as_uri()))
        .replace("__FILES__", json.dumps(files))
        .replace("__CODE__", json.dumps(code))
    )
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True
    )
    out = json.loads(run.stdout)
    assert out["checks"] > 0, "the word list module has no checks"
    assert out["out"] == []


def test_the_worker_checked_reuse_facts_pass_the_status_schema() -> None:
    """F-REUSE-001 (worker-loop-next 6684c6c): the worker writes a checked reuse as planned (part 1, route reuse_check),
    check_claimed, reuse_checked, a reused delivered and closed; every fact, as a version of the request noun, must pass
    docs/status-events.schema.json, which the worker validates against before writing."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "docs" / "status-events.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    request_id = "rq-r_" + "ef" * 16 + "-mvywfy1j"
    report = "RPT-RC676414-01"
    worker = {"worker": "dedicated worker 1 (run by ta-amps)", "dedicated": True}
    checker = {"worker": "dedicated worker 3 (run by ta-amps)", "dedicated": True}
    facts: list[dict[str, Any]] = [
        {
            "type": "planned",
            "receipt": "b" * 64,
            **worker,
            "parts": [
                {
                    "part": 1,
                    "route": "reuse_check",
                    "text": "What are the key food-safety rules for a community food pantry?",
                    "reused_from": {"report_id": report},
                    "review_task_id": "t-reuse-review-1",
                }
            ],
        },
        {
            "type": "check_claimed",
            "part": 1,
            "receipt": "1" * 64,
            **checker,
            "model": "muse-spark-1.3",
        },
        {
            "type": "reuse_checked",
            "part": 1,
            "receipt": "2" * 64,
            "verdict": "fits",
            "checker_role": "dedicated worker 3 (run by ta-amps)",
            "model": "muse-spark-1.3",
            "model_name": "Muse Spark 1.3",
            "similarity": 0.83,
            "ref": f"eranos.solutions/{report}",
        },
        {
            "type": "delivered",
            "part": 1,
            "ref": f"eranos.solutions/{report}",
            "result_id": report,
            "summary": {"reused": True, "score": 0.83},
            **worker,
        },
        {
            "type": "plan_claimed",
            "receipt": "3" * 64,
            **worker,
            "method": "deterministic planner (no model)",
        },
        {"type": "closed", "receipt": "4" * 64, **worker},
    ]
    for index, event in enumerate(facts):
        value = {
            "schema_version": 1,
            "request_id": request_id,
            "status": "closed" if event["type"] == "closed" else "open_for_build",
            "event": {"at": 1_793_602_200 + index, **event},
        }
        errors = [error.message for error in validator.iter_errors(value)]
        assert errors == [], (event["type"], errors)
    # A does-not-fit verdict passes too, and a wrong verdict does not.
    rejected = {**facts[2], "verdict": "does_not_fit"}
    wrong = {**facts[2], "verdict": "maybe"}
    base = {"schema_version": 1, "request_id": request_id, "status": "open_for_build"}
    assert not list(validator.iter_errors({**base, "event": {"at": 1, **rejected}}))
    assert list(validator.iter_errors({**base, "event": {"at": 1, **wrong}}))
