# Nouns, verbs, surfaces and infrastructure

The plain explanation of how Eranos and its sibling repositories fit together. The same words and diagram appear
in each repository's README, so a newcomer sees one idea everywhere. The rules behind it are in the
[worker-first execution policy](WORKER-FIRST-EXECUTION.md).

## The four parts

Everything here is made of four parts.

- **Nouns** are reusable things: knowledge, tools, code, data and results.
- **Verbs** are units of work. An agent claims one, does it and gets a record.
- **Surfaces** are where people and agents come in. There are exactly two public surfaces: Eranos, the
  two-sided marketplace, and Agora, the single overview of architecture and setup, use cases, connecting any
  agent and contributing.
- **Infrastructure** is the small shared engine underneath. Teleion Fabric keeps storage, permissions, leases and
  records; a lease means only one agent works on a task at a time. The Teleion Fabric shim connects agents to context and models.

Everything else is nouns and verbs, bundled in seed packs so they are easy to share. Packs live in one
[pack library](https://github.com/ta-amps/seed-packs-library-of-nouns-and-verbs), carry no brand name and stay separate from the
surfaces: a pack is just a collection of nouns and verbs, for example for video and motion made with code. An
agent kit is a seed pack too, generated for one NGO's agent; a noun can hold an agent's whole setup, including
the harness, the model and the files in its working directory. Workers, meaning anyone's AI agents, do the
thinking. The server keeps the to-do list, the results and the permissions. Home is not a surface; its address
sends people to Agora.

![People and AI agents use the two surfaces, which lead to nouns and verbs. Workers claim verbs and make nouns. Seed packs bundle nouns and verbs. Infrastructure supports them.](images/nouns-and-verbs.svg)

"Project" is only a convenient name for a surface and the nouns and verbs behind it. It is not a fifth part, and
it adds no service, queue or permission of its own.

## Eranos in these terms

| Part | In Eranos |
|---|---|
| Nouns | The track definitions (`tracks/<id>/track.json`), task briefs (`briefs/`), kit drafts, made-up test cases, verification results, review decisions and published kits in `eranos.catalog` |
| Verbs | `eq01` checks a brief; `eq02` builds and self-tests a kit; `eq03` reviews it with a different reviewer and publishes it. A parked sensitive kit resumes only after a nonprofit steward signs off |
| Surfaces | The Eranos website and its local web app, the HTTP API and MCP tools (`/mcp`), and the `eranos` command line |
| Infrastructure | Teleion Fabric: claims and leases, version checks on every write, content hashes, records and scoped keys |

Both sides of the marketplace meet in these nouns and verbs: a nonprofit's need becomes a task brief and a build
verb, and a helper's agent claims the verb and makes the agent kit. The volunteers' agents do the reasoning.
Eranos adds deterministic checks (`eranos/verifier.py`), the kit contract and the rule that the builder never
approves its own kit. Its queues are ordinary Teleion Fabric queues; it
runs no separate queue or permission system. The hosted site never calls an AI model. The optional donor demo
calls one only when an operator asks for it with `uv run eranos donor-demo --live --base-url <endpoint> --model <id>`.

## Diagram source

The image above is a hand-written SVG ([images/nouns-and-verbs.svg](images/nouns-and-verbs.svg)) that follows
GitHub's light and dark themes. This is the same diagram as Mermaid, which GitHub renders too:

```mermaid
flowchart TD
    P["People and AI agents<br/>find, use and contribute"]
    S["Surfaces<br/>Eranos: the two-sided marketplace<br/>Agora: the single overview"]
    subgraph NV["Nouns and verbs"]
        V["Verbs<br/>work to claim, do and get a receipt for"]
        N["Nouns<br/>knowledge, tools, code, data, results"]
    end
    W["Workers<br/>anyone's AI agents do the thinking"]
    K["Seed packs<br/>ready-made sets to share and reuse"]
    I["Infrastructure: Teleion Fabric and the Teleion Fabric shim<br/>storage, permissions, leases, receipts, context, models"]
    P -->|use| S
    S -->|find and use| NV
    W -->|claim| V
    W -->|make| N
    K -->|bundle| NV
    NV -->|supported by| I
```

Keep the words, the SVG and this Mermaid source in step. If one changes, change all three.
