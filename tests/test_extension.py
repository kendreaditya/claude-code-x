"""Extension / edge-case tests for the ccx engine (M0-M3 robustness).

Covers: version gating, container gating, absent anchor, ambiguous anchor,
partial-state apply, _splice drift guard, revert --all, and graceful detect
errors. Self-skips if the pristine binary isn't present.

Run: python3 tests/test_extension.py [pristine]
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccx import engine, sign
from ccx.anchors import OpState, ResolvedEdit
from ccx.detect import detect
from ccx.manifest import MANIFEST_DIR
from ccx.patchdef import (PatchDef, container_compatible, load_one,
                          version_compatible)

PRISTINE_DEFAULT = Path.home() / ".local/share/claude/versions/2.1.158.unpatched"
PROFILE = "test-ext"
_fail = 0


def check(cond, msg):
    global _fail
    print(("PASS" if cond else "FAIL") + ": " + msg)
    if not cond:
        _fail += 1


def _pd(d):
    return PatchDef(path=Path("/tmp/x.json"), data=d)


def test_gating():
    base = {"id": "g", "name": "g", "group": "behavior",
            "operations": [], "applies_to": {}}
    check(version_compatible(_pd({**base, "applies_to": {"version_range": ">=2.1.0 <3.0.0"}}), "2.1.158"),
          "version in range accepted")
    check(not version_compatible(_pd({**base, "applies_to": {"version_range": ">=3.0.0"}}), "2.1.158"),
          "future version range rejected")
    check(not version_compatible(_pd({**base, "applies_to": {"version_range": "<2.1.0"}}), "2.1.158"),
          "too-old range rejected")
    check(container_compatible(_pd({**base, "applies_to": {"containers": ["macho-arm64-bun", "elf-x64-bun"]}}), "macho-arm64"),
          "matching container accepted")
    check(not container_compatible(_pd({**base, "applies_to": {"containers": ["elf-x64-bun"]}}), "macho-arm64"),
          "non-matching container rejected")
    check(container_compatible(_pd({**base, "applies_to": {}}), "macho-arm64"),
          "no containers declared => accept all")


def test_anchor_states(copy: Path):
    data = copy.read_bytes()
    # absent anchor
    absent = _pd({"id": "absent", "name": "a", "group": "x",
                  "operations": [{"op_id": "o", "kind": "landmark-anchored",
                                  "anchor": "THIS_STRING_DOES_NOT_EXIST_ANYWHERE_42",
                                  "replace": "THIS_STRING_DOES_NOT_EXIST_ANYWHERE_43",
                                  "patched_anchor": "THIS_STRING_DOES_NOT_EXIST_ANYWHERE_43",
                                  "same_length": True, "must_be_unique": True, "in_bun_region": True}]})
    r = engine.resolve(absent, data)
    check(r.state == "absent" and not r.applicable, "absent anchor => state absent, not applicable")

    # ambiguous anchor (a very common byte sequence, must_be_unique)
    amb = _pd({"id": "amb", "name": "a", "group": "x",
               "operations": [{"op_id": "o", "kind": "landmark-anchored",
                               "anchor": "function", "replace": "function",
                               "patched_anchor": "ZZZ", "same_length": True,
                               "must_be_unique": True, "in_bun_region": True}]})
    r = engine.resolve(amb, data)
    check(r.state == "ambiguous" and not r.applicable, "non-unique anchor => ambiguous, not applicable")


def test_partial_state(copy: Path, fifo: PatchDef):
    # apply only op1 by hand, then resolve full FIFO -> partial
    data = bytearray(copy.read_bytes())
    op1 = fifo.operations[0]
    import re
    m = re.search(op1["anchor"].encode(), data)
    new = m.expand(op1["replace"].encode())
    data[m.start():m.start() + len(m.group(0))] = new
    copy.write_bytes(bytes(data))
    r = engine.resolve(fifo, copy.read_bytes())
    states = {o.state for o in r.ops}
    check(OpState.APPLIED in states and OpState.UNPATCHED in states and r.state == "partial",
          f"hand-applied op1 => partial state ({r.state})")
    # validate_on_copy should still report applies True (completes the rest)
    t = detect(str(copy))
    res = engine.validate_on_copy(fifo, t)
    check(res["applies"] and res["launch_ok"], "partial -> validate completes remaining ops + launches")


def test_splice_guard():
    buf = bytearray(b"hello world")
    bad = ResolvedEdit(op_id="o", offset=0, old_bytes=b"XXXXX", new_bytes=b"YYYYY", module_index=0)
    try:
        engine._splice(buf, [bad])
        check(False, "_splice should raise on byte drift")
    except engine.PatchError:
        check(True, "_splice raises PatchError when bytes changed under us")


def test_revert_all(copy: Path, fifo: PatchDef):
    shutil.copy2(PRISTINE_DEFAULT, copy) if PRISTINE_DEFAULT.exists() else None
    if sys.platform == "darwin":
        sign.resign(copy, "macho-arm64")
    t = detect(str(copy))
    mf = MANIFEST_DIR / f"{PROFILE}.json"
    if mf.exists():
        mf.unlink()
    engine.apply_patch(fifo, t, profile=PROFILE)
    from ccx.manifest import Manifest
    ids = Manifest.open(PROFILE).applied_ids()
    check(ids == ["fifo-steering-queue"], "manifest records applied patch")
    rep = engine.revert_patch("fifo-steering-queue", t, profile=PROFILE)
    check(rep["result"] == "reverted" and rep["launch_ok"], "revert ok + launches")
    check(Manifest.open(PROFILE).applied_ids() == [], "manifest cleared after revert")
    if mf.exists():
        mf.unlink()


def test_detect_errors():
    try:
        detect("/no/such/binary/anywhere")
        check(False, "detect should raise on missing file")
    except FileNotFoundError:
        check(True, "detect raises FileNotFoundError on missing target")


def main(pristine: Path) -> int:
    test_gating()
    test_splice_guard()
    test_detect_errors()
    if not pristine.exists():
        print(f"SKIP binary-dependent tests: {pristine} not found")
        return 1 if _fail else 0
    fifo = load_one("fifo-steering-queue")
    with tempfile.TemporaryDirectory() as td:
        copy = Path(td) / "claude"
        shutil.copy2(pristine, copy)
        copy.chmod(0o755)
        if sys.platform == "darwin":
            sign.resign(copy, "macho-arm64")
        test_anchor_states(copy)
        test_partial_state(copy, fifo)
        test_revert_all(copy, fifo)
    print(f"\n{'ALL EXTENSION TESTS PASSED' if not _fail else f'{_fail} FAILURE(S)'}")
    return 1 if _fail else 0


if __name__ == "__main__":
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else PRISTINE_DEFAULT
    sys.exit(main(p))
