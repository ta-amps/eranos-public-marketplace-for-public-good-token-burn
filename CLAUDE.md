# Claude Code instructions for Eranos

## Worker execution direction

Follow the [worker-first execution policy](docs/WORKER-FIRST-EXECUTION.md) when designing agentic work. Prefer claimed verbs and authorized workers, including private workers. Keep ordinary coordination deterministic; additional review is a verb when required. Distinguish required procedures from useful pointers and open-ended discovery. Tool preparation and separate-process execution follow the task workspace and execution contract. The policy does not widen effect, spending or publication authority.

Read and follow @AGENTS.md first. Every hard rule in `AGENTS.md` applies here, enforced by
`.claude/hooks/guard.py`.

- Keep neutral modules in `eranos/` free of hardcoded track IDs: tracks live in `tracks/<id>/track.json`.
- Run `make check` before every commit, and `make index` + `python3 scripts/check_architecture.py . --sync-docs`
  whenever files or invariants change.
- Commit with the repo-local `ta-amps` identity and never add `Co-Authored-By` or `Generated with` trailers.

Surface release: follow [docs/SURFACE-RELEASE.md](docs/SURFACE-RELEASE.md) and the
light-only/accordion policy in AGENTS.md. A backend update must preserve the
approved UI ancestry and pass the compiled-asset deployment guard.
