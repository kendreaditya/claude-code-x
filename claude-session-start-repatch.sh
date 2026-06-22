#!/usr/bin/env bash
#
# claude-session-start-repatch.sh
#
# SessionStart hook (matcher: startup). Detects whether the active Claude Code
# binary has the noqueue patches applied and, if not, runs the repatch script
# to re-apply them.
#
# Detection is in-binary: scans for the tautology `<var>.mode===<var>.mode`
# introduced by patch #2, where <var> is whatever the minifier currently
# names the loop variable (it churns release-to-release — 'q' on 2.1.158,
# 't' on 2.1.185 — so the check must not hardcode a name). That sequence
# cannot occur naturally — no minifier emits it — so its presence is a
# reliable "this binary is patched" signal that travels with the binary
# itself. No sentinel file to drift out of sync.
#
# A plain `grep -q 'q.mode===q.mode'` only catches the one variable name it
# hardcodes, and a naive backreference regex search in Python (re.search
# over the whole 200MB file) takes ~5s — too slow for a SessionStart hook.
# So we do a fast literal scan for the much rarer fixed substring `.mode===`
# (C-level bytes.find, same speed class as grep) and only do the cheap
# backreference comparison at the handful of candidate offsets it finds.
#
# Failure mode is intentionally non-blocking: SessionStart exit codes can
# block the session, so on patch failure we log + warn but exit 0 so the
# user's session still starts.

set -euo pipefail

BINARY="$(readlink ~/.local/bin/claude)"
LOG=/tmp/claude-repatch.log

# Recursion guard — `claude -p` spawned from here would re-enter this hook.
if [[ "${CLAUDE_REPATCH_INFLIGHT:-}" == "1" ]]; then
  exit 0
fi

# Fast path: patched already → exit silently.
if python3 - "$BINARY" <<'PY'
import sys
data = open(sys.argv[1], "rb").read()
target = b".mode==="
ident = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$0123456789")
start = 0
while True:
    idx = data.find(target, start)
    if idx == -1:
        sys.exit(1)
    k = idx
    while k > 0 and data[k - 1] in ident:
        k -= 1
    var = data[k:idx]
    after = idx + len(target)
    if var and data[after:after + len(var)] == var and data[after + len(var):after + len(var) + 5] == b".mode":
        sys.exit(0)
    start = idx + 1
PY
then
  exit 0
fi

# Unpatched binary detected (probably an auto-update). Apply.
echo "[repatch] $(basename "$BINARY") is unpatched — applying noqueue patches" >&2
if CLAUDE_REPATCH_INFLIGHT=1 ~/.config/scripts/repatch-claude-noqueue.sh >"$LOG" 2>&1; then
  echo "[repatch] applied successfully" >&2
else
  echo "[repatch] FAILED — see $LOG" >&2
  echo "[repatch] (the script's byte fingerprints may need re-deriving for this release)" >&2
fi
exit 0
