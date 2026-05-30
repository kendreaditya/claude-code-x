#!/usr/bin/env bash
#
# repatch-claude-noqueue.sh
#
# Patches the active Claude Code binary IN PLACE so that:
#   1. It does NOT inject mid-turn <system-reminder> attachments into the
#      running turn when the user types a new message. (No "steering" of
#      in-flight turns.)
#   2. It does NOT bundle multiple queued user messages into a single user
#      turn. Each queued message drains one-at-a-time as its own turn.
#
# After running, the standard `claude` launcher (~/.local/bin/claude) uses
# the patched binary directly — no second launcher, no `-noqueue` suffix.
#
# Auto-update flow:
#   When Claude Code auto-updates it writes a NEW versioned binary at a new
#   path and repoints ~/.local/bin/claude → that new versions/<X> file.
#   The new binary is unpatched. Re-run this script after any update to
#   re-apply the patches to the now-current binary.
#
# Backup / reversibility:
#   On first patch of any given versioned binary, the original bytes are
#   saved alongside as <binary>.unpatched. The script is idempotent — if the
#   current binary already has both patches applied, it exits early without
#   re-doing anything. To roll back manually:
#       cp <binary>.unpatched <binary>
#       codesign --force --sign - --preserve-metadata=entitlements <binary>
#   (the original signature can't be restored; ad-hoc is the only option
#   once bytes have been touched).
#
# ──────────────────────────────────────────────────────────────────────────────
# WHY THIS SCRIPT EXISTS
# ──────────────────────────────────────────────────────────────────────────────
#
# Claude Code's default mid-turn message behavior is "soft steer":
#
#   - When you hit Enter while Claude is working on a turn, your message is
#     enqueued (it does NOT abort the turn).
#   - BUT the next time attachments are built for a tool result, the queued
#     message is also rendered into the model's context as a <system-reminder>
#     attachment with the text:
#         "The user sent a new message while you were working: <msg>
#          IMPORTANT: After completing your current task, you MUST address
#          the user's message above. Do not ignore it."
#   - Result: the model often pivots mid-stream because the reminder language
#     is strong, even though the tool itself wasn't aborted.
#
# Separately, when the queue drains between turns:
#
#   - All queued same-mode commands are dequeued together (`dequeueAllMatching`)
#     and delivered as a SINGLE bundled user message.
#   - Result: if you type "another one" three times while Claude is writing,
#     all three become one user turn and Claude returns one combined response
#     instead of three separate ones.
#
# This script kills both behaviors so user input behaves as a pure FIFO queue:
# each message gets its own complete turn, in order, with no mid-flight steer.
#
# ──────────────────────────────────────────────────────────────────────────────
# HOW WE FOUND THE PATCHES
# ──────────────────────────────────────────────────────────────────────────────
#
# 1. The CLI ships as a single Bun-compiled Mach-O binary (~200MB) at
#    ~/.local/share/claude/versions/<version>. The JS bundle is embedded
#    plaintext inside it — you can grep it with `grep -oa <bytes> <file>`.
#
# 2. We had read-only source access to an unpacked tree of the same release
#    (TypeScript source, no build infra). That let us locate the exact
#    functions we wanted to neutralize. The relevant source files are:
#       - src/utils/attachments.ts       (the INLINE_NOTIFICATION_MODES set)
#       - src/utils/messages.ts          (wrapCommandText — the reminder text)
#       - src/utils/queueProcessor.ts    (processQueueIfReady — bundle vs single)
#       - src/utils/handlePromptSubmit.ts (where enqueue is called mid-turn)
#       - src/utils/messageQueueManager.ts (enqueue/dequeue/priority levels)
#
# 3. For each behavior we wanted to kill, we identified a stable byte
#    sequence in the binary corresponding to a literal in the source, then
#    replaced it with a same-length byte sequence that changes the behavior
#    without changing the surrounding code structure. Same-length is critical
#    so we don't shift any offsets in the binary.
#
# 4. After patching, Anthropic's code signature is broken. We re-sign ad-hoc
#    (no developer cert) so macOS will still launch it from the terminal.
#    Gatekeeper is fine for terminal-launched binaries; only quarantined
#    binaries (downloaded via browser) would be blocked.
#
# ──────────────────────────────────────────────────────────────────────────────
# PATCH #1 — disable mid-turn <system-reminder> injection
# ──────────────────────────────────────────────────────────────────────────────
#
# Source location: src/utils/attachments.ts:1044
#
#     // src/utils/attachments.ts
#     const INLINE_NOTIFICATION_MODES = new Set(['prompt', 'task-notification'])
#     ...
#     // queued commands of these modes are emitted as queued_command
#     // attachments on tool results — i.e. visible to the model mid-turn.
#     const filtered = queuedCommands.filter(_ =>
#       INLINE_NOTIFICATION_MODES.has(_.mode),
#     )
#
# The queued-command attachment then gets rendered with the steering language:
#
#     // src/utils/messages.ts:5510 (wrapCommandText)
#     return `The user sent a new message while you were working:
#     ${raw}
#     IMPORTANT: After completing your current task, you MUST address the
#     user's message above. Do not ignore it.`
#
# Modes in PromptInputMode (src/types/textInputTypes.ts:265):
#     'bash' | 'prompt' | 'orphaned-permission' | 'task-notification'
#
# 'prompt' is the mode tag for normal user-typed text (the default when you
# type something and press Enter). 'task-notification' is used by background
# agents reporting back — it's LOAD-BEARING for proactive loops (SleepTool
# wake-up), so we must keep it in the set.
#
# Strategy: rewrite the Set literal so 'prompt' is no longer a member, but
# 'task-notification' still is. The exact bytes in the minified JS:
#
#     OLD:  new Set(["prompt","task-notification"])
#     NEW:  new Set(["__off_","task-notification"])
#
# Both are exactly 39 bytes. "__off_" (6 chars) replaces "prompt" (6 chars),
# preserving the byte count. "__off_" never matches any real PromptInputMode,
# so the Set's `has(_.mode)` returns false for user-typed 'prompt'-mode
# commands and they are never inlined as attachments.
#
# Net effect: user keystrokes still enqueue, but the model never sees them
# mid-turn. They are only delivered as a normal user turn after the current
# turn fully completes.
#
# ──────────────────────────────────────────────────────────────────────────────
# PATCH #2 — disable per-mode queue bundling
# ──────────────────────────────────────────────────────────────────────────────
#
# Source location: src/utils/queueProcessor.ts:52 (processQueueIfReady)
#
#     export function processQueueIfReady({ executeInput }) {
#       const isMainThread = cmd => cmd.agentId === undefined
#       const next = peek(isMainThread)
#       if (!next) return { processed: false }
#       // Slash commands and bash run one at a time (per-command isolation)
#       if (isSlashCommand(next) || next.mode === 'bash') {
#         const cmd = dequeue(isMainThread)!
#         void executeInput([cmd])
#         return { processed: true }
#       }
#       // Everything else (incl. 'prompt') is BUNDLED:
#       const targetMode = next.mode
#       const commands = dequeueAllMatching(
#         cmd => isMainThread(cmd) && !isSlashCommand(cmd) && cmd.mode === targetMode,
#       )
#       if (commands.length === 0) return { processed: false }
#       void executeInput(commands)   // ← one user turn with N commands
#       return { processed: true }
#     }
#
# In the minified binary this function (renamed PFK) looks like:
#
#     function PFK({executeInput:H}){
#       let _=(T)=>T.agentId===void 0,    // isMainThread
#           q=JGH(_);                      // peek(isMainThread)
#       if(!q)return{processed:!1};
#       if(XFK(q)||q.mode==="bash"){       // ← THE CHECK we're flipping
#         let T=tUH(_);                    // dequeue
#         return H([T]),{processed:!0}     // single-item executeInput
#       }
#       let K=q.mode,
#           O=eUH((T)=>_(T)&&!XFK(T)&&T.mode===K);  // dequeueAllMatching
#       if(O.length===0)return{processed:!1};
#       return H(O),{processed:!0}                   // BUNDLED executeInput
#     }
#
# We force every queued command through the single-item branch by making
# the if-condition always true. Trick: replace the string literal "bash"
# with `q.mode` itself, so `q.mode === q.mode` is tautologically true.
#
#     OLD:  XFK(q)||q.mode==="bash"
#     NEW:  XFK(q)||q.mode===q.mode
#
# Both are exactly 23 bytes. After patching, every queued command goes
# through the dequeue() + executeInput([cmd]) branch — one at a time, as its
# own user turn. The bundling drain `dequeueAllMatching` is now unreachable.
#
# Why this specific replacement vs. alternatives:
#
#   - Flipping `===` to `!==` ("==!"bash") would route prompt/orphaned/
#     task-notification through single-item but break BASH mode (which the
#     original explicitly wanted single-item too). Net regression for bash.
#
#   - Replacing "bash" with another 4-char literal would break uniqueness or
#     match nothing (e.g. "prom" is never a real mode → still bundles).
#
#   - `q.mode===q.mode` is the cleanest: always-true, 23 bytes, no regression
#     in bash handling, preserves the type signature of the condition.
#
# Caveat: `task-notification` mode also bundles in the original. After this
# patch, task notifications drain one-at-a-time too. This is benign — each
# notification represents a separate background-agent completion and was
# never required to bundle for correctness, just performance.
#
# ──────────────────────────────────────────────────────────────────────────────
# UNIQUENESS / SAFETY
# ──────────────────────────────────────────────────────────────────────────────
#
# Both target byte sequences are unique in the binary (verified by grep -oac).
# The script aborts if uniqueness ever changes — that would mean Anthropic
# changed the minified naming (XFK, PFK, JGH, tUH, eUH) or the literal,
# and the patch needs to be re-derived against the new source.
#
# To re-derive after a breaking update:
#   1. Look at the new src/utils/queueProcessor.ts and src/utils/attachments.ts
#   2. Find the new minified function names by searching the new binary for
#      distinctive bytes (e.g. ".agentId===void 0" still uniquely fingerprints
#      processQueueIfReady's isMainThread arrow).
#   3. Update the OLD_* / NEW_* byte sequences below.
#
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Resolve the active Claude Code binary ────────────────────────────────────
CLAUDE_LAUNCHER="$HOME/.local/bin/claude"
if [[ ! -L "$CLAUDE_LAUNCHER" ]]; then
  echo "error: $CLAUDE_LAUNCHER is not a symlink — non-standard install layout" >&2
  exit 1
fi

BINARY="$(readlink -f "$CLAUDE_LAUNCHER")"
if [[ ! -f "$BINARY" ]]; then
  echo "error: binary $BINARY does not exist" >&2
  exit 1
fi

VERSION="$(basename "$BINARY")"
BACKUP="${BINARY}.unpatched"

echo "Detected Claude Code version: $VERSION"
echo "  binary:  $BINARY"
echo "  backup:  $BACKUP"
echo

# ── Apply patches via Python (auto-locates byte sequences on every run) ──────
#
# The locator strategy:
#
#   Each patch defines a regex anchored on STRUCTURALLY STABLE elements of
#   the minified source — function signature shape, literal strings, AST
#   shape — and extracts the unstable minified identifier (e.g. XFK, T_, dH)
#   dynamically. This means routine minifier-name churn between Claude Code
#   releases is handled automatically without editing this script.
#
# Resilience to "already patched" state:
#
#   Each locator tries the unpatched fingerprint first; if not found, it
#   tries the patched fingerprint and derives OLD from NEW. This makes the
#   script idempotent even when re-run against a binary that's already
#   been patched (i.e. the OLD bytes no longer exist).
#
# When this still needs human re-derivation:
#
#   - If Anthropic restructures the source (function moves, control flow
#     changes, literal renamed like "bash" → "shell-input"), the regex
#     anchors fail. The script aborts with a clear error pointing at the
#     specific patch — see the WHY section at the top for re-derivation steps.
#
/usr/bin/env python3 - "$BINARY" "$BACKUP" <<'PY'
import os, sys, shutil, re
binary_path, backup_path = sys.argv[1], sys.argv[2]


class PatchError(Exception):
    pass


def locate_patch_1(data):
    """Patch #1: src/utils/attachments.ts — INLINE_NOTIFICATION_MODES Set.

    The literal Set contents are invariant across releases (string contents
    are not touched by minification). Remove 'prompt' from the set so
    user-typed messages are no longer emitted as queued_command attachments
    mid-turn. Keep 'task-notification' (load-bearing for SleepTool wake-up).
    """
    old = b'new Set(["prompt","task-notification"])'
    new = b'new Set(["__off_","task-notification"])'
    return old, new


def locate_patch_2(data):
    """Patch #2: src/utils/queueProcessor.ts — processQueueIfReady bash branch.

    Anchored on the function signature shape (parameter destructure +
    `agentId===void 0` arrow), which the source defines and the minifier
    can't restructure. Inside that function, find the bash check and
    extract the (unstable) minified isSlashCommand identifier. Replace
    `"bash"` with `q.mode` so the gate becomes tautologically true,
    forcing every queued command through the single-item dequeue path
    instead of the bundled drain.
    """
    # Unpatched: `<slash>(q)||q.mode==="bash"`
    m = re.search(rb'([A-Za-z_$0-9]+)\(q\)\|\|q\.mode==="bash"', data)
    if m:
        old = m.group(0)
        new = old.replace(b'"bash"', b'q.mode')
        return old, new
    # Idempotency: already patched. Derive OLD from NEW.
    m = re.search(rb'([A-Za-z_$0-9]+)\(q\)\|\|q\.mode===q\.mode', data)
    if m:
        new = m.group(0)
        old = new.replace(b'q.mode===q.mode', b'q.mode==="bash"')
        return old, new
    raise PatchError(
        "could not locate processQueueIfReady bash check — neither the "
        "unpatched fingerprint `XXX(q)||q.mode===\"bash\"` nor the patched "
        "tautology `XXX(q)||q.mode===q.mode` matched. Source structure may "
        "have changed; re-derive against src/utils/queueProcessor.ts."
    )


def locate_patch_3(data):
    """Patch #3: src/query.ts — mid-turn removeFromQueue filter.

    Anchored on the filter shape `X.mode==="prompt"||X.mode==="task-notification"`
    with a backreference forcing both sides to use the same minified var.
    Replace the `"prompt"` literal with `"__off_"` so the filter no longer
    matches prompt-mode commands (preserving the 'task-notification' branch
    so background subagent notifications still drain correctly).
    """
    # Unpatched
    m = re.search(
        rb'([A-Za-z_$0-9]+)\.mode==="prompt"\|\|\1\.mode==="task-notification"',
        data,
    )
    if m:
        old = m.group(0)
        new = old.replace(b'"prompt"', b'"__off_"')
        return old, new
    # Idempotency: already patched.
    m = re.search(
        rb'([A-Za-z_$0-9]+)\.mode==="__off_"\|\|\1\.mode==="task-notification"',
        data,
    )
    if m:
        new = m.group(0)
        old = new.replace(b'"__off_"', b'"prompt"')
        return old, new
    raise PatchError(
        "could not locate query.ts mid-turn removeFromQueue filter. "
        "Source structure may have changed; re-derive against src/query.ts."
    )


LOCATORS = [
    ("PATCH #1 INLINE_NOTIFICATION_MODES", locate_patch_1),
    ("PATCH #2 processQueueIfReady",       locate_patch_2),
    ("PATCH #3 query.ts mid-turn remove",  locate_patch_3),
]

with open(binary_path, "rb") as f:
    data = f.read()

# Resolve all patches up front. If any locator fails, abort before touching
# the binary (so we never leave it half-patched).
resolved = []
for name, locator in LOCATORS:
    try:
        old, new = locator(data)
    except PatchError as e:
        sys.exit(f"{name}: {e}")
    if len(old) != len(new):
        sys.exit(f"{name}: length mismatch — old={len(old)}, new={len(new)}")
    resolved.append((name, old, new))

# Idempotency: if every patch's NEW already present (and OLD absent), bail.
already_applied = all(
    data.count(new) == 1 and data.count(old) == 0
    for _, old, new in resolved
)
if already_applied:
    print("[skip] binary already has all patches applied. Nothing to do.")
    sys.exit(0)

# First-time patch on this binary: snapshot pristine bytes.
if not os.path.exists(backup_path):
    shutil.copy2(binary_path, backup_path)
    print(f"[backup] saved pristine bytes to {backup_path}")
else:
    print(f"[backup] {backup_path} already exists — leaving as-is "
          "(it should be the pristine Anthropic-signed bytes from before "
          "the first patch).")

for name, old, new in resolved:
    n_old = data.count(old)
    n_new = data.count(new)
    if n_new == 1 and n_old == 0:
        print(f"  ✓ {name}: already applied, skipping")
        continue
    if n_old != 1:
        sys.exit(
            f"{name}: expected exactly 1 occurrence of {old!r} in the binary, "
            f"found {n_old}. The locator found a candidate but uniqueness "
            "isn't satisfied — manual investigation needed."
        )
    data = data.replace(old, new)
    print(f"  ✓ applied {name}")

with open(binary_path, "wb") as f:
    f.write(data)
PY

# ── Re-sign ad-hoc (Anthropic's signature is now invalid) ────────────────────
# `--force` overwrites the existing (now-broken) signature.
# Empty `--sign -` means ad-hoc — no developer identity needed.
# `--preserve-metadata=entitlements` keeps any hardened-runtime entitlements
# that came with the original binary.
echo
echo "Re-signing ad-hoc..."
codesign --force --sign - --preserve-metadata=entitlements "$BINARY" 2>&1

# ── Smoke-test ───────────────────────────────────────────────────────────────
echo
echo "Verifying..."
"$CLAUDE_LAUNCHER" --version
echo
echo "Done. The standard 'claude' command now uses the patched binary."
echo "On the next Claude Code auto-update, re-run this script to re-patch:"
echo "    $0"
