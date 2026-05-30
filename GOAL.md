# claudius-code — Universal CLI Patcher

## Goal

`claudius-code` (binary: `ccx`) is a universal, version-aware, provenance-respecting patcher for the Bun-compiled Claude Code CLI. Its north star is to let a user apply, inspect, and cleanly revert curated community patches — and their own custom patches — against the locally installed Claude Code binary using the highest-resilience intervention layer that the detected version supports, never hardcoding offsets, always citing each patch's origin repo/author/license, recording a verifiable manifest of what changed, and refusing to touch the binary whenever it cannot reproduce a patch's precondition. The first shipped capability is the existing `claudius-code` FIFO/noqueue patch, ported into the new declarative registry format and driven end-to-end by the same engine that every future patch will use.

## The Patching Problem & Chosen Approach

Claude Code 2.1.x ships as a single Bun-compiled native binary. The application JavaScript is **not** appended at EOF — it lives inside a dedicated Mach-O `__BUN` segment as raw plaintext JS (the `cli.js` module begins `// @bun @bytecode @bun-cjs\n(function(exports, require, module, …`). For this build, **latest = installed = 2.1.158**; the **2.1.88 source tree at `/tmp/cc-2188` is the mapping reference** we use to derive stable source landmarks (file → behavior → anchor) before locating the minified equivalents in the binary. The Bun StandaloneModuleGraph format (magic `\n---- Bun! ----\n`, segment-relative StringPointers, `CompiledModuleGraphFile` records, plaintext JS) is identical across Mach-O / ELF / PE — only the container and signing differ.

The recommended engine is **a single Python engine with a raw same-length fast-path and a LIEF-backed variable-length path**, for the following reasons:

- **Same-length is the default and the fast path.** An equal-byte-count (or pad-to-length) replacement inside `__BUN` requires *no* offset fixups — the only thing invalidated at the byte level is the code signature, so the apply step is `read → locate → splice → re-sign`. This is the ~95% case and needs no parsing library at all (`RawByteEngine`). **Caveat (verified):** re-signing rebuilds `__LINKEDIT`/`LC_CODE_SIGNATURE` and therefore changes *total file size* every run — the on-disk patched 2.1.158 is ~1.25 MB **smaller** than pristine. "Same-length" means the spliced *operation* is byte-balanced, **not** that the final file size is unchanged. Any "size unchanged" verification is therefore wrong and is explicitly excluded (see Risks).
- **Variable-length is an explicit, gated advanced mode.** Length changes cascade: the edited module's `contents.len` must grow, every downstream StringPointer (segment-relative) must shift by delta, `__bun` section size + `__BUN` `filesize`/`vmsize` must be re-padded to 16K alignment, and `__LINKEDIT` plus every LINKEDIT-referencing load command must move. This is `LiefEngine`, invoked only when `allow_variable_length: true` *and* the replacement cannot be padded back to the original length. It is **not yet implemented or exercised** (see Risks) and ships as a hard refusal until it is.
- **Signing is mandatory and entitlement-preserving on macOS.** The binary is adhoc-signed with `allow-jit`, `allow-unsigned-executable-memory`, and `disable-library-validation`. Any byte change invalidates the CDHash; on Apple Silicon an invalid/missing signature is an immediate `SIGKILL`. Re-sign via `codesign --force --sign - --preserve-metadata=entitlements …` — dropping the JIT/unsigned-memory entitlements re-signs cleanly but crashes JSC at launch. (Note: the working reference preserves only `entitlements`; the broader `flags,identifier` set is untested — see Risks.)
- **Locators are version-agnostic by construction.** Never store offsets. Anchor on the most stable token available — user-facing string literals, protocol values (`"task-notification"`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, the `[1m]` alias suffix), or distinctive structural tokens (`.agentId===void 0`) — and **capture** the churned minified identifier in a regex group, reusing it in the replacement so the patch self-adapts every release. Recognize the patched state too, so locate is idempotent. When no anchor survives a restructure, raise a typed `PatchError` and **abort cleanly** — fail-to-no-op, never patch-and-break.

The decisive discipline is **resolve everything up front, then write once**: detect → locate → verify is a chain of hard gates that abort before any byte is written, so the binary is never left half-patched.

## Architecture

### Engine (the apply pipeline)

One pipeline for every patch and both backends; each stage is a hard gate:

```
0. DETECT   container (magic) + version + capability gate; refuse on unknown/unsafe
1. LOCATE   resolve each op's anchor → concrete (file_offset, old_bytes, new_bytes); derive churned ids
2. VERIFY   uniqueness (count==1) + length policy + in-owning-module-region + per-op 3-state idempotency
            └─ --dry-run stops here and prints the resolved plan
3. BACKUP   copy2 → <binary>.unpatched once, with sha256+version stamp (never overwrite a pristine backup)
4. APPLY    splice all ops; same-length → RawByteEngine, var-length → LiefEngine; write <binary>.tmp
5. RE-SIGN  platform signer (macOS codesign, entitlement-preserving; rcodesign off-Mac; ELF no-op)
6. SMOKE    atomic os.replace(tmp, binary); `claude --version`; on fail → auto-rollback from .unpatched
```

Two backends behind one interface: **`RawByteEngine`** (pure byte splice, no LIEF, all same-length / pad-to-length ops) and **`LiefEngine`** (LIEF parse/resize/repack + Bun StringPointer fixups, variable-length only). Both feed the same locate, verify, backup, sign, and smoke-test stages.

### Patch-definition schema (declarative JSON, one file per patch)

The engine — not the patch file — owns locate/verify/backup/sign. Each `registry/<group>/<id>.ccxpatch.json` carries:

- `schema_version`, `id`, `name`, `group`, `description`
- `provenance` — `source_repo`, `source_url`, `license`, `derived_by`, `source_landmarks[]`
- `applies_to` — `containers[]`, `version_range` (semver), `min_bun`
- `marker` — a byte sequence present **only** post-patch (idempotency sentinel; should be a dedicated inert comment marker decoupled from any behavioral edit — see Risks)
- `allow_variable_length` — default `false`
- `operations[]` — each with `op_id`, `kind` (`landmark-anchored` ▸ `ast-node` ▸ `regex-replace`, in resilience order), `must_be_unique`, `same_length`, `in_bun_region`, `anchor` (regex with capture groups), `replace` (template referencing captures), `patched_anchor` (recognizes applied state), `rationale`.

### CLI command surface (`ccx`)

Global flags: `--target <path>`, `--dry-run`, `--yes/-y`, `--json`, `--no-color`, `--profile <name>`.

| Command | Purpose |
|---|---|
| `ccx list` | Catalog grouped by group, annotated with applicability + applied-state vs the detected target |
| `ccx status` | Detected version, container/signing facts, manifest contents re-verified live (3-state) |
| `ccx apply <id…> \| --group <g> \| -i \| --all-applicable` | Apply patches; prints citation block + plan, confirms, backs up, mutates, re-signs, verifies, writes manifest |
| `ccx revert <id> \| --group <g> \| --all \| --to <backup>` | Surgical inverse from manifest, else pristine-backup restore + replay |
| `ccx doctor` | Re-detect version, re-verify manifest, validate signing/entitlements, offer auto-repair + hook install |
| `ccx credits [--applied] [--format md\|json\|notice]` | Standing provenance ledger |
| `ccx custom add\|apply\|scaffold\|validate\|list` | User-supplied patches, same engine + safety machinery |
| `ccx hook install\|remove` · `ccx detect` · `ccx version` | SessionStart auto-repair hook mgmt; version/compat probe |

`apply -i` is a grouped collapsible checkbox TUI: group headers toggle all *applicable* children, N/A rows render disabled with the gating reason inline, already-applied rows are pre-checked and dimmed, and a live plan summary states cross-cutting consequences once (re-sign required, restart Claude).

### Repo layout

```
claudius-code/
├─ bin/ccx                       # entrypoint: arg parse → command dispatch
├─ core/
│  ├─ detect.py                  # install location, container sniff, version + Bun + signing
│  ├─ compat.py / compat-matrix.json   # (version, format) → available layers (data-driven gate)
│  ├─ anchors.py                 # string / lexical-landmark / AST anchor resolver
│  ├─ idempotency.py             # per-op 3-state detection, marker scan
│  ├─ engines/{binary_raw,binary_lief,source_ast,runtime_preload,proxy_boundary}.py
│  ├─ sign.py backup.py manifest.py verify.py plan.py   # signing, backup, manifest, verify, conflict-detect
├─ registry/{behavior,performance,cosmetic,limits,models,privacy}/*.ccxpatch.json
├─ cli/{commands/, interactive.py, render.py}
├─ hooks/sessionstart-repair.sh
├─ CREDITS.md   tests/   README.md
```

User state (outside repo): `~/.claudius-code/{manifests/<profile>.json, backups/cli.bak.<ts>, registry/, proxy/extensions/*.mjs}`.

The intervention ladder (highest-resilience-first) is `proxy > runtime > source > binary`. The capability matrix (`native-bun-binary` 2.1.x+ supports proxy/runtime/binary but **not** source; `legacy-cli-js` 2.0.x adds source; `unknown` → refuse). Implementation language: **Python 3.11+** packaged via `pipx`, with LIEF as the (future) variable-length engine and platform signers shelled out to.

## Patch Registry & Groups

Groups are the primary organizing axis everywhere a patch list appears: **behavior, performance, cosmetic, limits, models, privacy** (intervention level surfaced as a badge: `build`, `manager`, `proxy`, `prompt`, `source`, `binary`). Every patch is pure data; the engine is generic. **Every catalogued patch cites its origin repo + author + license — this is non-negotiable.**

| id | name | group | level | source repo (author) | license |
|---|---|---|---|---|---|
| `fifo-steering-queue` | FIFO Steering and Queue Bundling | behavior | binary | kendreaditya/claudius-code (kendreaditya) | unknown* |
| `denerf-system-prompt` | De-nerf System Prompt | behavior | source | roman01la/patch-claude-code gist (roman01la) | unknown |
| `expand-thinking-traces` | Expand Thinking Traces by Default | behavior | binary | aleks-apostle/claude-code-patches (aleks-apostle) | unknown |
| `inline-files-thinking` | Inline Files-Read and Streamed Thinking | behavior | binary | a-connoisseur/patch-claude-code (a-connoisseur) | unknown |
| `babel-ast-patcher` | Babel AST Patcher | behavior | source | wenwen12345/ccpatch (wenwen12345) | unknown |
| `advisor-to-doer` | Advisor-to-Doer Mode | behavior | prompt | 0xLoqi/claude-code-patches (0xLoqi) | unknown |
| `version-aware-patch-manager` | Version-Aware Patch Manager | behavior | manager | taocihei/claude-code-patcher-next (taocihei) | unknown |
| `cpu-perf-patches` | CPU/Performance Patches | performance | binary | denysvitali/claude-code-patches (denysvitali) | unknown |
| `trim-system-prompt` | Trim System Prompt (~2400 tokens/turn) | performance | source | kfirco-jit/claude-code-patches (kfirco-jit) | unknown |
| `prompt-cache-fix-proxy` | Prompt-Cache Regression Fix Proxy | performance | proxy | cnighswonger/claude-code-cache-fix (cnighswonger) | unknown |
| `centos7-build` | CentOS 7 Compatible Builds | performance | build | yucongxing/claude-centos7 (yucongxing) | unknown |
| `plain-thinking-words` | Plain Thinking Loading Words | cosmetic | binary | ominiverdi/claude-depester (ominiverdi) | unknown |
| `companion-pet-customize` | Companion Pet Customization | cosmetic | binary | Pickle-Pixel/claudecode-buddy-crack (Pickle-Pixel) | unknown |
| `user-message-color` | Highlight User Messages | cosmetic | binary | gabinfay/claude-code-color-patch (gabinfay) | unknown |
| `terminal-title-update` | Terminal Title Updates | cosmetic | binary | antonioacg/claude-code-title-patch (antonioacg) | unknown |
| `unlock-limits-skills` | Unlock Limits via Agent Skills | limits | binary | huybuidac/claude-code-patchkit (huybuidac) | unknown |
| `context-limits-compaction` | Context Limits and Compaction Thresholds | limits | binary | InDreamer/claude-context-patch (InDreamer) | unknown |
| `model-aliases` | Custom Model Aliases | models | binary | East-rayyy/claude-alias-patch (East-rayyy) | unknown |
| `local-model-runnable` | Run Leaked CC with Local Models | models | source | changzhiai/claude-code-patch (changzhiai) | unknown |
| `channels-no-oauth` | Channels Without OAuth | privacy | binary | genusdryasnizhninovgorod936/claude-channels-patch | unknown |

\* The MIT license on the `kendreaditya/claudius-code` scripts covers the *patch scripts*, not the patched Anthropic binary (see Attribution & Licensing). MIT-clean **engine internals** to lean on as references: LIEF unpack/repack pattern (ominiverdi/claude-depester), context-guard / marker idempotency (huybuidac/claude-code-patchkit), API-boundary proxy + fail-to-no-op (cnighswonger/claude-code-cache-fix), version-gate + capability matrix (taocihei/claude-code-patcher-next).

### Reference patch: `fifo-steering-queue` (the MVP port)

Three same-length, landmark-anchored ops, each capturing the churned minified identifier and pinning to invariant literals. Source landmarks (derived against `/tmp/cc-2188`):

- `inline-notification-modes-drop-prompt` — `utils/attachments.ts` `INLINE_NOTIFICATION_MODES` Set; replace `"prompt"` → `"__off_"` (6→6 bytes) so user-typed messages are never emitted as queued attachments mid-turn; `"task-notification"` preserved.
- `queueprocessor-force-single-item` — `utils/queueProcessor.ts` bash branch; anchor `([A-Za-z_$0-9]+)\(q\)\|\|q\.mode==="bash"` → `\g<1>(q)||q.mode===q.mode`, making the gate tautologically true so every queued command drains one-at-a-time (`"bash"`→`q.mode`, 6→6 bytes). Currently doubles as the project marker (to be decoupled — see Risks).
- `query-midturn-remove-drop-prompt` — `query.ts` mid-turn `removeFromQueue` filter; rewrite `"prompt"`→`"__off_"` with a backreferenced minified var so prompt-mode commands survive to drain as their own post-turn turns; `"task-notification"` preserved.

## Attribution & Licensing policy

Provenance is enforced at three touchpoints:

1. **On apply — mandatory citation block.** Before any mutation (and always in `--dry-run`), `ccx` prints per patch: source repo, author, license, intervention level, resolved anchor. Licenses normalize to an SPDX-ish enum (`MIT`, `unknown`, `unlicensed`, `educational-only`, `unlicensed-local`); anything not clearly redistributable prints a `⚠` advisory exactly when the user acts. (Catalog reality: nearly all community entries are `unknown`.)
2. **Generated manifest.** Each successful apply appends a provenance-bearing entry to `~/.claudius-code/manifests/<profile>.json`: target facts, the patch's `source{repo,author,license}`, resolved anchor, marker, per-edit original/patched bytes (base64, for surgical inverse), backup name, and re-sign metadata. The manifest is the single source of truth for `status`, `revert`, `doctor`, and SessionStart re-apply.
3. **`ccx credits` — standing ledger.** Renders provenance for the whole catalog or just the applied set, exportable as Markdown / JSON / NOTICE. This is what ships in `CREDITS.md` and what a user runs to honor attribution before sharing. User-authored customs are listed distinctly under "Local / user-supplied" (`local/<user>`, `unlicensed-local`) so applied state is never misattributed to a community author.

**ToS / legal caveat (load-bearing, surfaced to the user — not assumed away):** patching and redistributing a modified, re-signed Anthropic binary **plausibly violates the Claude Code / Anthropic Consumer ToS and copyright, regardless of the MIT license on the patch *scripts*.** The MIT license covers the scripts, **not** the patched binary, which remains Anthropic's copyrighted work; the pervasive `license: unknown` on community patches compounds this. `ccx credits` and the README must state plainly that **a patched binary must not be redistributed** and that **running it may breach Anthropic's terms.** The tool is positioned as a *local-only*, build-it-yourself patcher; nothing about MIT on the scripts sanitizes redistribution of the modified binary.

## Phased Implementation Plan

Ordered so a working MVP ships first; later phases harden, broaden, and only then enable the risky paths.

- **M0 — Honest MVP: port the FIFO patch into the registry.** Implement `RawByteEngine`, `detect.py` (container + version gate, refuse outside `>=2.1.0 <3.0.0` / non-Mach-O), `anchors.py` (landmark-anchored locator with churned-id capture), per-op `idempotency.py`, `backup.py` (with sha256+version stamp), entitlement-preserving `sign.py`, and a `verify.py` that checks **marker presence + Bun trailer offset stable vs backup + `codesign --verify` + launch** (explicitly **not** file-size equality). Port `repatch-claude-noqueue.sh` to `registry/behavior/fifo-steering-queue.ccxpatch.json`. **Deliverable:** `ccx apply fifo-steering-queue`, `ccx status`, `ccx revert fifo-steering-queue`, `ccx detect` working on installed 2.1.158, write-to-`.tmp` + `os.replace`, auto-rollback on smoke-test failure. Single-platform, single-version, in-place, local-only — advertised exactly that narrowly.

- **M1 — Region model + uniqueness correctness.** Enumerate **all** plaintext `// @bun @bytecode @bun-cjs` module headers and parse each `CompiledModuleGraphFile {off,len}` from the trailer; run `in_bun_region` against the *owning* module per edit (not one hardcoded `[193186496, +15520011)` window). Enforce uniqueness in the **locator** for every op (including hardcoded-byte ops) and switch from replace-all to single-site splice at the verified offset. **Deliverable:** correct multi-module region gating + no clobber-all risk; empirical confirmation each FIFO anchor lands in its claimed module.

- **M2 — Behavioral verification (resolve `@bytecode`).** Build `verify-effect`: launch the patched copy, queue two messages mid-turn, assert two separate turns. Resolve whether the executed code is the plaintext source or a parallel JSC bytecode blob (8 `@bytecode` tags present). **Deliverable:** every patch labeled `applied` only after a behavioral check; until M2 passes, all patches read `cleanly applied, runtime effect UNVERIFIED`.

- **M3 — Decoupled marker + SessionStart hook hardening.** Introduce a dedicated inert marker (e.g. `/*ccx:fifo*/`) separate from any behavioral edit; make 3-state detection per-op via each op's `patched_anchor`. Ship `sessionstart-repair.sh` with `grep -F` (fixed-string), a single reconciled recursion-guard env var, and a per-session attempt cap as hard backoff; non-blocking `exit 0` on failure. **Deliverable:** `ccx hook install/remove`; mixed/partial state reported accurately, no fork-bomb, no infinite-repatch.

- **M4 — Manifest, revert, doctor, credits, list/status TUI.** Full manifest schema (no `original_size` equality field; store pre-resign size as an annotated note only), surgical-inverse `revert`, `ccx doctor` (drift detect + auto-repair re-resolving anchors against new versions), `ccx credits` (md/json/notice), grouped `list`/`status`, and the `apply -i` checkbox TUI. Conflict detection in `plan.py` via **interval overlap on resolved offsets**. **Deliverable:** full read/inspect/revert/repair UX over the FIFO patch and one or two MIT-licensed additions.

- **M5 — Custom patches.** `ccx custom add/apply/scaffold/validate/list`, shared schema + safety machinery, forced `source` block (`local/<user>`, `unlicensed-local`), validation gate (unique anchor, unique+absent marker, achievable length policy). **Deliverable:** user-authored patches through the same pipeline with distinct credits attribution.

- **M6 — Catalog growth (MIT-first).** Port additional community patches into the registry, prioritizing MIT-clean sources (patchkit, depester, cache-fix, patcher-next) and clearly flagging `unknown`-license entries with the redistribution `⚠`. **Deliverable:** populated `registry/` across all six groups, each with full provenance.

- **M7 — LIEF variable-length backend (gated).** Install + pin LIEF in `~/workspace/.venv`; implement `LiefEngine` (splice + fix the edited module's `contents.len` + shift every downstream StringPointer + `__bun`/`__BUN` size re-pad to 16K + `__LINKEDIT` and all LINKEDIT-referencing load commands + strip-and-rebuild signature). Write an end-to-end grow-by-N test on a copy of 2.1.158 (all modules' StringPointers + trailer + LINKEDIT, re-sign, launch). **Deliverable:** `allow_variable_length: true` becomes real; until this lands and tests pass it is a **hard refusal**, not an "advanced mode."

- **M8 — Cross-platform + other layers.** ELF (no-sign) and PE (Authenticode strip/re-sign if present) container support; `runtime_preload` and `proxy_boundary` engines for layers that survive `claude update`. **Deliverable:** the "universal" claim earned, not asserted.

## Risks & Open Questions

These are verified findings against the on-disk 2.1.158 binary and the reference implementation; the plan above is sequenced to retire them.

- **"Same-length changes only the signature" is false at the file level.** The patched 2.1.158 is **213,982,368 bytes vs 215,233,824 pristine — a 1.25 MB shrink** (same delta on 2.1.152): ad-hoc re-signing rebuilds `__LINKEDIT`/`LC_CODE_SIGNATURE` and changes total size every run. Any `size unchanged` check (Stage-6 / manifest `original_size`) would **false-positive "corrupted" on every successful patch.** → Drop size-equality; verify via marker==1, Bun trailer offset stable vs backup (verified `213,313,453` in both), `codesign --verify`, and launch.
- **The single-`cli.js`-region model is wrong.** The binary has **7 plaintext module headers** (first at file offset `63,632,421`), not one module at `193,186,496` — the recon conflated `__BUN` segment filesize (`140,951,552`) with total file size (~214 MB). A hardcoded `[193186496, +15520011)` `in_bun_region` gate would reject valid edits in the other 6 modules. → M1 enumerates all modules and gates per owning module.
- **LIEF is not installed and the variable-length backend is untested vaporware.** `LiefEngine` (Tier 2/3 StringPointer + LINKEDIT fixups) has never run against this binary. → Ship `allow_variable_length: false` as a hard refusal; M7 installs/pins LIEF and adds an end-to-end test before advertising it.
- **The reference does not actually deliver several design safety claims.** It edits **in place** (not `.tmp` + `os.replace`), has **no auto-rollback** from `.unpatched` on smoke-test failure, uses `data.replace(old,new)` (**replace-all**, no per-op uniqueness check for patch #1's hardcoded bytes), and never stamps/verifies the `.unpatched` backup (a poisoned backup restores garbage). → M0/M1 implement `.tmp`+rename, auto-rollback, single-site splice, and sha256+version-stamped backups.
- **`@bytecode` runtime-effect is unresolved.** 8 `@bytecode` tags are present; if a parallel JSC bytecode blob executes instead of the plaintext source, editing only the plaintext has **no runtime effect** and `claude --version` cannot detect it. → M2 `verify-effect` resolves this before any patch is labeled working.
- **Re-sign metadata mismatch, signature validity unverified.** Design mandates `--preserve-metadata=entitlements,flags,identifier`; the working reference uses only `entitlements`. `codesign -dvvv` returned "No such process" in this environment, so signature validity is **unverified** — shipping the broader untested set risks `SIGKILL` on Apple Silicon. → Match the verified-working flag set first; widen only after `codesign -dvvv` + launch validation on a patched copy.
- **The marker is dangerously overloaded.** `q.mode===q.mode` is *both* a behavioral edit and the global is-patched sentinel. If a release legitimately removes the queueProcessor bash branch, patch #2 no-ops, the marker is never written, and the SessionStart hook repatches **every session forever** with no backoff. The SessionStart grep also uses `.` as a regex metacharacter (latent false-positive) and the recursion-guard env var name **differs between hook (`CLAUDE_REPATCH_INFLIGHT`) and engine (`CLAUDIUS_REPATCH_INFLIGHT`)** — a mismatch is an unbounded `claude --version` fork-bomb. → M3 introduces a dedicated inert marker, per-op 3-state detection, `grep -F`, one reconciled env var, and a per-session attempt cap.
- **Conflict detection is unspecified.** The CLI claims overlapping anchor spans are detected from resolved offsets, but no module computes/compares spans; two same-length adjacent edits in one run could silently corrupt each other's `old_bytes` match. → M4 implements interval-overlap on resolved offsets in `plan.py`.
- **Legal posture is the most under-treated risk.** Redistributing a re-signed, modified Anthropic binary is plausibly a ToS/copyright violation that MIT on the scripts does **not** cure; `license: unknown` community entries compound it. → `ccx credits`/README state plainly: do not redistribute the patched binary; running it may breach Anthropic's terms. Tool is local-only.

**Verdict guiding scope:** the same-length `RawByteEngine` fast-path is real and working; the design overstates its invariant and ships claims the reference does not yet deliver. **Do not advertise "universal," `LiefEngine`, auto-rollback, or size-verify until each is implemented and tested.** Initial release is reframed as a single-platform, single-version, in-place, local-only FIFO patcher with a correct region model, correct verification, and honest provenance/legal messaging — exactly the M0–M3 path above.