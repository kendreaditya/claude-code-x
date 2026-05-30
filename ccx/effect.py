"""M2: runtime-effect verification.

We proved (docs/M2-bytecode-finding.md) that plaintext JS in a CJS module region
is the executed path. This module classifies a patch's runtime status:

  * effect-verified           — patch declares an `effect_probe` and it passed
  * module-execution-confirmed — no headless probe, but all edits land in a CJS
                                 module region (proven-executing plaintext)
  * unverified                — edits land outside any module region
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .anchors import ResolvedEdit
from .region import enumerate_modules, owning_module


def run_cli_probe(binary: Path, probe: dict) -> tuple[bool, str]:
    """probe = {kind:'cli-output', args:[...], expect_present?:str, expect_absent?:str}"""
    args = probe.get("args", ["--help"])
    try:
        out = subprocess.run(
            [str(binary), *args], capture_output=True, text=True, timeout=60,
            env={**os.environ, "CLAUDIUS_INFLIGHT": "1"},
        )
    except Exception as e:  # noqa: BLE001
        return False, f"probe launch failed: {e}"
    blob = (out.stdout or "") + (out.stderr or "")
    present = probe.get("expect_present")
    absent = probe.get("expect_absent")
    ok = True
    detail = []
    if present is not None:
        hit = present in blob
        ok &= hit
        detail.append(f"present({present!r})={hit}")
    if absent is not None:
        gone = absent not in blob
        ok &= gone
        detail.append(f"absent({absent!r})={gone}")
    return ok, "; ".join(detail) or "no assertions"


def classify(binary: Path, edits: list[ResolvedEdit], probe: dict | None) -> tuple[str, str]:
    if probe and probe.get("kind") == "cli-output":
        ok, detail = run_cli_probe(binary, probe)
        return ("effect-verified" if ok else "effect-FAILED", detail)
    # No headless probe: confirm edits are in executing plaintext modules.
    data = binary.read_bytes()
    mods = enumerate_modules(data)
    in_region = all(owning_module(mods, e.offset) is not None for e in edits)
    if in_region:
        why = probe.get("note", "interactive-only behavior") if probe else "no probe declared"
        return ("module-execution-confirmed", f"all edits in CJS module region; {why}")
    return ("unverified", "one or more edits outside any module region")
