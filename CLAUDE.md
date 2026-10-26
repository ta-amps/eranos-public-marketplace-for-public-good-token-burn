# Claude Code instructions for Eranos

Read and follow @AGENTS.md first. Every hard rule in `AGENTS.md` applies here, enforced by
`.claude/hooks/guard.py`.

- Keep neutral modules in `eranos/` free of hardcoded track IDs: tracks live in `tracks/<id>/track.json`.
- Run `make check` before every commit, and `make index` + `python3 scripts/check_architecture.py . --sync-docs`
  whenever files or invariants change.
- Commit with the repo-local `ta-amps` identity and never add `Co-Authored-By` or `Generated with` trailers.
