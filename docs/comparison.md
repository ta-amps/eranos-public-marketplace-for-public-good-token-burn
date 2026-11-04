# Comparison

How donating unused tokens through **Eranos**, the two-sided marketplace, compares with common ways NGOs and
public-good teams try to get working AI help. In Eranos that help arrives as an agent kit: a seed pack of nouns
and verbs generated for the NGO's agent, holding skills, read-only tool definitions, files and agentic processes.

| Approach | Cost to NGO | Who builds & tests it | Human-only boundaries | Data hygiene | Multi-agent safety |
|---|---|---|---|---|---|
| Ad-hoc shared prompt docs | Free, high staff time | Untested copy-paste prompts | Written in prose only, easy to omit | Risk of pasting real client notes into examples | Overwrites in shared docs |
| Open community skill hubs | Free | Single-author upload, rarely tested on NGO edge cases | Rarely separates `drafts`, `assists`, and `human_only` | Varies by author | No lease or record trail |
| Bespoke consulting builds | High ($10k–$100k+) | Custom per engagement | Custom per engagement | Scoped per engagement | Out of reach for small NGOs |
| **Eranos on Teleion Fabric** | **Free off the shelf (funded by donated unused tokens)** | Contributor 1 builds & runs deterministic verifier (`eq02`); **Contributor 2 independently tests & reviews** (`eq03`, `drafter != reviewer`) | Enforced in Pydantic and verifier: interviews, crisis plans, individual decisions, and external sends must be `human_only` | Practice mark required on every fixture; non-accusatory copy enforced | Teleion Fabric leases, fencing tokens, SHA-256 records, park/resume steward sign-off, and CAS catalog history |
