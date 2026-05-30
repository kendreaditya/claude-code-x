"""End-to-end engine test on a sandbox copy: detect -> apply -> status -> verify
bytes -> idempotent re-apply -> revert -> verify restored.

Run: python3 tests/test_engine.py [path-to-pristine-binary]
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccx import engine
from ccx.detect import detect
from ccx.manifest import MANIFEST_DIR
from ccx.patchdef import load_one

PRISTINE_DEFAULT = Path.home() / ".local/share/claude/versions/2.1.158.unpatched"
PROFILE = "test-engine"


def check(cond, msg):
    print(("PASS" if cond else "FAIL") + ": " + msg)
    if not cond:
        raise SystemExit(1)


def main(pristine: Path) -> int:
    if not pristine.exists():
        print(f"SKIP: pristine binary not found at {pristine}")
        return 0
    pd = load_one("fifo-steering-queue")
    check(pd is not None, "FIFO patch definition loads")
    with tempfile.TemporaryDirectory() as td:
        copy = Path(td) / "claude"
        copy.write_bytes(pristine.read_bytes())
        copy.chmod(0o755)

        t = detect(str(copy))
        check(t.version == "2.1.158", f"detect version ({t.version})")
        check(t.format_class == "native-bun-binary", "detect format")

        # clean test manifest
        mf = MANIFEST_DIR / f"{PROFILE}.json"
        if mf.exists():
            mf.unlink()

        rep = engine.apply_patch(pd, t, profile=PROFILE)
        check(rep["result"] == "applied", f"apply result ({rep['result']})")
        check(rep["edits"] == 3, f"3 edits applied ({rep.get('edits')})")
        check(rep["verify"]["launch_ok"], "patched binary launches")
        check(rep["verify"]["signature_valid"], "signature valid after patch")

        data = copy.read_bytes()
        check(data.count(b'new Set(["__off_","task-notification"])') == 1, "p1 applied")
        check(data.count(b"q.mode===q.mode") == 1, "p2 applied")
        check(data.count(b'new Set(["prompt","task-notification"])') == 0, "p1 old gone")

        # idempotent re-apply
        rep2 = engine.apply_patch(pd, t, profile=PROFILE)
        check(rep2["result"] == "already-applied", "re-apply is no-op")

        # revert
        rev = engine.revert_patch("fifo-steering-queue", t, profile=PROFILE)
        check(rev["result"] == "reverted", f"revert ({rev['result']})")
        check(rev["launch_ok"], "binary launches after revert")
        data2 = copy.read_bytes()
        check(data2.count(b'new Set(["prompt","task-notification"])') == 1, "p1 restored")
        check(data2.count(b"q.mode===q.mode") == 0, "p2 restored")

        if mf.exists():
            mf.unlink()
    print("\nALL ENGINE TESTS PASSED")
    return 0


if __name__ == "__main__":
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else PRISTINE_DEFAULT
    sys.exit(main(p))
