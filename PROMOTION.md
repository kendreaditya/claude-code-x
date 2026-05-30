# Getting claude-code-x in front of people

Research-backed plan for growing the repo. Ordered by leverage (effort → reach).

## Positioning (read first)

Lead with the **insight**, not "crack Claude Code." The genuinely interesting,
shareable hook is the **FIFO / no-mid-turn-steering** behavior — most heavy
Claude Code users have felt the "it pivoted because I typed while it was working"
problem and don't know why. That's the story. The universal patcher is the
payoff. Always foreground **local-only + reversible + does-not-redistribute the
binary** to stay on the right side of the ToS conversation.

One-liner: *"Claude Code soft-steers your turn when you type mid-stream — ccx is a
reversible, version-aware patcher that turns that off (and bundles other community
patches with full attribution)."*

## 1. `awesome-claude-code` lists — highest leverage for stars

Getting listed is the single biggest, lowest-effort popularity lever. Open a PR
to each, under "developer tooling" / "patchers":

- **[hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code)** (~21.6k★) — the canonical list. Follow its CONTRIBUTING; quality/originality bar is high — ccx's anchor engine + provenance model fit.
- **[jqueryscript/awesome-claude-code](https://github.com/jqueryscript/awesome-claude-code)** — tools/IDE/frameworks.
- **[rohitg00/awesome-claude-code-toolkit](https://github.com/rohitg00/awesome-claude-code-toolkit)** — broad ecosystem index.
- Directories: [awesome-claude-code.com](https://awesome-claude-code.com/), [claudelog.com](https://claudelog.com/), [claudemarketplaces.com](https://claudemarketplaces.com/), [awesomeclaude.ai](https://awesomeclaude.ai/).

## 2. Reddit — best discussion signal

- **r/ClaudeCode** — most active CC community (~4.2k weekly contributors). Primary target. Title angle: *"I patched Claude Code to stop it from steering mid-turn — and built a universal patcher around it."* Include a before/after gif.
- **r/ClaudeAI** — broader Claude audience; cross-post.
- **r/vibecoding** (~89k) — build-log framing does well.
- Possibly **r/LocalLLaMA**, **r/commandline** for the reverse-engineering/CLI angle (read each sub's self-promo rules first; lead with technical detail, not a pitch).

## 3. Hacker News — Show HN

High-variance but high-ceiling. The reverse-engineering writeup (how the Bun
binary embeds plaintext JS, landmark-anchored same-length patching, the
`@bytecode` finding) is HN-catnip. Title: *"Show HN: ccx – a reversible,
version-aware patcher for the Claude Code binary."* Be ready to discuss the ToS
question transparently in comments (local-only, never redistributes the binary).

## 4. X / Twitter

- Use **#ClaudeCode**. The demo (no mid-turn steering) is a strong <30s screen recording.
- Reply/quote into Claude Code tool roundup threads (e.g. accounts that post "great collection of Claude Code stuff"). Tag [@claudeai](https://x.com/claudeai) sparingly.
- A short thread: the problem → the one-line behavior change → the universal patcher → repo link.

## 5. Content that compounds

- A short blog/DEV.to writeup of the **`@bytecode` finding** (docs/M2-bytecode-finding.md) — original reverse-engineering content earns links.
- A 30–60s screen recording of `ccx list` → `ccx apply` → the behavior change.
- Keep `compat/COMPATIBILITY.md` current (the release-watch Action does this) — "still works on the latest version" is a trust signal.

## Sequencing

1. Get listed in the awesome lists (PRs) — passive, compounding.
2. Polish README + logo + a demo gif.
3. One strong r/ClaudeCode post → cross-post r/ClaudeAI, r/vibecoding.
4. X thread same day.
5. If Reddit lands well, Show HN with the reverse-engineering writeup.

> Do the awesome-list PRs and the README/gif before the Reddit/HN push — first
> impressions from a launch drive the star spike, and a clean README + working
> badge/report is what converts a visit into a star.

_Sources: aitooldiscovery (Claude Code Reddit guide), github.com/topics/awesome-claude-code, ClaudeLog, X #ClaudeCode discussion._
