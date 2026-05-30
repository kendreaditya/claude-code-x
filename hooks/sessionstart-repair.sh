#!/usr/bin/env bash
#
# ccx SessionStart repair hook (M3).
#
# Claude Code auto-updates write a NEW, unpatched versioned binary. This hook
# reconciles the ccx manifest against the current binary on session start by
# idempotently re-applying the recorded patch set. It re-resolves anchors fresh,
# so it patches the NEW version correctly; if anchors no longer resolve (upstream
# restructure), `ccx apply` reports not-applicable and this hook does NOT loop.
#
# Hardening (addresses the design review):
#   * single recursion guard env var: CLAUDIUS_INFLIGHT
#   * fast-path skip when the binary is unchanged since last reconcile (no 200MB
#     scan every session)
#   * hard per-binary attempt cap (no repatch fork-bomb when apply keeps failing)
#   * always exit 0 (SessionStart non-blocking) — warn on failure, never block
#   * no fragile grep sentinel: the MANIFEST is the source of truth

set -uo pipefail

# 1. recursion guard — any `claude`/ccx launch from here must not re-enter
[[ "${CLAUDIUS_INFLIGHT:-}" == "1" ]] && exit 0

# 2. resolve ccx (installed entrypoint, else module form)
if command -v ccx >/dev/null 2>&1; then
  CCX=(ccx)
elif [[ -n "${CCX_REPO:-}" && -d "${CCX_REPO}" ]]; then
  CCX=(python3 -m ccx)
  cd "${CCX_REPO}" || exit 0
else
  exit 0
fi

STATE="${TMPDIR:-/tmp}/ccx-repair.state"
ATTEMPTS="${TMPDIR:-/tmp}/ccx-repair.attempts"
LOG="${TMPDIR:-/tmp}/ccx-repair.log"

BIN="$(readlink -f "$HOME/.local/bin/claude" 2>/dev/null)" || exit 0
[[ -f "$BIN" ]] || exit 0

# binary fingerprint = mtime-size (cheap; changes on every update/patch)
sig="$(stat -f '%m-%z' "$BIN" 2>/dev/null || stat -c '%Y-%s' "$BIN" 2>/dev/null)"

# 3. fast path: already reconciled this exact binary
if [[ -f "$STATE" && "$(cat "$STATE" 2>/dev/null)" == "$sig" ]]; then
  exit 0
fi

# 4. per-binary attempt cap (reset on success below)
n=$(cat "$ATTEMPTS" 2>/dev/null || echo 0)
[[ "$n" =~ ^[0-9]+$ ]] || n=0
if [[ "$n" -ge 3 ]]; then
  echo "[ccx] repair attempt cap reached for $(basename "$BIN") — see $LOG" >&2
  exit 0
fi
echo $((n + 1)) >"$ATTEMPTS"

# 5. reconcile (idempotent; skips already-applied; re-resolves anchors fresh)
if CLAUDIUS_INFLIGHT=1 "${CCX[@]}" apply --from-manifest -y >"$LOG" 2>&1; then
  echo "$sig" >"$STATE"
  : >"$ATTEMPTS"
  echo "[ccx] patches reconciled for $(basename "$BIN")" >&2
else
  echo "[ccx] reconcile failed — see $LOG" >&2
fi
exit 0
