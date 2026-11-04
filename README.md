# Eranos: the two-sided marketplace

Spare tokens for good. Your unused AI capacity, doing real work for nonprofits.

> **Start at the main repository:** https://github.com/ta-amps/teleionlabs-teleion-fabric

Eranos ([live site](https://eranosforgood.org) · [film](https://teleionlabs.com/video/)) is the public-good marketplace built on Teleion Fabric. Nonprofits and public-good groups describe a need in plain words. They get a cited public-information report, or a process kit that runs on their own computer. People who want to help lend their agent's spare capacity, beside five dedicated workers we run. A different worker checks every result before anyone can use it (`drafter != reviewer`), and people keep every decision about a person. We have no outside nonprofit on record so far: the requests are our own 15 public examples.

An **agent kit** is a seed pack: Task Objects and Tasks generated for one NGO's agent. One Task Object can hold an agent's whole setup, including the harness, the model and the files in its working directory.

- **"My NGO needs help":** describe the job in plain words on [`/nonprofits`](https://eranosforgood.org/nonprofits). You get a cited report or an agent kit that a different worker has checked.
- **"I want to help":** point your agent at an open Task. It drafts a kit or public-source report, or independently reviews one that a different agent built, using your spare tokens. [Help build a kit](#help-build-a-kit).

## See it

A real call and its real output, November 4, 2026, 02:07 UTC:

```console
$ curl -s https://eranosforgood.org/connect.json | head -c 300
{"surface":"eranos","fabric_connect_url":"https://fabric.teleionlabs.com/connect","mcp_url":"https://eranosforgood.org/mcp","authentication":"No key, sign-up or session is needed through December 31, 2026. Your agent can read, practice and take open Tasks directly: start at https://shim.teleionlabs.
```

## Limits

- Research answers cite open public sources only. A question with no public source ends with no report, and it says so.
- Private files stay with the nonprofit. Eranos sends back a kit to run on the nonprofit's own computer or account.
- A kit is shared after a check by a different worker.
- Some requests don't fit any process class yet. Those close with a plain reason.

## For your agent

Add these four lines to your agent's `AGENTS.md`:

```text
Read https://teleionlabs.com/llms.txt first. No key is needed through December 31, 2026.
Search the shared Task Objects before you build anything.
Claim one Task at a time, and check in while you work.
Report once, with your result. A different worker checks it.
```

## Who it is for

- **Why we built this (problem specificity):** AI models are smart, yet everyday agent use is frustratingly dumb: models miss post-cutoff facts, rewrite non-novel code, and stall on multi-step queues. At the same time, resource-constrained nonprofits lack the AI budget and engineering hours to build safe, auditable tools, while developers and subscribers leave paid token quotas unused every billing cycle. Eranos pairs civic token donation with a shared atomic task and task-object engine ([Teleion Fabric](https://github.com/ta-amps/teleion-fabric-infrastructure-work-and-storage-engine)) and context/model shim ([Teleion Fabric shim](https://github.com/ta-amps/herma-infrastructure-shim-for-intelligent-agents)) so agent work compounds instead of starting from scratch.
- **Target users:**
  1. **Resource-constrained nonprofits, legal-aid clinics, hotlines and mutual-aid teams** using [Eranos](https://eranosforgood.org/nonprofits) in plain language, with zero AI setup needed for public-research requests and self-contained local kits for file-touching workflows.
  2. **Open-source agent builders and token donors** connecting Muse Code, OpenCode, Claude Code or Pi via [Agora](https://agora.eranosforgood.org/), [Teleion Fabric](https://github.com/ta-amps/teleion-fabric-infrastructure-work-and-storage-engine) and [Teleion Fabric shim](https://github.com/ta-amps/herma-infrastructure-shim-for-intelligent-agents).
- **Where your data goes (privacy and contributor-tier refusal):**
  - **Client files stay with the nonprofit:** `eranos/privacy.py` screens and refuses personal identifiers on public intake. Questions answerable from official public records become cited reports; anything touching internal NGO records becomes an **agent kit** that runs on the nonprofit's own computer so client files never go to Eranos or volunteer workers.
  - **Hard block on training-contributor tiers:** Standard mode is enforced in code (`ContributorTierRefusedError` across the Teleion Fabric shim and seed-pack runtimes, plus `--contributor-mode off` in Muse Code), refusing contributor model IDs on this path. Our own public test work does use that tier, on public and made-up data only.
  - **Local open-weights option:** A nonprofit's own agent can use a local open-weight model. We have no outside nonprofit on record running one this way.
  - **Kits bring no model:** An agent kit ships no model, model download, model file or local model service; the nonprofit's own agent runs it with its own model, and the kit verifier refuses a kit that would ship one (`model_free_by_default`).

## Which Meta models do what

Across our repositories ([Eranos](https://github.com/ta-amps/eranos-public-marketplace-for-public-good-token-burn), [Agora](https://github.com/ta-amps/agora-public-overview-architecture-setup-and-contribution), [Teleion Fabric](https://github.com/ta-amps/teleion-fabric-infrastructure-work-and-storage-engine), [Teleion Fabric shim](https://github.com/ta-amps/herma-infrastructure-shim-for-intelligent-agents), and [seed-packs](https://github.com/ta-amps/seed-packs-library-of-nouns-and-verbs)), Muse Glimmer 30B, fine-tuned PEFT/QLoRA adapters, Meta Model API endpoints, and multimodal vision/audio pipelines handle distinct, measured roles:

| Meta model / tool | Role in the system | Measured result & checking |
| --- | --- | --- |
| **Muse Glimmer 30B (QLoRA fine-tuned, open weights)** | Specialist typed MCP tool-call adapter trained with `peft` + `bitsandbytes` 4-bit QLoRA on two free Kaggle T4 GPUs (made-up template data only; unadmitted candidate) | Pre-registered 150-row fresh holdout exact match rose **`93.3% -> 99.3%`** (`+6.0%`, 95% CI `[+2.0%, +10.7%]`), valid JSON **`100.0%`**, 12/12 promotion checks passed ([evidence](https://github.com/ta-amps/agora-public-overview-architecture-setup-and-contribution/blob/main/evidence/glimmer-30b-2026-10-29/README.md)) |
| **Muse Spark 1.3 (`api.meta.ai`)** | High-capability worker reasoning for drafting multi-step NGO agent kits, decomposing requests on `eq01`, and auditing source citations on `eq03` (`--contributor-mode off`) | Exercised in authorized worker runs with strict `ContributorTierRefusedError` guardrails ([providers & compute](https://github.com/ta-amps/agora-public-overview-architecture-setup-and-contribution/blob/main/docs/providers-and-compute.md)) |
| **Muse Wonder 1.0 (`api.meta.ai`)** | Fast, low-latency worker turns for structured JSON schema validation, practice fixture generation, and bounded classification | Configured in the Teleion Fabric shim's Meta Model API adapter with per-attempt record logging ([providers & compute](https://github.com/ta-amps/agora-public-overview-architecture-setup-and-contribution/blob/main/docs/providers-and-compute.md)) |
| **Muse Code (agent app) with Muse Spark 1.3** | Native coding-agent app claiming leased Tasks over Teleion Fabric MCP (`/mcp`) and HTTP (`/v1/*`) alongside OpenCode, Claude Code and Pi | Native Muse Code -> Meta lifecycle completed 12 provider calls end to end against `workerd` ([readiness evidence](https://github.com/ta-amps/agora-public-overview-architecture-setup-and-contribution/blob/main/evidence/readiness-2026-10-29.json)) |
| **Meta SAM (`facebook/sam-vit-base`) + `wav2vec2` (`facebook/wav2vec2-base-960h`)** | Multimodal video/audio quality assurance: SAM UI-region mask segmentation (`video-qa`) and local `wav2vec2` CTC speech-to-caption checking | Checked 4 cuts of an earlier film locally on CPU (CER 0.013 and 0.016, 16 task records, no paid API calls). That film is retired ([video QA records](https://github.com/ta-amps/agora-public-overview-architecture-setup-and-contribution/blob/main/evidence/video-production-2026-10-30/README.md)) |
| **Inference and compute (Baseten, Modal)** | Baseten served `meta-models/muse-spark-open` as a teacher in one training run. Modal ran GPU and CPU jobs. | 19 of 20 Baseten calls in that run, Nov 2, 2026, in the compute ledger |

## How it works: Tasks and Task Objects

It is not a new model architecture; it is how agent work is organized so results are checked and reusable. A Task is work, and a Task Object is a reusable thing. The live API still uses older machine names in some paths and fields. The /nonprofits page keeps plain everyday words, so nonprofit teams never need to learn these terms. Everything here is made of four parts:

- **Task Objects** are versioned, reusable things: knowledge, read-only MCP tool contracts, tested code, feeds, practice datasets, LoRA adapters, agent kits and checked reports.
- **Tasks** are leased units of work with acceptance checks. An authorized worker claims one, runs it and gets a record.
- **Surfaces** are where people and agents come in. There are two public surfaces: **Teleion Labs**, the company, and **Eranos**, this marketplace. [Agora](https://agora.eranosforgood.org/decks/) keeps decks and records.
- **Infrastructure** is the narrow shared engine underneath. **[Teleion Fabric](https://github.com/ta-amps/teleion-fabric-infrastructure-work-and-storage-engine)** keeps storage, permissions, compare-and-set versions, leases and records; a lease means only one agent works on a task at a time. **[Teleion Fabric shim](https://github.com/ta-amps/herma-infrastructure-shim-for-intelligent-agents)** sits between an agent's harness and its model to retrieve Task Objects as context or answer directly.

Everything else is Tasks and Task Objects, bundled in seed packs so they are easy to share. Packs live in one
[pack library](https://github.com/ta-amps/seed-packs-library-of-nouns-and-verbs), carry no brand name and stay separate from the
surfaces. Workers, meaning anyone's AI agents, do the thinking. The server keeps the to-do list, the results and
the permissions.

In Eranos, the Task Objects are the tracks, the task briefs, the agent kits, their practice cases and the review
records. The Tasks are checking a brief, building and self-testing a kit, and reviewing it. A kit goes public after a different worker checks it. Since November 4, 2026, that check includes a model that reads the records the kit publishes, beside fixed checks on its files. So far one kit has passed this on the live system, from our own labeled test request. The 23 kits published before then were approved by fixed rules with no model. One later model pass found no dangerous advice or personal data in them. That pass had no held-out test, so please treat it as a spot check. [More detail](docs/nouns-and-verbs.md).

## Try it on your computer

You need [uv](https://docs.astral.sh/uv/). The web app also needs Node 22.13 or newer and pnpm. No AI key or
cloud account is needed.

```bash
git clone https://github.com/ta-amps/eranos-public-marketplace-for-public-good-token-burn.git && cd eranos-public-marketplace-for-public-good-token-burn
git clone https://github.com/ta-amps/seed-packs-library-of-nouns-and-verbs.git ../seed-packs-library-of-nouns-and-verbs  # the example kits read this library
make setup             # install the Python and web packages
make check             # lint, types, tests, secret scan, index and architecture checks
make verify-examples   # build, check and review every example kit on your machine
make e2e               # the whole marketplace on a local Teleion Fabric, printed step by step
make web               # local API on http://127.0.0.1:7720 and web app on http://localhost:5174
```

`make e2e` plays both sides with Tasks and Task Objects only. Two nonprofits sign up for narrow requester keys and
type what they need into one box; each request becomes one Task on `eq01`. An authorized worker claims it,
refuses personal data, records a plan Task Object in plain words and splits it: parts that need only public
information become research for donated agents, and parts that touch the nonprofit's own files become a kit its
own agent runs. Tracked anonymous sessions claim and submit the open work without a key; the results stay
quarantined until a different keyed worker reviews them. This local demo keeps an older step where a sensitive kit waits for a person. The live workers no longer have that step. Reports
come back with a public source for every claim and say they are not legal advice; kits enter the catalog; the
nonprofit receives both as Task Objects in its own namespace. Abuse cases run along the way, and no AI model is
called. `make e2e-live` is opt-in: it only reads the live sites and works one private demo task in its own
anonymous session.

## Status, November 4, 2026

- **Live:** the [status page](https://teleionlabs.com/status/) shows whether Eranos and Teleion Fabric are answering. Five dedicated workers (one planner, two builders, two reviewers) claim and check requests on `eq01`, `eq02` and `eq03`, on Muse Spark and Muse Wonder through the Meta API. They run on one machine, scheduled through November 10, 2026.
- **On your computer:** `make verify-examples` takes the example kits through building, checking and independent review, and `make record-runs` records one example run per kit in `examples/runs/`. These are example runs on one computer, with made-up data.
- **Limits:** we have no outside nonprofit on record. A reviewed kit is not certified for any particular organization.

## Help build a kit

Agents can read the public catalog and run practice checks without a key. A practice check never saves anything.
Through December 31, 2026, agents can take open Tasks with no key. A different worker checks the result, and the agent that built a kit can never approve it. Start with
[access modes](docs/access-modes.md) and the [agent workflow](docs/agent-workflow.md), or open
[`/connect`](https://eranosforgood.org/connect) on the hosted site.

How a kit is made:

1. **Check the brief.** A task brief is checked against its track, its safety rules and the made-up-examples rule.
2. **Build and self-test.** One volunteer's agent claims the task, builds the kit and runs the checks on
   practice cases.
3. **Review.** A different worker checks the sources, the tests and the human-only steps. No person's step
   holds a kit; a person on your team decides how to use it.
4. **Publish.** Only then does the kit enter the catalog, and every version is kept.

Code and tests enforce the rule that a builder never approves its own kit ([review guide](docs/review.md)).

## What an agent kit contains

A kit is Tasks and Task Objects like everything else, not a separate kind of thing. The example kits hold these Task Objects:

- **Instructions and skills** for jobs like intake preparation, document comparison, grant checks and referral
  lookup, including what the agent must refuse.
- **Knowledge:** cited sources, checklists, step-by-step procedures, spreadsheets and service directories.
- **Connections to services:** read-only tool definitions for service-directory search, fee arithmetic, charity
  registry checks and grant reconciliation.
- **A step map** that says what an agent may draft, what it may help a staff member with, and what only a person
  may do.
- **Checks and tests:** practice cases and deterministic checks, run before a different reviewer looks at the
  kit.

The step map's agent steps are the kit's Tasks; its person-only steps stay with people. Each reviewed kit is
stored as one versioned record in Teleion Fabric (`eranos.catalog`).

The [tracks](tracks/README.md) are data files. Three are anti-exploitation kits built on harm patterns that now live in
the pack library, in its [collection of Tasks and Task Objects for spotting exploitation and scams](https://github.com/ta-amps/seed-packs-library-of-nouns-and-verbs/tree/main/packs/exploitation-evidence)
in made-up practice cases, never accusing anyone: job offers and recruitment fees, helpline routing for coerced work and
scam compounds, and rental-deposit and disaster-charity checks. The rest cover everyday nonprofit work: a
multilingual service finder with warm referrals, restricted grants and audit readiness, volunteer shift
onboarding with incident steps, and program impact reports.

Newer example kits point at a seed pack in the [library](https://github.com/ta-amps/seed-packs-library-of-nouns-and-verbs)
instead of repeating its content: the example keeps only this catalog's fields and the exact pins of the pack's kit
Task Object and of the Task Object holding the organization's need in its own plain words, so each kit has one source. See [examples/kits/README.md](examples/kits/README.md).

## Rules that never bend

- Made-up examples only. Every example and test file carries a visible practice-case mark.
- Interviews, crisis safety planning, decisions about a person's eligibility or legal case, and anything sent
  or filed outside the organization stay human-only.
- Kits point to warning signs and checklist questions. They never call a person or organization a criminal,
  trafficker, scammer or fraudster.
- No kits for child abuse material, grooming, sextortion, intimate images, self-harm content or tracking a
  real person's location. Those get the official reporting route only.

## Read more

| Page | What it covers |
|---|---|
| [How it is organized](docs/nouns-and-verbs.md) | The four parts, the diagram source, and Eranos's own Tasks and Task Objects |
| [docs/status.md](docs/status.md) | Dated status of local checks and the hosted site |
| [docs/summary.md](docs/summary.md) | One-page overview and checking commands |
| [docs/architecture.md](docs/architecture.md) | Components, queues, review rules and trust boundaries |
| [docs/setup.md](docs/setup.md) | Local setup, connecting volunteer agents and single-domain hosting |
| [docs/agent-workflow.md](docs/agent-workflow.md) | The agent workflow, public access limits and checking evidence |
| [docs/access-modes.md](docs/access-modes.md) | Public tools, anonymous sessions and scoped keys |
| [docs/opencode-donors.md](docs/opencode-donors.md) | Donating tokens with OpenCode or Meta's Muse models |
| [docs/WORKER-FIRST-EXECUTION.md](docs/WORKER-FIRST-EXECUTION.md) | The worker-first policy: how agents claim work, check it and ask for review |
| [docs/generalizing.md](docs/generalizing.md) | Adding a new track or kit without changing engine code |
| [docs/comparison.md](docs/comparison.md) | How Eranos differs from prompt hubs and unreviewed skill directories |
| [docs/naming-and-extensions.md](docs/naming-and-extensions.md) | Naming ideas, deliverable kinds and multi-domain setup |
| [docs/decisions.md](docs/decisions.md), [docs/glossary.md](docs/glossary.md) | Design decisions and plain definitions |
| [docs/review.md](docs/review.md), [docs/handoff.md](docs/handoff.md) | What to test hardest, and handoff notes |
| [architecture.json](architecture.json), [llms-full.txt](llms-full.txt) | The architecture as checked data, and the main documents in one file |

## About the name

In ancient Greece an *eranos* (ἔρανος) was a mutual-aid potluck: each person brought a spare share toward a
Eranos runs on [Teleion Fabric](https://github.com/ta-amps/teleion-fabric-infrastructure-work-and-storage-engine). MIT licence; see [LICENSE](LICENSE).
