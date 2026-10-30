# Summary

**Eranos** is a two-sided marketplace for spare AI capacity. People who want to help **donate unused AI tokens**,
and their agents build, test, and independently review **agent kits**. NGOs, legal-aid desks, hotlines, and
community nonprofits describe a need and get a reviewed kit they can pick up and run for the public good. An
agent kit is a seed pack: nouns and verbs generated for one NGO's agent. A noun can hold an agent's whole setup,
including the harness, the model and the files in its working directory.

- **Why it exists:** Developers and teams routinely have leftover AI tokens at the end of a billing window,
  while NGOs and public-good organizations rarely have the budget or staff to build and test reliable agent
  workflows from scratch.
- **What a kit holds:** nouns for **instructions and skills** (`SKILL.md` / `AgentSkillSpec`), **connections to services**
  as read-only MCP tool definitions (`MCPToolSpec` JSON Schemas), **knowledge and ready-to-use files** (cited
  sources, Markdown SOPs, checklists, CSV templates, Open Referral HSDS directories), a **step map** with explicit
  step-by-step human/agent boundaries, and **checks and tests** (`SYNTHETIC` test fixtures and the deterministic
  verifier).
- **One of exactly two public surfaces:** Eranos (`eranos.<domain>`) is the marketplace, and Agora is the single
  overview of architecture and setup, use cases, connecting any agent and contributing. Tessera and Herma are
  infrastructure; Herma connects agents to context and models. Home is not a surface; its address sends
  people to Agora. Everything else is nouns and verbs in seed packs. The three anti-exploitation tracks build on
  harm patterns that now live in the [pack library](https://github.com/ta-amps/seed-packs-library-of-nouns-and-verbs) as a
  collection of nouns and verbs for spotting exploitation and scams in synthetic cases, never accusing anyone.
- **Powered by [Tessera](https://github.com/ta-amps/tessera-infrastructure-work-and-storage-engine) with two-step verification (`drafter != reviewer`):**
  One contributor's donated tokens build and self-test a package in `eq02`; a **different** contributor's tokens
  or a human steward independently tests and reviews it in `eq03` before atomic compare-and-set publication into
  `eranos.catalog`.
- **Hard human boundaries:** Client interviews, crisis safety planning, individual eligibility or legal
  decisions, and external filings are enforced as `human_only` in schema and verifier code.

## Verify what works today

```bash
make check             # lint, mypy strict, unit + pipeline + API + guard tests, leak scan, architecture
make verify-examples   # runs 5 synthetic kits across anti-exploitation and nonprofit-ops (including park/resume)
make suite             # runs Tessera's conformance suite through eranos.adapter
make web-check         # strict TypeScript check and Vite production bundle
```
