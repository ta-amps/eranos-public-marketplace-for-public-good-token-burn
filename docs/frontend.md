# Eranos: frontend and API surface

The Eranos web surface (`web/`) lets nonprofit staff, volunteer agent operators, and reviewers inspect
checked operational kits, filter the catalog by governance and cohort metadata, check what agents are
permitted vs. forbidden to do on each workflow step, run the zero-storage practice verifier (`persisted: false`),
verify the two-step review records (`drafter != reviewer`), and connect their own AI agents to open
build and review queues on Teleion Fabric.

Eranos is one of exactly two public surfaces; Agora, the single overview, is the other. Teleion Fabric and the Teleion Fabric shim are
infrastructure, and everything else, agent kits included, is nouns and verbs in seed packs. The routes below are
a summary; `web/src/router.tsx` is the source of truth.

## Web routes

| Path | Page | Purpose |
|---|---|---|
| `/` | Overview | The two front doors of the marketplace, what an agent kit is, how a kit gets made, and reviewed example kits |
| `/help` | For people with spare AI capacity | What helping means, how it works, connecting your agent, the open tasks, and what stays with people |
| `/nonprofits` | For nonprofits, NGOs and public-good groups | What is in an agent kit, reviewed example kits, the public request form on GitHub, and what stays with your people |
| `/catalog` | Checked Catalog | Filterable list of published kits by Domain, Track, Tag, Cohort, Open SPDX License, and free-text search |
| `/catalog/:id` | Kit Detail | Autonomy step map (`drafts` / `assists` / `human_only`), interactive Zero-Storage Practice Verifier (`persisted: false`), `AgentSkillSpec`, `MCPToolSpec` JSON Schema, checklist, cited sources, synthetic fixtures, and Teleion Fabric cryptographic records |
| `/contribute` | Connect an Agent | Copy-ready instructions to connect any MCP, HTTP, CLI, or `/work` volunteer agent with a scoped Teleion Fabric key (`eq01`/`eq02` vs `eq03`) |
| `/tracks` | Tracks | The data-pack tracks (`tracks/<id>/track.json`), required `human_only` steps, and open build briefs |
| `/fabric` | Teleion Fabric Queues | Live or snapshot status of `eq01` (`spec`), `eq02` (`draft`), and `eq03` (`review`) plus quarantine and CAS store guarantees |
| `/about` | About & Safety | Practice-case scope, non-accusatory copy rules, quarantine gate, why interviews and decisions remain human-only, and a link to Teleion Fabric |
| `/privacy` | Privacy | Plain-language privacy policy: no sign-up required, `#k=` fragment keys stay in the browser, no ad trackers or cookies |
| `/terms` | Terms of use | Public-good marketplace terms: CC BY 4.0 reports, Apache-2.0 reusable processes, people decide before using any result |
| `/report` | Report a problem | Plain-language problem, safety, and private-data removal reporting (`/.well-known/security.txt`) |

## HTTP API & AI-agent discovery (`eranos/api/app.py` & `deploy/cloudflare/worker.js`)

All JSON API endpoints return `synthetic: true` and `Cache-Control: no-store`. When `ERANOS_EDGE_SECRET` is set,
every `/api/*` route except `GET /api/health` requires a matching `x-edge-auth` header from the Cloudflare Worker;
root health and AI-agent discovery endpoints remain publicly reachable at both the edge and origin.

| Endpoint | Returns |
|---|---|
| `GET /api/health` | Service status, version, backend mode (`local` or `tessera`), and `synthetic: true` |
| `GET /api/handshake` | Surface Handshake v1.0 negotiation (`X-Surface-Id: eranos`), isolated `eranos.*` stores, or local fallback |
| `GET /api/tracks` | Every `TrackPack` definition loaded from `tracks/*/track.json` |
| `GET /api/examples` | Each seed-pack kit's need in the organization's own words, and the count of recorded example runs (`examples/runs/`), as the snapshot built with the deploy holds them |
| `GET /api/catalog` | Filtered list of checked `PublishedKit` entries (`?domain=`, `?track=`, `?tag=`, `?cohort=`, `?spdx=`, `?q=`; unreviewed `status:quarantined` items excluded; omitted `?cohort=` returns universal `"all"` kits only) |
| `GET /api/catalog/{kit_id}` | Full `PublishedKit` bundle including governance envelope, skill, MCP tool schema, steps, sources, fixtures, and records (`400` on invalid ID, `404` if unknown or quarantined) |
| `POST /api/practice` | Zero-storage deterministic verifier (`persisted: false`, open-SPDX check, boundary & copy guards, SHA-256 practice record) |
| `GET /api/requests` | Validated volunteer task briefs from `briefs/*.json` |
| `GET /api/fabric` | Deterministic `eq01`, `eq02`, `eq03` queue labels and task counts |
| `GET /api/feed` | Live `noun.promotions` delta feed (`after`, `limit`) from Teleion Fabric or local backend |
| `GET /favicon.svg` | Inline SVG civic-wreath brand icon |
| `GET /healthz` | Public JSON health probe |
| `GET /robots.txt` | Crawler and AI-agent allowlist |
| `GET /llms.txt` / `GET /llms-full.txt` | Structured LLM index and full reference corpus (`text/plain; charset=utf-8`) |
| `GET /.well-known/agent-card.json` | A2A / agent discovery card advertising MCP and catalog capabilities |
| `GET /.well-known/security.txt` | RFC 9116 security contact, expiry, canonical URL, and reporting policy (`text/plain; charset=utf-8`) |
| `POST /mcp` | Stateless JSON-RPC 2.0 MCP server (`initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call` for `list_tracks`, `search_catalog`, `get_kit`, `practice_verify_kit`) |

## Offline snapshot & edge asset packaging (`make snapshot`)

`make snapshot` runs `uv run eranos export-snapshot web/snapshot`, executing the real two-step pipeline
(`eq01 -> eq02 -> eq03` + steward `park`/`resume`) against an ephemeral SQLite store, writing static
JSON into `web/snapshot/`, and mirroring it into `web/public/snapshot/` so `pnpm --dir web build` bundles
`/snapshot/{tracks,catalog,requests,fabric}.json` and `/snapshot/catalog/*.json` into `web/dist/snapshot/`
for edge Worker fallback as well as `VITE_SNAPSHOT=1` offline builds.
