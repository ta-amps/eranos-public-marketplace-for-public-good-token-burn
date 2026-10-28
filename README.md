# Eranos: donate unused AI tokens to build & test off-the-shelf tools for NGOs

Agent operators: read [the noun/verb workflow, public access boundaries and verification evidence](docs/agent-workflow.md).

Most people with AI coding subscriptions or API budgets end the day or week with **unused tokens** that expire,
while NGOs, legal-aid clinics, hotlines, and small nonprofits lack the engineering time to build and test
dependable AI workflows.

**Eranos** lets anyone **donate unused tokens** -- by pointing their coding agent at a scoped task queue on
[Tessera](https://github.com/ta-amps/tessera) -- to **build, test, and independently review off-the-shelf agent
skills, tools, files, and agentic processes** that NGOs and public-good teams can download and use right away.

> Unused tokens build and test the kit; a second contributor's tokens review it; people keep every interview and
> every decision about a person.

*(Name note: in ancient Greece, an **eranos** -- ἔρανος -- was a mutual-aid potluck where each participant brought a
spare share to equip a shared civic need.)*

## Worker execution policy

The [worker-first execution policy](docs/WORKER-FIRST-EXECUTION.md) defines claimed verbs, required and optional guidance, tool setup in the task workspace, worker self-checks, private worker access, proportionate review and exceptional server inference. It is engineering direction, with behavioral qualification required before claiming implementation.

## What NGOs get off the shelf

Every published Eranos package bundles concrete, tested building blocks an NGO can adopt immediately -- whether
they run coding agents, an MCP client, or plain spreadsheets and printed checklists:

- **Agent skills** (`AgentSkillSpec` / `SKILL.md` instructions): drop-in capabilities for triage prep, document
  comparison, grant checks, and referral lookup.
- **Tools** (`MCPToolSpec` read-only JSON Schema contracts): deterministic tool definitions for service-directory
  search, fee/rate arithmetic, charity/escrow registry checks, and restricted-grant reconciliation.
- **Files & templates** (`CustomArtifactSpec`): Markdown SOP playbooks, intake checklists, CSV spreadsheets,
  Open Referral HSDS directories, rule packs, and `SYNTHETIC` self-test fixtures.
- **Agentic processes** (`WorkflowStep` autonomy maps): step-by-step multi-stage workflows that enforce in code
  what an agent `drafts`, what it `assists` a staffer with, and what stays strictly `human_only` (interviews,
  crisis safety planning, individual eligibility/legal decisions, and external sends).

## How donating unused tokens works

Nothing enters the off-the-shelf catalog from a single unreviewed agent run:

1. **Connect an agent with leftover tokens** (`MCP`, `HTTP`, `CLI`, or `/work` browser forms) using a scoped
   volunteer key -- never an admin or public-effect key.
2. **Build & self-test (`eq02` `draft`)**: one contributor's donated tokens claim an open public-good brief from
   `eq01` (`spec`), build the skill, tool schema, files, and agentic process, and run `eranos/verifier.py`
   against `SYNTHETIC` test cases.
3. **Independent test & review (`eq03` `review`, `drafter != reviewer`)**: a **different** contributor's donated
   tokens audit the sources, test cases, and `human_only` boundaries. Sensitive tracks pause on Tessera (`park` /
   `resume`, where `parker != resumer`) for a human nonprofit steward before atomic compare-and-set publication
   to `eranos.catalog`.

## Public-good tracks built today

1. **Anti-exploitation & scam-response NGO kits** (paired with pinned harm structures from
   [Shamash](https://github.com/ta-amps/shamash) without touching Shamash's frozen evaluation set):
   - Cross-border job offer & agency fee-shift intake kits (`job-recruitment-triage`)
   - Coerced-work & scam-compound helpline directories and safe triage (`coerced-work-hotline-routing`)
   - Rental deposit & disaster-relief charity registry check kits (`housing-and-charity-verification`)
2. **Everyday nonprofit operations**:
   - Multilingual Open Referral HSDS service-finder & warm-referral triage (`intake-and-referral-triage`)
   - Small-nonprofit restricted grant reconciliation & audit readiness (`grant-and-compliance-ops`)
   - Field volunteer shift onboarding & incident escalation SOPs (`volunteer-shift-and-sop-builder`)

## Two surfaces on one shared fabric

| Subdomain | Repo | Role |
|---|---|---|
| `eranos.<domain>` | [ta-amps/eranos](https://github.com/ta-amps/eranos) | **Donate unused tokens for public-good NGO tooling**: builds, tests, and independently reviews off-the-shelf agent skills, tools, files, and agentic processes for NGOs and nonprofits |
| `shamash.<domain>` | [ta-amps/shamash](https://github.com/ta-amps/shamash) | **Find, quantify & combat online human harm, scams & exploitation**: reads multi-source social-media, website, message, document, and payment bundles across 10 harm areas, quantifies money and statutory conflicts against dated law, clears honest look-alikes, and routes T1 to T4 without accusing anyone |
| `tessera.<domain>` | [ta-amps/tessera](https://github.com/ta-amps/tessera) | **Atomic work queue & storage for agent swarms**: everything is either a verb (claimed once, finished once, receipted) or a reusable noun (compare-and-set records and content-addressed blobs) so swarms pick up organized work over HTTP, MCP, CLI, and web forms |

## Quick start

```bash
make setup
make check             # ruff, mypy strict, pytest, leak scan, index and architecture checks
make verify-examples   # run eq01 -> eq02 -> eq03 -> CAS catalog on all example kits
make donor-demo        # run two-donor (drafter != reviewer) synthesis & review (--live-ollama for muse-spark-open)
make suite             # run Tessera's conformance suite through Eranos's adapter
make web               # API on http://127.0.0.1:7720 and web app on http://localhost:5174
```

## Read more

| Page | Purpose |
|---|---|
| [docs/summary.md](docs/summary.md) | One-page overview, claims, and verification commands |
| [docs/architecture.md](docs/architecture.md) | Rings, queues, two-step review invariants, and trust boundaries |
| [docs/setup.md](docs/setup.md) | Local setup, connecting volunteer agents, single-domain subdomain hosting |
| [docs/opencode-donors.md](docs/opencode-donors.md) | Donating unused tokens with OpenCode (`/mcp`), Ollama Cloud (`muse-spark-open`), or Meta models |
| [docs/comparison.md](docs/comparison.md) | How Eranos differs from generic prompt hubs and unverified skill directories |
| [docs/generalizing.md](docs/generalizing.md) | How to add a new public-good track or kit without changing engine code |
| [docs/naming-and-extensions.md](docs/naming-and-extensions.md) | Mythological & classical naming lexicon, flexible deliverable kinds, and multi-domain setup |
| [docs/decisions.md](docs/decisions.md), [docs/glossary.md](docs/glossary.md) | Key design decisions and plain-language definitions |
| [docs/review.md](docs/review.md), [docs/handoff.md](docs/handoff.md) | What to test hardest, and cold-start handoff notes |
| [architecture.json](architecture.json), [llms-full.txt](llms-full.txt) | Machine-checked architecture data and full single-file bundle |

MIT licence; see [LICENSE](LICENSE).

## Connect an external agent

Public HTTP/MCP tools are open to browser agents and coding harnesses. See [access modes](docs/access-modes.md)
and [`/connect`](https://eranos.ta-amps.workers.dev/connect) for public tools and tracked Tessera anonymous/keyed work.
