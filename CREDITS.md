# Credits

`claude-code-x` aggregates patch *techniques and ideas* from the community. Each
patch shipped in `registry/` carries a `provenance` block citing its origin repo,
author, and license; `ccx credits` (planned) renders this ledger from the
registry + applied manifest.

The full catalogue of upstream projects this work draws on is in
[PRIOR-ART.md](./PRIOR-ART.md). Special acknowledgement to:

- **roman01la** — the original `cli.js` de-nerf patch that started the ecosystem.
- **Pickle-Pixel/claudecode-buddy-crack** — landmark-based, version-agnostic binary patching (the resilience model this engine adopts).
- **taocihei/claude-code-patcher-next** — version-gate + capability-matrix patch-manager pattern.
- **huybuidac/claude-code-patchkit** — marker-based idempotency + context guard.
- **ominiverdi/claude-depester** — LIEF unpack/repack reference.
- **cnighswonger/claude-code-cache-fix** — API-boundary proxy with fail-to-no-op.

## Licensing & redistribution

Most upstream patches carry **no explicit license** (`unknown`). The MIT license
in this repo covers **the patch scripts and `*.ccxpatch.json` definitions only** —
**not** the patched Claude Code binary, which remains Anthropic's copyrighted
work. Patching it locally for your own use is one thing; **redistributing a
modified, re-signed binary plausibly violates Anthropic's terms and copyright.**
`claude-code-x` is a local-only, build-it-yourself patcher. Do not distribute
patched binaries.
