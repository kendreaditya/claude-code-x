#!/usr/bin/env bash
# Run the ccx test suite. Tests self-skip if the pristine binary isn't present.
set -uo pipefail
cd "$(dirname "$0")/.."
PRISTINE="${1:-$HOME/.local/share/claude/versions/2.1.158.unpatched}"
rc=0
echo "== M2 canary =="
python3 tests/test_m2_canary.py "$PRISTINE" || rc=1
echo
echo "== engine end-to-end =="
python3 tests/test_engine.py "$PRISTINE" || rc=1
echo
echo "== extension / edge cases =="
python3 tests/test_extension.py "$PRISTINE" || rc=1
exit $rc
