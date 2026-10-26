# Comparison

How Eranos compares with common ways nonprofits and public-good teams adopt AI prompts or agent skills:

| Approach | Who checks quality | Human-only boundaries | Data hygiene | Multi-agent safety |
|---|---|---|---|---|
| Ad-hoc shared prompt docs | None; copy-paste drift | Written in prose only, easy to omit | Risk of pasting real client notes into examples | Overwrites in shared docs |
| Open community skill hubs | Single-author upload | Rarely separates `drafts`, `assists`, and `human_only` | Varies by author | No lease or receipt trail |
| Bespoke consulting builds | High, for one organization | Custom per engagement | Scoped per engagement | Expensive for small nonprofits |
| **Eranos on Tessera** | Deterministic verifier (`eq02`) **plus** mandatory independent review (`eq03`, `drafter != reviewer`) | Enforced in Pydantic and verifier: interviews, crisis plans, individual decisions, and external sends must be `human_only` | `SYNTHETIC` mark required on every fixture; non-accusatory copy enforced | Tessera leases, fencing tokens, SHA-256 receipts, park/resume steward sign-off, and CAS catalog history |
