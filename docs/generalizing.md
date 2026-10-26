# Generalizing: Adding Tracks and Kits Without Engine Code

Eranos's Python engine (`eranos/`) knows no track ID or kit ID by name—`tests/test_tracks_and_verifier.py`
scans the AST of every module in `eranos/` and fails if one is hardcoded.

## Extension points

| What you want to add | Where it lives | What checks it |
|---|---|---|
| A public-good build track | `tracks/<id>/track.json` | `tests/test_tracks_and_verifier.py` validates `TrackPack`, sources, and `required_human_only` |
| A verified example kit | `examples/kits/<slug>.json` | `make verify-examples` runs `eq01 -> eq02 -> eq03` and checks CAS catalog publication |
| A volunteer build brief | `briefs/E<n>.json` | `tests/test_briefs_and_public.py` checks `TaskBrief` and refuses `public` effects for agents |

## Prohibited categories (never built)

Eranos never collects examples or builds generation kits for child sexual abuse material, grooming,
sextortion, intimate-image abuse, self-harm content, or real-person location tracking. `eranos/copy.py`
blocks these topics automatically.
