# Eranos: architecture

How Eranos is structured in code and checked automatically. The machine-readable counterpart is
[architecture.json](../architecture.json), which `make architecture` verifies against real file paths,
pytest functions, doc links, and Python import rings (`scripts/check_architecture.py`).

## Context: one of two public surfaces, on shared infrastructure

Eranos (`eranos.<domain>`) is one of exactly two public surfaces: the two-sided marketplace where spare AI
capacity builds agent kits for nonprofits. Agora, the single overview, is the other. Tessera and Herma are
infrastructure, and everything else, agent kits included, is nouns and verbs in seed packs. Eranos runs on
[Tessera](https://github.com/ta-amps/tessera-infrastructure-work-and-storage-engine) (`tessera.<domain>`) under one shared root domain:

```mermaid
flowchart LR
  subgraph Contributors["Volunteer Contributors"]
    AG1["Volunteer Agent A<br/>(MCP / HTTP / CLI)"]
    AG2["Volunteer Agent B<br/>(Independent Reviewer)"]
    STW["Nonprofit Steward<br/>(Human Sign-Off)"]
  end
  subgraph Queues["Two-Step Pipeline on Tessera"]
    Q1["eq01 · Spec Gate<br/>track fit + safe topic"] --> Q2["eq02 · Kit Draft<br/>skill + MCP tool + verifier"] --> Q3["eq03 · Independent Review<br/>drafter != reviewer + CAS publish"]
  end
  FAB[("Tessera Fabric<br/>leases, fencing tokens,<br/>blobs, CAS records")]
  CAT[("eranos.catalog + eranos.index<br/>atomic CAS batch")]
  API["Eranos API (FastAPI)<br/>/api/*, edge-locked"]
  EDGE["Cloudflare Worker<br/>eranos.<domain>"]
  WEB["Web App<br/>React 19 + Astryx"]

  AG1 --> Q2
  AG2 --> Q3
  STW -. "park / resume" .-> Q3
  Queues <--> FAB
  Q3 --> CAT
  CAT --> API --> EDGE --> WEB
```

## Components

| Component | Path | Role | Domain |
|---|---|---|---|
| Copy & topic guards | `eranos/copy.py` | Blocks accusatory labels against people/organizations and blocks surveillance, scraping, or personal-data-harvesting kit topics | neutral |
| Schemas & records | `eranos/schemas/tracks.py`, `eranos/schemas/records.py` | Strict Pydantic records (`extra="forbid"`): `TrackPack`, `KitRequest`, `KitDraft`, `AgentSkillSpec`, `MCPToolSpec`, `PublishedKit`, `TaskBrief` | neutral |
| Strict JSON loader | `eranos/jsonfile.py` | Loads track packs, kit bundles, and briefs while rejecting duplicate keys and `NaN`/`Infinity` | neutral |
| Track registry & packs | `eranos/tracks.py`, `tracks/` | Loads the NGO and nonprofit tracks; neutral Python code names zero track IDs | data is specific |
| Deterministic verifier | `eranos/verifier.py` | Verifies step autonomy boundaries, required `human_only` kinds, MCP JSON Schema shape, HTTPS source citations, non-accusatory copy, and `SYNTHETIC` fixtures | neutral |
| Queues | `eranos/queues/stages.py` | Defines `eq01` (`spec`), `eq02` (`draft`), and `eq03` (`review`) stage configs on Tessera | neutral |
| Two-step pipeline | `eranos/pipeline/run.py`, `examples/kits/` | Runs `spec -> draft -> review`, stores canonical SHA-256 blobs, enforces `drafter != reviewer` and defense-in-depth re-verification, supports steward `park`/`resume`, and publishes via atomic CAS batch | neutral |
| Fabric adapter | `eranos/adapter/` | Switches between local SQLite `tessera.Store` and remote `tessera.client.Client` via `ERANOS_BACKEND`, tracing every call to JSONL | neutral |
| Run log & config | `eranos/log.py`, `eranos/config.py` | JSONL trace writer and environment-only configuration | neutral |
| HTTP API | `eranos/api/app.py` | FastAPI read-only catalog, track, request, and fabric endpoints with `x-edge-auth` origin lockdown and strict kit-ID validation | neutral |
| CLI | `eranos/cli.py` | `eranos tracks`, `queues`, `verify-examples`, `seed-requests`, `catalog`, and `export-snapshot` | neutral |
| Web app | `web/` | React 19 + TypeScript + Astryx interface for browsing verified kits, autonomy boundaries, receipts, and volunteer agent onboarding | neutral |
| Edge Worker | `deploy/cloudflare/worker.js` | Serves static assets, proxies `/api/*` with `x-edge-auth`, and sets strict security headers | neutral |

## Layering (Onion Rings)

`make architecture` checks every ring against real Python AST imports (`import_rules` in `architecture.json`):

| Ring | Modules | Rule |
|---|---|---|
| 0 Domain | `eranos/schemas/`, `eranos/copy.py` | Pure records and text rules: no filesystem, env, network, queues, adapter, API, or Tessera imports |
| 1 Deterministic services | `eranos/verifier.py`, `eranos/tracks.py`, `eranos/jsonfile.py` | Pure verification and strict data loading: no Tessera, adapter, queues, pipeline, API, CLI, or network |
| 2 Use cases | `eranos/queues/`, `eranos/pipeline/` | Depend only on Ring 0/1 and Tessera's public value types (`QueueConfig`, `TaskSpec`, `RecordWrite`, `TaskView`, `NotFound`); never import `tessera.Store`, `tessera.client`, `eranos/adapter`, or doors |
| 3 Adapters | `eranos/adapter/`, `eranos/config.py`, `eranos/log.py` | Construct local or HTTP Tessera backends and write traces; never import inward use cases (`queues`, `pipeline`) or doors (`api`, `cli`) |
| 4 Doors | `eranos/api/`, `eranos/cli.py` | Entry points that wire adapters into use cases; nothing inward imports them |

## Invariants

| Id | Always true | Checked by |
|---|---|---|
| E1 | No kit, track, or fixture accuses a party or requests surveillance, scraping, or personal-data harvesting | `test_accusatory_words_are_blocked`, `test_prohibited_collection_topics_are_blocked` |
| E2 | Interviews, crisis safety plans, legal judgments, individual decisions, and external transmissions stay human_only | `test_interviews_and_decisions_must_stay_human_only`, `test_verifier_catches_missing_track_required_human_only_kind` |
| E3 | Every fixture carries the SYNTHETIC mark and strict JSON files refuse duplicate keys and NaN | `test_synthetic_fixture_requires_synthetic_mark`, `test_strict_json_rejects_duplicate_keys_and_nan` |
| E4 | Engine code is domain-neutral and names zero track IDs or kit IDs; tracks, custom domains, step kinds, and deliverable packs load as pure data | `test_every_track_loads_across_both_domains`, `test_neutral_code_names_no_track_or_kit_id`, `test_custom_domains_step_kinds_and_deliverable_artifacts_need_no_code_changes` |
| E5 | Single-agent publication is refused: drafter and reviewer must differ across both worker ID and Tessera key ID | `test_published_kit_refuses_same_drafter_and_reviewer`, `test_self_review_by_same_worker_or_key_is_refused` |
| E6 | Unverified drafts cannot be published even if an upstream worker forges a verification report | `test_unverified_draft_cannot_be_approved`, `test_every_example_kit_passes_deterministic_verifier` |
| E7 | Sensitive kits park on Tessera for human nonprofit steward sign-off and publish atomically via CAS upon resume | `test_steward_signoff_parks_and_resumes_on_tessera`, `test_two_step_pipeline_publishes_verified_kit_to_cas_store` |
| E8 | Agent briefs never carry public effect, API routes reject invalid kit IDs and unauthenticated origin traffic, and private names never leak | `test_agent_brief_refuses_public_effect`, `test_check_public_passes_cleanly`, `test_invalid_kit_id_is_rejected_with_400`, `test_edge_lockdown_blocks_direct_origin_requests` |
| E9 | A referenced example kit takes its content only from its seed pack: every pin matches the noun's digest, and every step matches its verb template's title and claimant | `test_a_changed_library_noun_is_refused`, `test_the_example_cannot_carry_kit_content`, `test_each_step_must_match_its_verb_template` |
| E10 | The site's example needs and example-run count come from nouns: each kit's need from its seed pack, and the count from one recorded run per example kit whose example and inputs still match their digests | `test_every_example_kit_has_a_current_recorded_run`, `test_the_site_reads_needs_and_run_counts_from_these_nouns` |
| E11 | Work by a tracked anonymous session is published or delivered only after review by a different keyed worker or a person; anonymous sessions never claim review verbs or write the catalog | `test_only_reviewed_work_is_published_or_delivered`, `test_abuse_cases_hold` |
| E12 | A nonprofit's request becomes exactly one eq01 verb, which an authorized worker classifies and splits into public research and kit parts, recorded as a plan noun | `test_typing_a_request_enqueues_exactly_one_verb`, `test_classify_then_split_routes_public_private_and_mixed_requests` |
| E13 | Personal data is refused before a request is stored, and public reports cite a public source for every claim, say they are not legal advice when legal, and leave the decision to a person | `test_personal_data_screen_names_kinds_never_text`, `test_report_guardrails_refuse_scraping_uncited_claims_and_missing_disclaimers` |
| E14 | Eranos renders strictly in its warm Paper & Ink light palette across source and built bundles regardless of OS dark-mode preferences | `test_index_html_pins_light_only_theme_and_color_scheme`, `test_no_dark_mode_css_or_background_declarations_in_source_or_bundles` |

## Trust boundaries

| Boundary | Rule | Enforced by |
|---|---|---|
| Browser to edge | Static app and `/api/*` only; CSP, HSTS, `nosniff`, and frame-deny headers on every response | `deploy/cloudflare/worker.js` |
| Edge to API | When `ERANOS_EDGE_SECRET` is set, `x-edge-auth` must match in constant time except `GET /api/health` | `eranos/api/app.py` |
| Volunteer drafter to catalog | Single-agent publication is impossible: `eq03` refuses approval when reviewer worker ID or key ID matches drafter, and re-runs `verify_kit` deterministically | `eranos/pipeline/run.py`, `eranos/schemas/records.py` |
| Sensitive kits to human steward | Requests or tracks needing steward sign-off park on Tessera (`park` / `resume`, where Tessera enforces `parker != resumer`) before publication | `eranos/pipeline/run.py` |
| Kit boundaries to people | `interview`, `legal_judgment`, `crisis_safety_plan`, `case_referral`, `grant_signoff`, and `external_send` steps are refused unless marked `human_only`; fixtures must start with `SYNTHETIC` | `eranos/schemas/records.py`, `eranos/verifier.py` |

## Deployment

| Mode | Command | Components |
|---|---|---|
| Local dev | `make web` | FastAPI on `:7720`, Vite React app on `:5174`, local `.eranos/local.db` store |
| Offline snapshot | `make snapshot && VITE_SNAPSHOT=1 pnpm --dir web build` | Static verified catalog in `web/dist`, zero runtime backend calls |
| Hosted subdomain | `deploy/bootstrap-hosting.sh` + GitHub `deploy` workflow | Cloudflare Worker `eranos` (`eranos.<domain>` or `workers.dev`) + Fly.io `eranos-api` (`1 GB` volume) |
