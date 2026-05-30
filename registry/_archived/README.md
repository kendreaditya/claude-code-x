# Archived patches

Patch definitions here are **not applied** by default (`ccx list` hides them;
`ccx list --archived` shows them). A patch lands here for one of two reasons:

1. **Out of scope for the byte engine** — it isn't a same-length binary edit:
   a proxy (`prompt-cache-fix-proxy`), an alternative build (`centos7-build`), a
   prompt-level instruction set (`advisor-to-doer`), a patching *framework* or
   *manager* (`babel-ast-patcher`, `version-aware-patch-manager`), or a
   source-only patch for the leaked tree (`local-model-runnable`). These keep
   their provenance so credit is preserved; some are candidates for future
   engines (source/runtime/proxy — see GOAL.md).

2. **Broke on a newer Claude Code version** — the release-watch CI moves a patch
   here automatically when its anchors stop resolving (or it stops launching) on
   a new release. The `archive_reason` records why, and the compatibility report
   under `compat/` shows the version it last worked on.

Each archived definition carries `"archived": true` and an `archive_reason`.
Re-deriving a working anchor against the current version and moving the file back
into its group directory is all it takes to reactivate one.
