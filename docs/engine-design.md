## Patching Engine

The patching engine is the core of the `claudius-code` universal patcher: the component that takes a declarative **patch definition** and a target Claude Code binary, and safely produces a patched, re-signed, launchable binary — or refuses to touch anything. It is built around one non-negotiable invariant inherited from the binary recon:

> **The JS lives inside the `__BUN` Mach-O segment as raw plaintext. Same-length edits within a module's declared `contents` region invalidate *only* the code signature — nothing else. Every length change cascades into Bun StringPointer fixups + Mach-O `__LINKEDIT` fixups. Therefore: same-length is the default and the fast path; variable-length is an explicit, gated advanced mode.**

The engine has two execution backends behind one interface:

1. **Raw fast-path** (`RawByteEngine`) — pure `read → locate → splice → write`, no parsing library. Handles every same-length / pad-to-length patch (the ~95% case). This is what the existing `repatch-claude-noqueue.sh` already does, generalized.
2. **LIEF resize-path** (`LiefEngine`) — only invoked when a patch declares `allow_variable_length: true` *and* the replacement genuinely cannot be padded to the original length. Parses the container (Mach-O / ELF / PE), splices, fixes Bun StringPointers + container load-commands, rewrites, re-signs.

Both backends feed the same locator, verification, backup, signing, and smoke-test stages.

---

### 1. The patch-apply pipeline

The pipeline is the same for every patch and every backend. Each stage is a hard gate: a failure aborts the whole run **before any bytes are written**, so the binary is never left half-patched. (This "resolve everything up front, then write once" discipline is exactly what the reference `repatch` script does across its three patches.)

```
                       ┌─────────────────────────────────────────────┐
 patch definition ───► │ 0. DETECT  container + version + capability  │
 (JSON)                │    gate — refuse on unknown/unsafe targets   │
                       └───────────────┬─────────────────────────────┘
                                       ▼
                       ┌─────────────────────────────────────────────┐
 target binary  ─────► │ 1. LOCATE   resolve each operation's anchor  │
                       │    → concrete (offset, old_bytes, new_bytes) │
                       └───────────────┬─────────────────────────────┘
                                       ▼
                       ┌─────────────────────────────────────────────┐
                       │ 2. VERIFY   uniqueness + length + in-region  │
                       │    + 3-state idempotency (unpatched/applied/ │
                       │    corrupted) via embedded marker            │
                       └───────────────┬─────────────────────────────┘
                                       ▼   (--dry-run stops here, prints plan)
                       ┌─────────────────────────────────────────────┐
                       │ 3. BACKUP   copy2 → <binary>.unpatched once  │
                       └───────────────┬─────────────────────────────┘
                                       ▼
                       ┌─────────────────────────────────────────────┐
                       │ 4. APPLY    splice all ops; same-length →    │
                       │    RawByteEngine, var-length → LiefEngine    │
                       │    write to <binary>.tmp                     │
                       └───────────────┬─────────────────────────────┘
                                       ▼
                       ┌─────────────────────────────────────────────┐
                       │ 5. RE-SIGN  platform signer (macOS codesign) │
                       └───────────────┬─────────────────────────────┘
                                       ▼
                       ┌─────────────────────────────────────────────┐
                       │ 6. SMOKE    atomic rename; `claude --version`│
                       │    on fail → auto-rollback from backup       │
                       └─────────────────────────────────────────────┘
```

#### Stage 0 — Detect

Read the first bytes to classify the container by magic:

| Magic | Container | Signing action |
|---|---|---|
| `0xFEEDFACF` / `0xCFFAEDFE` / `0xCAFEBABE` | Mach-O (this target) | **mandatory re-sign** (ad-hoc) |
| `0x7F 45 4C 46` (`\x7fELF`) | ELF (Linux) | none |
| `0x4D 5A` (`MZ`) | PE (Windows) | strip/re-sign only if Authenticode present |

Then resolve the version. Prefer the file path (`~/.local/share/claude/versions/<version>`); fall back to grepping a version literal in `__BUN`. Feed `(container, version)` into the capability gate (§2 `applies_to`). **If the version is outside every patch's range, or the container is one the patch doesn't declare support for, the engine refuses to run that patch** — detect-but-skip beats patch-and-break. This is the `taocihei` version-gate lesson made mandatory.

#### Stage 1 — Locate

For each operation in the patch, run its locator (§3) against the in-memory bytes to produce a concrete edit: `{file_offset, old_bytes, new_bytes}`. Locators never hardcode offsets and never assume minified identifiers — they anchor on stable lexical landmarks / strings / AST shape and *derive* the churned identifiers at locate-time.

Critically, the engine also computes the **`__BUN` contents region bounds** `[193_186_496, 193_186_496 + 15_520_011)` for this build (read from the `__BUN` `LC_SEGMENT_64` section, or by locating the `\n---- Bun! ----\n` trailer and parsing the `CompiledModuleGraphFile` records). Every resolved edit offset must fall inside the target module's declared `contents` region — an edit landing in the Bun metadata table or trailer would shift StringPointers and corrupt module resolution.

#### Stage 2 — Verify uniqueness

For each resolved `old_bytes`:

- **Uniqueness:** `data.count(old_bytes) == 1`. If 0 → maybe already patched (check `new_bytes`); if >1 → abort, the anchor is ambiguous and a blind splice could hit the wrong site. The reference script aborts on exactly this condition.
- **Length:** for same-length ops, `len(old) == len(new)`; the engine refuses to run a `same-length` op whose bytes differ in length.
- **In-region:** offset ∈ contents region (Stage 1 bounds).
- **3-state idempotency** (§5): classify the binary as `unpatched` / `already-patched` / `corrupted` per op, using the embedded marker.

`--dry-run` prints the full resolved plan (each op's offset, byte diff, classification) and exits here, having read but never written.

#### Stage 3 — Backup

On the first patch of a given versioned binary, `shutil.copy2(binary, binary + ".unpatched")` — pristine, Anthropic-signed bytes. If the backup already exists, leave it (it is the canonical pristine snapshot; never overwrite it with already-patched bytes). The backup is the rollback source and the corruption-recovery source.

#### Stage 4 — Apply

Splice each op. Same-length ops go through `RawByteEngine` (`bytearray` overwrite at offset). Variable-length ops route to `LiefEngine` (§6). Write the result to `<binary>.tmp` — never edit in place, so a crash mid-write can't destroy the live binary.

#### Stage 5 — Re-sign

On macOS this is **mandatory**: any byte change invalidates the SHA-256 CodeDirectory CDHash, and on Apple Silicon an invalid/missing signature is an immediate `SIGKILL` at launch.

```bash
codesign --force --sign - \
  --preserve-metadata=entitlements,flags,identifier \
  <binary.tmp>
```

`--preserve-metadata=entitlements` is **load-bearing**: Bun's JSC engine needs `allow-jit`, `allow-unsigned-executable-memory`, and `disable-library-validation`. Dropping them re-signs successfully but the patched binary crashes on launch. (The reference script preserves entitlements for exactly this reason.) Off-Mac, `rcodesign sign --code-signature-flags adhoc` is the fallback. Linux: no-op. Windows: strip Authenticode (or `osslsigncode`) only if present — Bun Windows standalones are usually unsigned.

#### Stage 6 — Atomic swap + smoke-test

Atomically `os.replace(binary.tmp, binary)` (rename-while-running is safe; the running process holds the old inode). Then run the binary's own version check:

```bash
"$CLAUDE_LAUNCHER" --version      # must exit 0 and print a version
```

A non-zero exit or `SIGKILL` (bad signature, broken Mach-O, dropped entitlements) triggers **automatic rollback**: restore from `<binary>.unpatched`, re-sign the restored copy ad-hoc, and report failure. The engine never leaves a non-launchable binary in place.

---

### 2. Patch-definition schema

Patches are **declarative JSON** (one file per patch in `patches/`, loaded by the engine). The schema carries provenance, a version gate, and one or more operations. The engine — not the patch file — owns locate/verify/backup/sign; the patch only describes *what* to find and *what* to write.

```jsonc
{
  "schema_version": 1,
  "id": "string (kebab-case, unique, matches catalog id)",
  "name": "Human-readable name",
  "group": "behavior | performance | cosmetic | limits | models | privacy",
  "description": "One-paragraph what-and-why.",

  // ── Provenance / attribution ───────────────────────────────────────────
  "provenance": {
    "source_repo": "owner/repo",
    "source_url": "https://…",
    "license": "MIT | unknown | …",
    "derived_by": "claudius-code",
    "source_landmarks": ["src/utils/attachments.ts", "…"]  // recon anchors
  },

  // ── Capability gate ────────────────────────────────────────────────────
  "applies_to": {
    "containers": ["macho", "elf", "pe"],   // which OS containers supported
    "version_range": ">=2.1.0 <3.0.0",       // semver range; engine skips outside
    "min_bun": "1.3.0"                        // graph-format compatibility hint
  },

  // ── Marker for 3-state idempotency / verification ──────────────────────
  "marker": "q.mode===q.mode",   // a byte sequence that exists ONLY post-patch

  // ── Variable-length opt-in (advanced mode, off by default) ─────────────
  "allow_variable_length": false,

  // ── Operations (all must resolve, or the whole patch aborts) ───────────
  "operations": [
    {
      "op_id": "string, unique within patch",
      "kind": "landmark-anchored | regex-replace | ast-node",
      "must_be_unique": true,
      "same_length": true,        // engine enforces len(old)==len(new)
      "in_bun_region": true,      // require edit inside cli.js contents region

      // for landmark-anchored / regex-replace:
      "anchor": "regex with capture groups for churned identifiers",
      "replace": "template referencing capture groups, e.g. \\g<1>q.mode",

      // idempotency: how to recognize an already-applied op
      "patched_anchor": "regex matching the post-patch bytes",
      "rationale": "why this exact replacement (and not alternatives)"
    }
  ]
}
```

#### Operation kinds (resilience ladder, best → worst)

Ordered exactly by the recon's "anchoring" lesson — prefer the most stable source available:

1. **`landmark-anchored`** *(default, preferred)* — anchor on a stable lexical landmark (user-facing string literal, schema `.describe()` text, protocol value like `"task-notification"`, or distinctive structural token like `.agentId===void 0`) and capture the churned minified identifier dynamically. Survives identifier mangling and whitespace churn. This is what all three FIFO ops use.
2. **`ast-node`** *(structurally robust)* — for edits where text is too fragile, match on Babel/SWC AST node shape rather than text. Tolerates reformatting. Heavier; reserved for control-flow edits where a string anchor doesn't exist.
3. **`regex-replace`** *(general)* — plain anchored regex on the byte stream. Acceptable when anchored on stable literals; degenerates to fragile if it leans on minified names.

The engine refuses any op whose `same_length: true` resolves to a length mismatch, and any op whose anchor matches `!= 1` site (unless `must_be_unique: false` is explicitly set, which is discouraged).

---

### 3. How locators stay version-agnostic

This is the decisive design choice (and the single most-copied idea across every surveyed patcher). Three rules, enforced by the engine:

**(a) Never store offsets.** Offsets shift every release. Locators always re-derive the offset by searching at apply-time. The reference script's locators take `data` and return `(old, new)` freshly each run.

**(b) Anchor on the most stable token available, capture the churned part.** Minifiers rename identifiers (`XFK`, `PFK`, `ZT2`…) every build but cannot rename:
- string literals (`"prompt"`, `"task-notification"`, `"bash"`, `# Output efficiency`),
- protocol/public values (`ANTHROPIC_DEFAULT_OPUS_MODEL`, the `[1m]` alias suffix),
- distinctive structural tokens (`.agentId===void 0`, `q.mode===`).

Example from patch #2: the anchor `([A-Za-z_$0-9]+)\(q\)\|\|q\.mode==="bash"` captures the unstable `isSlashCommand` minified name in group 1 and pins everything else to invariant literals. The replacement reuses the capture, so the patch self-adapts to whatever the identifier is this release.

**(c) Recognize the patched state too.** Each locator tries the unpatched fingerprint first, then the patched fingerprint, deriving `old` from `new`. This makes locate idempotent (re-running on an already-patched binary still resolves cleanly) and is the foundation of 3-state detection.

When all three rules still can't anchor (Anthropic restructured the source — function moved, control flow changed, `"bash"` renamed to `"shell-input"`), the locator raises a typed `PatchError` naming the specific op and pointing at the source landmark to re-derive against. The engine **aborts cleanly** rather than guessing — fail-to-no-op, never patch-and-break.

---

### 4. Idempotency + rollback

**3-state detection** per operation, using the patch's `marker`:

| State | Condition | Action |
|---|---|---|
| `unpatched` | `old` present (count 1), `new`/marker absent | apply |
| `already-patched` | `new`/marker present (count 1), `old` absent | skip (no-op) |
| `corrupted` | neither present, OR `old` count > 1, OR partial (some ops applied, some not) | abort + recommend restore from `.unpatched` |

If **all** ops are `already-patched`, the engine prints `[skip] all patches applied` and exits 0 without backing up or re-signing — exactly the reference script's early-exit. A partial state (mix of patched/unpatched ops on the same binary) is treated as `corrupted`: the engine refuses to "top up," because a half-patched binary plus an unknown edit history is unsafe to reason about; it directs the user to roll back and re-run from pristine.

The `marker` should be a sequence that **cannot occur naturally** in minifier output — e.g. the `q.mode===q.mode` tautology. Its presence is a self-describing "this binary is patched" signal that travels *with the binary*, so there's no sentinel file to drift out of sync (this is what the SessionStart hook greps for).

**Rollback** is a first-class command (`claudius-code restore`):

```bash
cp <binary>.unpatched <binary>
codesign --force --sign - --preserve-metadata=entitlements <binary>
```

The original Anthropic signature can't be restored once bytes are touched, so ad-hoc is the only option — restore returns the *bytes* to pristine, not the original signature. Automatic rollback on smoke-test failure (Stage 6) runs the same path.

---

### 5. Variable-length support (advanced mode)

Recon confirms variable-length is **viable** but high-risk, so the engine treats it as opt-in (`allow_variable_length: true`) and routes it to `LiefEngine`. Three tiers, cheapest first:

**Tier 1 — Pad-to-length (preferred, stays on the fast path).** If the replacement is *shorter* than the original, pad it back to the exact original length using string-/comment-safe filler (semicolons, whitespace, `/*…*/`) so it is *treated as same-length*. This skips **all** fixups — no StringPointer math, no `__LINKEDIT` shifts, no header edits. The recon explicitly calls this the simplest robust trick. The engine attempts this automatically before ever invoking LIEF.

**Tier 2 — LIEF splice + Bun fixups (true growth).** When growth is unavoidable, splice `delta` bytes into `__BUN` and run the coordinated fixup pass:
1. bump the edited module's `contents.len` by `delta`;
2. add `delta` to the `.off` of **every** Bun StringPointer whose target is *after* the edit — all modules' `contents`/`name`/`sourcemap`/`bytecode` pointers **and** the trailer's module/entry pointers (offsets are `__BUN`-relative, so everything downstream moves);
3. update `__bun` section size and the `__BUN` `LC_SEGMENT_64` `filesize`/`vmsize`, re-padded to 16K alignment;
4. shift `__LINKEDIT` `fileoff`/`vmaddr` and every LINKEDIT-referencing load command (`LC_SYMTAB`, `LC_DYSYMTAB`, `LC_FUNCTION_STARTS`, `LC_DATA_IN_CODE`, `LC_DYLD_INFO`/`EXPORTS_TRIE`, `LC_CODE_SIGNATURE`) by `delta + pad`.

LIEF performs the container-level segment resize and load-command fixups natively across Mach-O/ELF/PE from one API — matching the cross-platform Bun graph format. The engine's job is the **Bun-graph** half (StringPointer fixups), which LIEF does not know about.

**Tier 3 — strip + rebuild signature.** Easiest robust finish: strip the old `LC_CODE_SIGNATURE`, let LIEF write the container, then `codesign -f -s -` recomputes `dataoff`/size and writes a fresh CodeDirectory.

**Guardrails the engine enforces in this mode:** preserve 16K alignment of `__BUN`/`__LINKEDIT`; verify post-write that the `\n---- Bun! ----\n` trailer is intact and every module's `contents` slice still decodes as plaintext JS; refuse if any StringPointer would point outside the resized segment. Given the interdependence ("one missed StringPointer corrupts module resolution"), the engine logs a loud warning that variable-length is best-effort and always runs an extended smoke-test (launch + a trivial prompt round-trip) before committing the atomic swap.

> Open caveat surfaced to the user, not silently assumed: the module is tagged `@bytecode`. If this build executes a parallel JSC bytecode blob instead of the plaintext source, editing only the plaintext has **no runtime effect**. The engine therefore ships a `verify-effect` post-check that launches the patched copy and confirms the behavioral change actually took — for any new patch family, "it patched cleanly" is not accepted as "it works."

---

### 6. SessionStart auto-repatch hook

Claude Code auto-updates write a **new, unpatched** versioned binary and repoint `~/.local/bin/claude` at it. A `SessionStart` hook (matcher: `startup`) detects this and re-applies before the new behavior takes effect.

Design (matching the shipped `claude-session-start-repatch.sh`, generalized to the patch set):

- **In-binary detection, not a sentinel file.** `grep -q '<marker>'` on the resolved binary. The marker (e.g. `q.mode===q.mode`) travels with the binary, so it can't drift out of sync with a sidecar state file. Grep on the 200 MB binary is <10 ms — cheap enough for every startup.
- **Fast path:** marker present → exit 0 silently.
- **Repatch path:** marker absent (an update landed) → run the engine's apply pipeline, logging to `/tmp/claudius-repatch.log`.
- **Recursion guard:** the engine's smoke-test spawns `claude --version`, which would re-enter the hook. Guard with an env flag (`CLAUDIUS_REPATCH_INFLIGHT=1`) and exit early if set.
- **Non-blocking failure:** `SessionStart` exit codes can block the session, so on patch failure the hook logs + warns to stderr but **exits 0** — a failed repatch must never prevent the user from starting a session. The warning points at the log and notes the byte fingerprints may need re-deriving for the new release.

Registration (`~/.claude/settings.json`):

```json
{
  "hooks": {
    "SessionStart": [
      { "matcher": "startup",
        "hooks": [{ "type": "command",
                    "command": "~/.config/scripts/claudius-session-start-repatch.sh" }] }
    ]
  }
}
```

---

### 7. Concrete patch definition — the FIFO/noqueue patch

This is the `fifo-steering-queue` catalog entry (`kendreaditya/claudius-code`), expressed in the schema. It carries all three operations from the reference script, each anchored on stable literals with the churned minified identifier captured dynamically.

```json
{
  "schema_version": 1,
  "id": "fifo-steering-queue",
  "name": "FIFO Steering and Queue Bundling",
  "group": "behavior",
  "description": "Makes queued user input behave as a pure FIFO queue: no mid-turn <system-reminder> steering of the running turn, and no bundling of multiple queued messages into one turn. Each message gets its own complete turn, in order.",
  "provenance": {
    "source_repo": "kendreaditya/claudius-code",
    "source_url": "https://github.com/kendreaditya/claudius-code",
    "license": "MIT",
    "derived_by": "claudius-code",
    "source_landmarks": [
      "src/utils/attachments.ts (INLINE_NOTIFICATION_MODES Set)",
      "src/utils/queueProcessor.ts (processQueueIfReady bash branch)",
      "src/query.ts (mid-turn removeFromQueue filter)"
    ]
  },
  "applies_to": {
    "containers": ["macho", "elf", "pe"],
    "version_range": ">=2.1.0 <3.0.0",
    "min_bun": "1.3.0"
  },
  "marker": "q.mode===q.mode",
  "allow_variable_length": false,
  "operations": [
    {
      "op_id": "inline-notification-modes-drop-prompt",
      "kind": "landmark-anchored",
      "must_be_unique": true,
      "same_length": true,
      "in_bun_region": true,
      "anchor": "new Set\\(\\[\"prompt\",\"task-notification\"\\]\\)",
      "replace": "new Set([\"__off_\",\"task-notification\"])",
      "patched_anchor": "new Set\\(\\[\"__off_\",\"task-notification\"\\]\\)",
      "rationale": "Remove 'prompt' from INLINE_NOTIFICATION_MODES so user-typed messages are never emitted as queued_command attachments mid-turn. '__off_' (6 bytes) replaces 'prompt' (6 bytes) — same length, never matches any real PromptInputMode. 'task-notification' kept: load-bearing for background-agent / SleepTool wake-ups. 39 bytes in, 39 bytes out."
    },
    {
      "op_id": "queueprocessor-force-single-item",
      "kind": "landmark-anchored",
      "must_be_unique": true,
      "same_length": true,
      "in_bun_region": true,
      "anchor": "([A-Za-z_$0-9]+)\\(q\\)\\|\\|q\\.mode===\"bash\"",
      "replace": "\\g<1>(q)||q.mode===q.mode",
      "patched_anchor": "([A-Za-z_$0-9]+)\\(q\\)\\|\\|q\\.mode===q\\.mode",
      "rationale": "In processQueueIfReady, the gate `isSlashCommand(q)||q.mode===\"bash\"` routes commands to the single-item dequeue path; everything else is bundled via dequeueAllMatching. Replacing the \"bash\" literal with `q.mode` makes the gate `q.mode===q.mode` — tautologically true — so EVERY queued command drains one-at-a-time as its own turn and the bundling path is unreachable. Capture group 1 absorbs the churned isSlashCommand minified name. \"bash\" (6 bytes incl. quotes) → q.mode (6 bytes): same length. Chosen over flipping === to !== (would regress bash to bundling) and over other 4-char literals (break uniqueness or match no real mode). Also serves as the project marker."
    },
    {
      "op_id": "query-midturn-remove-drop-prompt",
      "kind": "landmark-anchored",
      "must_be_unique": true,
      "same_length": true,
      "in_bun_region": true,
      "anchor": "([A-Za-z_$0-9]+)\\.mode===\"prompt\"\\|\\|\\1\\.mode===\"task-notification\"",
      "replace": "\\g<1>.mode===\"__off_\"||\\g<1>.mode===\"task-notification\"",
      "patched_anchor": "([A-Za-z_$0-9]+)\\.mode===\"__off_\"\\|\\|\\1\\.mode===\"task-notification\"",
      "rationale": "Mid-turn, query.ts computes consumedCommands = snapshot.filter(mode==='prompt'||mode==='task-notification') and removeFromQueue()s them. Rewriting the 'prompt' literal to '__off_' (both 6 bytes) stops prompt-mode commands from being consumed/removed mid-turn, so they survive to drain as their own post-turn turns. The backreference \\1 forces both comparisons to use the same captured minified var, guaranteeing we matched one real OR-filter and not two unrelated sites. 'task-notification' branch preserved so subagent notifications still drain. Same length."
    }
  ]
}
```

**How the engine runs this definition end-to-end:**

1. **Detect** Mach-O, version `2.1.158` ∈ `>=2.1.0 <3.0.0` → gate passes.
2. **Locate** all three ops; each anchor resolves to exactly one site, capturing the churned identifiers (`isSlashCommand` name, the filter var) fresh for this build. Compute the `__BUN` contents region and confirm all three offsets fall inside `cli.js`.
3. **Verify** each `same_length: true` op is byte-balanced (39/39, 23/23, etc.), each is unique, and run 3-state detection via the `q.mode===q.mode` marker. If all three already applied → skip+exit 0.
4. **Backup** → `<binary>.unpatched` (first run only).
5. **Apply** all three via `RawByteEngine` (no LIEF — same-length), write `<binary>.tmp`.
6. **Re-sign** ad-hoc with `--preserve-metadata=entitlements,flags,identifier` (keeps JIT/unsigned-memory entitlements so JSC doesn't crash).
7. **Atomic swap** + `claude --version` smoke-test; on failure auto-restore from `.unpatched`.

Files in the reference implementation this design generalizes: `/Users/kendreaditya/workspace/claudius-code/repatch-claude-noqueue.sh` (the three locators, same-length discipline, abort-before-write, ad-hoc re-sign), `/Users/kendreaditya/workspace/claudius-code/claude-session-start-repatch.sh` (marker-grep detection, recursion guard, non-blocking exit 0), and `/Users/kendreaditya/workspace/claudius-code/README.md` (rollback procedure, caveats).
