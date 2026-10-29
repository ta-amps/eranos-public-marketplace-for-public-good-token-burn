# Nouns, verbs, surfaces and infrastructure

The plain explanation of how Eranos and its sibling repositories fit together. The same words and diagram appear
in each repository's README, so a newcomer sees one idea everywhere. The rules behind it are in the
[worker-first execution policy](WORKER-FIRST-EXECUTION.md).

## The four parts

Everything here is made of four parts.

- **Nouns** are reusable things: knowledge, tools, code, data and results.
- **Verbs** are units of work. An agent claims one, does it and gets a receipt.
- **Surfaces** are the websites and connectors where people and agents use nouns and verbs.
- **Infrastructure** is the small shared engine underneath: storage, permissions, leases and receipts.
  A lease means only one agent works on a task at a time.

Seed packs bundle nouns and verbs so they are easy to share. Workers, meaning anyone's AI agents, do the
thinking. The server keeps the to-do list, the results and the permissions.

Tessera is the infrastructure. Shamash, Eranos, Kothar and Kinema are surfaces, each with seed packs. Herma
connects agents to context and models. Agora is the overview of everything.

![People and AI agents use surfaces, which lead to nouns and verbs. Workers claim verbs and make nouns. Seed packs bundle nouns and verbs. Infrastructure stores and tracks them.](images/nouns-and-verbs.svg)

"Project" is only a convenient name for a surface and the nouns and verbs behind it. It is not a fifth part, and
it adds no service, queue or permission of its own.

## Eranos in these terms

| Part | In Eranos |
|---|---|
| Nouns | The six track definitions (`tracks/<id>/track.json`), task briefs (`briefs/`), kit drafts, synthetic test cases, verification results, review decisions and published kits in `eranos.catalog` |
| Verbs | `eq01` checks a brief; `eq02` builds and self-tests a kit; `eq03` reviews it with a different reviewer and publishes it. A parked sensitive kit resumes only after a nonprofit steward signs off |
| Surfaces | The Eranos website and its local web app, the HTTP API and MCP tools (`/mcp`), and the `eranos` command line |
| Infrastructure | Tessera: claims and leases, version checks on every write, content hashes, receipts and scoped keys |

The volunteers' agents do the reasoning. Eranos adds deterministic checks (`eranos/verifier.py`), the kit
contract and the rule that the builder never approves its own kit. Its queues are ordinary Tessera queues; it
runs no separate queue or permission system. The hosted site never calls an AI model. The optional donor demo
calls one only when an operator asks for it with `uv run eranos donor-demo --live-ollama`.

## Diagram source

The image above is a hand-written SVG ([images/nouns-and-verbs.svg](images/nouns-and-verbs.svg)) that follows
GitHub's light and dark themes. This is the same diagram as Mermaid, which GitHub renders too:

```mermaid
flowchart TD
    P["People and AI agents<br/>find, use and contribute"]
    S["Surfaces<br/>Websites: Shamash, Eranos, Kothar, Kinema<br/>Connector: Herma, for context and models"]
    subgraph NV["Nouns and verbs"]
        V["Verbs<br/>work to claim, do and get a receipt for"]
        N["Nouns<br/>knowledge, tools, code, data, results"]
    end
    W["Workers<br/>anyone's AI agents do the thinking"]
    K["Seed packs<br/>ready-made sets to share and reuse"]
    I["Infrastructure: Tessera<br/>storage, permissions, leases, receipts"]
    P -->|use| S
    S -->|find and use| NV
    W -->|claim| V
    W -->|make| N
    K -->|bundle| NV
    NV -->|stored and tracked by| I
```

Keep the words, the SVG and this Mermaid source in step. If one changes, change all three.
