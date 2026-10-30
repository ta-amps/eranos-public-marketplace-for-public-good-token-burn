# Synthetic Example Kit Bundles

Each file `examples/kits/*.json` holds a synthetic request, volunteer agent draft, optional steward
sign-off payload, and independent review decision exercised end-to-end by `make verify-examples`
(`eq01 -> eq02 -> eq03 -> eranos.catalog`).

Every fixture input begins with `SYNTHETIC:` -- no real client, worker, caller, or donor data is ever
stored in this repository.

## Kits that point at a seed pack

An example with a `seed_pack` block holds only this catalog's envelope: the kit id, track, license and
governance fields, the scripted review and any steward sign-off. It names its pack's kit noun and example
request noun by exact NounRef pins. Everything else, from the step map to the synthetic test cases, is read
from `packs/<pack>/nouns.json` in the seed-pack library (`ERANOS_SEED_PACKS`, by default
`../seed-packs-library-of-nouns-and-verbs`), so each kit has one source.

A pin whose noun changed, a step whose verb template has a different title or claimant, or an example that
repeats kit content fails loudly (`tests/test_seed_packs.py`). Reading a pack writes, enqueues and activates
nothing.
