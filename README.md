# claude-code-x (`ccx`)

A universal, version-aware, **provenance-respecting** CLI patcher for the
[Claude Code](https://claude.com/claude-code) Bun-compiled binary. Patches are
pure data (`registry/<group>/*.ccxpatch.json`); the engine resolves each by a
version-agnostic landmark anchor, applies a same-length byte edit, re-signs, and
verifies the binary still launches — with a clean revert and a manifest of
everything it changed. Not a fork, not a rebuild.

> **Local-only.** `ccx` patches *your* installed binary. It never redistributes a
> modified Anthropic binary — that would breach Anthropic's ToS/copyright (see
> [CREDITS.md](./CREDITS.md)). The daily release-watch Action publishes patch
> *definitions* + a compatibility report, not the binary.

## Quickstart

```bash
pip install -e .            # or: ./bin/ccx <cmd>

ccx latest                  # installed vs latest published Claude Code version
ccx detect                  # container / version / signing facts
ccx list                    # patch catalog, grouped, with applicability
ccx apply fifo-steering-queue   # apply (prints citation, backs up, re-signs, verifies)
ccx status                  # what's applied (re-verified live against the binary)
ccx validate-all            # apply every patch to a throwaway copy + smoke-test
ccx revert fifo-steering-queue  # surgical undo from the manifest
ccx hook install            # auto-reapply after Claude Code auto-updates
```

The flagship patch — **FIFO steering & queue bundling** — is described below; it
was the seed the engine was built around.

## Why (the flagship patch)

By default, Claude Code "soft-steers" the running turn when you type while it works:

- **Mid-turn injection** — a message you type mid-turn is rendered into the model's context as a `<system-reminder>` ("The user sent a new message while you were working… you MUST address it"). The strong language often makes the model pivot mid-stream.
- **Queue bundling** — multiple queued messages of the same mode are dequeued together and delivered as a *single* user turn, so three quick messages become one combined response.

`claude-code-x` neutralizes both so input behaves as a strict FIFO: **each message gets its own complete turn, in order, with no mid-flight steer.**

See **[GOAL.md](./GOAL.md)** for the design and milestones, **[PRIOR-ART.md](./PRIOR-ART.md)**
for the community patches this builds on, **[CREDITS.md](./CREDITS.md)** for the
attribution + licensing policy, and **[docs/](./docs/)** for the engine + CLI
design. Runtime-effect of plaintext-JS edits was verified empirically:
**[docs/M2-bytecode-finding.md](./docs/M2-bytecode-finding.md)**.

## What FIFO patch changes

| # | Source location | Behavior killed |
|---|-----------------|-----------------|
| 1 | `attachments.ts` — `INLINE_NOTIFICATION_MODES` | Mid-turn `<system-reminder>` injection for `prompt`-mode messages (keeps `task-notification`, load-bearing for background-agent wake-ups). |
| 2 | `queueProcessor.ts` — `processQueueIfReady` | Per-mode queue bundling. Forces every queued command through the single-item dequeue path. |
| 3 | `query.ts` — mid-turn `removeFromQueue` filter | Mid-turn removal of `prompt`-mode commands. |

All replacements are **same-length** byte sequences, so no offsets shift in the binary. The locator regexes anchor on structurally stable elements (function-signature shape, literal strings) and extract churned minifier identifiers dynamically — so routine minifier-name changes between releases are handled automatically.

All three replacements are **same-length** byte sequences anchored on structurally
stable elements (function-signature shape, literal strings) with the churned
minifier identifiers captured dynamically — so routine minifier-name churn between
releases is handled automatically.

## How the engine works

Every `ccx apply` is a chain of hard gates — it resolves everything before
touching a byte, then writes once and atomically swaps:

```
DETECT → LOCATE → VERIFY → [confirm] → BACKUP → APPLY → RE-SIGN → SMOKE-TEST → MANIFEST
```

- **Anchor, never offset** — locators are regexes over the embedded plaintext JS,
  gated to the owning Bun CJS module, required to match exactly once.
- **Same-length first** — equal-byte edits need no Mach-O fixups, only an ad-hoc
  re-sign. Variable-length (LIEF) is gated off until implemented.
- **Reversible** — the manifest stores original/patched bytes for a surgical
  `revert`; `<binary>.unpatched` is the pristine fallback.
- **Honest verification** — checks marker presence, stable Bun trailer offset,
  `codesign --verify`, and a launch smoke test (never file-size equality, which
  re-signing changes every run).

### Auto-repatch on update

Claude Code auto-updates write a new, **unpatched** binary. `ccx hook install`
adds a SessionStart hook that idempotently re-applies your manifest's patch set
(`ccx apply --from-manifest`), re-resolving anchors against the new version — with
a single recursion guard, an unchanged-binary fast path, and a per-binary attempt
cap so it can never fork-bomb.

## The original standalone script (v0)

`repatch-claude-noqueue.sh` is the original single-purpose FIFO patcher that
predates the engine. It still works (`./repatch-claude-noqueue.sh`) but `ccx` is
the maintained path.

## Rollback

```bash
cp <binary>.unpatched <binary>
codesign --force --sign - --preserve-metadata=entitlements <binary>
```

(The original Anthropic signature can't be restored once bytes are touched; ad-hoc is the only option.)

## Caveats

- macOS / Bun-compiled Mach-O binary only.
- Patches must be re-applied after every Claude Code auto-update.
- If Anthropic restructures the relevant source (function moves, control-flow changes, renamed literals like `"bash"` → `"shell-input"`), the regex anchors fail and the patches need re-deriving. The script aborts cleanly in that case rather than half-patching.

## License

MIT
