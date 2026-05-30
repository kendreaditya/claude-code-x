# Prior Art

Community projects that patch or modify Claude Code's behavior. `claude-code-x`
aims to be a universal CLI that aggregates many of these as selectable,
**attributed** patches (see [GOAL.md](./GOAL.md)). Every patch this project
ships will cite its origin repo, author, and license — this file is the seed of
that ledger.

Levels: **binary** (edits the Bun-compiled native binary), **source** (edits
`cli.js` on npm installs), **proxy** (intercepts at the API boundary, no binary
change), **prompt** (copy-paste behavior instructions), **build**, **manager**
(orchestrates other patches).

## The progenitor

- **[roman01la/patch-claude-code.sh](https://gist.github.com/roman01la/483d1db15043018096ac3babf5688881)** *(gist, source)* — the original "de-nerf" patch everyone forks. Rewrites brevity / low-effort instructions in `cli.js`. Broke when CC v2.1.97+ moved to a native Bun binary; spawned the ecosystem below. Anthropic later removed 3 of the aggressive brevity instructions in v2.1.100.

## Binary / source patchers

| ★ | Repo | What it does | Level |
|---|---|---|---|
| 64 | [aleks-apostle/claude-code-patches](https://github.com/aleks-apostle/claude-code-patches) | Expand thinking traces fully by default (no ctrl+o) | binary |
| 29 | [ominiverdi/claude-depester](https://github.com/ominiverdi/claude-depester) | Replace whimsical loading words with plain "Thinking"; CLI + VS Code ext | binary |
| 20 | [Pickle-Pixel/claudecode-buddy-crack](https://github.com/Pickle-Pixel/claudecode-buddy-crack) | Companion-pet customization via **landmark-based, version-agnostic** binary patching | binary |
| 17 | [a-connoisseur/patch-claude-code](https://github.com/a-connoisseur/patch-claude-code) | Show files-read + stream thinking inline without verbose mode | binary |
| 10 | [East-rayyy/claude-alias-patch](https://github.com/East-rayyy/claude-alias-patch) *(archived)* | Custom model aliases via `ANTHROPIC_DEFAULT_*_MODEL` | binary |
| 8 | [changzhiai/claude-code-patch](https://github.com/changzhiai/claude-code-patch) | Make the leaked CC runnable with local models | source |
| 5 | [denysvitali/claude-code-patches](https://github.com/denysvitali/claude-code-patches) | "Make Claude Code fast again" — CPU/perf patches from profiling the minified runtime | binary |
| 5 | [yucongxing/claude-centos7](https://github.com/yucongxing/claude-centos7) | Patched builds for CentOS 7 (old glibc/kernel) | build |
| 4 | [wenwen12345/ccpatch](https://github.com/wenwen12345/ccpatch) | Patches CC via Babel AST transforms | source |
| 4 | [huybuidac/claude-code-patchkit](https://github.com/huybuidac/claude-code-patchkit) | Community binary patches to unlock hard-coded limits, exposed via Agent Skills | binary |
| 3 | [stripe/claude-code-patches](https://github.com/stripe/claude-code-patches) | (Stripe org; no description) | — |
| 1 | [sethdford/claude-code-patcher](https://github.com/sethdford/claude-code-patcher) | Custom native tools without MCP + multi-agent orchestration | binary |
| 1 | [InDreamer/claude-context-patch](https://github.com/InDreamer/claude-context-patch) | Patch context limits + compaction thresholds for longer sessions | binary |
| 1 | [themaoci/ClaudeCode-Patcher](https://github.com/themaoci/ClaudeCode-Patcher) | Patch instructions to be "more robust and free" | binary |
| 0 | [taocihei/claude-code-patcher-next](https://github.com/taocihei/claude-code-patcher-next) | Version-aware **patch manager** for legacy cli.js + modern native binary | manager |
| 0 | [kfirco-jit/claude-code-patches](https://github.com/kfirco-jit/claude-code-patches) | Trim system prompt (~2,400 tokens saved/turn) | source |
| 0 | [gabinfay/claude-code-color-patch](https://github.com/gabinfay/claude-code-color-patch) | Highlight user messages in a custom color | binary |
| 0 | [antonioacg/claude-code-title-patch](https://github.com/antonioacg/claude-code-title-patch) | Update terminal title on every message | binary |
| 0 | [genusdryasnizhninovgorod936/claude-channels-patch](https://github.com/genusdryasnizhninovgorod936/claude-channels-patch) | Enable `--channels` without claude.ai OAuth | binary |
| 0 | [OscarBarreraGithub/claude-code-inline-math](https://github.com/OscarBarreraGithub/claude-code-inline-math) | Patch the VS Code webview to render inline LaTeX | VS Code |
| 0 | [0xLoqi/claude-code-patches](https://github.com/0xLoqi/claude-code-patches) | Flip "advisor mode" → "doer mode" (prompt-level) | prompt |
| 0 | [ACD421/claude-code-binary-patches](https://github.com/ACD421/claude-code-binary-patches) | Security research: safety architecture, classifier trust boundaries | research |
| 0 | [AntlerPotato/claude-code-patches](https://github.com/AntlerPotato/claude-code-patches) | Curated collection of CC patches/tools (Chinese) | collection |

## Adjacent — proxy / wrapper fixes (same goal, not binary patches)

- **[cnighswonger/claude-code-cache-fix](https://github.com/cnighswonger/claude-code-cache-fix)** (254★) — most-starred of the lot. A proxy that fixes a prompt-cache regression causing up to 20× cost on resumed sessions; works with the v2.1.113+ Bun binary. Notable for its fail-to-no-op boundary design.
- **[NullLabTests/claude-code-enhanced](https://github.com/NullLabTests/claude-code-enhanced)** (32★) — full fork with arXiv-research enhancements.

## Technique lessons (mined for the engine)

- **Landmark-anchored, version-agnostic locators** — anchor on invariant string literals / AST shape, capture the churned minified identifier in a regex group, reuse it in the replacement. (buddy-crack, claude-code-x.)
- **Version-gate + capability matrix** — `(version, container format) → available patch layers`; refuse on unknown. (patcher-next.)
- **Marker-based idempotency + context guard** — recognize the patched state so re-running is a no-op. (patchkit.)
- **LIEF unpack / repack** for variable-length edits. (depester.)
- **API-boundary proxy with fail-to-no-op** for changes that survive `claude update` without touching the binary. (cache-fix.)

## Positioning

No project in this set does `claude-code-x`'s specific behavioral patch (kill
mid-turn `<system-reminder>` steering + queue bundling → pure FIFO). Only
`taocihei/claude-code-patcher-next` and `huybuidac/claude-code-patchkit` attempt
to be a *manager* of many patches — the space for a well-attributed, grouped,
version-aware universal patcher is largely open.

> Stars are point-in-time. Licenses are mostly unspecified (`unknown`) — see
> [GOAL.md → Attribution & Licensing](./GOAL.md#attribution--licensing-policy)
> for why that constrains what can be redistributed.
