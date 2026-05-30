# claude-code-x

A set of in-place patches for the [Claude Code](https://claude.com/claude-code) CLI binary that make queued user input behave as a pure FIFO queue — no mid-turn steering, no message bundling.

> **What it is:** small, reversible, same-length byte patches applied to the active Bun-compiled `claude` binary, plus a re-sign step. Not a fork, not a rebuild. Re-run after every auto-update.

## Why

By default, Claude Code "soft-steers" the running turn when you type while it works:

- **Mid-turn injection** — a message you type mid-turn is rendered into the model's context as a `<system-reminder>` ("The user sent a new message while you were working… you MUST address it"). The strong language often makes the model pivot mid-stream.
- **Queue bundling** — multiple queued messages of the same mode are dequeued together and delivered as a *single* user turn, so three quick messages become one combined response.

`claude-code-x` neutralizes both so input behaves as a strict FIFO: **each message gets its own complete turn, in order, with no mid-flight steer.**

> **Where this is heading:** the current script is a single, hard-coded patch.
> The roadmap is a universal, version-aware CLI (`ccx`) that aggregates many
> community patches as selectable, **attributed**, grouped options with a custom
> path — see **[GOAL.md](./GOAL.md)** for the full plan, **[PRIOR-ART.md](./PRIOR-ART.md)**
> for the patches it builds on, **[CREDITS.md](./CREDITS.md)** for attribution
> policy, and **[docs/](./docs/)** for the engine + CLI design. The FIFO patch
> below is the seed, already expressed in the new registry format at
> [`registry/behavior/fifo-steering-queue.ccxpatch.json`](./registry/behavior/fifo-steering-queue.ccxpatch.json).

## Patches

| # | Source location | Behavior killed |
|---|-----------------|-----------------|
| 1 | `attachments.ts` — `INLINE_NOTIFICATION_MODES` | Mid-turn `<system-reminder>` injection for `prompt`-mode messages (keeps `task-notification`, load-bearing for background-agent wake-ups). |
| 2 | `queueProcessor.ts` — `processQueueIfReady` | Per-mode queue bundling. Forces every queued command through the single-item dequeue path. |
| 3 | `query.ts` — mid-turn `removeFromQueue` filter | Mid-turn removal of `prompt`-mode commands. |

All replacements are **same-length** byte sequences, so no offsets shift in the binary. The locator regexes anchor on structurally stable elements (function-signature shape, literal strings) and extract churned minifier identifiers dynamically — so routine minifier-name changes between releases are handled automatically.

## Usage

```bash
./repatch-claude-noqueue.sh
```

The script:

1. Resolves the active binary via `~/.local/bin/claude` → `~/.local/share/claude/versions/<version>`.
2. Saves a pristine `<binary>.unpatched` backup on first patch.
3. Applies all three patches (idempotent — re-running is a no-op if already patched).
4. Re-signs ad-hoc (`codesign --force --sign -`), since the original signature is now invalid.
5. Smoke-tests with `claude --version`.

### Auto-repatch on session start

Claude Code auto-updates write a new, **unpatched** versioned binary. Drop in the SessionStart hook (`claude-session-start-repatch.sh`) to detect and re-apply automatically — it greps the binary for the `q.mode===q.mode` tautology introduced by patch #2 as the "is patched" signal, so there's no sentinel file to drift.

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
