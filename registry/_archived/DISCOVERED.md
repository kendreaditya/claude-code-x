# Deep-research wave 2 — findings

A second discovery sweep (32 agents across GitHub repos/code/gists, web, the awesome-claude-code lists, and known-unprocessed repos) surfaced 46 new sources beyond the original catalog. Outcome:

## Added (verified same-length on 2.1.158)
- `bash-default-timeout-raise-1h` (limits) — VoidChecksum/void-patcher-cc subset
- `increase-file-read-token-limit` (limits) — Piebald-AI/tweakcc
- `restore-subagent-claudemd-context` (behavior) — anthropics/claude-code#40459 regression fix

## Archived — not applicable to 2.1.158 (derived against older versions; re-derive to revive)
- `force-budgeted-thinking-main`, `retry-on-should-retry-header-subscription`, `clawd-banner-body-color`, `disable-context-low-warning`

## Declined by policy (found, deliberately NOT shipped — operations omitted)
These defeat safety, billing, or gating controls of the product and are out of scope for this project:
- **Safety-control removal:** `acd421-binary-safety-removal-suite` (refusal handlers, permission classifier, killswitches) — refused.
- **Internal/non-GA feature-gate unlocks:** `clawgod-computeruse-default-enabled`, `ntakpe-loop-dynamic-flag`, `enable-auto-dream-runner`, `enable-agent-teams-gate`, `native-agent-teams-force-enable`, `force-ccr-bridge-gate`, `enable-channels-tengu-harbor-gate`.
- **Paid-entitlement / billing circumvention:** `unlock-1h-prompt-cache-ttl`, `prompt-cache-1h-unlock`, `extra-usage-default-enabled-1m-race`, `telemetry-decoupled-feature-gates`.
- **Vendor telemetry removal:** `datadog-token-zeroing` — left to explicit user opt-in.

## Out of scope for the byte engine (non-binary patches — real, but source/proxy/vscode/tool level)
- `sataz-ehl/claude-code-patch` — _source_ — Windows-focused patch: rewrites the execSync import in cli.js (patch-cli.mjs) and loads patch-execsync.mjs to cache cygpath -u/-w calls, fix
- `maibach-systems/maibach-tweaks` — _prompt_ — Replaces the behavior-instruction block of Claude Code's default system prompt with a 13 KB Askell-conform, source-citation-enforcing, senio
- `Sophomoresty/claude-code-enhance` — _vscode_ — Patches the VS Code Claude Code EXTENSION (v2.1.31) webview: injects enhance.js, modifies the CSP to allow CDN resources, and adds syntax hi
- `Frisch12 (gist b86ba9b2442da98b69aa34cd0cf56d41)` — _source_ — Claude Code 'buddy' (companion) generator/patcher: rewrites the companion-generation function in cli.js to force a custom companion build; i
- `simpolism (gist 302621e661f462f3e78684d96bf307ba)` — _source_ — Fixes Claude Code's broken --resume prompt cache (cache-fix-patch.js + check_cache_resume.py diagnostic) so resumed sessions reuse the promp
- `wspl/cursor-2-claude-code-proxy` — _source_ — Patches node_modules cli.js (and claude-agent-sdk cli.js/sdk.mjs) for a 'magic resume string' that resumes a conversation without injecting 
- `ranxianglei/qoder-claude-bridge` — _source_ — Patches cli.js productionDeps function to inject acpCallModel as the callModel dependency (route CC through Qoder), with version-aware backu
- `manhit96/claude-code-vietnamese-fix` — _source_ — Patches the backspace-handling logic in cli.js so Vietnamese IME (0x7F DEL char from OpenKey/EVKey/Unikey) also inserts replacement text, fi
- `Jer-B/buddy_patch_claude` — _source_ — Bash patcher that rewrites the companion-generation function in cli.js to force a custom buddy (species/hat/rarity/stats/seed). npm-only.
- `ykdojo/claude-code-tips` — _source_ — Per-version patch-cli.js scripts (2.0.74, 2.1.5, 2.1.11, 2.1.17, 2.1.42, 2.1.72, ...) that trim/halve the Claude Code system prompt; verifie
- `mbailey (gist 556651142037d88d0dad8c826bae3141)` — _source_ — Patch script fixing the Claude Code v2.0.22 OAuth flow (patch-claude-code.sh) so login/token exchange works.
- `Haleclipse (gist 1c35fe7b98fe1b5ea0523eb4d3a10f0b)` — _source_ — PowerShell patch (v2.1.5) fixing Claude Code Windows path bug where the Bash tool wrote temp files in cwd instead of the temp directory.
- `Haleclipse (gist e60e52941ddb30061623e33c711eae54)` — _source_ — Fixes ink2/render_v2 ANSI 'ghost character' rendering bug (Issue #19820) via .ps1 and .sh patch scripts against cli.js.
- `Zamua (gist f7ca58ce5dd9ba61279ea195a01b190c)` — _source_ — Patches Claude Code 2.0.76 to fix the LSP plugin (apply-claude-code-2.0.76-lsp-fix.sh).
- `taekchef/claude-code-zh-cn` — _source_ — Simplified-Chinese localization plugin that patches cli.js UI strings to Chinese (install.sh / uninstall.sh).
- `opencc9527/Pangu-Claude-Code` — _source_ — Makes Claude Code natively support the Pangu LLM ('more than reskin') by patching the model/endpoint plumbing in cli.js.
- `gist: Zamua/f7ca58ce5dd9ba61279ea195a01b190c` — _binary_ — Fixes the LSP plugin 'No LSP server available for file type' error by replacing the empty async initialize() stub in Claude Code's LSP manag
- `Yuyz0112/claude-code-reverse (+ Medium: douyipu 'Monkey Patching Claude Code')` — _tool_ — Monkey-patches the Anthropic SDK beta.messages.create call inside cli.js to intercept and log all LLM requests/responses (writes message.log
- `OscarBarreraGithub/claude-code-inline-math` — _vscode_ — "ClaudeTex" VS Code companion extension that patches the installed anthropic.claude-code extension's webview (webview/index.js and webview/i
