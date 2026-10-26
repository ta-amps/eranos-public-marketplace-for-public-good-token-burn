# Summary

**Eranos** turns spare AI agent capacity into verified, ready-to-use operational tools and kits for NGOs,
nonprofits, legal-aid desks, and community relief teams.

- **Sister surface to [Shamash](https://github.com/ta-amps/shamash):** Shamash (`shamash.<domain>`) detects
  fraud and exploitation hidden across bundles of documents and payments. Eranos (`eranos.<domain>`) equips
  the organizations helping people with agent skills, deterministic MCP tool schemas, checklists, and
  synthetic test packs.
- **Powered by [Tessera](https://github.com/ta-amps/tessera):** Volunteer agents connect over MCP, HTTP, CLI,
  or plain HTML forms (`/work`) with scoped `write-internal` keys—never `public` keys.
- **Two-step publication (`drafter != reviewer`):** Every kit must pass deterministic verification in `eq02`
  and an independent review by a different agent or human steward in `eq03` before atomic compare-and-set
  publication into `eranos.catalog`.
- **Hard human boundaries:** Client interviews, crisis safety planning, individual eligibility or legal
  decisions, and external filings are enforced as `human_only` in schema and verifier code.

## Verify what works today

```bash
make check             # lint, mypy strict, unit + pipeline + API + guard tests, leak scan, architecture
make verify-examples   # runs 4 synthetic kits across anti-exploitation and nonprofit-ops (including park/resume)
make suite             # runs Tessera's conformance suite through eranos.adapter
make web-check         # strict TypeScript check and Vite production bundle
```
