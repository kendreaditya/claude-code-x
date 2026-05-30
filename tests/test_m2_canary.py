"""M2 canary: prove plaintext JS in a CJS module region is the executed path.

Patches only the plaintext occurrence of a user-facing --help string on a sandbox
copy, re-signs, and asserts the runtime --help output changes. Reproduces
docs/M2-bytecode-finding.md.

Run: python3 tests/test_m2_canary.py [path-to-pristine-binary]
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PRISTINE_DEFAULT = Path.home() / ".local/share/claude/versions/2.1.158.unpatched"
TARGET = b"Claude Code - starts an interactive session by default"


def main(pristine: Path) -> int:
    if not pristine.exists():
        print(f"SKIP: pristine binary not found at {pristine}")
        return 0
    with tempfile.TemporaryDirectory() as td:
        copy = Path(td) / "claude-canary"
        copy.write_bytes(pristine.read_bytes())
        data = bytearray(copy.read_bytes())
        locs = [m.start() for m in re.finditer(re.escape(TARGET), data)]
        plain = [o for o in locs if data[o - 2:o] == b'("']
        assert plain, f"plaintext occurrence not found (locs={locs})"
        off = plain[0]
        new = b"PLAINTEXT-JS-EXECUTES" + b" " * (len(TARGET) - 21)
        assert len(new) == len(TARGET)
        data[off:off + len(TARGET)] = new
        copy.write_bytes(data)
        copy.chmod(0o755)
        if sys.platform == "darwin":
            subprocess.run(["codesign", "--force", "--sign", "-",
                            "--preserve-metadata=entitlements", str(copy)],
                           check=True, capture_output=True)
        out = subprocess.run([str(copy), "--help"], capture_output=True, text=True,
                             timeout=60, env={**os.environ, "CLAUDIUS_INFLIGHT": "1"})
        if "PLAINTEXT-JS-EXECUTES" in out.stdout:
            print("PASS: plaintext JS edit changed runtime --help output")
            return 0
        print("FAIL: runtime output did not reflect the plaintext edit")
        print(out.stdout[:300])
        return 1


if __name__ == "__main__":
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else PRISTINE_DEFAULT
    sys.exit(main(p))
