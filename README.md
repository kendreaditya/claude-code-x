<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/ccx-logo-dark.svg">
    <img src="assets/ccx-logo-light.svg" alt="ccx" width="200">
  </picture>
</p>

<h1 align="center">claude-code-x</h1>

<p align="center">A universal, provenance-respecting patcher for the Claude Code CLI binary.</p>

---

`ccx` is a version-agnostic patcher for the
[Claude Code](https://claude.com/claude-code) Bun-compiled binary. Patches are
pure data (`registry/<group>/*.ccxpatch.json`); the engine resolves each by a
version-agnostic **landmark anchor**, applies a **same-length byte edit**,
re-signs, and verifies the binary still launches — with a clean revert and a
manifest of everything it changed. Not a fork, not a rebuild.

> **Local-only.** `ccx` patches *your* installed binary. It never redistributes a
> modified Anthropic binary — that would breach Anthropic's ToS/copyright (see
> [CREDITS.md](./CREDITS.md)). The daily release-watch Action publishes patch
> *definitions* + a compatibility report, never the binary.

## Install

```bash
pip install -e .            # exposes the `ccx` entry point
# or run without installing:
./bin/ccx <cmd>
```

Requirements:

- Python ≥ 3.10 (stdlib-only for the same-length engine; no third-party deps)
- macOS or Linux, on the Bun-compiled Mach-O / ELF binary
- An official [Claude Code](https://claude.com/claude-code) install (the patcher
  edits *your* installed binary — it does not ship one)

## Usage

| Command | What it does |
|---------|--------------|
| `ccx latest` | Installed vs. latest published Claude Code version |
| `ccx detect` | Container / version / Bun-trailer / signing facts for the target |
| `ccx list [--archived]` | Patch catalog, grouped, with live applicability |
| `ccx apply <id>… \| --group <g> \| --all-applicable` | Apply patches (cite → back up → edit → re-sign → smoke-test → manifest) |
| `ccx status` | What's applied, re-verified live against the binary |
| `ccx validate-all` | Apply each patch to a throwaway copy and launch-test it |
| `ccx revert <id>… \| --group <g> \| --all` | Surgical undo from the manifest |
| `ccx verify-effect <id>…` | Classify a patch's *runtime* effect (M2) |
| `ccx hook install` | SessionStart hook that re-applies after auto-update |

`apply` also takes `--dry-run`, `--yes/-y`, and `--from-manifest` (used by the
repair hook). A fully interactive picker (`-i`) is planned. Patches select by id,
`--group`, or `--all-applicable`; conflicting patches (overlapping byte spans) are
detected and the later one is skipped.

```console
$ ccx detect
path:       /Users/you/.local/share/claude/versions/2.1.158/claude
version:    2.1.158
container:  macho-arm64-bun
format:     macho
bun:        trailer @ 102,432,768
signed:     adhoc
size:       128,401,232 bytes

$ ccx apply fifo-steering-queue
  [cite] FIFO Steering and Queue Bundling — kendreaditya/claude-code-x

Apply 1 patch(es) to 2.1.158? [y/N] y
  ✓ fifo-steering-queue: applied 3 edit(s); launch=True
```

## Patches

Patches ship grouped by intent. Each definition cites its origin repo; all active
patches are `binary`-level **same-length** edits (no offsets shift). Run
`ccx list` to see live applicability against your installed version.

### behavior

| id | what it does | source |
|----|--------------|--------|
| `fifo-steering-queue` | Make queued input a pure FIFO: no mid-turn `<system-reminder>` steering, no per-mode bundling — each message drains as its own turn | `kendreaditya/claude-code-x` |
| `denerf-system-prompt` | Rewrite the system prompt's "responses should be short and concise" brevity directive to "thorough and clear" | `roman01la/patch-claude-code` |
| `expand-thinking-traces` | Force the `shouldShowFullThinking` gate always-on so thinking blocks render expanded without `ctrl+o` | `aleks-apostle/claude-code-patches` |
| `inline-files-thinking` | Same-length subset of `patch-claude-display`: neutralize the thinking-collapse gate so full thinking streams inline | `a-connoisseur/patch-claude-code` |

### cosmetic

| id | what it does | source |
|----|--------------|--------|
| `plain-thinking-words` | Replace the 187-word whimsical spinner verb pool ("Flibbertigibbeting"…) with a single plain "Thinking" | `ominiverdi/claude-depester` |
| `terminal-title-update` | Flip the one-shot guard so the auto-generated terminal title regenerates on every qualifying message | `antonioacg/claude-code-title-patch` |
| `user-message-color` | Recolor the dark-theme user-message background from grey to blue-600 (both standard + daltonized variants) | `gabinfay/claude-code-color-patch` |

### limits

| id | what it does | source |
|----|--------------|--------|
| `context-limits-compaction` | Raise the context window 200000 → 272000 tokens and the autocompact buffer 13000 → 13600 | `InDreamer/claude-context-patch` |
| `unlock-limits-skills` | Raise the per-skill listing description cap 1536 → 9999 chars so fuller skill descriptions reach the model | `huybuidac/claude-code-patchkit` |

### performance

| id | what it does | source |
|----|--------------|--------|
| `cpu-perf-patches` | Neutralize the unconditional once-per-second forced `Bun.gc` (1000ms → 1e15), killing continuous heap-marking work | `denysvitali/claude-code-patches` |

### privacy

| id | what it does | source |
|----|--------------|--------|
| `channels-no-oauth` | Force the `isChannelsEnabled()` / `tengu_harbor` gate default to true so `--channels` works without claude.ai OAuth | `genusdryasnizhninovgorod936/claude-channels-patch` |

**Archived patches** live in [`registry/_archived/`](./registry/_archived/) (shown
via `ccx list --archived`). A patch is archived when it's *out of scope* for the
same-length byte engine (proxies, alternate builds, prompt-level rule sets,
patching frameworks, source-only patches) **or** when it *broke on a newer
version* — the daily release-watch CI auto-archives any patch whose anchors stop
resolving (or stops launching) on a new release, recording an `archive_reason`
and a compatibility report under [`compat/`](./compat/).

## How it works

Every `ccx apply` is a chain of hard gates — resolve everything before touching a
byte, then write once and atomically swap:

```
DETECT → LOCATE → VERIFY → [confirm] → BACKUP → APPLY → RE-SIGN → SMOKE-TEST → MANIFEST
```

- **Anchor, never offset** — locators are regexes over the embedded plaintext JS,
  gated to the owning Bun CJS module and required to match exactly once, so
  routine minifier-identifier churn between releases is handled automatically.
- **Same-length edits** — equal-byte replacements need no Mach-O fixups, only an
  ad-hoc re-sign; variable-length (LIEF) is gated off until implemented.
- **Owning-module gating** — `in_bun_region` confines matches to the right
  embedded module, avoiding accidental hits elsewhere in the binary.
- **Manifest-based revert** — the manifest stores original/patched bytes for a
  surgical `revert`; `<binary>.unpatched` is the pristine fallback.
- **Conflict detection** — overlapping byte spans across selected patches are
  caught and the later patch is dropped.
- **SessionStart auto-repair** — Claude Code auto-updates write a fresh,
  *unpatched* binary; the installed hook idempotently re-applies your manifest's
  patch set against the new version (recursion-guarded, fast-path on no-op,
  per-binary attempt cap).
- **Honest verification** — marker presence, stable Bun-trailer offset,
  `codesign --verify`, and a launch smoke test (never file-size equality, which
  re-signing changes every run).

Deeper reading: [docs/M2-bytecode-finding.md](./docs/M2-bytecode-finding.md)
(empirical proof plaintext-JS edits change runtime behavior),
[docs/engine-design.md](./docs/engine-design.md),
[docs/cli-design.md](./docs/cli-design.md), and [GOAL.md](./GOAL.md) for the
design and milestones.

## Contributing

Add a patch by dropping a `.ccxpatch.json` file into `registry/<group>/`. The
schema (shared between registry built-ins and user customs — see
[docs/cli-design.md](./docs/cli-design.md) §5):

```jsonc
{
  "schema_version": 1,
  "id": "my-patch",                 // unique, kebab-case
  "name": "Human-readable name",
  "group": "behavior",              // behavior | cosmetic | limits | performance | privacy
  "level": "binary",                // same-length binary edit
  "description": "One paragraph: what it changes and what's intentionally excluded.",
  "provenance": {                   // REQUIRED — credit is mandatory
    "source_repo": "owner/repo",
    "source_url": "https://github.com/owner/repo",
    "author": "owner",
    "license": "unknown",
    "derived_by": "anchored against pristine <version>"
  },
  "applies_to": {
    "containers": ["macho-arm64-bun", "macho-x64-bun", "elf-x64-bun"],
    "version_range": ">=2.1.0 <3.0.0",
    "verified_on": ["2.1.158"]
  },
  "allow_variable_length": false,
  "operations": [
    {
      "op_id": "unique-op-name",
      "kind": "landmark-anchored",
      "rationale": "Why this anchor is structurally stable and unique.",
      "must_be_unique": true,       // anchor must match exactly once
      "same_length": true,          // replacement is byte-for-byte the same length
      "in_bun_region": true,        // confine to the owning embedded module
      "anchor": "(var [A-Za-z0-9_$]{2,5}=)200000(,…)",
      "replace": "\\g<1>272000\\g<2>",
      "patched_anchor": "var [A-Za-z0-9_$]{2,5}=272000,…"
    }
  ]
}
```

The **same-length rule** is load-bearing: `replace` must produce exactly the same
byte count as the matched `anchor` so no offsets shift in the binary. Pad inside a
string literal if you need slack. Capture churned minifier identifiers with
backreferences rather than hard-coding them.

Validate before opening a PR:

```bash
ccx validate-all --group <your-group>   # applies to a throwaway copy + launch-test
ccx list --verbose                       # confirm it resolves uniquely
```

Then PR the file into `registry/<group>/`. A vetted custom patch is promotable to
the registry by the same path (see [docs/cli-design.md](./docs/cli-design.md) §5).

## Attribution & license

`ccx` aggregates patch *techniques and ideas* from the community; every shipped
patch carries a `provenance` block. See [CREDITS.md](./CREDITS.md) and
[PRIOR-ART.md](./PRIOR-ART.md) for the full ledger.

The MIT [LICENSE](./LICENSE) covers **the scripts and `*.ccxpatch.json`
definitions only** — **not** the patched Claude Code binary, which remains
Anthropic's copyrighted work. Patch your own install; do not distribute patched
binaries.
