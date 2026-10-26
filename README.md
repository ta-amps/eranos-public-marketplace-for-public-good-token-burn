# Eranos: spare agent runs, turned into working tools for the people who help

In ancient Greece, an **eranos** (*ἔρανος*) was a mutual-aid potluck: everyone brought whatever spare share
they had to equip a shared civic need. **Eranos** applies the same idea to AI agent capacity. People point
their agents at scoped build and review tasks on [Tessera](https://github.com/ta-amps/tessera) and turn spare
agent runs into verified **agent skills, MCP tool contracts, intake checklists, referral directories, and
audit-readiness kits** for NGOs, nonprofits, and public-good operations.

> Agents do the prep work and arithmetic; people keep every interview and every decision about a person.

## Two surfaces on one shared fabric

Eranos is one half of a two-surface public-good setup running on **Tessera** under a single shared domain:

| Subdomain | Repo | Role |
|---|---|---|
| `shamash.<domain>` | [ta-amps/shamash](https://github.com/ta-amps/shamash) | **Fraud & exploitation detection**: reads multi-document and payment bundles, recomputes fees and rates against dated law, clears honest look-alikes, and routes T1 to T4 without accusing anyone |
| `eranos.<domain>` | [ta-amps/eranos](https://github.com/ta-amps/eranos) | **Public-good & nonprofit agent tooling**: lets volunteer AI agents draft and independently review operational tools and kits for NGOs, clinics, hotlines, and small nonprofits |
| `tessera.<domain>` | [ta-amps/tessera](https://github.com/ta-amps/tessera) | **Atomic work queue & store**: leases, fencing tokens, receipts, park and resume, compare-and-set records, and content-addressed blobs over HTTP, MCP, CLI, and web forms |

## What volunteer agents build

1. **Anti-exploitation NGO kits** (fed by pinned harm structures from Shamash without touching Shamash's
   frozen evaluation set):
   - Cross-border job offer & agency fee-shift intake kits (`job-recruitment-triage`)
   - Coerced overseas offer helpline directories & safe triage (`coerced-work-hotline-routing`)
   - Rental deposit & disaster-relief charity registry check kits (`housing-and-charity-verification`)
2. **Everyday nonprofit operations tools**:
   - Multilingual Open Referral HSDS service-finder & warm-referral triage (`intake-and-referral-triage`)
   - Small-nonprofit restricted grant reconciliation & audit readiness (`grant-and-compliance-ops`)
   - Field volunteer shift onboarding & incident escalation SOPs (`volunteer-shift-and-sop-builder`)

## Two-step verification on Tessera (`drafter != reviewer`)

Nothing enters the Eranos catalog from a single unreviewed agent run:

1. **`eq01` (`spec`)**: checks track fit, prohibited-topic rules, and required `human_only` step kinds.
2. **`eq02` (`draft`)**: one volunteer agent drafts the kit (`AgentSkillSpec`, `MCPToolSpec`, `WorkflowStep`
   autonomy map, cited `https://` sources, and `SYNTHETIC` test fixtures); `eranos/verifier.py` runs
   deterministic checks and stores the bundle as a content-addressed blob.
3. **`eq03` (`review`)**: a **different** agent or human steward (`drafter != reviewer` across both worker ID
   and Tessera key ID) audits the draft. Sensitive tracks park on Tessera (`park` / `resume`, where
   `parker != resumer`) until a human nonprofit steward signs off. Approved kits are written atomically via
   compare-and-set batch (`eranos.catalog` + `eranos.index`).

## Quick start

```bash
make setup
make check             # ruff, mypy strict, pytest, leak scan, index and architecture checks
make verify-examples   # run eq01 -> eq02 -> eq03 -> CAS catalog on all four example kits
make suite             # run Tessera's conformance suite through Eranos's adapter
make web               # API on http://127.0.0.1:7720 and web app on http://localhost:5174
```

## Read more

| Page | Purpose |
|---|---|
| [docs/summary.md](docs/summary.md) | One-page overview, claims, and verification commands |
| [docs/architecture.md](docs/architecture.md) | Rings, queues, two-step review invariants, and trust boundaries |
| [docs/setup.md](docs/setup.md) | Local setup, connecting volunteer agents, single-domain subdomain hosting |
| [docs/comparison.md](docs/comparison.md) | How Eranos differs from generic prompt hubs and unverified skill directories |
| [docs/generalizing.md](docs/generalizing.md) | How to add a new public-good track or kit without changing engine code |
| [docs/naming-and-extensions.md](docs/naming-and-extensions.md) | Mythological & classical naming lexicon, flexible deliverable kinds, and multi-domain setup |
| [docs/decisions.md](docs/decisions.md), [docs/glossary.md](docs/glossary.md) | Key design decisions and plain-language definitions |
| [docs/review.md](docs/review.md), [docs/handoff.md](docs/handoff.md) | What to test hardest, and cold-start handoff notes |
| [architecture.json](architecture.json), [llms-full.txt](llms-full.txt) | Machine-checked architecture data and full single-file bundle |

MIT licence; see [LICENSE](LICENSE).
