# Summary

**Eranos** lets people **donate unused AI tokens** to build, test, and independently review **off-the-shelf
agent skills, tools, files, and agentic processes** that NGOs, legal-aid desks, hotlines, and community
nonprofits can pick up and run right away for the public good.

- **Why it exists:** Developers and teams routinely have leftover AI tokens at the end of a billing window,
  while NGOs and public-good organizations rarely have the budget or staff to build and test reliable agent
  workflows from scratch.
- **What NGOs get off the shelf:** Verified packages combining **agent skills** (`SKILL.md` / `AgentSkillSpec`),
  **read-only MCP tools** (`MCPToolSpec` JSON Schemas), **ready-to-use files** (Markdown SOPs, checklists, CSV
  templates, Open Referral HSDS directories, `SYNTHETIC` test fixtures), and **agentic processes** with explicit
  step-by-step human/agent boundaries.
- **Sister surface to [Shamash](https://github.com/ta-amps/shamash):** Shamash (`shamash.<domain>`) finds,
  quantifies, and combats human harm, scams, financial fraud, and exploitation across social media, websites,
  messages, documents, and payments. Eranos (`eranos.<domain>`) turns donated tokens into the off-the-shelf tools
  and workflows helping organizations use on the ground.
- **Powered by [Tessera](https://github.com/ta-amps/tessera) with two-step verification (`drafter != reviewer`):**
  One contributor's donated tokens build and self-test a package in `eq02`; a **different** contributor's tokens
  or a human steward independently tests and reviews it in `eq03` before atomic compare-and-set publication into
  `eranos.catalog`.
- **Hard human boundaries:** Client interviews, crisis safety planning, individual eligibility or legal
  decisions, and external filings are enforced as `human_only` in schema and verifier code.

## Verify what works today

```bash
make check             # lint, mypy strict, unit + pipeline + API + guard tests, leak scan, architecture
make verify-examples   # runs 4 synthetic kits across anti-exploitation and nonprofit-ops (including park/resume)
make suite             # runs Tessera's conformance suite through eranos.adapter
make web-check         # strict TypeScript check and Vite production bundle
```
