#!/usr/bin/env bash
#
# claude-session-start-repatch.sh
#
# SessionStart hook (matcher: startup). Detects whether the active Claude Code
# binary has the noqueue patches applied and, if not, runs the repatch script
# to re-apply them.
#
# Detection is in-binary: greps for the tautology `q.mode===q.mode` introduced
# by patch #2. That sequence cannot occur naturally — no minifier emits it —
# so its presence is a reliable "this binary is patched" signal that travels
# with the binary itself. No sentinel file to drift out of sync.
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

# Fast path: patched already → exit silently. Grep on a 200MB file is <10ms.
if grep -q 'q.mode===q.mode' "$BINARY"; then
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
