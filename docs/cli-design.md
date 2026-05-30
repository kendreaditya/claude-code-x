# claude-code-x — Universal Patcher: CLI UX + Architecture Design

`claude-code-x` (binary name: `ccx`) is a universal, version-aware, provenance-respecting patcher for the Bun-compiled Claude Code CLI. It applies curated community patches (and user-supplied custom patches) using the highest-resilience intervention layer a given target version supports, always citing the origin repo/author/license, recording a manifest of what was applied, and supporting clean revert.

This document specifies the command surface, group presentation/selection, the custom-patch path, the source-citation system, version detection + compatibility resolution, and the repo/file layout. Implementation language is chosen and justified at the end.

---

## 1. Design principles (carried from the technique lessons)

These directly encode the synthesized lessons from the surveyed projects and the binary-method analysis:

1. **Tiered intervention ladder, highest-resilience-first.** For every patch, prefer the most update-proof layer the target supports: `proxy` (API boundary) > `runtime` (NODE_OPTIONS preload) > `source` (AST/regex on cli.js) > `binary` (LIEF/byte-splice). The selected layer is recorded per-application.
2. **Anchor, never offset.** Resolve every edit by stable lexical landmark, user-facing/schema string, or AST node shape — never hardcoded byte offsets or minified identifiers. The catalog's `landmark_anchor` fields are first-class data.
3. **Same-length fast-path.** For binary edits, prefer equal-length / pad-to-length replacement (no Mach-O/ELF/PE fixups, only re-sign). Fall back to LIEF segment-resize + offset fixups only when a true length change is unavoidable.
4. **Detect-but-skip beats patch-and-break.** A version-detection gate maps version ranges to applicable patch families and refuses to run on unknown/unsafe targets.
5. **Three-state idempotency.** Every patch is detectable as `unpatched` / `applied` / `corrupted` via an embedded marker, before any mutation.
6. **Safe-open / fail-to-no-op.** Any patch that cannot reproduce its precondition (anchor not found, fingerprint mismatch) becomes a no-op rather than a guess.
7. **Provenance is mandatory.** No patch applies without printing its source repo, author, and license; everything applied is written to a manifest.
8. **Backup before mutate, atomic swap, verify after.** Timestamped backup, atomic rename-while-running, size + signature + launch validation.

---

## 2. Command surface

Top-level binary: `ccx`. Global flags available on every subcommand:

| Flag | Effect |
|---|---|
| `--target <path>` | Explicit path to the Claude Code binary/install (otherwise auto-detected; see §7). |
| `--dry-run` | Resolve and plan everything, print the diff/plan, mutate nothing. |
| `--yes` / `-y` | Skip interactive confirmations (for scripts / hooks). |
| `--json` | Machine-readable output (for hooks, CI, the SessionStart auto-repair path). |
| `--no-color` | Plain output. |
| `--profile <name>` | Named manifest profile (e.g. `work`, `experimental`) so multiple patch sets can coexist. |

### 2.1 `ccx list`

Lists the patch catalog **grouped by group**, annotated with applicability against the detected target.

```
$ ccx list
Target: Claude Code 2.1.158  (Bun 1.3.14, macOS arm64, adhoc-signed)
Engine availability: binary ✓   source ✗ (native build)   runtime ✓   proxy ✓

behavior  (6)
  [ ]  denerf-system-prompt        De-nerf System Prompt          source* → binary fallback   ✓ applicable
  [✓]  fifo-steering-queue         FIFO Steering & Queue Bundling binary                       ✓ applicable   APPLIED
  [ ]  expand-thinking-traces      Expand Thinking Traces         binary                       ✓ applicable
  [ ]  advisor-to-doer             Advisor-to-Doer Mode           prompt                        ✓ applicable
  [!]  babel-ast-patcher           Babel AST Patcher              source                        ✗ N/A (native 2.1.x)
  [ ]  inline-files-thinking       Inline Files & Streamed Think  binary                       ✓ applicable

performance  (4)
  [ ]  cpu-perf-patches            CPU/Performance Patches        binary                       ✓ applicable
  [ ]  trim-system-prompt          Trim System Prompt             source* → binary fallback   ✓ applicable
  [ ]  prompt-cache-fix-proxy      Prompt-Cache Regression Fix    proxy                         ✓ applicable
  [!]  centos7-build              CentOS 7 Compatible Builds     build                         ✗ N/A (macOS target)

cosmetic (4) · limits (2) · models (2) · privacy (1)   — run `ccx list --group cosmetic` to expand
```

Legend: `[ ]` unpatched · `[✓]` applied · `[!]` not applicable / blocked · `*` higher-resilience layer unavailable, will use fallback. Flags: `--group <g>` (filter), `--applicable` (hide N/A), `--verbose` (show anchors + source repo inline).

### 2.2 `ccx status`

Reports on the current install: detected version, container/signing facts, and what the manifest says is applied — re-verified live against the binary (three-state).

```
$ ccx status
Target:   /Users/.../@anthropic-ai/claude-code/cli  (2.1.158, Bun 1.3.14)
Container: Mach-O arm64 · __BUN segment present · adhoc-signed (com.anthropic.claude-code)
Backup:    cli.bak.2026-05-30T17-22-04Z (140,951,552 bytes — matches expected)
Profile:   default

Applied patches (manifest: ~/.claude-code-x/manifests/default.json):
  fifo-steering-queue   binary   applied ✓ (marker found, signature valid, launches OK)
  plain-thinking-words  binary   CORRUPTED ✗ (marker present but anchor region altered)

Drift check: 1 patch in manifest no longer verifies → run `ccx doctor`.
```

### 2.3 `ccx apply`

Applies one or more patches. Forms:

- `ccx apply <id> [<id> ...]` — apply specific patches by id.
- `ccx apply --group <g>` — apply all applicable patches in a group (`§3`).
- `ccx apply --interactive` (alias `ccx apply -i`) — checkbox menu grouped by group (`§3`).
- `ccx apply --all-applicable` — apply every patch the version gate marks applicable (requires `-y` or confirmation).

Every `apply` run performs, in order: (1) version-detect + gate (§7); (2) resolve anchors / select engine layer per patch; (3) three-state precheck; (4) **print source citation block** (§6) and a plan; (5) confirm (unless `-y`); (6) timestamped backup; (7) mutate via the engine; (8) re-sign if needed; (9) verify (marker + size + signature + optional launch smoke test); (10) write/update manifest. `--dry-run` stops after step (4) and prints the plan/diff.

```
$ ccx apply expand-thinking-traces
Resolving against 2.1.158 … layer=binary (same-length fast-path) … anchor found ✓

  Patch:    expand-thinking-traces  "Expand Thinking Traces by Default"
  Group:    behavior
  Source:   aleks-apostle/claude-code-patches
  Author:   aleks-apostle
  License:  unknown  ⚠  (educational/as-is — review before redistribution)
  Layer:    binary, same-length replacement (no offset fixups; re-sign only)
  Anchor:   `isTranscriptMode || verbose` gate near paddingLeft:2 thinking render

Plan:
  - backup → cli.bak.2026-05-30T17-31-10Z
  - 1 same-length edit in __BUN cli.js region (file 193,186,496 .. +15,520,011)
  - re-sign: codesign -f -s - --preserve-metadata=entitlements,flags,identifier
  - verify: marker, size unchanged, codesign -vvv, launch smoke test

Proceed? [y/N]
```

### 2.4 `ccx apply --interactive` (checkbox menu by group)

A grouped, collapsible checkbox TUI. Groups are headers; patches are checkbox rows. Space toggles a row; toggling a group header toggles all applicable children. N/A rows are shown disabled with the reason. Already-applied rows are pre-checked and dimmed (re-toggling them off stages a revert). The bottom bar shows a live plan summary (how many edits, which layers, whether re-sign/restart needed).

```
Select patches to apply   (space toggle · g toggle group · a all-applicable · enter confirm)

▾ behavior
   [x] De-nerf System Prompt           source→binary   roman01la (license: unknown ⚠)
   [x] FIFO Steering & Queue Bundling  binary          kendreaditya  ← already applied
   [ ] Expand Thinking Traces          binary          aleks-apostle
   [-] Babel AST Patcher               N/A: native 2.1.x build (source layer unavailable)
▸ performance  (3 applicable, 1 N/A)
▸ cosmetic     (4 applicable)
▾ limits
   [ ] Unlock Limits via Agent Skills  binary          huybuidac (MIT)
   [ ] Context Limits & Compaction     binary          InDreamer (license: unknown ⚠)

Plan: 2 to apply · 1 already applied · layers: binary×2, source×0 · re-sign required · restart Claude after
[ Confirm ]   [ Cancel ]
```

### 2.5 `ccx apply --group <g>`

Non-interactive batch over a group. Equivalent to selecting all *applicable* patches in that group. Prints one combined citation block (all sources/licenses) and one plan, then a single confirmation. Conflicting patches within a group (two patches touching the same anchor region) are detected at plan time and the user is asked to pick one.

### 2.6 `ccx revert`

Restores via the **manifest + backup**, not by blind file swap. Forms:

- `ccx revert <id>` — reverse a single patch (uses the stored inverse: original bytes for binary, AST-inverse for source, unregister for runtime/proxy).
- `ccx revert --group <g>` — reverse all applied patches in a group.
- `ccx revert --all` — restore the pristine backup, clearing the manifest.
- `ccx revert --to <backup>` — restore a specific timestamped backup.

Single-patch revert prefers a **surgical inverse** (re-apply the recorded original bytes at the re-located anchor, then re-sign) so that other applied patches survive. If the surgical inverse can't verify, it offers to fall back to a full pristine-backup restore + replay of the remaining manifest entries.

### 2.7 `ccx doctor`

Health + repair. Runs the full diagnostic and offers fixes:

- Re-detect version; flag if `claude update` changed the binary out from under the manifest (size/hash drift).
- Re-verify every manifest entry (three-state): report `applied` / `corrupted` / `missing (overwritten by update)`.
- Validate signing (`codesign -dvvv`) and entitlements preservation; warn if JIT/unsigned-memory entitlements were lost.
- Offer **auto-repair**: re-resolve anchors against the new version and re-apply the manifest's patch set (this is the path the SessionStart hook calls in `--yes --json` mode).
- Offer to install/repair the SessionStart auto-repair hook.
- Backup hygiene: list backups, prune with `--prune`.

```
$ ccx doctor
✓ Target detected: 2.1.160  (was 2.1.158 in manifest — binary changed)
⚠ claude update overwrote the binary; 2 manifest patches no longer present.
✓ Anchors re-resolved against 2.1.160 for both patches.
? Re-apply [fifo-steering-queue, expand-thinking-traces] to 2.1.160? [Y/n]
✓ Re-applied · re-signed · launch smoke test passed.
? Install SessionStart hook to auto-repair on every launch? [y/N]
```

### 2.8 `ccx credits`

Prints the full provenance ledger (§6): for every patch in the catalog (or with `--applied`, only those in the active manifest), its origin repo, author, license, intervention level, and a thank-you/attribution block suitable for a NOTICE file. `--format md|json|notice` controls output. This is the standing answer to "where did each patch come from and what may I do with it."

### 2.9 `ccx custom`

User-supplied patches (§5). Subforms:

- `ccx custom add --find <str> --replace <str> [--anchor <str>] [--same-length] [--group <g>] [--name ...]` — define an ad-hoc find/replace patch inline.
- `ccx custom apply <file.ccxpatch.json>` — load and apply a patch-definition file.
- `ccx custom scaffold > my.ccxpatch.json` — emit a template patch definition.
- `ccx custom validate <file>` — lint a definition (anchor resolves? length policy sane? marker unique?) without applying.
- `ccx custom list` — show user patches registered under `~/.claude-code-x/registry/`.

### 2.10 Misc

- `ccx hook install|remove` — manage the SessionStart auto-repair hook.
- `ccx version` / `ccx --version`.
- `ccx detect` — print only the version/compat resolution (useful in scripts).

---

## 3. How groups are presented and selected

Groups are the primary organizing axis everywhere a patch list appears. The fixed group set comes straight from the catalog: **behavior, performance, cosmetic, limits, models, privacy** (plus pseudo-levels surfaced as badges: `build`, `manager`, `proxy`, `prompt`, `source`, `binary`).

Presentation rules:

- **`list` / `status`**: patches are bucketed under group headers with a per-group count; each row shows id, name, intervention level badge, applicability, and applied-state. Collapsed groups expand with `--group`.
- **`apply -i` (checkbox menu)**: groups are collapsible section headers; each contains checkbox rows. A header toggle selects/deselects all *applicable* children. N/A children render disabled with the gating reason inline (never silently hidden — transparency over tidiness). Already-applied rows are pre-checked and dimmed.
- **`apply --group <g>`**: selects the whole applicable set of a group in one shot.
- **Conflict handling within a group**: two patches whose resolved anchor regions overlap (e.g. two `source`-level system-prompt rewrites both targeting `# Output efficiency`) are flagged at plan time; the user picks one or aborts. This is computed from the resolved anchor spans, not from static metadata, so it stays correct across versions.

Selection state is staged in memory; nothing mutates until confirmation. The plan summary always states cross-cutting consequences once (re-sign required, restart Claude needed, backup created) rather than per-patch.

---

## 4. Intervention layer selection (the resilience ladder)

For each selected patch, the engine resolves the **best available layer** for the detected target, recorded in the manifest:

1. `proxy` — preferred when the change is payload-observable (e.g. `prompt-cache-fix-proxy`). Decoupled from the binary; survives `claude update`. Implemented as a local `/v1/messages` interceptor with hot-reloadable extension modules and a fingerprint re-verify / fail-to-no-op invariant.
2. `runtime` — `NODE_OPTIONS` preload that reassigns/wraps functions in-process. Non-destructive; survives updates structurally. Anchors still matter (minified symbol drift).
3. `source` — AST (preferred) or regex edit of `cli.js`. Only when the target ships an editable `cli.js` (legacy 2.0.x). Auto-skipped on native 2.1.x builds.
4. `binary` — LIEF parse/edit/repack of the Bun container, with a **raw same-length fast-path** that needs no LIEF (find unique substring in the `__BUN` cli.js region, overwrite equal-length, re-sign). LIEF segment-resize + full offset fixups are used only for unavoidable length changes. Required for native 2.1.x+.

Each catalog patch declares an ordered list of acceptable layers (`prefer: [proxy, runtime, source, binary]`); the resolver intersects that with **what the detected version actually supports** and picks the top survivor. If none survive, the patch is `N/A` and shown disabled.

Binary specifics baked into the engine (from the method analysis):
- Locate JS by `rfind("\n---- Bun! ----\n")` then parse the trailer + `CompiledModuleGraphFile` records, or read `__BUN` section bounds from `LC_SEGMENT_64`; offsets are `__BUN`-relative.
- Default to same-length / pad-to-length to avoid touching headers, segment sizes, StringPointers, and the trailer.
- macOS: always re-sign `codesign -f -s - --preserve-metadata=entitlements,flags,identifier` (must keep `allow-jit` / `allow-unsigned-executable-memory` or JSC crashes); `rcodesign` as off-Mac fallback. Linux: no signing. Windows: strip/re-sign Authenticode only if present.
- Variable-length path: splice, fix the edited module's `contents.len`, add delta to every StringPointer whose target is after the edit, update `__bun` sectsize + `__BUN` filesize/vmsize (16K realign), shift `__LINKEDIT` and all LINKEDIT-referencing load commands, then strip old `LC_CODE_SIGNATURE` and let `codesign -f -s -` rebuild.

---

## 5. The CUSTOM option

`ccx custom` lets users define their own patches without forking the tool, using the same engine, citation, manifest, backup, verify, and revert machinery as built-ins.

Two entry modes:

**(a) Inline find/replace** — quick one-off:
```
ccx custom add \
  --name "force-opus-1m" \
  --group models \
  --anchor 'process.env.ANTHROPIC_MODEL' \
  --find  'process.env.ANTHROPIC_MODEL||' \
  --replace 'process.env.ANTHROPIC_MODEL||"claude-opus-4-8[1m]"||' \
  --same-length=false
```
The `--anchor` scopes the search so `--find` is only matched in the right region (mirrors the context-guard pattern). If `--same-length` is omitted, the engine auto-detects whether lengths match and chooses fast-path vs LIEF-resize. The user is warned and prompted because a self-authored edit has no provenance vetting.

**(b) Patch-definition file** (`*.ccxpatch.json`) — versionable, shareable, reviewable. Same schema as registry entries (§8), so a good custom patch can be promoted into the registry by PR. `ccx custom scaffold` emits this template:

```json
{
  "id": "my-custom-patch",
  "name": "My Custom Patch",
  "group": "behavior",
  "description": "What this does and why.",
  "source": { "repo": "local/me", "author": "me", "license": "unlicensed-local" },
  "prefer": ["source", "binary"],
  "compat": { "min": "2.0.0", "max": null, "exclude": [] },
  "anchors": [
    { "id": "main", "kind": "string", "value": "isTranscriptMode||verbose" }
  ],
  "edits": [
    {
      "layer": "binary",
      "anchor": "main",
      "find": "isTranscriptMode||verbose",
      "replace": "true/*ccx:my-custom-patch*/   ",
      "length_policy": "same-or-pad",
      "marker": "ccx:my-custom-patch"
    }
  ],
  "verify": { "marker": "ccx:my-custom-patch", "launch_smoke_test": true }
}
```

Key custom-mode behaviors:
- **Same engine, same safety**: backup, three-state precheck, dry-run, marker-based idempotency, re-sign, verify, and `ccx revert <id>` all work identically.
- **Forced provenance**: a custom patch must carry a `source` block; if the user authored it, it is recorded as `local/<user>` with license `unlicensed-local`, and `ccx credits` lists it distinctly under a "Local / user-supplied" section so applied state is never misattributed to a community author.
- **Validation gate**: `ccx custom validate` checks anchor resolves uniquely, marker is unique and absent pre-apply, and the length policy is achievable; refuses ambiguous matches (>1 hit) to avoid clobbering.
- **Length policy**: `same` (must match), `same-or-pad` (pad replacement with comment/whitespace in a string-safe context to hit length), or `resize` (allow LIEF variable-length path).

---

## 6. Source-citation system

Provenance is enforced at three touchpoints:

**(1) On apply — mandatory citation block.** Before any mutation (and always in `--dry-run`), `ccx` prints, per patch: source repo, author, license, intervention level, and the resolved anchor. Licenses are normalized to an SPDX-ish enum (`MIT`, `unknown`, `unlicensed`, `educational-only`, `unlicensed-local`). Anything not clearly redistributable (`unknown` / `educational-only` / `unlicensed`) prints a `⚠` advisory ("source license is X — review before redistribution"). This makes the legal posture visible exactly when the user acts. (Catalog reality: many entries are `unknown`; the MIT-safe internals to lean on are patchkit, depester, cache-fix.)

**(2) Generated manifest — what's applied + provenance.** Each successful apply appends/updates an entry in `~/.claude-code-x/manifests/<profile>.json`:

```json
{
  "schema": 1,
  "profile": "default",
  "target": {
    "path": "/Users/.../@anthropic-ai/claude-code/cli",
    "version": "2.1.158", "bun": "1.3.14",
    "container": "macho-arm64", "signed": "adhoc-com.anthropic.claude-code",
    "original_size": 140951552,
    "original_sha256": "…"
  },
  "applied": [
    {
      "id": "fifo-steering-queue",
      "name": "FIFO Steering and Queue Bundling",
      "group": "behavior",
      "layer": "binary",
      "applied_at": "2026-05-30T17:31:10Z",
      "ccx_version": "0.4.0",
      "source": { "repo": "kendreaditya/claude-code-x", "author": "kendreaditya", "license": "unknown" },
      "anchor_resolved": "new Set([\"prompt\",\"task-notification\"])",
      "marker": "ccx:fifo-steering-queue",
      "edits": [ { "file_offset": 193186496, "len": 47, "original_b64": "…", "patched_b64": "…", "same_length": true } ],
      "backup": "cli.bak.2026-05-30T17-31-10Z",
      "resign": { "tool": "codesign", "preserved": ["entitlements","flags","identifier"] }
    }
  ]
}
```

The manifest is the single source of truth for `status`, `revert`, `doctor`, and the SessionStart re-apply — it records *exactly what changed and where it came from*, including the original bytes (base64) for surgical inverse revert.

**(3) `ccx credits` — standing ledger.** Renders provenance for the catalog or just the applied set, exportable as Markdown / JSON / a NOTICE file. This is what ships in the project's `CREDITS.md` and what a user runs to honor attribution before sharing a patched build.

```
$ ccx credits --applied
Patches currently applied (profile: default)

  FIFO Steering and Queue Bundling
    repo:    kendreaditya/claude-code-x
    author:  kendreaditya
    license: unknown  ⚠ review before redistribution
    level:   binary

Community internals reused by the engine:
  LIEF unpack/repack pattern .................. ominiverdi/claude-depester (MIT)
  context-guard / marker idempotency .......... huybuidac/claude-code-patchkit (MIT)
  API-boundary proxy + fail-to-no-op .......... cnighswonger/claude-code-cache-fix (MIT)
  version-gate + capability matrix ............ taocihei/claude-code-patcher-next (MIT)
```

---

## 7. Version detection + compatibility resolution

Pipeline run at the start of `list`, `status`, `apply`, `doctor`, `detect`:

1. **Locate target.** `--target` if given; else multi-path install detection across node version managers / global npm / Homebrew / known `@anthropic-ai/claude-code` locations (borrowed multi-tier detection). Resolve symlinks to the real `cli`.
2. **Identify container + build.** Sniff Mach-O / ELF / PE; detect the Bun standalone graph via `\n---- Bun! ----\n`; read embedded Bun version (`Bun v1.3.14`) and Claude Code version (package metadata or an embedded version string). Record signing state (`codesign -dvvv` on macOS).
3. **Classify format.** `native-bun-binary` (2.1.x+, JS sealed in `__BUN`), `legacy-cli-js` (2.0.x editable `cli.js`), or `unknown`.
4. **Capability matrix.** A table maps `(version range, container/format)` → which intervention layers are available:

   | Format | proxy | runtime | source | binary |
   |---|---|---|---|---|
   | native-bun-binary (2.1.x+) | ✓ | ✓ | ✗ | ✓ |
   | legacy-cli-js (2.0.x) | ✓ | ✓ | ✓ (AST/regex) | ✓ |
   | unknown | ✓ (payload-only) | ✓ | ✗ | ✗ (refuse) |

5. **Per-patch gating.** For each patch, intersect its `compat` range + `prefer` layer list with the matrix and with **live anchor resolution** (does the landmark actually exist in this binary?). Outcomes: `applicable(layer)`, `N/A(reason)`, or `blocked(anchor-not-found)`. Anchor resolution is what lets a patch survive minor version bumps without metadata edits, and what makes the tool *detect-but-skip* on structural change rather than corrupt the binary.
6. **Idempotency probe.** Marker scan classifies each as `unpatched` / `applied` / `corrupted` before planning.

The matrix is data (`core/compat-matrix.json`), so new versions/formats are onboarded without code changes. Unknown/unsafe targets default to refusal (`apply` aborts; `list`/`status` still inform).

---

## 8. Repository / file layout

```
claude-code-x/
├─ bin/
│  └─ ccx                      # CLI entrypoint (arg parse → command dispatch)
├─ core/                       # the engine (container-aware, layer-aware)
│  ├─ detect.py                # install location, container sniff, version + Bun + signing
│  ├─ compat.py                # capability matrix + per-patch gating
│  ├─ compat-matrix.json       # data: (version,format) → available layers
│  ├─ anchors.py               # anchor resolver: string / lexical-landmark / AST node
│  ├─ idempotency.py           # three-state detection, marker scan
│  ├─ engines/
│  │  ├─ binary_raw.py         # same-length / pad-to-length byte splice (no LIEF), Bun graph locate
│  │  ├─ binary_lief.py        # LIEF parse/resize/repack for variable-length (Mach-O/ELF/PE)
│  │  ├─ source_ast.py         # Babel/AST + regex edits on cli.js (legacy)
│  │  ├─ runtime_preload.py    # NODE_OPTIONS=-r/--import preload generation + registry
│  │  └─ proxy_boundary.py     # /v1/messages interceptor, hot-reload .mjs extensions, fail-to-no-op
│  ├─ sign.py                  # codesign / rcodesign / signtool / osslsigncode wrappers
│  ├─ backup.py                # timestamped backup, atomic rename-while-running, prune
│  ├─ manifest.py              # read/write/verify manifests, surgical inverse data
│  ├─ verify.py                # marker + size + signature + launch smoke test
│  └─ plan.py                  # selection → resolved plan, conflict detection
├─ registry/                   # one file per patch definition (the catalog as data)
│  ├─ behavior/
│  │  ├─ denerf-system-prompt.ccxpatch.json
│  │  ├─ fifo-steering-queue.ccxpatch.json
│  │  ├─ expand-thinking-traces.ccxpatch.json
│  │  ├─ advisor-to-doer.ccxpatch.json
│  │  ├─ inline-files-thinking.ccxpatch.json
│  │  └─ babel-ast-patcher.ccxpatch.json
│  ├─ performance/  (cpu-perf, trim-system-prompt, prompt-cache-fix-proxy, centos7-build)
│  ├─ cosmetic/     (plain-thinking-words, companion-pet, user-message-color, terminal-title)
│  ├─ limits/       (unlock-limits-skills, context-limits-compaction)
│  ├─ models/       (model-aliases, local-model-runnable)
│  └─ privacy/      (channels-no-oauth)
├─ cli/
│  ├─ commands/                # list, status, apply, revert, doctor, credits, custom, hook, detect
│  ├─ interactive.py           # grouped checkbox TUI (apply -i)
│  └─ render.py                # group rendering, citation blocks, plan summaries
├─ hooks/
│  └─ sessionstart-repair.sh   # calls `ccx doctor --yes --json` to auto-repair after updates
├─ CREDITS.md                  # generated by `ccx credits --format notice`
├─ tests/                      # fixtures per version/format, golden manifests, dry-run snapshots
└─ README.md
```

User state (outside the repo): `~/.claude-code-x/`
```
~/.claude-code-x/
├─ manifests/<profile>.json    # what's applied + provenance + inverse data
├─ backups/cli.bak.<ts>        # timestamped pristine + intermediate backups
├─ registry/                   # user custom patch defs (ccx custom add/apply)
└─ proxy/extensions/*.mjs      # hot-reloadable proxy extensions
```

Each `registry/<group>/<id>.ccxpatch.json` carries: `id, name, group, description, source{repo,author,license}, prefer[layers], compat{min,max,exclude}, anchors[], edits[], verify`. The catalog is therefore pure data; the engine is generic. Built-ins and user customs share one schema (§5), so a vetted custom patch is promotable to the registry by PR.

---

## 9. Implementation language choice

**Python (3.11+), packaged as a single self-contained CLI (`pipx install claude-code-x` / standalone build), with `LIEF` as the binary engine.**

Justification, tied to the technique analysis:

- **The recommended engine is already Python + LIEF.** The method analysis explicitly concludes: a single Python engine built on LIEF, with a same-length fast-path that needs no LIEF at all. Python gives the raw byte-I/O fast-path (locate `\n---- Bun! ----\n`, overwrite equal-length in the `__BUN` cli.js region) with zero dependencies, and LIEF for the variable-length Mach-O/ELF/PE resize + offset-fixup path — one library across all three Bun target OSes, matching the OS-agnostic Bun graph format (the depester project proves LIEF unpack/repack works here).
- **Cross-platform container handling for free.** LIEF parses and rewrites Mach-O, ELF, and PE from one API, so the universal-patcher requirement (detect container → locate magic → edit → container-specific fixups) is satisfied without per-OS native code.
- **Signing stays delegated to platform tools**, which Python shells out to cleanly: `codesign` (present on macOS), `rcodesign` off-Mac, `signtool`/`osslsigncode` on Windows — exactly the recommended division of labor.
- **Strong fit for the non-binary layers too:** the proxy layer (a local `/v1/messages` server) and the runtime-preload generator are straightforward in Python; only the proxy's hot-reloadable extensions and the runtime preload module are emitted as small `.mjs`/JS artifacts to run inside Bun/Node, which is intrinsic to those layers regardless of host language.
- **Distribution + ergonomics:** Python ships a clean argparse/`typer`-style CLI and a grouped checkbox TUI (`prompt_toolkit`/`questionary`), reads/writes JSON manifests natively, and installs via `pipx` without a Node toolchain dependency — keeping the patcher independent of whatever Node/Bun the user's Claude Code install uses.

The one deliberate constraint: avoid the `bun build --compile` recompile path (local Bun version mismatch, lost entitlements, unrecoverable un-bundled source). The tool **patches the existing binary in place**, which is precisely what the Python + LIEF + same-length-fast-path design optimizes for.