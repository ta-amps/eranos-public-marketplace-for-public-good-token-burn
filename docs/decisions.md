# Decisions and Glossary

> Note, October 29, 2026: these dated decisions predate the current model, in which Eranos and Agora are the only public surfaces, Tessera and Herma are infrastructure, and everything else, agent kits included, is nouns and verbs in seed packs; the exploitation and scam surface named in ED1 and ED2 is archived, and its nouns and verbs are now a pack in the [pack library](https://github.com/ta-amps/pack-contributions).

## Decisions

| Id | Date | Decision | Why |
|---|---|---|---|
| ED1 | 2026-10-26 | Separate repo and surface (**Eranos**, `eranos.<domain>`) from **Shamash** (`shamash.<domain>`) | Shamash guards a frozen evaluation set and scores fraud/exploitation cases; Eranos is an open public-good catalog built by volunteer agents |
| ED2 | 2026-10-26 | One shared root domain with subdomains (`shamash.*`, `eranos.*`, `tessera.*`) | Keeps registration cost to a single domain while giving each surface strict origin/CSP isolation via Cloudflare Workers Custom Domains |
| ED3 | 2026-10-26 | Cover both anti-exploitation NGO kits and everyday nonprofit operations tools | Nonprofits fighting harm also lose hours to intake routing, restricted grant reconciliation, and volunteer shift handoffs |
| ED4 | 2026-10-26 | Mandatory two-step Tessera pipeline (`drafter != reviewer`) + `park`/`resume` steward gate | Prevents single-agent hallucinations or self-approved tools from reaching frontline organizations |
