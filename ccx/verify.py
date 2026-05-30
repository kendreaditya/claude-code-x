"""Post-apply verification.

NOT file-size equality — re-signing rebuilds __LINKEDIT and changes total size on
every run (verified: patched 2.1.158 is ~1.25 MB smaller than the original
Team-signed binary). We verify instead via:
  * marker / patched bytes present where expected
  * Bun trailer offset unchanged vs pre-apply (the JS region didn't shift)
  * codesign --verify passes
  * launch smoke test (`<binary> --version` exits 0 and prints a version)
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .detect import BUN_TRAILER
from .sign import verify_signature


@dataclass
class VerifyResult:
    ok: bool
    checks: dict
    detail: str


def trailer_offset(data: bytes) -> int:
    return data.rfind(BUN_TRAILER)


def smoke_launch(binary: Path) -> tuple[bool, str]:
    try:
        out = subprocess.run(
            [str(binary), "--version"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "CLAUDIUS_INFLIGHT": "1"},
        )
        ok = out.returncode == 0 and bool(re.search(r"\d+\.\d+\.\d+", out.stdout))
        return ok, (out.stdout.strip() or out.stderr.strip())
    except Exception as e:  # noqa: BLE001
        return False, f"launch raised: {e}"


def verify_patched(binary: Path, container: str, expected_patched: list[bytes],
                   expected_trailer: int | None) -> VerifyResult:
    data = binary.read_bytes()
    checks: dict = {}

    # 1. patched bytes present
    missing = [p[:24] for p in expected_patched if data.count(p) < 1]
    checks["patched_bytes_present"] = not missing

    # 2. trailer stable (JS region not shifted)
    if expected_trailer is not None:
        checks["trailer_stable"] = (trailer_offset(data) == expected_trailer)

    # 3. signature
    sig_ok, sig_detail = verify_signature(binary, container)
    checks["signature_valid"] = sig_ok

    # 4. launch
    launch_ok, launch_detail = smoke_launch(binary)
    checks["launch_ok"] = launch_ok

    ok = all(v for v in checks.values())
    detail = f"sig={sig_detail}; launch={launch_detail}"
    if missing:
        detail = f"missing patched bytes: {missing}; " + detail
    return VerifyResult(ok=ok, checks=checks, detail=detail)
